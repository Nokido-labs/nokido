"""Surveille un job detache et EMET ses transitions sur stdout.

__FORGE_COLOR__ = "vegetatif/heartbeat : emet les transitions d'un job long vers la boucle du client"

Pourquoi ce module existe (2026-09-13). L'outil `Monitor` du client reveille sa
boucle en transformant chaque ligne de stdout en evenement -- une notification
deposee dans l'inbox ne le fait PAS (mesure du 2026-09-09). Mais `Monitor`
execute du shell NATIF : il echappait a `bash_guard`, donc a toute la politique
d'execution. C'etait un passe-droit, releve et ferme sur directive owner.

Ce CLI est la seule forme de surveillance que `bash_guard` accepte pour
`Monitor` : un script git-tracke, en LECTURE SEULE, dont le comportement est
revu. Le shell libre n'y a plus sa place.

Frere de `tools/forge_job_watch_notify.py`, qui vise l'INBOX (asynchrone, ne
reveille pas la boucle). Les deux coexistent a dessein : meme surveillance,
deux destinataires.

COUVERTURE. Le silence n'est pas un succes : un moniteur qui n'emet que sur le
chemin heureux reste muet sur un crash, et le mutisme ressemble a « ca tourne ».
Trois sorties sont donc emises -- fin (`.rc` present), GEL (le journal cesse de
grossir), DEPASSEMENT. Et jamais `kill -0` : sous Git Bash il interroge la table
de PID MSYS, pas Windows, et a deja declare morte une CI bien vivante.

  LAFORGE_PYTHON tools/forge_job_watch_cli.py --job job_xxx [--gel-s 900]

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `lire_bilan` — Etat GRADUE d'un job fini : ECHEC · ARRET_GARDE · VIDE · DECLARE · TERMINE_NON_VERIFIE · INCONNU. Jamais VERIFIED.
- `delegations_en_vol` / `transitions` / `ligne_evenement` / `alertes_gel` — suivi des delegations (owner 22/10) : la vue des taches en vol lue dans `tasks.db`, les transitions DEDUITES de deux lectures (statut ou agent change), les gels signales UNE fois chacun. `--delegations [--une-fois]` rend la vue a TOUT CLI, par le `run` du hub.

  LAFORGE_PYTHON tools/forge_job_watch_cli.py --delegations --une-fois --de <AGENT>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "sandbox" / "jobs"


def _mtime(p: Path):
    """mtime, ou None si illisible. None n'est PAS 'pas de progres'."""
    try:
        return p.stat().st_mtime
    except OSError:
        return None


TACHES = ROOT / "sandbox" / "tasks.db"
_TERMINAUX = ("done", "failed", "error", "cancelled", "timeout")


def _etat_tache(task_id: str, db=None):
    """(status, longueur_du_result) — `(None, 0)` si illisible ou inconnue.

    `None`, jamais une chaine : une base verrouillee ou une tache absente ne
    doivent pas se lire comme un statut. ILLISIBLE != PAS_LA != EN_COURS.
    """
    import sqlite3
    chemin = Path(db) if db else TACHES
    if not chemin.exists():
        return None, 0
    try:
        c = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=3)
        try:
            ligne = c.execute(
                "SELECT status, COALESCE(LENGTH(result), 0) FROM tasks WHERE id = ?",
                (task_id,)).fetchone()
        finally:
            c.close()
    except Exception:  # noqa: BLE001 — muet-ok : l'appelant recoit None et le DIT
        return None, 0
    return (ligne[0], ligne[1]) if ligne else (None, 0)


