"""
forge_ingest_pipeline.py - Pipeline raffinement données -> vecteurs
====================================================================
3 niveaux (état de l'art 2026) :
  L1 - Chunking sémantique  : 256-512 tokens, overlap phrases
  L2 - Contextual prefix    : résumé du contexte
  L3 - role_hint structuré  : domain:subdomain:type

Sources : GitHub releases, ArXiv, PyPI, RSS, web pages, code Python
"""

from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : sys.stderr L317 -- dans un chemin
# d'ERREUR, donc la NameError se serait declenchee au pire moment.
import sys
import hashlib, json, logging, re, sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.Ingest")
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"

CHUNK_TOKENS_MAX = 400
CHUNK_OVERLAP = 0.15

# Overlap dynamique par source_type (decision arbitrage debat multi-LLM)
OVERLAP_BY_TYPE = {
    "python_source": 0.05,
    "arxiv": 0.20,
    "github": 0.15,
    "web": 0.15,
    "markdown": 0.10,
}

# Domaines avec dedup semantique cosine en plus du MD5
COSINE_DEDUP_DOMAINS = {"watch_alerts", "rag_research"}

# Flag modele embedding (migration BGE-M3 future)
import os

EMBED_MODEL = os.environ.get("EMBED_MODEL", "minilm")

MIN_CHUNK_CHARS = 80


@dataclass
class RefinedChunk:
    id: str
    text: str
    source: str
    domain: str
    role_hint: str
    author: str = ""
    meta: dict = field(default_factory=dict)
    embedding: list = field(default_factory=list)
    quality: float = 1.0


def clean_text(text: str) -> str:
    text = re.sub(r"^\s*https?://\S+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-_=]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def chunk_semantic(text: str, max_tokens: int = CHUNK_TOKENS_MAX, overlap: float = CHUNK_OVERLAP) -> list[str]:
    """Chunking sémantique sur phrases avec overlap."""
    text = clean_text(text)
    if estimate_tokens(text) <= max_tokens:
        return [text] if len(text) >= MIN_CHUNK_CHARS else []

    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks, current, current_tokens = [], [], 0

    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for sent in sentences:
            sent_tokens = estimate_tokens(sent)
            if current_tokens + sent_tokens > max_tokens and current:
                chunk_text = " ".join(current)
                if len(chunk_text) >= MIN_CHUNK_CHARS:
                    chunks.append(chunk_text)
                n_overlap = max(1, int(len(current) * overlap))
                current = current[-n_overlap:]
                current_tokens = sum(estimate_tokens(s) for s in current)
            current.append(sent)
            current_tokens += sent_tokens

    if current:
        chunk_text = " ".join(current)
        if len(chunk_text) >= MIN_CHUNK_CHARS:
            chunks.append(chunk_text)
    return chunks


DOMAIN_SIGNALS = {
    "watch_alerts": [
        "release",
        "changelog",
        "breaking",
        "deprecated",
        "migration",
        "upgrade",
        "version",
        "advisory",
        "cve",
    ],
    "rag_research": [
        "retrieval",
        "embedding",
        "chunking",
        "vector",
        "rag",
        "graphrag",
        "agentic",
        "semantic search",
        "reranking",
        "colbert",
        "matryoshka",
        "late chunking",
    ],
    "nokido_code": [
        "laforge",
        "forge_",
        "mcp",
        "hub",
        "registry",
        "dispatch",
        "router",
        "worker",
        "ring",
        "heartbeat",
    ],
    "ai_papers": [
        "arxiv",
        "abstract",
        "we propose",
        "we present",
        "our approach",
        "experimental results",
        "transformer",
    ],
    "security": ["cve", "vulnerability", "exploit", "patch", "advisory", "rce", "injection", "auth bypass"],
    "devops": ["docker", "kubernetes", "deploy", "ci/cd", "github actions", "nssm", "systemd"],
}

ROLE_SIGNALS = {
    "release:breaking_change": ["breaking", "removed", "deprecated", "migration required", "incompatible"],
    "release:feature": ["added", "new feature", "introduces", "now supports", "enhancement"],
    "release:bugfix": ["fixed", "fix", "resolved", "patch", "bug"],
    "paper:abstract": ["abstract", "we propose", "we present", "in this paper", "we demonstrate"],
    "doc:api": ["api", "endpoint", "parameter", "returns", "raises", "usage"],
    "alert:security": ["critical", "high severity", "cve-", "patch immediately"],
}


def detect_meta(text: str, source: str = "") -> tuple[str, str]:
    text_lower = text.lower()
    src_lower = source.lower()

    domain_scores: dict[str, int] = {}
    for domain, signals in DOMAIN_SIGNALS.items():
        score = sum(1 for s in signals if s in text_lower)
        if score:
            domain_scores[domain] = score
    if "arxiv" in src_lower:
        domain_scores["ai_papers"] = domain_scores.get("ai_papers", 0) + 3
    if "github" in src_lower:
        domain_scores["watch_alerts"] = domain_scores.get("watch_alerts", 0) + 2
    if "pypi" in src_lower:
        domain_scores["watch_alerts"] = domain_scores.get("watch_alerts", 0) + 2
    domain = max(domain_scores, key=domain_scores.get) if domain_scores else "general"

    role_scores: dict[str, int] = {}
    for role, signals in ROLE_SIGNALS.items():
        score = sum(1 for s in signals if s in text_lower)
        if score:
            role_scores[role] = score
    role = max(role_scores, key=role_scores.get) if role_scores else "content"

    return domain, role


def add_contextual_prefix(chunk: str, source: str, domain: str, doc_summary: str = "") -> str:
    src_name = source.split("/")[-1][:40] if "/" in source else source[:40]
    prefix = f"[{domain}:{src_name}]"
    if doc_summary:
        prefix += " " + doc_summary[:100].replace("\n", " ")
    return f"{prefix}\n\n{chunk}"


def _text_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text[:200].lower())
    return hashlib.md5(normalized.encode()).hexdigest()


