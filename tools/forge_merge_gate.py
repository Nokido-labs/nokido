#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_merge_gate.py -- porte de merge wip/<agent> -> alpha, jugee sur le GAIN.

Brique 2 du flux "agent = producteur de patch" (brief isolation multi-agents). Un
agent autonome edite dans son worktree (branche wip/<agent>, cf forge_worktree) ;
ce module DECIDE si ce travail entre dans le canonique. Il MESURE alpha (baseline)
et le worktree (candidat) sur la MEME suite de tests, puis juge le GAIN. Merge
SEULEMENT si AMELIORE ; NEUTRE / DEGRADE / regression = REJET (le wip reste pour
revue). Un patch vert-mais-sans-gain n'entre PAS (reserve owner 2026-07-30).

ANTI-DUP : reutilise forge_worktree (route) et forge_mutation_judge (mesurer,
juger_gain). Ne reimplemente NI la mesure NI le juge.

Le reload du hub apres un merge reste ACTION OWNER (binding MCP coupe + surfaces
actives) : ce module le PROPOSE, ne le declenche jamais.

Owner-run (git). dry-run par defaut : aucun merge sans --apply.

Usage :
    forge_merge_gate.py --agent gemini            # evalue (dry-run)
    forge_merge_gate.py --agent gemini --apply    # merge si AMELIORE
    forge_merge_gate.py --agent gemini --tests tests/nr/test_x.py ...
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : porte de merge wip vers alpha, jugee sur le gain"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


def _git(args, cwd=None):
    r = subprocess.run(["git", "-c", "safe.directory=*", *args],
                       cwd=str(cwd or ROOT), capture_output=True, text=True,
                       errors="replace", timeout=120)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def suite_nr(explicit=None):
    """Suite d'invariants : les tests NR (tests/nr/*.py). Override explicite possible."""
    if explicit:
        return explicit
    return sorted(str(Path(p).relative_to(ROOT)).replace("\\", "/")
                  for p in glob.glob(str(ROOT / "tests" / "nr" / "test_*.py")))


def _wip_branch(agent):
    return "wip/%s" % agent.lower()


JOURNAL_ARENE = ROOT / "sandbox" / "arene_promotion_observe.jsonl"


def _observer_arene(ev):
    """Avis de l'arene darwinienne sur chaque .py du wip, en OBSERVATION (owner 19/10).

    Ne bloque jamais et n'ecrit pas dans darwinian_arena.db : on rejoue son scan AST et sa
    regle de promotion (3 tests synthetiques minimum, qu'un merge n'a pas). Mesure du 19/10 :
    le scan refuse 96 % des modules forge_* -- ce journal chiffre l'inadequation.
    """
    rc, out, _ = _git(["diff", "--name-only", "alpha...%s" % ev["branch"]])
    py = [l for l in out.splitlines() if l.endswith(".py")] if rc == 0 else []
    return _avis_arene([(rel, _git(["show", "%s:%s" % (ev["branch"], rel)])[1]) for rel in py],
                       {"branch": ev["branch"]})


def _avis_arene(fichiers_contenus, provenance: dict) -> dict:
    """Scan AST + regle de promotion de l'arene sur des (fichier, contenu) .py, journalises en OBSERVATION. Jamais
    bloquant. 19/10 : aussi appele par la reconciliation -- l'arene n'avait vu AUCUNE integration reelle."""
    fichiers = []
    for rel, contenu in fichiers_contenus:
        try:
            from nokido_agent.app.forge_darwinian_arena import _ast_safety_scan
            sain, motif = _ast_safety_scan(contenu)
            verdict = "NON_PROMOUVABLE" if sain else "REFUS_AST"
            motif = "0/3 tests synthetiques" if sain else motif
        except Exception as e:  # arene illisible : INCONNU, jamais un refus ni un accord
            verdict, motif = "INCONNU", "%s: %s" % (type(e).__name__, str(e)[:120])
        fichiers.append({"fichier": rel, "verdict": verdict, "motif": motif})
    obs = {"mode": "observation", "fichiers": fichiers}
    try:
        JOURNAL_ARENE.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_ARENE, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(obs, **provenance), ensure_ascii=False) + "\n")
    except OSError as e:
        obs["journal"] = "non ecrit : %s" % e
    return obs


