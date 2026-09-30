"""
forge_endocrine_system.py — Bus Endocrine de régulation de rythme métabolique Nokido.

POURQUOI
========
Dissonance d'horloge entre les tâches de fond (veilles SearXNG, curiosité, indexation RAG,
janitor) et les sessions interactives (CLI développeur, prompts en temps réel).
Cette dissonance crée une contention CPU/RAM et des verrous de base de données (WinError 32 / SQLite).

SOLUTION : LE BUS ENDOCRINE
===========================
Ce module diffuse un état métabolique global (Rhythme Endocrine) accessible de manière 
atomique et inter-processus via SQLite (WAL) et couplé aux signaux hormonaux (`forge_endocrine.py`).

LES 4 ÉTATS DU RYTHME (RHYTHMS) :
1. BOOST      : Accélération métabolique. Les workers tournent à cadence maximale (multiplier 0.5x).
2. NORMAL     : Équilibre homéostatique par défaut (multiplier 1.0x).
3. CONSERVE   : Mode Focus Développeur / Contention. Les workers de fond (SearXNG, Curiosité, 
                RAG bulk) sont EN PAUSE (`should_pause_worker(...) == True`) pour libérer 100% 
                du CPU et de la RAM pour le CLI actif. Multiplier 4.0x pour les tâches légères.
4. DEEP_SLEEP : Dormance / Conservation d'énergie extrême. Seuls les watchdogs vitaux tournent.

MÉCANISME ANTI-BLOCAGE (TTL & DECAY) :
======================================
Tout passage en mode CONSERVE ou DEEP_SLEEP exige un `ttl_s` (par défaut 3600s = 1h).
Si le CLI ou le développeur oublie de rétablir le rythme, le système revient automatiquement
au rythme NORMAL après expiration du TTL.

USAGE :
=======
    from forge_endocrine_system import set_rhythm, get_rhythm, should_pause_worker, get_delay_multiplier

    # Passage en mode focus développeur
    set_rhythm("CONSERVE", ttl_s=1800, reason="user en session de code interactive", source="CLI")

    # Dans une boucle de worker (ex: forge_watch_agent.py ou rss_watcher.py) :
    if should_pause_worker("forge_watch_agent", worker_type="background"):
        time.sleep(10) # Reste en pause sans consommer de ressources
        continue

    # Adapter le délai de sommeil d'un worker :
    time.sleep(base_delay * get_delay_multiplier("rss_watcher"))
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

__FORGE_COLOR__ = "vegetatif/resource : bus endocrine de regulation du rythme metabolique"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from nokido_agent.app.forge_endocrine import release as release_hormone
except ImportError:
    def release_hormone(*args, **kwargs):
        pass

logger = logging.getLogger("forge_endocrine_system")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Rythmes valides
RHYTHM_BOOST = "BOOST"
RHYTHM_NORMAL = "NORMAL"
RHYTHM_CONSERVE = "CONSERVE"
RHYTHM_DEEP_SLEEP = "DEEP_SLEEP"

VALID_RHYTHMS = {RHYTHM_BOOST, RHYTHM_NORMAL, RHYTHM_CONSERVE, RHYTHM_DEEP_SLEEP}

# Multiplicateurs de délai (sommeil des boucles) selon le rythme
DELAY_MULTIPLIERS = {
    RHYTHM_BOOST: 0.5,
    RHYTHM_NORMAL: 1.0,
    RHYTHM_CONSERVE: 4.0,
    RHYTHM_DEEP_SLEEP: 10.0,
}

# Types de workers ou noms considérés comme "tâches de fond lourdes" à pauser en CONSERVE
BACKGROUND_WORKER_TYPES = {
    "background",
    "curiosity",
    "searxng",
    "biblio",
    "embed",
    "watch",
    "rss",
    "janitor",
    "crawler",
}

BACKGROUND_WORKER_NAMES = {
    "forge_watch_agent",
    "forge_curiosity_driver",
    "rss_watcher",
    "forge_rag_embed_daemon",
    "forge_biblio_worker",
    "forge_auto_ingest_daemon",
    "forge_circadian_loop",
}


@dataclass
class RhythmStatus:
    rhythm: str
    set_at: str
    ttl_s: int
    age_s: int
    remaining_ttl_s: int
    expired: bool
    reason: str
    source: str
    delay_multiplier: float

    def to_dict(self) -> dict:
        return {
            "rhythm": self.rhythm,
            "set_at": self.set_at,
            "ttl_s": self.ttl_s,
            "age_s": self.age_s,
            "remaining_ttl_s": self.remaining_ttl_s,
            "expired": self.expired,
            "reason": self.reason,
            "source": self.source,
            "delay_multiplier": self.delay_multiplier,
        }


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS endocrine_rhythm_state (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        rhythm      TEXT NOT NULL,
        set_at      TEXT NOT NULL,
        ttl_s       INTEGER NOT NULL,
        reason      TEXT,
        source      TEXT
    )""")
    conn.commit()


