"""
forge_inhibition_bus.py — Nokido Engrid v3 · Sprint 2
========================================================
InhibitionBus : signalisation latérale entre silos.

Inspiré du couplage RKKY (Ruderman-Kittel-Kasuya-Yosida) :
- En physique : un électron de conduction oscille entre ferromagnétique
  (coopératif) et antiferromagnétique (inhibiteur) selon l'épaisseur
  de l'espaceur métallique.
- Dans Engrid : le couplage entre silos oscille entre inhibition
  et coopération selon la "profondeur" de raisonnement (step count).

Formule RKKY discrète :
    coupling(n) = A * cos(2 * k_F * n + phi)
    n = step de raisonnement (0, 1, 2, ...)
    k_F = vecteur d'onde de Fermi (paramètre oscillation)
    A = amplitude du couplage [0, 1]
    phi = phase initiale (décalage)

    coupling > 0 → coopération  (silos partagent leur résultat)
    coupling < 0 → inhibition   (silo SOURCE peut veto silo TARGET)
    |coupling| → force du couplage

Usage :
    bus = InhibitionBus()
    bus.emit_veto("SECURITY", "LOGIC", reason="CVE non corrigée détectée", step=0)
    vetoes = bus.get_active_vetoes(target="LOGIC")
    coupling = bus.rkky_coupling("SECURITY", "LOGIC", step=2)
"""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES RKKY
# ══════════════════════════════════════════════════════════════════════════════

# Vecteur d'onde de Fermi (détermine la période d'oscillation)
# k_F = π/2 → oscillation FM/AFM tous les 2 steps (période = 4)
RKKY_K_FERMI = math.pi / 2.0

# Amplitude maximale du couplage [0, 1]
RKKY_AMPLITUDE = 0.8

# Phase initiale — 0 = coopératif au step 0
RKKY_PHASE = 0.0

# Seuil en-dessous duquel le veto est effectif (couplage négatif)
VETO_THRESHOLD = -0.2

# TTL d'un veto (secondes) — expire automatiquement
VETO_TTL_SEC = 300

# Silos reconnus
KNOWN_SILOS = {"INFRA", "LOGIC", "PAYLOAD", "SECURITY", "NOISE"}


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class VetoSignal:
    """Signal d'inhibition émis par un silo source vers un silo target."""

    source: str
    target: str
    reason: str
    step: int  # step de raisonnement au moment du veto
    coupling: float  # valeur RKKY au moment du veto
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_ts: float = field(default_factory=lambda: time.time() + VETO_TTL_SEC)

    @property
    def active(self) -> bool:
        return time.time() < self.expires_ts


@dataclass
class CoopSignal:
    """Signal de coopération — partage de résultat entre silos."""

    source: str
    target: str
    payload: str  # fragment de résultat à partager
    coupling: float
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# INHIBITION BUS
# ══════════════════════════════════════════════════════════════════════════════


