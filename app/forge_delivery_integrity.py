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
Seule ecriture : `ack` (l'enregistrement reste). Depuis le 7/11, `remesurer` relit le fait PRESENT d'un constat ;
c'est forge_remediation.check_delivery_integrity qui acquitte et depose, sous `armed`.

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
GH_REPO = os.environ.get("LAFORGE_GH_REPO", "Nokido-labs/nokido-private")
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


_FUSEAU_LOCAL = None   # None = fuseau du poste ; un test le FIXE pour etre deterministe sur tout runner


def _creation_au_plus_tot(raw: str | None):
    """Instant UTC le plus TOT plausible d'une date de tasks.db.

    Mesure du 15/10 : tasks.db porte des dates NAIVES ecrites en HEURE LOCALE (tache deposee a 12:25 locale,
    enregistree `12:25:16`), alors que le test du 23/07 les supposait en UTC -- plusieurs ecrivains, deux
    conventions. Lire une date naive comme de l'UTC la decalait de +2 h (CEST) et a fabrique deux fausses
    accusations contre AGY (commits 20 et 22 min APRES la creation, lus « 97-99 min avant »). Une date naive est
    donc AMBIGUE : on prend la plus tot des deux lectures -- on n'accuse que ce qui est vrai dans les deux."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    en_local = (dt.replace(tzinfo=_FUSEAU_LOCAL) if _FUSEAU_LOCAL is not None else dt.astimezone()).astimezone(
        timezone.utc)
    return min(dt.replace(tzinfo=timezone.utc), en_local)


_RE_PTR_COMMIT = re.compile(r'\\?"pointer_ref\\?"\s*:\s*\\?"commit:([0-9a-f]{7,40})')
# Une attestation de succes : intent OK_DONE (M2M) ou status_code SUCCESS (enveloppe AGY sans intent).
_RE_OK_DONE = re.compile(r'\\?"(?:intent\\?"\s*:\s*\\?"OK_DONE|status_code\\?"\s*:\s*\\?"SUCCESS)')


def _sha_atteste(result) -> str | None:
    """Sha du `pointer_ref: commit:` de la DERNIERE enveloppe OK_DONE du resultat (echappee ou non), sinon None."""
    txt = str(result or "")
    oks = list(_RE_OK_DONE.finditer(txt))
    if not oks:
        return None
    debut = txt.rfind("{", 0, oks[-1].start())
    fin = txt.find("}", oks[-1].end())
    m = _RE_PTR_COMMIT.search(txt[debut if debut >= 0 else 0:fin if fin >= 0 else len(txt)])
    return m.group(1) if m else None


_RE_HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
# Constat de l'EXECUTEUR (tools/forge_task_executor.py `_effet_observe`, stocke en tete par `_mark_done` sous la forme
# « <effet> | <reponse de l'agent> »). Meme forme stricte que `_statut_artefact`.
_RE_EFFET_OBSERVE = re.compile(r"\[effet observe\]\s*commits produits\s*:\s*(\d+|ILLISIBLE)\s*\([^)]*\)\s*;"
                               r"\s*fichiers non commites\s*:\s*\d+")


def _sha_dans_consigne(sha: str, description) -> bool:
    """Le sha figure-t-il dans la consigne, SOUS QUELQUE FORME QUE CE SOIT ? 7/11 : « CI de reference 50221f9ca »
    (en clair) etait lu comme une fausse attestation, seule la forme `commit:<sha>` etait reconnue. Prefixe dans les
    deux sens : la consigne et l'attestation n'abregent pas le sha a la meme longueur."""
    s = str(sha or "").lower()
    if len(s) < 7:
        return False
    return any(t.startswith(s) or s.startswith(t) for t in _RE_HEX.findall(str(description or "").lower()))


def _commits_observes(result) -> int | None:
    """Commits produits selon l'EXECUTEUR, None si non dit (UNKNOWN != NO).

    Seule la TETE fait foi : le texte avant le premier « | », que l'executeur ecrit avant la reponse de l'agent. Un
    marqueur recopie dans la prose de l'agent (sans tete d'executeur, ou apres elle) ne vaut rien. Limite connue,
    la meme que `_constat_executeur` : une prose qui imprimerait la forme exacte suivie d'un « | » serait
    indiscernable -- elle ne peut qu'ADOUCIR un constat, jamais en fabriquer un."""
    tete, sep, _ = str(result or "").partition(" | ")
    if not sep:
        return None
    m = _RE_EFFET_OBSERVE.search(tete)
    if not m or not m.group(1).isdigit():
        return None
    return int(m.group(1))