def evaluer(agent, tests=None):
    """Mesure baseline(alpha) vs candidat(worktree) et juge le GAIN. NE MERGE PAS."""
    from nokido_agent.tools.forge_worktree import route, ROOT as WT_CANON
    from nokido_agent.app.forge_mutation_judge import mesurer, juger_gain

    wt = route(agent)
    if wt == str(WT_CANON):
        return {"agent": agent, "verdict": "PAS_DE_WORKTREE",
                "pourquoi": "aucun worktree pour %s (create() jamais lance)" % agent}
    branch = _wip_branch(agent)
    rc, _, err = _git(["rev-parse", "--verify", branch])
    if rc != 0:
        return {"agent": agent, "verdict": "PAS_DE_BRANCHE",
                "pourquoi": "branche %s absente (%s)" % (branch, err[:120])}
    rc, ab, _ = _git(["rev-list", "--count", "alpha..%s" % branch])
    ahead = int(ab) if rc == 0 and ab.isdigit() else 0
    if ahead == 0:
        return {"agent": agent, "verdict": "RIEN_A_MERGER",
                "pourquoi": "%s n'a aucun commit au-dela d'alpha" % branch}

    # LE CANDIDAT NE SE JUGE PAS AVEC SES PROPRES TESTS (2026-10-01). `mesurer(tests, cwd=wt)`
    # execute les tests TELS QU'ILS SONT DANS LE WORKTREE : une branche qui affaiblit tests/nr,
    # ou glisse un conftest/addopts qui saute tout, passait verte. La zone de l'evaluateur
    # n'etait appliquee que par `mutable()` (mutation en place). Revue claude.ai
    # (mission_rsi_soif), verifiee dans le code. Hors zone, les tests du worktree SONT ceux
    # d'alpha : le candidat est juge par le juge d'alpha. Diff illisible -> on ne juge pas.
    from nokido_agent.app.forge_mutation_judge import zone_evaluateur_touchee

    rc, noms, err = _git(["diff", "--name-only", "alpha...%s" % branch])
    if rc != 0:
        return {"agent": agent, "branch": branch, "ahead": ahead, "verdict": "INDECIDABLE",
                "pourquoi": "diff alpha...%s illisible (%s) : la zone de l'evaluateur ne peut "
                            "pas etre verifiee, rien n'est juge" % (branch, (err or "")[:120])}
    touches = zone_evaluateur_touchee(noms.splitlines())
    if touches:
        return {"agent": agent, "branch": branch, "ahead": ahead,
                "verdict": "REFUSE_ZONE_EVALUATEUR", "zone_touchee": touches,
                "pourquoi": "le candidat modifie ce qui le juge (%s%s) : il se jugerait avec ses "
                            "propres tests -- revue OWNER, jamais un merge automatique"
                            % (", ".join(touches[:5]), " ..." if len(touches) > 5 else "")}

    tests = suite_nr(tests)
    baseline = mesurer(tests, cwd=str(WT_CANON))   # alpha (canonique)
    candidat = mesurer(tests, cwd=wt)              # worktree de l'agent
    g = juger_gain(baseline, candidat)
    return {"agent": agent, "branch": branch, "ahead": ahead,
            "tests_utilises": len(tests), "verdict": g["verdict"],
            "pourquoi": g["pourquoi"], "baseline": baseline, "candidat": candidat}


