# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : metacognition / immunitaire (organe, READ-ONLY)

ORGANE : INTEGRITE DE LIVRAISON — « ce qui est DECLARE fait l'est-il REELLEMENT ? ».

Gap MESURE (owner 2026-07-24, apres restart hub) : la roadmap SSoT a ete ecrite sur des
ATTESTATIONS d'agents jamais croisees avec le depot. Cas reel : la task P1 « gate RAM
intent-aware » est revenue {intent:OK_DONE, status_code:SUCCESS,
pointer_ref:"commit:0a880f22"} et donc `status=done` en base — or 0a880f22 est un commit
ANTERIEUR DE 37 MINUTES a la creation de la task (c'etait le P0 de quelqu'un d'autre).
Le travail n'avait jamais ete fait, et rien dans le corps ne l'a signale.

Trois angles morts de la meme famille, tous mesures le meme jour :
  1. `status=done` signifie « l'agent a REPONDU », jamais « le code EXISTE ».
  2. une file dont la surface ne draine plus accumule en silence (20 taches gelees,
     la plus vieille depuis juin) : personne ne se plaint, donc personne ne le voit.
  3. un commit local n'est pas un travail SAUVEGARDE : 9 commits non pousses au moment
     de la mesure, dont la totalite du chantier NPU de la veille.

STRICTEMENT READ-ONLY : il LIT (tasks.db + git) et EMET des findings. Il ne commit pas,
ne pousse pas, ne requalifie aucune task — agir appartient a l'owner ou a l'organe
proprietaire. Meme doctrine que forge_metric_integrity : la microglie signale
l'inflammation, elle ne recable pas le neurone.

Anti-dup (rag_fts + lecture des modules) : forge_scalable_oversight fait juger une sortie
par un PANEL LLM (verdict semantique, couteux) ; forge_metric_integrity traque le Goodhart
sur les SCORES internes ; forge_task_queue gere le cycle de vie des taches. AUCUN ne
confronte une attestation au REEL. Cet organe est transverse, passif et DETERMINISTE
(zero token : git + sqlite tranchent, pas un LLM).

CLI :
    LAFORGE_PYTHON app/forge_delivery_integrity.py --scan
    LAFORGE_PYTHON app/forge_delivery_integrity.py --history [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
GH_REPO = os.environ.get("LAFORGE_GH_REPO", "user/nokido")
TASKS_DB = ROOT / "sandbox" / "tasks.db"
SUPERREPO = ROOT.parent

# Une task encore pending/claimed au-dela de ce delai = file non drainee.
STALE_DAYS = 7
# Retard de push tolere avant de sonner.
UNPUSHED_WARN = 3
UNPUSHED_HIGH = 10

_SHA_RE = re.compile(r"commit:([0-9a-f]{7,40})")


def _rows(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


# Pourquoi le dernier appel git a echoue. `_git` rend `None` sans distinguer
# « git absent », « rc!=0 » et « spawn interdit » : trois causes qui demandent
# trois remedes opposes, et dont l'indistinction a fait refaire le meme
# diagnostic trois fois (2026-09-03, 2026-09-04 x2). Un logger.debug ne suffit
# pas — un debug non active est une cause INVISIBLE. On garde donc la derniere
# raison en memoire, lisible par l'appelant qui diagnostique.
DERNIERS_ECHECS_GIT: list[str] = []


def _note_echec(txt: str) -> None:
    DERNIERS_ECHECS_GIT.append(txt[:300])
    del DERNIERS_ECHECS_GIT[:-20]  # borne : c'est un journal de diagnostic


def _pourquoi_invisible(sub: Path) -> str:
    """ABSENT, ILLISIBLE ou PRESENT-SANS-.git : trois etats, jamais deux.

    `Path.exists()` rend `False` pour un chemin absent ET pour un chemin dont
    l'ACL refuse la traversee. Confondre les deux fabrique un faux negatif
    indetectable — meme remede que `forge_memory_compactor.audit`, qui force
    l'erreur a se nommer plutot que de la reduire a un booleen.
    """
    try:
        next(sub.iterdir(), None)
    except PermissionError:
        return "dossier du submodule ILLISIBLE depuis ce compte (PermissionError)"
    except FileNotFoundError:
        return "dossier du submodule ABSENT (submodule non initialise ?)"
    except OSError as exc:
        return "dossier du submodule illisible (%s)" % type(exc).__name__
    return "dossier lisible, mais son .git n'est pas visible"


def _git(repo: Path, *args: str) -> str | None:
    """Git en lecture seule. Retourne None si git est injoignable OU si l'appelant
    n'a pas le droit de spawner (sandbox WORKSPACE_GUARD) — dans ce cas l'organe se
    tait sur la dimension git au lieu de planter le tick homeostatique."""
    # `-C <racine>` change le repertoire COURANT. Mesure 2026-09-03 : `LaForgeTrusted`
    # ne peut pas s'y placer sur la racine du superrepo (son ACE n'y est pas heritee),
    # git sort en rc!=0, cette fonction rend None, et l'appelant lit ce silence comme
    # « rien a signaler ». Quand `.git` est un VRAI repertoire (cas du superrepo), on
    # NOMME le depot par `--git-dir` : le compte y a `(OI)(CI)(M)` et lit sans peine.
    # Pour un submodule, `.git` est un FICHIER (gitfile) et `-C` reste la bonne forme.
    #
    # Ne PAS ajouter `--work-tree` ici : mesure 2026-09-04, avec un repertoire courant
    # HORS de l'arbre, git applique un pathspec implicite tire du CWD et `ls-tree` sort
    # VIDE avec rc=0 -- deuxieme incarnation du meme symptome, cause differente.
    gitdir = repo / ".git"
    if gitdir.is_dir():
        base = ["git", "-c", "safe.directory=*", "--git-dir", str(gitdir)]
    else:
        base = ["git", "-c", "safe.directory=*", "-C", str(repo)]
    try:
        r = subprocess.run(
            [*base, *args],
            capture_output=True, text=True, timeout=20,
            # errors= obligatoire : un nom d'auteur accentue ou une sortie cp1252
            # ferait crasher le reader thread en mode texte -> organe muet.
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            return r.stdout.strip()
        _note_echec("git %s (%s) -> rc=%s err=%r"
                    % (" ".join(args), repo.name, r.returncode,
                       (r.stderr or "").strip()[:120]))
        return None
    except Exception as exc:
        # Distinguer le spawn INTERDIT du reste : sous `run action=python` le
        # WORKSPACE_GUARD leve sur `subprocess.Popen`, donc TOUS les appels
        # echouent et le scan rend « illisible » partout. C'est exact, mais si
        # la cause n'est pas nommee on l'attribue au COMPTE ou aux ACL et on
        # part corriger un probleme qui n'existe pas (mesure 2026-09-04 : j'ai
        # conclu a un defaut d'ACL depuis un vehicule de test qui interdisait
        # simplement de lancer git).
        _note_echec("git %s (%s) -> %s: %s"
                    % (" ".join(args), repo.name, type(exc).__name__, str(exc)[:120]))
        return None


def _as_utc(raw: str | None):
    """Normalise un timestamp. Les dates applicatives (tasks.db) sont naives et
    exprimees en UTC ; git rend de l'ISO avec offset. Comparer sans normaliser
    decalerait tout de 2 heures et fabriquerait de faux positifs."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# Enveloppe M2M qui REUSSIT / contenu qui ECHOUE. Deux marqueurs distincts, exiges
# ENSEMBLE : accuser sur un seul serait inventer une derive (cout asymetrique).
# Au-dela, une attestation contredite n'est plus actionnable : elle est archivee,
# pas resolue. Surchargeable pour un audit retrospectif complet.
_FENETRE_JOURS = int(os.environ.get("LAFORGE_INTEGRITY_WINDOW_DAYS", "7"))

_ATTEST_OK_RE = re.compile(r'"(?:status_code)"\s*:\s*"SUCCESS"|"(?:intent|intent_code)"\s*:\s*"OK_DONE"')
_ATTEST_KO_RE = re.compile(r'\\?"status\\?"\s*:\s*\\?"(?:ERROR|FAILED|TIMEOUT)\\?"'
                           r'|\\?"error\\?"\s*:\s*\\?"[^"\\]+')


def _scan_attestation_contredite() -> list[dict]:
    """L'enveloppe dit SUCCESS, le contenu qu'elle transporte dit ERROR.

    Motif MESURE le 24-07 : la task AGY `job_3418a105` rend
    `{"intent":"OK_DONE","status_code":"SUCCESS", "detail":"...
    {\\"status\\":\\"ERROR\\",\\"response\\":\\"\\",\\"error\\":\\"timeout waiting for
    response\\"}"}`. Le wrapper atteste la reussite du RELAIS, jamais celle du
    TRAVAIL — un appelant qui lit `status_code` conclut que la tache est faite.

    `_scan_false_attestations` ne pouvait pas le voir : il ne lit que les resultats
    citant un `commit:`. Une preuve absente n'est pas une preuve contredite.
    """
    out: list[dict] = []
    if not TASKS_DB.exists():
        return out
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
    try:
        rows = _rows(con, "SELECT id, agent, result, created_at FROM tasks "
                          "WHERE status IN ('done','completed') AND result IS NOT NULL")
    finally:
        con.close()

    # FENETRE D'ACTIONNABILITE. Un detecteur qui crie eternellement sur du passe
    # devient un bruit qu'on apprend a ignorer — et c'est exactement ce qui rend un
    # capteur inutile le jour ou il a raison. Une attestation contredite se corrige
    # a chaud (relancer, reparer le maillon) ; passe ce delai elle releve de
    # l'archive, pas de l'alerte. Le fait reste en base, il cesse d'etre signale.
    limite = datetime.now(tz=timezone.utc) - timedelta(days=_FENETRE_JOURS)

    for tid, agent, result, cree in rows:
        cree_dt = _as_utc(cree)
        if cree_dt is not None and cree_dt < limite:
            continue
        txt = result or ""
        if not _ATTEST_OK_RE.search(txt):
            continue
        ko = _ATTEST_KO_RE.search(txt)
        if not ko:
            continue
        out.append({
            "kind": "attestation_contredite",
            "target": str(tid),
            "severity": "high",
            "detail": (f"task {tid} (agent {agent}) attestee SUCCESS alors que son "
                       f"contenu porte {ko.group(0)[:60]!r} — le relais a abouti, "
                       f"pas le travail"),
        })
    return out


def _scan_false_attestations() -> list[dict]:
    """Une preuve doit etre POSTERIEURE a ce qu'elle prouve.

    Un `pointer_ref: commit:<sha>` anterieur a la creation de la task ne peut
    pas en etre le livrable : le code existait avant que le travail soit demande.
    """
    out: list[dict] = []
    if not TASKS_DB.exists():
        return out
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
    try:
        rows = _rows(con, "SELECT id, agent, created_at, result FROM tasks "
                          "WHERE status IN ('done','completed') AND result LIKE '%commit:%'")
    finally:
        con.close()

    for tid, agent, created, result in rows:
        m = _SHA_RE.search(result or "")
        if not m:
            continue
        sha = m.group(1)
        created_dt = _as_utc(created)
        raw = _git(ROOT, "show", "-s", "--format=%cI", sha)
        if raw is None:
            # git muet : on ne peut pas distinguer « sha absent » de « git indisponible ».
            # Cout des deux erreurs asymetrique -> on s'abstient d'accuser.
            continue
        commit_dt = _as_utc(raw)
        if commit_dt is None or created_dt is None:
            continue
        if commit_dt < created_dt:
            delta = created_dt - commit_dt
            out.append({
                "kind": "attestation_commit_anterieur",
                "target": f"{tid}:{sha}",
                "severity": "high",
                "detail": (f"task {tid} (agent {agent}) marquee done en citant {sha}, "
                           f"commit anterieur de {int(delta.total_seconds() // 60)} min "
                           f"a la creation de la task — ne peut pas etre son livrable"),
            })
    return out


def _scan_stale_queue() -> list[dict]:
    """File non drainee : des taches attendent un consommateur qui ne vient plus."""
    out: list[dict] = []
    if not TASKS_DB.exists():
        return out
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
    try:
        rows = _rows(con, "SELECT agent, status, COUNT(*), MIN(created_at) FROM tasks "
                          "WHERE status IN ('pending','claimed') GROUP BY agent, status")
    finally:
        con.close()

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=STALE_DAYS)
    for agent, status, n, oldest in rows:
        oldest_dt = _as_utc(oldest)
        if oldest_dt is None or oldest_dt > cutoff:
            continue
        age_d = (datetime.now(tz=timezone.utc) - oldest_dt).days
        out.append({
            "kind": "file_non_drainee",
            "target": f"{agent}:{status}",
            "severity": "high" if age_d >= 2 * STALE_DAYS else "med",
            "detail": (f"{n} task(s) {status} pour {agent}, la plus ancienne a {age_d} j "
                       f"— la surface qui doit drainer cette file ne tourne pas"),
        })
    return out


def _scan_unpushed() -> list[dict]:
    """Un commit local n'est pas un travail sauvegarde."""
    out: list[dict] = []
    branch = _git(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        return out
    upstream = _git(ROOT, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream:
        out.append({
            "kind": "branche_sans_upstream", "target": branch, "severity": "med",
            "detail": f"la branche {branch} ne suit aucun remote — rien ne partira jamais",
        })
        return out
    count = _git(ROOT, "rev-list", "--count", f"{upstream}..HEAD")
    try:
        n = int(count)
    except (TypeError, ValueError):
        return out
    if n >= UNPUSHED_WARN:
        out.append({
            "kind": "commits_non_pousses",
            "target": f"{branch}->{upstream}",
            "severity": "high" if n >= UNPUSHED_HIGH else "med",
            "detail": (f"{n} commit(s) locaux jamais pousses vers {upstream} — "
                       f"le travail declare livre n'existe que sur cette machine"),
        })
    return out


def _gh_env() -> dict:
    """Environnement pour `gh`, avec le jeton lu AU COFFRE si besoin.

    Le helper d'authentification de `gh` est per-user : il existe pour le compte
    owner et PAS pour les comptes de service qui font tourner le tick (mesure
    2026-07-24 : `gh` y sort rc=4 « please run: gh auth login »). Sans ce relais,
    le scanner CI serait muet exactement la ou il doit veiller.

    Le jeton transite par l'ENVIRONNEMENT du sous-process, jamais par la ligne de
    commande : le hub journalise les args de `run`, donc un secret colle dans une
    commande finirait dans l'audit puis dans le RAG (meme precaution que
    tools/forge_push_sovereign.py).
    """
    env = dict(os.environ)
    if env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"):
        return env
    try:
        app_dir = str(ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        tok = get_secret("GITHUB_TOKEN")
        if tok:
            env["GH_TOKEN"] = tok
    except Exception:
        pass
    return env


def _gh(*args: str) -> str | None:
    """GitHub CLI en lecture seule. None si `gh` est absent, non authentifie ou
    injoignable — l'organe se tait alors sur la dimension CI plutot que d'accuser."""
    try:
        r = subprocess.run(
            ["gh", *args, "--repo", GH_REPO],
            capture_output=True, text=True, timeout=45,
            encoding="utf-8", errors="replace", env=_gh_env(),
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _scan_ci_failures() -> list[dict]:
    """Un push accepte n'est pas une livraison verte.

    Angle mort signale par l'owner le 2026-07-24 : la CI echouait a CHAQUE push
    depuis au moins le 09-07 — deux semaines de rouge — sans que personne ne
    regarde. Le gate egress dit OK, le remote accepte les refs, et on en conclut
    que c'est livre ; ce qui se passe APRES le push n'etait dans le champ de
    vision d'aucun organe. Cause reelle du jour : le workflow pointait un
    environnement conda inexistant (sequelle de renommage).

    On ne juge que le DERNIER run termine de chaque workflow, pour ne pas
    ressortir un echec deja corrige.
    """
    out: list[dict] = []
    branch = _git(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        return out
    raw = _gh("run", "list", "--branch", branch, "--limit", "30",
              "--json", "conclusion,status,name,headSha,createdAt,url")
    if not raw:
        # « CI verte » et « je n'ai pas pu regarder » rendraient tous deux une liste
        # vide : on DIT le silence au lieu de le laisser passer pour un feu vert.
        # (`gh` n'est authentifie que pour le compte owner, et le bac a sable n'a
        # pas de sortie reseau -> deux facons de devenir aveugle sans le savoir.)
        return [{
            "kind": "ci_non_observable",
            "target": branch,
            "severity": "low",
            "detail": ("impossible d'interroger les runs GitHub (gh absent, non "
                       "authentifie, ou hors reseau) — l'absence d'echec signale "
                       "ici n'est PAS une preuve que la CI est verte"),
        }]
    try:
        runs = json.loads(raw)
    except Exception:
        return out

    # gh rend du plus recent au plus ancien : on regroupe par workflow en gardant l'ordre.
    per_wf: dict[str, list[dict]] = {}
    for r in runs:
        if r.get("status") != "completed":
            continue
        per_wf.setdefault(r.get("name") or "?", []).append(r)

    for name, rs in per_wf.items():
        if not rs or rs[0].get("conclusion") != "failure":
            continue  # dernier run vert -> rien a signaler, meme si l'historique est rouge
        n = 0
        for r in rs:  # serie d'echecs, coupee au premier succes
            if r.get("conclusion") != "failure":
                break
            n += 1
        head = rs[0]
        out.append({
            "kind": "ci_en_echec",
            "target": name,
            "severity": "high",
            "detail": (f"le dernier run termine du workflow '{name}' sur {branch} est en "
                       f"ECHEC ({n} consecutif(s), commit {(head.get('headSha') or '')[:8]}) — "
                       f"un push accepte n'est pas une livraison verte. {head.get('url') or ''}"),
        })
    return out


def _scan_uncommitted() -> list[dict]:
    """Du travail modifie mais jamais commite — l'etage AVANT le push.

    `--ignore-submodules=all` est deliberé : sans lui, un submodule casse fait
    sortir la commande en rc!=0 et le scanner redevient muet (meme piege que le
    drift). On ne juge pas le contenu : d'autres surfaces editent le meme arbre,
    on signale seulement qu'il dort depuis longtemps.
    """
    out: list[dict] = []
    changed = _git(ROOT, "diff", "--name-only", "--ignore-submodules=all")
    staged = _git(ROOT, "diff", "--cached", "--name-only", "--ignore-submodules=all")
    files = {f for f in ((changed or "") + "\n" + (staged or "")).splitlines() if f.strip()}
    if not files:
        return out

    now = datetime.now(tz=timezone.utc)
    oldest_days = 0
    for rel in files:
        try:
            mt = (ROOT / rel).stat().st_mtime
        except OSError:
            continue
        age = (now - datetime.fromtimestamp(mt, tz=timezone.utc)).days
        oldest_days = max(oldest_days, age)

    if oldest_days >= STALE_DAYS:
        out.append({
            "kind": "travail_non_commite",
            "target": f"{len(files)} fichier(s)",
            "severity": "med",
            "detail": (f"{len(files)} fichier(s) tracke(s) modifie(s) et non commite(s), "
                       f"le plus ancien depuis {oldest_days} j — un travail qui n'est ni "
                       f"commite ni pousse n'existe pour personne d'autre"),
        })
    return out


def _submodules_declares() -> tuple[list[str], str | None]:
    """Chemins des submodules, lus dans l'ARBRE GIT plutot que dans `.gitmodules`.

    Mesure 2026-09-04 : sous `LaForgeTrusted` — le seul compte qui puisse
    committer le superrepo — `.gitmodules` est ILLISIBLE (`PermissionError`),
    alors que `Path.exists()` y rend True : le fichier existe, sa LECTURE est
    refusee. L'ancienne lecture tombait donc dans `except OSError: return out`
    et rendait « aucun drift » sur un gitlink retarde de 22 commits. Une source
    qui se tait, prise pour une source qui dit non — et le diagnostic affichait
    `.gitmodules : True`, ce qui achevait de rassurer.

    L'arbre git porte la MEME information (`mode 160000`) et il est lisible par
    ce compte, qui a `(OI)(CI)(M)` sur le `.git`. Aucune ACL a elargir : c'etait
    la mauvaise SOURCE, pas un droit manquant. Bonus de robustesse — un gitlink
    present dans l'arbre mais absent de `.gitmodules` est vu lui aussi.

    Rend (chemins, None) ou ([], raison) : jamais une liste vide muette.
    """
    arbre = _git(SUPERREPO, "ls-tree", "HEAD")
    if arbre:
        liens = [l.split("\t", 1)[1].strip()
                 for l in arbre.splitlines()
                 if l.startswith("160000") and "\t" in l]
        if liens:
            return liens, None
    try:
        txt = (SUPERREPO / ".gitmodules").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return [], None  # pas de submodule declare : il n'y a reellement rien a dire
    except OSError as exc:
        return [], ("ni l'arbre git ni .gitmodules ne sont lisibles depuis ce compte "
                    "(%s sur .gitmodules)" % type(exc).__name__)
    return [p.strip() for p in re.findall(r"^\s*path\s*=\s*(.+)$", txt,
                                          flags=re.MULTILINE)], None


def _scan_submodule_drift() -> list[dict]:
    """Le superrepo pointe-t-il encore un SHA perime du submodule ?

    Compare le SHA ENREGISTRE dans l'arbre du superrepo (`ls-tree`) au HEAD reel de
    chaque submodule. Volontairement du plumbing et non `git status` : un seul
    submodule casse fait sortir le status global en rc!=0 (mesure ici :
    « fatal: this operation must be run in a work tree » sur modelcontextprotocol),
    ce qui rendrait ce scanner MUET sur tous les autres — le defaut exact que cet
    organe est cense denoncer.
    """
    out: list[dict] = []
    paths, err = _submodules_declares()
    if err:
        out.append({
            "kind": "submodule_illisible",
            "target": ".gitmodules",
            "severity": "high",
            "detail": err + " — AUCUN submodule n'a pu etre examine ; ne pas lire "
                            "ce resultat comme « aucun drift »",
        })
        return out

    for path in (p.strip() for p in paths):
        sub = SUPERREPO / path
        if not (sub / ".git").exists():
            # Sortie MUETTE historique, et le trou par lequel tout passait : le
            # garde a trois etats est pose douze lignes plus bas, donc il n'avait
            # jamais l'occasion de parler. Mesure 2026-09-04 : l'outil de bump
            # annoncait « aucun drift » alors que le gitlink de Nokido etait
            # 22 commits en retard, et que les trois formes de lecture du gitlink
            # fonctionnent depuis le compte sandbox.
            #
            # Un submodule DECLARE dans .gitmodules dont on ne voit pas le `.git`
            # est un fait a signaler. Le seul cas ou se taire est juste, c'est le
            # submodule volontairement non initialise — et il se reconnait a son
            # dossier ABSENT, pas a un `.exists()` qui rend False sans dire
            # pourquoi.
            raison = _pourquoi_invisible(sub)
            if "ABSENT" in raison:
                continue
            out.append({
                "kind": "submodule_illisible",
                "target": path,
                "severity": "med",
                "detail": ("%s : %s — ce n'est PAS une absence de derive. Relancer "
                           "sous un compte qui lit le submodule avant de conclure"
                           % (path, raison)),
            })
            continue
        recorded = _git(SUPERREPO, "ls-tree", "HEAD", path)
        real = _git(sub, "rev-parse", "HEAD")
        if not recorded or not real:
            # NE PAS se taire ici. Un `continue` muet transforme « je n'ai pas pu
            # lire » en « rien a signaler » : c'est ce qui a laisse le gitlink de
            # Nokido 47 commits en retard pendant que l'outil annoncait « aucun
            # drift » (2026-09-03 puis 2026-09-04, deux causes differentes). Trois
            # etats, jamais deux : a jour · en derive · ILLISIBLE.
            out.append({
                "kind": "submodule_illisible",
                "target": path,
                "severity": "med",
                "detail": ("pointeur %s / HEAD %s — le scan n'a PAS pu regarder ; ce "
                           "n'est pas une absence de derive, et il ne faut pas le lire "
                           "comme tel" % ("lu" if recorded else "ILLISIBLE",
                                          "lu" if real else "ILLISIBLE")),
            })
            continue
        m = re.search(r"\b([0-9a-f]{40})\b", recorded)
        if not m or m.group(1) == real:
            continue
        ahead = _git(sub, "rev-list", "--count", f"{m.group(1)}..{real}")
        n = ahead if (ahead or "").isdigit() else "?"
        out.append({
            "kind": "submodule_non_bumpe",
            "target": path,
            "severity": "med",
            "detail": (f"le superrepo pointe {m.group(1)[:8]} pour {path} alors que son "
                       f"HEAD reel est {real[:8]} ({n} commit(s) d'avance) — un clone "
                       f"frais ne recupererait pas le travail commite dans le submodule"),
        })
    return out


def ack(kind: str, target: str, motif: str = "") -> bool:
    """Acquitter un signal : la CAUSE est traitee, l'enregistrement reste.

    La fenetre d'actionnabilite ne suffit pas — un signal du jour meme peut etre
    deja resolu (mesure 24-07 : l'attestation contredite de job_3418a105 tenait a
    un writer qui perdait l'enonce ; le writer repare, le signal continuait de
    sonner). Sans acquittement, le detecteur reste bruyant sur du corrige, et un
    detecteur bruyant finit ignore le jour ou il a raison.
    """
    import hashlib

    h = hashlib.md5((kind + target).encode()).hexdigest()[:16]
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        _ensure_schema(con)
        cur = con.execute(
            "UPDATE delivery_integrity_findings SET acked_at=?, ack_motif=? WHERE id=?",
            (datetime.now(tz=timezone.utc).isoformat(timespec="seconds"), motif[:300], h),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS delivery_integrity_findings ("
                "id TEXT PRIMARY KEY, kind TEXT, target TEXT, severity TEXT, "
                "detail TEXT, created_at TEXT)")
    cols = {r[1] for r in con.execute("PRAGMA table_info(delivery_integrity_findings)")}
    for nom, typ in (("acked_at", "TEXT"), ("ack_motif", "TEXT")):
        if nom not in cols:
            con.execute(f"ALTER TABLE delivery_integrity_findings ADD COLUMN {nom} {typ}")


def scan() -> dict:
    findings = (_scan_false_attestations() + _scan_attestation_contredite()
                + _scan_stale_queue()
                + _scan_unpushed() + _scan_uncommitted() + _scan_submodule_drift()
                + _scan_ci_failures())
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        _ensure_schema(con)
        acquittes = {r[0] for r in con.execute(
            "SELECT id FROM delivery_integrity_findings WHERE acked_at IS NOT NULL")}
        stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        ins = 0
        import hashlib
        retenus = []
        for f in findings:
            h = hashlib.md5((f["kind"] + f["target"]).encode()).hexdigest()[:16]
            if h in acquittes:
                continue
            retenus.append(f)
            try:
                # Colonnes NOMMEES : le schema s'etend (acked_at, ack_motif) et un
                # INSERT positionnel casse des le premier ALTER TABLE.
                con.execute(
                    "INSERT INTO delivery_integrity_findings "
                    "(id, kind, target, severity, detail, created_at) VALUES (?,?,?,?,?,?)",
                    (h, f["kind"], f["target"], f["severity"], f["detail"], stamp))
                ins += 1
            except sqlite3.IntegrityError:
                con.execute("UPDATE delivery_integrity_findings SET detail=?, created_at=? "
                            "WHERE id=?", (f["detail"], stamp, h))
        con.commit()
        return {"findings": retenus, "count": len(retenus), "new_or_updated": ins,
                "acquittes": len(findings) - len(retenus)}
    finally:
        con.close()


def history(limit: int = 20) -> list[dict]:
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        rows = _rows(con, "SELECT kind, target, severity, detail, created_at "
                          "FROM delivery_integrity_findings ORDER BY created_at DESC LIMIT ?",
                     (limit,))
        return [{"kind": a, "target": b, "severity": c, "detail": d, "at": e}
                for a, b, c, d, e in rows]
    finally:
        con.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description="Integrite de livraison (declare vs reel)")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    if a.history:
        print(json.dumps(history(a.limit), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(scan(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
