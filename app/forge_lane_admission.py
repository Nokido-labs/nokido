#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_lane_admission.py — Admission control souverain avec prévention d'embolie.

Évolution v2 : Conscience Biométrique.
Ce module régule l'accès aux ressources LOURDES (GPU, CPU, RAM).
Avant d'admettre un job, il vérifie les 'signes vitaux' du système via forge_inspector.
Si le système est en pré-embolie (RAM > 85%, CPU saturé), il refuse l'admission locale
et force un repli vers le Cloud pour protéger l'intégrité du Hub.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "vegetatif/resource : admission control souverain, prevention d'embolie (lanes)"  # organe declare le 2026-09-06 (audit de raccordement)

import sqlite3
import os
import time
import logging
from pathlib import Path

# Configuration des chemins
def _envf(key: str, default: str) -> float:
    """Parse défensif d'un float d'env (audit 2026-06-15 : env malformé -> ValueError
    à l'import = module inimportable)."""
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return float(default)


_DB_PATH = Path(os.environ.get("LAFORGE_LANES_DB", "C:/tmp/laforge_lanes.db"))
DEFAULT_TTL = _envf("LAFORGE_LANE_TTL", "7200")
ALT_LOCAL = os.environ.get("LAFORGE_LANE_ALT_LOCAL", "ollama:qwen2.5-coder:1.5b")
ALT_CLOUD = os.environ.get("LAFORGE_LANE_ALT_CLOUD", "openrouter:free")

# Seuils de sécurité pour éviter l'embolie
MAX_RAM_PCT = 85.0
MAX_CPU_PCT = 90.0
# GB de RAM libre vises quand l'admission tente de faire de la place avant de
# refuser un job lourd (meme cible que l'auto-eviction du sampler).
RESERVE_GB = _envf("LAFORGE_LANE_RESERVE_GB", "4")

# Duree de mesure du CPU. Constante NOMMEE, et >= 0.5 s : un echantillon de
# 100 ms est domine par le bruit d'ordonnancement, or c'est sur lui qu'on refuse
# une admission. Mesure du 2026-09-08 : un refus « CPU 100 % » est tombe pile au
# demarrage d'une CI collectant 8815 tests, pendant que la machine tenait 21-26 %
# avec UN SEUL coeur sur 16 charge. L'owner l'a vue a 13 %. Les deux etaient
# vraies : l'une est un pic, l'autre le regime. On decide sur le regime.
FENETRE_CPU_S = float(_envf("LAFORGE_LANE_FENETRE_CPU_S", "0.6"))


