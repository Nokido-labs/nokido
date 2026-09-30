"""forge_memory_archival.py — memory hierarchique Letta MemGPT pattern.

Architecture :
  - main_context  : rolling FIFO buffer (last N turns) - max_chars=8000
  - core_memory   : facts persistents agent_persona + user_persona (always in prompt)
  - archival_memory : full history vectorise -> recall on-demand via embed search
  - recall_memory : log conversations brutes (audit/replay)

Stockage : table conv_archives (FK rag_chunks pour vectorisation).

API :
    am = ArchivalMemory(agent_id="agt_claude", session_id="...")
    am.append(role="user", content="...")
    am.append(role="assistant", content="...")
    am.recall(query="...", top_k=5) -> list[ConvMessage]  # archival search
    am.compose_context(query) -> str  # main + core + recalled archival
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("memory_archival")

# PROMOTION VERS LA MEMOIRE GLOBALE — mesure 2026-08-25.
# `domain="laforge-memory"` est le SEUL tier agent-memory vectorisable (trigger
# forge_tier_guard) ; `conv_archive` est SKIP_TIER, donc archive et auditable mais
# jamais embarque. On s'appuie sur ce mecanisme existant au lieu d'ajouter une
# colonne de statut : un message d'OWNER est une source primaire et se promeut ; une
# reponse d'ASSISTANT est un brouillon tant que rien ne l'a verifiee.
# Le journal brut garde TOUT dans les deux cas : on ne conditionne que la promotion.
_PROMOUVOIR_ASSISTANT = os.environ.get("LAFORGE_MEMORY_PROMOTE_ASSISTANT", "0") == "1"
_TIER_PROMU = "laforge-memory"
_TIER_BROUILLON = "conv_archive"


def _epoch_archive(brut) -> tuple:
    """(epoch, provenance) : la date d'ORIGINE du message, pas celle du rappel.

    Defaut mesure 2026-08-25 : `recall()` SELECTionnait `archived_at` puis le jetait
    au profit de `time.time()`. Un message archive en juillet, rappele ce soir, se
    declarait de ce soir — toute question temporelle devenait impossible sur l'objet
    remis au consommateur, alors que la colonne etait deja chargee.

    Trois etats : date lue / date illisible / date absente. Quand on ne sait pas, on
    retombe sur maintenant ET on le DIT dans la metadata, au lieu de laisser croire a
    une precision qu'on n'a pas.
    """
    if brut:
        try:
            return datetime.fromisoformat(str(brut)).timestamp(), "archived_at"
        except Exception:  # noqa: BLE001 — date illisible : on le declare
            return time.time(), "illisible"
    return time.time(), "absente"


def _conv_depuis_ligne(r) -> "ConvMessage":
    """Reconstruit un message rappele en CONSERVANT sa date d'origine.

    Ecrit une fois, utilise par les DEUX branches du rappel (FTS et repli LIKE) :
    la version precedente dupliquait la construction, et les deux copies ecrasaient
    la date. Une meme donnee reconstruite par deux chemins qui divergent, c'est le
    defaut que ce module vient de payer.
    """
    ts, provenance = _epoch_archive(r[2])
    meta = {}
    try:
        meta = json.loads(r[4] or "{}")
    except Exception:  # noqa: BLE001 — metadata illisible : on n'en fabrique pas
        meta = {}
    meta["ts_source"] = provenance
    return ConvMessage(role=r[0], content=r[1], timestamp=ts,
                       tokens_estimate=r[3] or 0, metadata=meta)


def _tier_rag(role: str) -> tuple:
    """(domaine, statut) : ce message va-t-il en memoire GLOBALE ?

    `user` = source primaire, promue. `assistant` = brouillon par defaut, car une
    hallucination promue revient en contexte au tour suivant et se renforce
    elle-meme. Le drapeau d'environnement permet de retablir l'ancien comportement
    sans toucher au code — un choix, pas un accident.
    """
    if str(role) == "user" or _PROMOUVOIR_ASSISTANT:
        return _TIER_PROMU, "promu"
    return _TIER_BROUILLON, "brouillon"


def _meta_verite(role: str, observe_a: str) -> str:
    """Le meta JSON du chunk : etat de VERITE et validite TEMPORELLE.

    RECONCILIATION, et non mecanisme de plus. `forge_rag_truth` porte deja une
    machine a etats complete (DRAFT / REVIEW / VERIFIED / GOLD) stockee dans
    `rag_chunks.meta` sous `consensus_level`, avec `promote_chunk`,
    `validate_and_promote` et `batch_promote_draft` qui la lisent. Ecrire un statut
    dans un champ a moi aurait fabrique une seconde verite qu'aucun de ces appelants
    ne sait promouvoir — le defaut exact que ce depot paie ailleurs.

    Deux axes ORTHOGONAUX, et c'est voulu :
      * le DOMAINE decide de la vectorisation (tier guard existant) ;
      * `consensus_level` decide de la CONFIANCE, et reste promouvable.

    Validite temporelle portee dans le meme JSON plutot qu'en colonnes : le corpus
    compte plus d'un million de chunks, une migration de schema serait un geste d'une
    autre nature. `valid_from` est la date d'OBSERVATION, pas celle d'ingestion —
    c'est la distinction qui manquait pour repondre « qu'est-ce qui etait vrai a T ».
    `valid_to = None` signifie « encore valide », jamais « inconnu ».
    """
    _, statut = _tier_rag(role)
    return json.dumps({
        "consensus_level": "verified" if statut == "promu" else "draft",
        "valid_from": observe_a,
        "valid_to": None,
        "superseded_by": None,
        "origine": "conv_archive",
    }, ensure_ascii=False)


def promouvoir_brouillon(chunk_id: str, corroborant_id: str, db_path=None,
                         validator_id: str = "epistemic:corroboration",
                         validator_ring: int = 2) -> dict:
    """La PORTE draft -> verified, absente jusqu'ici.

    Depuis le 2026-08-25 l'archival ecrit `consensus_level` (draft pour une reponse
    assistant, verified pour une source primaire owner) : la matiere a promouvoir
    existe. Mais rien ne faisait passer un brouillon a verified — `validate_and_promote`
    n'avait AUCUN appelant, et `batch_promote_draft` se valide contre le texte du chunk
    LUI-MEME (`source_text=text`) : une hallucination y passe le check semantique avec
    un Jaccard de 1.0. Ce n'est pas une porte, c'est un tampon.

    Ici la preuve est INDEPENDANTE : le brouillon est valide contre le texte d'un chunk
    deja verifie (source primaire owner, ou document de veille) venant d'une AUTRE
    source, designe par la reevaluation `supports` du consolidateur epistemique
    (`tools/forge_epistemic_extract_claims.reevaluer`). Le check A (semantique) mesure
    alors un vrai ancrage, le check B (autorite) passe par le ring du validateur, le
    check C (coherence) par le ledger. Si les trois passent, `promote_chunk` ecrit
    l'etat de verite ET le chunk change de tier (`conv_archive` -> `laforge-memory`) :
    il devient vectorisable, donc memoire GLOBALE. Rien n'est promu sur la seule foi
    d'un LLM : le juge designe le candidat, le triple check tranche.

    PLAFOND : VERIFIED. `triple_check` signe la coherence au nom du ledger (ring 0),
    ce qui fait monter n'importe quel chunk qui passe a GOLD — etat IMMUABLE qui sert
    ensuite de reference aux autres. Une corroboration automatique ne vaut pas un
    acte ring 0/1 : on plafonne, GOLD reste un geste humain ou du NR runner.

    Rend un dict a raison explicite — jamais un booleen muet. La promotion est
    RELUE en base avant d'etre annoncee.
    """
    import dataclasses

    from nokido_agent.app import forge_rag_truth as verite

    db = Path(db_path) if db_path else DB
    try:
        conn = sqlite3.connect(str(db), timeout=30)
        try:
            rows = {r[0]: r for r in conn.execute(
                "SELECT id, text, domain, source, meta FROM rag_chunks WHERE id IN (?, ?)",
                (chunk_id, corroborant_id))}
        finally:
            conn.close()
    except sqlite3.Error as e:
        return {"promu": None, "raison": "base illisible (%s)" % type(e).__name__}
    if chunk_id not in rows or corroborant_id not in rows:
        return {"promu": False, "raison": "chunk introuvable"}
    b, c = rows[chunk_id], rows[corroborant_id]

    def _meta(s):
        try:
            return json.loads(s or "{}") or {}
        except (TypeError, ValueError):
            return {}

    meta_b, meta_c = _meta(b[4]), _meta(c[4])
    if meta_b.get("consensus_level", "draft") != "draft":
        return {"promu": False, "raison": "pas un brouillon (%s)" % meta_b.get("consensus_level")}
    if (b[3] or "") == (c[3] or ""):
        return {"promu": False, "raison": "meme source : pas une corroboration independante"}
    if meta_c.get("consensus_level") not in ("verified", "gold") and c[2] != "watch_veille":
        return {"promu": False, "raison": "corroborant non verifie (%s)" % meta_c.get("consensus_level")}

    res = verite.triple_check(
        chunk_id=chunk_id, chunk_text=b[1] or "", source_text=c[1] or "",
        domain=b[2] or "general", current_meta=meta_b,
        validator_id=validator_id, validator_ring=validator_ring, db_path=db)
    if not res.passed:
        return {"promu": False, "raison": "triple check: " + " | ".join(res.reasons)[:300]}
    plafond = verite.TruthState.VERIFIED
    if res.new_state > plafond:
        try:
            res = dataclasses.replace(res, new_state=plafond,
                                      trust_score=min(res.trust_score, plafond.trust_score()))
        except TypeError:
            res.new_state = plafond
            res.trust_score = min(res.trust_score, plafond.trust_score())
    if not verite.promote_chunk(chunk_id, res, db_path=db):
        return {"promu": False, "raison": "etat %s n'a pas depasse draft (trust %.2f)"
                % (res.new_state.label(), res.trust_score)}

    tier = "inchange"
    try:
        conn = sqlite3.connect(str(db), timeout=30)
        try:
            relu = conn.execute("SELECT meta FROM rag_chunks WHERE id = ?", (chunk_id,)).fetchone()
            niveau = _meta(relu[0] if relu else None).get("consensus_level")
            if niveau not in ("verified", "gold"):
                return {"promu": False, "raison": "relecture: consensus_level=%s" % niveau}
            cur = conn.execute(
                "UPDATE rag_chunks SET domain = ?, "
                "role_hint = replace(coalesce(role_hint, ''), ':brouillon', ':promu') "
                "WHERE id = ? AND domain = ?",
                (_TIER_PROMU, chunk_id, _TIER_BROUILLON))
            conn.commit()
            tier = _TIER_PROMU if cur.rowcount else "deja global"
        finally:
            conn.close()
    except sqlite3.Error as e:
        tier = "tier non change (%s)" % type(e).__name__
    return {"promu": True, "etat": res.new_state.label(), "trust": round(res.trust_score, 3),
            "tier": tier, "corrobore_par": corroborant_id}


# Schema (idempotent init au premier usage)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conv_archives (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tokens_estimate INTEGER,
    archived_at TEXT DEFAULT (datetime('now', 'utc')),
    recall_score REAL DEFAULT 0,
    rag_chunk_id TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_archives_agent ON conv_archives(agent_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_archives_session ON conv_archives(session_id);

CREATE TABLE IF NOT EXISTS core_memory (
    agent_id TEXT PRIMARY KEY,
    persona TEXT,
    user_persona TEXT,
    facts TEXT,
    updated_at TEXT DEFAULT (datetime('now', 'utc'))
);

-- Recall index (FTS5) : recherche archival sans SQL LIKE brut (regle maison).
CREATE VIRTUAL TABLE IF NOT EXISTS conv_archives_fts USING fts5(
    content,
    agent_id UNINDEXED,
    arch_id UNINDEXED,
    tokenize = 'porter unicode61'
);
"""


