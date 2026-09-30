# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_hot_ingest
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_hot_ingest.py — Fast-Track Ingestion (Priorité 0, Ring 2)
===============================================================
Point d'entrée prioritaire pour l'humain dans la TUI.

Principe :
  L'humain est un validateur. Quand il dépose un fichier ou une URL
  explicitement, on lui attribue ring=2 (TRUSTED) immédiatement —
  pas ring=3 comme un agent externe.

  Ce bypass est légitime UNIQUEMENT depuis la TUI (action humaine directe).
  Le MCP server n'a pas accès à cette voie.

Deux scénarios :
  1. @rag drop <fichier|URL>   — ingestion forcée Ring 2, priorité 0 (FLASH)
  2. Hot-folder watcher        — surveille data/rag_files/ et ingère les nouveaux
                                  fichiers avec ring=2 dès qu'ils apparaissent

Flux complet :
  TUI humain → hot_ingest() → add_document() [ring=2, author=user_manual]
                             → CoVe SKIPPÉ (humain a déjà validé)
                             → qualify_chunk() → trust_score=0.8 (TRUSTED)
                             → PromotionOrchestrator.enqueue(priority=0)
                             → FAISS rebuild
                             → feedback TUI immédiat

Author signé : 'user_manual' (ring=2 TRUSTED par convention humaine)
Provenance   : 'tui_drop' ou 'hot_folder'
"""


import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_RAG_DIR = _ROOT / "data" / "rag_files"

# Ring humain — validateur direct TUI
HUMAN_RING = 2
HUMAN_AUTHOR = "user_manual"
HUMAN_CONSENSUS = "verified"  # pas draft — l'humain a déjà présélectionné
HUMAN_TRUST = 0.8
HUMAN_PRIORITY = 0  # FLASH — passe devant tout


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────────────────────


def _build_human_meta(source: str, provenance: str = "tui_drop") -> Dict:
    """Construit le meta JSON pour une ingestion humaine directe."""
    return {
        "ring": HUMAN_RING,
        "ring_label": "TRUSTED",
        "consensus_level": HUMAN_CONSENSUS,
        "trust_score": HUMAN_TRUST,
        "mutable": True,
        "verified_by": [
            {
                "agent": HUMAN_AUTHOR,
                "ring": HUMAN_RING,
                "check": "human_validation",
                "score": HUMAN_TRUST,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "qualified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin_type": "document",
        "provenance": provenance,
        "author": HUMAN_AUTHOR,
        "cove_skip": True,  # l'humain a fait office de CoVe
    }


def _detect_domain(path_or_url: str) -> str:
    """Détecte le domaine probable depuis le nom du fichier."""
    s = path_or_url.lower()
    if any(x in s for x in ["secu", "kali", "pentest", "cve", "hack"]):
        return "securite"
    if any(x in s for x in ["python", "code", "prog", "dev"]):
        return "code"
    if any(x in s for x in ["linux", "debian", "ubuntu", "kernel"]):
        return "systeme"
    if any(x in s for x in ["reseau", "network", "cisco", "routeur"]):
        return "reseau"
    if any(x in s for x in ["docker", "k8s", "ansible", "ci", "devops"]):
        return "devops"
    if any(x in s for x in ["ia", "llm", "rag", "embedding", "ai"]):
        return "ia"
    return "general"


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion fichier (Fast-Track)
# ─────────────────────────────────────────────────────────────────────────────


async def hot_ingest_file(
    path: Path,
    rag_engine: Any,
    log_fn: Callable[[str], None] = print,
    provenance: str = "tui_drop",
    delete_after: bool = False,
) -> Dict:
    """
    Ingestion prioritaire d'un fichier local.
    Ring 2 (TRUSTED) — l'humain fait office de validateur.

    Returns:
        {"ok": bool, "chunks": int, "source": str, "trust": float, "msg": str}
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    if not path.exists():
        return {"ok": False, "chunks": 0, "source": str(path), "trust": 0, "msg": f"Fichier introuvable: {path}"}

    log_fn(f"[dim]⚡ Fast-track : [bold]{path.name}[/bold] (ring=TRUSTED)…[/dim]")
    t0 = time.monotonic()

    # Ingestion via RAGEngine standard
    ok = await rag_engine.add_document(path, delete_after=delete_after)
    if not ok:
        return {
            "ok": False,
            "chunks": 0,
            "source": path.name,
            "trust": 0,
            "msg": f"add_document a échoué pour {path.name}",
        }

    # Patcher le meta des chunks nouvellement insérés avec ring=TRUSTED
    human_meta = _build_human_meta(path.name, provenance)
    _patch_source_meta(path.name, human_meta)

    # Promouvoir immédiatement dans la file prioritaire
    _enqueue_source_promotion(path.name, priority=HUMAN_PRIORITY)

    elapsed = (time.monotonic() - t0) * 1000
    n = _count_source_chunks(path.name)
    msg = f"[green]⚡ {path.name}[/] — {n} chunks · ring=TRUSTED · trust=0.8 · {elapsed:.0f}ms"
    log_fn(msg)
    return {"ok": True, "chunks": n, "source": path.name, "trust": HUMAN_TRUST, "msg": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion URL (Fast-Track)
# ─────────────────────────────────────────────────────────────────────────────


async def hot_ingest_url(
    url: str,
    rag_engine: Any,
    log_fn: Callable[[str], None] = print,
    provenance: str = "tui_drop",
) -> Dict:
    """
    Ingestion prioritaire d'une URL.
    Extraction texte via trafilatura → forge_rag_engine.ingest_web_content().

    Returns:
        {"ok": bool, "chunks": int, "source": str, "trust": float, "msg": str}
    """
    log_fn(f"[dim]⚡ Fast-track URL : [bold]{url[:60]}[/bold]…[/dim]")
    t0 = time.monotonic()
    text = ""

    # Extraction texte
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True) or ""
    except ImportError:
        pass

    if not text:
        # Fallback : requests + strip HTML basique
        try:
            import urllib.request
            import html
            import re

            with urllib.request.urlopen(url, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", raw)
            text = html.unescape(text)
            text = re.sub(r"\s{3,}", "  ", text)[:50000]
        except Exception as e:
            return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": f"Extraction URL échouée: {e}"}

    if len(text.strip()) < 50:
        return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": "Contenu extrait trop court"}

    # Source canonique
    from urllib.parse import urlparse

    domain = urlparse(url).netloc.replace("www.", "")
    source = f"url:{domain}"

    # Ingestion via le moteur RAG
    n = await rag_engine.ingest_web_content(
        session_name=source,
        content=text,
        skill=_detect_domain(url),
        meta={"layer": "trusted", "url": url, "ingested_at": datetime.now(timezone.utc).isoformat()},
    )

    if n == 0:
        return {"ok": False, "chunks": 0, "source": url, "trust": 0, "msg": "Aucun chunk ingéré"}

    # Patcher avec meta TRUSTED
    human_meta = _build_human_meta(source, provenance)
    _patch_source_meta(source, human_meta)
    _enqueue_source_promotion(source, priority=HUMAN_PRIORITY)

    elapsed = (time.monotonic() - t0) * 1000
    msg = f"[green]⚡ {domain}[/] — {n} chunks · ring=TRUSTED · trust=0.8 · {elapsed:.0f}ms"
    log_fn(msg)
    return {"ok": True, "chunks": n, "source": source, "trust": HUMAN_TRUST, "msg": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────


def _patch_source_meta(source: str, human_meta: Dict) -> int:
    """
    Met à jour le meta de tous les chunks d'une source avec les données TRUSTED.
    Opération synchrone légère — SQLite WAL.
    """
    import sqlite3, json

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute("SELECT id, meta FROM rag_chunks WHERE source=?", (source,)).fetchall()
        updates = []
        for chunk_id, meta_s in rows:
            meta = json.loads(meta_s) if meta_s else {}
            meta.update(human_meta)
            updates.append((json.dumps(meta, ensure_ascii=False), chunk_id))
        if updates:
            conn.executemany("UPDATE rag_chunks SET meta=? WHERE id=?", updates)
            conn.commit()
        conn.close()
        return len(updates)
    except Exception as e:
        logger.debug(f"[hot_ingest] patch_meta: {e}")
        return 0


def _count_source_chunks(source: str) -> int:
    """Count source chunks.

    Args:
        source: Description.
    """
    import sqlite3

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE source=?", (source,)).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def _enqueue_source_promotion(source: str, priority: int = 0) -> None:
    """Enfile tous les chunks d'une source dans la queue de promotion."""
    import sqlite3

    db = _ROOT / "RAG" / "embeddings.db"
    try:
        from nokido_agent.app.forge_promotion_queue import get_orchestrator

        orch = get_orchestrator()
        conn = sqlite3.connect(str(db))
        ids = [r[0] for r in conn.execute("SELECT id FROM rag_chunks WHERE source=?", (source,)).fetchall()]
        conn.close()
        # enqueue_sync — thread-safe depuis code synchrone
        for chunk_id in ids:
            orch.enqueue_sync(chunk_id, priority=priority, author_id=HUMAN_AUTHOR, source_exists=True)
        if ids:
            logger.debug(f"[hot_ingest] {len(ids)} chunks enfilés prio={priority}")
    except Exception as e:
        logger.debug(f"[hot_ingest] enqueue: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Hot-Folder Watcher
# ─────────────────────────────────────────────────────────────────────────────


class HotFolderWatcher:
    """
    Surveille data/rag_files/ et ingère les nouveaux fichiers automatiquement
    avec ring=TRUSTED dès qu'ils apparaissent.

    Utilisé quand l'humain copie directement un PDF dans le dossier RAG
    sans passer par la commande @rag download.

    Polling toutes les POLL_INTERVAL secondes (pas d'inotify requis).
    Non-bloquant : thread daemon.
    """

    POLL_INTERVAL = 3.0  # secondes entre chaque scan
    SUPPORTED_EXT = {".pdf", ".txt", ".md"}

    def __init__(self, rag_dir: Path = _RAG_DIR, rag_engine_getter: Callable = None, log_fn: Callable = None) -> None:
        """Init.

        Args:
            rag_dir: Description.
            rag_engine_getter: Description.
            log_fn: Description.
        """
        self._dir = rag_dir
        self._getter = rag_engine_getter  # callable() → rag_engine
        self._log_fn = log_fn or (lambda m: logger.info(m))
        self._seen: set = set()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Indexer les fichiers déjà présents sans les ré-ingérer
        self._init_seen()

    def _init_seen(self) -> None:
        """Marque les fichiers existants comme déjà connus."""
        if self._dir.exists():
            self._seen = {f.name for f in self._dir.iterdir() if f.suffix.lower() in self.SUPPORTED_EXT}
            logger.debug(f"[watcher] {len(self._seen)} fichiers existants marqués")

    def start(self) -> None:
        """Start."""
        if self._running:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="hot-folder-watcher", daemon=True)
        self._thread.start()
        logger.info(f"[watcher] Hot-folder actif : {self._dir}")

    def stop(self) -> None:
        """Stop."""
        self._running = False

    def _loop(self) -> None:
        """Loop."""
        while self._running:
            try:
                self._scan()
            except Exception as e:
                logger.debug(f"[watcher] scan: {e}")
            time.sleep(self.POLL_INTERVAL)

    def _scan(self) -> None:
        """Scan."""
        if not self._dir.exists():
            return
        current = {f.name for f in self._dir.iterdir() if f.suffix.lower() in self.SUPPORTED_EXT}
        new_files = current - self._seen
        for fname in sorted(new_files):
            fpath = self._dir / fname
            # Attendre que le fichier soit stable (copie en cours)
            try:
                s1 = fpath.stat().st_size
                time.sleep(0.5)
                s2 = fpath.stat().st_size
                if s1 != s2:
                    continue  # encore en cours de copie
            except Exception:
                continue

            self._seen.add(fname)
            logger.info(f"[watcher] Nouveau fichier détecté : {fname}")
            self._log_fn(f"[dim]📂 Hot-folder : [bold]{fname}[/bold] détecté → ingestion TRUSTED…[/dim]")

            # Lancer l'ingestion dans l'event loop de la TUI
            rag_engine = self._getter() if self._getter else None
            if rag_engine:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            hot_ingest_file(fpath, rag_engine, log_fn=self._log_fn, provenance="hot_folder"),
                            loop,
                        )
                    else:
                        asyncio.run(hot_ingest_file(fpath, rag_engine, log_fn=self._log_fn, provenance="hot_folder"))
                except Exception as e:
                    logger.warning(f"[watcher] ingestion {fname}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton watcher — accessible depuis Nokido.py on_mount
# ─────────────────────────────────────────────────────────────────────────────

_watcher: Optional[HotFolderWatcher] = None


def get_watcher(
    rag_engine_getter: Optional[Callable] = None,
    log_fn: Optional[Callable] = None,
    rag_dir: Path = _RAG_DIR,
) -> HotFolderWatcher:
    """Retourne le watcher singleton, le crée si nécessaire."""
    global _watcher
    if _watcher is None:
        _watcher = HotFolderWatcher(
            rag_dir=rag_dir,
            rag_engine_getter=rag_engine_getter,
            log_fn=log_fn,
        )
    return _watcher
