#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_organ_pulse.py — SENTINELLE ANTI-EMBOLIE (pouls périodique de l'organisme).

Directive user : « le corps ne doit pas souffrir d'embolie » + automatiser la vérification
périodiquement. Une embolie = un BLOCAGE qui tue le flux : l'event-loop wedgé (crash hub ×3),
une file qui s'engorge, des signaux critiques qui s'accumulent SANS consommateur, l'OOM, un
job coincé. Cette sentinelle BALAYE périodiquement tous les points de blocage OBSERVABLES
cross-process (DB/fichiers/HTTP/psutil — pas l'état in-process du hub) et ALERTE.

Comble le trou trouvé au census (forge_organ_agents:critical_points) : des signaux DÉJÀ ÉMIS
(forge_critical_events.processed_at IS NULL) que PERSONNE ne consomme entre deux boots.

Rôles de check (extensibles — « autant de tours qu'il faudra ») dans CHECKS. Chacun renvoie
(status, detail) où status ∈ clear|warn|embolie. Sur embolie : cortisol + notify facteur +
log durable (logs/organ_pulse.log). watch(interval) = boucle déportée (run_job, survit restart).

ANTI-DUP : fédère forge_loop_sentinel(loop_lag.log) / forge_critical_events / forge_resource_
manager(psutil) / RAG(embeddings.db) / hub /health / forge_endocrine. N'invente aucun moniteur.
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/heartbeat : sentinelle anti-embolie, pouls periodique de l'organisme"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ⚠️ LA RACINE EN PREMIER — et ce n'est pas cosmetique. Lance PAR CHEMIN (c'est
# ainsi que services.toml le demarre), `sys.path[0]` vaut le dossier du SCRIPT.
# Ce module ajoutait `app/` et `tools/` mais PAS la racine, ou vit le package
# `nokido_agent`. Consequence mesuree le 2026-09-20 : le daemon faisait son tour,
# puis mourait sur `ModuleNotFoundError: No module named 'nokido_agent'` en
# important `beat_daemon` pour ecrire son pouls.
#
# Il est donc mort A CHAQUE TOUR depuis le 2026-09-10 06:45, en laissant la
# signature la plus trompeuse qui soit : un journal qui GROSSIT (le tour a lieu)
# et un `.heartbeat` FIGE (l'ecriture n'a jamais lieu). Trois diagnostics faux
# ont precede l'execution qui a tranche. Meme amorce que
# `forge_service_crash_watcher`, qui lui demarre.
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PULSE_LOG = ROOT / "logs" / "organ_pulse.log"


def _stamp(row: dict) -> dict:
    """Date une ligne via l'autorité unique des timecodes (forge_timecode).

    MESURE 2026-07-26 : ce journal est l'ALARME du corps, et il écrivait sans
    aucune date. Conséquence payée le jour même — impossible de placer les
    verdicts EMBOLIE dans la chronologie d'un gel machine ; le post-mortem a dû
    s'en passer. Un fait temporel ne se réfute que par un log, et un log sans
    date ne réfute rien.

    Repli local si le module manque : une date approximative vaut mieux qu'aucune.
    """
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_timecode import stamp_row

        return stamp_row(row)
    except Exception:  # noqa: BLE001
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        row = dict(row)
        row.setdefault("ts", _dt.now(tz=_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        return row
LAG_LOG = ROOT / "logs" / "loop_lag.log"
CRIT_DB = ROOT / "sandbox" / "critical_events.db"
RAG_DB = ROOT / "RAG" / "embeddings.db"
JOBS_DIR = Path("C:/tmp/nokido_jobs")
HUB = "http://127.0.0.1:8766/health"

CLEAR, WARN, EMBOLIE = "clear", "warn", "embolie"

# Seuils (relâchables).
HUB_LAT_S = 2.5          # /health au-delà = event-loop wedgé
LAG_MS = 1800            # lag récent au-delà = embolie event-loop
LAG_RECENT_S = 600       # fenêtre "récent" pour loop_lag.log
CRIT_UNCONSUMED = 25     # signaux critiques non consommés au-delà = caillot
RAM_PCT = 90.0           # RAM au-delà = risque OOM
DISK_FREE_GB = 5.0       # disque libre en-deçà = embolie
JOB_STUCK_S = 1800       # job actif > 30 min sans fin = coincé
JOB_ABANDON_S = 21600    # > 6h sans fin = abandonné (auto-clear, plus une embolie active)
HB_STALE_S = 600         # heartbeat daemon > 10 min = organe mort
WAL_BLOAT_GB = 0.5       # -wal > 500 Mo = WAL non checkpointé (écriture qui s'accumule)
EMBED_BACKLOG = 60000    # chunks non-embeddés au-delà = digestion engorgée


def _check_hub() -> tuple:
    """Event-loop wedgé = /health injoignable ou lent (la cause des 3 crashes)."""
    t0 = time.time()
    try:
        with urllib.request.urlopen(HUB, timeout=4) as r:
            dt = time.time() - t0
            if r.status != 200:
                return EMBOLIE, f"/health status={r.status}"
            return (EMBOLIE if dt > HUB_LAT_S else CLEAR), f"latence={dt*1000:.0f}ms"
    except Exception as e:  # noqa: BLE001
        return EMBOLIE, f"/health injoignable: {type(e).__name__}"


def _check_event_loop() -> tuple:
    """loop_lag.log récent avec un gros lag = event-loop starvé."""
    if not LAG_LOG.exists():
        return CLEAR, "pas de log de lag"
    age = time.time() - LAG_LOG.stat().st_mtime
    if age > LAG_RECENT_S:
        return CLEAR, f"dernier lag il y a {age/60:.0f}min"
    try:
        import re
        tail = LAG_LOG.read_text("utf-8", "ignore")[-4000:]
        lags = [int(x) for x in re.findall(r"lag=(\d+)ms", tail)]
        mx = max(lags) if lags else 0
        return (EMBOLIE if mx >= LAG_MS else WARN if mx else CLEAR), f"lag max récent={mx}ms"
    except Exception as e:  # noqa: BLE001
        return WARN, f"lecture KO: {e}"


def _check_critical_signals() -> tuple:
    """forge_critical_events.processed_at IS NULL = signaux émis NON consommés (le caillot)."""
    if not CRIT_DB.exists():
        return CLEAR, "pas de DB critical_events"
    try:
        con = sqlite3.connect(f"file:{CRIT_DB}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM forge_critical_events "
                        "WHERE processed_at IS NULL").fetchone()[0]
        con.close()
        return (EMBOLIE if n >= CRIT_UNCONSUMED else WARN if n > 5 else CLEAR), \
            f"{n} signaux critiques non consommés"
    except Exception as e:  # noqa: BLE001
        return WARN, f"lecture KO: {e}"


def _check_ram() -> tuple:
    try:
        import psutil
        p = psutil.virtual_memory().percent
        return (EMBOLIE if p >= RAM_PCT else WARN if p >= 80 else CLEAR), f"RAM={p:.0f}%"
    except Exception as e:  # noqa: BLE001
        return WARN, f"psutil KO: {e}"


def _check_disk() -> tuple:
    try:
        import shutil
        free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
        return (EMBOLIE if free_gb < DISK_FREE_GB else CLEAR), f"disque libre={free_gb:.1f}Go"
    except Exception as e:  # noqa: BLE001
        return WARN, f"KO: {e}"


def _check_stuck_jobs() -> tuple:
    """Job déporté sans .rc dans la fenêtre 30min–6h = coincé. Au-delà = abandonné (auto-
    clear, plus une embolie ACTIVE). Évite le faux-positif éternel d'un job mort orphelin."""
    if not JOBS_DIR.exists():
        return CLEAR, "pas de jobs"
    try:
        now = time.time()
        stuck = []
        for log in JOBS_DIR.glob("*.log"):
            if log.with_suffix(".rc").exists():
                continue  # terminé
            age = now - log.stat().st_mtime
            if JOB_STUCK_S < age < JOB_ABANDON_S:
                stuck.append(f"{log.stem}({age/60:.0f}min)")
        return (EMBOLIE if stuck else CLEAR), (f"coincés: {stuck}" if stuck else "aucun job coincé")
    except Exception as e:  # noqa: BLE001
        return WARN, f"KO: {e}"


def _supervised_heartbeats() -> dict:
    """Daemons DÉCLARÉS dans services.toml -> seuil de péremption PROPRE À CHACUN.
    Évite deux faux-positifs : les .heartbeat résiduels de daemons désactivés
    (non déclarés) ET les daemons à cycle long jugés morts sur un seuil de 10 min."""
    import re as _re
    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    if not toml.exists():
        return {}
    txt = toml.read_text("utf-8", "ignore")
    out = {}
    for block in _re.split(r"\n(?=\[)", txt):
        m = _re.search(r'heartbeat\s*=\s*"sandbox/([\w.]+)\.heartbeat"', block)
        if not m:
            continue
        # disabled = true => service ON-DEMAND (wake via forge_supervisor_ctl.py
        # ensure ...). Il ne DOIT pas battre : l'exiger produisait 6 faux
        # "organes morts" (mesure 2026-07-22) et un verdict EMBOLIE permanent.
        if _re.search(r"^\s*disabled\s*=\s*true", block, _re.M):
            continue
        name = m.group(1)
        arg = _re.search(r'"--interval"\s*,\s*"(\d+)"', block)
        interval = int(arg.group(1)) if arg else HB_INTERVAL_S.get(name, 0)
        out[name] = max(HB_STALE_S, interval * 3)
    return out


# Morts ASSUMES (curation GO user 2026-07-07) : declares dans services.toml
# mais volontairement arretes/remplaces -> exclus du VERDICT embolie (sinon
# _alert re-latche CORTISOL_FRUSTRATION 0.9 toutes les 10min a tort). Restent
# visibles dans le detail (capteur honnete). Reactiver = retirer d'ici.
# - gemini_autonomous / gemini_poll_daemon : Gemini CLI MORT 2026-07-04
# - embed_auto_trigger : remplace par hepatocyte pluripotent + backfill :8099
# - embed_worker_isolated : brain_worker :5557 DISABLED OOM 2026-06-03
# - lmstudio_keeper / lmstudio_server : arretes par design (deadlock RAM keeper,
#   chantier RAM CLOS par l owner 2026-07-22) -> ne pas relancer, ne pas crier.
PARKED_DAEMONS = {"gemini_autonomous", "gemini_poll_daemon",
                  "embed_auto_trigger", "embed_worker_isolated",
                  "lmstudio_keeper", "lmstudio_server"}

# Cadence REELLE des daemons dont l intervalle est code en dur (absent du toml).
# Un daemon a cycle long n est PAS mort parce qu il n a pas battu depuis 10 min :
# seuil = max(HB_STALE_S, 3x son intervalle). Mesure 2026-07-22 : skill_curator
# (6h), hebbian_linker (6h), log_retention (24h), memory_consolidator (12h)
# etaient comptes STALE a tort -> verdict EMBOLIE permanent -> _alert re-latchait
# CORTISOL_FRUSTRATION 0.9 toutes les 10 min sur un capteur faux.
HB_INTERVAL_S = {
    "hebbian_linker": 21600,
    "skill_curator": 21600,
    "memory_consolidator": 43200,
    "log_retention": 86400,
}


_SUPERVISOR_STATUS = "http://127.0.0.1:8765/supervisor/status"
BOOT_GRACE_S = 300  # au-delà, le corps est réputé réveillé
BOOT_Z_TOLERANCE = 1.5  # écart toléré à l'attendu APPRIS pendant le réveil


def _supervisor_uptime_s():
    """Âge du superviseur = max des uptime_s de ses services. None si injoignable.

    None n'est PAS zéro : injoignable veut dire « je ne sais pas dans quelle phase
    je suis », et l'appelant doit alors retomber sur la règle STRICTE. Confondre
    les deux ferait relâcher les exigences précisément quand on ne voit plus rien.
    """
    try:
        with urllib.request.urlopen(_SUPERVISOR_STATUS, timeout=3) as _r:
            _svc = (json.loads(_r.read().decode("utf-8", "replace")) or {}).get("services") or {}
        _ups = [v.get("uptime_s") for v in _svc.values()
                if isinstance(v, dict) and isinstance(v.get("uptime_s"), (int, float))]
        return max(_ups) if _ups else None
    except Exception:  # noqa: BLE001
        return None


def _body_phase() -> str:
    """Phase du corps — le CONTEXTE dans lequel un capteur doit être lu.

    Le même chiffre ne dit pas la même chose à T+70 s d'un boot et après six heures
    de régime établi. Sans cette notion, un capteur confond « pas encore né » et
    « mort » : c'est exactement l'erreur du 29-07.
    """
    up = _supervisor_uptime_s()
    if up is None:
        return "steady"  # fail-safe : on ne relâche AUCUNE exigence
    if up < 120:
        return "boot_0_2m"
    if up < BOOT_GRACE_S:
        return "boot_2_5m"
    return "steady"


def _check_daemon_heartbeats() -> tuple:
    """Heartbeats des daemons SUPERVISÉS DÉCLARÉS (services.toml) trop vieux = organe MORT.
    Ne flagge QUE les daemons attendus (pas les .heartbeat résiduels = bruit)."""
    sup = _supervised_heartbeats()
    if not sup:
        return CLEAR, "services.toml illisible"
    try:
        now = time.time()
        hb_dir = ROOT / "sandbox"
        stale = [n for n, limit in sup.items()
                 if not (hb_dir / f"{n}.heartbeat").exists()
                 or now - (hb_dir / f"{n}.heartbeat").stat().st_mtime > limit]
        parked = sorted(set(stale) & PARKED_DAEMONS)
        stale = [n for n in stale if n not in PARKED_DAEMONS]
        _extra = f" | parked({len(parked)}): {parked}" if parked else ""
        n_stale, n_tot = len(stale), len(sup)
        phase = _body_phase()
        # PRÉDICTIF : on apprend l'attendu de CETTE phase, et la surprise se lit sur le
        # modèle qui avait cours (observe_signal calcule z AVANT sa propre mise à jour).
        z = None
        try:
            from nokido_agent.app import forge_active_inference as _ai
            z = _ai.observe_signal("daemons_stale", phase, float(n_stale)).get("z")
        except Exception:  # noqa: BLE001 — le pouls ne casse jamais sur son modèle
            pass
        _ctx = f" | phase={phase}" + (f" z={z}" if z is not None else " (modèle immature)")
        _detail = f"{n_stale}/{n_tot} daemons déclarés stale: {sorted(stale)[:6]}{_extra}{_ctx}"
        if phase.startswith("boot"):
            # Pendant le réveil, l'absence EST l'état normal. Escalader ici arme le
            # cortisol, qui fait refuser les spawns, qui perpétue l'absence — la boucle
            # mesurée le 29-07 (19/29 stale à T+70 s, 471 spawns refusés). On alerte
            # donc au plus en WARN, jamais en EMBOLIE, et l'attendu appris tranche.
            if z is not None and z <= BOOT_Z_TOLERANCE:
                return CLEAR, _detail
            return (WARN if n_stale else CLEAR), _detail
        return (EMBOLIE if n_stale >= 5 else WARN if stale else CLEAR), _detail
    except Exception as e:  # noqa: BLE001
        return WARN, f"KO: {e}"


def _check_db_locks() -> tuple:
    """DB SQLite verrouillée = un écrivain bloque tout le monde (caillot de persistance)."""
    locked = []
    for db in (RAG_DB, CRIT_DB, ROOT / "sandbox" / "audit.db", ROOT / "sandbox" / "event_stream.db"):
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(str(db), timeout=2)
            con.execute("SELECT 1").fetchone()
            con.close()
        except Exception as e:  # noqa: BLE001
            if "lock" in str(e).lower():
                locked.append(db.name)
    return (EMBOLIE if locked else CLEAR), (f"verrouillées: {locked}" if locked else "aucun lock DB")


def _check_wal_bloat() -> tuple:
    """Fichier -wal qui enfle = WAL non checkpointé (l'écriture s'accumule sans fusion)."""
    big = []
    for d in (RAG_DB.parent, ROOT / "sandbox"):
        if not d.exists():
            continue
        try:
            for wal in d.glob("*.db-wal"):
                gb = wal.stat().st_size / 1e9
                if gb >= WAL_BLOAT_GB:
                    big.append(f"{wal.name}={gb:.1f}Go")
        except Exception:  # noqa: BLE001
            pass
    return (EMBOLIE if big else CLEAR), (f"WAL enflés: {big}" if big else "WAL sains")


def _check_embed_backlog() -> tuple:
    """Chunks en attente de vecteur qui s'accumulent = digestion engorgée.

    Lu chez le PRODUCTEUR (forge_memory_availability.snapshot, ecrit hors chemin
    chaud, la nuit), jamais recompte ici : le COUNT(*) sur rag_chunks toutes les
    600 s lisait 107 Mo/s de la base de 24,9 Go (mesure 2026-09-05), meme famille
    que le COUNT(*) qui a couche le hub le 03/09 -- c'est ce qui a fait couper ce
    service. `vector_pending` = chunks vectorisables SANS vecteur ; les tiers
    refuses par politique sont a part, comme le voulait deja le correctif du
    2026-07-07 (embedding_model IS NULL = le vrai working-set). Un snapshot perime
    ou absent rend WARN avec sa raison : une absence de mesure n'est ni un zero ni
    une embolie.
    """
    try:
        _app = str(ROOT / "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_memory_availability import snapshot
        snap = snapshot()
        if not snap.get("frais"):
            return WARN, f"backlog INCONNU : {snap.get('raison')}"
        n = int(snap.get("vector_pending") or 0)
        return (EMBOLIE if n >= EMBED_BACKLOG else WARN if n > 10000 else CLEAR), \
            f"{n} chunks en attente de vecteur (snapshot vieux de {float(snap.get('age_s') or 0):.0f} s)"
    except Exception as e:  # noqa: BLE001
        return WARN, f"KO: {e}"


def _check_cortisol() -> tuple:
    """Cortisol chronique élevé = stress soutenu (échecs/quota) — pré-embolie."""
    try:
        from nokido_agent.app.forge_endocrine import read as _hr
        c = max(float(_hr("CORTISOL_FRUSTRATION") or 0.0), float(_hr("CORTISOL_QUOTA_CLOUD") or 0.0))
        return (EMBOLIE if c >= 0.9 else WARN if c >= 0.6 else CLEAR), f"cortisol={c:.2f}"
    except Exception as e:  # noqa: BLE001
        return CLEAR, f"endocrinien indispo ({type(e).__name__})"


def _check_nerve_plug() -> tuple:
    """NERF QUI LÂCHE : module cœur qui ne s'importe plus (sectionné=embolie) ou composant
    disparu vs baseline (drift=warn). Branche forge_nervous_map.plug_report dans le pouls —
    le corps SAIT quand un nerf se débranche (suite logique de la carte nerveuse)."""
    try:
        from nokido_agent.app.forge_nervous_map import plug_report
        pr = plug_report()
        if pr.get("severed"):
            return EMBOLIE, f"nerfs sectionnés (import KO): {pr['severed'][:4]}"
        if pr.get("vanished"):
            return WARN, f"composants disparus vs baseline: {pr['vanished'][:5]}"
        return CLEAR, f"{pr.get('total', '?')} composants pluggés, sains"
    except Exception as e:  # noqa: BLE001
        return WARN, f"carte nerveuse indispo: {type(e).__name__}"


# Services ARRETES par design qui declarent un port : ne pas les compter muets
# (symetrique de PARKED_DAEMONS cote heartbeat).
MUTE_OK = {"NokidoLMStudio"}


def _check_mute_ports() -> tuple:
    """ORGANE MUET : service ACTIF qui declare un port mais n ecoute pas.

    Comble une zone aveugle mesuree le 2026-07-22 : sur 76 services declares,
    seuls 31 portent un heartbeat, donc _check_daemon_heartbeats n en surveille
    que 18. Les 31 autres (embed :8099, reranker :8100, qdrant, webhub...) peuvent
    mourir sans qu aucun check ne le dise. Ici le PORT tient lieu de pouls.
    Severite : EMBOLIE si essential=true (le corps ne peut pas fonctionner sans),
    WARN sinon -- volontairement conservateur, un check qui crie en permanence
    re-latche le cortisol et rend le garde inutile.
    """
    import re as _re
    import socket as _sk

    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    if not toml.exists():
        return CLEAR, "services.toml illisible"
    try:
        txt = toml.read_text("utf-8", "ignore")
        mute, mute_ess = [], []
        for block in _re.split(r"\n(?=\[\[service\]\])", txt):
            nm = _re.search(r'^\s*name\s*=\s*"([\w\-]+)"', block, _re.M)
            if not nm or nm.group(1) in MUTE_OK:
                continue
            if _re.search(r"^\s*disabled\s*=\s*true", block, _re.M):
                continue  # on-demand : n a pas a ecouter
            if _re.search(r'heartbeat\s*=\s*"sandbox/', block):
                continue  # deja couvert par _check_daemon_heartbeats
            pm = _re.search(r"^\s*port\s*=\s*(\d+)", block, _re.M)
            if not pm:
                continue
            port = int(pm.group(1))
            s = _sk.socket()
            s.settimeout(0.4)
            try:
                s.connect(("127.0.0.1", port))
            except OSError:
                tag = f"{nm.group(1)}:{port}"
                if _re.search(r"^\s*essential\s*=\s*true", block, _re.M):
                    mute_ess.append(tag)
                else:
                    mute.append(tag)
            finally:
                s.close()
        n_mute = len(mute) + len(mute_ess)
        phase = _body_phase()
        z = None
        try:
            from nokido_agent.app import forge_active_inference as _ai
            z = _ai.observe_signal("ports_muets", phase, float(n_mute)).get("z")
        except Exception:  # noqa: BLE001 — le pouls ne casse jamais sur son modèle
            pass
        _ctx = f" | phase={phase}" + (f" z={z}" if z is not None else " (modèle immature)")

        if phase.startswith("boot"):
            # Un port pas encore OUVERT n'est pas un organe MUET. Au réveil, les
            # services démarrent en vagues et le gate peut légitimement en différer :
            # l'absence d'écoute est l'état ATTENDU, pas une pathologie. Escalader ici
            # arme le cortisol, qui fait refuser les spawns, donc empêche précisément
            # ces ports de s'ouvrir — la boucle mesurée le 29-07, où ce capteur criait
            # « organes ESSENTIELS muets: ['NokidoDenoWebHub:7401'] » à T+0 d'un boot,
            # aux côtés de daemon_heartbeats. Les deux capteurs, un seul défaut.
            if not n_mute:
                return CLEAR, "tous les services a port declare ecoutent" + _ctx
            if z is not None and z <= BOOT_Z_TOLERANCE:
                return CLEAR, f"{n_mute} port(s) pas encore ouvert(s) — attendu au reveil{_ctx}"
            return WARN, f"{n_mute} port(s) pas encore ouvert(s): {sorted(mute_ess + mute)[:6]}{_ctx}"

        # Régime établi : sévérité INCHANGÉE. Un service essentiel muet après le
        # réveil est bien une embolie — c'est là que ce capteur gagne sa place.
        if mute_ess:
            return EMBOLIE, f"organes ESSENTIELS muets: {sorted(mute_ess)} | autres: {sorted(mute)[:4]}{_ctx}"
        if mute:
            return WARN, f"{len(mute)} organes muets (non essentiels): {sorted(mute)[:6]}{_ctx}"
        return CLEAR, "tous les services a port declare ecoutent" + _ctx
    except Exception as e:  # noqa: BLE001
        return WARN, f"KO: {e}"


def _check_port_clashes() -> tuple:
    """Clash de port = wedge silencieux (un service ne peut pas binder). Detecte les
    collisions de CONFIG via le registre canonique forge_ports. Pour l'audit live
    (qui ecoute quoi) : forge_ports.owner_report / CLI tools/forge_ports.py."""
    try:
        from nokido_agent.tools.forge_ports import reserved_collisions, PORTS
    except Exception as e:  # noqa: BLE001
        return WARN, f"forge_ports indisponible: {e}"
    coll = reserved_collisions()
    if coll:
        return EMBOLIE, f"clash config ports: {coll}"
    return CLEAR, f"{len(PORTS)} ports reserves, 0 clash config"


def _check_comm_bricks() -> tuple:
    """Perception des briques de comm CLI : lit l'etat du daemon forge_comm_watch
    (tourne en contexte owner ; le pouls le LIT, marche hors-owner). Daemon mort
    (stale) ou changement recent de brique = signal a remonter."""
    try:
        from nokido_agent.tools import forge_comm_watch as _cw

        st = _cw.status()
    except Exception as e:  # noqa: BLE001
        return WARN, f"comm_watch indispo: {e}"
    if st.get("ts") is None:
        return WARN, "comm_watch jamais execute (daemon owner non lance ?)"
    if (st.get("stale_s") or 0) > 3600:
        return WARN, f"comm_watch stale {st['stale_s']}s (daemon owner arrete ?)"
    ch = st.get("last_changes") or []
    if ch:
        return WARN, f"{len(ch)} brique(s) comm changee(s): {[c.get('brick') for c in ch][:5]}"
    return CLEAR, "briques comm stables"


# Roster de checks (extensible — ajouter un rôle = une ligne).
def _check_phantom_services() -> tuple:
    """Service DECLARE `running` dont le pid est MORT — le superviseur continue
    d'annoncer un uptime_s qui grimpe. Mesure 2026-07-29 : NokidoQdrantSync mort
    depuis 3 h sous un `running`, la file de sync n'etait plus drainee et personne
    ne le signalait. Signe d'ABSENCE : on alerte, on ne relache PAS de cortisol
    (freiner le spawn empecherait justement le respawn)."""
    try:
        from nokido_agent.tools.forge_process_inventory import collect
    except Exception as e:  # noqa: BLE001
        return WARN, f"forge_process_inventory indisponible: {e}"
    try:
        rapport = collect()
    except Exception as e:  # noqa: BLE001
        return WARN, f"inventaire KO: {e}"
    fantomes = [f["service"] for f in rapport.get("fantomes", [])]
    figes = [f["service"] for f in rapport.get("figes", [])]
    if fantomes:
        return EMBOLIE, f"pid mort sous un running: {fantomes}" + (
            f" | heartbeat fige: {figes}" if figes else ""
        )
    if figes:
        return WARN, f"heartbeat fige (pid vivant, boucle morte): {figes}"
    tot = rapport.get("totaux", {})
    return CLEAR, (
        f"{tot.get('declares_avec_pid_vivant')}/{tot.get('services_declares')} "
        f"services avec pid vivant, 0 fantome"
    )


# Activite du tour PRECEDENT : {nom: (cpu_s, io_octets, ts)}. On compare deux
# instants -- `cpu_percent()` sans intervalle rend 0.0, et un snapshot ferait passer
# tout organe pour inerte.
_ACTIVITE_PREC: dict = {}

# Seuils de l'activite dite PRESENTE. Volontairement bas : on cherche a distinguer
# VIVANT de GELE, pas a mesurer une charge.
ACT_CPU_S = 0.05          # 50 ms de CPU entre deux tours
ACT_IO_OCTETS = 4096      # ou 4 Ko lus/ecrits


def _activite(nom: str, pid) -> tuple:
    """Activite materielle d'un organe depuis le tour precedent.

    Rend (actif, detail) ou `actif` a TROIS valeurs : True, False, ou None quand on
    n'a pas pu regarder.

    LE CPU NE QUALIFIE RIEN, DANS AUCUN DES DEUX SENS. Une boucle infinie tient
    100 % d'un coeur sans rien produire ; un travail I/O-bound (crawl, embedding
    distant, rebuild FTS) consomme un CPU quasi nul en travaillant vraiment -- c'est
    exactement l'erreur qui a fait TUER un job en plein travail le 2026-09-01, sur
    la lecture « CPU bas donc bloque ». On regarde donc le CPU **et** les I/O, et on
    ne conclut a l'inertie que si les DEUX sont plats.

    `None` (illisible) n'est PAS `False` (inerte) : sous un compte de service, 331
    process sur 339 refusent la lecture (mesure 2026-08-14). Accuser un organe sur
    un refus de lecture serait fabriquer une pathologie.
    """
    if not isinstance(pid, int):
        return None, "pid inconnu au registre"
    try:
        import psutil
    except Exception as e:  # noqa: BLE001
        return None, "psutil indisponible (%s)" % type(e).__name__
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            ct = p.cpu_times()
            cpu_s = float(ct.user) + float(ct.system)
            try:
                io = p.io_counters()
                io_o = float(io.read_bytes) + float(io.write_bytes)
            except Exception:  # noqa: BLE001  # muet-ok : les compteurs d'E/S sont
                # refuses plus souvent que le CPU ; l'absence est portee par le
                # `None` de io_o, et le detail en dessous la nomme.
                io_o = None
    except psutil.NoSuchProcess:
        return None, "process absent (le registre le dit vivant)"
    except (psutil.AccessDenied, Exception) as e:  # noqa: BLE001
        return None, "lecture refusee (%s)" % type(e).__name__

    now = time.time()
    prec = _ACTIVITE_PREC.get(nom)
    _ACTIVITE_PREC[nom] = (cpu_s, io_o, now)
    if not prec:
        return None, "premiere mesure (aucune reference de delta)"
    d_cpu = cpu_s - prec[0]
    d_io = (io_o - prec[1]) if (io_o is not None and prec[1] is not None) else None
    if d_cpu < 0 or (d_io is not None and d_io < 0):
        # Compteurs qui reculent = process remplace : la reference ne vaut plus.
        return None, "compteurs remis a zero (process remplace ?)"
    fenetre = now - prec[2]

    # ORDRE DELIBERE, et il porte toute la semantique de ce capteur.
    #
    # 1. Le CPU qui bouge est une preuve POSITIVE d'activite : elle se suffit, et
    #    l'illisibilite des E/S ne la retire pas.
    if d_cpu >= ACT_CPU_S:
        return True, "cpu +%.2fs sur %.0fs" % (d_cpu, fenetre)
    # 2. Le CPU est plat. Sans les E/S, on n'a RIEN mesure -- un travail I/O-bound
    #    (crawl, embedding distant, rebuild FTS) consomme un CPU quasi nul EN
    #    TRAVAILLANT. Conclure `False` ici serait exactement le defaut que ce module
    #    combat : « je ne peux pas mesurer » deviendrait « ca ne bouge pas », et un
    #    organe sain se retrouverait suspect puis gele. ABSENCE DE PREUVE D'ACTIVITE
    #    N'EST PAS PREUVE D'ABSENCE D'ACTIVITE.
    if d_io is None:
        return None, ("cpu +%.2fs sur %.0fs mais E/S ILLISIBLES — inertie NON "
                      "etablie" % (d_cpu, fenetre))
    # 3. Les deux sont lisibles et plats : l'inertie est MESUREE, pas supposee.
    return (d_io >= ACT_IO_OCTETS), "cpu +%.2fs, io +%.0f o sur %.0fs" % (
        d_cpu, d_io, fenetre)


def _check_organes_bloques() -> tuple:
    """BLOQUE ou OCCUPE ? La question que ni le pouls ni le superviseur ne tranchent.

    Depuis que `forge_heartbeat.Cadence` declare `travail_en_cours`, le superviseur
    s'abstient de relancer un organe qui travaille -- ce qui evite de tuer un crawl
    de quatre minutes, mais laisse ouverte la question qu'il ne peut pas juger : ce
    travail AVANCE-T-IL ? Le superviseur constate, il n'instruit pas. C'est ici qu'on
    instruit, en croisant TROIS sources qu'aucune ne suffit seule :

        le registre    le process existe-t-il, et depuis quand
        le pouls       l'organe declare-t-il un travail, et depuis quand
        le metabolisme consomme-t-il quelque chose (CPU **et** I/O)

    On rend une QUALIFICATION, jamais une action. Tuer reste au superviseur, avec
    son plafond ; ce check sert a nommer ce qui se passe avant qu'on en arrive la.
    """
    seuils = _supervised_heartbeats()
    if not seuils:
        return WARN, "registre des heartbeats illisible — aucune qualification possible"
    try:
        brut = json.load(urllib.request.urlopen(_SUPERVISOR_STATUS, timeout=1.5))
    except (OSError, ValueError) as e:
        # UNIQUEMENT les echecs de TRANSPORT et de PARSE. Un `except Exception` ici a
        # deja fait dire « superviseur injoignable (NameError) » sur un defaut de CE
        # fichier : un capteur qui rattrape tout finit par accuser un autre organe de
        # sa propre panne. Le reste remonte a `pulse()`, qui le nommera « check KO ».
        return WARN, "superviseur injoignable (%s) — sans registre, rien a croiser" % type(e).__name__
    svc = brut.get("services") or brut
    paires = svc.items() if isinstance(svc, dict) else [(s.get("name"), s) for s in svc]

    geles, suspects, inconnus, occupes = [], [], [], 0
    # DENOMINATEUR, et il n'est pas decoratif. Mesure du 2026-09-03 : ce check a rendu
    # `clear` sept fois de suite pendant qu'un organe declarait un travail. La cause
    # etait un `_json.loads` inexistant, dont le NameError tombait dans le `except`
    # ci-dessous et sortait par un `continue` MUET -- tous les organes ecartes, verdict
    # vert. Un capteur qui ne publie pas ce qu'il a ECARTE ne peut pas etre pris en
    # defaut : sa cecite ressemble a une bonne nouvelle.
    vu = {"running": 0, "sans_pouls_declare": 0, "pouls_illisible": 0,
          "pouls_non_objet": 0, "sans_travail": 0, "qualifies": 0}
    for nom_svc, v in paires:
        if not isinstance(v, dict) or v.get("status") != "running":
            continue
        vu["running"] += 1
        chemin = v.get("heartbeat_path")
        if not chemin:
            vu["sans_pouls_declare"] += 1
            continue
        p = ROOT / str(chemin).lstrip("./")
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            # UNIQUEMENT lecture et parse. Un `except Exception` ici a deja avale un
            # defaut de ce fichier et rendu un vert. Un organe sans pouls lisible
            # releve de `daemon_heartbeats` ; il reste COMPTE ci-dessous.
            vu["pouls_illisible"] += 1
            continue
        # Tous les pouls ne sont pas des OBJETS : certains organes ecrivent un float
        # nu (un horodatage). `json.loads` reussit, et l'appel suivant explose --
        # mesure du 2026-09-03, un `.heartbeat` sur les vingt-huit lisibles.
        if not isinstance(d, dict):
            vu["pouls_non_objet"] += 1
            continue
        if d.get("travail_en_cours") is not True:
            vu["sans_travail"] += 1
            continue
        vu["qualifies"] += 1
        # Duree REELLE : un process gele n'ecrit plus, donc son `travail_depuis_s`
        # est FIGE et son fichier a vieilli d'autant. La somme est la seule verite.
        age_fichier = max(0.0, time.time() - p.stat().st_mtime)
        declare = float(d.get("travail_depuis_s") or 0.0)
        duree = declare + age_fichier
        cle = str(chemin).rsplit("/", 1)[-1].replace(".heartbeat", "")
        seuil = seuils.get(cle, HB_STALE_S)
        actif, det = _activite(cle, v.get("pid"))
        etiquette = "%s(travail %.0fmin, %s)" % (nom_svc, duree / 60, det)
        if actif is None:
            inconnus.append(etiquette)
        elif actif:
            occupes += 1                      # travail reel : rien a signaler
        elif duree > 4 * seuil:
            geles.append(etiquette)           # inerte ET au-dela du plafond
        else:
            suspects.append(etiquette)        # inerte, mais dans les clous

    vu["actifs"] = occupes
    vu["activite_illisible"] = len(inconnus)
    if geles:
        return EMBOLIE, ("GELES (aucune activite, travail au-dela du plafond) : %s | "
                         "suspects: %d | %s" % (geles, len(suspects), vu))
    if suspects:
        return WARN, "travail declare SANS activite mesurable : %s | %s" % (suspects, vu)
    return CLEAR, "aucun travail inerte | %s" % (vu,)


CHECKS = [
    ("hub_health", _check_hub),
    ("organes_bloques", _check_organes_bloques),  # occupe vs gele (progres x activite)
    ("phantom_services", _check_phantom_services),  # declare running / pid mort
    ("port_clashes", _check_port_clashes),
    ("comm_bricks", _check_comm_bricks),
    ("event_loop", _check_event_loop),
    ("critical_signals", _check_critical_signals),
    ("ram", _check_ram),
    ("disk", _check_disk),
    ("stuck_jobs", _check_stuck_jobs),
    ("embed_backlog", _check_embed_backlog),
    ("cortisol", _check_cortisol),
    ("daemon_heartbeats", _check_daemon_heartbeats),  # organe mort (heartbeat stale)
    ("db_locks", _check_db_locks),                    # caillot de persistance (SQLite lock)
    ("wal_bloat", _check_wal_bloat),                  # WAL non checkpointé
    ("nerve_plug", _check_nerve_plug),                # nerf qui lâche (module sectionné / drift)
    ("mute_ports", _check_mute_ports),                # organe muet (port déclaré qui n'écoute pas)
]


def pulse() -> dict:
    """Un POULS : balaie tous les checks. Renvoie le diagnostic + verdict global."""
    points, embolies, warns = {}, [], []
    for name, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001 - un check KO ne casse pas le pouls
            status, detail = WARN, f"check KO: {e}"
        points[name] = {"status": status, "detail": detail}
        if status == EMBOLIE:
            embolies.append(name)
        elif status == WARN:
            warns.append(name)
    verdict = EMBOLIE if embolies else WARN if warns else CLEAR
    # Axe C : publie la santé dans le tier RAM hot (forge_state, <1µs, zéro disque ->
    # remplace health.json — les agents lisent forge_state.read_health()). Best-effort.
    try:
        import psutil as _ps
        import shutil as _sh
        from nokido_agent.app.forge_state import publish_health as _pub

        _pub(
            cpu_pct=round(_ps.cpu_percent(interval=0.0), 1),
            ram_pct=round(_ps.virtual_memory().percent, 1),
            disk_free_gb=round(_sh.disk_usage(str(ROOT)).free / 1e9, 1),
            hub_up=(points.get("hub", {}).get("status") == CLEAR),
            verdict=verdict,
        )
    except Exception:  # noqa: BLE001 — la publication santé ne casse jamais le pouls
        pass
    return {"verdict": verdict, "embolies": embolies, "warns": warns, "points": points}


# Signes d'ABSENCE : points de pouls qui constatent qu'un organe MANQUE (daemon
# sans heartbeat, port déclaré qui n'écoute pas). Ils ne disent rien d'une
# surcharge — ils disent qu'il faut DÉMARRER quelque chose. Cf. _alert.
ABSENCE_SIGNS = frozenset({"daemon_heartbeats", "mute_ports", "phantom_services"})


def _alert(p: dict) -> None:
    """Sur embolie : cortisol (endocrine) + notify facteur (hub) + log durable. Non bloquant."""
    msg = f"[ANTI-EMBOLIE] {p['verdict'].upper()} — embolies={p['embolies']} warns={p['warns']}"
    PULSE_LOG.parent.mkdir(exist_ok=True)
    try:
        with open(PULSE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(_stamp({"msg": msg, "points": p["points"]}),
                               ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).error(
            "[organ_pulse] pouls NON journalise (%s: %s) | consequence: ce battement "
            "n'existe nulle part, et une serie de pouls trouee se lit comme un organe "
            "intermittent", type(e).__name__, str(e)[:90])
    if p["verdict"] != EMBOLIE:
        return
    # ── GARDE ANTI-EMBOLIE IATROGÈNE (mesure horodatée 2026-07-29) ───────────
    # Le cortisol alimente l'efférent should_throttle(), qui REFUSE les spawns.
    # Or freiner le spawn ne peut JAMAIS soigner un MANQUE d'organes. Mesure :
    # au 1er cycle suivant un boot du superviseur (08:16:06), 19/29 daemons
    # étaient stale — état NORMAL à T+0, personne n'a encore eu le temps de
    # battre — verdict EMBOLIE, cortisol 0.9, et 1 seconde plus tard (08:16:07)
    # la rafale de refus démarrait : 471 spawns refusés en 5 min, dont les deux
    # piliers RAG (llama embed :8099, reranker :8100) et le WebHub :7400. Les
    # daemons restaient donc stale, et le cycle suivant re-latchait 0.9. Le
    # capteur mesurait l'effet de son propre effecteur — même famille que
    # l'auto-empoisonnement du 25-07, ici via l'endocrine plutôt que le disque.
    # RÈGLE : un verdict fondé UNIQUEMENT sur des signes d'ABSENCE ne relâche
    # pas l'hormone qui empêche de combler cette absence. Le notify part quand
    # même : on alerte sans se paralyser. Un blocage RÉEL (event_loop, db_locks,
    # stuck_jobs, wal_bloat, ram, disk, critical_signals) la relâche toujours.
    _absence_seule = bool(p["embolies"]) and set(p["embolies"]) <= ABSENCE_SIGNS
    if _absence_seule:
        try:
            with open(PULSE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(_stamp({
                    "msg": "[ANTI-EMBOLIE] cortisol NON relâché — embolie d'ABSENCE seule : "
                           "freiner le spawn ne comble pas un manque d'organes",
                    "embolies": p["embolies"]}), ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger(__name__).warning(
                "[organ_pulse] note ANTI-EMBOLIE non ecrite (%s: %s) | consequence: la "
                "raison pour laquelle le cortisol n'a PAS ete relache est perdue, et "
                "l'absence d'hormone paraitra inexpliquee",
                type(e).__name__, str(e)[:90])
    else:
        try:  # cortisol : l'organisme RESSENT le blocage (alimente l'efferent du gate)
            from nokido_agent.app.forge_endocrine import release
            release("CORTISOL_FRUSTRATION", level=0.9, ttl_s=1800, source="organ_pulse")
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Une hormone non relachee = un signal que ses recepteurs n'auront jamais.
            # Le corps RESSENT alors moins que ce qu'il subit, et l'efferent du gate
            # reste au repos sur un blocage reel.
            _lg.getLogger(__name__).error(
                "[organ_pulse] CORTISOL_FRUSTRATION NON relache (%s: %s) | consequence: "
                "le blocage est reel mais aucun recepteur ne le saura",
                type(e).__name__, str(e)[:90])
    # 2026-08-05 — CE BLOC NE MARCHAIT PAS, ET PERSONNE NE POUVAIT LE SAVOIR.
    # Format {"tool":..., "args":...} qui n'est PAS du JSON-RPC 2.0, AUCUN en-tete
    # Authorization, et `except: pass`. Mesure : ce daemon (pid vu 8992, compte
    # AUTORITE NT\Systeme) etait l'un des deux emetteurs des 4 730 rejets `no_auth`
    # du hub sur 24 h. Le pouls d'organe alertait donc dans le vide depuis toujours.
    import logging as _logging
    _jlog = _logging.getLogger(__name__)
    try:  # notify facteur (réveille la coagulation/humain)
        import sys as _sys
        _app = str(ROOT / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_hub_client import HubClient  # client GOUVERNE (identite + coffre)

        _rep = HubClient(agent="ORGAN_PULSE").notify(json.dumps({
            "intent": "NEED_HUMAN_APPROVAL",
            "pointer_ref": "organ_pulse:heartbeat",
            "confidence": 1.0,
            "detail": msg,
        }, ensure_ascii=False))
        if _rep is None:
            _jlog.error("[ORGAN_PULSE] ALERTE NON DELIVREE (hub injoignable) : %s "
                        "| consequence: ce pouls anormal n'a alerte PERSONNE", msg)
        elif isinstance(_rep, str) and ("GATE_DENIED" in _rep or "Erreur" in _rep):
            _jlog.error("[ORGAN_PULSE] ALERTE REFUSEE par le hub : %s | message: %s "
                        "| remede: verifier le ring d'ORGAN_PULSE dans "
                        "config/agent_identities.json (notify exige ring <= 3)",
                        _rep, msg)
        else:
            _jlog.info("[ORGAN_PULSE] alerte delivree au hub : %s", msg)
    except Exception as _e:  # noqa: BLE001
        _jlog.error("[ORGAN_PULSE] ALERTE IMPOSSIBLE (%s: %s) : %s | consequence: "
                    "ce pouls anormal n'a alerte PERSONNE",
                    type(_e).__name__, str(_e)[:120], msg)


HEARTBEAT = ROOT / "sandbox" / "organ_pulse.heartbeat"


def watch(interval: int = 600, rounds: int = 0) -> int:
    """Boucle (déportée run_job OU supervisée services.toml). Pouls tous les `interval`s ;
    HEARTBEAT toutes les ~60s (frais pour le superviseur même si le pouls est espacé -> pas
    de faux 'mort' / restart-loop). rounds=0 -> infini."""
    i, last = 0, 0.0
    p = {"verdict": CLEAR, "embolies": [], "warns": []}
    while rounds == 0 or i < rounds:
        now = time.time()
        if i == 0 or now - last >= interval:
            p = pulse()
            _alert(p)
            last = now
            print(json.dumps({"verdict": p["verdict"], "embolies": p["embolies"],
                              "warns": p["warns"]}, ensure_ascii=False), flush=True)
        # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le
        # `pid` absent et ne leve jamais, le garde local devient inutile.
        from nokido_agent.app.forge_heartbeat import beat_daemon

        beat_daemon("organ_pulse", verdict=p.get("verdict"))
        i += 1
        if rounds and i >= rounds:
            break
        time.sleep(60)
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Sentinelle anti-embolie — pouls de l'organisme")
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="boucle périodique (déport)")
    ap.add_argument("--rounds", type=int, default=0, help="nb de tours (0=infini)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.watch:
        return watch(a.watch, a.rounds)
    p = pulse()
    _alert(p)
    print(json.dumps(p, ensure_ascii=False, indent=2))
    return 0


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    p = pulse()
    chk(p["verdict"] in (CLEAR, WARN, EMBOLIE), f"pouls -> verdict {p['verdict']}")
    chk(len(p["points"]) == len(CHECKS) == 12, f"12 rôles de check balayés ({len(p['points'])})")
    chk("critical_signals" in p["points"] and "hub_health" in p["points"],
        "checks clés présents (signaux non consommés + wedge hub)")
    chk(all(v["status"] in (CLEAR, WARN, EMBOLIE) for v in p["points"].values()),
        "chaque check a un statut valide")
    chk(watch(0, rounds=1) == 0, "watch(rounds=1) fait un tour sans lever")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_main())