def build_role_hint(source_type: str, domain: str, role: str, qualifier: str = "") -> str:
    """
    Construit un role_hint structure 4 niveaux.
    Format : source_type:domain:role:qualifier
    Ex: github:watch_alerts:release:breaking_change
        arxiv:ai_papers:paper:abstract
        python:nokido_code:function:core
    """
    parts = [source_type, domain, role]
    if qualifier:
        parts.append(qualifier)
    return ":".join(p for p in parts if p)


def _classify_source(source: str) -> str:
    s = source.lower()
    if "arxiv.org" in s:
        return "arxiv"
    if "github.com" in s:
        return "github"
    if "pypi.org" in s:
        return "pypi"
    if "huggingface" in s:
        return "huggingface"
    if s.endswith(".py"):
        return "python_source"
    if s.endswith(".md"):
        return "markdown"
    if s.startswith("http"):
        return "web"
    return "file"


def process_document(
    text: str,
    source: str,
    domain_hint: str = "",
    role_hint: str = "",
    author: str = "",
    doc_summary: str = "",
    max_tokens: int = CHUNK_TOKENS_MAX,
) -> list[RefinedChunk]:
    """
    Pipeline complet : texte brut -> chunks raffinés.

    L1 : chunking sémantique (phrases + overlap 15%)
    L2 : préfixe contextuel déterministe
    L3 : role_hint structuré auto-détecté
    """
    if not text or len(text.strip()) < MIN_CHUNK_CHARS:
        return []

    src_type = _classify_source(source)
    dyn_overlap = OVERLAP_BY_TYPE.get(src_type, CHUNK_OVERLAP)
    raw_chunks = chunk_semantic(text, max_tokens, overlap=dyn_overlap)
    if not raw_chunks:
        return []

    auto_domain, auto_role = detect_meta(text, source)
    final_domain = domain_hint or auto_domain
    final_role = role_hint or auto_role
    quality = min(1.0, len(text.strip()) / max(len(text), 1))

    chunks = []
    for i, chunk_text in enumerate(raw_chunks):
        enriched = add_contextual_prefix(chunk_text, source, final_domain, doc_summary)
        uid = "rp_" + hashlib.md5(f"{source}:{i}:{chunk_text[:50]}".encode()).hexdigest()[:12]

        chunks.append(
            RefinedChunk(
                id=uid,
                text=enriched,
                source=source,
                domain=final_domain,
                role_hint=(f"{final_role}:chunk{i:02d}" if len(raw_chunks) > 1 else final_role),
                author=author,
                quality=quality,
                meta={
                    "chunk_idx": i,
                    "total_chunks": len(raw_chunks),
                    "tokens_est": estimate_tokens(chunk_text),
                    "source_type": _classify_source(source),
                    "fingerprint": _text_fingerprint(enriched),
                },
            )
        )
    return chunks


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Connexion d'ecriture GOUVERNEE (`forge_db_path.open_writer`).

    Avant le 2026-09-03 : `sqlite3.connect(...)` nu. Il manquait
    `isolation_level=None`, donc le module ouvrait une transaction IMPLICITE au
    premier INSERT et la gardait jusqu'au commit — le verrou d'ecriture etait
    tenu pendant TOUTE la boucle d'ingestion. La docstring de
    `forge_db_path.write_retry` decrit exactement ce cas (« un voisin mal ecrit
    (`sqlite3.connect()` nu) garde un verrou implicite ») : le pipeline
    d'ingestion ETAIT ce voisin, alors que la primitive prouvee existait depuis
    le 2026-06-04 (bench « 0 contention / 0 echec » sous N workers).

    Consequence directe : l'ingestion ne pouvait pas etre parallelisee, et les
    ecrivains voisins prenaient des `database is locked` — une ecriture qui rend
    `locked` est PERDUE si personne ne la reprend (3 veilles perdues le 25/07).

    Le repli garde l'ancien comportement si la primitive est indisponible, mais
    il le DIT : un repli silencieux ferait croire que l'ecriture est gouvernee.
    """
    try:
        import sys as _sys
        _app = str(Path(__file__).resolve().parent)
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_db_path import open_writer
    except ImportError as exc:
        print("[ingest] forge_db_path.open_writer indisponible (%s) — connexion "
              "NON gouvernee, ne pas paralleliser" % exc, file=sys.stderr)
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    return open_writer()


class SessionSink:
    """Ecrivain RAG DURABLE, compatible avec la signature RAGEngine.add_session_message.

    Pourquoi : RAGEngine.add_session_message() n'ajoute le chunk QU'EN RAM
    (self.chunks) — sans save explicite il meurt avec le process. Les appelants
    historiques (clawhub_bridge, silo_engine, silo_fragmenter) croyaient indexer :
    ils n'indexaient rien (et importaient en plus un `ForgeRAGEngine` inexistant,
    donc ImportError avale). Ce sink garde LEUR signature mais persiste via
    process_document + store_chunks. Embedding laisse a NULL : le daemon
    forge_embed_auto_trigger le remplit (pipeline prevu). Aucun RAGEngine
    construit -> pas de decode ~691k chunks.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    def add_session_message_sync(
        self, session_name: str, role: str, content: str, meta: dict | None = None
    ) -> int:
        chunks = process_document(
            text=f"[{role}] {content}",
            source=f"session:{session_name}",
            domain_hint="session",
            role_hint=role,
            author=session_name,
        )
        if meta:
            for c in chunks:
                c.meta.update(meta)
        return store_chunks(chunks, db_path=self.db_path)

    async def add_session_message(
        self, session_name: str, role: str, content: str, meta: dict | None = None
    ) -> int:
        """Meme signature que RAGEngine.add_session_message. I/O SQLite -> to_thread
        (ne jamais bloquer l'event loop du hub)."""
        import asyncio

        return await asyncio.to_thread(self.add_session_message_sync, session_name, role, content, meta)


