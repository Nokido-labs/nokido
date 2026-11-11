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
import logging
import os
import re
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

# REGISTRE DES RACINES DE PREUVE (owner 15/10 : « reconcilier, le travail ne doit pas etre perdu »).
# PROOF_ROOT depend du TEMP du compte qui juge : le hook pre-push (session owner) ecrit sous
# D:/Temp/nokido_proof, que le service de retention (autre compte) ne peut pas deviner -- 44
# worktrees de preuve s'y etaient accumules. Le proprietaire DIT ou il ecrit, a chaque preuve.
REGISTRE_RACINES = ROOT / "sandbox" / "proof_roots.json"
# Ce qu'un worktree de preuve porte NORMALEMENT hors de son commit (mesure du 15/10 sur 94 worktrees) :
# suppressions du filtrage de la racine de preuve, artefacts sous sandbox/, temoin de vitalite des gardes.
ARTEFACTS_DE_PREUVE = (r"^ D ", r"^\?\? sandbox/", r"^ M sandbox/", r"^ M tests/nr/vitalite_gardes\.json$")


def racines_de_preuve_inscrites() -> list:
    """Racines inscrites par les comptes qui ont cree des preuves. Illisible ou absent -> []."""
    try:
        d = json.loads(REGISTRE_RACINES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(x) for x in d if isinstance(x, str)] if isinstance(d, list) else []


