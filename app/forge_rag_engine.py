"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
from collections import OrderedDict

# Import oublie, mesure le 2026-09-08 : time.time() L2147.
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import aiohttp
import asyncio
import datetime as _dt
import hashlib
import json
import numpy as np
import re
import uuid

logger = __import__("logging").getLogger(__name__)

# BM25 backend availability flag — set par _build_bm25_index()
HAS_BM25: bool = False

# ── Backend NPU (optionnel, prioritaire sur Ollama HTTP) ──
# Singleton : ort.InferenceSession chargée une seule fois, ~0ms aux appels suivants
try:
    from nokido_agent.app.forge_npu_embedder import get_npu_embedder as _get_npu_emb

    _npu_embedder = _get_npu_emb()
    if _npu_embedder and _npu_embedder.available:
        logger.info(f"RAG: NPU embedder actif ({_npu_embedder.provider})")
    else:
        _npu_embedder = None
except Exception as _e:
    logger.debug(f"RAG: NPU embedder indisponible — {_e}")
    _npu_embedder = None

from pathlib import Path as _Path_lp

# Chemins calculés depuis __file__ — fiables même hors __main__
_APP_DIR = _Path_lp(__file__).resolve().parent  # …/LaForge/app/
_ROOT_DIR = _APP_DIR.parent  # …/LaForge/
_DATA_DIR = _ROOT_DIR / "data"
_LOGS_DIR = _ROOT_DIR / "logs"
_EMBEDDINGS_DB = _ROOT_DIR / "RAG" / "embeddings.db"

import sqlite3 as _sqlite3

# On définit le chemin par défaut s'il n'est pas déjà défini
if "_EMBEDDINGS_DB" not in globals() or _EMBEDDINGS_DB is None:
    _EMBEDDINGS_DB = _ROOT_DIR / "RAG" / "embeddings.db"

import struct as _struct


def _decode_embedding_blob(blob) -> list | None:
    """Décode un embedding depuis son format de stockage SQLite.

    Gère deux formats:
    - JSON bytes (starts with '[') → décodé comme liste Python
    - Raw float32 binary (brain_worker format) → struct.unpack en liste
    """
    if not blob:
        return None
    if isinstance(blob, (bytes, bytearray)):
        if blob[:1] == b"[":
            try:
                return json.loads(blob.decode("utf-8"))
            except Exception:
                return None
        # raw float32 binary
        n = len(blob) // 4
        if n == 0:
            return None
        return list(_struct.unpack(f"{n}f", blob[: n * 4]))
    # str fallback
    try:
        return json.loads(blob)
    except Exception:
        return None


def _db_connect(db_path: str | Path | None = None) -> "_sqlite3.Connection":
    """tablit une connexion SQLite en mode WAL pour le stockage RAG.

    Cette fonction ouvre (ou cre) une base de donnes SQLite situe
    ``db_path``. Si ``db_path`` vaut ``None``, le chemin par dfaut
    ``_EMBEDDINGS_DB`` (dfini ailleurs dans le module) est utilis.
    La connexion est configure en mode journal ``WAL`` avec une
    synchronisation ``NORMAL`` afin d'optimiser les performances en
    environnement concurrentiel.

    Args:
        db_path: Chemin vers le fichier SQLite. Si ``None``, utilise
            la constante globale ``_EMBEDDINGS_DB``.

    Returns:
        Une instance de :class:`sqlite3.Connection` prte  tre
        utilise, configure en mode WAL et avec ``synchronous=NORMAL``.
    """
    p = db_path or str(_EMBEDDINGS_DB)
    # NE PAS router par get_db ici (revert #8) : le chemin RAG est ULTRA-chaud,
    # l'overhead par appel (realpath V: + resolve_key lit Nokido.env + sqlcipher
    # check) ralentissait CHAQUE rag search (timeouts). L'audit DB read/write #8 doit
    # se faire au grain TOOL (1× par rag_search via l'ActorContext get_actor), PAS par
    # connexion. Raw sqlite rapide ici. (get_db reste instrumenté pour les autres appelants.)
    conn = _sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


import sys as _sys_f

try:
    from app.core.settings import get_settings as _forge_settings  # noqa: F401
except ImportError:

    def _forge_settings():  # type: ignore[misc]
        return None


class _SettingsProxy:
    """settingsproxy."""

    def __getattr__(self, k: int) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


def _get_rag_engine() -> object:
    """Récupère l'instance RAGEngine depuis __main__ (injection depuis Nokido.py)."""
    m = _sys_f.modules.get("__main__")
    return getattr(m, "rag_engine", None)


def _get_web_search() -> bool:
    """Récupère la fonction web_search depuis __main__."""
    m = _sys_f.modules.get("__main__")
    return getattr(m, "_web_search_fn", None) or getattr(m, "web_search", None)


# ── Dépendances manquantes après shredder ───────────────────────────────────────

# Couches mémoire avec décroissance exponentielle (lambda = taux d’oubli/jour)
MEMORY_LAYERS: dict = {
    "core": {"lambda": 0.001},  # connaissances fondamentales, quasi-permanentes
    "session": {"lambda": 0.1},  # contexte de session courante
    "disco": {"lambda": 0.05},  # acquis via @disco, non vérifié
    "verified": {"lambda": 0.005},  # vérifié par usage répété, très stable
}

# Domaines de compétences reconnus pour le scoring RAG
SKILL_DOMAINS: frozenset = frozenset(
    [
        "reseau",
        "securite",
        "devops",
        "python",
        "ia",
        "systeme",
        "docker",
        "kubernetes",
        "ansible",
        "terraform",
        "git",
        "linux",
        "windows",
        "ssh",
        "firewall",
        "sql",
        "api",
    ]
)

# Flag web search (récupéré dynamiquement)
try:
    from nokido_agent.app.forge_web import web_search as _web_search_fn

    HAS_WEB_SEARCH = True
except ImportError:
    HAS_WEB_SEARCH = False
    """Web search fn."""

    async def _web_search_fn(*a, **kw) -> list:
        """web search fn."""
        return []  # type: ignore


# Flag skilltree (skilltree.py optionnel)
try:
    from nokido_agent.app.skilltree import detect_skills as detect_skill_keywords

    HAS_SKILLTREE = True
except ImportError:
    HAS_SKILLTREE = False
    """Detect skill keywords.

    Args:
        text: Description.
    """

    def detect_skill_keywords(text: str) -> list:
        """Detect skill keywords."""
        return []


# rag_engine : proxy dynamique vers l'instance dans __main__
# Utilisé par AgenticEngine — se résout au moment de l’appel
class _RAGEngineProxy:
    """Proxy transparent vers rag_engine dans __main__."""

    """Bool."""

    def __bool__(self) -> object:
        """bool  ."""
        return _get_rag_engine() is not None

    """Getattr.

    Args:
        k: Description.
    """

    def __getattr__(self, k: int) -> object:
        """getattr  ."""
        return getattr(_get_rag_engine(), k)


rag_engine = _RAGEngineProxy()