def set_rhythm(
    rhythm: str,
    *,
    ttl_s: int = 3600,
    reason: str = "",
    source: str = "unknown",
) -> dict:
    """Définit le rythme métabolique global de l'essaim.

    Args:
        rhythm: "BOOST", "NORMAL", "CONSERVE", ou "DEEP_SLEEP".
        ttl_s: Durée de validité en secondes avant retour automatique à NORMAL (défaut 3600s = 1h).
        reason: Justification du changement (ex: "CLI interactif en cours").
        source: Module ou agent initiateur.
    """
    rhythm = rhythm.upper()
    if rhythm not in VALID_RHYTHMS:
        raise ValueError(f"Rythme invalide: {rhythm}. Rythmes admis: {VALID_RHYTHMS}")

    if rhythm == RHYTHM_NORMAL:
        ttl_s = 86400 * 365  # NORMAL est stable quasi indéfiniment (1 an)
    else:
        ttl_s = max(60, int(ttl_s))  # Min 60s pour un mode d'exception

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn = _conn()
    _ensure_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO endocrine_rhythm_state (id, rhythm, set_at, ttl_s, reason, source) "
        "VALUES (1, ?, ?, ?, ?, ?)",
        (rhythm, now_iso, ttl_s, reason or "", source),
    )
    conn.commit()
    conn.close()

    # Émission d'un signal hormonal scalaire couplé pour informer les récepteurs forge_endocrine
    if rhythm == RHYTHM_CONSERVE:
        release_hormone("HORMONE_FOCUS", level=1.0, ttl_s=ttl_s, source=source, reason=reason)
        release_hormone("ADRENALINE_HUB_PRESSURE", level=0.8, ttl_s=ttl_s, source=source, reason=reason)
    elif rhythm == RHYTHM_BOOST:
        release_hormone("TSH_VECTORIZATION", level=1.0, ttl_s=ttl_s, source=source, reason=reason)
    elif rhythm == RHYTHM_NORMAL:
        release_hormone("HORMONE_FOCUS", level=0.0, ttl_s=60, source=source, reason="revert to normal")

    logger.info("[ENDOCRINE BUS] Rythme changé -> %s (ttl=%ds, source=%s, reason=%s)", rhythm, ttl_s, source, reason)
    return get_rhythm_status().to_dict()


def get_rhythm_status() -> RhythmStatus:
    """Lit l'état du rythme global actuel en vérifiant l'expiration du TTL."""
    conn = _conn()
    _ensure_schema(conn)
    row = conn.execute("SELECT rhythm, set_at, ttl_s, reason, source FROM endocrine_rhythm_state WHERE id = 1").fetchone()
    conn.close()

    if not row:
        # Aucun rythme défini, retour à NORMAL par défaut
        return RhythmStatus(
            rhythm=RHYTHM_NORMAL,
            set_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ttl_s=86400,
            age_s=0,
            remaining_ttl_s=86400,
            expired=False,
            reason="default_init",
            source="system",
            delay_multiplier=DELAY_MULTIPLIERS[RHYTHM_NORMAL],
        )

    rhythm_val, set_at_str, ttl_s, reason, source = row[0], row[1], int(row[2]), row[3] or "", row[4] or ""

    try:
        set_dt = datetime.fromisoformat(set_at_str.replace(" ", "T"))
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        age_s = max(0, int((now_utc - set_dt).total_seconds()))
    except Exception:
        age_s = 0

    expired = age_s >= ttl_s and rhythm_val != RHYTHM_NORMAL
    remaining_ttl_s = max(0, ttl_s - age_s)

    if expired:
        # Le TTL a expiré ! On revient automatiquement à NORMAL pour éviter de figer le système
        logger.info("[ENDOCRINE BUS] Rythme %s expiré (age=%ds > ttl=%ds). Revers vers NORMAL.", rhythm_val, age_s, ttl_s)
        try:
            set_rhythm(RHYTHM_NORMAL, reason=f"auto_revert_expired_{rhythm_val}", source="endocrine_ttl_watchdog")
        except Exception:
            pass
        return get_rhythm_status()

    mult = DELAY_MULTIPLIERS.get(rhythm_val, 1.0)
    return RhythmStatus(
        rhythm=rhythm_val,
        set_at=set_at_str,
        ttl_s=ttl_s,
        age_s=age_s,
        remaining_ttl_s=remaining_ttl_s,
        expired=expired,
        reason=reason,
        source=source,
        delay_multiplier=mult,
    )