def inscrire_racine_de_preuve(racine=None) -> bool:
    """Ajoute la racine (defaut : PROOF_ROOT du compte courant) au registre, sans doublon. Faux = non inscrite."""
    r = str(Path(racine or PROOF_ROOT))
    vues = racines_de_preuve_inscrites()
    if any(os.path.normcase(os.path.normpath(x)) == os.path.normcase(os.path.normpath(r)) for x in vues):
        return True
    try:
        REGISTRE_RACINES.parent.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRE_RACINES.with_suffix(".tmp")
        tmp.write_text(json.dumps(vues + [r], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, REGISTRE_RACINES)
        return True
    except OSError:
        return False


def perte_possible(wt) -> str | None:
    """Retirer ce worktree perdrait-il du travail ? None = non (prouve) ; sinon la RAISON, et on ne retire pas.

    Prouve « sans perte » : HEAD accessible depuis au moins une reference ET `git status` ne porte que
    des ARTEFACTS_DE_PREUVE. Toute lecture impossible vaut perte possible (INCONNU n'est pas NON)."""
    import re as _re

    wt = Path(wt)
    st = _git(["status", "--porcelain", "--untracked-files=all"], cwd=wt)
    if st.returncode != 0:
        return "status illisible (%s)" % (st.stderr or "").strip()[:120]
    hors = [l for l in st.stdout.splitlines()
            if l.strip() and not any(_re.match(p, l) for p in ARTEFACTS_DE_PREUVE)]
    if hors:
        return "%d chemin(s) hors artefacts, ex. %s" % (len(hors), hors[0][:100])
    head = _git(["rev-parse", "HEAD"], cwd=wt)
    if head.returncode != 0 or not head.stdout.strip():
        return "HEAD illisible"
    refs = _git(["for-each-ref", "--contains", head.stdout.strip(), "--format=%(refname)", "--count=1"], cwd=ROOT)
    if refs.returncode != 0:
        return "references illisibles"
    if not refs.stdout.strip():
        return "COMMIT_ORPHELIN : HEAD %s accessible depuis aucune reference" % head.stdout.strip()[:12]
    return None


# surfaces autonomes = celles qui clobbent (RULES_SHARED). Interactif (claude+user) peut rester alpha.
AUTONOMOUS = ["gemini", "cowork", "claude_cli", "codex"]


def _git(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    # core.longpaths : sous un chemin profond (tmp de la CI de reference, 144 car. de base), `rebase` mourait en
    # « fatal: failed to stat '<sha>...<sha>': Filename too long » (CI d58bb84bb) ; transmis aux git enfants.
    return subprocess.run(["git", "-c", "safe.directory=*", "-c", "core.longpaths=true", *args],
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
    marqueur = "ecrit"
    try:
        (wt / ".nokido.agent").write_text(f"agent={agent.upper()}\n", encoding="utf-8")
    except OSError as exc:
        logging.getLogger("Nokido.Worktree").warning(
            "ecriture .nokido.agent impossible (%s): %s",
            type(exc).__name__,
            exc,
        )
        marqueur = (
            f"NON ECRIT ({type(exc).__name__}) : "
            f"forge_git_gate n'attribuera pas les commits de ce worktree a {agent.upper()}"
        )
    return {"agent": agent, "path": str(wt), "branch": branch, "status": "created", "marqueur_identite": marqueur}


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
    # La retention, sous un autre compte, saura ou chercher. JAMAIS sous pytest : des tests repointent
    # PROOF_ROOT vers leur dossier temporaire, et 15 de ces racines s'etaient inscrites dans le VRAI
    # registre au premier rejeu (15/10) -- un test n'ecrit pas dans l'etat reel.
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        inscrire_racine_de_preuve()

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


# Etape 2 de P1_worktree_par_provenance_et_reconciliation_20261018 (decision owner 22/10) : la provenance EXECUTEUR
# (identite ou en-tete LaForge-Provenance TASK_EXECUTOR) ecrit dans SON worktree, jamais dans l'arbre partage.
_EXECUTEURS_WT_EXACTS = frozenset({"CLAUDE_HEADLESS", "ANTIGRAVITY", "MISTRAL"})
_EXECUTEURS_WT_PREFIXES = ("OPENCODE_",)
_PROVENANCE_EXECUTEUR = "TASK_EXECUTOR"
# 31/10 (choix owner « alias + refus ») : le 27/10 02:24 VIBE_HEADLESS a ecrase app/forge_byte_router.py (« ... »)
# DANS L'ARBRE PARTAGE -- son nom n'etait pas ci-dessus. Alias identite headless -> DOSSIER du worktree de
# l'executeur qu'elle sert ; toute AUTRE identite *_HEADLESS est refusee a l'ecriture tant que son worktree n'est pas
# declare (creation = geste owner). NR tests/nr/test_worktree_alias_headless_nr.py.
_ALIAS_WT_HEADLESS = {"VIBE_HEADLESS": "mistral", "CODEX_HEADLESS": "codex",
                      "AGY_HEADLESS": "antigravity", "ANTIGRAVITY_HEADLESS": "antigravity"}
_SUFFIXE_HEADLESS = "_HEADLESS"


def court_tache(task_id) -> str:
    """Identifiant court UNIQUE d'une tache (nom de son worktree et de sa branche `tache/<agent>/<court>`).
    SOURCE UNIQUE depuis le 31/10 (l'executeur `_wt_court` y delegue) : la portee du hub et le worktree de l'executeur
    doivent nommer le MEME dossier. 29/10 : tete + empreinte, jamais les 12 derniers caracteres (collisions)."""
    import hashlib
    s = re.sub(r"[^A-Za-z0-9]", "", str(task_id).replace("job_", "", 1))
    if len(s) <= 12:
        return s or "tache"
    return s[:8] + hashlib.sha1(str(task_id).encode("utf-8")).hexdigest()[:4]


def taches_en_cours(agent, tasks_db=None) -> list:
    """Ids des taches `running` de cet agent (tasks.db, lecture seule). Illisible -> [] (portee la plus etroite)."""
    import sqlite3
    db = Path(tasks_db) if tasks_db else ROOT / "sandbox" / "tasks.db"
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            return [r[0] for r in c.execute("SELECT id FROM tasks WHERE status='running' AND upper(agent)=?",
                                            (str(agent or "").upper(),))]
        finally:
            c.close()
    except Exception:  # noqa: BLE001 - base illisible : aucune tache, donc aucun worktree de tache lisible
        return []


def portee_lecture(agent, taches, wt_root=None, depot=None):
    """Portee de LECTURE d'un executeur, calculee a chaque appel depuis ses taches en cours (owner 31/10 : « le scope
    sur task.db doit etre bien defini dynamiquement ; des taches distinctes, il faut bien les scinder »).

    Rend None pour l'owner / une identite non executeur (portee inchangee). Pour un executeur : le depot (lecture du
    tronc commun), son worktree habituel, et le worktree de CHACUNE de ses taches en cours -- jamais celui d'une autre
    tache. Les entrees d'un travail (travaux amont) sont FUSIONNEES dans son propre worktree a l'ouverture : aucune
    lecture croisee n'est necessaire pour qu'un travail 3 se nourrisse des travaux 1 et 2."""
    nom = str(agent or "").strip().upper()
    if not (nom in _EXECUTEURS_WT_EXACTS or nom.startswith(_EXECUTEURS_WT_PREFIXES)):
        return None
    racine = Path(wt_root) if wt_root is not None else WT_ROOT
    ag = re.sub(r"[^a-z0-9_]", "_", nom.lower())
    racines = [Path(depot) if depot is not None else ROOT, racine / nom.lower()]
    racines += [racine / "taches" / ("%s_%s" % (ag, court_tache(t))) for t in (taches or [])]
    return {"agent": nom, "racines": racines}


def dans_portee(chemin, portee) -> bool:
    """Le chemin est-il sous une racine de la portee ? Portee None (owner) : oui, comportement inchange."""
    if portee is None:
        return True
    try:
        p = Path(chemin).resolve()
    except OSError:
        return False
    for r in portee["racines"]:
        try:
            p.relative_to(Path(r).resolve())
            return True
        except (ValueError, OSError):
            continue  # muet-ok : pas sous cette racine (cas NORMAL) -> racine suivante ; aucune -> False en fin
    return False


_NON_EXIGEE = object()  # `tentative` non fournie : l'appelant n'a pas de jeton a verifier (comportement d'avant)


def tentative_courante(task_id, tasks_db=None):
    """Tentative (colonne `garde`, +1 a chaque claim pending->running) de la tache `running` `task_id`.
    7/11 : `attempt` ne sert pas, la voie « pid mort » ne l'incremente pas et son increment consommerait le plafond de
    reprises. Base illisible, colonne absente, tache non `running` -> None (echec ferme cote appelant)."""
    import sqlite3
    db = Path(tasks_db) if tasks_db else ROOT / "sandbox" / "tasks.db"
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            r = c.execute("SELECT garde FROM tasks WHERE id=? AND status='running'", (str(task_id),)).fetchone()
        finally:
            c.close()
        return int(r[0] or 0) if r else None
    except Exception:  # noqa: BLE001 - illisible : None, l'appelant refuse
        return None


def cible_ecriture(agent, provenance="", wt_root=None, tasks_db=None, tache="", tentative=_NON_EXIGEE) -> dict:
    """Ou un appel `governed_edit` doit ecrire. Rend {cible, racine, raison}.

    cible = "PARTAGE" (owner / inconnu : comportement inchange), "WORKTREE" (racine = nokido_worktrees/<agent>, ou le
    worktree de SA tache s'il en a une en cours) ou "REFUS" (executeur dont le worktree n'existe pas, dont le nom ne
    se deduit pas, ou qui a plusieurs taches en cours : JAMAIS de repli silencieux). Un worktree = un dossier portant
    un marqueur `.git`. 7/11 : sans cela les livrables de CLAUDE_HEADLESS partaient dans son arbre fixe, en retard,
    pendant que le juge lisait le worktree de la tache : `[artefact ABSENT]` a tort.
    """
    nom = str(agent or "").strip().upper()
    entete = str(provenance or "").strip().upper()
    alias = _ALIAS_WT_HEADLESS.get(nom)
    est_executeur = alias is not None or nom in _EXECUTEURS_WT_EXACTS or nom.startswith(_EXECUTEURS_WT_PREFIXES)
    if not est_executeur and nom.endswith(_SUFFIXE_HEADLESS):
        return {"cible": "REFUS", "racine": None,
                "raison": "identite %s (surface headless) sans worktree d'executeur declare : refus, jamais d'arbre "
                          "partage (choix owner 31/10) -- creer son worktree puis l'ajouter a _ALIAS_WT_HEADLESS"
                          % nom}
    if not est_executeur and entete != _PROVENANCE_EXECUTEUR:
        return {"cible": "PARTAGE", "racine": None, "raison": ""}
    if not est_executeur:
        return {"cible": "REFUS", "racine": None,
                "raison": "en-tete LaForge-Provenance TASK_EXECUTOR mais l'identite %r ne nomme aucun worktree "
                          "d'executeur : refus (on ne devine pas le worktree, jamais d'arbre partage)" % (agent,)}
    racine_wt = Path(wt_root) if wt_root is not None else WT_ROOT
    ag = alias or nom.lower()
    en_cours = taches_en_cours(ag.upper(), tasks_db)
    tache = str(tache or "").strip()
    if tache:
        # L'en-tete LaForge-Tache lie l'ecriture a SA tache : elle doit etre parmi les taches en cours de CET agent
        # (une tache d'un autre agent ne donne jamais son arbre).
        choisies = [t for t in en_cours if tache in (str(t), court_tache(t))]
        if not choisies:
            return {"cible": "REFUS", "racine": None,
                    "raison": "tache %r absente des taches en cours de %s : refus (la tache d'un autre agent ne "
                              "donne jamais son arbre)" % (tache, nom)}
        en_cours = choisies
        if tentative is not _NON_EXIGEE:
            # Jeton de garde (7/11) : la tentative SIGNEE dans le jeton doit etre celle de la tache `running`.
            if tentative is None:
                logging.getLogger("forge_worktree").warning("[garde] tentative ABSENTE du jeton pour %s (%s) : refus", tache, nom)
                return {"cible": "REFUS", "racine": None,
                        "raison": "tentative absente du jeton de %s pour la tache %r : refus (echec ferme)"
                                  % (nom, tache)}
            actuelle = tentative_courante(en_cours[0], tasks_db)
            if actuelle is None:
                return {"cible": "REFUS", "racine": None,
                        "raison": "tentative de la tache %r illisible (base ou colonne) : refus (echec ferme)" % tache}
            try:
                signee = int(tentative)
            except (TypeError, ValueError):
                signee = None
            if signee != actuelle:
                logging.getLogger("forge_worktree").warning("[garde] tentative perimee pour %s : jeton=%s, base=%s : refus", tache, tentative, actuelle)
                return {"cible": "REFUS", "racine": None,
                        "raison": "tentative perimee : le jeton porte la tentative %s, la tache est a la %s "
                                  "(worker zombie apres reprise) : refus" % (tentative, actuelle)}
    dossiers = [racine_wt / "taches" / ("%s_%s" % (re.sub(r"[^a-z0-9_]", "_", ag), court_tache(t)))
                for t in en_cours]
    dossiers = [d for d in dossiers if d.is_dir() and (d / ".git").exists()]
    if len(dossiers) == 1:
        return {"cible": "WORKTREE", "racine": dossiers[0], "raison": ""}
    if len(dossiers) > 1:
        return {"cible": "REFUS", "racine": None,
                "raison": "%d taches en cours pour %s : worktree ambigu, refus. L'en-tete LaForge-Tache manque : "
                          "la config MCP de la tache doit le porter (--tache)" % (len(dossiers), nom)}
    wt = racine_wt / ag
    if not (wt.is_dir() and (wt / ".git").exists()):
        return {"cible": "REFUS", "racine": None,
                "raison": "worktree de l'executeur %s introuvable (%s) : refus, jamais de repli sur l'arbre partage"
                          % (nom, wt)}
    return {"cible": "WORKTREE", "racine": wt, "raison": ""}


def route(agent: str) -> str:
    """CWD que <agent> doit utiliser (canonique si pas de worktree)."""
    wt = _wt_path(agent.lower())
    return str(wt) if wt.exists() else str(ROOT)


def _assainir(agent: str, wt: Path, raison: str) -> dict:
    """Decision owner 19/10 (« preserver puis repartir ») : tout l'etat du worktree -- commits de la branche ET
    fichiers modifies ou non suivis, hors marqueur d'identite -- part sur preserve/<agent>-<horodatage>, puis la
    branche de l'agent repart d'alpha. JAMAIS PERDU : la branche de preservation se relit et s'integre a la main."""
    import time as _t
    branche = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt).stdout.strip()
    if not branche or branche == "HEAD":
        branche = "wip/%s" % agent.lower()
    pres = "preserve/%s-%s" % (agent.lower(), _t.strftime("%Y%m%d-%H%M%S"))
    if _git(["checkout", "-q", "-b", pres], cwd=wt).returncode != 0:
        return {"agent": agent, "rebased": False, "msg": "assainissement IMPOSSIBLE (branche %s) -- %s" % (pres, raison)}
    _git(["add", "-A", "--", ".", ":(exclude).nokido.agent"], cwd=wt)
    if _git(["diff", "--cached", "--quiet"], cwd=wt).returncode != 0:
        c = _git(["-c", "user.name=nokido-preservation", "-c", "user.email=preservation@nokido.local", "commit", "-q",
                  "-m", "chore(preservation): etat de %s avant recalage sur alpha" % agent, "-m", raison[:300]], cwd=wt)
        if c.returncode != 0:
            return {"agent": agent, "rebased": False, "preserve": pres,
                    "msg": "preservation NON committee, worktree laisse sur %s -- %s" % (pres, (c.stderr or c.stdout)[:160])}
    r = _git(["checkout", "-q", "-B", branche, "alpha"], cwd=wt)
    return {"agent": agent, "rebased": r.returncode == 0, "assaini": r.returncode == 0, "preserve": pres,
            "msg": ("etat preserve sur %s, %s repart d'alpha -- cause : %s" % (pres, branche, raison[:160]))
            if r.returncode == 0 else "recalage IMPOSSIBLE apres preservation -- %s" % (r.stderr or r.stdout)[:160]}


def sync(agent: str) -> dict:
    """Rebase la branche wip/<agent> sur alpha (récupère le canonique à jour). NON destructif si conflit."""
    wt = _wt_path(agent.lower())
    if not wt.exists():
        return {"agent": agent, "error": "worktree absent"}
    # 17/10 : le SEUL marqueur `.nokido.agent` indexe faisait refuser le rebase (index non vide) -- opencode_nemotron restait
    # sur 4048d8ff6. On desindexe ce marqueur, et lui seul : un vrai travail en cours bloque toujours le rebase (jamais
    # touche, NR test_un_travail_en_cours_n_est_jamais_touche). Pas de --autostash : il rebaserait aussi ce travail.
    _git(["reset", "-q", "--", ".nokido.agent"], cwd=wt)
    r = _git(["rebase", "alpha"], cwd=wt)
    if r.returncode != 0:
        # 2026-10-17 : sur CONFLIT, git s'arretait EN PLEIN REBASE -- le worktree restait casse pour l'agent, contrairement
        # a « NON destructif » (mesure par NR). On l'abandonne : la branche revient a son etat d'avant, rien n'est perdu.
        en_cours = any((wt / _git(["rev-parse", "--git-path", x], cwd=wt).stdout.strip()).exists()
                       for x in ("rebase-merge", "rebase-apply"))
        if en_cours:
            ab = _git(["rebase", "--abort"], cwd=wt)
            if ab.returncode != 0:
                return {"agent": agent, "rebased": False, "abandonne": False,
                        "msg": "conflit : rebase NON abandonne -- " + (r.stderr or r.stdout).strip()[:160]}
        # Conflit, non indexes ou non suivis qui bloquent : preserver puis repartir d'alpha (decision owner 19/10).
        return _assainir(agent, wt, (r.stderr or r.stdout).strip()[:300])
    return {"agent": agent, "rebased": True, "msg": (r.stderr or r.stdout).strip()[:200]}


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
    elif cmd == "reconcilier-boucle":
        print(json.dumps(reconcilier_orphelins_boucle(), ensure_ascii=False, indent=1))
    else:
        print(f"cmd inconnue: {cmd} (status|list|create [agent]|create-proof <sha>|"
              f"remove-proof <sha>|route <agent>|sync <agent>|reconcilier-boucle)")
    return 0


# ── RECONCILIATEUR AUTOMATIQUE DE WORKTREE (decision owner 6/11 & v2 7/11) ───
_REGISTRE_RECONCILIATION = ROOT / "sandbox" / "reconciliateur_lots.json"
_LOTS_MEMOIRE: set[str] = set()
_DERNIER_PASSAGE_BOUCLE: float = 0.0
_INTERVALLE_MIN_BOUCLE_S: float = 30.0


def alerter_owner_reconciliation(sujet: str, gravite: str, detail: str, emetteur: str = "reconciliateur_boucle") -> str:
    """Canal d'alerte owner officiel (forge_critical_events). Ne leve jamais."""
    try:
        from nokido_agent.app import forge_critical_events as _ce
        return _ce.alerter_owner(sujet=sujet, gravite=gravite, detail=detail, emetteur=emetteur)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").warning("[reconciliateur] alerte INDISPONIBLE (%s) : %s", type(exc).__name__, sujet)
        return "indisponible"


def interrupteur_reconciliateur_actif(root: Path | None = None) -> bool:
    """Interrupteur global lu a CHAQUE passage. Faux par defaut."""
    if os.environ.get("NOKIDO_RECONCILIATEUR_ACTIF") == "1" or os.environ.get("FORGE_RECONCILIATEUR_ACTIF") == "1":
        return True
    r = Path(root) if root else ROOT
    switch = r / "sandbox" / "reconciliateur_boucle.switch"
    return switch.is_file()


def _lire_pression_systeme() -> tuple[float, float]:
    """Lit (ram_ratio, cpu_ratio) dans [0.0, 1.0]. Fail-closed : si capteur muet ou leve, ratio=1.0."""
    # 1. Hormones / endocrine : seul un niveau FRAIS compte. Absent ou expire ne vaut pas zero (relecture 7/11).
    try:
        from nokido_agent.app import forge_endocrine as _en
        r_ram = _en.read_full("pression_ram")
        r_cpu = _en.read_full("pression_cpu")
        if r_ram and r_cpu and not getattr(r_ram, "expired", False) and not getattr(r_cpu, "expired", False):
            return (float(getattr(r_ram, "fresh_level", 1.0)), float(getattr(r_cpu, "fresh_level", 1.0)))
    except Exception:  # noqa: BLE001 - muet-ok : capteur indisponible, la mesure directe prend le relais
        pass

    # 2. Repli psutil
    try:
        import psutil
        ram = psutil.virtual_memory().percent / 100.0
        cpu = psutil.cpu_percent(interval=None) / 100.0
        return ram, cpu
    except Exception:  # noqa: BLE001
        # Capteur muet ou cassé -> fail-closed (abstention)
        return 1.0, 1.0


def garde_ressources_au_rouge() -> bool:
    """S'abstient si le garde RAM ou CPU est au rouge (seuil >= 0.75).
    Fail-closed : capteur muet ou en exception -> abstention (True)."""
    try:
        ram, cpu = _lire_pression_systeme()
        if ram >= 0.75 or cpu >= 0.75:
            return True
        return False
    except Exception:  # noqa: BLE001
        return True


def _charger_registre_reconciliation(fichier: Path | None = None) -> tuple[set[str], bool]:
    """Charge le registre de reconciliation.
    Rend (lots, illisible) : si le fichier existe mais est illisible/corrompu,
    illisible=True pour empecher toute re-alerte en double."""
    p = fichier or _REGISTRE_RECONCILIATION
    lots = set(_LOTS_MEMOIRE)
    if not p.is_file():
        return lots, False
    try:
        items = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(items, list):
            lots.update(str(x) for x in items)
            return lots, False
        logging.getLogger("forge_worktree").error("[reconciliateur] registre invalide (pas une liste): %s", p)
        return lots, True
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").error("[reconciliateur] registre illisible (%s): %s", type(exc).__name__, p)
        return lots, True


def _sauver_registre_reconciliation(lots: set[str], fichier: Path | None = None) -> bool:
    """Sauvegarde le registre. Journalise en cas d'erreur sans lever."""
    p = fichier or _REGISTRE_RECONCILIATION
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(lots), ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").error("[reconciliateur] sauvegarde registre impossible (%s): %s", type(exc).__name__, p)
        return False


def _resoudre_tache_et_vol(court: str, agent: str, tasks_db: Path | None = None) -> tuple[bool | str, dict | None]:
    """Resout la tache associee a (agent, court) et determine son etat de vol.
    Rend (en_vol, tache_resolue).
    en_vol vaut True (en vol), False (libre), ou 'INCONNU' (base absente ou illisible).
    tache_resolue est un dict {'id', 'status', 'exec_pid', 'exec_cree'} ou None.
    Statuts en vol : ('running', 'claimed', 'assigned', 'pending').
    """
    import sqlite3
    db = Path(tasks_db) if tasks_db else ROOT / "sandbox" / "tasks.db"
    if not db.is_file():
        logging.getLogger("forge_worktree").warning("[reconciliateur] tasks.db absente : %s", db)
        return "INCONNU", None
    try:
        try:
            conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
        except Exception:
            conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            statuts = ("running", "claimed", "assigned", "pending")
            # 1. Recuperer les taches de l'agent (ou toutes si agent vide)
            if agent:
                rows = conn.execute("SELECT * FROM tasks WHERE upper(agent) = ?", (str(agent).upper(),)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tasks").fetchall()

            tache_resolue = None
            if court and court != "orphan" and court != "wip":
                for r in rows:
                    tid = str(r["id"])
                    try:
                        ct = court_tache(tid)
                    except Exception:
                        ct = None
                    if (ct and ct == court) or tid.endswith(court) or tid == court:
                        tache_resolue = {
                            "id": r["id"],
                            "status": r["status"],
                            "exec_pid": r["exec_pid"] if "exec_pid" in r.keys() else None,
                            "exec_cree": r["exec_cree"] if "exec_cree" in r.keys() else None,
                        }
                        break

            # Une tache RESOLUE decide seule
            if tache_resolue is not None:
                en_vol = tache_resolue["status"] in statuts
                return en_vol, tache_resolue

            # Repli prudent si aucune tache n'est resolue : toute tache de l'agent en vol = en vol
            for r in rows:
                if r["status"] in statuts:
                    return True, None

            return False, None
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").warning("[reconciliateur] tasks.db illisible (%s): %s", type(exc).__name__, db)
        return "INCONNU", None


def _tache_est_en_vol(court: str, agent: str, tasks_db: Path | None = None, avec_info: bool = False):
    """Etat de vol de la tache : True (en vol), False (libre), ou 'INCONNU' (base absente ou illisible).
    Statuts en vol : ('running', 'claimed', 'assigned', 'pending').
    Si avec_info=True, rend tuple (en_vol, info_tache_resolue)."""
    en_vol, info = _resoudre_tache_et_vol(court, agent, tasks_db)
    if avec_info:
        return en_vol, info
    return en_vol


def _info_tache_par_id(tasks_db: Path | str | None, task_id: str) -> dict | None:
    """Recupere id, status, exec_pid et exec_cree d'une tache depuis tasks.db."""
    import sqlite3
    db = Path(tasks_db) if tasks_db else ROOT / "sandbox" / "tasks.db"
    if not db.is_file():
        return None
    try:
        try:
            conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
        except Exception:
            conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "status": row["status"],
                "exec_pid": row["exec_pid"] if "exec_pid" in row.keys() else None,
                "exec_cree": row["exec_cree"] if "exec_cree" in row.keys() else None,
            }
        finally:
            conn.close()
    except Exception:
        return None


def _vivacite_par_defaut(pid, cree):
    """Vivacite par defaut : forge_task_executor._vivacite_processus (import paresseux)."""
    try:
        from tools.forge_task_executor import _vivacite_processus
        return _vivacite_processus(pid, cree)
    except Exception:
        try:
            from forge_task_executor import _vivacite_processus
            return _vivacite_processus(pid, cree)
        except Exception:
            return None


def _emettre_resultat_par_defaut(task_id: str, payload: dict) -> None:
    """Emission par defaut via le hub MCP (task action=result, sur le modele de _clore_delegation).
    Un echec se journalise sans lever."""
    try:
        from tools.forge_task_executor import _hub_call, _jeton_de_la_brique
    except Exception:
        try:
            from forge_task_executor import _hub_call, _jeton_de_la_brique
        except Exception:
            logging.getLogger("forge_worktree").warning(
                "[reconciliateur] emission impossible : forge_task_executor introuvable")
            return
    try:
        token = _jeton_de_la_brique()
        _hub_call("task", {
            "action": "result",
            "task_id": task_id,
            "intent": payload.get("intent", "ERR_INTERNAL"),
            "result": json.dumps(payload, ensure_ascii=False)
        }, token, timeout=30)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").warning(
            "[reconciliateur] echec emission resultat pour %s (%s: %s)",
            task_id, type(exc).__name__, exc
        )


def _clore_tache_session_perdue(tasks_db: Path | str | None, task_id: str,
                                suffixe_result: str, pointer_ref: str,
                                emettre=None) -> bool:
    """Clot une tache a mort prouvee :
    UPDATE tasks SET status='failed', cause_echec='SESSION_PERDUE',
    result=COALESCE(result,'')||suffixe_result, updated_at=...
    WHERE id=? AND status='running'.
    Puis UN appel emettre(task_id, {intent:'ERR_INTERNAL', status_code:'SESSION_PERDUE', pointer_ref: pointer_ref}).
    Une tache deja terminale (done/failed/cancelled) n'est ni reecrite ni re-annoncee.
    """
    import datetime
    import sqlite3
    db = Path(tasks_db) if tasks_db else ROOT / "sandbox" / "tasks.db"
    if not db.is_file():
        return False
    modifie = False
    try:
        conn = sqlite3.connect(str(db))
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            set_clauses = ["status = 'failed'"]
            params = []
            if "cause_echec" in cols:
                set_clauses.append("cause_echec = 'SESSION_PERDUE'")
            if "result" in cols:
                set_clauses.append("result = COALESCE(result, '') || ?")
                params.append(suffixe_result)
            if "updated_at" in cols:
                set_clauses.append("updated_at = ?")
                params.append(datetime.datetime.now(datetime.timezone.utc).isoformat())
            sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ? AND status = 'running'"
            params.append(task_id)
            cur = conn.execute(sql, params)
            modifie = cur.rowcount > 0
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").warning(
            "[reconciliateur] echec cloture tache %s en base (%s: %s)", task_id, type(exc).__name__, exc)
        return False

    if modifie:
        fn_emettre = emettre if emettre is not None else _emettre_resultat_par_defaut
        payload = {
            "intent": "ERR_INTERNAL",
            "status_code": "SESSION_PERDUE",
            "pointer_ref": pointer_ref,
            # Le hub REMPLACE result par cette charge (forge_mcp_registry:6946) : la trace y vit.
            "detail": suffixe_result,
        }
        try:
            fn_emettre(task_id, payload)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("forge_worktree").warning(
                "[reconciliateur] echec emission resultat pour %s (%s: %s)", task_id, type(exc).__name__, exc)
        return True
    return False


