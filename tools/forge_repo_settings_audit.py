#!/usr/bin/env python
"""Audit des reglages GitHub qui GOUVERNENT une branche — ce que le clone ne voit pas.

POURQUOI. Avant de sortir une branche de la circulation (ici `main`, fige au
17/03/2026), la seule verification qui manque a l'audit local est cote SERVEUR :
branche par defaut, protections/rulesets, PR ouvertes, webhooks. Un clone n'en
sait rien ; supprimer une branche encore branche par defaut, protegee, ou cible
d'une PR ouverte casse une dependance invisible. Cet outil rend ces quatre faits.

Il REUTILISE la plomberie authentifiee de forge_ci_check (`_api` + `_creds`) :
meme token au coffre, memes en-tetes surs en redirection. Aucune ecriture — GET
uniquement. `_api`/`_creds` sont importes au niveau module pour rester
monkeypatchables (les tests NR fabriquent les reponses, zero reseau).

CLI :
    trusted_script path=tools/forge_repo_settings_audit.py \
        script_args="--repo Nokido-labs/nokido-private --branch main"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reutilise la couche HTTP+auth deja durcie (token vault, anti-fuite Authorization
# en redirection). Importes localement -> monkeypatchables dans les tests NR.
from nokido_agent.tools.forge_ci_check import API, _api, _creds  # noqa: E402


def _get(path, cred):
    """GET tolerant : rend (ok, payload). Un 404 n'est pas une panne — c'est un
    fait ('rien a cet endpoint'). Toute autre erreur est remontee comme motif,
    JAMAIS avalee en 'vide' (sinon une protection illisible passerait pour
    absente : exactement le faux-negatif a eviter)."""
    # forge_ci_check._api fait API + path : le '/' initial est OBLIGATOIRE,
    # sinon l'hote devient 'api.github.comrepos/...' -> getaddrinfo failed.
    if not path.startswith("/"):
        path = "/" + path
    try:
        return True, _api(path, cred)
    except Exception as e:  # noqa: BLE001 — on classe l'erreur, on ne la cache pas
        code = getattr(e, "code", None)
        if code == 404:
            return True, None
        return False, "%s: %s" % (type(e).__name__, str(e)[:200])


def audit(repo, branch="main"):
    """Rend un dict structure. Ne conclut pas a la place de l'owner : il EXPOSE
    les faits + un drapeau `bloqueurs` par item, l'owner tranche."""
    cred = _creds()
    if not cred:
        return {"ok": False, "motif": "aucun token GITHUB — audit impossible (ne PAS conclure 'rien ne depend de main')"}

    out = {"ok": True, "repo": repo, "branch": branch, "faits": {}, "bloqueurs": []}

    ok, repo_info = _get("repos/%s" % repo, cred)
    if not ok:
        return {"ok": False, "motif": repo_info}
    default_branch = (repo_info or {}).get("default_branch")
    is_default = default_branch == branch
    out["faits"]["default_branch"] = default_branch
    out["faits"]["est_branche_par_defaut"] = is_default
    if is_default:
        out["bloqueurs"].append(
            "'%s' est la BRANCHE PAR DEFAUT — la rebasculer (sur alpha) AVANT toute suppression" % branch)

    # Protection classique (404 = aucune) + rulesets (free tier).
    ok, prot = _get("repos/%s/branches/%s/protection" % (repo, branch), cred)
    protege_classique = bool(ok and prot)
    out["faits"]["protection_classique"] = protege_classique

    ok, rulesets = _get("repos/%s/rulesets" % repo, cred)
    rs_visant = []
    if ok and isinstance(rulesets, list):
        for rs in rulesets:
            # Le detail des conditions demande un 2e GET ; on remonte au moins nom+id.
            rs_id = rs.get("id")
            ok2, detail = _get("repos/%s/rulesets/%s" % (repo, rs_id), cred)
            refs = []
            if ok2 and isinstance(detail, dict):
                refs = (((detail.get("conditions") or {}).get("ref_name") or {}).get("include")) or []
            vise = any(branch in str(r) for r in refs) or (rs.get("target") == "branch" and not refs)
            if vise:
                rs_visant.append({"id": rs_id, "name": rs.get("name"), "enforcement": rs.get("enforcement"), "refs": refs})
    out["faits"]["rulesets_visant_branche"] = rs_visant
    if protege_classique or rs_visant:
        out["bloqueurs"].append(
            "'%s' est PROTEGE (classique=%s, rulesets=%d) — retirer la protection avant suppression"
            % (branch, protege_classique, len(rs_visant)))

    # PR ouvertes ayant la branche pour base OU pour tete.
    ok, pulls = _get("repos/%s/pulls?state=open&per_page=100" % repo, cred)
    pr_liees = []
    if ok and isinstance(pulls, list):
        for pr in pulls:
            base = ((pr.get("base") or {}).get("ref"))
            head = ((pr.get("head") or {}).get("ref"))
            if branch in (base, head):
                pr_liees.append({"num": pr.get("number"), "titre": pr.get("title"), "base": base, "head": head})
    out["faits"]["pr_ouvertes_total"] = len(pulls) if isinstance(pulls, list) else None
    out["faits"]["pr_liees_a_branche"] = pr_liees
    if pr_liees:
        out["bloqueurs"].append("%d PR ouverte(s) referencent '%s'" % (len(pr_liees), branch))

    # Webhooks (peut 403 si le token n'a pas admin:repo_hook -> on le DIT).
    ok, hooks = _get("repos/%s/hooks" % repo, cred)
    if not ok:
        out["faits"]["webhooks"] = "illisible (%s) — verifier a la main dans l'UI" % hooks
    else:
        out["faits"]["webhooks"] = [{"url": (h.get("config") or {}).get("url"), "active": h.get("active")}
                                    for h in (hooks or [])]

    return out


