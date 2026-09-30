"""
forge_trauma_vault.py — Nokido Engrid v3 · Sprint 3
======================================================
TraumaVault : mémoire des échecs avec plasticité STDP et
protection topologique par winding_count (skyrmion-inspired).

Deux mécanismes bio-inspirés :

[1] STDP — Spike-Timing-Dependent Plasticity
    Inspiré de mumax3_neurospin (STDP_tau_plus=20ms, triplet STDP).
    Le poids d'un pattern dépend du DELTA DE TEMPS entre:
        t_mutation  = moment où le pattern est appliqué (spike pré)
        t_outcome   = moment où le résultat est observé (spike post)

    delta_t = t_outcome - t_mutation

    LTP (Long-Term Potentiation) — renforcement :
        delta_t > 0 ET delta_t < t_ltp_window → +w_plus * exp(-delta_t/tau_plus)
    LTD (Long-Term Depression) — affaiblissement :
        delta_t < 0 OU delta_t > t_ltd_window → -w_minus * exp(+delta_t/tau_minus)

    Dans Nokido :
        Succès rapide  (Δt < 60s)   → +0.15  (apprentissage fort)
        Succès tardif  (Δt > 3600s) → +0.02  (apprentissage faible)
        Échec rapide   (Δt < 60s)   → -0.08  (punition forte)
        Échec tardif                → -0.02  (punition faible)

[2] Skyrmion Topological Protection (winding_count)
    Inspiré de mumax3_neurospin (skyrmion_energy_barriers).
    Un skyrmion a un invariant topologique — il faut franchir une
    barrière d'énergie minimale pour l'annihiler.

    winding_count = nombre de confirmations du trauma :
        winding < 3  → trauma FRAGILE   (1 succès suffit à l'effacer)
        winding >= 3 → trauma PROTÉGÉ   (3 succès consécutifs requis)

Usage :
    vault = TraumaVault()
    tid = vault.record_mutation("pattern_hash", "desc", ts_spike=time.time())
    vault.record_outcome(tid, success=False, ts_outcome=time.time()+30)
    vault.is_pattern_blocked("pattern_hash")  # True si poids < -0.5
"""

from __future__ import annotations

import hashlib

# DEAD_IMPORT removed: import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES STDP
# ══════════════════════════════════════════════════════════════════════════════

# LTP (renforcement si succès)
STDP_W_PLUS = 0.15  # poids max de renforcement
STDP_TAU_PLUS_SEC = 300.0  # constante de temps LTP (5 min)
STDP_LTP_WINDOW = 3600.0  # fenêtre de renforcement (1h)

# LTD (dépression si échec)
STDP_W_MINUS = 0.08  # poids max de punition
STDP_TAU_MINUS_SEC = 600.0  # constante de temps LTD (10 min)

# Seuil de blocage
BLOCK_THRESHOLD = -0.50  # poids < -0.50 → pattern bloqué

# Winding count (skyrmion topological protection)
WINDING_PROTECTION_THRESHOLD = 3  # >= 3 → trauma protégé
SUCCESSES_TO_UNWIND = 3  # succès consécutifs requis pour effacer


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class TraumaRecord:
    """Enregistrement d'un pattern traumatique."""

    id: str
    pattern_hash: str
    description: str
    weight: float = 0.0
    winding_count: int = 0  # nb de confirmations du trauma
    consecutive_ok: int = 0  # succès consécutifs (pour unwinding)
    ts_first: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ts_last_update: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    blocked: bool = False

    @property
    def topological_state(self) -> str:
        """FRAGILE si winding < seuil, PROTÉGÉ sinon."""
        if self.winding_count >= WINDING_PROTECTION_THRESHOLD:
            return "TOPOLOGICAL_PROTECTED"
        return "FRAGILE"


@dataclass
class STDPEvent:
    """Événement STDP : spike pré + spike post."""

    trauma_id: str
    ts_spike: float  # t_mutation (spike pré-synaptique)
    ts_outcome: float  # t_outcome  (spike post-synaptique)
    success: bool
    delta_t: float  # ts_outcome - ts_spike
    dw: float  # variation de poids appliquée
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# TRAUMA VAULT
# ══════════════════════════════════════════════════════════════════════════════