def _scorecard_livraison(wt: Path, fichiers: list[str]) -> tuple[str, str]:
    """Evalue le verdict de livraison via scorecard_de_livraison.
    Rend (verdict, detail). verdict est le nom du QualityGrade (OPTIMAL/PARTIAL/REJECTED/UNRATED)."""
    try:
        from app.forge_scorecard import scorecard_de_livraison
    except Exception:
        try:
            from nokido_agent.app.forge_scorecard import scorecard_de_livraison
        except Exception:
            try:
                import sys
                if str(ROOT) not in sys.path:
                    sys.path.insert(0, str(ROOT))
                from app.forge_scorecard import scorecard_de_livraison
            except Exception as exc:
                logging.getLogger("forge_worktree").warning(
                    "[reconciliateur] import scorecard_de_livraison impossible (%s): %s", type(exc).__name__, exc)
                return "UNRATED", str(exc)[:80]
    try:
        sc = scorecard_de_livraison(wt, fichiers)
        grade_nom = getattr(sc.grade, "name", str(sc.grade))
        return grade_nom, getattr(sc, "critique", "")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("forge_worktree").warning(
            "[reconciliateur] scorecard_de_livraison impossible (%s): %s", type(exc).__name__, exc)
        return "UNRATED", str(exc)[:80]


