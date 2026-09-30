"""
forge_bounded_queue.py — Bounded queue avec backpressure + leptin release.

Phase 7b (2026-05-24). Outil reutilisable pour les producteurs Nokido
qui generent du backlog (embed_trigger, ingestion_pipeline, watch_agent,
hebbian_linker). Avant ce module : chaque producteur empilait sans cap
=> RAM gonfle silencieusement => OOM ou heartbeat stale.

Pattern hydraulique (vase d'expansion + relief valve) :
  - capacity = N : queue blocking au-dela
  - try_put(item) : non-bloquant, retourne False si pleine
  - Si full : release(leptin level=fill_pct receptors=['producer', 'orchestrator'])
    -> autres daemons peuvent throttle leur production en lisant la dose

API :
    >>> bq = BoundedQueue(name="my_producer", capacity=1000)
    >>> if bq.try_put(item): ...        # non-bloquant
    >>> bq.put(item, timeout=5.0)       # bloquant avec timeout
    >>> bq.get()                        # consumer
    >>> bq.stats()                      # {capacity, current, fill_pct, rejected, accepted}

Hormone leptin :
  - half_life 900s (15min) => signal de satiete moyen-terme
  - level = fill_pct au moment de la saturation
  - receptors = [<queue_name>, 'orchestrator', 'producer']

Pas d'integration auto dans les daemons existants — outil opt-in. Wrap
manuellement dans les daemons consommateurs.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `EcrivainDiffere` — Execute des ecritures HORS de la boucle asyncio qui les produit : un seul fil, ordre FIFO.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge_bounded_queue")

# Throttle release(leptin) : pas plus d'1 release par RELEASE_COOLDOWN_S
# meme si la queue sature en boucle (evite spam hub :8766).
RELEASE_COOLDOWN_S = 30.0


@dataclass
class _Stats:
    accepted: int = 0
    rejected: int = 0
    blocking_waits: int = 0
    timeouts: int = 0
    saturated_releases: int = 0
    last_release_ts: float = 0.0


class BoundedQueue:
    """Wrapper queue.Queue avec stats + release(leptin) sur saturation."""

    def __init__(self, name: str, capacity: int = 1000, leptin_release: bool = True):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.name = name
        self.capacity = capacity
        self.leptin_release = leptin_release
        self._q: queue.Queue = queue.Queue(maxsize=capacity)
        self._stats = _Stats()
        self._lock = threading.Lock()

    # ----- producer side -------------------------------------------------

    def try_put(self, item: Any) -> bool:
        """Non-bloquant. True si accepte, False si pleine (release leptin)."""
        try:
            self._q.put_nowait(item)
            with self._lock:
                self._stats.accepted += 1
            return True
        except queue.Full:
            with self._lock:
                self._stats.rejected += 1
            self._maybe_release_leptin()
            return False

    def put(self, item: Any, timeout: float | None = None) -> bool:
        """Bloquant avec timeout. True si accepte, False si timeout."""
        try:
            if timeout is None:
                self._q.put(item)
            else:
                self._q.put(item, timeout=timeout)
            with self._lock:
                self._stats.accepted += 1
                self._stats.blocking_waits += 1
            return True
        except queue.Full:
            with self._lock:
                self._stats.timeouts += 1
                self._stats.rejected += 1
            self._maybe_release_leptin()
            return False

    # ----- consumer side -------------------------------------------------

    def get(self, timeout: float | None = None) -> Any:
        """Bloquant ou avec timeout. Raise queue.Empty si timeout."""
        if timeout is None:
            return self._q.get()
        return self._q.get(timeout=timeout)

    def get_nowait(self) -> Any:
        return self._q.get_nowait()

    def task_done(self) -> None:
        try:
            self._q.task_done()
        except ValueError:
            pass

    # ----- introspection -------------------------------------------------

    def current(self) -> int:
        return self._q.qsize()

    def fill_pct(self) -> float:
        return self.current() / self.capacity

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "capacity": self.capacity,
                "current": self.current(),
                "fill_pct": round(self.fill_pct(), 3),
                "accepted": self._stats.accepted,
                "rejected": self._stats.rejected,
                "blocking_waits": self._stats.blocking_waits,
                "timeouts": self._stats.timeouts,
                "saturated_releases": self._stats.saturated_releases,
                "reject_ratio": round(
                    self._stats.rejected / max(1, self._stats.accepted + self._stats.rejected),
                    3,
                ),
            }

    def _maybe_release_leptin(self) -> None:
        if not self.leptin_release:
            return
        now = time.time()
        with self._lock:
            if now - self._stats.last_release_ts < RELEASE_COOLDOWN_S:
                return
            self._stats.last_release_ts = now
            self._stats.saturated_releases += 1
        try:
            from nokido_agent.app.forge_hormones import release

            release(
                "leptin",
                level=min(1.0, self.fill_pct()),
                payload={
                    "queue": self.name,
                    "capacity": self.capacity,
                    "current": self.current(),
                    "stats": self.stats(),
                },
                receptors=[self.name, "orchestrator", "producer"],
            )
        except Exception as exc:
            logger.debug("leptin release skipped: %s", exc)


class EcrivainDiffere:
    """Execute des ecritures HORS de la boucle asyncio qui les produit : un seul fil, ordre FIFO.

    Mesure du 27/09 : le hub ecrivait dans RAG/embeddings.db DEPUIS sa boucle (profileur par
    tool, journal d'intentions). Des qu'un tiers tenait le verrou d'ecriture, chaque appel
    attendait 5 a 10 s (timeout SQLite) et TOUT le hub gelait : 1 257 s de boucle figee en une
    soiree, le tray le voyait instable. Ici l'ecriture part dans un fil dedie ; la boucle ne
    paie qu'un `put_nowait`.

    - `sur_une_boucle()` : vrai si l'appelant tourne dans une boucle asyncio. Hors boucle
      (script, CLI, thread), l'appelant ecrit sur place : aucun changement de comportement.
    - File BORNEE, sans hormone (la liberer appelle le hub, qui s'attendrait lui-meme) :
      pleine => ecriture ABANDONNEE et comptee (`stats()['rejected']`), jamais bloquante.
    - Un echec d'ecriture est compte (`echecs`) et journalise, jamais propage.
    - Fil daemon : ce qui reste en file a l'arret brutal du processus est perdu (best-effort).
    """

    def __init__(self, name: str, capacity: int = 10000):
        self._bq = BoundedQueue(name, capacity=capacity, leptin_release=False)
        self._fil: threading.Thread | None = None
        self._verrou = threading.Lock()
        self.echecs = 0

    @staticmethod
    def sur_une_boucle() -> bool:
        import asyncio

        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def soumettre(self, ecriture) -> bool:
        """Met `ecriture` (callable sans argument) en file. False si la file est pleine."""
        self._demarrer()
        return self._bq.try_put(ecriture)

    def _demarrer(self) -> None:
        if self._fil is not None and self._fil.is_alive():
            return
        with self._verrou:
            if self._fil is None or not self._fil.is_alive():
                self._fil = threading.Thread(target=self._boucle, daemon=True,
                                             name=f"ecrivain-{self._bq.name}")
                self._fil.start()

    def _boucle(self) -> None:
        while True:
            ecriture = self._bq.get()
            try:
                ecriture()
            except Exception as exc:  # noqa: BLE001
                self.echecs += 1
                logger.warning("ecrivain %s : ecriture perdue (%s: %s)", self._bq.name,
                               type(exc).__name__, str(exc)[:120])
            finally:
                self._bq.task_done()

    def vider(self, timeout: float = 30.0) -> bool:
        """Attend que la file soit ecoulee (tests, arret propre). False si le delai expire."""
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            if self._bq._q.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    def stats(self) -> dict[str, Any]:
        return {**self._bq.stats(), "echecs": self.echecs}


if __name__ == "__main__":
    # smoke
    import json

    bq = BoundedQueue("smoke_test", capacity=3, leptin_release=False)
    print("put 5 items into capacity 3:")
    for i in range(5):
        ok = bq.try_put(i)
        print(f"  item {i}: {'OK' if ok else 'REJECTED'}")
    print("\nstats:", json.dumps(bq.stats(), indent=2))
    print("\ndrain:")
    while bq.current() > 0:
        print(f"  got {bq.get_nowait()}")