def _post(path, cred, payload):
    """POST authentifie (le GET vit dans forge_ci_check._api ; ici on ECRIT).
    Rend (ok, corps_ou_motif). Le corps d'un HTTPError est LU et remonte : une
    422 GitHub explique pourquoi le ruleset est refuse -- l'avaler ferait passer
    un refus pour un succes."""
    if not path.startswith("/"):
        path = "/" + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path, data=data, method="POST",
        headers={
            "Authorization": "Bearer %s" % cred,
            "Accept": "application/vnd.github+json",
            "User-Agent": "nokido-repo-audit",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:  # muet-ok : best-effort ; l'erreur principale est deja remontee (ok=False)
            pass
        return False, "%s: %s %s" % (type(e).__name__, str(e)[:200], detail)


# ANTI-ACCIDENT : bloque suppression et force-push, RIEN d'autre. Pas de
# pull_request (garderait le push direct impossible), pas de required_signatures
# (les commits ne sont pas signes GPG). Adapte a une branche de dev mono-dev en
# push direct qui est AUSSI la branche par defaut/release.
ANTI_ACCIDENT_RULES = [{"type": "deletion"}, {"type": "non_fast_forward"}]


def protect_branch(repo, branch, rules=None, name=None):
    """Pose un ruleset ANTI-ACCIDENT ciblant `branch`. Idempotent : si un ruleset
    du meme nom existe deja, ne re-poste pas (rend deja_present=True). Ne conclut
    au succes que sur reponse serveur -- token absent ou POST refuse -> ok False."""
    rules = rules if rules is not None else ANTI_ACCIDENT_RULES
    name = name or ("%s-protection-antiaccident" % branch)
    cred = _creds()
    if not cred:
        return {"ok": False, "motif": "aucun token GITHUB — protection NON posee"}

    ok, existing = _get("repos/%s/rulesets" % repo, cred)
    if ok and isinstance(existing, list):
        for rs in existing:
            if rs.get("name") == name:
                return {"ok": True, "deja_present": True,
                        "ruleset": {"id": rs.get("id"), "name": name}}

    payload = {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/heads/%s" % branch], "exclude": []}},
        "rules": rules,
        "bypass_actors": [],
    }
    ok, resp = _post("repos/%s/rulesets" % repo, cred, payload)
    if not ok:
        return {"ok": False, "motif": resp}
    return {"ok": True, "deja_present": False,
            "ruleset": {"id": resp.get("id"), "name": resp.get("name"),
                        "enforcement": resp.get("enforcement")}}


def _write(path, cred, payload, method):
    """Ecriture authentifiee (PATCH/PUT). Rend (ok, corps_ou_motif) ; le corps
    d'un HTTPError est LU et remonte (une 403 explique le scope manquant)."""
    if not path.startswith("/"):
        path = "/" + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": "Bearer %s" % cred,
            "Accept": "application/vnd.github+json",
            "User-Agent": "nokido-repo-audit",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:  # muet-ok : best-effort, l'erreur principale est deja remontee
            pass
        return False, "%s: %s %s" % (type(e).__name__, str(e)[:200], detail)


def set_meta(repo, description=None, homepage=None, topics=None):
    """Corrige les metadonnees GitHub-facing (About + topics). Scope admin requis
    -> une 403 est remontee, jamais avalee. Ne touche que les champs fournis."""
    cred = _creds()
    if not cred:
        return {"ok": False, "motif": "aucun token GITHUB"}
    res = {"ok": True, "repo": repo, "applied": {}}
    body = {}
    if description is not None:
        body["description"] = description
    if homepage is not None:
        body["homepage"] = homepage
    if body:
        ok, r = _write("repos/%s" % repo, cred, body, "PATCH")
        res["applied"]["about"] = {"ok": ok,
                                   "detail": {k: (r or {}).get(k) for k in body} if ok else r}
        res["ok"] = res["ok"] and ok
    if topics is not None:
        ok, r = _write("repos/%s/topics" % repo, cred, {"names": topics}, "PUT")
        res["applied"]["topics"] = {"ok": ok,
                                    "detail": (r.get("names") if ok and isinstance(r, dict) else r)}
        res["ok"] = res["ok"] and ok
    return res


def meta(repo):
    """Audit des metadonnees GITHUB-FACING (ce qui s'affiche publiquement) : About
    (description/homepage/topics/visibilite/licence/archived), releases, profil
    community (= l'onglet Security-overview : SECURITY.md, CoC, CONTRIBUTING...),
    et tags distants. GET-only. Sert a reperer le faux/perime/manquant/mal-nomme."""
    cred = _creds()
    if not cred:
        return {"ok": False, "motif": "aucun token GITHUB — audit meta impossible"}
    out = {"ok": True, "repo": repo}

    ok, r = _get("repos/%s" % repo, cred)
    if not ok:
        return {"ok": False, "motif": r}
    r = r or {}
    lic = r.get("license")
    out["about"] = {
        "description": r.get("description"),
        "homepage": r.get("homepage"),
        "topics": r.get("topics"),
        "visibility": r.get("visibility"),
        "archived": r.get("archived"),
        "disabled": r.get("disabled"),
        "default_branch": r.get("default_branch"),
        "license": (lic or {}).get("spdx_id") if isinstance(lic, dict) else lic,
        "has_wiki": r.get("has_wiki"),
        "has_pages": r.get("has_pages"),
        "has_issues": r.get("has_issues"),
        "open_issues": r.get("open_issues_count"),
        "pushed_at": r.get("pushed_at"),
    }

    ok, rel = _get("repos/%s/releases?per_page=100" % repo, cred)
    if ok and isinstance(rel, list):
        out["releases"] = [{"tag": x.get("tag_name"), "name": x.get("name"),
                            "draft": x.get("draft"), "prerelease": x.get("prerelease"),
                            "created": x.get("created_at"), "assets": len(x.get("assets") or [])}
                           for x in rel]
    else:
        out["releases"] = rel if ok else ("illisible: %s" % rel)

    ok, cp = _get("repos/%s/community/profile" % repo, cred)
    if ok and isinstance(cp, dict):
        f = cp.get("files") or {}
        out["community"] = {
            "health_pct": cp.get("health_percentage"),
            "files_present": {k: bool(f.get(k)) for k in
                              ("readme", "license", "code_of_conduct", "contributing",
                               "security_policy", "issue_template", "pull_request_template")},
        }
    else:
        out["community"] = "illisible: %s" % (cp if not ok else "forme inattendue")

    ok, tags = _get("repos/%s/tags?per_page=100" % repo, cred)
    out["tags_remote"] = [t.get("name") for t in tags] if (ok and isinstance(tags, list)) \
        else ("illisible: %s" % tags)
    return out


def _fmt(a):
    if not a.get("ok"):
        return "[audit] IMPOSSIBLE : %s" % a.get("motif")
    lignes = ["[audit] %s @ branche '%s'" % (a["repo"], a["branch"])]
    f = a["faits"]
    lignes.append("  branche par defaut      : %s%s" % (f.get("default_branch"),
                  "  <-- C'EST la branche auditee" if f.get("est_branche_par_defaut") else ""))
    lignes.append("  protection classique    : %s" % f.get("protection_classique"))
    lignes.append("  rulesets visant branche : %d" % len(f.get("rulesets_visant_branche") or []))
    for rs in (f.get("rulesets_visant_branche") or []):
        lignes.append("      - #%s %s (%s) refs=%s" % (rs["id"], rs["name"], rs["enforcement"], rs["refs"]))
    lignes.append("  PR ouvertes (total)     : %s" % f.get("pr_ouvertes_total"))
    for pr in (f.get("pr_liees_a_branche") or []):
        lignes.append("      - #%s %s  (base=%s head=%s)" % (pr["num"], pr["titre"], pr["base"], pr["head"]))
    wh = f.get("webhooks")
    lignes.append("  webhooks                : %s" % (wh if isinstance(wh, str) else len(wh)))
    if isinstance(wh, list):
        for h in wh:
            lignes.append("      - %s (active=%s)" % (h["url"], h["active"]))
    if a["bloqueurs"]:
        lignes.append("  BLOQUEURS AVANT SUPPRESSION :")
        for b in a["bloqueurs"]:
            lignes.append("      ! %s" % b)
    else:
        lignes.append("  aucun bloqueur cote serveur -> suppression sure (apres archive/*)")
    return "\n".join(lignes)


def main():
    ap = argparse.ArgumentParser(description="Audit reglages GitHub gouvernant une branche")
    ap.add_argument("--repo", default="Nokido-labs/nokido-private")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply-protection", action="store_true",
                    help="pose le ruleset anti-accident (deletion + non_fast_forward) sur --branch")
    ap.add_argument("--meta", action="store_true",
                    help="audit des metadonnees GitHub-facing (About/topics/releases/security/tags)")
    ap.add_argument("--set-description")
    ap.add_argument("--set-homepage")
    ap.add_argument("--set-topics", help="liste separee par des virgules (REMPLACE tous les topics)")
    args = ap.parse_args()
    if args.set_description is not None or args.set_homepage is not None or args.set_topics is not None:
        topics = [t.strip() for t in args.set_topics.split(",") if t.strip()] if args.set_topics is not None else None
        r = set_meta(args.repo, description=args.set_description, homepage=args.set_homepage, topics=topics)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1
    if args.meta:
        r = meta(args.repo)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1
    if args.apply_protection:
        r = protect_branch(args.repo, args.branch)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1
    a = audit(args.repo, args.branch)
    print(json.dumps(a, ensure_ascii=False, indent=2) if args.json else _fmt(a))
    return 0 if a.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