def _analyser_porcelain_z(st_z: bytes | str) -> tuple[list[str], list[str]]:
    """Parse git status --porcelain -z.
    Rend (toutes_entrees, chemins_a_committer)."""
    toutes = []
    chemins = []
    st_z_bytes = st_z.encode("utf-8") if isinstance(st_z, str) else st_z
    morceaux = st_z_bytes.split(b"\x00")
    i = 0
    n = len(morceaux)
    while i < n:
        chunk = morceaux[i]
        if not chunk:
            i += 1
            continue
        code = chunk[:2].decode("utf-8", "replace")
        path_bytes = chunk[3:]
        path = path_bytes.decode("utf-8", "replace")
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            if i + 1 < n:
                i += 1
                orig_path = path
                path = morceaux[i].decode("utf-8", "replace")
        toutes.append(f"{code} {path}")
        if path and path != ".nokido.agent" and path != "nokido.lock":
            chemins.append(path)
        i += 1
    return toutes, chemins


def _trouver_nom_branche_preserve(root: Path, agent: str, court: str) -> str:
    """Trouve un nom de branche preserve qui n'ecrase JAMAIS une branche existante."""
    base = f"preserve/{agent.lower()}/{court}"
    nom = base
    idx = 1
    while True:
        r = _git(["rev-parse", "--verify", "-q", f"refs/heads/{nom}"], cwd=root)
        if r.returncode != 0:
            return nom
        nom = f"{base}_{idx}"
        idx += 1