def merger(agent, tests=None, apply=False):
    """evaluer + merge wip->alpha SI AMELIORE et apply. Sinon rejet (wip conserve)."""
    ev = evaluer(agent, tests)
    ev["applique"] = False
    if ev.get("verdict") != "AMELIORE":
        ev["decision"] = "REJET (%s) -- le wip reste pour revue" % ev.get("verdict")
        return ev
    if apply:
        # PORTE DE L'EVOLUTION (2026-10-01) : appliquer est une mutation du canonique. Jugee AVANT tout appel git, y
        # compris la lecture de l'arene (312aa797c l'avait placee devant : porte fermee, git appele quand meme).
        from nokido_agent.app.forge_mutation_judge import evolution_autorisee

        porte = evolution_autorisee()
        if not porte["autorisee"]:
            ev["porte"] = porte
            ev["decision"] = "HALTED (%s) : %s -- le wip reste pour revue" % (porte["etat"], porte["motif"])
            return ev
    ev["arene"] = _observer_arene(ev)
    if not apply:
        ev["decision"] = "AMELIORE -- merge PROPOSE (dry-run ; relancer avec --apply)"
        return ev
    rc, head, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    if head != "alpha":
        ev["decision"] = "ABANDON : le canonique n'est pas sur alpha (HEAD=%s)" % head
        return ev
    rc, st, _ = _git(["status", "--porcelain"])
    if st:
        ev["decision"] = "ABANDON : working tree canonique non propre"
        return ev
    rc, out, err = _git(["merge", "--no-ff", "-m",
                         "merge(%s): patch juge AMELIORE via merge gate" % ev["branch"],
                         ev["branch"]])
    if rc != 0:
        ev["decision"] = "MERGE ECHOUE : %s" % (err or out)[:200]
        return ev
    ev["applique"] = True
    ev["decision"] = ("MERGE %s -> alpha (AMELIORE). RELOAD HUB = action OWNER "
                      "(binding MCP coupe, surfaces actives)." % ev["branch"])
    return ev


# ---------------------------------------------------------------------------------------------------------------
# RECONCILIATION (decision owner 18/10 : « reconciliateur seul d'abord »). Un commit d'executeur RELU entre dans alpha
# par ses seuls fichiers NOMMES par la tache : les restes balayes (90bc00bee, c4f627a9f : 8 fichiers pour 2 et 5) sont
# ecartes ET dits. La preuve d'un GREEN est son RED (tests nommes), pas un gain de duree. Owner-run, dry-run par defaut.
# Ce n'est pas une mutation autonome : le frein d'evolution ne la bloque pas.
# ---------------------------------------------------------------------------------------------------------------
def plan_reconciliation(fichiers_commit, fichiers_nommes) -> dict:
    c = [f.strip().replace("\\", "/") for f in fichiers_commit if f and f.strip()]
    n = [f.strip().replace("\\", "/") for f in fichiers_nommes if f and f.strip()]
    return {"a_integrer": [f for f in c if f in n], "hors_consigne": [f for f in c if f not in n],
            "manquants": [f for f in n if f not in c]}


def message_reconciliation(sha: str, agent: str, sujet: str) -> str:
    return "integre(%s): %s (reconcilie %s, fichiers nommes seuls)" % (agent, sujet or "livraison", sha)


def _motif_git(err: str, out: str = "") -> str:
    """La CAUSE d'un refus git n'est pas en tete du stderr : celle-ci porte les avertissements du statut (19/10, 0b8cc9ff4
    refuse avec pour seul motif « warning: could not open directory... Permission denied »), et le hook pre-commit ecrit
    la sienne sur STDOUT (132 736 car. de stderr, tous des avertissements). Borne dite."""
    brut = (out or "") + "\n" + (err or "")
    utiles = [l for l in brut.splitlines() if l.strip() and not l.startswith("warning:")]
    return "%s [%d car. au total]" % (("\n".join(utiles) or brut.strip())[-300:], len(brut.strip()))


def _remettre_alpha(fichiers, root) -> None:
    """Annule une extraction (meme partielle) : existant dans HEAD -> checkout HEAD ; NEUF -> rm (un checkout HEAD
    d'un fichier neuf echoue et le laisse dans l'arbre partage -- 9 fichiers le 19/10 ~17 h)."""
    existants = [f for f in fichiers if _git(["cat-file", "-e", "HEAD:" + f], root)[0] == 0]
    neufs = [f for f in fichiers if f not in existants]
    if neufs:
        _git(["rm", "-q", "-f", "--ignore-unmatch", "--"] + neufs, root)
    if existants:
        # l'INDEX d'abord (reset ne touche pas l'arbre) : tient meme quand l'ecriture d'un fichier est refusee
        # (MANIFESTO.md ecrit par le compte du hub, « unable to unlink », index neuf sur arbre ancien le 19/10 ~17 h)
        _git(["reset", "-q", "--"] + existants, root)
        _git(["checkout", "HEAD", "--"] + existants, root)