def get_session_sink(db_path: Path = DB_PATH) -> SessionSink:
    """Sink d'ecriture RAG durable (aucun etat lourd : instanciation triviale)."""
    return SessionSink(db_path=db_path)


def store_chunks(chunks: list[RefinedChunk], db_path: Path = DB_PATH, batch_size: int = 100) -> int:
    """Stocke les chunks dans embeddings.db.
    Ferme et rouvre la connexion après chaque batch pour libérer le slot WAL writer."""
    if not chunks:
        return 0
    import datetime, numpy as np

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inserted = 0
    batch = []

    # --- Dedup par fingerprint : UNE requete pour tout le lot ---------------
    # Mesure 2026-07-31. La version precedente faisait, PAR CHUNK, un
    # `meta LIKE '%"fingerprint": "..."%'` : EXPLAIN = SCAN rag_chunks, soit
    # 710 604 lignes (10,5 Go) a 3,49 s piece. Une RFC de 339 chunks = 20 min,
    # les 36 normes de l'audit = 11,8 h -- l'ingestion paraissait "bloquee".
    # Second defaut, plus discret : le fingerprint n'etait JAMAIS ecrit dans
    # meta a l'insertion. 188 lignes sur 710 604 en portaient un, donc le garde
    # payait un scan complet pour se comparer a un ensemble quasi vide
    # (recepteur sans emetteur). Il est desormais pose a l'ecriture.
    for c in chunks:
        if not c.meta.get("fingerprint"):
            c.meta["fingerprint"] = _text_fingerprint(c.text)

    known = set()
    fps = [c.meta["fingerprint"] for c in chunks]
    conn = _open_db(db_path)
    try:
        for start in range(0, len(fps), 500):
            part = fps[start:start + 500]
            placeholders = ",".join("?" * len(part))
            rows = conn.execute(
                "SELECT json_extract(meta,'$.fingerprint') FROM rag_chunks "
                "WHERE json_extract(meta,'$.fingerprint') IN (" + placeholders + ")",
                part,
            ).fetchall()
            known.update(row[0] for row in rows if row[0])
    finally:
        conn.close()

    for c in chunks:
        fp = c.meta["fingerprint"]
        if fp in known:
            continue
        known.add(fp)  # dedup intra-lot : deux chunks identiques d'un meme document
        if c.domain in COSINE_DEDUP_DOMAINS and c.embedding:
            conn = _open_db(db_path)
            try:
                import numpy as _np

                vec = _np.array(c.embedding, dtype=_np.float32)
                rows_cos = conn.execute(
                    "SELECT embedding FROM rag_chunks WHERE domain=? AND embedding IS NOT NULL ORDER BY rowid DESC LIMIT 50",
                    (c.domain,),
                ).fetchall()
                skip = any(
                    (
                        lambda o: (
                            o.shape == vec.shape
                            and float(_np.dot(vec, o) / (_np.linalg.norm(vec) * _np.linalg.norm(o) + 1e-9)) > 0.92
                        )
                    )(_np.frombuffer(emb_blob, dtype=_np.float32))
                    for (emb_blob,) in rows_cos
                )
                conn.close()
                if skip:
                    continue
            except Exception:
                conn.close()

        emb_blob = np.array(c.embedding, dtype=np.float32).tobytes() if c.embedding else None
        batch.append(
            (c.id, c.text[:4000], c.source, c.domain, c.role_hint, c.author, now, json.dumps(c.meta), emb_blob)
        )

        if len(batch) >= batch_size:
            conn = _open_db(db_path)
            conn.executemany(
                "INSERT OR REPLACE INTO rag_chunks "
                "(id,text,source,domain,role_hint,author,ingested_at,meta,embedding) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                batch,
            )
            conn.commit()
            conn.close()  # release WAL write slot between batches
            inserted += len(batch)
            batch = []

    if batch:
        conn = _open_db(db_path)
        conn.executemany(
            "INSERT OR REPLACE INTO rag_chunks "
            "(id,text,source,domain,role_hint,author,ingested_at,meta,embedding) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            batch,
        )
        conn.commit()
        conn.close()
        inserted += len(batch)

    logger.info(f"[ingest] {inserted}/{len(chunks)} chunks stockes")
    return inserted


if __name__ == "__main__":
    sample = """
    llama-cpp-python 0.3.16 Release Notes

    Breaking Changes
    Removed deprecated llamacpp_call_sync(). Use llamacpp_call() with asyncio.
    The n_gpu_layers parameter now defaults to 0 (CPU) instead of -1.
    Migration required: add n_gpu_layers=-1 explicitly in Llama() constructor.

    New Features
    Vulkan backend now supports AMD iGPU Radeon 780M on Windows via DirectML fallback.
    Added flash_attn=True parameter for 30 percent faster inference.

    Bug Fixes
    Fixed numpy 2.x compatibility when loading GGUF models.
    Fixed tokenizer int32/int64 mismatch on Windows with ONNX models.
    """

    chunks = process_document(
        text=sample,
        source="https://github.com/abetlen/llama-cpp-python/releases/tag/v0.3.16",
        author="abetlen/llama-cpp-python",
        doc_summary="llama-cpp-python v0.3.16 breaking changes GPU Vulkan AMD",
    )
    for c in chunks:
        print(f"domain={c.domain} role={c.role_hint} tokens={c.meta['tokens_est']}")
        print(f"  {c.text[:120]}\n")