def reconcilier_worktree_orphelin(wt: Path, root: Path | None = None, tasks_db: Path | None = None,
                                  registre: set[str] | None = None,
                                  notifier=None, vivacite=None, emettre=None) -> dict:
    """Reconcilie un worktree orphelin jusqu'au commit local preserve/<agent>/<court>.
    Ne fusionne JAMAIS dans alpha, ne pousse jamais, ne supprime jamais."""
    notifier = notifier or alerter_owner_reconciliation
    wt = Path(wt).resolve()
    root = Path(root) if root else ROOT

    # 1. Verification statut git -z (fail-safe)
    st = _git(["status", "--porcelain", "-z", "--untracked-files=all"], cwd=wt)
    if st.returncode != 0:
        err_msg = (st.stderr if isinstance(st.stderr, str) else st.stderr.decode("utf-8", "replace"))[:200]
        notifier(
            f"reconciliateur:illisible:{wt.name}",
            "WARN",
            f"Worktree {wt.name} ignore car statut git illisible : {err_msg}",
            "reconciliateur_boucle",
        )
        return {"action": "ignore", "motif": "statut_illisible", "worktree": str(wt)}

    # Extraction agent et court
    if wt.parent.name == "taches":
        # Le court n'a jamais de `_`, l'agent si : claude_headless_<court>, opencode_glm_<court>. Un `partition` lisait
        # l'agent `claude` : sa tache en vol restait invisible, et le worktree occupe etait committe (relecture 7/11).
        agent, _, court = wt.name.rpartition("_")
        if not agent or not court:
            notifier(f"reconciliateur:nom_illisible:{wt.name}", "WARN",
                     f"Worktree {wt.name} non touche : agent et tache illisibles dans son nom", "reconciliateur_boucle")
            return {"action": "ignore", "motif": "nom_illisible", "worktree": str(wt)}
    else:
        agent = wt.name
        court = "wip"

    # 2. Tache en vol (tri-etat)
    en_vol, tache_resolue = _tache_est_en_vol(court, agent, tasks_db, avec_info=True)
    if en_vol == "INCONNU":
        notifier(
            f"reconciliateur:tache_inconnue:{agent}:{court}",
            "WARN",
            f"Worktree {wt.name} non touche car etat de vol de la tache INCONNU (tasks.db indisponible)",
            "reconciliateur_boucle",
        )
        return {"action": "ignore", "motif": "etat_tache_inconnu", "agent": agent, "court": court}

    tache_a_clore = None
    if tache_resolue is not None:
        if tache_resolue["status"] == "running":
            pid = tache_resolue.get("exec_pid")
            if pid is None:
                return {"action": "ignore", "motif": "tache_en_vol", "agent": agent, "court": court}
            fn_vivacite = vivacite if vivacite is not None else _vivacite_par_defaut
            v = fn_vivacite(pid, tache_resolue.get("exec_cree"))
            if v is None:
                notifier(
                    f"reconciliateur:vivacite_illisible:{agent}:{court}",
                    "WARN",
                    f"Worktree {wt.name} ignore car vivacite du pid {pid} illisible",
                    "reconciliateur_boucle",
                )
                return {"action": "ignore", "motif": "vivacite_illisible", "agent": agent, "court": court}
            if v is True:
                return {"action": "ignore", "motif": "tache_en_vol", "agent": agent, "court": court}
            # v is False : mort PROUVEE -> on continue la preservation puis on clot
            tache_a_clore = tache_resolue["id"]
        elif en_vol is True:
            return {"action": "ignore", "motif": "tache_en_vol", "agent": agent, "court": court}
    else:
        if en_vol is True:
            return {"action": "ignore", "motif": "tache_en_vol", "agent": agent, "court": court}

    # 3. Detection du travail non integre via porcelain -z
    toutes_lignes, chemins_a_committer = _analyser_porcelain_z(st.stdout)
    lignes_utiles = [
        l for l in toutes_lignes
        if not any(re.match(p, l) for p in ARTEFACTS_DE_PREUVE)
        and ".nokido.agent" not in l
        and "nokido.lock" not in l
    ]

    alpha_head = _git(["rev-parse", "alpha"], cwd=root).stdout.strip() if root.is_dir() else ""
    commits_avance = 0
    if alpha_head:
        rev_cnt = _git(["rev-list", "--count", "alpha..HEAD"], cwd=wt)
        if rev_cnt.returncode == 0:
            try:
                commits_avance = int(rev_cnt.stdout.strip() or "0")
            except ValueError:
                commits_avance = 0

    if not lignes_utiles and commits_avance == 0:
        return {"action": "ignore", "motif": "aucun_travail_non_integre", "worktree": str(wt)}

    cle_lot = f"{agent}:{court}"
    if registre is not None and cle_lot in registre and not lignes_utiles:
        return {"action": "ignore", "motif": "deja_traite", "worktree": str(wt)}

    # Commit du travail non committe s'il existe (SANS changer de branche)
    if lignes_utiles and chemins_a_committer:
        _git(["add", "--"] + chemins_a_committer, cwd=wt)
        c = _git(["commit", "-m", f"chore({agent}): preservation orphelin tache {court}"], cwd=wt)
        if c.returncode != 0:
            notifier(
                f"reconciliateur:refus_hook:{agent}:{court}",
                "WARN",
                f"Commit refuse par pre-commit hook pour {agent} {court} : {(c.stderr or c.stdout)[:200]}",
                "reconciliateur_boucle",
            )
            return {"action": "refus_hook", "agent": agent, "tache": court, "worktree": str(wt)}

    # 4. Branche preserve locale (NE DEPLACE JAMAIS la branche courante)
    branche_preserve = _trouver_nom_branche_preserve(root, agent, court)
    r_branch = _git(["branch", branche_preserve, "HEAD"], cwd=wt)
    if r_branch.returncode != 0:
        notifier(
            f"reconciliateur:branche_echec:{agent}:{court}",
            "WARN",
            f"Impossible de creer {branche_preserve} : {r_branch.stderr[:200]}",
            "reconciliateur_boucle",
        )
        return {"action": "echec", "motif": "branche_impossible", "worktree": str(wt)}

    # 5. Extraction sha et scorecard de livraison
    sha = _git(["rev-parse", "HEAD"], cwd=wt).stdout.strip()[:12]
    show_files = _git(["show", "--name-only", "--format=", sha], cwd=wt).stdout.splitlines()
    fichiers = [f.strip() for f in show_files if f.strip() and f.strip() != ".nokido.agent"]

    verdict, extrait = _scorecard_livraison(wt, fichiers)

    # 6. Commande de fusion et notification idempotente
    cmd_fusion = f"python tools/forge_merge_gate.py reconcilier {sha} {' '.join(fichiers)} --apply"
    detail = (
        f"agent={agent} tache={court} verdict={verdict} fichiers={len(fichiers)} "
        f"branche={branche_preserve} sha={sha} | fusion: {cmd_fusion}"
    )

    notifier(
        f"reconciliateur:lot_pret:{agent}:{court}",
        "INFO",
        detail,
        "reconciliateur_boucle",
    )

    if registre is not None:
        registre.add(cle_lot)
        registre.add(f"{cle_lot}:{sha}")
    _LOTS_MEMOIRE.add(cle_lot)

    if tache_a_clore:
        _clore_tache_session_perdue(
            tasks_db=tasks_db or (root / "sandbox" / "tasks.db"),
            task_id=tache_a_clore,
            suffixe_result=f"[SESSION_PERDUE] preserve {branche_preserve} sha {sha}",
            pointer_ref=f"{branche_preserve}@{sha}",
            emettre=emettre,
        )

    return {
        "action": "preserve",
        "agent": agent,
        "tache": court,
        "branche": branche_preserve,
        "sha": sha,
        "verdict": verdict,
        "fichiers": fichiers,
        "commande_fusion": cmd_fusion,
    }


