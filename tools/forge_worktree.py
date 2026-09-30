#!/usr/bin/env python3
"""forge_worktree.py — isolation PHYSIQUE par agent (git worktree) = fin du clobber multi-surface.

PROBLÈME (mesuré) : arbre de travail PARTAGÉ → Claude + Gemini + cowork éditent les mêmes fichiers →
soup uncommitted, clobber, `hub run du WIP cassé` (incident reboot). Le blackboard tree_locks =
protocole COOPÉRATIF (faillible). RULES_SHARED : « isolation physique > protocole coopératif ».

MODÈLE :
  repo canonique (alpha)         ← ce que le HUB run (revu/mergé)
  nokido_worktrees/<agent>      ← branche wip/<agent>, l'agent édite ISOLÉ
        ↓ commit → merge alpha (revue) → reload hub
  état partagé (hub/RAG/blackboard) = INCHANGÉ, mono-writer (NE PAS isoler = fragmenter).

Le hub run TOUJOURS le canonique (jamais la soup d'un agent). Les worktrees vivent HORS du repo
(pas de nesting tracké). `forge_cli_route` peut poser le CWD = route(agent) au lancement.

Owner-run (git). create/list/status/route/sync. Idempotent.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `retirer_worktree` — Retire un worktree par son CHEMIN (`git worktree remove`). Le depot n'est jamais touche.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/git : isolation physique par agent via git worktree"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WT_ROOT = ROOT.parent / "nokido_worktrees"          # hors du repo (pas de nesting tracké)

# Racine du JUGEMENT — DISJOINTE de WT_ROOT, et c'est structurel, pas cosmétique :
# sous WT_ROOT, un agent nommé « proof » entrerait en collision avec le juge, et
# l'invariant « worktree d'agent != worktree de preuve » ne serait plus qu'une
# convention de nommage. Deux racines = deux espaces qui ne peuvent pas se croiser.
#
# OU elle vit : la ou le compte QUI JUGE a le droit d'écrire, pas là où le dépôt
# se trouve. Mesure du 2026-09-11, `icacls` sur la racine du superrepo —
# LaForgeTrusted (RX), LaForgeSbxOffline (RX) puis (OI)(CI)(R), et seuls user,
# SYSTEM et Administrateurs en (F) : le premier emplacement choisi était donc
# inaccessible en écriture à TOUS les comptes d'exécution, quel que soit le canal.
# Ce n'était pas un mauvais compte, c'était un mauvais endroit. Le temp du compte
# courant est inscriptible par construction et se déclare au besoin.
PROOF_ROOT = Path(os.environ.get("NOKIDO_PROOF_ROOT")
                  or (Path(tempfile.gettempdir()) / "nokido_proof"))

# surfaces autonomes = celles qui clobbent (RULES_SHARED). Interactif (claude+user) peut rester alpha.
AUTONOMOUS = ["gemini", "cowork", "claude_cli", "codex"]


def _git(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "safe.directory=*", *args],
                          capture_output=True, text=True, cwd=str(cwd), errors="replace")


def _wt_path(agent: str) -> Path:
    return WT_ROOT / agent.lower()


def create(agent: str) -> dict:
    """Crée worktrees/<agent> sur branche wip/<agent> (depuis alpha). Idempotent."""
    agent = agent.lower()
    wt = _wt_path(agent)
    branch = f"wip/{agent}"
    if wt.exists():
        return {"agent": agent, "path": str(wt), "status": "exists"}
    WT_ROOT.mkdir(parents=True, exist_ok=True)
    # branche : créer si absente (depuis alpha), sinon réutiliser
    has_branch = _git(["rev-parse", "--verify", branch]).returncode == 0
    if has_branch:
        r = _git(["worktree", "add", str(wt), branch])
    else:
        r = _git(["worktree", "add", "-b", branch, str(wt), "alpha"])
    if r.returncode != 0:
        return {"agent": agent, "error": r.stderr.strip()[:200]}
    # marqueur d'identité per-worktree (lu par forge_git_gate._agent)
    try:
        (wt / ".nokido.agent").write_text(f"agent={agent.upper()}\n", encoding="utf-8")
    except Exception:
        pass
    return {"agent": agent, "path": str(wt), "branch": branch, "status": "created"}


def _segment(valeur: str) -> str:
    """Rend une chaîne utilisable comme NOM DE REPERTOIRE.

    Un `execution_id` porte volontiers des `:` (`claude-cli-http:9f2a...`), qui sont
    illégaux dans un chemin Windows. On translittère au lieu de refuser : l'identité
    d'exécution est une donnée d'appelant, pas une saisie à valider.
    """
    return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in str(valeur))[:64] or "sans-id"


def proof_path(target_sha: str, execution_id: str = None) -> Path:
    """Chemin du worktree de jugement. Lecture seule, ne cree rien.

    Par `execution_id` quand il est fourni : deux juges peuvent alors mesurer le
    MEME sha en meme temps sans se voler leur arbre. Un emplacement unique et global
    — le `sandbox/ci_reference_wt` historique — les ferait se marcher dessus, le
    second `checkout --force` deplacant l'arbre que le premier est en train de lire.
    Sans `execution_id`, on retombe sur le sha : idempotent, mais partage.
    """
    if execution_id:
        return PROOF_ROOT / _segment(execution_id) / "worktree"
    return PROOF_ROOT / str(target_sha)[:12]


def _worktree_detache(sha: str, wt: Path) -> dict:
    """PRIMITIVE UNIQUE : un arbre detache sur `sha` en `wt`. add, sinon refresh.

    Toute creation de worktree detache du depot passe par ici. Avant la convergence
    du 2026-09-11 il en existait TROIS copies — `ci_local.preparer_reference`,
    `ci_local` pour le cliquet de mutation, et `create_proof` — qui avaient deja
    commence a diverger sur le traitement d'un arbre reste au mauvais commit.
    """
    if wt.exists():
        tete = _git(["rev-parse", "HEAD"], cwd=wt).stdout.strip()
        if tete == sha:
            return {"sha": sha, "path": str(wt), "status": "exists", "detached": True}
        r = _git(["-C", str(wt), "checkout", "--detach", "--force", sha], cwd=ROOT)
        if r.returncode != 0:
            return {"sha": sha, "path": str(wt), "status": "incoherent",
                    "error": "worktree sur %s, rafraichissement vers %s refuse : %s"
                             % (tete[:12], sha[:12], r.stderr.strip()[:160])}
        relu = _git(["rev-parse", "HEAD"], cwd=wt).stdout.strip()
        if relu != sha:
            # On RELIT pour conclure, jamais l'absence d'erreur : un checkout qui
            # rend 0 sans avoir bouge laisserait juger le mauvais commit.
            return {"sha": sha, "path": str(wt), "status": "incoherent",
                    "error": "rafraichissement annonce OK mais HEAD vaut %s" % relu[:12]}
        return {"sha": sha, "path": str(wt), "status": "rafraichi", "detached": True}

    try:
        wt.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"sha": sha, "path": str(wt), "status": "refuse",
                "error": "racine non creable (%s: %s) — un worktree s'ecrit sur le "
                         "disque, le compte courant doit y avoir le droit"
                         % (type(exc).__name__, str(exc)[:120])}
    try:
        r = _git(["worktree", "add", "--detach", str(wt), sha], cwd=ROOT)
    except OSError as exc:
        return {"sha": sha, "status": "refuse",
                "error": "git worktree add impossible (%s: %s)" % (type(exc).__name__, str(exc)[:120])}
    if r.returncode != 0:
        return {"sha": sha, "error": r.stderr.strip()[:200]}
    return {"sha": sha, "path": str(wt), "status": "created", "detached": True}


def create_scratch(target_sha: str, chemin) -> dict:
    """Arbre detache DESTINE A ETRE ECRIT (mutation, bac d'essai).

    A NE PAS CONFONDRE avec `create_proof`. Le cliquet de mutation, lui, ECRIT dans
    son arbre — c'est tout son objet : il mute le code pour verifier que les tests
    mordent. Lui faire partager le contrat du worktree de preuve (« aucun fichier
    n'est ecrit dedans ») serait une erreur de conception, pas une simplification :
    un seul CREATEUR, mais deux CONTRATS D'USAGE, et ils se nomment.

    L'emplacement est fourni par l'appelant : un bac de travail se place la ou son
    proprietaire a le droit d'ecrire, alors qu'un arbre de jugement se place la ou
    la gouvernance le decide.
    """
    sha = (target_sha or "").strip()
    if not sha:
        return {"error": "target_sha vide"}
    resolu = _git(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd=ROOT)
    if resolu.returncode != 0 or not resolu.stdout.strip():
        return {"error": f"sha inconnu dans ce depot : {sha[:40]}"}
    return _worktree_detache(resolu.stdout.strip(), Path(chemin))


def create_proof(target_sha: str, execution_id: str = None) -> dict:
    """Worktree de JUGEMENT : tete DETACHEE sur `target_sha`. Idempotent.

    POURQUOI IL EXISTE (mesure du 2026-09-11 sur alpha 80035fe14) : l'arbre de
    travail etait `git status` PROPRE cote fichiers suivis, et pourtant la capture
    de sha refusait de se faire, a cause de 70 fichiers NON SUIVIS appartenant a
    d'autres chantiers. Un agent qui n'avait rien pousse empechait donc de juger un
    commit deja publie. Le remede n'est pas d'excuser ces fichiers un a un — c'est
    de changer de PERIMETRE : ici, ils n'existent pas.

    DEUX DIFFERENCES AVEC `create()`, et elles sont volontaires :

    1. `--detach`, jamais de branche. Une preuve represente un etat IMMUABLE ; une
       branche est une ligne de developpement. Un sha juge ne doit pas en devenir une.
    2. AUCUN fichier n'est ecrit dans le worktree — pas meme un marqueur d'identite
       comme le `.nokido.agent` que `create()` depose. Un juge qui ecrit dans ce
       qu'il mesure se salit lui-meme, et c'est exactement le defaut paye le
       2026-09-09 : la procedure de preuve prenait ses propres sorties pour une
       alteration adverse. Les artefacts (logs, JUnit, captures) vivent HORS d'ici.

    `cwd=ROOT` est passe EXPLICITEMENT a chaque appel : le defaut `cwd: Path = ROOT`
    de `_git` est lie a la DEFINITION, donc un test qui repointe `ROOT` verrait
    quand meme le depot reel — et creerait de vrais worktrees en croyant simuler.
    """
    sha = (target_sha or "").strip()
    if not sha:
        return {"error": "target_sha vide — un juge sans sha n'a rien a juger"}

    resolu = _git(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd=ROOT)
    if resolu.returncode != 0 or not resolu.stdout.strip():
        return {"error": f"sha inconnu dans ce depot : {sha[:40]}"}
    sha = resolu.stdout.strip()
    wt = proof_path(sha, execution_id)

    # Un refus d'ACL est une reponse, pas une panne (mesure du 2026-09-11 :
    # PermissionError WinError 5 quand la racine visait le profil owner). La
    # primitive le NOMME au lieu de laisser l'exception remonter, sinon une
    # permission manquante se lit comme un mecanisme casse.
    return _worktree_detache(sha, wt)


def retirer_worktree(wt) -> dict:
    """Retire un worktree par son CHEMIN (`git worktree remove`). Le depot n'est jamais touche.

    Pourquoi par chemin (2026-09-24, mesure) : `PROOF_ROOT` depend du TEMP du compte qui
    l'evalue. La CI (compte de job) ecrit sous `sandbox/workspace/tmp/nokido_proof`, le
    service de retention (autre compte) calculait `C:\\WINDOWS\\TEMP\\nokido_proof` : une
    purge qui re-deduit le chemin depuis un sha ne retire rien de ce que la CI a cree.
    """
    wt = Path(wt)
    if not wt.exists():
        return {"chemin": str(wt), "status": "absent"}
    r = _git(["worktree", "remove", "--force", str(wt)], cwd=ROOT)
    return {"chemin": str(wt), "status": "removed" if r.returncode == 0 else "erreur",
            "msg": (r.stderr or r.stdout).strip()[:200]}


def remove_proof(target_sha: str, execution_id: str = None) -> dict:
    """Retire le worktree de jugement d'un sha. Le depot n'est jamais touche."""
    r = retirer_worktree(proof_path(target_sha, execution_id))
    r["sha"] = target_sha
    return r


def list_wt() -> list:
    r = _git(["worktree", "list", "--porcelain"])
    out, cur = [], {}
    for ln in r.stdout.splitlines():
        if ln.startswith("worktree "):
            if cur:
                out.append(cur)
            cur = {"path": ln.split(" ", 1)[1]}
        elif ln.startswith("branch "):
            cur["branch"] = ln.split(" ", 1)[1]
        elif ln.startswith("HEAD "):
            cur["head"] = ln.split(" ", 1)[1][:12]
    if cur:
        out.append(cur)
    return out


def status() -> dict:
    wts = list_wt()
    detail = {}
    for w in wts:
        p = Path(w["path"])
        if p == ROOT:
            continue
        st = _git(["status", "--short"], cwd=p)
        detail[p.name] = {"branch": w.get("branch", "?"), "dirty_lines": len(st.stdout.splitlines())}
    return {"canonical": str(ROOT), "worktrees": wts, "dirty": detail}


def route(agent: str) -> str:
    """CWD que <agent> doit utiliser (canonique si pas de worktree)."""
    wt = _wt_path(agent.lower())
    return str(wt) if wt.exists() else str(ROOT)


def sync(agent: str) -> dict:
    """Rebase la branche wip/<agent> sur alpha (récupère le canonique à jour). NON destructif si conflit."""
    wt = _wt_path(agent.lower())
    if not wt.exists():
        return {"agent": agent, "error": "worktree absent"}
    r = _git(["rebase", "alpha"], cwd=wt)
    return {"agent": agent, "rebased": r.returncode == 0, "msg": (r.stderr or r.stdout).strip()[:200]}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    arg = argv[1] if len(argv) > 1 else None
    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=1))
    elif cmd == "list":
        print(json.dumps(list_wt(), ensure_ascii=False, indent=1))
    elif cmd == "create":
        targets = [arg] if arg else AUTONOMOUS
        print(json.dumps([create(a) for a in targets], ensure_ascii=False, indent=1))
    elif cmd == "create-proof":
        if not arg:
            print("usage: create-proof <sha>")
            return 2
        print(json.dumps(create_proof(arg), ensure_ascii=False, indent=1))
    elif cmd == "remove-proof":
        if not arg:
            print("usage: remove-proof <sha>")
            return 2
        print(json.dumps(remove_proof(arg), ensure_ascii=False, indent=1))
    elif cmd == "route":
        print(route(arg or "claude"))
    elif cmd == "sync":
        print(json.dumps(sync(arg or "gemini"), ensure_ascii=False, indent=1))
    else:
        print(f"cmd inconnue: {cmd} (status|list|create [agent]|create-proof <sha>|"
              f"remove-proof <sha>|route <agent>|sync <agent>)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