class RAGEngine:
    """Moteur de recherche augmentée (RAG) avec FAISS et BM25."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        # rag_dir : absolu sous _DATA_DIR (plus jamais de chemin relatif ./)
        """Init."""
        self.db_path = db_path
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        settings = _ac.settings
        # Robustesse PROCESS STANDALONE (script/run_job, ex reindex_v15) : settings peut être None
        # (singleton non initialisé hors hub) -> fallback rag_dir au lieu de crasher (AttributeError).
        _rd_val = getattr(settings, "rag_dir", None) if settings is not None else None
        _rd = Path(_rd_val) if _rd_val else (_DATA_DIR / "rag_files")
        if not _rd.is_absolute():
            _rd = _DATA_DIR / _rd
        self.rag_dir = _rd
        self.rag_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None
        self._sem: Optional[asyncio.Semaphore] = None
        # 3.14t free-threaded safety: list.append + slice rebind are NOT atomic
        # without the GIL. All chunks mutations must hold _chunks_lock.
        import threading as _threading

        self._chunks_lock = _threading.RLock()
        self.chunks: List[Dict] = []
        self.emb_file = self.rag_dir / "embeddings.json"
        self.indexed_file = self.rag_dir / "indexed_files.json"
        self.indexed = self._load_json(self.indexed_file, {})
        self.emb_cache = OrderedDict()
        self.expected_dim: Optional[int] = None
        self.faiss_index = None
        self.bm25_index = None
        self.session_ctxs: Dict[str, Any] = {}
        self._load_embeddings()

    def _get_session(self) -> aiohttp.ClientSession:
        """Get session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                force_close=True,  # pas de keep-alive → jamais de socket périmé
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=120, connect=10)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self._session

    def _get_sem(self) -> asyncio.Semaphore:
        """Get sem."""
        from nokido_agent.app.forge_app_context import get_settings as _gs

        settings = _gs()
        if self._sem is None:
            self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)
        return self._sem

    def _load_json(self, path: Path, default: object) -> None:
        """Load json.

        Args:
            path: Description.
            default: Description.
        """
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Erreur chargement {path}: {e}")
        return default

    def _save_json(self, path: Path, data: dict) -> None:
        """Save json.

        Args:
            path: Description.
            data: Description.
        """
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde {path}: {e}")

    def file_hash(self, path: Path) -> str:
        """File hash.

        Args:
            path: Description.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def make_chunk_id(text: str, source: str, ring_label: str = "") -> str:
        """
        P2 CRDT-lite : chunk_id déterministe basé sur le contenu.
        Propriétés :
          - Même texte + même source + même ring → même ID (pas de doublon)
          - Texte différent → ID différent (pas de collision)
          - Indépendant du timestamp → ID stable entre sessions
        Format : sha256(source|ring|text)[:16]
        """
        key = f"{source}|{ring_label}|{text.strip()}"
        return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]

    async def index_pending(self) -> None:
        """
        Indexe les fichiers nouveaux/modifiés dans rag_dir.
        Retire automatiquement les chunks des fichiers supprimés.
        """
        _SUPPORTED_EXT = (".txt", ".pdf", ".md")
        existing = {f.name for f in self.rag_dir.iterdir() if f.suffix.lower() in _SUPPORTED_EXT and f.is_file()}

        # ── Retirer les chunks des fichiers qui n'existent plus ────────────
        removed = [name for name in list(self.indexed) if name not in existing]
        if removed:
            with self._chunks_lock:
                before = len(self.chunks)
                self.chunks = [c for c in self.chunks if c.get("source") not in removed]
            for name in removed:
                del self.indexed[name]
            logger.info(f"RAG : {len(removed)} fichier(s) supprimé(s), {before - len(self.chunks)} chunks retirés")
            self._save_embeddings()
            self.faiss_index = self.bm25_index = None

        # ── Indexer les fichiers nouveaux ou modifiés ──────────────────────
        todo = []
        for name in existing:
            f = self.rag_dir / name
            fhash = self.file_hash(f)
            if self.indexed.get(name) != fhash:
                todo.append((name, f, fhash))
        if not todo:
            return
        results = await asyncio.gather(*[self.add_document(fp) for _, fp, _ in todo], return_exceptions=True)
        for (name, _, fhash), res in zip(todo, results):
            if res is True:
                self.indexed[name] = fhash
        self._save_json(self.indexed_file, self.indexed)

    _DOMAIN_MARKERS = {
        "reseau": [
            "ssh",
            "snmp",
            "vlan",
            "routeur",
            "switch",
            "arp",
            "tcp",
            "udp",
            "subnet",
            "gateway",
            "firewall",
            "bgp",
            "ospf",
            "nat",
            "cisco",
            "juniper",
            "mikrotik",
            "aruba",
            "fortinet",
            "interface",
            "netmask",
            "dhcp",
            "dns",
            "ping",
            "traceroute",
        ],
        "securite": [
            "ids",
            "ips",
            "cve",
            "exploit",
            "vuln",
            "brute.force",
            "intrusion",
            "certificat",
            "ssl",
            "tls",
            "chiffr",
            "auth",
            "permission",
            "sudo",
            "privilege",
            "pentest",
            "nmap",
            "port",
            "audit",
            "acl",
        ],
        "devops": [
            "docker",
            "kubernetes",
            "k8s",
            "helm",
            "ci/cd",
            "pipeline",
            "deploy",
            "build",
            "test",
            "lint",
            "github",
            "gitlab",
            "jenkins",
            "ansible",
            "terraform",
            "nginx",
            "systemctl",
            "service",
            "compose",
        ],
        "code": [
            "def ",
            "class ",
            "import ",
            "function",
            "async",
            "await",
            "return",
            "exception",
            "stack",
            "debug",
            "bug",
            "fix",
            "refactor",
            "pattern",
            "algorithme",
            "complexité",
            "variable",
            "boucle",
            "condition",
        ],
        "ia": [
            "llm",
            "modèle",
            "embedding",
            "rag",
            "faiss",
            "bm25",
            "ollama",
            "prompt",
            "token",
            "contexte",
            "inference",
            "quantization",
            "fine",
            "agent",
            "orchestrat",
            "neural",
            "transformer",
            "attention",
        ],
        "systeme": [
            "linux",
            "debian",
            "ubuntu",
            "kernel",
            "process",
            "cpu",
            "ram",
            "disk",
            "mount",
            "cron",
            "systemd",
            "journal",
            "proc",
            "fd",
            "socket",
            "inode",
            "chmod",
            "chown",
            "partition",
            "swap",
            "ulimit",
        ],
    }
    _ROLE_HINTS = {
        "action": [
            "commande",
            "exécute",
            "lance",
            "installe",
            "configure",
            "redémarre",
            "arrête",
            "démarre",
            "copie",
            "supprime",
            "sudo",
            "apt",
            "systemctl",
            "docker",
            "kubectl",
            "run",
            "exec",
            "kill",
            "start",
            "stop",
        ],
        "rag": [
            "documentation",
            "manuel",
            "guide",
            "spec",
            "référence",
            "explique",
            "définition",
            "rfc",
            "standard",
            "protocole",
            "architecture",
            "schéma",
            "tutoriel",
            "exemple",
            "comment fonctionne",
        ],
        "chat": [
            "question",
            "pourquoi",
            "comment",
            "aide",
            "conseil",
            "recommande",
            "suggestion",
            "avis",
            "penses-tu",
            "que fais",
        ],
    }

    def _detect_meta(self, text: str, source: str) -> dict:
        """Detect meta.

        Args:
            text: Description.
            source: Description.
        """
        tl = text.lower()
        sl = source.lower()
        dom_scores = {d: sum(1 for m in ms if m in tl or m in sl) for d, ms in self._DOMAIN_MARKERS.items()}
        best_dom = max(dom_scores, key=lambda d: dom_scores[d])
        if dom_scores[best_dom] == 0:
            best_dom = "general"
        ct = "texte"
        if "def " in text or "class " in text:
            ct = "code"
        elif any(w in tl for w in ["[p.", "[page", "[section"]):
            ct = "document"
        elif "session:" in sl or "exchange" in sl:
            ct = "conversation"
        elif "doc:" in sl or "source:" in sl:
            ct = "documentation"
        role_scores = {r: sum(1 for m in ms if m in tl) for r, ms in self._ROLE_HINTS.items()}
        best_role = max(role_scores, key=lambda r: role_scores[r])
        if role_scores[best_role] == 0:
            best_role = "chat"
        return {"domain": best_dom, "content_type": ct, "role_hint": best_role}

    def chunk_text(self, text: str, source: str, chunk_size: int = 120) -> List[Dict]:
        """Découpe + détecte automatiquement domain/content_type/role_hint.
        from forge_app_context import app_ctx as _actx; _ac = _actx()
        settings = _ac.settings
        chunk_size : max mots par chunk. 120 mots ≈ 600 chars, optimal cosine.
        """
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = []
        current_len = 0
        for sent in sentences:
            words = sent.split()
            wlen = len(words)
            if current_len + wlen > chunk_size and current:
                ctv = " ".join(current)
                meta = self._detect_meta(ctv, source)
                chunks.append({"id": self.make_chunk_id(ctv, source), "source": source, "text": ctv, **meta})
                overlap = current[-settings.chunk_overlap_words :] if settings.chunk_overlap_words else []
                current = overlap
                current_len = len(overlap)
            current.extend(words)
            current_len += wlen
        if current:
            ctv = " ".join(current)
            meta = self._detect_meta(ctv, source)
            chunks.append({"id": self.make_chunk_id(ctv, source), "source": source, "text": ctv, **meta})
        seen = set()
        unique = []
        for c in chunks:
            h = hashlib.md5(c["text"].encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(c)
        return unique

    async def get_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Get embeddings.

        Args:
            texts: Description.
        """
        from nokido_agent.app.forge_app_context import get_settings as _gs

        settings = _gs()
        if not texts:
            return []
        result = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []
        for i, t in enumerate(texts):
            key = hashlib.md5(t.encode()).hexdigest()
            if key in self.emb_cache:
                result[i] = self.emb_cache[key]
                self.emb_cache.move_to_end(key)
            else:
                uncached_indices.append(i)
                uncached_texts.append(t)
        if not uncached_texts:
            return result

        # ── NPU local (prioritaire) ──
        if _npu_embedder is not None:
            try:
                npu_embs = _npu_embedder.embed_batch(uncached_texts)
                for j, emb in enumerate(npu_embs):
                    if self.expected_dim is None:
                        self.expected_dim = len(emb)
                    key = hashlib.md5(uncached_texts[j].encode()).hexdigest()
                    self.emb_cache[key] = emb
                    if len(self.emb_cache) > 1000:
                        self.emb_cache.popitem(last=False)
                    result[uncached_indices[j]] = emb
                return result
            except Exception as e:
                logger.warning(f"NPU embeddings fallback → Ollama : {e}")

        # ── Ollama HTTP (fallback) ──
        session = self._get_session()
        sem = self._get_sem()
        async with sem:
            for i in range(0, len(uncached_texts), settings.embed_batch_size):
                batch = uncached_texts[i : i + settings.embed_batch_size]
                for _retry in range(2):
                    try:
                        async with session.post(
                            settings.ollama_embeddings_url,
                            json={"model": settings.ollama_embeddings_model, "input": batch},
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                embs = data.get("embeddings", [])
                                for j, emb in enumerate(embs):
                                    if self.expected_dim is None:
                                        self.expected_dim = len(emb)
                                    key = hashlib.md5(batch[j].encode()).hexdigest()
                                    self.emb_cache[key] = emb
                                    if len(self.emb_cache) > 1000:
                                        self.emb_cache.popitem(last=False)
                                    result[uncached_indices[i + j]] = emb
                            else:
                                logger.error(f"Erreur embeddings: HTTP {resp.status}")
                                return None
                            break  # succès
                    except Exception as e:
                        if _retry == 0 and "disconnected" in str(e).lower():
                            logger.debug(f"Embeddings reconnexion (retry) : {e}")
                            try:
                                await self._session.close()
                            except Exception:
                                pass
                            self._session = None
                            session = self._get_session()
                        else:
                            logger.error(f"Exception embeddings: {e}")
                            return None
        return result

    def _chunk_markdown(self, text: str, source: str) -> List[Dict]:
        """
        Découpe un Markdown par sections ## / ### avec overlap.
        Chaque section devient un chunk atomique, proprement délimité.
        Fallback sur chunk_text() si aucun header trouvé.
        """
        # Découpe aux headers niveau 2 et 3
        parts = re.split(r"(?m)^(?=#{1,3} )", text)
        raw_sections = [p.strip() for p in parts if len(p.strip()) > 60]

        if not raw_sections:
            return self.chunk_text(text, source)

        chunks: List[Dict] = []
        max_words = 350  # ~500 chars, optimal pour cosine search
        overlap_words = 30

        for section in raw_sections:
            words = section.split()
            if len(words) <= max_words:
                # Section courte → chunk unique
                meta = self._detect_meta(section, source)
                chunks.append(
                    {
                        "id": f"{source}_{len(chunks)}",
                        "source": source,
                        "text": section,
                        **meta,
                    }
                )
            else:
                # Section longue → sub-découpe avec overlap
                start = 0
                while start < len(words):
                    end = min(start + max_words, len(words))
                    part = " ".join(words[start:end])
                    meta = self._detect_meta(part, source)
                    chunks.append(
                        {
                            "id": f"{source}_{len(chunks)}",
                            "source": source,
                            "text": part,
                            **meta,
                        }
                    )
                    if end >= len(words):
                        break
                    start = end - overlap_words  # overlap

        # Dédoublonnage
        seen: set = set()
        unique: List[Dict] = []
        for c in chunks:
            h = hashlib.md5(c["text"].encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(c)
        logger.debug(f"[MD] {source}: {len(raw_sections)} sections → {len(unique)} chunks")
        return unique

    async def add_document(self, path: Path, delete_after: bool = False) -> bool:
        """
        Indexe un document dans le RAG.
        MD  : découpe par headers ## / ### (MarkdownChunker interne).
        PDF : pdfplumber (texte+tableaux) → pypdf, nettoyage OCR.
        TXT : multi-encoding utf-8/latin-1/cp1252.
        Chaque chunk préfixé du nom de source pour meilleure récupération.
        """
        ext = path.suffix.lower()
        text = ""
        if ext == ".pdf":
            text = self._extract_pdf_text(path)
            if not text:
                logger.error(f"PDF illisible ou vide : {path.name}")
                return False
        else:
            # .md, .txt — multi-encoding
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    with open(path, "r", encoding=enc) as f:
                        text = f.read()
                    break
                except UnicodeDecodeError:
                    continue
        if not text or len(text.strip()) < 30:
            return False

        # On utilise le chemin relatif pour la source (plus precis pour le GraphLinker)
        try:
            source = str(path.relative_to(_ROOT_DIR)).replace("\\", "/")
        except ValueError:
            source = path.name

        with self._chunks_lock:
            self.chunks = [c for c in self.chunks if c["source"] != source]

        # Routage du chunker selon le type de fichier
        if ext == ".md":
            chunks = self._chunk_markdown(text, source)
        else:
            chunks = self.chunk_text(text, source)
        # Préfixer chaque chunk avec le nom du fichier source → meilleure récupération
        for c in chunks:
            c["text"] = f"[Doc: {source}] " + c["text"]
        embs = await self.get_embeddings([c["text"] for c in chunks])
        if embs is None:
            return False
        for chunk, emb in zip(chunks, embs):
            chunk["embedding"] = emb
        self.chunks.extend(chunks)
        self._save_embeddings()
        self.faiss_index = self.bm25_index = None
        logger.info(f"Indexé {source} ({len(chunks)} chunks)")
        # CoVe : promotion asynchrone des nouveaux chunks (non-bloquant)
        import threading as _t

        def _promote(src: object = source) -> None:
            """Promote.

            Args:
                src: Description.
            """
            try:
                from nokido_agent.app.forge_rag_truth import batch_promote_draft as _bpd

                _bpd(validator_id="system:nr_runner", validator_ring=0, domain="", limit=len(chunks) + 10)
            except Exception:
                pass

        _t.Thread(target=_promote, daemon=True).start()
        if delete_after:
            try:
                path.unlink()
                logger.info(f"Source supprimée après ingestion : {source}")
            except Exception as _e:
                logger.warning(f"Impossible de supprimer {source} : {_e}")
        return True

    def _extract_pdf_text(self, path: Path) -> str:
        """PDF → Markdown structuré. Marker (best) → pdfplumber → pypdf."""
        import re as _re

        def _clean(t: object) -> object:
            """Clean.

            Args:
                t: Description.
            """
            t = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", t)
            t = _re.sub(r"[ \t]{3,}", "  ", t)
            t = _re.sub(r"\n{4,}", "\n\n", t)
            return t.strip()

        # Backend 0 : Marker (PDF → Markdown structuré)
        try:
            from nokido_agent.app.forge_rag_store import MarkerConverter

            if MarkerConverter.is_available():
                md, meta = MarkerConverter.convert(path)
                if md and len(md) > 100:
                    logger.info(f"[PDF] {path.name}: Marker → {len(md):,} chars md")
                    return md
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[PDF] Marker fallback {path.name}: {e}")

        # Backend 1 : pdfplumber
        try:
            import pdfplumber

            parts = []
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    pt = page.extract_text() or ""
                    # Extraire aussi les tableaux
                    try:
                        for tbl in page.extract_tables() or []:
                            for row in tbl:
                                pt += " | ".join(str(c or "").strip() for c in row if c) + "\n"
                    except Exception:
                        pass
                    if pt.strip():
                        parts.append(f"[p.{i + 1}] {_clean(pt)}")
            if parts:
                logger.debug(f"PDF {path.name}: {len(parts)} pages (pdfplumber)")
                return "\n\n".join(parts)
        except Exception as e:
            logger.debug(f"pdfplumber {path.name}: {e}")

        # Backend 2 : pypdf
        try:
            from pypdf import PdfReader

            parts = []
            for i, page in enumerate(PdfReader(str(path)).pages):
                pt = page.extract_text() or ""
                if pt.strip():
                    parts.append(f"[p.{i + 1}] {_clean(pt)}")
            if parts:
                logger.debug(f"PDF {path.name}: {len(parts)} pages (pypdf)")
                return "\n\n".join(parts)
        except Exception as e:
            logger.debug(f"pypdf {path.name}: {e}")

        return ""

    # ──────────────────────────────────────────────────────────────────────────
    # PRE-TRAITEMENT TEXTE WEB (disco / enrichissement)
    # ──────────────────────────────────────────────────────────────────────────

    _NOISE_PATTERNS = re.compile(
        r"(https?://\S+)"  # URLs
        r"|(\[\d+\])"  # références wiki [1]
        r"|(\|[^|\n]{0,40}){3,}"  # lignes de tableaux mal extraites
        r"|(^\s*[-•*]\s*$)",  # bullets vides
        re.MULTILINE,
    )

    def _clean_web_text(self, text: str) -> str:
        """
        Nettoyage léger du texte web avant ingestion :
        - Supprime les URLs nues, références [N], tableaux brisés
        - Déduplique les lignes consécutives identiques
        - Normalise les espaces / sauts de ligne excessifs
        """
        t = self._NOISE_PATTERNS.sub(" ", text)
        # Dédupliquer lignes consécutives identiques
        seen_lines: set = set()
        deduped = []
        for line in t.splitlines():
            stripped = line.strip()
            if stripped and stripped not in seen_lines:
                seen_lines.add(stripped)
                deduped.append(stripped)
        t = " ".join(deduped)
        # Normaliser espaces multiples
        t = re.sub(r"\s{3,}", "  ", t)
        return t.strip()

    async def ingest_web_content(
        self,
        session_name: str,
        content: str,
        skill: str = "",
        meta: Dict = None,
    ) -> int:
        """
        Pipeline complet pour ingérer du contenu web dans le RAG :
        1. Nettoyage (URLs, bruit, doublons)
        2. Chunking (chunk_text 120 mots + overlap)
        3. _detect_meta (domain, content_type, role_hint)
        4. get_embeddings (NPU → Ollama)
        from forge_app_context import app_ctx as _actx; _ac = _actx()
        session_name = _ac.session_name
        5. Persistance SQLite WAL immédiate

        Retourne le nombre de chunks ingérés.
        """
        if not content or len(content.strip()) < 50:
            return 0

        # ── 1. Nettoyage ──────────────────────────────────────────────────────
        clean = self._clean_web_text(content)
        if len(clean) < 50:
            return 0
        logger.debug(f"[disco] {session_name}: texte brut {len(content)} → nettoyé {len(clean)} chars")

        # ── 2. Chunking ───────────────────────────────────────────────────────
        source = f"disco:{session_name}"
        chunks = self.chunk_text(clean, source)  # 120 mots max, overlap
        if not chunks:
            return 0

        # ── 3. Enrichir avec meta disco ──────────────────────────────────────
        now_iso = _dt.datetime.utcnow().isoformat()
        base_meta = {
            "layer": "disco",
            "ingested_at": now_iso,
            "lambda_decay": 0.05,
            "unverified": True,
        }
        if skill:
            base_meta["skill"] = skill
        if meta:
            base_meta.update(meta)

        for c in chunks:
            c.update(base_meta)
            # Préfixer le texte pour le retrieval (cohérent avec add_document)
            c["text"] = f"[disco:{skill or session_name}] " + c["text"]

        # ── 4. Embeddings en batch ────────────────────────────────────────────
        texts = [c["text"] for c in chunks]
        try:
            embs = await self.get_embeddings(texts)
            if embs:
                for c, emb in zip(chunks, embs):
                    if emb is not None:
                        c["embedding"] = emb
        except Exception as e:
            logger.warning(f"[disco] embeddings: {e}")

        # Retirer les chunks sans embedding (Ollama hors ligne, etc.)
        valid = [c for c in chunks if c.get("embedding") is not None]
        if not valid:
            # Conserver quand même sans embedding (sera re-vectorisé au prochain boot)
            valid = chunks
            logger.warning(f"[disco] {session_name}: aucun embedding disponible — chunks stockés sans vecteur")

        # Retirer les chunks existants de la même source (mise à jour)
        with self._chunks_lock:
            self.chunks = [c for c in self.chunks if not c.get("source", "").startswith(f"disco:{session_name}")]
            self.chunks.extend(valid)

        # ── 5. Persistance immédiate ──────────────────────────────────────────
        self._save_embeddings()
        # Invalider les index pour forcer rebuild
        self.faiss_index = self.bm25_index = None

        logger.info(
            f"[disco] {session_name}: {len(valid)} chunks ingérés "
            f"(dim={self.expected_dim}, domain={valid[0].get('domain', '?') if valid else '?'})"
        )
        return len(valid)

    async def add_session_message(
        self,
        session_name: str,
        role: str,
        content: str,
        meta: Dict = None,
    ) -> None:
        """
        Ajoute un message de session ET le vectorise immédiatement.
        Pour du contenu web disco, préférer ingest_web_content().
        meta : dict optionnel (layer, ingested_at, lambda_decay, unverified, skill)
        """
        doc_id = f"session:{session_name}:{uuid.uuid4().hex[:8]}"
        text = f"[{role}] {content}"
        chunk = {
            "id": doc_id,
            "source": f"session:{session_name}",
            "text": text,
            "embedding": None,
        }
        if meta:
            chunk.update(meta)
        with self._chunks_lock:
            self.chunks.append(chunk)

        # Vectorisation asynchrone immédiate
        try:
            embs = await self.get_embeddings([text])
            if embs and embs[0] is not None:
                chunk["embedding"] = embs[0]
                if HAS_BM25 and self.bm25_index is not None:
                    self.build_bm25()
        except Exception as e:
            logger.debug(f"Embedding session non disponible : {e}")

        logger.debug(f"Session {session_name} [{role}] indexée ({len(content)} chars)")

    # Nombre max de chunks de session (échanges conversation) conservés
    _MAX_SESSION_CHUNKS = 500

    def _save_embeddings(self) -> None:
        """Sauvegarde les chunks RAG dans embeddings.db (table rag_chunks, WAL)."""
        conn = _db_connect(self.db_path)
        try:
            sess_c = [c for c in self.chunks if c.get("source", "").startswith("session:")]
            if len(sess_c) > self._MAX_SESSION_CHUNKS:
                sess_c = sess_c[-self._MAX_SESSION_CHUNKS :]
            other_c = [c for c in self.chunks if not c.get("source", "").startswith("session:")]
            to_save = other_c + sess_c

            # ── DELETE sélectif : préserve les chunks MCP/WMI ────────────────
            # Sources gérées par rag_engine (remplacées)
            _managed_sources = set(c.get("source", "") for c in to_save)
            # Préserve les chunks créés par MCP / agents (non gérés par rag_engine)
            _PROTECTED_PREFIXES = (
                "rag_",
                "decisions_",
                "architecture_",
                "wmi_",
                "config:",
                "bug_backlog",
                "nr_report:",
            )
            if _managed_sources:
                # Supprime uniquement les sources que rag_engine gère
                _placeholders = ",".join("?" * len(_managed_sources))
                conn.execute(f"DELETE FROM rag_chunks WHERE source IN ({_placeholders})", list(_managed_sources))
            else:
                # Fallback sûr : ne supprime que les sources non-protégées
                conn.execute(
                    "DELETE FROM rag_chunks WHERE source NOT LIKE 'rag_%' "
                    "AND source NOT LIKE 'decisions_%' "
                    "AND source NOT LIKE 'architecture_%' "
                    "AND source NOT LIKE 'wmi_%' "
                    "AND source NOT LIKE 'config:%' "
                    "AND source NOT LIKE 'nr_report:%'"
                )
            for c in to_save:
                emb = c.get("embedding")
                emb_blob = json.dumps(emb).encode() if emb else None
                # Qualification intrinsèque — chaque chunk porte sa confiance
                try:
                    from nokido_agent.app.forge_rag_qualify import qualify_chunk as _qc

                    _qmeta = _qc(
                        source=c.get("source", ""),
                        author=c.get("author", ""),
                        meta={
                            k: v
                            for k, v in c.items()
                            if k
                            in {
                                "layer",
                                "ingested_at",
                                "lambda_decay",
                                "unverified",
                                "ring",
                                "consensus_level",
                                "trust_score",
                                "mutable",
                                "verified_by",
                            }
                        },
                    )
                except Exception:
                    _qmeta = {k: v for k, v in c.items() if k in {"layer", "ingested_at", "lambda_decay", "unverified"}}
                # Ajoute version Nokido dans meta (traçabilité RAG versionnée)
                try:
                    from nokido_agent.app.forge_version import get as _fvg

                    _qmeta["nokido_version"] = _fvg()
                except Exception:
                    pass
                meta = json.dumps(_qmeta, ensure_ascii=False)
                conn.execute(
                    "INSERT OR REPLACE INTO rag_chunks "
                    "(id, text, source, domain, role_hint, embedding, meta, ingested_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        c.get("id") or self.make_chunk_id(c.get("text", ""), c.get("source", "")),
                        c.get("text", ""),
                        c.get("source", ""),
                        c.get("domain", "general"),
                        c.get("role_hint", "chat"),
                        emb_blob,
                        meta,
                        c.get("ingested_at", _dt.datetime.utcnow().isoformat()),
                    ),
                )
            conn.commit()
            logger.debug(f"RAG save: {len(to_save)} chunks -> SQLite WAL")
            # Notify brain_worker to embed chunks that have no embedding yet
            no_emb = [
                (c.get("id") or self.make_chunk_id(c.get("text", ""), c.get("source", "")), c.get("text", ""))
                for c in to_save
                if not c.get("embedding")
            ]
            if no_emb:
                self._notify_brain_embed(no_emb)
        except Exception as e:
            logger.error(f"RAG save SQLite: {e}")
        finally:
            conn.close()

    def _notify_brain_embed(self, id_text_pairs: list) -> None:
        """Soumet des chunks a l'embedding differe — en VERIFIANT qu'on est ecoute.

        L'ancienne version poussait en fire-and-forget sur :5557 et journalisait en
        `debug`, donc invisible. Mesure du 2026-08-05 : un PUSH ZMQ vers un port
        FERME est ACCEPTE sans exception — le `except` ne se declenchait jamais et la
        soumission paraissait partie. Le port est ferme depuis juin : ces chunks
        n'ont jamais ete embarques, et rien ne le disait.
        """
        try:
            from nokido_agent.app.forge_nudge_embed import nudge_embed

            r = nudge_embed(
                len(id_text_pairs), source="forge_rag_engine",
                payload={
                    "cmd": "submit",
                    "type": "embed",
                    "ids": [p[0] for p in id_text_pairs],
                    "texts": [p[1] for p in id_text_pairs],
                })
            if r.get("delivre"):
                logger.debug("[RAG] brain_worker notified: %d chunks", len(id_text_pairs))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[RAG] soumission a l'embedding differe IMPOSSIBLE (%s: %s) — %d chunk(s) "
                "| consequence: ils restent sans vecteur jusqu'au prochain drain",
                type(e).__name__, str(e)[:80], len(id_text_pairs))

    def _load_embeddings(self) -> None:
        """Charge les chunks RAG depuis embeddings.db (table rag_chunks, WAL)."""
        # 3.14t safety: full reload swap behind _chunks_lock to avoid readers
        # seeing a half-populated list (slice rebind not atomic without GIL).
        # -- 1. SQLite WAL (nouveau format) --
        try:
            import os as _os

            # DECIDER AVANT DE REQUETER (mesure 2026-08-25). Le sidecar vectoriel etant
            # actif, `emb` valait None pour les 1 328 780 lignes — et pourtant la colonne
            # `embedding` etait DEMANDEE quand meme : 7,36 Go de blobs traversaient le
            # `fetchall` pour etre jetes ligne par ligne. Avec le texte (2,63 Go) et
            # l'enveloppe des dicts (0,74 Go), cela explique le pic d'engagement mesure
            # sur le hub — 11,878 Go sur une machine qui en expose 23,67, et c'est
            # l'amplitude, pas la moyenne, qui declenche pagination et compression.
            # On ne demande donc PAS la colonne qu'on ne garde pas, et on parcourt un
            # CURSEUR au lieu de materialiser la table entiere d'un bloc.
            skip_emb = _os.environ.get("LAFORGE_VEC_SIDECAR_PORT") is not None
            conn = _db_connect()
            _dim_probe = None
            if skip_emb:
                # Sonde de dimension : on ne charge PAS les vecteurs en RAM, mais on
                # MESURE la dim sur un blob reel. La declarer en dur (1024) ferait
                # passer un corpus 768 pour compatible et casserait le dense EN SILENCE.
                try:
                    _probe_row = conn.execute(
                        "SELECT embedding FROM rag_chunks "
                        "WHERE embedding IS NOT NULL LIMIT 1"
                    ).fetchone()
                    if _probe_row and _probe_row[0] is not None:
                        _dim_probe = _decode_embedding_blob(_probe_row[0])
                except Exception as _pe:  # noqa: BLE001
                    logger.warning(
                        "RAG skip_emb: sonde de dimension IMPOSSIBLE (%s) — expected_dim "
                        "restera NON MESUREE, ce qui n'est pas la meme chose que mesuree a 0",
                        type(_pe).__name__)
            _cols = ("id, text, source, domain, role_hint, meta, quality_score" if skip_emb
                     else "id, text, source, domain, role_hint, embedding, meta, quality_score")
            # RESPECTER `active` (decision owner 2026-09-23, option 1). Seul
            # forge_epistemic_retrieve le filtrait : un chunk marque active=0 restait
            # trouvable, en dense comme en lexical (le lexical se rattache a
            # self.chunks via _lex_map et jette deja tout id absent). Filtrer ICI rend
            # les deux canaux coherents d'un seul point, et allege la RAM du hub.
            # La colonne est VERIFIEE : l'absente ne doit pas faire echouer le SELECT,
            # ce qui ferait basculer en silence vers les anciens formats.
            try:
                _a_col = any(r[1] == "active" for r in
                             conn.execute("PRAGMA table_info(rag_chunks)"))
            except Exception:  # noqa: BLE001
                _a_col = False
            if not _a_col:
                logger.warning("RAG: colonne `active` absente -> AUCUN filtre, "
                               "les chunks marques inactifs restent charges")
            _where = " WHERE (active IS NULL OR active = 1)" if _a_col else ""
            _cur = conn.execute(f"SELECT {_cols} FROM rag_chunks{_where}")
            # Un curseur ne dit pas d'avance s'il rendra des lignes : la vacuite se
            # CONSTATE apres le parcours (plus bas), elle ne se teste pas avant.
            if _cur is not None:
                with self._chunks_lock:
                    self.chunks = []
                    for _row in _cur:
                        if skip_emb:
                            (row_id, text, source, domain, role_hint,
                             meta_str, quality_score) = _row
                            emb = None
                        else:
                            (row_id, text, source, domain, role_hint,
                             emb_blob, meta_str, quality_score) = _row
                            emb = _decode_embedding_blob(emb_blob)
                        c = {
                            "id": row_id,
                            "text": text,
                            "source": source,
                            "domain": domain,
                            "role_hint": role_hint,
                            "embedding": emb,
                        }
                        if meta_str:
                            try:
                                c.update(json.loads(meta_str))
                            except Exception:
                                pass
                        if quality_score is not None:
                            c["quality_score"] = quality_score
                        self.chunks.append(c)
                    if self.chunks:
                        if self.chunks[0].get("embedding"):
                            self.expected_dim = len(self.chunks[0]["embedding"])
                        elif skip_emb:
                            if _dim_probe is not None and len(_dim_probe):
                                self.expected_dim = len(_dim_probe)
                            else:
                                logger.warning(
                                    "RAG skip_emb: aucun blob embedding lisible -> expected_dim=%s "
                                    "NON MESUREE (valeur par defaut) ; le dense peut etre incompatible",
                                    self.expected_dim,
                                )
                conn.close()
                if not self.chunks:
                    raise RuntimeError("rag_chunks vide -> essayer les formats anciens")
                logger.info(f"RAG: {len(self.chunks)} chunks dim={self.expected_dim} (SQLite WAL, skip_emb={skip_emb})")
                return
        except Exception as e:
            logger.debug(f"RAG load SQLite: {e}")

        # -- 2. Fallback : Arrow (ancien format, migration auto) --
        _ap = self.rag_dir / "embeddings.arrow"
        if _ap.exists():
            try:
                import pyarrow as pa, pyarrow.ipc as ipc

                with pa.OSFile(str(_ap), "rb") as f:
                    t = ipc.open_file(f).read_all()
                tx = t.column("text").to_pylist()
                sr = t.column("source").to_pylist()
                dm = t.column("domain").to_pylist()
                rh = t.column("role_hint").to_pylist()
                ids = t.column("id").to_pylist()
                mt = t.column("meta").to_pylist()
                em = t.column("embedding").to_pylist()
                with self._chunks_lock:
                    self.chunks = []
                    for i in range(len(tx)):
                        c = {
                            "id": ids[i],
                            "text": tx[i],
                            "source": sr[i],
                            "domain": dm[i],
                            "role_hint": rh[i],
                            "embedding": em[i],
                        }
                        if mt[i]:
                            try:
                                c.update(json.loads(mt[i]))
                            except Exception:
                                pass
                        self.chunks.append(c)
                if self.chunks:
                    self.expected_dim = len(self.chunks[0]["embedding"])
                    logger.info(f"RAG: {len(self.chunks)} chunks (Arrow -> SQLite migration)")
                    self._save_embeddings()
                return
            except Exception as e:
                logger.debug(f"Arrow load: {e}")

        # -- 3. Fallback : JSON (tres ancien format) --
        data = self._load_json(self.emb_file, {})
        chunks = data.get("chunks", [])
        if chunks and "embedding" in chunks[0]:
            self.expected_dim = len(chunks[0]["embedding"])
            with self._chunks_lock:
                self.chunks = chunks
            logger.info(f"RAG: {len(chunks)} chunks (JSON -> SQLite migration)")
            self._save_embeddings()

    def build_faiss(self) -> None:
        """Build faiss with disk persistence."""
        try:
            import faiss
        except ImportError:
            logger.warning("[RAG] faiss not available - FAISS index disabled")
            self.faiss_index = None
            return

        if not self.chunks:
            self.faiss_index = None
            return

        faiss_index_path = _ROOT_DIR / "RAG" / "faiss_index.bin"

        # Check if a recent index file exists
        if faiss_index_path.exists():
            try:
                mtime = faiss_index_path.stat().st_mtime
                if (_dt.datetime.now().timestamp() - mtime) < 86400:
                    logger.info(f"RAG: Loading FAISS index from {faiss_index_path}")
                    self.faiss_index = faiss.read_index(str(faiss_index_path))
                    # Validate index size
                    embs = np.array([c["embedding"] for c in self.chunks if c["embedding"] is not None]).astype(
                        "float32"
                    )
                    if self.faiss_index.ntotal == len(embs):
                        logger.info(f"RAG: FAISS index loaded successfully with {self.faiss_index.ntotal} vectors.")
                        return
                    else:
                        logger.warning("RAG: FAISS index size mismatch. Rebuilding.")
                else:
                    logger.info("RAG: FAISS index is older than 24 hours. Rebuilding.")
            except Exception as e:
                logger.error(f"RAG: Error loading FAISS index: {e}. Rebuilding.")

        # Build and save the index
        logger.info("RAG: Building new FAISS index.")
        embs = np.array([c["embedding"] for c in self.chunks if c["embedding"] is not None]).astype("float32")
        if len(embs) == 0:
            self.faiss_index = None
            return

        if self.expected_dim is None and len(embs) > 0:
            self.expected_dim = embs.shape[1]

        if self.expected_dim is None:
            logger.error("RAG: Cannot determine embedding dimension. Aborting FAISS index build.")
            self.faiss_index = None
            return

        index = faiss.IndexFlatIP(self.expected_dim)
        faiss.normalize_L2(embs)
        index.add(embs)

        try:
            faiss.write_index(index, str(faiss_index_path))
            logger.info(f"RAG: FAISS index saved to {faiss_index_path}")
            self.faiss_index = index
        except Exception as e:
            logger.error(f"RAG: Could not write FAISS index to {faiss_index_path}: {e}")
            self.faiss_index = None

    # ═══════════════ PIPELINE RAG AVANCÉ ═══════════════

    @staticmethod
    # ⚠️ GELE — CODE MORT, mesure du 2026-09-08. Ne pas croire cette methode
    # active : la fusion RRF qui tourne REELLEMENT est ecrite INLINE dans
    # `search()` (« RRF (Reciprocal Rank Fusion) », ~L1981-1992), avec un poids
    # lexical majore a 1.2 sur les requetes techniques. Deux implementations de
    # la meme idee, une vivante et une morte.
    #
    # PREUVE : `_rrf` apparait UNE seule fois dans 4356 fichiers de app/, tools/,
    # tests/, proxy_deno/ et config/ — sa propre definition. Aucun appelant,
    # aucun appel dynamique, aucune mention en configuration. Et sa signature ne
    # prend pas `self` alors qu'elle vit dans une classe : un `self._rrf(...)`
    # passerait l'instance en `rankings`. Elle est donc morte ET mal formee pour
    # etre appelee.
    #
    # NON SUPPRIMEE, deliberement (regle owner du 2026-09-03 : geler, jamais
    # enterrer — c'est le seul geste que la mesure suivante ne peut pas corriger).
    # DETTE NOMMEE : la fusion VIVANTE, qui decide de tout le classement du RAG,
    # n'a aujourd'hui aucun test. C'est elle qu'il faut couvrir, pas celle-ci.
    def _rrf(rankings: list, k: int = 60) -> object:
        """Rrf.

        Args:
            rankings: Description.
            k: Description.
        """
        scores = {}
        for ranking in rankings:
            for rank, (idx, _) in enumerate(ranking):
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    @staticmethod
    def _rerank(query: str, docs: list, top_n: int = 5) -> object:
        """Rerank cross-encoder (bge-reranker-v2-m3, :8100) + fallback lexical.

        Etage 1 : cross-encoder bge-reranker via llama-server :8100 (precision,
        bench mesure +0.10 R@1 / +0.06 NDCG@10). Etage 2 (fallback si le serveur
        est indisponible) : scoring lexical overlap + bigrammes.

        Args:
            query: requete utilisateur.
            docs: candidats, chacun avec 'content' (texte) et 'score' (dense).
            top_n: nombre de docs a retourner.
        """
        # --- Etage 1 : reranker cross-encoder ---
        try:
            import json as _j
            import urllib.request as _u

            _payload = _j.dumps(
                {
                    "model": "bge-reranker",
                    "query": query,
                    "documents": [(d.get("content", "") or "")[:512] for d in docs],
                }
            ).encode()
            _rq = _u.Request(
                "http://127.0.0.1:8100/v1/rerank",
                data=_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _u.urlopen(_rq, timeout=8) as _rp:
                _res = _j.loads(_rp.read()).get("results", [])
            if _res and len(_res) == len(docs):
                for _it in _res:
                    docs[_it["index"]]["rerank_score"] = _it.get("relevance_score", 0.0)
                docs.sort(key=lambda d: d.get("rerank_score", 0.0), reverse=True)
                return docs[:top_n]
        except Exception as _e:  # noqa: BLE001 - fallback lexical si reranker down
            # DECLARER, pas seulement subir. Le keeper sait ETEINDRE le reranker
            # (_piliers_on_demand) mais ne le rallumera JAMAIS sans intention posee :
            # sans cette ligne, :8100 s'eteint une fois et le RAG reste en lexical
            # pour toujours. C'est l'asymetrie declarant/lecteur payee sur
            # llama.wanted. Et `debug` masquait la perte de precision mesuree au
            # bench (-0.10 R@1, -0.06 NDCG@10) : on la DIT, throttlee par le
            # cooldown du declarant (1 warning / 300 s max), comme le dense muet.
            _pose = False
            try:
                import sys as _s

                _ad = str(_ROOT_DIR / "app")
                if _ad not in _s.path:
                    _s.path.insert(0, _ad)
                from nokido_agent.app.forge_embed_router import declare_wanted as _dw

                _pose = _dw("rerank.wanted",
                            motif=":8100 injoignable ; le RAG retombe en rerank LEXICAL")
            except Exception as _de:  # noqa: BLE001
                logger.warning("rerank: intention rerank.wanted NON posee (%r)", _de)
            if _pose:
                logger.warning(
                    "rerank cross-encoder INDISPO -> tentative fallback Cohere/Lexical (%s)", _e)
            else:
                logger.debug(f"rerank cross-encoder indispo, tentative fallback: {_e}")

        # --- Etage 1.5 : Fallback Cohere Cloud Reranker ---
        try:
            import os as _os
            import json as _j
            import urllib.request as _u
            _cohere_key = _os.environ.get("COHERE_API_KEY")
            if not _cohere_key:
                try:
                    from nokido_agent.app.forge_secrets import get_secret as _gs
                    _cohere_key = _gs("COHERE_API_KEY")
                except Exception:
                    pass
            if _cohere_key:
                _c_payload = _j.dumps(
                    {
                        "model": "rerank-v3.5",
                        "query": query,
                        "documents": [(d.get("content", "") or "")[:1000] for d in docs],
                        "top_n": top_n,
                    }
                ).encode()
                _c_rq = _u.Request(
                    "https://api.cohere.com/v2/rerank",
                    data=_c_payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {_cohere_key}",
                    },
                    method="POST",
                )
                with _u.urlopen(_c_rq, timeout=5) as _c_rp:
                    _c_res = _j.loads(_c_rp.read()).get("results", [])
                if _c_res:
                    for _it in _c_res:
                        docs[_it["index"]]["rerank_score"] = _it.get("relevance_score", 0.0)
                    docs.sort(key=lambda d: d.get("rerank_score", 0.0), reverse=True)
                    logger.info("rerank: fallback Cohere Cloud Reranker appliqué avec succès")
                    return docs[:top_n]
        except Exception as _ce:  # noqa: BLE001
            logger.debug("rerank Cohere Cloud indisponible: %s", _ce)

        # --- Etage 2 : fallback lexical (overlap + bigrammes) ---
        qw = set(w.lower() for w in query.split() if len(w) > 2)
        ql = query.lower()
        for d in docs:
            t = d.get("content", "")
            tw = set(w.lower() for w in t.split() if len(w) > 2)
            ov = len(qw & tw) / max(len(qw), 1)
            ex = min(
                sum(0.15 for bg in [ql[i : i + 15] for i in range(0, max(1, len(ql) - 14), 8)] if bg in t.lower()), 0.3
            )
            d["rerank_score"] = round(
                d.get("score", 0) * 0.5 + ov * 0.3 + ex - max(0, (len(t) - 2000) / 10000) * 0.1, 4
            )
        docs.sort(key=lambda d: d["rerank_score"], reverse=True)
        return docs[:top_n]

    @staticmethod
    def _compress_context(query: str, text: str, max_chars: int = 800) -> bool:
        """Compress context.

        Args:
            query: Description.
            text: Description.
            max_chars: Description.
        """
        if len(text) <= max_chars:
            return text
        qw = set(w.lower() for w in query.split() if len(w) > 2)
        sents = re.split(r"(?<=[.!?])\s+|\n+", text)
        scored = sorted(
            [
                (s.strip(), len(qw & set(w.lower() for w in s.split() if len(w) > 2)) / max(len(qw), 1))
                for s in sents
                if len(s.strip()) > 10
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        kept, total = [], 0
        for s, _ in scored:
            if total + len(s) > max_chars:
                break
            kept.append(s)
            total += len(s)
        orig = [s.strip() for s in sents if s.strip()]
        return " ".join(s for s in orig if s in kept) or text[:max_chars]

    @staticmethod
    def _grade_retrieval(query: str, docs: list, threshold: float = 0.15) -> object:
        """Grade retrieval.

        Args:
            query: Description.
            docs: Description.
            threshold: Description.
        """
        qw = set(w.lower() for w in query.split() if len(w) > 2)
        graded = []
        for d in docs:
            tw = set(w.lower() for w in d.get("content", "").split() if len(w) > 2)
            r = len(qw & tw) / max(len(qw), 1)
            d["retrieval_grade"] = round(r, 3)
            if r >= threshold:
                graded.append(d)
        if not graded:
            return [], False, "aucun chunk pertinent"
        return graded, True, "OK"

    @staticmethod
    def _grade_hallucination(response: str, docs: list) -> object:
        """Grade hallucination.

        Args:
            response: Description.
            docs: Description.
        """
        if not response or not docs:
            return False, 0.0, []
        cw = set()
        for d in docs:
            cw.update(w.lower() for w in d.get("content", "").split() if len(w) > 2)
        grounded, ungrounded = [], []
        for s in re.split(r"(?<=[.!?])\s+", response):
            if len(s.strip()) < 15:
                continue
            sw = set(w.lower() for w in s.split() if len(w) > 2)
            (grounded if len(sw & cw) / max(len(sw), 1) >= 0.2 else ungrounded).append(s)
        conf = len(grounded) / max(len(grounded) + len(ungrounded), 1)
        return conf >= 0.5, round(conf, 3), ungrounded

    @staticmethod
    def _grade_answer(query: str, response: str) -> object:
        """Grade answer.

        Args:
            query: Description.
            response: Description.
        """
        if not response:
            return False, 0.0, "réponse vide"
        qw = set(w.lower() for w in query.split() if len(w) > 2)
        rw = set(w.lower() for w in response.split() if len(w) > 2)
        cov = len(qw & rw) / max(len(qw), 1)
        evasion = any(k in response.lower() for k in ["je ne sais pas", "impossible de répondre", "aucune donnée"])
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        settings = _ac.settings
        score = cov * 0.6 + (0.3 if 50 < len(response) < 5000 else 0) + (0 if evasion else 0.1)
        useful = score >= 0.4 and not evasion
        sugg = None if useful else ("web_search" if evasion else "rewrite_query" if cov < 0.3 else "more_context")
        return useful, round(score, 3), sugg

    async def hyde_transform(self, query: str) -> object:
        """Hyde transform.

        Args:
            query: Description.
        """
        try:
            from nokido_agent.app.forge_ollama import ollama_stream

            reply = await ollama_stream(
                getattr(settings, "ollama_model_default", "") or "mistral:7b",
                [
                    {
                        "role": "user",
                        "content": f"Écris un court paragraphe technique (3-5 phrases) répondant à: {query}",
                    }
                ],
                lambda _: None,
                lambda: None,
            )
            if reply and len(reply) > 30:
                return reply[:500]
        except Exception:
            pass
        return query

    def ragas_evaluate(self, query: str, answer: str, docs: list) -> dict:
        """Ragas evaluate.

        Args:
            query: Description.
            answer: Description.
            docs: Description.
        """
        qw = set(w.lower() for w in query.split() if len(w) > 2)
        aw = set(w.lower() for w in answer.split() if len(w) > 2)
        ctx = " ".join(d.get("content", "") for d in docs).lower()
        cw = set(w for w in ctx.split() if len(w) > 2)
        cr = len(qw & cw) / max(len(qw), 1)
        ar = len(qw & aw) / max(len(qw), 1)
        fa = len(aw & cw) / max(len(aw), 1) if aw else 0
        cp = (
            sum(1 for d in docs if any(w in d.get("content", "").lower() for w in qw)) / max(len(docs), 1)
            if docs
            else 0
        )
        return {
            "context_relevancy": round(cr, 3),
            "answer_relevancy": round(ar, 3),
            "faithfulness": round(fa, 3),
            "context_precision": round(cp, 3),
            "overall": round((cr + ar + fa + cp) / 4, 3),
        }

    async def smart_search(
        self, query: str, k: int = None, use_hyde: object = True, max_retries: int = 2, **kwargs
    ) -> object:
        """Smart search.

        Args:
            query: Description.
            k: Description.
            use_hyde: Description.
            max_retries: Description.
        """
        _q = query
        if use_hyde and len(query.split()) >= 4:
            _q = await self.hyde_transform(query)
        for attempt in range(max_retries + 1):
            docs = await self.search(_q, k=k, **kwargs)
            graded, ok, reason = self._grade_retrieval(query, docs)
            if ok:
                return graded
            logger.info(f"[Grader1] retry {attempt}: {reason}")
            if attempt < max_retries:
                qw = set(w.lower() for w in query.split() if len(w) > 2)
                ac = " ".join(d.get("content", "") for d in docs).lower()
                missing = [w for w in qw if w not in ac]
                _q = (query + " " + " ".join(missing[:3])) if missing else f"documentation {query}"
        return docs

    async def graded_respond(self, query: str, response: str, docs: list) -> object:
        """Graded respond.

        Args:
            query: Description.
            response: Description.
            docs: Description.
        """
        info = {"hallucination_ok": True, "answer_ok": True, "action": None}
        ok, conf, ungrounded = self._grade_hallucination(response, docs)
        info["hallucination_confidence"] = conf
        if not ok and ungrounded:
            info["hallucination_ok"] = False
            grounded = [s for s in re.split(r"(?<=[.!?])\s+", response) if s.strip() not in ungrounded]
            if grounded:
                response = " ".join(grounded)
                info["action"] = "pruned"
        useful, ascore, sugg = self._grade_answer(query, response)
        info["answer_score"] = ascore
        if not useful:
            info["answer_ok"] = False
            info["suggestion"] = sugg
        return response, info

    def build_bm25(self) -> None:
        """Build bm25."""
        if not self.chunks:
            return
        texts = [c["text"] for c in self.chunks]
        corpus = [t.lower().split() for t in texts]
        global HAS_BM25
        try:
            from forge_bm25 import BM25  # Rust extension (10-50x faster)

            self.bm25_index = BM25(corpus)
            HAS_BM25 = True
            return
        except ImportError:
            pass
        try:
            from rank_bm25 import BM25Okapi  # Python fallback

            self.bm25_index = BM25Okapi(corpus)
            HAS_BM25 = True
        except ImportError:
            HAS_BM25 = False
            logger.warning("[RAG] aucun backend BM25 disponible (forge_bm25 ni rank_bm25)")

    def _scores_lexicaux(self, query: str) -> list:
        """Canal LEXICAL (FTS5), synchrone — appele en thread, concurremment au dense.

        B4 (2026-09-12) : c'etait une closure interne a `search`, definie APRES le
        bloc dense, donc impossible a lancer avant lui. Sortie ici pour qu'elle
        puisse partir en premier. Le corps est INCHANGE — seul son emplacement
        bouge, pour que le changement soit lisible comme un deplacement.

        sqlite est SYNC : l'appeler dans l'event-loop du hub le bloquait a chaque
        recherche (Phase 0, anti-wedge). D'ou `to_thread` cote appelant.
        """
        _bm = [0.0] * len(self.chunks)
        _hits: dict[str, float] = {}
        try:
            import sqlite3 as _sq
            import re as _re

            _conn = _sq.connect(str(_EMBEDDINGS_DB))
            # FTS5: 'a b c' → 'a OR b OR c' (AND implicite → 0 hit sur contenu FR+EN)
            _tokens = [w for w in _re.split(r"\W+", query) if len(w) > 3][:15]
            _q_fts = " OR ".join(_tokens)
            if _q_fts:
                # On resout l'ID du chunk cote SQL : le rowid ne suffit pas (cf. plus bas).
                _rows = _conn.execute(
                    "SELECT c.id, s.rank FROM "
                    "(SELECT rowid AS rid, rank FROM rag_chunks_fts "
                    " WHERE rag_chunks_fts MATCH ? ORDER BY rank LIMIT 200) s "
                    "JOIN rag_chunks c ON c.rowid = s.rid",
                    (_q_fts,),
                ).fetchall()
                if _rows:
                    _min_r = min(r[1] for r in _rows)
                    for _cid, _rank in _rows:
                        _hits[_cid] = _rank / _min_r if _min_r != 0 else 1.0
            _conn.close()
        except Exception as _fts_e:
            logger.debug(f"FTS5 fallback BM25: {_fts_e}")
            if HAS_BM25 and self.bm25_index:
                _bm = self.bm25_index.get_scores(query.lower().split()).tolist()
        # `rowid == position dans self.chunks` etait FAUX : les suppressions cumulees
        # ont porte MAX(rowid) a 2 318 899 pour 711 085 lignes (mesure 2026-07-29), donc
        # 99,5 % des scores lexicaux tombaient hors bornes et etaient jetes en silence,
        # et les 0,5 % restants etaient attribues au MAUVAIS chunk. On mappe par id.
        if _hits:
            if getattr(self, "_lex_map_n", -1) != len(self.chunks):
                self._lex_map = {
                    _c.get("id"): _i for _i, _c in enumerate(self.chunks) if _c.get("id")
                }
                self._lex_map_n = len(self.chunks)
            for _cid, _score in _hits.items():
                _idx = self._lex_map.get(_cid)
                if _idx is not None and 0 <= _idx < len(_bm):
                    _bm[_idx] = _score
        return _bm

    async def search(
        self,
        query: str,
        k: int = None,
        include_sessions: bool = False,
        role_hint: str = None,
        domain: str = None,
        rerank: bool = True,
        compress: bool = True,
        reorder_mid: bool = False,
        include_flagged: bool = False,
    ) -> list:
        """Recherche hybride (Vecteurs + BM25) avec pondération dynamique.

        reorder_mid=True : réordonne le top-k en head+tail (meilleurs aux
        extrémités) pour atténuer le lost-in-the-middle dans le prompt final.
        OPT-IN : défaut False car les callers top-1/top-k (forge_self_correction)
        dépendent de l'ordre décroissant strict. À activer côté assemblage prompt."""
        if k is None:
            from nokido_agent.app.forge_app_context import get_settings as _gs

            settings = _gs()
            k = settings.rag_docs_topk

        if not self.chunks:
            return []

        # ── 1. Initialisation BM25 si nécessaire ───────────────────────────
        # Anti-wedge : la tokenisation de build_bm25 est pure-python GIL-bound
        # -> même en to_thread elle affame l'event-loop (~minutes sur 691k
        # chunks) et le kill-watchdog suicide le hub. Au-delà du cap on SAUTE
        # BM25 : FTS5 (sqlite, hors GIL) couvre le lexical ; bm25_index ne
        # sert que de fallback si FTS5 échoue.
        import os as _os

        _bm25_cap = int(_os.environ.get("LAFORGE_BM25_MAX_CHUNKS", "120000"))
        if (
            HAS_BM25
            and self.bm25_index is None
            and len(self.chunks) <= _bm25_cap
            and not getattr(self, "_bm25_building", False)
        ):
            self._bm25_building = True
            try:
                await asyncio.to_thread(self.build_bm25)
            finally:
                self._bm25_building = False

        # ── 2. Recherche Vectorielle ───────────────────────────────────────
        # B4 (2026-09-12) — LE CANAL LEXICAL PART EN PREMIER, ET SEUL.
        #
        # Il ne lit que `query` et `self.chunks` : ni `qv`, ni `embs`, ni `sims`.
        # Il etait pourtant lance APRES que l'embedder ait repondu ET que le
        # produit scalaire soit fini. Le poste couteux n'est pas FTS5 (sqlite,
        # hors GIL, ~2-4 ms) mais l'appel reseau a l'embedder — et ce canal dense
        # TOMBE regulierement ici (sidecar injoignable, zero embedding en RAM,
        # backends indisponibles). L'ancien ordre faisait donc attendre le seul
        # canal qui, lui, repondait. Le lexical PRIME : il ne depend de personne.
        _tache_lex = asyncio.create_task(
            asyncio.to_thread(self._scores_lexicaux, query))
        # Si `search` sort avant la recolte (l'embedder qui leve, par exemple),
        # l'exception de cette tache ne serait jamais lue : asyncio se contente
        # alors d'un « Task exception was never retrieved » au garbage collector,
        # dans un journal que personne ne lit. Ce rappel la consomme.
        _tache_lex.add_done_callback(lambda _t: _t.cancelled() or _t.exception())

        qe = await self.get_embeddings([query])
        if not qe or qe[0] is None:
            # Fallback pur BM25 si les embeddings échouent
            sims = [0.0] * len(self.chunks)
        else:
            qv = np.array(qe[0])

            def _vec_sims():
                # P1 inc-2 : sidecar process (forge_faiss_sidecar, faiss, HORS event-loop) si vivant.
                # Retourne (chunk_id, sim) -> aligné sur self.chunks par id. embs vide => SIGReg skip
                # propre + matrice NON construite côté hub = vrai offload. Liveness cachée 30s (pas de
                # pénalité /health par search). Fallback = cache matrice numpy (P0) ci-dessous.
                try:
                    import time as _tm
                    import sys as _s
                    _ok = getattr(self, "_sidecar_ok", None)
                    if _tm.time() - getattr(self, "_sidecar_ct", 0) > 30:
                        _tdir = str(_ROOT_DIR / "tools")
                        if _tdir not in _s.path:
                            _s.path.insert(0, _tdir)
                        from nokido_agent.tools.forge_faiss_sidecar import sidecar_alive as _sa
                        _ok = _sa()
                        self._sidecar_ok, self._sidecar_ct = _ok, _tm.time()
                    if _ok:
                        from nokido_agent.tools.forge_faiss_sidecar import search_remote as _sr
                        _rem = _sr(qv.tolist(), k=min(len(self.chunks), 200))
                        if _rem:
                            _id2i = {c.get("id"): i for i, c in enumerate(self.chunks)}
                            _sims = [0.0] * len(self.chunks)
                            for _cid, _sim in _rem:
                                _j = _id2i.get(_cid)
                                if _j is not None:
                                    _sims[_j] = _sim
                            return np.array([]), _sims
                except Exception as _sc_err:
                    # PAS muet : depuis le boot-trim RAM, le sidecar EST le chemin dense
                    # nominal (skip_emb). Son echec avale sinon la seule trace du repli.
                    import time as _tw

                    if _tw.time() - getattr(self, "_sidecar_warn_ts", 0) > 300:
                        self._sidecar_warn_ts = _tw.time()
                        logger.warning(
                            "RAG dense: sidecar vectoriel injoignable (%s) -> repli matrice locale",
                            _sc_err,
                        )
                # P0 fallback (matrice embeddings + normes ne dépendent PAS de la query -> cache keyé
                # fingerprint count+embedded, s'invalide seul ; seuls dot+qn query-dépendants recalculés).
                _fp = (len(self.chunks), sum(1 for c in self.chunks if c.get("embedding") is not None))
                _cache = getattr(self, "_emb_cache", None)
                if _cache is not None and _cache[0] == _fp:
                    _embs, _norms = _cache[1], _cache[2]
                else:
                    _embs = np.array([c["embedding"] for c in self.chunks if c["embedding"] is not None])
                    _norms = np.linalg.norm(_embs, axis=1) if len(_embs) else _embs
                    self._emb_cache = (_fp, _embs, _norms)
                if len(_embs) == 0:
                    # Sidecar KO + 0 embedding en RAM (skip_emb) = le dense est MORT et la
                    # recherche devient LEXICALE seule, sans erreur. Motif paye le 2026-07-24
                    # (eviction par capacite a endormi le RAG) : il ne se voit que si on le DIT.
                    import time as _tw2

                    if _tw2.time() - getattr(self, "_dense_dead_ts", 0) > 300:
                        self._dense_dead_ts = _tw2.time()
                        logger.warning(
                            "RAG dense MUET: 0 embedding en RAM et sidecar injoignable "
                            "-> resultats LEXICAUX seuls (verifier NokidoQdrantSidecar :8098)"
                        )
                    return _embs, [0.0] * len(self.chunks)
                _qn = np.linalg.norm(qv)
                return _embs, (np.dot(_embs, qv) / (_norms * _qn + 1e-9)).tolist()

            # Phase 0 concurrence (hub_concurrency_plan) : la sim numpy brute-force
            # (build array 30k×1024 + dot product) est SYNC et lourde -> to_thread
            # libère l'event-loop du hub pendant le calcul (anti_gil_multiprocess_isolation).
            embs, sims = await asyncio.to_thread(_vec_sims)

        # ── 3. Recherche Lexicale (FTS5) — sqlite SYNC -> to_thread (Phase 0, anti-wedge) ──
        # Le MATCH FTS5 + (avant) un fetch full-table id->rowid bloquaient l'event-loop à CHAQUE
        # search. NB: l'ancien _id2row (SELECT id,rowid 30k lignes) était du CODE MORT (le mapping
        # utilise _rowid-1) -> supprimé = gros gain + plus de fetch full-table. OPT: FTS5 ~2-4ms.
        # B4 (2026-09-12) : le corps vit desormais dans `_scores_lexicaux`, et la
        # tache a ete LANCEE tout en haut de `search`. Ici on ne fait que la
        # recolter. Un canal qui ne depend de personne ne doit attendre personne.
        try:
            bm_scores = await _tache_lex
        except Exception as _lex_e:  # noqa: BLE001
            # Le repli existait avant la mise en concurrence : il doit y survivre.
            # Et une tache dont l'exception n'est jamais recuperee ne remonte qu'en
            # « exception was never retrieved », dans un journal que personne ne lit.
            logger.debug("canal lexical en echec (%r) -> scores nuls", _lex_e)
            bm_scores = [0.0] * len(self.chunks)

        # ── 4. Fusion Hybride (RRF avec Boost Lexical) ────────────────────
        # Boost BM25 si la requête ressemble à un identifiant technique (CVE, IP, etc.)
        is_technical = bool(re.search(r"cve-\d+|[a-z]{2,}-\d+|\d{1,3}\.\d{1,3}|\b0x[0-9a-f]+\b", query.lower()))

        _rk = min(k * 4, len(self.chunks))
        dr = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)[:_rk]
        sr = sorted(enumerate(bm_scores), key=lambda x: x[1], reverse=True)[:_rk]

        # RRF (Reciprocal Rank Fusion)
        # On donne plus de poids au classement lexical (sr) si technique
        k_rrf = 60
        bm25_weight = 1.2 if is_technical else 1.0

        combined = {}
        # Vecteurs
        for rank, (idx, _) in enumerate(dr):
            combined[idx] = combined.get(idx, 0.0) + 1.0 / (k_rrf + rank + 1)
        # BM25
        for rank, (idx, _) in enumerate(sr):
            combined[idx] = combined.get(idx, 0.0) + (1.0 / (k_rrf + rank + 1)) * bm25_weight

        # POINT DE BASCULE DU ROUTEUR (2026-09-08) -- SOUDE ICI, inerte en SHADOW.
        #
        # POURQUOI ICI ET PAS PLUS BAS. `forge_retrieval_router.fusionner` se declare
        # "LE POINT DE BASCULE, et le seul", et promet que passer de SHADOW a ACTIVE
        # "ne demande aucun autre changement architectural". Cette promesse etait
        # FAUSSE tant que personne ne l'appelait : `LAFORGE_ROUTER_MODE=active` n'aurait
        # RIEN change. Mecanisme present, non cable = dette de cablage, jamais capacite.
        # En SHADOW `fusionner` rend l'objet d'entree LUI-MEME (identite prouvee par
        # `is`), donc ce cablage ne modifie aucun classement aujourd'hui.
        #
        # LA DISPONIBILITE N'ENTRE PAS DANS LA DECISION APPLIQUEE, et c'est voulu :
        # elle n'est connue qu'APRES le classement (`annoter` travaille sur les docs
        # rendus). La faire peser sur les poids qui PRODUISENT ce classement serait
        # circulaire. Elle est journalisee comme CONTEXTE, pour la calibration.
        _rt_dec = None
        _rt_signaux: dict = {}
        try:
            from nokido_agent.app.forge_retrieval_router import decider as _rt_decider
            from nokido_agent.app.forge_retrieval_router import fusionner as _rt_fusionner

            # (rang_lexical, rang_vectoriel) par candidat. Un canal absent laisse None
            # -- jamais un rang factice : un rang invente est un score invente.
            _rt_rangs: dict = {}
            for _r, (_i, _) in enumerate(sr):
                _rt_rangs[_i] = (_r, None)
            for _r, (_i, _) in enumerate(dr):
                _rt_rangs[_i] = (_rt_rangs.get(_i, (None, None))[0], _r)

            # SIGNAUX PAR CANAL pour le journal. Le schema d'observation les prevoit
            # depuis le 2026-09-01 -- avec un troisieme etat, `NOT_OBSERVABLE`, pour ne
            # jamais confondre "le canal a dit zero" et "le canal n'a rien dit -- et
            # PERSONNE NE LES EMETTAIT. Toute observation ecrite depuis lors porte donc
            # NOT_OBSERVABLE sur les deux canaux, ce qui rend le journal inexploitable
            # pour la calibration qu'il est cense preparer. On les emet ici, a la source,
            # ou les scores BRUTS existent encore -- plus bas ils ont deja fondu dans le
            # score final. `float()` est obligatoire : un np.float32 casse le JSON.
            for _i in _rt_rangs:
                _cid = self.chunks[_i].get("id") if 0 <= _i < len(self.chunks) else None
                if _cid is None:
                    continue
                _lx = float(bm_scores[_i]) if 0 <= _i < len(bm_scores) else "NOT_OBSERVABLE"
                _vc = float(sims[_i]) if 0 <= _i < len(sims) else "NOT_OBSERVABLE"
                _rt_signaux[_cid] = (_lx, _vc)

            _rt_dec = _rt_decider(query, {})
            combined = _rt_fusionner(combined, _rt_dec, _rt_rangs)
        except Exception as _rt_be:  # noqa: BLE001 - la bascule ne doit jamais casser une recherche
            logger.debug("[router] bascule ignoree (%r)", _rt_be)

        # ── 5. Filtrage & Qualification ───────────────────────────────────
        import math as _m
        from datetime import datetime

        _now = datetime.utcnow()

        final_candidates = []
        for idx, rrf_score in sorted(combined.items(), key=lambda x: x[1], reverse=True)[: k * 3]:
            c = self.chunks[idx]
            w = rrf_score

            # Décroissance temporelle
            _lam = c.get("lambda_decay", 0.0)
            _ing = c.get("ingested_at", "")
            if _lam > 0 and _ing:
                try:
                    dt = (_now - datetime.fromisoformat(_ing)).total_seconds() / 86400
                    w *= max(0.1, _m.exp(-_lam * dt))
                except Exception:
                    pass

            # Boosters de métadonnées
            if role_hint and c.get("role_hint") == role_hint:
                w += 0.005
            if domain and c.get("domain") == domain:
                w += 0.003
            # Quality score boost (SQL colonne quality_score 0-1)
            # Source: audit 2026-04-26 — chunks >0.6 = bons, <0.2 = bruit
            qs = c.get("quality_score")
            if qs is not None:
                # Boost léger: +0.010 pour excellent, -0.005 pour bruit
                w += (qs - 0.5) * 0.02

            # Hard-exclude flagged injections unless include_flagged is explicitly True
            if not include_flagged:
                is_flagged = False
                try:
                    if c.get("injection_flagged") is True:
                        is_flagged = True
                    elif "meta" in c:
                        meta_val = c["meta"]
                        if isinstance(meta_val, str):
                            try:
                                meta_dict = json.loads(meta_val)
                                if meta_dict.get("injection_flagged") is True:
                                    is_flagged = True
                            except Exception:
                                pass
                        elif isinstance(meta_val, dict):
                            if meta_val.get("injection_flagged") is True:
                                is_flagged = True
                except Exception:
                    pass
                if is_flagged:
                    continue

            # TRACE BRUTE d'activite hors du canal de connaissance.
            # `session:auto_*` (domaine episodic_memory) indexe les tool_calls VERBATIM,
            # requete comprise : une recherche retrouvait en tete l'appel d'outil ou la
            # question figurait mot pour mot — le RAG rendait son propre echo. Sa
            # pertinence lexicale est par construction maximale, donc aucun prior
            # d'autorite raisonnable ne peut la renverser (mesure 24-07 : toujours 1re
            # a 0.30 d'autorite). Il faut un filtre, pas un poids — sinon il faudrait
            # ecraser la pertinence partout ailleurs pour corriger ce seul cas.
            # `include_sessions=True` les rend, meme semantique que pour les contextes
            # vivants : « je veux aussi l'historique ». Rien n'est supprime en base.
            if not include_sessions and str(c.get("source", "")).startswith("session:auto_"):
                continue

            # Qualification de confiance (Ring/Trust)
            try:
                from nokido_agent.app.forge_rag_qualify import apply_trust_weight as _atw
                from nokido_agent.app.forge_rag_qualify import trust_weight as _tw

                _meta = {k: v for k, v in c.items() if k in ("trust_score", "consensus_level", "ring")}
                # Aucun chunk ne porte `trust_score` (mesure 24-07 : 0 sur ~694k) : le
                # defaut 0.5 rendait le facteur IDENTIQUE partout, donc sans effet sur
                # l'ordre. A defaut de metadonnee, l'ORIGINE dit qui parle.
                if "trust_score" not in _meta:
                    _meta["trust_score"] = _tw(c.get("source", "") or "")
                w, _include = _atw(w, _meta)
                if not _include:
                    continue
            except Exception:
                pass

            final_candidates.append((idx, w))

        # Tri final
        final_candidates.sort(key=lambda x: x[1], reverse=True)
        cands = final_candidates[: k * 3]

        # ── 6. SIGReg anti-collapse (Stabilisation) ──────────────────────
        try:
            from nokido_agent.app.forge_sigreg import apply_sigreg, get_monitor as _srmon

            if len(cands) >= 4 and len(embs) > 0 and qe and qe[0]:
                _sr_cands, _sr_stats = apply_sigreg(qv, cands, embs, k=k * 3)
                _srmon().record(_sr_stats)
                if _sr_stats.collapsed:
                    cands = _sr_cands
        except Exception:
            pass

        # ── 7. Construction du résultat ───────────────────────────────────
        docs = [
            {
                "id": self.chunks[i].get("id"),
                "source": f"rag:{self.chunks[i]['source']}",
                "content": self.chunks[i]["text"],
                "score": s,
                "type": "rag",
                "domain": self.chunks[i].get("domain", "general"),
                "role_hint": self.chunks[i].get("role_hint", "chat"),
            }
            for i, s in cands
        ]

        if rerank and len(docs) > k:
            docs = self._rerank(query, docs, top_n=k)
        else:
            docs = docs[:k]

        # DISPONIBILITE PAR CANAL (2026-09-01) -- OBSERVATION SEULE, aucun score ni
        # ordre n'est touche ici. On annote uniquement les k documents RENDUS, donc
        # une seule lecture bornee.
        #
        # POURQUOI. Un score vectoriel manquant devenait un score NUL, et le canal
        # concluait a la non-pertinence de ce qu'il n'avait pas pu voir. Or sur
        # 772 264 chunks sans embedding, 626 646 (81,1 %) sont REFUSES par
        # `forge_tier_guard` et n'en auront JAMAIS : les lire comme « en attente »
        # surestimait la dette d'un facteur cinq. Le futur routeur pondere doit
        # distinguer PENDING, REFUSED_BY_POLICY et UNKNOWN -- sinon il penalise un
        # chunk pour un signal que la politique lui interdit d'avoir.
        try:
            from nokido_agent.app.forge_memory_availability import annoter as _annoter

            _contrib = {self.chunks[i].get("id") for i, _ in cands
                        if 0 <= i < len(bm_scores) and bm_scores[i] > 0}
            docs = _annoter(docs, lexical_contrib=_contrib)
        except Exception as _av_e:  # noqa: BLE001 - observer ne doit jamais casser une recherche
            logger.debug("[availability] annotation ignoree (%r)", _av_e)

        # OBSERVATION DU ROUTEUR (2026-09-01, cablage revu le 2026-09-08).
        # Le mode ne bascule que par la donnee `LAFORGE_ROUTER_MODE` -- et cela est
        # desormais VRAI, parce que le point de bascule est soude plus haut, sur la
        # fusion RRF elle-meme. En SHADOW il rend l'objet d'entree : rien n'est
        # applique, exactement comme avant.
        #
        # ON JOURNALISE LA DECISION QUI A ETE APPLIQUEE, pas une seconde decision
        # calculee ici : deux decisions aux entrees differentes feraient un journal
        # qui decrit autre chose que ce qui s'est passe. Le repli ne sert que si la
        # bascule a leve.
        try:
            from nokido_agent.app.forge_retrieval_router import decider as _rt_decider
            from nokido_agent.app.forge_retrieval_router import observer as _rt_observer

            _rt_dispo = (docs[0].get("availability") if docs else {}) or {}
            if _rt_dec is None:
                _rt_dec = _rt_decider(query, _rt_dispo)
            _rt_observer(f"{int(time.time() * 1000)}", query, _rt_dec, [
                {"chunk_id": d.get("id"), "rank": i + 1, "final_score": d.get("score"),
                 "lexical_score": _rt_signaux.get(
                     d.get("id"), ("NOT_OBSERVABLE", "NOT_OBSERVABLE"))[0],
                 "vector_score": _rt_signaux.get(
                     d.get("id"), ("NOT_OBSERVABLE", "NOT_OBSERVABLE"))[1],
                 "availability": d.get("availability")}
                for i, d in enumerate(docs[:k])],
                contexte={"rerank": bool(rerank), "k": int(k),
                          "include_sessions": bool(include_sessions),
                          "domain": domain, "role_hint": role_hint,
                          "availability_observee": _rt_dispo})
        except Exception as _rt_e:  # noqa: BLE001 - le shadow ne doit jamais gener la recherche
            logger.debug("[router] observation shadow ignoree (%r)", _rt_e)

        if compress:
            for d in docs:
                d["content_full"] = d["content"]
                d["content"] = self._compress_context(query, d["content"])

        if include_sessions:
            for sn, ctx in self.session_ctxs.items():
                for msg in ctx.messages[-3:]:
                    docs.append({"source": f"session:{sn}", "content": msg["content"], "score": 0.4, "type": "session"})

        docs.sort(key=lambda x: x["score"], reverse=True)
        docs = docs[:k]
        if reorder_mid and len(docs) > 2:
            # Lost-in-the-middle : meilleurs aux EXTREMITES du prompt, faibles au
            # centre. APRES le slice [:k] (sinon head=indices pairs perdrait les
            # 2e/4e meilleurs du top-k). head=pairs, tail=impairs inversés.
            _head, _tail = docs[0::2], docs[1::2]
            docs = _head + _tail[::-1]
        self._bump_access([d.get("id") for d in docs if d.get("id")])
        return docs

    def _bump_access(self, ids: list) -> None:
        """Incrémente access_count des chunks RETOURNÉS = signal hot-par-usage
        (consommé par compaction cold + promotion). Écrit le TARGET réel du symlink
        (realpath -> V:) car le -wal échoue via le symlink C: (dir read-only).
        Best-effort, JAMAIS fatal (la lecture ne doit pas casser sur un write raté)."""
        if not ids:
            return
        try:
            import os as _os
            import sqlite3 as _sq

            _p = _os.path.realpath(str(_EMBEDDINGS_DB))
            _conn = _sq.connect(_p, timeout=2)
            _conn.execute(
                f"UPDATE rag_chunks SET access_count=COALESCE(access_count,0)+1 "
                f"WHERE id IN ({','.join('?' for _ in ids)})",
                ids,
            )
            _conn.commit()
            _conn.close()
        except Exception as _e:
            logger.debug(f"access_count bump skip: {_e}")

    async def close(self) -> None:
        """Close."""
        if self._session and not self._session.closed:
            await self._session.close()


# Re-exports pour compatibilité ascendante
from nokido_agent.app.forge_agentic_engine import SkillEntry, AgenticEngine  # noqa: F401

# ─── Point d'entrée public ───────────────────────────────────────────────

import threading as _threading_rag

_RAG = None
_RAG_LOCK = _threading_rag.Lock()


def get_rag(db_path=None) -> RAGEngine:
    """Accesseur global (singleton) pour le RAG.

    Double-checked locking : construire un RAGEngine decode ~691k chunks
    (GIL-bound, ~2 min, gros pic RAM). Sans verrou, deux appels concurrents
    construisent DEUX moteurs — race identifiee au cold-wedge 2026-07-07.
    """
    global _RAG
    if _RAG is None:
        with _RAG_LOCK:
            if _RAG is None:
                _RAG = RAGEngine(db_path=db_path)
    return _RAG


async def run_full_cycle(query: str):
    """Lance un cycle complet d'évolution sémantique."""
    from nokido_agent.app.forge_agentic_engine import EvolutionOrchestrator
    from nokido_agent.app.forge_app_context import get_settings, get_version_manager

    settings = get_settings()
    vm = get_version_manager()
    orc = EvolutionOrchestrator(settings.ollama_url, vm, get_rag())
    return await orc.run_full_cycle(query)