def balayer_et_reconcilier(root: Path | None = None, wt_root: Path | None = None,
                           tasks_db: Path | None = None, max_worktrees: int = 3,
                           registre: set[str] | None = None, notifier=None,
                           vivacite=None, emettre=None) -> dict:
    """Balaye les worktrees orphelins et sauvegardes pour reconcilier les lots prets."""
    root = Path(root) if root else ROOT
    notifier = notifier or alerter_owner_reconciliation

    if not interrupteur_reconciliateur_actif(root):
        return {"actif": False, "raison": "interrupteur_coupe", "lots": []}

    if garde_ressources_au_rouge():
        return {"actif": True, "retenu": True, "raison": "garde_ressources_au_rouge", "lots": []}

    wt_base = Path(wt_root) if wt_root else (root.parent / "nokido_worktrees")
    reg_path = root / "sandbox" / "reconciliateur_lots.json"
    if registre is not None:
        reg = registre
        reg_illisible = False
    else:
        reg, reg_illisible = _charger_registre_reconciliation(reg_path)

    # Point 6 : Si le registre est illisible, abstention stricte pour eviter re-alertes en double
    if reg_illisible:
        notifier(
            "reconciliateur:registre_illisible",
            "WARN",
            f"Registre de reconciliation {reg_path} illisible/corrompu : abstention de balayage",
            "reconciliateur_boucle",
        )
        return {"actif": True, "retenu": True, "raison": "registre_illisible", "lots": []}

    candidats: list[Path] = []

    # 1. Scanner les worktrees sous nokido_worktrees/taches
    taches_dir = wt_base / "taches"
    if taches_dir.is_dir():
        for d in sorted(taches_dir.iterdir()):
            if d.is_dir() and (d / ".git").exists() and d.resolve() != root.resolve():
                candidats.append(d)

    # 2. Scanner les worktrees d'agents directs sous nokido_worktrees
    if wt_base.is_dir():
        for d in sorted(wt_base.iterdir()):
            if d.name != "taches" and d.is_dir() and (d / ".git").exists() and d.resolve() != root.resolve():
                if not d.name.startswith("proof"):
                    candidats.append(d)

    lots = []
    traites = 0
    for wt in candidats:
        if traites >= max_worktrees:
            break
        res = reconcilier_worktree_orphelin(wt, root=root, tasks_db=tasks_db, registre=reg, notifier=notifier,
                                            vivacite=vivacite, emettre=emettre)
        if res.get("action") == "preserve":
            lots.append(res)
            traites += 1

    # 3. Scanner les sauvegardes dans sandbox/sauvegardes_executeurs/
    sauv_root = root / "sandbox" / "sauvegardes_executeurs"
    if sauv_root.is_dir():
        for ag_dir in sorted(sauv_root.iterdir()):
            if ag_dir.is_dir():
                for t_dir in sorted(ag_dir.iterdir()):
                    if t_dir.is_dir() and (t_dir / "manifeste.json").is_file():
                        cle_sauv = f"sauvegarde:{ag_dir.name}:{t_dir.name}"
                        try:
                            man = json.loads((t_dir / "manifeste.json").read_text(encoding="utf-8"))
                        except Exception as exc:  # noqa: BLE001
                            logging.getLogger("forge_worktree").warning(
                                "[reconciliateur] sauvegarde %s non traitee (%s)", t_dir.name, type(exc).__name__)
                            continue
                        if not isinstance(man, dict):
                            # JSON valide mais pas un objet : sauter CETTE sauvegarde, jamais tout le balayage.
                            logging.getLogger("forge_worktree").warning(
                                "[reconciliateur] sauvegarde %s non traitee (manifeste %s, objet attendu)",
                                t_dir.name, type(man).__name__)
                            continue

                        tache_id = man.get("tache")
                        if tache_id:
                            info = _info_tache_par_id(tasks_db or (root / "sandbox" / "tasks.db"), tache_id)
                            if info and info["status"] == "running":
                                pid = info.get("exec_pid")
                                if pid is not None:
                                    fn_viv = vivacite if vivacite is not None else _vivacite_par_defaut
                                    v = fn_viv(pid, info.get("exec_cree"))
                                    if v is False:
                                        chemin_sauv = str(t_dir).replace("\\", "/")
                                        _clore_tache_session_perdue(
                                            tasks_db=tasks_db or (root / "sandbox" / "tasks.db"),
                                            task_id=tache_id,
                                            suffixe_result=f"[SESSION_PERDUE] sauvegarde {chemin_sauv}",
                                            pointer_ref=chemin_sauv,
                                            emettre=emettre,
                                        )

                        if cle_sauv not in reg:
                            fics = man.get("fichiers", [])
                            cmd_s = f"python tools/forge_merge_gate.py reconcilier_sauvegarde {t_dir} {' '.join(fics)} --apply"
                            notifier(
                                f"reconciliateur:lot_pret_sauvegarde:{ag_dir.name}:{t_dir.name}",
                                "INFO",
                                f"sauvegarde agent={ag_dir.name} tache={t_dir.name} fichiers={len(fics)} | fusion: {cmd_s}",
                                "reconciliateur_boucle",
                            )
                            reg.add(cle_sauv)
                            lots.append({"action": "sauvegarde_signalee", "agent": ag_dir.name, "tache": t_dir.name, "cmd_fusion": cmd_s})

    if registre is None:
        _sauver_registre_reconciliation(reg, reg_path)

    return {"actif": True, "retenu": False, "lots": lots, "candidats_scannes": len(candidats)}