def reconcilier(sha, fichiers_nommes, apply=False, agent="?", sujet="", tests=None) -> dict:
    root = Path(__file__).resolve().parent.parent
    rc, out, err = _git(["show", "--name-only", "--format=", sha], root)
    if rc != 0:
        return {"sha": sha, "applique": False, "decision": "ABANDON : commit illisible (%s)" % (err or out)[:160]}
    plan = plan_reconciliation(out.splitlines(), fichiers_nommes)
    r = {"sha": sha, "plan": plan, "applique": False}
    if not plan["a_integrer"]:
        r["decision"] = "RIEN A INTEGRER : aucun fichier nomme dans le commit"
        return r
    if not apply:
        r["decision"] = "DRY-RUN : %d fichier(s) a integrer, %d ecarte(s) hors consigne" % (
            len(plan["a_integrer"]), len(plan["hors_consigne"]))
        return r
    rc, head, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if head != "alpha":
        r["decision"] = "ABANDON : le canonique n'est pas sur alpha (HEAD=%s)" % head
        return r
    rc, _, err = _git(["checkout", sha, "--"] + plan["a_integrer"], root)
    if rc != 0:
        _remettre_alpha(plan["a_integrer"], root)
        r["decision"] = "ABANDON : extraction refusee (%s) -- arbre remis a l'etat d'alpha" % _motif_git(err)
        return r
    return _achever(r, plan, root, tests, message_reconciliation(sha, agent, sujet), origine={"sha": sha})


def _achever(r, plan, root, tests, message, origine=None) -> dict:
    """Fin COMMUNE d'une integration (commit relu ou sauvegarde) : deja dans alpha, tests, commit, annulation atomique."""
    if _git(["diff", "--cached", "--quiet", "--"] + plan["a_integrer"], root)[0] == 0:
        # 19/10 : « nothing added to commit » lu COMMIT REFUSE, trois rejeux d'un rapport deja integre (71ff63262).
        r["decision"] = ("DEJA DANS ALPHA : %d fichier(s) identique(s) a HEAD, rien a committer"
                         % len(plan["a_integrer"]))
        return r
    if tests:
        t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + list(tests),
                           cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
        r["tests"] = (t.stdout.strip().splitlines() or [""])[-1]
        if t.returncode != 0:
            _remettre_alpha(plan["a_integrer"], root)
            r["decision"] = "REJET : tests rouges apres integration -- fichiers remis a l'etat d'alpha"
            return r
    rc, out, err = _git(["commit", "-q", "-m", message, "--"] + plan["a_integrer"], root)
    r["applique"] = rc == 0
    if rc != 0:
        _remettre_alpha(plan["a_integrer"], root)
    elif origine:
        py = [f for f in plan["a_integrer"] if f.endswith(".py")]
        r["arene"] = _avis_arene([(f, _git(["show", "HEAD:%s" % f], root)[1]) for f in py], dict(origine, integre=True))
    r["decision"] = ("INTEGRE" if rc == 0 else "COMMIT REFUSE : %s -- arbre remis a l'etat d'alpha"
                     % _motif_git(err, out))
    return r