def _progres_tache(task_id: str, db=None):
    """`tasks.progress_at` tel que l'executeur le DECLARE (battement de delegation), ou None si absent ou illisible.
    Un progres qui avance repousse le gel : STALE n'est pas DEAD (P2 du 17/10)."""
    import sqlite3
    chemin = Path(db) if db else TACHES
    if not chemin.exists():
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=3)
        try:
            ligne = c.execute("SELECT progress_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        finally:
            c.close()
    except Exception:  # noqa: BLE001 — muet-ok : l'appelant recoit None et le DIT (progres ILLISIBLE)
        return None
    return str(ligne[0]) if ligne and ligne[0] else None


_POULS_EMISSION_S = 600   # une ligne « EN COURS » au plus toutes les 10 min : visible sans inonder la boucle


def _pouls_executeur(task_id: str, dossier: Path):
    """`travail_depuis_s` du pouls d'un executeur qui DECLARE travailler sur CETTE tache, sinon None.

    Mesure du 2026-10-18 : une surveillance a expire 30 min sans un evenement pendant que l'executeur
    travaillait -- le statut de la table ne bougeait pas, et ce guetteur ne lisait que lui. Un pouls
    illisible est ignore (on ne conclut rien d'un fichier qu'on ne sait pas lire)."""
    import json as _json
    try:
        candidats = sorted(Path(dossier).glob("task_executor_*.heartbeat"))
    except OSError:
        return None
    for f in candidats:
        try:
            d = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_job_watch_cli.py', 112, exc_info=True)
            continue
        if isinstance(d, dict) and d.get("tache") == task_id and d.get("travail_en_cours"):
            try:
                return float(d.get("travail_depuis_s") or 0)
            except (TypeError, ValueError):
                return 0.0
    return None


def surveiller_tache(task_id: str, gel_s: int, max_s: int, intervalle: int,
                     ecrire=print, db=None, horloge=time.time, dormir=time.sleep, pouls_dir=None) -> int:
    """Surveille une TACHE M2M (`tasks.db`) comme `surveiller` suit un job.

    POURQUOI. Une reponse deposee dans l'inbox ne REVEILLE PAS la boucle du
    client. Le 2026-09-22, une tache confiee a ANTIGRAVITY a repondu en
    quelques minutes : vue au tour suivant, par hasard. Le meme jour, le
    verdict d'une CI distante est reste trois heures non lu.

    CE QU'ON N'ANNONCE JAMAIS. Le statut d'une tache dit ce que l'agent
    AFFIRME, pas ce qu'il a PRODUIT. Mesure du meme jour :

        status=done  intent=OK_DONE  status_code=SUCCESS
        detail="Je suis EN TRAIN d'executer... J'ATTENDS le premier lot."

    et l'artefact visé n'avait pas bouge depuis un mois. L'emission renvoie
    donc toujours a l'artefact, et ne dit jamais « reussi ».

        ACCEPTED DECLARE ACHIEVED — c'est le faux calme qu'on refuse de relayer.
    """
    debut = horloge()
    vu, _ = _etat_tache(task_id, db)
    progres_vu = _progres_tache(task_id, db)
    dernier_changement = debut
    dossier_pouls = Path(pouls_dir) if pouls_dir else (Path(db).parent if db else TACHES.parent)
    dernier_pouls_emis = debut - _POULS_EMISSION_S
    if vu is not None:
        ecrire("TACHE %s statut=%s — un statut dit ce que l'agent AFFIRME ; "
               "l'effet se lit sur l'ARTEFACT vise" % (task_id, vu))

    while True:
        statut, taille = _etat_tache(task_id, db)
        maintenant = horloge()

        progres = _progres_tache(task_id, db)
        if progres is not None and progres != progres_vu:
            progres_vu, dernier_changement = progres, maintenant   # l'executeur declare du travail : pas de gel

        pouls = _pouls_executeur(task_id, dossier_pouls)
        if pouls is not None:
            dernier_changement = maintenant   # un executeur DECLARE travailler sur cette tache : pas un gel
            if maintenant - dernier_pouls_emis >= _POULS_EMISSION_S:
                dernier_pouls_emis = maintenant
                ecrire("TACHE %s EN COURS — pouls de l'executeur : travail depuis %d min (statut %s) ; "
                       "un pouls DECLARE, pas un effet" % (task_id, int(pouls / 60), vu if vu is not None
                                                            else "ILLISIBLE"))

        if statut is not None and statut != vu:
            vu, dernier_changement = statut, maintenant
            ecrire("TACHE %s -> %s (result %d o) — statut AFFIRME, pas effet "
                   "constate : relire l'ARTEFACT vise par la tache"
                   % (task_id, statut, taille))

        if statut in _TERMINAUX:
            ecrire("TACHE %s TERMINALE statut=%s — ne pas conclure sur OK_DONE : "
                   "l'ARTEFACT tranche (mesure 2026-09-22 : un done/SUCCESS "
                   "n'avait rien produit)" % (task_id, statut))
            return 0

        if maintenant - dernier_changement > gel_s:
            ecrire("TACHE %s FIGEE — statut %s et progres inchanges depuis %d min ; %s"
                   % (task_id, vu if vu is not None else "ILLISIBLE",
                      int((maintenant - dernier_changement) / 60),
                      ("dernier progres declare %s" % progres_vu) if progres_vu
                      else "progres ILLISIBLE (aucun progress_at lu)"))
            return 0

        if maintenant - debut > max_s:
            ecrire("TACHE %s TOUJOURS EN COURS apres %d min — ni fin ni gel"
                   % (task_id, int((maintenant - debut) / 60)))
            return 0

        dormir(intervalle)


# BILAN GRADUE (fiche de veille V2, 2026-09-23). Ce CLI rappelait que le rc n'est
# qu'un signal... puis s'arretait la. Payes le meme jour : vague 5 finie rc=0 sans
# bilan, un rc=0 a 0 chunk, un arret de garde disque (rc=5) a relire a la main.
# Il lit donc le BILAN que le producteur ecrit. `DECLARE` = l'affirmation du
# producteur, JAMAIS `VERIFIED` : la preuve independante (compte en base par
# source) est hors de portee d'un notifieur en lecture seule. NR :
# tests/nr/test_job_watch_bilan_gradue_nr.py
import re as _re

_QUEUE_OCTETS = 256 * 1024
# Un arret de garde TERMINE le job : il est en QUEUE de journal. Un « ARRET » suivi de travail est
# la sortie d'autre chose -- mesure 2026-09-26 : une CI verte (12 462 tests, 0 echec) annoncee
# ARRET_GARDE sur une ligne imprimee par un NR de ci-attente qui simule des admissions.
_QUEUE_ARRET = 30
_BILANS = (_re.compile(r"TOTAL\s+(\d+)\s+chunks"),
           _re.compile(r"=== RAG : \+(\d+) chunks"),
           # bilan JSON de tools/forge_ingest_github_repo.py (« index.inserted ») -- lu « sans bilan » le 18/10
           _re.compile(r'"inserted":\s*(\d+)'))
# Le bilan d'une CI (`tools/ci_local.py`) est sa ligne `[preuve]`, calculee sur le JUnit. Mesure
# 2026-09-26 : la CI de reference job_e073b2edba52 (12 496 executes, 0 echec, SUITE_COMPLETE)
# annoncee ECHEC -- 13 Traceback IMPRIMES par des tests qui passent, et faute de bilan
# d'ingestion le premier suffisait. Meme famille que ARRET_GARDE : la sortie d'un test n'est
# pas la fin du job.
_DEFAILLANCES_CI = ("echecs", "erreurs", "timeouts")
_ANSI = _re.compile(r"\x1b\[[0-9;]*m")

# Le bruit TECHNIQUE de l'exportateur OTLP et de la fermeture des clients HTTP n'est pas un
# verdict. Mesure 2026-10-24 (job_b039a2b4f7ca, rc=0, mesure valide) : le .err ne portait que
# « Failed to export spans batch ... WinError 10061 » et des Traceback « Event loop is closed »
# de httpx -> le bilan disait ECHEC. Ces lignes sont ecartees de la recherche du motif ; un rc
# non nul reste un echec, et un vrai Traceback applicatif reste lisible.
# Seul le bruit qui NOMME l'exportateur est ecarte (relecture 24/10) : « Max retries exceeded », « ConnectionRefusedError »
# ou « WinError 10061 » seuls peuvent venir d'une vraie panne (hub :8766 eteint) dont le motif doit rester lisible.
# Un Traceback de l'exportateur reste ecarte en bloc : ses frames nomment `opentelemetry`.
_BRUIT_OTLP = _re.compile(
    r"(Failed to export spans|opentelemetry|OTLP|/v1/traces|:4318\b|port=4318\b)",
    _re.IGNORECASE)
_BRUIT_FERMETURE = _re.compile(
    r"^(Task exception was never retrieved|future: <Task finished|"
    r"RuntimeError: Event loop is closed)")


def _sans_bruit_technique(lignes: list) -> list:
    """Lignes SANS le bruit de l'exportateur OTLP ni des fermetures httpx/asyncio.

    Un bloc `Traceback` est ecarte ENTIEREMENT s'il porte une marque de ce bruit (frame
    opentelemetry, connexion refusee, « Event loop is closed »). Un vrai Traceback applicatif
    n'en porte aucune : son motif reste lisible, et un rc non nul reste un ECHEC.
    """
    bruit = {i for i, l in enumerate(lignes)
             if _BRUIT_OTLP.search(l) or _BRUIT_FERMETURE.search(l)}
    i, n = 0, len(lignes)
    while i < n:
        if lignes[i].strip().startswith("Traceback"):
            j = i + 1
            while j < n and lignes[j].strip():
                j += 1
            if any(k in bruit for k in range(i, j)):
                bruit.update(range(i, j))
            i = j
            continue
        i += 1
    return [l for k, l in enumerate(lignes) if k not in bruit]


def _depots_pair(depuis_iso: str, client: str | None, m2m=None) -> list | None:
    """[(id, from_agent, method, intent, created_at)] des depots de pairs recus APRES `depuis_iso`
    dans la boite OWNER_APPROBATION ; None si la base est illisible (jamais « aucun depot »)."""
    import json as _json
    import sqlite3 as _sq

    try:
        if m2m is None:
            import sys as _sys

            _racine = str(Path(__file__).resolve().parents[1])
            if _racine not in _sys.path:
                _sys.path.insert(0, _racine)
            from nokido_agent.tools.forge_pair_quarantaine import chemin_m2m

            m2m = chemin_m2m()
        con = _sq.connect("file:%s?mode=ro" % m2m, uri=True, timeout=10)
        try:
            lignes = con.execute(
                "SELECT id, from_agent, method, payload, created_at FROM agent_messages "
                "WHERE to_agent='OWNER_APPROBATION' AND created_at > ? AND from_agent LIKE ? "
                "ORDER BY created_at", (depuis_iso, ("PAIR:%s%%" % client) if client else "PAIR:%")).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - illisible : dit par None, jamais lu comme « rien »
        return None
    out = []
    for ident, de, methode, charge, recu in lignes:
        try:
            intent = (_json.loads(charge or "{}") or {}).get("intent")
        except ValueError:
            intent = "?"
        out.append((ident, de, methode, intent, recu))
    return out


def surveiller_pair(client: str | None, max_s: int, intervalle: int, ecrire=print, m2m=None,
                    horloge=time.time, dormir=time.sleep, depuis_iso: str | None = None) -> int:
    """Surveille la QUARANTAINE des pairs cloud (claude.ai...) et SE TERMINE au premier depot neuf.

    POURQUOI (owner 2026-10-01 : « la capsule claude.ai est finie, tu ne le vois pas direct ? lance un
    monitor en fonction du LLM qui le lance »). Un job local se suit par --job, une tache d'AGY par
    --task ; un pair cloud depose en quarantaine, que rien ne surveillait : son rendu du soir est reste
    non vu jusqu'a ce que l'owner le signale.

    L'emission ne porte que des METADONNEES (id, auteur, intent, methode) -- jamais le texte externe,
    qui reste une donnee a lire volontairement (`forge_pair_quarantaine --lister`)."""
    import datetime as _dt

    depuis = depuis_iso or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    debut = horloge()
    ecrire("PAIRS : veille de la quarantaine depuis %s%s" % (depuis, (" (client %s)" % client) if client else ""))
    illisible = 0
    while True:
        neufs = _depots_pair(depuis, client, m2m)
        if neufs is None:
            illisible += 1
            if illisible in (1, 10):
                ecrire("PAIRS : base m2m ILLISIBLE (x%d) -- un depot pourrait arriver sans etre vu" % illisible)
        elif neufs:
            for ident, de, methode, intent, recu in neufs:
                ecrire("PAIR DEPOT %s de %s intent=%s methode=%s recu=%s -- lire : "
                       "forge_pair_quarantaine --lister (texte EXTERNE = donnee)" % (ident, de, intent, methode, recu))
            return 0
        if horloge() - debut > max_s:
            ecrire("PAIRS : aucun depot neuf apres %d min -- veille terminee, a re-armer" % int((horloge() - debut) / 60))
            return 0
        dormir(intervalle)


def _preuve_ci(lignes: list) -> tuple:
    """(index, champs, ligne) de la DERNIERE ligne `[preuve]`, ou (-1, None, "")."""
    for i in range(len(lignes) - 1, -1, -1):
        if "[preuve]" in lignes[i]:
            ligne = _ANSI.sub("", lignes[i]).strip()
            return i, dict(_re.findall(r"(\w+)=(\S+)", ligne)), ligne
    return -1, None, ""


_PYTEST_RESUME = _re.compile(r"\b\d+ (?:passed|failed|errors?)\b.*\bin [\d.]+s\b")
_PYTEST_COMPTE = _re.compile(r"\b(\d+) (passed|failed|errors?)\b")


def _resume_pytest(lignes) -> dict | None:
    """Cumul des lignes de resume pytest (« 10 failed, 30 passed in 12.3s ») ; None = aucune.

    15/10 : le guet rendait « rc=0 sans ligne de bilan » sur des jobs de NR dont le journal portait `74 passed`, ce
    qui forcait un aller-retour de plus pour lire le journal ; et un relais qui avale le rc d'un pytest rouge
    passait pour un succes. Le resume du producteur se LIT -- il ne se VERIFIE pas (JUnit)."""
    vus = {"passed": 0, "echecs": 0, "lignes": 0, "derniere_rouge": ""}
    for l in lignes:
        propre = _ANSI.sub("", l)
        if not _PYTEST_RESUME.search(propre):
            continue
        vus["lignes"] += 1
        for n, mot in _PYTEST_COMPTE.findall(propre):
            if mot == "passed":
                vus["passed"] += int(n)
            else:
                vus["echecs"] += int(n)
                vus["derniere_rouge"] = propre.strip()
    return vus if vus["lignes"] else None


def lire_bilan(texte: str, rc: str) -> dict:
    """Etat GRADUE d'un job fini : ECHEC · ARRET_GARDE · VIDE · DECLARE ·
    TERMINE_NON_VERIFIE · INCONNU. Jamais VERIFIED (voir plus haut)."""
    rc = (rc or "").strip()
    if not rc.lstrip("-").isdigit():
        return {"etat": "INCONNU", "motif": "rc illisible : %s" % rc[:80]}
    lignes = _sans_bruit_technique((texte or "").splitlines())
    dernier_bilan, n_chunks = -1, None
    for i, l in enumerate(lignes):
        for motif in _BILANS:
            m = motif.search(l)
            if m:
                dernier_bilan, n_chunks = i, int(m.group(1))
    i_preuve, preuve, ligne_preuve = _preuve_ci(lignes)
    non_vides = [l.strip() for l in lignes if l.strip()]
    arret = [l for l in non_vides[-_QUEUE_ARRET:] if "ARRET" in l]
    if arret:
        return {"etat": "ARRET_GARDE", "motif": arret[-1][:240]}
    tb = [i for i, l in enumerate(lignes) if l.startswith("Traceback")]
    if tb and tb[-1] > max(dernier_bilan, i_preuve):
        fin = [l.strip() for l in lignes[tb[-1]:] if l.strip()]
        return {"etat": "ECHEC", "motif": (fin[-1] if fin else "Traceback")[:240]}
    if rc != "0":
        if preuve is not None:
            return {"etat": "ECHEC", "motif": "rc=%s %s" % (rc, ligne_preuve[:200])}
        # Sans Traceback ni preuve, la cause est souvent une ligne de verdict DEJA ecrite (gate ❌, FAIL, ERROR) :
        # « sans motif lisible » la taisait (pre-controles du 13/10, rouges sur des gates nommees dans le journal).
        parlantes = [l for l in non_vides if "❌" in l or _re.search(r"\b(FAIL|FAILED|ERROR|Error|ERREUR)\b", l)]
        return {"etat": "ECHEC", "motif": "rc=%s %s" % (
            rc, _ANSI.sub("", parlantes[-1])[:200] if parlantes else "sans motif lisible dans le journal ni le .err")}
    if preuve is not None:
        if any(preuve.get(k, "0") != "0" for k in _DEFAILLANCES_CI):
            return {"etat": "ECHEC", "motif": ligne_preuve[:240]}
        if preuve.get("etat") != "SUITE_COMPLETE":
            return {"etat": "TERMINE_NON_VERIFIE", "motif": "suite incomplete : " + ligne_preuve[:200]}
        return {"etat": "DECLARE",
                "motif": "preuve CI du producteur, NON verifiee (JUnit) : " + ligne_preuve[:200]}
    pyt = _resume_pytest(lignes)
    if pyt is not None and pyt["echecs"]:
        return {"etat": "ECHEC", "motif": "rc=0 MAIS %d echec(s)/erreur(s) pytest : %s"
                % (pyt["echecs"], pyt["derniere_rouge"][:200])}
    if pyt is not None and n_chunks is None:
        return {"etat": "DECLARE", "motif": "resume pytest du producteur : %d verts sur %d resume(s), NON verifie (JUnit)"
                % (pyt["passed"], pyt["lignes"])}
    if n_chunks is None:
        return {"etat": "TERMINE_NON_VERIFIE", "motif": "rc=0 sans ligne de bilan : le silence n'est pas un succes"}
    if n_chunks == 0:
        return {"etat": "VIDE", "chunks": 0, "motif": "bilan a 0 chunk"}
    return {"etat": "DECLARE", "chunks": n_chunks,
            "motif": "bilan du producteur, NON verifie en base"}


def _queue_du_journal(log: Path) -> tuple[str, str]:
    """Les derniers octets du journal, et DIT s'il a ete tronque (borne annoncee)."""
    try:
        taille = log.stat().st_size
        with log.open("rb") as f:
            if taille > _QUEUE_OCTETS:
                f.seek(taille - _QUEUE_OCTETS)
            brut = f.read()
    except OSError as e:
        return "", "journal illisible (%s)" % type(e).__name__
    note = "" if taille <= _QUEUE_OCTETS else "lu sur les %d Ko de fin" % (_QUEUE_OCTETS // 1024)
    return brut.decode("utf-8", errors="replace"), note


def _activite_arbre(pid):
    """(cpu_s, octets_io, operations_io) cumules du process ET de ses enfants. None = ILLISIBLE -- jamais « inactif ».

    2026-10-13 : un cycle de soif a ete declare FIGE apres 15 min de journal muet, alors que son ENFANT lisait
    37 Mo/s dans la base (balayage de 45 Go, qui ne journalise rien). Le wrapper de run_job reste a 0 % pendant que
    l'enfant travaille : seul l'ARBRE dit la verite (« le CPU du wrapper n'est pas celui de l'enfant »).

    2026-10-15 : le pack natif a ete declare FIGE alors que son enfant ATTENDAIT l'embedder :8099 (connexion etablie,
    CPU du serveur en hausse). Sous Windows, le reseau se compte dans `other_bytes`/`other_count`, pas dans
    read/write : mesure sur 15 s, enfant +667 operations et +31 Ko « other », 0 octet lu ou ecrit ; temoin inactif,
    0 operation. Le travail d'un client se fait dans le serveur : seules ses operations d'E/S le trahissent."""
    if not pid:
        return None
    try:
        import psutil

        p = psutil.Process(int(pid))
        procs = [p] + p.children(recursive=True)
    except Exception:  # noqa: BLE001 -- muet-ok : None = ILLISIBLE, dit par l'appelant
        return None
    cpu, io, ops, lus = 0.0, 0, 0, 0
    for q in procs:
        try:
            t = q.cpu_times()
            c = q.io_counters()
        except Exception:  # noqa: BLE001 -- muet-ok : process illisible ou parti, compte par `lus`
            continue
        cpu += t.user + t.system
        # `other_*` n'existe que sous Windows (reseau, peripheriques) : absent = 0, pas une erreur.
        io += c.read_bytes + c.write_bytes + getattr(c, "other_bytes", 0)
        ops += c.read_count + c.write_count + getattr(c, "other_count", 0)
        lus += 1
    return (cpu, io, ops) if lus else None


SEUIL_OPS = 50  # operations d'E/S par intervalle : temoin inactif mesure a 0, client en attente d'un serveur a ~2 700/min


def _arbre_progresse(act, ref) -> bool:
    """L'arbre a-t-il progresse depuis `ref` ? CPU > 0,5 s, OU E/S > 1 Mo, OU plus de SEUIL_OPS operations.
    Une mesure a deux champs (ancienne forme, injectee par les NR) se juge sur CPU et octets seuls."""
    if act[0] - ref[0] > 0.5 or act[1] - ref[1] > 1_000_000:
        return True
    return len(act) > 2 and len(ref) > 2 and act[2] - ref[2] > SEUIL_OPS


def _pid_du_job(base: Path, job: str):
    try:
        import json

        return json.loads((base / ("%s.json" % job)).read_text(encoding="utf-8")).get("pid")
    except Exception:  # noqa: BLE001 -- muet-ok : pid inconnu = activite ILLISIBLE, dite au verdict
        return None


def surveiller(job: str, gel_s: int, max_s: int, intervalle: int, ecrire=print,
               jobs_dir=None, horloge=time.time, dormir=time.sleep, activite=None) -> int:
    """Surveille un job. `jobs_dir`/`horloge`/`dormir` existent pour le NR.

    Une constante figee a l'import ne se redirige pas : sans ce parametre, le
    test ne pourrait pas fabriquer un job temoin, et le module resterait
    verifie seulement « par lecture ». Defaut paye ailleurs le meme jour --
    une redirection qui court-circuite le point d'injection casse d'abord la
    testabilite.
    """
    base = Path(jobs_dir) if jobs_dir else JOBS
    rc = base / ("%s.rc" % job)
    log = base / ("%s.log" % job)
    debut = horloge()
    dernier_vu = None
    dernier_progres = debut
    activite = activite or _activite_arbre
    act_ref, arbre_dit = None, False

    while True:
        if rc.exists():
            try:
                code = rc.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as e:
                code = "ILLISIBLE (%s)" % type(e).__name__
            # Les Traceback partent sur STDERR (`.err`), pas dans le `.log` : sans lui,
            # un echec etait note ECHEC mais SANS son motif (controle du 2026-09-23).
            texte, note = _queue_du_journal(log)
            texte_err, _ = _queue_du_journal(base / ("%s.err" % job))
            b = lire_bilan(texte + "\n" + texte_err, code)
            ecrire("JOB %s TERMINE rc=%s — le rc est un SIGNAL, le verdict se lit "
                   "sur l'artefact (JUnit, rapport), jamais sur lui | bilan %s%s : %s%s"
                   % (job, code, b["etat"],
                      "(%d)" % b["chunks"] if b.get("chunks") is not None else "",
                      b["motif"], (" [%s]" % note) if note else ""))
            return 0

        m = _mtime(log)
        maintenant = horloge()
        if m is None:
            # Journal pas encore cree, ou illisible : on ne conclut pas.
            dernier_progres = maintenant if dernier_vu is None else dernier_progres
        elif m != dernier_vu:
            dernier_vu = m
            dernier_progres = maintenant

        # L'ARBRE du job progresse-t-il (CPU, octets ou operations d'E/S depuis la reference) ? Alors ce n'est pas
        # un gel, meme si le journal se tait.
        act = activite(_pid_du_job(base, job))
        if act is not None and act_ref is not None and _arbre_progresse(act, act_ref):
            if maintenant - dernier_progres > intervalle and not arbre_dit:
                ecrire("JOB %s journal muet depuis %d min MAIS son arbre travaille (CPU +%.1f s, I/O +%.1f Mo%s) -- pas FIGE"
                       % (job, int((maintenant - dernier_progres) / 60), act[0] - act_ref[0],
                          (act[1] - act_ref[1]) / 1e6,
                          ", %d operations" % (act[2] - act_ref[2]) if len(act) > 2 and len(act_ref) > 2 else ""))
                arbre_dit = True
            dernier_progres = maintenant
        if act is not None:
            act_ref = act

        if maintenant - dernier_progres > gel_s:
            ecrire("JOB %s FIGE — journal sans ecriture depuis %d min, aucun .rc, et son arbre %s"
                   % (job, int((maintenant - dernier_progres) / 60),
                      "INACTIF (CPU, octets et operations d'E/S stables)" if act is not None
                      else "ILLISIBLE (activite non lue : verdict tire du seul journal)"))
            return 0

        if maintenant - debut > max_s:
            ecrire("JOB %s TOUJOURS EN COURS apres %d min — ni fin ni gel detecte"
                   % (job, int((maintenant - debut) / 60)))
            return 0

        dormir(intervalle)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # `--job` et `--task` s'excluent : un seul sujet par surveillance. Sans
    # `required`, oublier les deux rendrait un usage, pas un plantage.
    cible = ap.add_mutually_exclusive_group(required=True)
    cible.add_argument("--job", help="job_id rendu par run_job")
    cible.add_argument("--task", help="task_id d'une tache M2M (tasks.db)")
    cible.add_argument("--pair", nargs="?", const="", metavar="CLIENT",
                       help="quarantaine des pairs cloud (claude.ai...) : premier depot neuf ; CLIENT optionnel")
    cible.add_argument("--delegations", action="store_true",
                       help="suit les delegations du demandeur (tasks.db) : transitions et gels")
    ap.add_argument("--gel-s", "--gel", type=int, default=900,
                    help="silence (journal, ou progression d'une delegation) au-dela duquel on declare un GEL")
    ap.add_argument("--max-s", "--max", type=int, default=4800, help="borne dure")
    ap.add_argument("--intervalle", type=int, default=20)
    ap.add_argument("--de", default=None,
                    help="demandeur : filtre sur from_agent (insensible a la casse)")
    ap.add_argument("--une-fois", action="store_true",
                    help="une seule lecture : on imprime la vue et on rend la main")
    ap.add_argument("--db", default=None,
                    help="base des delegations (defaut sandbox/tasks.db)")
    a = ap.parse_args(argv)
    if a.delegations:
        return suivre_delegations(db=a.db, de=a.de, gel_s=a.gel_s, max_s=a.max_s,
                                  intervalle=a.intervalle, une_fois=a.une_fois)
    if a.pair is not None:
        if any(c in a.pair for c in "/\\%_") or ".." in a.pair:
            print("REFUS : --pair attend un identifiant de client, pas un motif")
            return 2
        return surveiller_pair(a.pair or None, a.max_s, a.intervalle)
    sujet = a.job or a.task
    if "/" in sujet or "\\" in sujet or ".." in sujet:
        print("REFUS : --job/--task est un identifiant, pas un chemin")
        return 2
    if a.task:
        return surveiller_tache(a.task, a.gel_s, a.max_s, a.intervalle, db=a.db)
    return surveiller(a.job, a.gel_s, a.max_s, a.intervalle)


# ── SUIVI DES DELEGATIONS (owner 22/10) ──────────────────────────────────────
# Une delegation confiee a un autre agent vit dans `sandbox/tasks.db` : c'est la
# source UNIQUE (agent, statut, progression, reaffectations). Ce module la LIT --
# il n'invente ni table ni emetteur : une transition se DEDUIT de deux lectures
# (le statut ou l'agent a change).
#
# LECTURE SEULE (`mode=ro`) : un suiveur n'ecrit jamais dans l'etat qu'il observe.

_EN_VOL = ("pending", "running", "claimed", "assigned")
_LIMITE_DEFAUT = 200


def _ts_epoch(brut, fuseau=None):
    """Instant (epoch UTC, float) d'un horodatage `tasks`, ou None si illisible.

    Deux formes coexistent : l'ISO TEXT ecrit par le producteur
    (`2026-10-21T22:35:35.211392`) et l'epoch REAL (les tests). Une date SANS
    fuseau est lue en UTC (le contrat du suivi) ; le producteur ecrit en heure
    LOCALE, d'ou le repli de `_age_s`.
    """
    import datetime as _dt
    if brut is None or isinstance(brut, bool):
        return None
    if isinstance(brut, (int, float)):
        return float(brut)
    texte = str(brut).strip()
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError:  # muet-ok : essai suivant (formats iso/strptime)
        pass
    moment = None
    try:
        moment = _dt.datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:  # muet-ok : essai suivant (formats strptime)
        for forme in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                moment = _dt.datetime.strptime(texte, forme)
                break
            except ValueError:  # muet-ok : format non correspondant
                continue
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=fuseau or _dt.timezone.utc)
    return moment.timestamp()


def _age_s(maintenant, brut):
    """Age en secondes (int) d'un horodatage, ou None s'il est illisible ou futur.

    Lecture UTC d'abord -- c'est le contrat. Si elle donne un FUTUR, on relit en
    heure locale : le producteur ecrit l'heure locale (forge_mcp_registry), et un
    age negatif ne veut rien dire (une lecture qui ment non plus). Un horodatage
    encore futur apres les deux lectures vaut INCONNU (None), pas un age negatif.
    """
    import datetime as _dt
    epoch = _ts_epoch(brut)
    if epoch is None or maintenant is None:
        return None
    age = int(maintenant - epoch)
    if age >= 0:
        return age
    local = _ts_epoch(brut, _dt.datetime.now().astimezone().tzinfo)
    if local is not None and maintenant - local >= 0:
        return int(maintenant - local)
    return None


def _nb_reaffectations(brut):
    """Nombre de reaffectations tracees, ou None si la trace est illisible.

    `reaffectations` porte une LISTE JSON ([{de, vers, motif, quand}]) : ce qu'on
    lit, c'est le nombre. Une trace illisible vaut None (INCONNU) -- jamais 0,
    qui dirait « aucune reaffectation » alors qu'on n'a rien lu.
    """
    if brut is None:
        return None
    if isinstance(brut, (list, tuple)):
        return len(brut)
    texte = str(brut).strip()
    if not texte:
        return None
    import json as _json
    try:
        trace = _json.loads(texte)
    except (ValueError, TypeError):
        return None
    return len(trace) if isinstance(trace, list) else None


def _lire_taches(db=None, maintenant=None, de=None, statuts=None, limite=_LIMITE_DEFAUT):
    """(taches, motif) -- les taches lues dans `tasks.db`, ou le motif de l'echec.

    LECTURE SEULE (`mode=ro`), comme `_etat_tache`. Une base absente ou
    illisible ne rend JAMAIS « aucune tache » : elle rend un MOTIF, que l'appelant
    DIT (ILLISIBLE != PAS_LA). Les colonnes absentes d'un schema ancien sont
    ignorees, pas fatales ; seule l'absence de `id` ou de `from_agent` (quand on
    filtre dessus) est signalee.
    """
    import sqlite3
    chemin = Path(db) if db else TACHES
    if not chemin.exists():
        return [], "base absente (%s)" % chemin
    try:
        con = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=3)
    except Exception as e:  # noqa: BLE001 -- muet-ok : le motif est rendu au caller
        return [], "base ILLISIBLE (%s: %s)" % (type(e).__name__, e)
    try:
        try:
            colonnes = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
        except Exception as e:  # noqa: BLE001
            return [], "schema ILLISIBLE (%s: %s)" % (type(e).__name__, e)
        if not colonnes:
            return [], "table `tasks` absente (%s)" % chemin
        if "id" not in colonnes:
            return [], "table `tasks` sans `id` (%s)" % chemin
        if de and "from_agent" not in colonnes:
            return [], "colonne `from_agent` absente : filtre `de` inapplicable (%s)" % chemin
        vues = ("id", "agent", "status", "from_agent", "created_at", "progress_at", "reaffectations", "result")
        dispo = [c for c in vues if c in colonnes]
        requete = "SELECT %s FROM tasks" % ", ".join(dispo)
        params = []
        clauses = []
        if statuts:
            clauses.append("status IN (%s)" % ",".join("?" * len(statuts)))
            params.extend(statuts)
        if de:
            # `from_agent` porte le delegant : `agt_claude` doit matcher `claude`.
            clauses.append("(LOWER(from_agent) = LOWER(?) OR LOWER(from_agent) LIKE ?)")
            params.extend([de, "%_" + str(de).lower()])
        if clauses:
            requete += " WHERE " + " AND ".join(clauses)
        if "created_at" in colonnes:
            requete += " ORDER BY created_at DESC"
        if limite:
            requete += " LIMIT %d" % int(limite)
        try:
            lignes = con.execute(requete, params).fetchall()
        except Exception as e:  # noqa: BLE001
            return [], "lecture ILLISIBLE (%s: %s)" % (type(e).__name__, e)
    finally:
        con.close()
    taches = []
    for ligne in lignes:
        d = dict(zip(dispo, ligne))
        taches.append({
            "task_id": d.get("id"),
            "agent": d.get("agent"),
            "statut": d.get("status"),
            "de": d.get("from_agent"),
            "age_s": _age_s(maintenant, d.get("created_at")),
            "depuis_progres_s": _age_s(maintenant, d.get("progress_at")),
            "reaffectations": _nb_reaffectations(d.get("reaffectations")),
            "result": d.get("result"),
        })
    return taches, None