def _journaliser_refus(motif: str, sante: dict, lane: str = "") -> None:
    """Trace d'un refus d'admission — un garde sans trace n'est pas auditable.

    Mesure du 2026-09-08 : ZERO occurrence de « EMBOLIE CPU » dans 8736 journaux
    alors qu'un refus venait d'etre emis. L'incident a donc ete IRRECUPERABLE :
    impossible de dire apres coup si la mesure etait vraie, degradee ou sentinelle.

    Ce journal NE LEVE JAMAIS. Un garde agit d'abord et journalise ensuite ; le
    2026-09-08 un autre garde est mort sur l'ouverture de son propre journal,
    laissant un job « running » a vie.
    """
    try:
        import datetime as _dt

        ligne = "%s\tREFUS\tlane=%s\tsource=%s\tcpu=%s\tram=%s\tdegraded=%s\t%s\n" % (
            _dt.datetime.now().isoformat(timespec="seconds"),
            lane or "-",
            sante.get("source", "?"),
            sante.get("cpu_pct"),
            sante.get("ram_pct"),
            bool(sante.get("degraded")),
            motif,
        )
        # `ROOT` n'existe pas ici : la racine est `_RACINE_AMORCE` (L18), une CHAINE.
        # Mesure 2026-09-19 : ce `NameError` etait avale par le `except` muet-ok
        # juste en dessous -- donc `lane_admission.log` n'a JAMAIS ete ecrit, en
        # silence. Un journal qui ne s'ecrit pas ne se distingue pas d'un organe
        # qui n'a rien a dire.
        journal = _Path_amorce(_RACINE_AMORCE) / "logs" / "lane_admission.log"
        journal.parent.mkdir(parents=True, exist_ok=True)
        with open(journal, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(ligne)
    except Exception:  # muet-ok : journaliser ne doit jamais casser une decision
        pass


def _get_system_health() -> dict:
    """Signes vitaux via forge_inspector ou psutil. FAIL-CLOSED (audit 2026-06-15) :
    si la mesure échoue, on retourne des sentinelles saturées (degraded) -> l'admission
    lourde se replie sur le cloud au lieu d'ouvrir grand. Normalise aussi les clés
    (l'inspecteur peut exposer cpu/cpu_percent/ram_percent...)."""
    # forge_inspector : except LARGE (pas seulement ImportError) — une erreur runtime
    # de l'inspecteur ne doit pas faire crasher acquire/admit, ni passer en silence.
    try:
        from app.forge_inspector import _sys_metrics
        m = _sys_metrics() or {}
        cpu = m.get("cpu_pct", m.get("cpu", m.get("cpu_percent")))
        ram = m.get("ram_pct", m.get("ram", m.get("ram_percent", m.get("mem_pct"))))
        if cpu is not None and ram is not None:
            try:
                import psutil as _ps
                _dispo = _ps.virtual_memory().available / 1e9
            except Exception:  # noqa: BLE001
                _dispo = None
            return {"cpu_pct": float(cpu), "ram_pct": float(ram),
                    "ram_dispo_gb": _dispo, "source": "inspecteur"}
    except Exception:  # noqa: BLE001 - inspecteur indispo/clé absente -> psutil direct
        pass
    try:
        import psutil
        # interval=0.1 : sans intervalle, le 1er cpu_percent d'un process retourne
        # TOUJOURS 0.0 -> le check d'embolie CPU ne se déclenchait jamais.
        _vm = psutil.virtual_memory()
        return {"cpu_pct": psutil.cpu_percent(interval=FENETRE_CPU_S),
                "ram_pct": _vm.percent, "ram_dispo_gb": _vm.available / 1e9,
                "source": "psutil"}
    except Exception:  # noqa: BLE001 - mesure impossible -> FAIL-CLOSED (saturé)
        # Sentinelle, PAS une mesure. `source` la rend discernable : sans elle,
        # 100.0 se lit comme une charge reelle et envoie chercher une saturation
        # qui n'existe pas -- UNKNOWN presente comme NO.
        return {"cpu_pct": 100.0, "ram_pct": 100.0, "ram_dispo_gb": 0.0,
                "degraded": True, "source": "indisponible"}


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout=5.0 pour réduire SQLITE_BUSY sous contention (Audit 2026-06-15)
    c = sqlite3.connect(str(_DB_PATH), timeout=5.0, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.execute("PRAGMA busy_timeout=5000;")
    c.execute('''
        CREATE TABLE IF NOT EXISTS lane_leases (
            lane TEXT PRIMARY KEY,
            holder TEXT NOT NULL,
            acquired REAL NOT NULL,
            expiry REAL NOT NULL
        )
    ''')
    return c

def _holder_termine(holder: str) -> bool:
    """Le detenteur du bail est-il un job DEJA fini ?

    Mesure 2026-08-16 : un job stoppe par la MORT DU HUB (rc=3) a garde sa lane
    plus d'une heure — `run_job` refusait toute relance (« lane occupee,
    busy_by=job_... ») au profit d'un process inexistant, et il a fallu un
    `job_kill force=true` a la main. Le TTL du bail est taille pour un job
    VIVANT ; il ne couvre pas le cas ou l'hote meurt au milieu, justement celui
    ou la reprise presse le plus.

    Fail-SAFE : tout doute rend False (bail conserve). Liberer a tort ferait
    tourner deux jobs lourds ensemble — precisement ce que la lane empeche.
    """
    if not holder or not str(holder).startswith("job_"):
        return False
    try:
        import sys as _s

        _app = str(Path(__file__).resolve().parent)
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_job_runner import read_job

        r = read_job(str(holder), tail=0)
    except Exception:  # noqa: BLE001 - fail-safe : on ne libere pas sur un doute
        return False
    return bool(r.get("ok")) and r.get("status") in ("done", "killed")


def current(lane: str) -> dict | None:
    try:
        c = _conn()
    except sqlite3.Error:
        return None  # DB indispo -> on ne sait pas, ne pas prétendre 'libre'
    try:
        row = c.execute("SELECT holder, acquired, expiry FROM lane_leases WHERE lane=?", (lane,)).fetchone()
        if not row: return None
        if row[2] <= time.time():
            c.execute("DELETE FROM lane_leases WHERE lane=?", (lane,))
            return None
        # Reconciliation avec le reel : un bail jeune est cru sur parole (le job
        # vient de demarrer), un bail age est confronte a l'etat du job.
        if (time.time() - float(row[1] or 0)) > 60 and _holder_termine(row[0]):
            c.execute("DELETE FROM lane_leases WHERE lane=?", (lane,))
            logging.getLogger("Nokido.LaneAdmission").info(
                "lane %s liberee : detenteur %s deja termine", lane, row[0])
            return None
        return {"holder": row[0], "lane": lane, "acquired": row[1], "expiry": row[2]}
    except sqlite3.OperationalError:
        return None  # SQLITE_BUSY sous contention
    finally:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass

def acquire(lane: str, holder: str, ttl: float = DEFAULT_TTL) -> bool:
    """Tente d'acquérir la lane avec vérification anti-embolie."""
    ttl = max(1.0, float(ttl))  # ttl<=0 -> lease morte instantanée (acquisition fantôme)
    # 1. Vérification des signes vitaux (fail-closed via _get_system_health)
    health = _get_system_health()
    if health.get("ram_pct", 0) > MAX_RAM_PCT:
        return False  # Embolie RAM (ou mesure dégradée) : admission refusée

    try:
        c = _conn()
    except sqlite3.Error:
        return False  # DB indispo/lock -> fail-closed (pas d'admission locale)
    try:
        now = time.time()
        c.execute("DELETE FROM lane_leases WHERE lane=? AND expiry <= ?", (lane, now))
        try:
            c.execute("INSERT INTO lane_leases (lane, holder, acquired, expiry) VALUES (?, ?, ?, ?)",
                      (lane, holder, now, now + ttl))
            return True
        except sqlite3.IntegrityError:
            row = c.execute("SELECT holder FROM lane_leases WHERE lane=?", (lane,)).fetchone()
            if row and row[0] == holder:
                c.execute("UPDATE lane_leases SET expiry=? WHERE lane=?", (now + ttl, lane))
                return True
            return False
    except sqlite3.OperationalError:
        return False  # SQLITE_BUSY sous contention -> refus propre (audit 2026-06-15)
    finally:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass

def release(lane: str, holder: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM lane_leases WHERE lane=? AND holder=?", (lane, holder))
    finally:
        c.close()

def _try_reserve(needed_gb: float = RESERVE_GB) -> dict:
    """Demande au corps de FAIRE DE LA PLACE. Jamais de kill.

    Delegue a forge_resource_manager.request_resources, dont l'echelle
    d'eviction ne touche que des charges rechargeables : modeles Ollama (LRU),
    llama-server :8091, pause Docker hors organes de perception (searxng /
    crawl4ai). Un process tiers n'est JAMAIS tue — s'il tient la RAM,
    l'admission refuse et renvoie vers le cloud, ce qui est le comportement
    voulu (cf. doctrine : interrompre un travail en cours = destructif).

    Ne leve jamais. Retourne le plan d'eviction (diagnostic) ou {} si indispo.
    """
    try:
        from nokido_agent.app.forge_resource_manager import request_resources
    except ImportError:
        try:
            from app.forge_resource_manager import request_resources  # type: ignore
        except ImportError:
            return {}
    try:
        return request_resources(needed_ram_gb=needed_gb, allow_evict=True) or {}
    except Exception:  # noqa: BLE001 - la reservation ne doit jamais casser l'admission
        return {}


def check_ressources(heavy: bool = True) -> dict:
    """Verdict d'embolie SEUL, sans toucher aux baux de lane. {ok, reason, ...}

    Extrait d'`admit` (qui l'appelle toujours) parce qu'un appelant peut avoir
    besoin du controle SANS acquerir de lane : mesure 2026-08-02, le chemin
    `run_job` sans lane ne controlait RIEN, et un job relance sur une machine
    a 96 % de RAM a fini en famine memoire et gel du bureau. Acquerir une lane
    a sa place aurait serialise tous les jobs — le besoin est le verdict, pas
    l'exclusion mutuelle. FAIL-CLOSED via `_get_system_health`.
    """
    if not heavy:
        return {"ok": True, "reason": "leger"}
    health = _get_system_health()
    def _sature(h):
        # Refuse aussi sur la RESERVE ABSOLUE en Go, pas seulement le % : le %
        # instantane laissait empiler deux jobs admis a 81% qui montaient ENSEMBLE
        # a 95% (dispo 1.25 Go), rendant le HUB injoignable par thrash (incident
        # 2026-08-28). La reserve absolue protege la RAM du hub contre l'empilement.
        return (h.get("ram_pct", 0) > MAX_RAM_PCT
                or (h.get("ram_dispo_gb") is not None and h["ram_dispo_gb"] < RESERVE_GB))
    if health.get("degraded"):
        # La mesure a ECHOUE. On reste fail-closed -- mais on le DIT, au lieu
        # d'accuser un CPU ou une RAM qu'on n'a pas pu observer.
        motif = ("MESURE INDISPONIBLE (signes vitaux illisibles) - refus par "
                 "precaution, pas sur une charge observee")
        _journaliser_refus(motif, health)
        return {"ok": False, "reason": motif, "alt": ALT_CLOUD,
                "source": health.get("source")}
    if _sature(health):
        # RESERVER AVANT DE REFUSER : tenter de liberer (charges rechargeables :
        # Ollama, llama-server, conteneurs non-perceptifs), re-mesurer, refuser
        # seulement si la place manque VRAIMENT.
        plan = _try_reserve()
        health = _get_system_health()
        if _sature(health):
            motif = (f"RISQUE EMBOLIE RAM ({health.get('ram_pct')}% > {MAX_RAM_PCT}% "
                     f"ou dispo {health.get('ram_dispo_gb', 0):.1f} Go < reserve {RESERVE_GB} Go)")
            _journaliser_refus(motif, health)
            return {
                "ok": False,
                "reason": motif,
                "alt": ALT_CLOUD,
                "reserve": plan.get("action") or "rien a liberer",
                "freed_gb": plan.get("freed_gb", 0.0),
                "source": health.get("source"),
            }
    if health.get("cpu_pct", 0) > MAX_CPU_PCT:
        motif = (f"RISQUE EMBOLIE CPU ({health['cpu_pct']}% > {MAX_CPU_PCT}%, "
                 f"mesure sur {FENETRE_CPU_S} s via {health.get('source', '?')})")
        _journaliser_refus(motif, health)
        return {"ok": False, "reason": motif, "alt": ALT_CLOUD,
                "source": health.get("source")}
    return {"ok": True, "ram_pct": health.get("ram_pct"), "cpu_pct": health.get("cpu_pct")}


def admit(lane: str, holder: str, *, heavy: bool = True, ttl: float = DEFAULT_TTL) -> dict:
    """Décision d'admission avec diagnostic médical."""
    verdict = check_ressources(heavy)
    if not verdict.get("ok"):
        return {"admit": False, **{k: v for k, v in verdict.items() if k != "ok"}}

    if not heavy:
        return {"admit": True, "lane": lane, "reason": "léger admis"}
        
    if acquire(lane, holder, ttl):
        return {"admit": True, "lane": lane, "reason": "lane acquise"}
    
    busy = current(lane)
    return {"admit": False, "busy_by": (busy or {}).get("holder"), "alt": ALT_CLOUD, "reason": "lane occupée"}

if __name__ == "__main__":
    h = _get_system_health()
    print(f"Signes vitaux : CPU {h.get('cpu_pct')}% | RAM {h.get('ram_pct')}%")
    print(f"Admission test (heavy) : {admit('selftest', 'gemini')}")