@dataclass
class ConvMessage:
    role: str  # user|assistant|system|tool
    content: str
    timestamp: float = field(default_factory=time.time)
    tokens_estimate: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _init_schema(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _estimate_tokens(text: str) -> int:
    """Rough estimate : ~4 chars per token."""
    return len(text) // 4


class ArchivalMemory:
    """Letta-style hierarchical memory pour un agent + session."""

    def __init__(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        main_max_chars: int = 8000,
        archival_summarize_threshold: int = 12000,
    ):
        self.agent_id = agent_id
        self.session_id = session_id or hashlib.sha256((agent_id + str(time.time())).encode()).hexdigest()[:12]
        self.main_max_chars = main_max_chars
        self.archival_summarize_threshold = archival_summarize_threshold
        self.main_buffer: deque[ConvMessage] = deque()
        self._main_chars = 0
        self.async_writes = False  # get_agent_memory(async_writes=True) -> archivage en thread
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(DB), timeout=30)
        try:
            _init_schema(conn)
        finally:
            conn.close()

    def _conn(self):
        return sqlite3.connect(str(DB), timeout=30)

    # --- Main context (rolling) ---

    def append(self, role: str, content: str, metadata: Optional[dict] = None):
        """Ajoute message au main_buffer. Si overflow -> archive le plus ancien."""
        msg = ConvMessage(
            role=role, content=content, tokens_estimate=_estimate_tokens(content), metadata=metadata or {}
        )
        self.main_buffer.append(msg)
        self._main_chars += len(content)

        # Evict overflow vers archival
        while self._main_chars > self.main_max_chars and len(self.main_buffer) > 2:
            old = self.main_buffer.popleft()
            self._main_chars -= len(old.content)
            self._archive_dispatch(old)

    def remember(self, role: str, content: str, metadata: Optional[dict] = None):
        """Persiste IMMEDIATEMENT en archival (sans attendre l'overflow du buffer).
        Pour logique stateless/one-shot (research_agent) ou fin de tache (cowork) :
        garantit que le tour survit au process. compose_context/recall le retrouvent."""
        msg = ConvMessage(
            role=role, content=content, tokens_estimate=_estimate_tokens(content), metadata=metadata or {}
        )
        self._archive_dispatch(msg)

    def _archive_dispatch(self, msg: ConvMessage):
        """Archive sync, ou en thread daemon si async_writes (fire-and-forget :
        respecte la parade R3 des consommateurs a DB dediee comme cowork)."""
        if getattr(self, "async_writes", False):
            import threading

            threading.Thread(target=self._archive_safe, args=(msg,), daemon=True).start()
        else:
            self._archive(msg)

    def _archive_safe(self, msg: ConvMessage):
        try:
            self._archive(msg)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"async archive failed: {e}")

    def _archive(self, msg: ConvMessage):
        """Persiste msg dans conv_archives (+ rag_chunks pour vectorisation future).

        BROUILLON PAR DEFAUT pour l'assistant (2026-08-25). Chaque message partait
        dans `rag_chunks` avec `domain="laforge-memory"`, le SEUL tier agent-memory
        vectorisable — donc globalement recuperable, sans validation, sans confiance,
        sans statut, sans separation fait / hypothese / reponse LLM. Une hallucination
        de l'assistant pouvait donc revenir en contexte au tour suivant et se
        renforcer elle-meme :

            reponse LLM -> rag_chunks global -> retrieval -> nouveau prompt -> ...

        Le journal brut (`conv_archives` + FTS) garde TOUT : on n'efface rien et le
        rappel par agent reste entier. Seule la PROMOTION vers la memoire globale est
        conditionnee. On reutilise le tier guard existant plutot que d'ajouter une
        colonne : `conv_archive` est deja un domaine SKIP_TIER, donc archive et
        auditable mais jamais vectorise.
        """
        conn = self._conn()
        try:
            arch_id = (
                "arch_"
                + hashlib.sha256(f"{self.agent_id}|{msg.timestamp}|{msg.content[:200]}".encode()).hexdigest()[:16]
            )
            now = datetime.now(tz=timezone.utc).isoformat()

            # Insert conv_archives
            conn.execute(
                """
                INSERT OR IGNORE INTO conv_archives
                    (id, agent_id, session_id, role, content,
                     tokens_estimate, archived_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    arch_id,
                    self.agent_id,
                    self.session_id,
                    msg.role,
                    msg.content,
                    msg.tokens_estimate,
                    now,
                    json.dumps(msg.metadata),
                ),
            )

            # Mirror dans rag_chunks pour BGE-M3 embed (retrievable via search GLOBAL).
            # domain="laforge-memory" = SEUL tier agent-memory vectorisable (trigger
            # forge_tier_guard) ; "conv_archive" etait refuse SKIP_TIER = jamais embed.
            chunk_id = f"conv_{arch_id[5:]}"
            domaine, statut = _tier_rag(msg.role)
            conn.execute(
                """
                INSERT OR IGNORE INTO rag_chunks
                    (id, text, source, domain, role_hint, author, ingested_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    chunk_id,
                    # 2026-09-12 : `[:2500]` amputait le corps des messages archives.
                    f"[{msg.role}] {msg.content}",
                    f"conv://{self.agent_id}/{self.session_id}",
                    domaine,
                    f"{self.agent_id}:{msg.role}:{statut}",
                    self.agent_id,
                    now,
                    _meta_verite(msg.role, now),
                ),
            )

            # Index recall FTS5 (recherche archival sans LIKE brut)
            conn.execute(
                "INSERT INTO conv_archives_fts (content, agent_id, arch_id) VALUES (?, ?, ?)",
                (msg.content, self.agent_id, arch_id),
            )

            # Link archive -> rag_chunk
            conn.execute("UPDATE conv_archives SET rag_chunk_id = ? WHERE id = ?", (chunk_id, arch_id))
            conn.commit()
        finally:
            conn.close()

    # --- Core memory (persistent facts) ---

    @staticmethod
    def _statut_tier(role: str) -> tuple:
        """Expose la regle de promotion pour l'inspection et les tests."""
        return _tier_rag(role)

    def set_persona(self, persona: str, user_persona: str = "", facts: str = ""):
        conn = self._conn()
        try:
            now = datetime.now(tz=timezone.utc).isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO core_memory (agent_id, persona, user_persona, facts, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (self.agent_id, persona, user_persona, facts, now),
            )
            conn.commit()
        finally:
            conn.close()

    def get_core(self) -> dict:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT persona, user_persona, facts FROM core_memory WHERE agent_id = ?", (self.agent_id,)
            ).fetchone()
            if not row:
                return {"persona": "", "user_persona": "", "facts": ""}
            return {"persona": row[0] or "", "user_persona": row[1] or "", "facts": row[2] or ""}
        finally:
            conn.close()

    # --- Archival recall (search vectorise via RAG) ---

    @staticmethod
    def _fts_sanitize(query: str) -> str:
        """Tokens alphanum -> requete FTS5 OR-jointe (evite les erreurs de syntaxe
        FTS sur la ponctuation). Vide si aucun token utile."""
        toks = [t for t in re.findall(r"\w+", query or "", flags=re.UNICODE) if len(t) > 1][:12]
        return " OR ".join(toks)

    @staticmethod
    def _epoch_archive(brut) -> tuple:
        """Expose la regle de datation pour l'inspection et les tests."""
        return _epoch_archive(brut)

    def recall(self, query: str, top_k: int = 5, session_filter: bool = False) -> list[ConvMessage]:
        """Search archival memory pour ce query. Filtre par agent_id (+ session si flag).
        FTS5 d'abord (regle maison : jamais de SQL LIKE brut) ; fallback LIKE borne
        si FTS indispo ou zero hit."""
        conn = self._conn()
        try:
            fts_q = self._fts_sanitize(query)
            if fts_q:
                try:
                    sess = " AND a.session_id = ?" if session_filter else ""
                    p = [self.agent_id, fts_q]
                    if session_filter:
                        p.append(self.session_id)
                    p.append(top_k)
                    rows = conn.execute(
                        f"""
                        SELECT a.role, a.content, a.archived_at, a.tokens_estimate, a.metadata
                        FROM conv_archives_fts f
                        JOIN conv_archives a ON a.id = f.arch_id
                        WHERE f.agent_id = ? AND f.content MATCH ?{sess}
                        ORDER BY f.rank, a.archived_at DESC
                        LIMIT ?
                        """,
                        p,
                    ).fetchall()
                    if rows:
                        return [_conv_depuis_ligne(r) for r in rows]
                except sqlite3.Error as e:
                    logger.debug(f"recall FTS fallback ({e}); using LIKE")

            # Fallback : LIKE borne (FTS absent ou zero hit)
            where = "WHERE agent_id = ? AND content LIKE ?"
            params = [self.agent_id, f"%{query[:50]}%"]
            if session_filter:
                where += " AND session_id = ?"
                params.append(self.session_id)
            params.append(top_k)
            rows = conn.execute(
                f"""
                SELECT role, content, archived_at, tokens_estimate, metadata
                FROM conv_archives
                {where}
                ORDER BY archived_at DESC
                LIMIT ?
            """,
                params,
            ).fetchall()
            return [_conv_depuis_ligne(r) for r in rows]
        finally:
            conn.close()

    # --- Context composition ---

    def compose_context(self, recall_query: Optional[str] = None, max_chars: int = 12000) -> str:
        """Compose prompt = core_memory + recalled_archival + main_buffer.
        Format Letta-style avec headers explicites."""
        parts = []
        core = self.get_core()
        if core.get("persona"):
            parts.append(f"### Agent persona\n{core['persona']}")
        if core.get("user_persona"):
            parts.append(f"### User persona\n{core['user_persona']}")
        if core.get("facts"):
            parts.append(f"### Core facts\n{core['facts']}")

        if recall_query:
            recalled = self.recall(recall_query, top_k=5)
            if recalled:
                parts.append("### Recalled from archival memory")
                for m in recalled[:5]:
                    parts.append(f"  [{m.role}] {m.content[:200]}")

        if self.main_buffer:
            parts.append("### Current conversation (main_context)")
            for m in self.main_buffer:
                parts.append(f"  [{m.role}] {m.content[:300]}")

        full = "\n".join(parts)
        return full[:max_chars]

    # --- Stats ---

    def stats(self) -> dict:
        conn = self._conn()
        try:
            n_archived = conn.execute(
                "SELECT COUNT(*) FROM conv_archives WHERE agent_id = ?", (self.agent_id,)
            ).fetchone()[0]
            n_session = conn.execute(
                "SELECT COUNT(*) FROM conv_archives WHERE agent_id = ? AND session_id = ?",
                (self.agent_id, self.session_id),
            ).fetchone()[0]
            return {
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                "main_buffer_size": len(self.main_buffer),
                "main_chars": self._main_chars,
                "archived_total": n_archived,
                "archived_this_session": n_session,
            }
        finally:
            conn.close()