class TraumaVault:
    """
    Mémoire persistante des patterns pathologiques avec STDP et
    protection topologique skyrmionique.
    """

    def __init__(
        self,
        db_path: str = "",
        block_threshold: float = BLOCK_THRESHOLD,
        winding_thresh: int = WINDING_PROTECTION_THRESHOLD,
        successes_unwind: int = SUCCESSES_TO_UNWIND,
    ):
        self.block_threshold = block_threshold
        self.winding_thresh = winding_thresh
        self.successes_unwind = successes_unwind
        self._lock = threading.Lock()
        self._pending: dict[str, float] = {}  # trauma_id → ts_spike en attente

        root = Path(__file__).resolve().parent.parent
        self._db = db_path or str(root / "recon_silo" / "recon_data" / "trauma_vault.db")
        self._mem_conn = None  # connexion persistante pour :memory:
        if self._db != ":memory:":
            Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── DB ────────────────────────────────────────────────────────────────────

    def _connect(self):
        """Retourne une connexion — persistante pour :memory:, normale sinon."""
        if self._db == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            return self._mem_conn
        return sqlite3.connect(self._db)

    def _init_db(self) -> None:
        conn = self._connect()
        with conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traumas (
                    id              TEXT PRIMARY KEY,
                    pattern_hash    TEXT NOT NULL,
                    description     TEXT,
                    weight          REAL DEFAULT 0.0,
                    winding_count   INTEGER DEFAULT 0,
                    consecutive_ok  INTEGER DEFAULT 0,
                    ts_first        TEXT,
                    ts_last_update  TEXT,
                    blocked         INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stdp_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    trauma_id   TEXT,
                    ts_spike    REAL,
                    ts_outcome  REAL,
                    success     INTEGER,
                    delta_t     REAL,
                    dw          REAL,
                    ts          TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pattern ON traumas(pattern_hash)")
            conn.commit()

    # ── STDP ──────────────────────────────────────────────────────────────────

    def _stdp_dw(self, delta_t: float, success: bool) -> float:
        """
        Calcule la variation de poids STDP.

        LTP (succès) : dw = +W_PLUS * exp(-delta_t / TAU_PLUS)
            seulement si 0 < delta_t < LTP_WINDOW

        LTD (échec) : dw = -W_MINUS * exp(-|delta_t| / TAU_MINUS)
            toujours applicable
        """
        if success:
            if 0 < delta_t < STDP_LTP_WINDOW:
                return STDP_W_PLUS * math.exp(-delta_t / STDP_TAU_PLUS_SEC)
            else:
                # Succès hors fenêtre : renforcement minimal
                return STDP_W_PLUS * 0.1
        else:
            # LTD : punition plus forte si feedback rapide
            return -STDP_W_MINUS * math.exp(-abs(delta_t) / STDP_TAU_MINUS_SEC)

    # ── API publique ──────────────────────────────────────────────────────────

    def record_mutation(
        self,
        pattern_hash: str,
        description: str,
        ts_spike: float | None = None,
    ) -> str:
        """
        Enregistre l'application d'un pattern (spike pré-synaptique).
        Retourne l'ID du trauma pour l'appel ultérieur à record_outcome().
        """
        ts = ts_spike or time.time()
        tid = hashlib.sha256(f"{pattern_hash}:{ts:.3f}".encode()).hexdigest()[:16]

        with self._lock:
            self._pending[tid] = ts

        # Crée le record s'il n'existe pas
        conn = self._connect()
        with conn:
            existing = conn.execute("SELECT id FROM traumas WHERE pattern_hash=?", (pattern_hash,)).fetchone()
            if not existing:
                now = datetime.utcnow().isoformat()
                conn.execute(
                    "INSERT OR IGNORE INTO traumas "
                    "(id, pattern_hash, description, weight, ts_first, ts_last_update) "
                    "VALUES (?,?,?,?,?,?)",
                    (tid, pattern_hash, description, 0.0, now, now),
                )
                conn.commit()
            else:
                # Utilise l'ID existant
                tid = existing[0]
                with self._lock:
                    self._pending[tid] = ts

        return tid

    def record_outcome(
        self,
        trauma_id: str,
        success: bool,
        ts_outcome: float | None = None,
    ) -> STDPEvent | None:
        """
        Enregistre le résultat d'une mutation (spike post-synaptique).
        Calcule dw via STDP et met à jour le poids du trauma.
        """
        ts_out = ts_outcome or time.time()

        with self._lock:
            ts_spike = self._pending.pop(trauma_id, None)

        if ts_spike is None:
            return None  # pas de spike pré enregistré

        delta_t = ts_out - ts_spike
        dw = self._stdp_dw(delta_t, success)

        conn = self._connect()
        with conn:
            row = conn.execute(
                "SELECT weight, winding_count, consecutive_ok FROM traumas WHERE id=?", (trauma_id,)
            ).fetchone()

            if row is None:
                return None

            old_weight, winding, consec_ok = row
            new_weight = max(-1.0, min(0.5, old_weight + dw))

            # ── Winding count (topological protection) ────────────────────────
            if not success:
                # Chaque échec confirme le trauma → incrémente winding
                winding += 1
                consec_ok = 0  # reset succès consécutifs
            else:
                # Succès : vérifie si on peut "dérouler" le skyrmion
                consec_ok += 1
                if winding >= self.winding_thresh:
                    # Trauma protégé : nécessite N succès consécutifs
                    if consec_ok >= self.successes_unwind:
                        winding = max(0, winding - 1)
                        consec_ok = 0
                else:
                    # Trauma fragile : 1 succès suffit
                    winding = max(0, winding - 1)

            # ── Seuil de blocage ──────────────────────────────────────────────
            blocked = new_weight < self.block_threshold

            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE traumas SET weight=?, winding_count=?, consecutive_ok=?, "
                "blocked=?, ts_last_update=? WHERE id=?",
                (new_weight, winding, consec_ok, int(blocked), now, trauma_id),
            )
            conn.execute(
                "INSERT INTO stdp_events (trauma_id,ts_spike,ts_outcome,success,delta_t,dw,ts) VALUES (?,?,?,?,?,?,?)",
                (trauma_id, ts_spike, ts_out, int(success), delta_t, dw, now),
            )
            conn.commit()

        return STDPEvent(
            trauma_id=trauma_id,
            ts_spike=ts_spike,
            ts_outcome=ts_out,
            success=success,
            delta_t=delta_t,
            dw=dw,
        )

    # ── Requêtes ──────────────────────────────────────────────────────────────

    def is_pattern_blocked(self, pattern_hash: str) -> bool:
        """True si le pattern a un poids < block_threshold."""
        conn = self._connect()
        with conn:
            row = conn.execute("SELECT blocked FROM traumas WHERE pattern_hash=?", (pattern_hash,)).fetchone()
        return bool(row and row[0])

    def get_trauma(self, trauma_id: str) -> TraumaRecord | None:
        conn = self._connect()
        with conn:
            row = conn.execute(
                "SELECT id,pattern_hash,description,weight,winding_count,"
                "consecutive_ok,ts_first,ts_last_update,blocked "
                "FROM traumas WHERE id=?",
                (trauma_id,),
            ).fetchone()
        if not row:
            return None
        return TraumaRecord(
            id=row[0],
            pattern_hash=row[1],
            description=row[2],
            weight=row[3],
            winding_count=row[4],
            consecutive_ok=row[5],
            ts_first=row[6],
            ts_last_update=row[7],
            blocked=bool(row[8]),
        )

    def list_blocked(self) -> list[TraumaRecord]:
        """Liste tous les patterns bloqués."""
        conn = self._connect()
        with conn:
            rows = conn.execute(
                "SELECT id,pattern_hash,description,weight,winding_count,"
                "consecutive_ok,ts_first,ts_last_update,blocked "
                "FROM traumas WHERE blocked=1 ORDER BY weight ASC"
            ).fetchall()
        return [
            TraumaRecord(
                id=r[0],
                pattern_hash=r[1],
                description=r[2],
                weight=r[3],
                winding_count=r[4],
                consecutive_ok=r[5],
                ts_first=r[6],
                ts_last_update=r[7],
                blocked=bool(r[8]),
            )
            for r in rows
        ]

    def stats(self) -> dict:
        conn = self._connect()
        with conn:
            total = conn.execute("SELECT COUNT(*) FROM traumas").fetchone()[0]
            blocked = conn.execute("SELECT COUNT(*) FROM traumas WHERE blocked=1").fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM stdp_events").fetchone()[0]
            avg_w = conn.execute("SELECT AVG(weight) FROM traumas").fetchone()[0] or 0.0
            prot = conn.execute(
                f"SELECT COUNT(*) FROM traumas WHERE winding_count>={WINDING_PROTECTION_THRESHOLD}"
            ).fetchone()[0]
        return {
            "total_patterns": total,
            "blocked": blocked,
            "topological_prot": prot,
            "stdp_events": events,
            "avg_weight": round(avg_w, 4),
        }