def reconcilier_sauvegarde(dossier, fichiers_nommes, apply=False, agent="?", sujet="", tests=None, root=None) -> dict:
    """Integre une SAUVEGARDE d'executeur (sandbox/sauvegardes_executeurs/<agent>/<tache>/, manifeste.json) par les
    memes regles que `reconcilier` (19/10 : d31564f96 sauvait le travail, rien ne l'integrait -- 1ad5425fd recopie a
    la main)."""
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    d = Path(dossier)
    if not d.is_absolute():
        d = root / d    # jamais contre le cwd du hub (19/10 : manifeste « illisible », meme faute que 045efbda8)
    try:
        man = json.loads((d / "manifeste.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"sauvegarde": str(d), "applique": False, "decision": "ABANDON : manifeste illisible (%s)" % type(e).__name__}
    plan = plan_reconciliation(man.get("fichiers") or [], fichiers_nommes)
    r = {"sauvegarde": str(d), "tache": man.get("tache"), "plan": plan, "applique": False}
    absents = [f for f in plan["a_integrer"] if not (d / f).is_file()]
    if absents:
        r["decision"] = "ABANDON : %d fichier(s) nomme(s) absent(s) de la sauvegarde : %s" % (len(absents), absents)
        return r
    if not plan["a_integrer"]:
        r["decision"] = "RIEN A INTEGRER : aucun fichier nomme dans la sauvegarde"
        return r
    if not apply:
        r["decision"] = "DRY-RUN : %d fichier(s) a integrer, %d ecarte(s) hors consigne" % (
            len(plan["a_integrer"]), len(plan["hors_consigne"]))
        return r
    rc, head, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if head != "alpha":
        r["decision"] = "ABANDON : le canonique n'est pas sur alpha (HEAD=%s)" % head
        return r
    try:
        for f in plan["a_integrer"]:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_bytes((d / f).read_bytes())
    except OSError as e:
        _remettre_alpha(plan["a_integrer"], root)
        r["decision"] = "ABANDON : copie refusee (%s: %s) -- arbre remis a l'etat d'alpha" % (type(e).__name__, str(e)[:160])
        return r
    _git(["add", "--"] + plan["a_integrer"], root)
    message = "integre(%s): %s (sauvegarde %s, fichiers nommes seuls)" % (agent, sujet or "livraison", man.get("tache"))
    return _achever(r, plan, root, tests, message, origine={"sauvegarde": man.get("tache")})


# ── ORACLE GELE (chantier 5 de la preparation du takehome, decision owner 18/10) ──────────────────────────────
# Risque n°1 nomme par l'owner : des resultats spectaculaires invalides parce que des agents avaient modifie
# les tests. L'oracle evalue un candidat dans un worktree ISOLE, detache au SHA de reference, refuse toute
# ecriture sous un chemin protege, et ne promeut que correction validee ET gain confirme par l'evaluateur.
ORACLE_PROTEGES = ("tests/",)


def _empreinte_contenu(texte: str) -> str:
    import hashlib

    return hashlib.sha256(texte.encode("utf-8", "replace")).hexdigest()[:16]


def oracle_gele(depot, sha_ref: str, fichiers_candidat: dict, commande: list, extraire_metrique=None,
                proteges=ORACLE_PROTEGES, timeout: int = 600, archive=None) -> dict:
    """Evalue `fichiers_candidat` ({chemin relatif: contenu}) contre le depot fige a `sha_ref`.

    Verdicts : CORRECTNESS_PASS (commande rc 0) / CORRECTNESS_FAIL (rc != 0) / INVALID (chemin protege touche,
    ou diff des proteges non vide : rien n'est execute) / UNKNOWN (delai, worktree ou commande en erreur).
    Le depot de reference n'est jamais ecrit ; le worktree est retire dans tous les cas. `archive` (chemin
    .jsonl, optionnel) recoit une ligne par evaluation."""
    import shutil
    import tempfile
    import time as _time

    depot = Path(depot)
    rec = {"sha_ref": sha_ref, "commande": list(commande), "execute": False, "metrique": None,
           "fichiers": {p: _empreinte_contenu(c) for p, c in sorted((fichiers_candidat or {}).items())}}
    touches = sorted(p for p in (fichiers_candidat or {})
                     if any(p.replace("\\", "/").lstrip("./").startswith(pr) for pr in proteges))
    if touches:
        rec.update(verdict="INVALID", pourquoi="chemin(s) protege(s) touche(s) : %s" % ", ".join(touches))
        return _oracle_archiver(rec, archive)
    wt = Path(tempfile.mkdtemp(prefix="oracle_")) / "wt"
    rc, _o, err = _git(["worktree", "add", "--detach", str(wt), sha_ref], cwd=depot)
    if rc:
        rec.update(verdict="UNKNOWN", pourquoi="worktree non cree : %s" % err[:200])
        return _oracle_archiver(rec, archive)
    try:
        for chemin, contenu in (fichiers_candidat or {}).items():
            cible = wt / chemin
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(contenu, encoding="utf-8")
        rc, diff, _e = _git(["diff", "--name-only", "HEAD", "--", *proteges], cwd=wt)
        if rc or diff:
            rec.update(verdict="INVALID", pourquoi="proteges modifies apres ecriture : %s" % (diff or _e)[:200])
            return _oracle_archiver(rec, archive)
        t0 = _time.monotonic()
        try:
            r = subprocess.run(commande, cwd=str(wt), capture_output=True, text=True, errors="replace",
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            rec.update(execute=True, verdict="UNKNOWN", pourquoi="delai depasse (%d s)" % timeout,
                       duree_s=round(_time.monotonic() - t0, 3))
            return _oracle_archiver(rec, archive)
        except OSError as e:
            rec.update(verdict="UNKNOWN", pourquoi="commande non lancee : %s" % e)
            return _oracle_archiver(rec, archive)
        rec.update(execute=True, duree_s=round(_time.monotonic() - t0, 3), rc=r.returncode,
                   sortie=(r.stdout or "")[-2000:], erreurs=(r.stderr or "")[-2000:])
        rec["verdict"] = "CORRECTNESS_PASS" if r.returncode == 0 else "CORRECTNESS_FAIL"
        if extraire_metrique is not None and r.returncode == 0:
            rec["metrique"] = extraire_metrique(r.stdout)
        return _oracle_archiver(rec, archive)
    finally:
        _git(["worktree", "remove", "--force", str(wt)], cwd=depot)
        shutil.rmtree(wt.parent, ignore_errors=True)


def _oracle_archiver(rec: dict, archive) -> dict:
    if archive:
        try:
            import json as _json

            with open(archive, "a", encoding="utf-8") as f:
                f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            rec["archive_erreur"] = str(e)[:160]
    return rec


def promouvable(base: dict, cand: dict) -> dict:
    """Promotion seulement si les DEUX evaluations sont CORRECTNESS_PASS, au meme SHA, et que le gain est
    confirme par le contrat de metrique (juger_metrique : hors bruit, oriente)."""
    if base.get("verdict") != "CORRECTNESS_PASS" or cand.get("verdict") != "CORRECTNESS_PASS":
        return {"promouvable": False, "pourquoi": "correction non validee (%s / %s)"
                % (base.get("verdict"), cand.get("verdict"))}
    if base.get("sha_ref") != cand.get("sha_ref"):
        return {"promouvable": False, "pourquoi": "evaluations a des SHA differents"}
    sys.path.insert(0, str(ROOT / "app"))
    from forge_mutation_judge import juger_metrique  # noqa: PLC0415

    m = juger_metrique(base.get("metrique"), cand.get("metrique"))
    return {"promouvable": m["verdict"] == "AMELIORE", "pourquoi": m["pourquoi"], "metrique": m["verdict"]}


def main():
    ap = argparse.ArgumentParser(
        description="Porte de merge wip/<agent> -> alpha, jugee sur le gain ; ou reconciliation d'un commit relu")
    ap.add_argument("--agent", default=None)
    ap.add_argument("--commit", default=None, help="reconciliation : sha du commit d'executeur RELU")
    ap.add_argument("--sauvegarde", default=None,
                    help="reconciliation : dossier sandbox/sauvegardes_executeurs/<agent>/<tache> (manifeste.json)")
    ap.add_argument("--fichiers", nargs="*", default=None, help="reconciliation : fichiers NOMMES par la tache")
    ap.add_argument("--sujet", default="", help="reconciliation : sujet du commit d'integration")
    ap.add_argument("--apply", action="store_true",
                    help="merge si AMELIORE (defaut: dry-run)")
    ap.add_argument("--tests", nargs="*", default=None,
                    help="suite de tests (defaut: tests/nr/*)")
    a = ap.parse_args()
    if a.commit or a.sauvegarde:
        if a.sauvegarde:
            r = reconcilier_sauvegarde(a.sauvegarde, a.fichiers or [], apply=a.apply, agent=a.agent or "?",
                                       sujet=a.sujet, tests=a.tests)
        else:
            r = reconcilier(a.commit, a.fichiers or [], apply=a.apply, agent=a.agent or "?", sujet=a.sujet,
                            tests=a.tests)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if (r.get("applique") or not a.apply) and not str(r.get("decision", "")).startswith(("ABANDON", "REJET")) else 1
    if not a.agent:
        ap.error("--agent requis (ou --commit pour une reconciliation)")
    r = merger(a.agent, a.tests, a.apply)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("verdict") in ("AMELIORE", "NEUTRE", "RIEN_A_MERGER",
                                     "PAS_DE_WORKTREE", "PAS_DE_BRANCHE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