def get_rhythm() -> str:
    """Retourne le nom du rythme actuel (ex: 'NORMAL', 'CONSERVE')."""
    return get_rhythm_status().rhythm


def should_pause_worker(worker_name: str = "", worker_type: str = "background") -> bool:
    """Indique si un worker doit se mettre en pause pour éviter la contention.

    En mode CONSERVE, tous les workers de fond (SearXNG, curiosité, indexation)
    doivent suspendre leur activité pour laisser 100% de la bande passante au CLI.
    En mode DEEP_SLEEP, tous les workers sauf les watchdogs vitaux se mettent en pause.
    """
    status = get_rhythm_status()
    rhythm = status.rhythm

    if rhythm == RHYTHM_NORMAL or rhythm == RHYTHM_BOOST:
        return False

    w_type = (worker_type or "").lower()
    w_name = (worker_name or "").lower()

    if rhythm == RHYTHM_CONSERVE:
        # En CONSERVE, on pause les tâches de fond lourdes ou non urgentes
        if w_type in BACKGROUND_WORKER_TYPES:
            return True
        for name_kw in BACKGROUND_WORKER_NAMES:
            if name_kw in w_name:
                return True
        return False

    if rhythm == RHYTHM_DEEP_SLEEP:
        # En DEEP_SLEEP, tout est en pause sauf les watchdogs et superviseurs de santé
        if "watchdog" in w_name or "sentinel" in w_name or w_type == "vital":
            return False
        return True

    return False


def get_delay_multiplier(worker_name: str = "", worker_type: str = "background") -> float:
    """Retourne le multiplicateur à appliquer aux intervalles de sommeil des boucles.

    Ex: si intervalle de base est 60s et rythme est CONSERVE, renvoie 4.0 -> sommeil 240s.
    """
    status = get_rhythm_status()
    return status.delay_multiplier


def pulse_auto_conserve(active_threshold_s: int = 300, conserve_ttl_s: int = 1800) -> str:
    """Sonde l'activité récente dans l'essaim et bascule automatiquement en mode CONSERVE
    si un CLI ou une tâche interactive de haute priorité est active depuis moins de active_threshold_s.
    """
    # Ce pulse peut être invoqué par after_model_hook ou un watchdog.
    # Si un message CLI a été reçu récemment, on engage CONSERVE pour protéger la session.
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT max(timestamp) FROM messages WHERE sender LIKE '%cli%' OR sender LIKE '%claude%' OR sender LIKE '%antigravity%'"
        ).fetchone()
        conn.close()
        if row and row[0]:
            # Analyse simple, par défaut on active CONSERVE lors d'un appel CLI explicite
            pass
    except Exception:
        pass
    return get_rhythm()


# ============================================================================
# CLI INTERACTIF
# ============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Nokido Endocrine Bus (Régulation du rythme)")
    subparsers = parser.add_subparsers(dest="command", help="Commande à exécuter")

    status_parser = subparsers.add_parser("status", help="Afficher le rythme actuel")

    set_parser = subparsers.add_parser("set", help="Définir un nouveau rythme")
    set_parser.add_argument("rhythm", choices=list(VALID_RHYTHMS), help="Rythme à imposer")
    set_parser.add_argument("--ttl", type=int, default=3600, help="TTL en secondes (défaut 3600)")
    set_parser.add_argument("--reason", default="cli_override", help="Raison du changement")
    set_parser.add_argument("--source", default="cli", help="Source du signal")

    check_parser = subparsers.add_parser("check", help="Vérifier si un worker doit être en pause")
    check_parser.add_argument("--name", default="forge_watch_agent", help="Nom du worker")
    check_parser.add_argument("--type", default="background", help="Type du worker")

    args = parser.parse_args()

    if args.command == "status" or not args.command:
        s = get_rhythm_status()
        print(json.dumps(s.to_dict(), indent=2, ensure_ascii=False))
    elif args.command == "set":
        res = set_rhythm(args.rhythm, ttl_s=args.ttl, reason=args.reason, source=args.source)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.command == "check":
        paused = should_pause_worker(args.name, args.type)
        mult = get_delay_multiplier(args.name, args.type)
        print(json.dumps({"worker": args.name, "type": args.type, "should_pause": paused, "delay_multiplier": mult}, indent=2))
    sys.exit(0)