def delegations_en_vol(db=None, maintenant=None, de=None):
    """Les delegations EN VOL (pending, running, claimed, assigned) vues depuis `tasks.db`.

    [{task_id, agent, statut, de, age_s (int ou None), depuis_progres_s (int ou
    None), reaffectations (int ou None)}] -- `age_s` = maintenant - created_at
    (UTC) ; `depuis_progres_s` = maintenant - progress_at, None si absent (un
    progres ILLISIBLE n'est pas un gel) ; `reaffectations` = nombre de
    reaffectations tracees, None si la trace est illisible. `de` filtre le
    demandeur (`from_agent`), insensible a la casse.
    """
    if maintenant is None:
        maintenant = time.time()
    taches, _motif = _lire_taches(db=db, maintenant=maintenant, de=de, statuts=_EN_VOL, limite=None)
    return taches


def transitions(avant, apres):
    """Evenements DEDUITS de deux lectures : NOUVELLE · STATUT · REAFFECTEE.

    Un changement d'AGENT est une REAFFECTEE (la tache passe a un autre
    executeur) ; un changement de STATUT est un STATUT ; une tache vue pour la
    premiere fois est NOUVELLE. Aucun changement -> aucun evenement : le
    silence est l'absence de changement, pas une panne.
    """
    ev = []
    avant = avant or {}
    for tid, etat_apres in (apres or {}).items():
        etat_avant = avant.get(tid) or {}
        agent_avant = etat_avant.get("agent")
        agent_apres = etat_apres.get("agent")
        statut_avant = etat_avant.get("statut")
        statut_apres = etat_apres.get("statut")
        if not etat_avant:
            ev.append({"task_id": tid, "genre": "NOUVELLE", "de": None,
                       "vers": statut_apres, "agent": agent_apres})
            continue
        if agent_avant is not None and agent_apres is not None and agent_avant != agent_apres:
            ev.append({"task_id": tid, "genre": "REAFFECTEE", "de": agent_avant,
                       "vers": agent_apres, "statut": statut_apres})
        if statut_avant != statut_apres:
            e = {"task_id": tid, "genre": "STATUT", "de": statut_avant, "vers": statut_apres, "agent": agent_apres}
            if statut_apres in ("done", "failed"):
                e["livraison"] = _livraison(etat_apres.get("result"), statut_apres)
            ev.append(e)
    return ev