class InhibitionBus:
    """
    Canal de signalisation latérale inter-silos.

    Le couplage RKKY détermine si deux silos sont en mode inhibition
    ou coopération à un step donné. Ce n'est pas binaire — c'est un
    continuum oscillant.

    Analogie physique :
        step=0  coupling=+0.80  → LOGIC et SECURITY coopèrent
        step=1  coupling=+0.00  → neutre
        step=2  coupling=-0.80  → SECURITY inhibe LOGIC
        step=3  coupling=+0.00  → neutre
        step=4  coupling=+0.80  → coopération de nouveau
    """

    def __init__(
        self,
        k_fermi: float = RKKY_K_FERMI,
        amplitude: float = RKKY_AMPLITUDE,
        phase: float = RKKY_PHASE,
        db_path: str = "",
        on_veto: Callable[[VetoSignal], None] | None = None,
        on_coop: Callable[[CoopSignal], None] | None = None,
    ):
        self.k_fermi = k_fermi
        self.amplitude = amplitude
        self.phase = phase
        self.on_veto = on_veto
        self.on_coop = on_coop

        self._vetoes: list[VetoSignal] = []
        self._coops: list[CoopSignal] = []
        self._lock = threading.Lock()
        self._step = 0  # step global de raisonnement courant

        root = Path(__file__).resolve().parent.parent
        self._db = db_path or str(root / "recon_silo" / "recon_data" / "inhibition_bus.db")
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS veto_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT,
                    source     TEXT,
                    target     TEXT,
                    reason     TEXT,
                    step       INTEGER,
                    coupling   REAL,
                    expires_ts REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS coop_log (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts       TEXT,
                    source   TEXT,
                    target   TEXT,
                    coupling REAL,
                    payload  TEXT
                )
            """)
            conn.commit()

    def _persist_veto(self, v: VetoSignal) -> None:
        try:
            with sqlite3.connect(self._db) as conn:
                conn.execute(
                    "INSERT INTO veto_log (ts,source,target,reason,step,coupling,expires_ts) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (v.ts, v.source, v.target, v.reason, v.step, v.coupling, v.expires_ts),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Un veto non persiste DISPARAIT au redemarrage : l'inhibition qu'il
            # portait ne sera pas rejouee, et le systeme repartira en croyant que
            # rien ne s'y opposait.
            _lg.getLogger(__name__).error(
                "[inhibition] veto NON persiste (%s: %s) — %s -> %s | consequence: "
                "cette inhibition ne survivra pas au redemarrage",
                type(e).__name__, str(e)[:80], v.source, v.target)

    # ── RKKY coupling ─────────────────────────────────────────────────────────

    def rkky_coupling(self, source: str, target: str, step: int) -> float:
        """
        Calcule le couplage RKKY entre deux silos au step n.

        coupling(n) = A * cos(2 * k_F * n + phi)

        Retourne [-A, +A] :
          > 0  → coopération
          < 0  → inhibition
          = 0  → neutre
        """
        return self.amplitude * math.cos(2 * self.k_fermi * step + self.phase)

    def coupling_sign(self, coupling: float) -> str:
        if coupling > 0.1:
            return "FM"  # ferromagnétique = coopératif
        if coupling < -0.1:
            return "AFM"  # antiferromagnétique = inhibiteur
        return "NEUTRAL"

    # ── Signaux ───────────────────────────────────────────────────────────────

    def emit_veto(
        self,
        source: str,
        target: str,
        reason: str,
        step: int | None = None,
        force: bool = False,
    ) -> VetoSignal | None:
        """
        Émet un veto de source → target.

        Si force=False : le veto n'est émis que si le couplage RKKY
        est effectivement inhibiteur (< VETO_THRESHOLD) au step courant.

        Retourne le VetoSignal créé ou None si le couplage est coopératif.
        """
        n = step if step is not None else self._step
        coupling = self.rkky_coupling(source, target, n)

        if not force and coupling > VETO_THRESHOLD:
            # Couplage coopératif → pas de veto
            return None

        v = VetoSignal(
            source=source,
            target=target,
            reason=reason,
            step=n,
            coupling=coupling,
        )
        with self._lock:
            self._vetoes.append(v)
        self._persist_veto(v)

        if self.on_veto:
            try:
                self.on_veto(v)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                # Le veto est emis mais son CONSOMMATEUR a echoue : l'inhibition
                # n'inhibe rien. C'est pire qu'un veto absent, parce que le journal
                # montre un veto emis.
                _lg.getLogger(__name__).error(
                    "[inhibition] recepteur du veto en ECHEC (%s: %s) — %s -> %s | "
                    "consequence: le veto est journalise mais n'a EMPECHE personne",
                    type(e).__name__, str(e)[:80], v.source, v.target)

        return v

    def emit_coop(
        self,
        source: str,
        target: str,
        payload: str,
        step: int | None = None,
    ) -> CoopSignal | None:
        """
        Partage un fragment de résultat entre silos coopérants.
        N'envoie que si le couplage est positif (FM).
        """
        n = step if step is not None else self._step
        coupling = self.rkky_coupling(source, target, n)

        if coupling <= 0:
            return None

        c = CoopSignal(source=source, target=target, payload=payload, coupling=coupling)
        with self._lock:
            self._coops.append(c)

        if self.on_coop:
            try:
                self.on_coop(c)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "[inhibition] recepteur de cooperation en ECHEC (%s: %s) | "
                    "consequence: le signal de cooperation est emis mais n'a produit "
                    "aucun effet chez son destinataire", type(e).__name__, str(e)[:80])

        return c

    # ── Lecture ───────────────────────────────────────────────────────────────

    def get_active_vetoes(self, target: str | None = None) -> list[VetoSignal]:
        """Retourne les vetos actifs (non expirés), filtrés par target."""
        with self._lock:
            vetoes = [v for v in self._vetoes if v.active]
        if target:
            vetoes = [v for v in vetoes if v.target == target]
        return vetoes

    def is_vetoed(self, target: str, source: str | None = None) -> bool:
        """Un silo est-il sous veto actif ?"""
        vetoes = self.get_active_vetoes(target)
        if source:
            vetoes = [v for v in vetoes if v.source == source]
        return bool(vetoes)

    def get_coop_payloads(self, target: str) -> list[str]:
        """Récupère les fragments coopératifs destinés à target."""
        with self._lock:
            return [c.payload for c in self._coops if c.target == target]

    # ── Step management ───────────────────────────────────────────────────────

    def next_step(self) -> int:
        """Avance le step global de raisonnement."""
        self._step += 1
        # Purge les vetos expirés à chaque step
        with self._lock:
            self._vetoes = [v for v in self._vetoes if v.active]
        return self._step

    def reset(self) -> None:
        """Remet le bus à zéro (nouvelle mission)."""
        with self._lock:
            self._vetoes.clear()
            self._coops.clear()
            self._step = 0

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """État complet du bus pour debug."""
        pairs = [
            ("SECURITY", "LOGIC"),
            ("SECURITY", "INFRA"),
            ("LOGIC", "PAYLOAD"),
            ("INFRA", "LOGIC"),
        ]
        coupling_map = {}
        for src, tgt in pairs:
            c = self.rkky_coupling(src, tgt, self._step)
            coupling_map[f"{src}→{tgt}"] = {
                "coupling": round(c, 3),
                "mode": self.coupling_sign(c),
            }
        return {
            "step": self._step,
            "active_vetoes": len(self.get_active_vetoes()),
            "coop_signals": len(self._coops),
            "coupling_map": coupling_map,
        }
