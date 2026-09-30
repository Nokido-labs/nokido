# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_promotion_queue
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
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
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_promotion_queue.py — File d'attente adaptative pour la promotion RAG
==========================================================================
Découplé de brain_worker.py pour ne pas alourdir le sidecar ML.

Architecture :
  PromotionOrchestrator
    └─ asyncio.Queue (en mémoire)
    └─ SQLite (persistance inter-sessions via agent_tasks)
    └─ N workers asyncio (2 local, 10 cloud)
    └─ RAM guardrail : pause si RAM > RAM_THRESHOLD_PCT

Intégration :
  TUI allumée  → PromotionOrchestrator.get() lancé dans on_mount()
  TUI éteinte  → run_standalone() depuis __main__ ou brain_worker
  boot suivant → restore_from_db() reprend les tâches PENDING

Priorités :
  0 = action utilisateur directe (rag_ingest MCP)
  5 = @rag build batch
 10 = add_document background
 20 = batch_promote_draft systématique

Topics ZMQ (optionnel, si brain_worker tourne) :
  b"promotion:done"  → {chunk_id, from, to, trust_score}
  b"promotion:fail"  → {chunk_id, reason}
"""


import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
_ROOT = Path(__file__).resolve().parent.parent

# Détection auto cloud vs local
_IS_CLOUD = os.getenv("LAFORGE_CLOUD", "").lower() == "true"

# Seuil RAM : pause si mémoire utilisée > ce pourcentage.
#
# CONTRAT DE REPRESENTATION, mesure le 2026-09-13 : `LAFORGE_RAM_THRESHOLD` est
# REEL-VALUE. La configuration du corps la pose a "95.0", et l'autre lecteur du
# systeme -- `forge_resource_manager.should_throttle` (L1874) -- la lit en
# `float`. Ce site etait le SEUL a exiger un entier strict : `int("95.0")` leve
# ValueError, donc ce module cassait A L'IMPORT dans tout process ou
# l'environnement du corps avait ete charge avant lui. Il ne « marchait » que par
# ordre d'import favorable.
#
# Le defaut etait MASQUE : `test_orchestrator_cloud_workers` recharge ce module,
# mais `importlib.reload` etait inerte sur un module ponte (cf.
# nokido_agent/__init__.py) -- la ligne n'etait jamais reevaluee et le test
# passait sans rien verifier. Reparer le pont a fait remonter le defaut.
#
# NI `int(float(...))` : ce serait troquer une incoherence de contrat contre une
# TRONCATURE SILENCIEUSE. Un seuil a 95.5 deviendrait 95, et une RAM a 95.2 %
# declencherait une attente que l'autre regulateur, lui, ne declenche pas. Deux
# organes qui lisent la meme variable doivent en tirer la MEME decision.
# Contrat verrouille par tests/nr/test_forge_promotion_queue_nr.py.
RAM_THRESHOLD_PCT = float(os.getenv("LAFORGE_RAM_THRESHOLD", "88"))


# ─────────────────────────────────────────────────────────────────────────────
# Item de queue
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(order=True)
class PromotionItem:
    priority: int
    chunk_id: str = field(compare=False, default="")
    author_id: str = field(compare=False, default="collab:claude")
    source_exists: bool = field(compare=False, default=True)
    enqueued_at: str = field(
        compare=False,
        default_factory=lambda: (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# RAM guardrail
# ─────────────────────────────────────────────────────────────────────────────


async def _wait_for_ram(threshold: float = RAM_THRESHOLD_PCT, check_interval: float = 5.0) -> None:
    """
    Suspend la coroutine tant que la RAM utilisée dépasse le seuil.
    Non-bloquant : cède le contrôle à l'event loop pendant l'attente.
    """
    try:
        import psutil

        while psutil.virtual_memory().percent > threshold:
            pct = psutil.virtual_memory().percent
            logger.debug(f"[promo] RAM {pct:.0f}% > {threshold}% — attente {check_interval}s")
            await asyncio.sleep(check_interval)
    except ImportError:
        pass  # psutil absent → on continue sans guardrail


# ─────────────────────────────────────────────────────────────────────────────
# Persistance SQLite (agent_tasks)
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_promo_table(db_path: Path = _DB) -> None:
    """Crée la table promotion_queue si absente (idempotent)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS promotion_queue (
            chunk_id     TEXT PRIMARY KEY,
            priority     INTEGER DEFAULT 10,
            author_id    TEXT    DEFAULT 'collab:claude',
            source_exists INTEGER DEFAULT 1,
            status       TEXT    DEFAULT 'pending',
            enqueued_at  TEXT,
            processed_at TEXT,
            result       TEXT
        )
    """)
    conn.commit()
    conn.close()


def _persist_item(item: PromotionItem, db_path: Path = _DB) -> None:
    """Persiste un item en statut 'pending'."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            INSERT OR IGNORE INTO promotion_queue
            (chunk_id, priority, author_id, source_exists, status, enqueued_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """,
            (item.chunk_id, item.priority, item.author_id, int(item.source_exists), item.enqueued_at),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[promo] persist: {e}")


def _mark_done(chunk_id: str, result: Dict, db_path: Path = _DB) -> None:
    """Marque un item comme traité."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            UPDATE promotion_queue
            SET status='done', processed_at=?, result=?
            WHERE chunk_id=?
        """,
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps(result, ensure_ascii=False),
                chunk_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[promo] mark_done: {e}")


def restore_from_db(db_path: Path = _DB) -> list[PromotionItem]:
    """
    Récupère les items 'pending' non traités (survivants d'un arrêt brutal).
    Appelé au boot pour reprendre le travail interrompu.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("""
            SELECT chunk_id, priority, author_id, source_exists, enqueued_at
            FROM promotion_queue
            WHERE status = 'pending'
            ORDER BY priority, enqueued_at
            LIMIT 500
        """).fetchall()
        conn.close()
        items = [
            PromotionItem(
                priority=r[1],
                chunk_id=r[0],
                author_id=r[2],
                source_exists=bool(r[3]),
                enqueued_at=r[4],
            )
            for r in rows
        ]
        if items:
            logger.info(f"[promo] Reprise boot : {len(items)} items pending")
        return items
    except Exception as e:
        logger.debug(f"[promo] restore: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# PromotionOrchestrator
# ─────────────────────────────────────────────────────────────────────────────


class PromotionOrchestrator:
    """
    File d'attente adaptative pour la promotion DRAFT → VERIFIED/GOLD.

    Adaptatif :
      - Local  : 2 workers (ne tue pas la TUI ni SSH)
      - Cloud  : 10 workers (LAFORGE_CLOUD=true)

    Guardrail RAM : pause si RAM > RAM_THRESHOLD_PCT

    Persistance : chaque item est enregistré dans promotion_queue (SQLite WAL)
    avant traitement. Au boot suivant, restore_from_db() reprend les pending.

    ZMQ optionnel : si pub_fn fourni, publie les événements de promotion
    sur TOPIC_LEDGER pour les nœuds Edge abonnés.
    """

    TOPIC_PROMO_DONE = b"promotion:done"
    TOPIC_PROMO_FAIL = b"promotion:fail"

    def __init__(
        self,
        db_path: Path = _DB,
        pub_fn: Optional[Callable] = None,
        max_local_workers: int = 2,
    ):
        """Init.

        Args:
            db_path: Description.
            pub_fn: Description.
            max_local_workers: Description.
        """
        _ensure_promo_table(db_path)
        self._db = db_path
        self._pub_fn = pub_fn  # callable(topic: bytes, payload: dict)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._workers: list = []
        self._stats = {"enqueued": 0, "promoted": 0, "skipped": 0, "errors": 0}

        # Détection auto cloud
        self.max_workers = 10 if _IS_CLOUD else max_local_workers
        logger.info(
            f"[promo] PromotionOrchestrator init "
            f"({'cloud' if _IS_CLOUD else 'local'}, {self.max_workers} workers, "
            f"RAM seuil {RAM_THRESHOLD_PCT}%)"
        )

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    async def start(self, restore: bool = True) -> None:
        """Lance les workers. Optionnel : reprend les pending depuis DB."""
        self._running = True
        if restore:
            for item in restore_from_db(self._db):
                await self._queue.put(item)

        self._workers = [asyncio.create_task(self._worker_loop(i)) for i in range(self.max_workers)]
        logger.info(f"[promo] {self.max_workers} worker(s) démarré(s)")

    async def stop(self) -> None:
        """Arrêt propre — attend la fin des items en cours."""
        self._running = False
        # Poison pill pour chaque worker
        for _ in range(self.max_workers):
            await self._queue.put(None)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info(f"[promo] Arrêt propre. Stats: {self._stats}")

    async def join(self) -> None:
        """Attend que la queue soit vide (mode batch standalone)."""
        await self._queue.join()

    # ── API publique ──────────────────────────────────────────────────────────

    async def enqueue(
        self,
        chunk_id: str,
        priority: int = 10,
        author_id: str = "collab:claude",
        source_exists: bool = True,
    ) -> None:
        """
        Ajoute un chunk à la file.
        Priorité basse (10) = background, haute (0) = utilisateur direct.
        """
        item = PromotionItem(
            priority=priority,
            chunk_id=chunk_id,
            author_id=author_id,
            source_exists=source_exists,
        )
        _persist_item(item, self._db)
        await self._queue.put(item)
        self._stats["enqueued"] += 1

    def enqueue_sync(
        self,
        chunk_id: str,
        priority: int = 10,
        author_id: str = "collab:claude",
        source_exists: bool = True,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """
        Version thread-safe pour appel depuis code synchrone
        (ex: _save_embeddings, rag_ingest MCP dans un thread non-asyncio).
        """
        item = PromotionItem(priority=priority, chunk_id=chunk_id, author_id=author_id, source_exists=source_exists)
        _persist_item(item, self._db)
        try:
            _loop = loop or asyncio.get_event_loop()
            if _loop.is_running():
                asyncio.run_coroutine_threadsafe(self._queue.put(item), _loop)
            else:
                _loop.run_until_complete(self._queue.put(item))
        except RuntimeError:
            # Pas d'event loop disponible — créer un thread dédié
            threading.Thread(target=lambda: asyncio.run(self._queue.put(item)), daemon=True).start()
        self._stats["enqueued"] += 1

    @property
    def queue_size(self) -> int:
        """Queue size."""
        return self._queue.qsize()

    def stats(self) -> Dict:
        """Stats."""
        return dict(self._stats, queue_size=self._queue.qsize())

    # ── Boucle worker ─────────────────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int) -> None:
        """Boucle d'un worker — tourne jusqu'à stop() ou poison pill."""
        logger.debug(f"[promo] worker-{worker_id} démarré")
        while self._running:
            try:
                item = await self._queue.get()
            except Exception:
                break

            if item is None:  # poison pill
                self._queue.task_done()
                break

            try:
                await self._process(item, worker_id)
            except Exception as e:
                logger.warning(f"[promo] worker-{worker_id} erreur: {e}")
                self._stats["errors"] += 1
                _mark_done(item.chunk_id, {"error": str(e)}, self._db)
            finally:
                self._queue.task_done()

        logger.debug(f"[promo] worker-{worker_id} arrêté")

    async def _process(self, item: PromotionItem, worker_id: int) -> None:
        """
        Traite un item :
          1. RAM guardrail
          2. CoVe mono_mode_promote()
          3. Persist résultat
          4. Publish ZMQ si pub_fn disponible
        """
        # ── 1. RAM guardrail ──────────────────────────────────────────────────
        await _wait_for_ram(RAM_THRESHOLD_PCT)

        # ── 2. Promotion CoVe ─────────────────────────────────────────────────
        t0 = time.monotonic()
        promoted = False
        result: Dict = {}

        try:
            from nokido_agent.app.forge_rag_truth import mono_mode_promote

            promoted, cove = mono_mode_promote(
                chunk_id=item.chunk_id,
                author_id=item.author_id,
                source_exists=item.source_exists,
                db_path=self._db,
            )
            result = {
                "promoted": promoted,
                "trust_score": cove.trust_score,
                "hallucination": cove.hallucination_check,
                "coherence": cove.coherence_score,
                "ring_enforced": cove.ring_enforced,
                "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                "worker": worker_id,
            }
            if promoted:
                self._stats["promoted"] += 1
            else:
                self._stats["skipped"] += 1

        except Exception as e:
            result = {"error": str(e), "promoted": False}
            self._stats["errors"] += 1
            logger.debug(f"[promo] chunk {item.chunk_id}: {e}")

        # ── 3. Persist ────────────────────────────────────────────────────────
        _mark_done(item.chunk_id, result, self._db)

        # ── 4. ZMQ publish ────────────────────────────────────────────────────
        if self._pub_fn:
            topic = self.TOPIC_PROMO_DONE if promoted else self.TOPIC_PROMO_FAIL
            payload = {"chunk_id": item.chunk_id, **result}
            try:
                self._pub_fn(topic, payload)
            except Exception:
                pass

        if promoted:
            logger.info(
                f"[promo] worker-{worker_id} chunk {item.chunk_id}: "
                f"promoted trust={result.get('trust_score', 0):.3f} "
                f"({result.get('duration_ms', 0):.0f}ms)"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Singleton — accessible depuis tous les modules
# ─────────────────────────────────────────────────────────────────────────────

_orchestrator: Optional[PromotionOrchestrator] = None


def get_orchestrator(
    pub_fn: Optional[Callable] = None,
    db_path: Path = _DB,
) -> PromotionOrchestrator:
    """
    Retourne l'orchestrateur singleton.
    Crée si nécessaire — thread-safe (GIL Python suffit ici).
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = PromotionOrchestrator(db_path=db_path, pub_fn=pub_fn)
    return _orchestrator


async def enqueue_promotion(
    chunk_id: str,
    priority: int = 10,
    author_id: str = "collab:claude",
    source_exists: bool = True,
) -> None:
    """Raccourci global : enfile un chunk dans le singleton."""
    await get_orchestrator().enqueue(
        chunk_id=chunk_id,
        priority=priority,
        author_id=author_id,
        source_exists=source_exists,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone : batch processing hors TUI
# ─────────────────────────────────────────────────────────────────────────────


async def run_standalone(
    limit: int = 200,
    priority: int = 5,
    author_id: str = "system:nr_runner",
    db_path: Path = _DB,
) -> Dict:
    """
    Mode standalone : traite les drafts en batch sans TUI.
    Utilisé par brain_worker ou via `python forge_promotion_queue.py`.

    Retourne les stats de la session.
    """
    orch = get_orchestrator(db_path=db_path)
    await orch.start(restore=True)

    # Charger les chunks draft existants en DB
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            """
            SELECT id FROM rag_chunks
            WHERE json_extract(meta,'$.consensus_level') = 'draft'
            AND id NOT IN (
                SELECT chunk_id FROM promotion_queue
                WHERE status IN ('done','pending')
            )
            ORDER BY ROWID DESC
            LIMIT ?
        """,
            (limit,),
        ).fetchall()
        conn.close()
        for (cid,) in rows:
            await orch.enqueue(cid, priority=priority, author_id=author_id)
        logger.info(f"[promo:standalone] {len(rows)} drafts enfilés")
    except Exception as e:
        logger.error(f"[promo:standalone] chargement DB: {e}")

    await orch.join()
    await orch.stop()
    return orch.stats()


# ─────────────────────────────────────────────────────────────────────────────
# Branchement brain_worker — intégré dans BrainService
# ─────────────────────────────────────────────────────────────────────────────


def attach_to_brain_service(brain_service_instance: Any) -> None:
    """
    Attache l'orchestrateur à un BrainService existant.
    Appelé depuis BrainService.start() après démarrage ZMQ.

    Utilise le pub_fn du BrainService pour les notifications ZMQ.
    """
    pub_fn = getattr(brain_service_instance, "_pub_fn", None)
    orch = get_orchestrator(pub_fn=pub_fn)

    # Lancer l'orchestrateur dans le thread asyncio SSH si disponible
    ssh_loop = getattr(getattr(brain_service_instance, "_ssh", None), "_loop", None)

    def _start_in_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Start in loop.

        Args:
            loop: Description.
        """
        asyncio.run_coroutine_threadsafe(orch.start(restore=True), loop)
        logger.info("[promo] Orchestrateur attaché au BrainService")

    if ssh_loop and ssh_loop.is_running():
        _start_in_loop(ssh_loop)
    else:
        # Fallback : thread asyncio dédié
        def _run() -> None:
            """Run."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(orch.start(restore=True))
            loop.run_forever()

        threading.Thread(target=_run, name="promo-loop", daemon=True).start()
        logger.info("[promo] Orchestrateur dans thread dédié")


# ─────────────────────────────────────────────────────────────────────────────
# __main__ : traitement batch depuis CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Promotion RAG batch")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--priority", type=int, default=5)
    parser.add_argument("--author", default="system:nr_runner")
    args = parser.parse_args()

    stats = asyncio.run(run_standalone(limit=args.limit, priority=args.priority, author_id=args.author))
    print(json.dumps(stats, indent=2))