def _livraison(result, statut) -> str:
    """Livraison d'une tache close, par la fonction CANONIQUE de l'executeur (`_statut_livraison`) -- jamais un
    classement reinvente (30/10 : « done » cachait un commit REFUSE, « failed » cachait 2 fichiers ecrits).
    Resultat absent ou fonction illisible -> ILLISIBLE, jamais rien."""
    if not result:
        return "ILLISIBLE"
    # Un status_code EXPLICITE dans le resultat (cloture manuelle : CANCELLED, ...) prime sur la deduction.
    m = _re.search(r'"status_code"\s*:\s*"([A-Z_]+)"', str(result))
    if m:
        return m.group(1)
    try:
        try:
            from nokido_agent.tools.forge_task_executor import _statut_livraison
        except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
            from forge_task_executor import _statut_livraison
        return _statut_livraison(statut == "done", str(result)) or "ILLISIBLE"
    except Exception:  # noqa: BLE001 - muet-ok : rendu ILLISIBLE sur la ligne de l'owner, donc dit
        return "ILLISIBLE"


def ligne_evenement(e):
    """Ligne courte d'un evenement : « [12:04:05] job_a REAFFECTEE A -> B ».

    Vide si l'evenement est inconnu : une ligne vide ne se lit pas comme un
    succes, elle ne se lit pas du tout.
    """
    import datetime as _dt
    if not e:
        return ""
    genre = e.get("genre")
    tid = e.get("task_id")
    if not genre or not tid:
        return ""
    horodatage = "[%s]" % _dt.datetime.now().strftime("%H:%M:%S")
    if genre == "REAFFECTEE":
        return "%s %s REAFFECTEE %s -> %s" % (horodatage, tid, e.get("de"), e.get("vers"))
    if genre == "STATUT":
        livraison = (" [%s]" % e["livraison"]) if e.get("livraison") else ""
        return "%s %s STATUT %s -> %s%s" % (horodatage, tid, e.get("de"), e.get("vers"), livraison)
    if genre == "NOUVELLE":
        return "%s %s NOUVELLE %s statut=%s" % (horodatage, tid, e.get("agent") or "?", e.get("vers"))
    return ""


