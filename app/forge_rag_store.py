"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_rag_store
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_rag_store.py — Pipeline PDF→Markdown (Marker) + connecteurs vectoriels.

Composants :
  1. MarkerConverter   : PDF → Markdown structuré (tableaux, headers, code)
  2. MarkdownChunker   : Split par headers markdown (## / ###)
  3. QdrantStore        : Connecteur Qdrant (local Docker ou cloud)
  4. migrate_to_qdrant : Migre le RAG mémoire vers Qdrant

Installation :
  pip install marker-pdf --break-system-packages    # PDF→Markdown
  pip install qdrant-client --break-system-packages  # Qdrant (optionnel, pour plus tard)

Le RAG en mémoire reste le défaut. Qdrant est préparé pour migration future.
"""

import re
import logging
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# 1. MARKER — PDF → Markdown structuré
# =============================================================================


class MarkerConverter:
    """
    Convertit les PDFs en Markdown propre via Marker.
    Fallback sur pdfplumber si Marker n'est pas installé.
    """

    _marker_available: Optional[bool] = None

    @classmethod
    def is_available(cls) -> bool:
        """Is available.

        Args:
            cls: Description.
        """
        if cls._marker_available is None:
            try:
                from marker.converters.pdf import PdfConverter

                cls._marker_available = True
            except ImportError:
                cls._marker_available = False
        return cls._marker_available

    @classmethod
    def convert(cls, pdf_path: Path) -> Tuple[str, dict]:
        """
        Convertit un PDF en Markdown.
        Retourne (markdown_text, metadata).
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            return "", {"error": "fichier introuvable"}

        # ── Essai 1 : Marker (meilleure qualité) ─────────────────────────
        if cls.is_available():
            try:
                return cls._convert_marker(pdf_path)
            except Exception as e:
                logger.warning(f"[Marker] Fallback pour {pdf_path.name}: {e}")

        # ── Essai 2 : pdfplumber (tableaux) ──────────────────────────────
        try:
            return cls._convert_pdfplumber(pdf_path)
        except Exception as e:
            logger.debug(f"[pdfplumber] {pdf_path.name}: {e}")

        return "", {"error": "aucun backend PDF disponible"}

    @classmethod
    def _convert_marker(cls, path: Path) -> Tuple[str, dict]:
        """Conversion via Marker — meilleure qualité pour tableaux et structure."""
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(str(path))
        md = rendered.markdown if hasattr(rendered, "markdown") else str(rendered)

        # Nettoyage post-Marker
        md = cls._clean_markdown(md, path.stem)
        meta = {
            "backend": "marker",
            "pages": md.count("\n---\n") + 1,
            "chars": len(md),
        }
        logger.info(f"[Marker] {path.name} → {len(md):,} chars markdown")
        return md, meta

    @classmethod
    def _convert_pdfplumber(cls, path: Path) -> Tuple[str, dict]:
        """Conversion via pdfplumber avec extraction tableaux."""
        import pdfplumber

        parts = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_md = []
                # Texte. x_tolerance MESURE (owner 2026-07-25) et non laisse au defaut :
                # sur un PDF LaTeX d'arxiv, `extract_text()` sans tolerance (defaut 3)
                # fusionne les mots -- « Memoryistheprocessofencoding ». Mesure sur
                # arxiv 2504.15965, 4 pages :
                #     defaut(3) : 1447 mots, 120 colles (8,29 %)
                #     x_tol=2.0 : 2608 mots,   2 colles
                #     x_tol=1.5 : 2620 mots,   0 colle   <- retenu (haut du plateau)
                #     x_tol=1.0/0.5 : identiques a 1.5 (aucun gain, donc pas plus bas)
                # Le defaut perdait 45 % des mots pour le lexical : « large language
                # model » est introuvable en BM25 dans « Largelanguagemodel ». Le nombre
                # de miettes (mots d'une lettre = sur-segmentation) ne bouge pas entre
                # 2.0 et 0.5, donc 1.5 ne coute rien. Fallback si la version de
                # pdfplumber ignore le parametre.
                try:
                    text = page.extract_text(x_tolerance=1.5) or ""
                except TypeError:
                    text = page.extract_text() or ""
                if text.strip():
                    page_md.append(text.strip())
                # Tableaux → markdown
                try:
                    for tbl in page.extract_tables() or []:
                        if not tbl or not tbl[0]:
                            continue
                        # Header
                        header = "| " + " | ".join(str(c or "").strip() for c in tbl[0]) + " |"
                        sep = "| " + " | ".join("---" for _ in tbl[0]) + " |"
                        rows = ["| " + " | ".join(str(c or "").strip() for c in row) + " |" for row in tbl[1:] if row]
                        page_md.append(f"\n{header}\n{sep}\n" + "\n".join(rows))
                except Exception:
                    pass
                if page_md:
                    parts.append(f"<!-- page {i + 1} -->\n" + "\n".join(page_md))

        md = "\n\n".join(parts)
        md = cls._clean_markdown(md, path.stem)
        return md, {"backend": "pdfplumber", "pages": len(parts), "chars": len(md)}

    @staticmethod
    def _clean_markdown(md: str, doc_name: str = "") -> str:
        """Nettoyage post-conversion : headers/footers répétitifs, artefacts."""
        # Supprimer les en-têtes/pieds de page répétitifs
        lines = md.split("\n")
        if len(lines) > 20:
            # Détecter les lignes qui apparaissent > 3 fois (probablement header/footer)
            from collections import Counter

            counts = Counter(l.strip() for l in lines if len(l.strip()) > 5)
            repeated = {l for l, c in counts.items() if c >= 4}
            if repeated:
                lines = [l for l in lines if l.strip() not in repeated]
                logger.debug(f"[clean] Supprimé {len(repeated)} lignes répétitives")

        md = "\n".join(lines)
        # Supprimer les artefacts OCR courants
        md = re.sub(r"\[p\.\d+\]\s*", "", md)
        md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
        md = re.sub(r"\n{4,}", "\n\n", md)
        # Ajouter un titre si absent
        if not md.strip().startswith("#"):
            md = f"# {doc_name}\n\n{md}"
        return md.strip()


# =============================================================================
# 2. MARKDOWN CHUNKER — Split par headers
# =============================================================================


class MarkdownChunker:
    """
    Découpe du Markdown par headers (## / ###) avec overlap.
    Inspiré du MarkdownHeaderTextSplitter de LangChain.
    """

    @staticmethod
    def chunk(md: str, max_chunk_chars: int = 2000, overlap_chars: int = 200) -> List[Dict]:
        """
        Split le markdown par sections (headers).
        Chaque chunk contient : text, header_path, level.
        """
        chunks = []
        current_headers = {}  # level → header text
        current_text = []
        current_len = 0

        for line in md.split("\n"):
            # Détecter les headers
            m = re.match(r"^(#{1,4})\s+(.+)", line)
            if m:
                # Flush le chunk courant
                if current_text:
                    chunks.append(
                        {
                            "text": "\n".join(current_text),
                            "headers": dict(current_headers),
                            "header_path": " > ".join(
                                current_headers.get(i, "")
                                for i in sorted(current_headers.keys())
                                if current_headers.get(i)
                            ),
                        }
                    )
                    # Overlap : garder les dernières lignes
                    if overlap_chars > 0:
                        overlap_lines = []
                        olen = 0
                        for ol in reversed(current_text):
                            if olen + len(ol) > overlap_chars:
                                break
                            overlap_lines.insert(0, ol)
                            olen += len(ol)
                        current_text = overlap_lines
                        current_len = olen
                    else:
                        current_text = []
                        current_len = 0

                level = len(m.group(1))
                header = m.group(2).strip()
                current_headers[level] = header
                # Nettoyer les sous-niveaux
                for l in list(current_headers.keys()):
                    if l > level:
                        del current_headers[l]
                current_text.append(line)
                current_len += len(line)
                continue

            # Texte normal — accumuler
            current_text.append(line)
            current_len += len(line)

            # Chunk trop long → split
            if current_len >= max_chunk_chars:
                chunks.append(
                    {
                        "text": "\n".join(current_text),
                        "headers": dict(current_headers),
                        "header_path": " > ".join(
                            current_headers.get(i, "") for i in sorted(current_headers.keys()) if current_headers.get(i)
                        ),
                    }
                )
                current_text = current_text[-3:]  # overlap 3 lignes
                current_len = sum(len(l) for l in current_text)

        # Dernier chunk
        if current_text:
            chunks.append(
                {
                    "text": "\n".join(current_text),
                    "headers": dict(current_headers),
                    "header_path": " > ".join(
                        current_headers.get(i, "") for i in sorted(current_headers.keys()) if current_headers.get(i)
                    ),
                }
            )

        return chunks


# =============================================================================
# 3. QDRANT STORE — Connecteur vectoriel (local Docker + cloud)
# =============================================================================


@dataclass
class QdrantConfig:
    """Configuration Qdrant."""

    mode: str = "local"  # "local" | "cloud" | "memory" | "embedded"
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: str = ""  # pour Qdrant Cloud
    cloud_url: str = ""  # ex: "https://xxx.qdrant.io"
    # mode embedded (blueprint SSoT RAG 2026, COMMUNICATIONS.md 2026-07-06) :
    # moteur Rust in-process via PyO3, JAMAIS de conteneur Docker pour le RAG
    # local. ATTENTION : verrou mono-process sur le storage -> à héberger dans
    # UN process dédié (sidecar), pas dans le hub (GIL + partage impossible).
    path: str = ""  # ex: "RAG/qdrant_storage" (embedded uniquement)
    collection: str = "laforge"
    vector_size: int = 1024  # MiniLM-L6-v2 = 384, BGE-M3 = 1024
    distance: str = "Cosine"
    on_disk: bool = True  # stocker les vecteurs sur disque (économie RAM)


class QdrantStore:
    """
    Connecteur Qdrant avec support :
      - local Docker (port 6333)
      - Qdrant Cloud (API key + URL)
      - mode mémoire (tests)
    Prêt pour migration future depuis le RAG en mémoire.
    """

    def __init__(self, config: QdrantConfig = None) -> None:
        """Init.

        Args:
            config: Description.
        """
        self.config = config or QdrantConfig()
        self._client = None
        self._available = None

    @property
    def available(self) -> bool:
        """Available."""
        if self._available is None:
            try:
                from qdrant_client import QdrantClient

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def connect(self) -> bool:
        """Connexion au serveur Qdrant."""
        if not self.available:
            logger.info("[Qdrant] qdrant-client non installé")
            return False
        try:
            from qdrant_client import QdrantClient

            cfg = self.config

            if cfg.mode == "cloud" and cfg.cloud_url:
                self._client = QdrantClient(
                    url=cfg.cloud_url,
                    api_key=cfg.api_key,
                    timeout=10,
                )
            elif cfg.mode == "embedded" and cfg.path:
                # Embedded PyO3 : storage local, verrou mono-process (sidecar only)
                self._client = QdrantClient(path=cfg.path)
            elif cfg.mode == "memory":
                self._client = QdrantClient(location=":memory:")
            else:
                self._client = QdrantClient(
                    host=cfg.host,
                    port=cfg.port,
                    grpc_port=cfg.grpc_port,
                    timeout=5,
                )

            # Test connexion
            self._client.get_collections()
            logger.info(f"[Qdrant] Connecté ({cfg.mode} {cfg.host}:{cfg.port})")
            return True
        except Exception as e:
            logger.warning(f"[Qdrant] Connexion échouée: {e}")
            self._client = None
            return False

    def ensure_collection(self) -> bool:
        """Crée la collection si elle n'existe pas."""
        if not self._client:
            return False
        try:
            from qdrant_client.models import Distance, VectorParams

            cfg = self.config
            collections = [c.name for c in self._client.get_collections().collections]
            if cfg.collection not in collections:
                self._client.create_collection(
                    collection_name=cfg.collection,
                    vectors_config=VectorParams(
                        size=cfg.vector_size,
                        distance=Distance.COSINE if cfg.distance == "Cosine" else Distance.DOT,
                        on_disk=cfg.on_disk,
                    ),
                )
                logger.info(f"[Qdrant] Collection '{cfg.collection}' créée (dim={cfg.vector_size})")
            return True
        except Exception as e:
            logger.warning(f"[Qdrant] ensure_collection: {e}")
            return False

    def _notify_brain(self, n_points: int):
        """Notification ZMQ pour brain_worker:5557 (job_b46f349e)."""
        try:
            import zmq

            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.PUSH)
            sock.setsockopt(zmq.LINGER, 500)
            sock.connect("tcp://127.0.0.1:5557")
            msg = {"event": "rag_upsert", "collection": self.config.collection, "count": n_points, "ts": time.time()}
            sock.send_json(msg, zmq.NOBLOCK)
            logger.debug(f"[Qdrant] ZMQ notify brain_worker: {n_points} points")
        except Exception as e:
            logger.debug(f"[Qdrant] ZMQ notify failed: {e}")

    def upsert(self, chunks: List[Dict]) -> int:
        """Insère des chunks avec leurs embeddings."""
        if not self._client:
            return 0
        try:
            from qdrant_client.models import PointStruct

            points = []
            for i, chunk in enumerate(chunks):
                emb = chunk.get("embedding")
                if emb is None:
                    continue
                pid = hashlib.md5(chunk.get("text", "").encode()).hexdigest()
                points.append(
                    PointStruct(
                        id=pid,
                        vector=emb,
                        payload={
                            "text": chunk.get("text", ""),
                            "source": chunk.get("source", ""),
                            "domain": chunk.get("domain", "general"),
                            "role_hint": chunk.get("role_hint", "chat"),
                            "content_type": chunk.get("content_type", "texte"),
                        },
                    )
                )
            if points:
                self._client.upsert(
                    collection_name=self.config.collection,
                    points=points,
                )
                self._notify_brain(len(points))
            return len(points)
        except Exception as e:
            logger.warning(f"[Qdrant] upsert: {e}")
            return 0

    def search(self, query_vector: list, k: int = 5, filters: dict = None) -> List[Dict]:
        """Recherche vectorielle."""
        if not self._client:
            return []
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            _filter = None
            if filters:
                conditions = []
                for key, val in filters.items():
                    conditions.append(FieldCondition(key=key, match=MatchValue(value=val)))
                _filter = Filter(must=conditions)

            results = self._client.search(
                collection_name=self.config.collection,
                query_vector=query_vector,
                limit=k,
                query_filter=_filter,
            )
            return [
                {
                    "content": r.payload.get("text", ""),
                    "source": r.payload.get("source", ""),
                    "score": r.score,
                    "domain": r.payload.get("domain", "general"),
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"[Qdrant] search: {e}")
            return []

    def count(self) -> int:
        """Count."""
        if not self._client:
            return 0
        try:
            info = self._client.get_collection(self.config.collection)
            return info.points_count
        except Exception:
            return 0

    def delete_collection(self) -> bool:
        """Delete collection."""
        if not self._client:
            return False
        try:
            self._client.delete_collection(self.config.collection)
            return True
        except Exception:
            return False


# =============================================================================
# 4. MIGRATION HELPER — RAG mémoire → Qdrant
# =============================================================================


async def migrate_to_qdrant(rag_engine, qdrant_config: QdrantConfig = None, log_fn=None) -> int:
    """
    Migre tous les chunks du RAG mémoire vers Qdrant.
    Non destructif — le RAG mémoire continue de fonctionner.
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    _log = log_fn or (lambda m: logger.info(m))
    store = QdrantStore(qdrant_config or QdrantConfig())
    if not store.connect():
        _log("[migration] Qdrant non disponible")
        return 0
    store.ensure_collection()

    chunks = rag_engine.chunks
    total = len(chunks)
    migrated = 0
    batch_size = 100

    _log(f"[migration] {total} chunks à migrer…")
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        n = store.upsert(batch)
        migrated += n
        if (i // batch_size) % 5 == 0:
            _log(f"[migration] {migrated}/{total} …")

    _log(f"[migration] ✅ {migrated} chunks migrés vers Qdrant ({store.config.collection})")
    return migrated


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "MarkerConverter",
    "MarkdownChunker",
    "QdrantStore",
    "QdrantConfig",
    "migrate_to_qdrant",
]