def _juger_attestation(description, result, sha: str, created) -> dict:
    """Juge une attestation `commit:<sha>` -> {"verdict", "motif", "commits"}. Partage par le scan et le soin.

    RECOPIE   : sha dans la consigne (toute forme) ou livrable reel observe par l'executeur -> pas d'accusation ;
    ANTERIEUR : commit anterieur a la creation, hors consigne ou 0 commit observe -> accusation `high` ;
    POSTERIEUR: le commit peut etre le livrable ;
    INCONNU   : git muet ou date illisible -> on s'abstient (cout asymetrique).
    Le texte de l'executeur PRIME : 0 commit observe garde l'accusation meme si le sha est dans la consigne (forme
    job_af6dbf75). Marqueur absent : on ne conclut pas, le jugement est celui d'avant (ni adouci ni aggrave)."""
    n = _commits_observes(result)
    if n is not None and n > 0:
        return {"verdict": "RECOPIE", "commits": n,
                "motif": "livrable reel observe par l'executeur (%d commit(s)), l'attestation designe un autre sha" % n}
    if n != 0 and _sha_dans_consigne(sha, description):
        return {"verdict": "RECOPIE", "commits": n, "motif": "sha %s present dans la consigne" % sha}
    raw = _git(ROOT, "show", "-s", "--format=%cI", sha)
    created_dt = _creation_au_plus_tot(created)
    commit_dt = _as_utc(raw) if raw is not None else None
    if commit_dt is None or created_dt is None:
        return {"verdict": "INCONNU", "commits": n,
                "motif": "git muet ou date illisible : ni accusation ni acquittement"}
    if commit_dt >= created_dt:
        return {"verdict": "POSTERIEUR", "commits": n, "motif": "commit %s posterieur a la creation" % sha}
    return {"verdict": "ANTERIEUR", "commits": n,
            "minutes": int((created_dt - commit_dt).total_seconds() // 60),
            "motif": ("0 commit observe par l'executeur" if n == 0 else
                      "marqueur de l'executeur absent : non conclu, signal garde")}


def _scan_false_attestations() -> list[dict]:
    """Une preuve doit etre POSTERIEURE a ce qu'elle prouve.

    Un `pointer_ref: commit:<sha>` anterieur a la creation de la task ne peut
    pas en etre le livrable : le code existait avant que le travail soit demande.
    La creation se lit au plus TOT (`_creation_au_plus_tot`) : une date naive est ambigue, et le cout des deux
    erreurs n'est pas symetrique -- accuser a tort un agent coute plus que rater un cas douteux.
    7/11 : le jugement vit dans `_juger_attestation`, partage avec le soin (`remesurer`).
    """
    out: list[dict] = []
    if not TASKS_DB.exists():
        return out
    con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
    try:
        # description lue si la colonne existe : un SELECT en echec rendrait [] en silence (detecteur muet).
        cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
        desc_col = "description" if "description" in cols else "NULL"
        rows = _rows(con, f"SELECT id, agent, created_at, {desc_col}, result FROM tasks "
                          "WHERE status IN ('done','completed') AND result LIKE '%commit:%'")
    finally:
        con.close()

    for tid, agent, created, description, result in rows:
        # 28/10 : seul le pointeur de la DERNIERE enveloppe OK_DONE est une attestation. Un `commit:` cite en prose
        # (« DEJA_FAIT (commit:<vieux sha>) ») est une preuve d'anteriorite, pas un livrable ; pas d'enveloppe : on
        # s'abstient (cout asymetrique ci-dessus).
        sha = _sha_atteste(result)
        if not sha:
            continue
        j = _juger_attestation(description, result, sha, created)
        if j["verdict"] == "RECOPIE":
            out.append({
                "kind": "pointeur_spec_recopie",
                "target": f"{tid}:{sha}",
                "severity": "low",
                "detail": (f"task {tid} (agent {agent}) marquee done en citant {sha} ({j['motif']}) : "
                           f"defaut de forme de l'attestation, son livrable n'est pas designe"),
            })
        elif j["verdict"] == "ANTERIEUR":
            out.append({
                "kind": "attestation_commit_anterieur",
                "target": f"{tid}:{sha}",
                "severity": "high",
                "detail": (f"task {tid} (agent {agent}) marquee done en citant {sha}, "
                           f"commit anterieur de {j['minutes']} min "
                           f"a la creation de la task — ne peut pas etre son livrable ({j['motif']})"),
            })
        # POSTERIEUR : peut etre le livrable ; INCONNU : git muet, on s'abstient d'accuser.
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
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_delivery_integrity.py', 383, exc_info=True)
    return env


def _gh(*args: str, coffre: bool = True) -> str | None:
    """GitHub CLI en lecture seule. None si `gh` est absent, non authentifie ou
    injoignable — l'organe se tait alors sur la dimension CI plutot que d'accuser.
    `coffre=False` (le soin, 7/11) : environnement herite SEUL, jamais de lecture de secret ; non authentifie ->
    None -> INCONNU, donc aucun acquittement."""
    try:
        r = subprocess.run(
            ["gh", *args, "--repo", GH_REPO],
            capture_output=True, text=True, timeout=45,
            encoding="utf-8", errors="replace", env=_gh_env() if coffre else dict(os.environ),
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_delivery_integrity.py', 486, exc_info=True)
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


# ── SOIN (7/11) : re-mesurer le fait PRESENT d'un constat ouvert ─────────────────────────────────────────────
# Owner 7/11 : « si le corps recoit des signaux il doit savoir les traiter de facon autonome ». Ces fonctions LISENT
# (tasks.db, git, gh sans coffre) et rendent un etat ; acquitter (`ack`) et deposer une tache appartiennent a
# forge_remediation.check_delivery_integrity, sous le drapeau `armed`.
#   RESOLU    : le fait n'existe plus            -> acquittable
#   CONTREDIT : le constat etait faux             -> acquittable
#   SUSPECT   : accusation confirmee par l'executeur (0 commit observe) -> tache de reverification
#   PERSISTE  : le fait tient, ou non conclu      -> garde
#   INCONNU   : illisible                         -> garde, JAMAIS acquitte

# Requete de la SEULE table des constats (la base est partagee : jamais de balayage d'une autre table).
# EXPLAIN QUERY PLAN prouve par tests/nr/test_coagulation_soin_integrite_nr.py.
_SQL_OUVERTS = ("SELECT id, kind, target, severity, created_at FROM delivery_integrity_findings "
                "WHERE acked_at IS NULL ORDER BY created_at LIMIT ?")


def findings_ouverts(limit: int = 60) -> list[dict] | None:
    """Constats non acquittes, plus anciens d'abord, en LECTURE SEULE ; None si la table est illisible."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error:
        return None
    try:
        rows = con.execute(_SQL_OUVERTS, (int(limit),)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return [{"id": a, "kind": b, "target": c, "severity": d, "created_at": e} for a, b, c, d, e in rows]


def _etat(etat: str, motif: str, **extra) -> dict:
    return dict(extra, etat=etat, motif=str(motif)[:240])


def _remesurer_attestation(target: str) -> dict:
    tid, _, sha = str(target).rpartition(":")
    if not tid or not sha:
        return _etat("INCONNU", "cible illisible")
    if not TASKS_DB.exists():
        return _etat("INCONNU", "tasks.db absente")
    try:
        con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
            desc_col = "description" if "description" in cols else "NULL"
            stat_col = "status" if "status" in cols else "NULL"
            row = con.execute(f"SELECT agent, created_at, {desc_col}, result, {stat_col} FROM tasks WHERE id=?",
                              (tid,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return _etat("INCONNU", "tasks.db illisible (%s)" % type(exc).__name__)
    if row is None:
        return _etat("INCONNU", "tache %s absente de tasks.db" % tid)
    agent, created, description, result, status = row
    # 9/11 (choix owner « requalifier ») : une tache sortie de done/completed n'atteste plus rien ; sans ce chemin,
    # job_af6dbf75 etait re-emise en high a chaque tick (SUSPECT perpetuel). Statut illisible (NULL) : on continue.
    if status is not None and status not in ("done", "completed"):
        return _etat("RESOLU", "tache %s requalifiee (status=%s) : elle n'atteste plus %s" % (tid, status, sha),
                     agent=agent)
    if _sha_atteste(result) != sha:
        return _etat("RESOLU", "l'attestation de %s ne cite plus %s" % (tid, sha), agent=agent)
    j = _juger_attestation(description, result, sha, created)
    if j["verdict"] in ("RECOPIE", "POSTERIEUR"):
        return _etat("CONTREDIT", j["motif"], agent=agent)
    if j["verdict"] == "ANTERIEUR" and j["commits"] == 0:
        return _etat("SUSPECT", "sha %s anterieur de %s min, %s" % (sha, j["minutes"], j["motif"]),
                     agent=agent, tache=tid, sha=sha, consigne=str(description or "")[:600])
    if j["verdict"] == "ANTERIEUR":
        return _etat("PERSISTE", j["motif"], agent=agent)
    return _etat("INCONNU", j["motif"], agent=agent)


def _remesurer_travail_non_commite(target: str) -> dict:
    changed = _git(ROOT, "diff", "--name-only", "--ignore-submodules=all")
    staged = _git(ROOT, "diff", "--cached", "--name-only", "--ignore-submodules=all")
    if changed is None or staged is None:
        return _etat("INCONNU", "git diff illisible")
    present = _scan_uncommitted()
    if not present:
        return _etat("RESOLU", "plus aucun fichier tracke modifie depuis %d j" % STALE_DAYS)
    if present[0]["target"] == target:
        return _etat("PERSISTE", "chemin encore sale : %s" % target)
    return _etat("RESOLU", "remplace par le constat present (%s)" % present[0]["target"])


def _remesurer_file_non_drainee(target: str) -> dict:
    agent, _, status = str(target).rpartition(":")
    if not agent or not status:
        return _etat("INCONNU", "cible illisible")
    if not TASKS_DB.exists():
        return _etat("INCONNU", "tasks.db absente")
    try:
        con = sqlite3.connect(f"file:{TASKS_DB}?mode=ro", uri=True, timeout=30)
        try:
            n, oldest = con.execute("SELECT COUNT(*), MIN(created_at) FROM tasks WHERE agent=? AND status=?",
                                    (agent, status)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return _etat("INCONNU", "tasks.db illisible (%s)" % type(exc).__name__)
    if not n:
        return _etat("RESOLU", "file %s videe" % target)
    oldest_dt = _as_utc(oldest)
    if oldest_dt is None:
        return _etat("INCONNU", "date de la plus ancienne tache illisible")
    if oldest_dt > datetime.now(tz=timezone.utc) - timedelta(days=STALE_DAYS):
        return _etat("RESOLU", "%d tache(s) %s, toutes de moins de %d j" % (n, target, STALE_DAYS))
    return _etat("PERSISTE", "%d tache(s) %s, la plus ancienne du %s" % (n, target, oldest))


def _remesurer_submodule(target: str) -> dict:
    recorded = _git(SUPERREPO, "ls-tree", "HEAD", target)
    real = _git(SUPERREPO / target, "rev-parse", "HEAD")
    if not recorded or not real:
        return _etat("INCONNU", "pointeur ou HEAD du submodule illisible")
    m = re.search(r"\b([0-9a-f]{40})\b", recorded)
    if not m:
        return _etat("INCONNU", "pointeur du superrepo illisible")
    if m.group(1) == real:
        return _etat("RESOLU", "superrepo a jour sur %s" % real[:8])
    return _etat("PERSISTE", "superrepo sur %s, submodule sur %s" % (m.group(1)[:8], real[:8]))


def _remesurer_ci(target: str) -> dict:
    branch = _git(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch:
        return _etat("INCONNU", "branche illisible")
    raw = _gh("run", "list", "--branch", branch, "--limit", "30", "--json", "conclusion,status,name,headSha",
              coffre=False)
    if not raw:
        return _etat("INCONNU", "runs GitHub illisibles (gh absent ou non authentifie, coffre non lu)")
    try:
        runs = json.loads(raw)
    except ValueError:
        return _etat("INCONNU", "sortie gh illisible")
    rs = [r for r in runs if r.get("status") == "completed" and (r.get("name") or "?") == target]
    if not rs:
        return _etat("INCONNU", "aucun run termine du workflow %s sur %s" % (target, branch))
    if rs[0].get("conclusion") == "failure":
        # workflow + commit : la tache d'analyse du soin est dedupliquee sur ce couple. Sha absent -> pas de couple,
        # donc pas de tache (le soin ne cree rien sur une lecture incomplete).
        return _etat("PERSISTE", "dernier run de %s sur %s en echec" % (target, branch),
                     workflow=target, commit=str(rs[0].get("headSha") or "")[:40], branche=branch)
    return _etat("RESOLU", "dernier run de %s sur %s : %s" % (target, branch, rs[0].get("conclusion")))


_REMESURES = {
    "attestation_commit_anterieur": _remesurer_attestation,
    "travail_non_commite": _remesurer_travail_non_commite,
    "file_non_drainee": _remesurer_file_non_drainee,
    "submodule_non_bumpe": _remesurer_submodule,
    "ci_en_echec": _remesurer_ci,
}


def remesurer(kind: str, target: str) -> dict:
    """Etat PRESENT d'un constat -> {"etat", "motif", ...}. Lecture seule ; ne leve jamais."""
    f = _REMESURES.get(str(kind))
    if f is None:
        return _etat("INCONNU", "type %s sans re-mesure" % kind)
    try:
        return f(str(target))
    except Exception as exc:  # noqa: BLE001 - une re-mesure qui casse vaut INCONNU, jamais RESOLU
        return _etat("INCONNU", "re-mesure en echec (%s: %s)" % (type(exc).__name__, str(exc)[:80]))


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