def alertes_gel(vue, gel_s, deja):
    """Alertes de GEL : les taches `running` sans progression depuis plus de `gel_s`.

    Chacune UNE SEULE fois (`deja` est memoise sur place). Une progression
    ILLISIBLE (None) n'est JAMAIS un gel : INCONNU n'est pas NO.
    """
    alertes = []
    for t in vue or []:
        if (t.get("statut") or "") != "running":
            continue
        depuis = t.get("depuis_progres_s")
        if depuis is None:
            continue
        tid = t.get("task_id")
        if depuis > gel_s and tid not in deja:
            deja.add(tid)
            alertes.append({"task_id": tid, "agent": t.get("agent"), "statut": t.get("statut"),
                            "age_s": t.get("age_s"), "depuis_progres_s": depuis})
    return alertes


def _ecrire_ligne(ligne):
    """Ecrit UNE ligne sur stdout et la FLUSH immediatement : un Monitor qui reveille
    sa boucle sur chaque ligne ne peut pas attendre un tampon plein."""
    print(ligne, flush=True)


def _id_court(task_id):
    """Identifiant court : les deux premiers segments (`job_15787c78_...` -> `job_15787c78`).

    Le demandeur et l'horodatage du suffixe sont du bruit pour une vue ; les
    evenements, eux, gardent l'identifiant COMPLET (c'est lui qu'on relit).
    """
    if not task_id:
        return "?"
    morceaux = str(task_id).split("_")
    return "_".join(morceaux[:2]) if len(morceaux) > 1 else str(task_id)