def _acquerir_verrou_reconciliateur(lock_file: Path):
    """Acquiert un verrou exclusif inter-processus non-bloquant. Rend un lock object ou None."""
    try:
        from filelock import FileLock
        lock = FileLock(str(lock_file), timeout=0)
        lock.acquire()
        return lock
    except Exception:  # noqa: BLE001
        return None


def reconcilier_orphelins_boucle(root: Path | None = None, intervalle_min_s: float | None = None) -> dict:
    """Point d'entree sovereign pour la boucle de maintenance (ex: TaskExecutor.run_loop).
    Garantit :
    - un intervalle minimal entre balayages (evite d'epuiser la machine si la boucle tourne vite)
    - une seule instance a la fois (verrou exclusif inter-executeurs)."""
    global _DERNIER_PASSAGE_BOUCLE
    import time
    root = Path(root) if root else ROOT
    intervalle = intervalle_min_s if intervalle_min_s is not None else _INTERVALLE_MIN_BOUCLE_S

    maintenant = time.time()
    if maintenant - _DERNIER_PASSAGE_BOUCLE < intervalle:
        return {"actif": True, "retenu": True, "saute_intervalle": True, "lots": []}

    lock_file = root / "sandbox" / "reconciliateur_boucle.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock = _acquerir_verrou_reconciliateur(lock_file)
    if lock is None:
        return {"actif": True, "retenu": True, "saute_concurrence": True, "lots": []}

    try:
        _DERNIER_PASSAGE_BOUCLE = time.time()
        return balayer_et_reconcilier(root=root)
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - muet-ok : le verrou tombe avec le processus, le balayage est deja rendu
            pass



if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