# --- Factory (seam unique pour rendre stateful n'importe quelle logique locale) ---

_MEM_CACHE: dict = {}


def get_agent_memory(agent_id: str, session_id: Optional[str] = None, async_writes: bool = True, **kw):
    """Retourne (cache) l'ArchivalMemory d'un (agent_id, session_id). Point d'entree
    UNIQUE : research_agent, cowork, workers swarm long-run, ou toute logique locale
    qui veut une memoire persistante Letta s'y branchent sans reimplementer l'organe.
    async_writes=True -> archivage en thread daemon (non bloquant, parade R3)."""
    key = (agent_id, session_id or "_default")
    am = _MEM_CACHE.get(key)
    if am is None:
        am = ArchivalMemory(agent_id, session_id=session_id, **kw)
        am.async_writes = async_writes
        _MEM_CACHE[key] = am
    return am


# --- CLI demo ---


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="agt_demo")
    ap.add_argument("--session", default=None)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--recall", help="Query archival recall")
    args = ap.parse_args()

    am = ArchivalMemory(args.agent, session_id=args.session)
    if args.stats:
        print(json.dumps(am.stats(), indent=2))
    if args.recall:
        msgs = am.recall(args.recall, top_k=5)
        for m in msgs:
            print(f"  [{m.role}] {m.content[:120]}")
    if not args.stats and not args.recall:
        # Demo basic
        am.set_persona(
            "Nokido assistant expert code + securite",
            user_persona="user, Python backend dev",
            facts="Project: Nokido sovereign AI hub.",
        )
        am.append("user", "Comment optimiser le RAG retrieval ?")
        am.append("assistant", "Ajouter hop expansion via graph_universal.")
        print(am.compose_context(recall_query="RAG retrieval"))


if __name__ == "__main__":
    main()