def _ligne_vue(t):
    """Ligne de vue d'une delegation : id court, agent, statut, age, progres, reaff."""
    age = t.get("age_s")
    prog = t.get("depuis_progres_s")
    reaff = t.get("reaffectations")
    return "%s %s %s age=%s progres=%s reaff=%s" % (
        _id_court(t.get("task_id")),
        t.get("agent") or "?",
        t.get("statut") or "?",
        ("%ds" % age) if age is not None else "INCONNU",
        ("%ds" % prog) if prog is not None else "INCONNU",
        str(reaff) if reaff is not None else "INCONNU")


def _ligne_gel(a):
    """Ligne d'alerte de GEL : une delegation sans battement depuis trop longtemps."""
    import datetime as _dt
    return "[%s] %s GEL %ds sans progres (statut %s) -- une delegation muette n'est pas " \
           "finie : la relancer ou la relire" % (
               _dt.datetime.now().strftime("%H:%M:%S"), a.get("task_id"),
               a.get("depuis_progres_s") or 0, a.get("statut") or "?")


def suivre_delegations(db=None, de=None, gel_s=900, max_s=4800, intervalle=20,
                        une_fois=False, ecrire=None, horloge=time.time, dormir=time.sleep):
    """Suit les delegations du DEMANDEUR : n'emet que ce qui CHANGE ou ce qui GEL.

    A chaque lecture on prend TOUTES les taches du demandeur -- terminees
    comprises, sinon un `done`/`failed` ne serait JAMAIS vu. Les transitions se
    DEDUISENT de deux lectures (statut ou agent change) ; un gel est une tache
    `running` sans progression depuis plus de `gel_s`, signalee UNE fois chacune.

    `une_fois` : une lecture, la vue imprimee (une ligne par tache), rc 0.
    Sinon : boucle, une ligne par evenement, vidage immediatement (consommable
    par un Monitor), fin sur `max_s`.

    Le silence n'est pas un succes : une base ILLISIBLE est DITE, jamais lue
    comme « aucune delegation ».
    """
    if ecrire is None:
        ecrire = _ecrire_ligne
    chemin = Path(db) if db else TACHES
    if une_fois:
        vue, motif = _lire_taches(db=db, maintenant=time.time(), de=de, statuts=_EN_VOL, limite=None)
        if motif:
            ecrire("DELEGATIONS : %s" % motif)
            return 0
        if not vue:
            ecrire("DELEGATIONS : aucune tache en vol (%s)" % chemin)
            return 0
        for t in vue:
            ecrire(_ligne_vue(t))
        return 0

    debut = horloge()
    etat = {}
    reference = False
    deja = set()
    illisible = 0
    while True:
        maintenant = horloge()
        vue, motif = _lire_taches(db=db, maintenant=maintenant, de=de, statuts=None,
                                   limite=_LIMITE_DEFAUT)
        if motif:
            illisible += 1
            if illisible in (1, 10):
                ecrire("DELEGATIONS : %s -- une delegation pourrait etre en vol sans etre vue" % motif)
        else:
            illisible = 0
            apres = {t["task_id"]: {"agent": t.get("agent"), "statut": t.get("statut"), "result": t.get("result")}
                     for t in vue}
            if reference:
                for e in transitions(etat, apres):
                    ligne = ligne_evenement(e)
                    if ligne:
                        ecrire(ligne)
            else:
                # La premiere lecture POSE la reference : sans elle, tout serait NOUVELLE.
                reference = True
            etat = apres
            for a in alertes_gel(vue, gel_s, deja):
                ecrire(_ligne_gel(a))
        if maintenant - debut > max_s:
            ecrire("DELEGATIONS : fin de veille apres %d s -- a re-armer" % int(maintenant - debut))
            return 0
        dormir(intervalle)


if __name__ == "__main__":
    # Sortie UTF-8 : elle est lue par Monitor, qui affichait « TERMINE rc=0 � le rc » en cp1252
    # (audit des prompts du 15/10, constat 1).
    for _flux in (sys.stdout, sys.stderr):
        if hasattr(_flux, "reconfigure"):
            _flux.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
