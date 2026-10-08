-- Schema de base d'une installation NEUVE (RAG/embeddings.db), applique par tools/forge_db_bootstrap.py.
--
-- POURQUOI (2026-10-07) : sur machine vierge, aucune etape du chemin documente ne creait ce schema (test
-- d'installation sur runners GitHub, 2e passe : Linux « base absente », Windows fichier cree SANS table, puis
-- « Table rag_chunks missing » a l'import du Knowledge Pack).
--
-- SOURCE : copie de la base vivante qui fait autorite (sqlite_master de %NOKIDO_DATA%\embeddings.db, lecture seule, ce jour),
-- avec IF NOT EXISTS partout : l'amorcage se rejoue sans risque.
-- ECARTE, et pourquoi : auto_snapshot_before_delete/update (exigent rag_snapshots), qdrant_sync_on_embed_* (exigent
-- qdrant_sync_pending ; Qdrant est gele par l'owner), et les tables de maintenance datees rag_fts_cibles_20260823,
-- rag_fts_fantomes_20260823, rag_fts_manquants_20260824. Ce sont des mecanismes du poste de reference : les copier
-- ferait echouer chaque insertion sur une machine qui n'a pas leurs tables.

-- ── memoire RAG ─────────────────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rag_chunks (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,
    domain      TEXT DEFAULT 'general',
    role_hint   TEXT DEFAULT 'chat',
    embedding   BLOB,
    meta        TEXT DEFAULT '{}',
    ingested_at TEXT DEFAULT (datetime('now')),
    author TEXT DEFAULT '', sequence_id INTEGER, session_id TEXT DEFAULT '', version_id TEXT DEFAULT '',
    updated_at TEXT DEFAULT '', hash TEXT, indexed_at TEXT, quality_score REAL DEFAULT NULL, created_at INTEGER,
    origin TEXT GENERATED ALWAYS AS (CASE
      WHEN source LIKE 'gitingest%' THEN 'external-lib'
      WHEN source LIKE '%.pdf' OR domain IN ('nagios_core','vitis_ai') THEN 'external-doc'
      WHEN domain IN ('gitingest','gitingest_litellm','sdk_gitingest','laforge_digest') THEN 'cold-legacy'
      WHEN domain = 'code' THEN 'external-pr'
      WHEN domain = 'mcp_result' THEN 'tool-output'
      WHEN domain = 'longmemeval' THEN 'eval-data'
      WHEN domain = 'conv' OR source LIKE 'conv%' THEN 'conversation'
      WHEN source LIKE 'session:%' OR source LIKE 'anchor%'
           OR domain IN ('autonomous','episodic_memory','longterm_memory','rag') THEN 'laforge-memory'
      WHEN source LIKE 'http%' THEN 'web-crawl'
      WHEN source LIKE 'app/%' OR source LIKE 'tools/%' OR source LIKE 'ctf/%'
           OR source LIKE 'proxy_deno/%' THEN 'laforge-code'
      ELSE 'laforge'
    END) VIRTUAL,
    ext TEXT GENERATED ALWAYS AS (CASE
      WHEN source LIKE '%.py' OR source LIKE '%.py#%' THEN 'py'
      WHEN source LIKE '%.ts' OR source LIKE '%.ts#%' THEN 'ts'
      WHEN source LIKE '%.js' OR source LIKE '%.js#%' THEN 'js'
      WHEN source LIKE '%.md' OR source LIKE '%.md#%' THEN 'md'
      WHEN source LIKE '%.rs' OR source LIKE '%.rs#%' THEN 'rs'
      WHEN source LIKE '%.toml' OR source LIKE '%.toml#%' THEN 'toml'
      WHEN source LIKE '%.json' OR source LIKE '%.json#%' THEN 'json'
      WHEN source LIKE '%.yaml' OR source LIKE '%.yaml#%' THEN 'yaml'
      WHEN source LIKE '%.yml' OR source LIKE '%.yml#%' THEN 'yaml'
      WHEN source LIKE '%.sh' OR source LIKE '%.sh#%' THEN 'sh'
      WHEN source LIKE '%.bat' OR source LIKE '%.bat#%' THEN 'bat'
      WHEN source LIKE '%.ps1' OR source LIKE '%.ps1#%' THEN 'ps1'
      WHEN source LIKE '%.sql' OR source LIKE '%.sql#%' THEN 'sql'
      WHEN source LIKE '%.html' OR source LIKE '%.html#%' THEN 'html'
      WHEN source LIKE '%.css' OR source LIKE '%.css#%' THEN 'css'
      WHEN source LIKE '%.pdf' OR source LIKE '%.pdf#%' THEN 'pdf'
      WHEN source LIKE '%.txt' OR source LIKE '%.txt#%' THEN 'txt'
      ELSE '' END) VIRTUAL,
    folder TEXT GENERATED ALWAYS AS (CASE WHEN instr(source, '/') > 0
      THEN substr(source, 1, instr(source, '/') - 1) ELSE '' END) VIRTUAL,
    lang TEXT GENERATED ALWAYS AS (CASE ext WHEN 'py' THEN 'python' WHEN 'ts' THEN 'typescript'
      WHEN 'js' THEN 'javascript' WHEN 'rs' THEN 'rust' WHEN 'sh' THEN 'shell' WHEN 'ps1' THEN 'powershell'
      WHEN 'md' THEN 'markdown' WHEN 'sql' THEN 'sql' ELSE '' END) VIRTUAL,
    canonical_id TEXT, version TEXT DEFAULT 'v1', superseded_by TEXT, active INTEGER DEFAULT 1,
    epistemic_weight REAL DEFAULT 0.5, last_validated_at TEXT, retraction_status TEXT,
    embedding_model TEXT DEFAULT NULL, access_count INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED);
CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(text, source, domain, content='rag_chunks',
    content_rowid='rowid');

CREATE INDEX IF NOT EXISTS idx_chunks_canonical_active ON rag_chunks(canonical_id, active);
CREATE INDEX IF NOT EXISTS idx_chunks_epistemic ON rag_chunks(epistemic_weight DESC) WHERE active=1;
CREATE INDEX IF NOT EXISTS idx_domain ON rag_chunks(domain);
CREATE INDEX IF NOT EXISTS idx_domain_ext ON rag_chunks(domain, ext);
CREATE INDEX IF NOT EXISTS idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;
CREATE INDEX IF NOT EXISTS idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;
CREATE INDEX IF NOT EXISTS idx_ext ON rag_chunks(ext);
CREATE INDEX IF NOT EXISTS idx_folder ON rag_chunks(folder);
CREATE INDEX IF NOT EXISTS idx_lang ON rag_chunks(lang);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_active ON rag_chunks(active);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_ingested_at ON rag_chunks(ingested_at);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_json_extract_meta_consensus ON rag_chunks(json_extract(meta,'$.consensus_level'));
CREATE INDEX IF NOT EXISTS idx_rag_chunks_json_extract_meta_ingested_a ON rag_chunks(json_extract(meta,'$.ingested_at'));
CREATE INDEX IF NOT EXISTS idx_rag_chunks_role_hint ON rag_chunks(role_hint);
CREATE INDEX IF NOT EXISTS idx_rag_disco ON rag_chunks(role_hint) WHERE role_hint='disco';
CREATE INDEX IF NOT EXISTS idx_rag_domain ON rag_chunks(domain);
CREATE INDEX IF NOT EXISTS idx_rag_fingerprint ON rag_chunks(json_extract(meta,'$.fingerprint'));
CREATE INDEX IF NOT EXISTS idx_rag_origin ON rag_chunks(origin);
CREATE INDEX IF NOT EXISTS idx_rag_ring_expr ON rag_chunks(json_extract(meta,'$.ring'));
CREATE INDEX IF NOT EXISTS idx_rag_seq ON rag_chunks(sequence_id);
CREATE INDEX IF NOT EXISTS idx_rag_session ON rag_chunks(session_id);
CREATE INDEX IF NOT EXISTS idx_rag_source ON rag_chunks(source);
CREATE INDEX IF NOT EXISTS idx_rag_updated ON rag_chunks(updated_at);

CREATE TRIGGER IF NOT EXISTS forge_tier_guard
BEFORE UPDATE OF embedding ON rag_chunks
FOR EACH ROW
WHEN NEW.embedding IS NOT NULL
 AND (CASE WHEN NEW.source LIKE 'gitingest%' THEN 'external-lib' WHEN NEW.source LIKE '%.pdf' OR NEW.domain IN ('nagios_core','vitis_ai') THEN 'external-doc' WHEN NEW.domain IN ('gitingest','gitingest_litellm','sdk_gitingest','laforge_digest') THEN 'cold-legacy' WHEN NEW.domain = 'code' THEN 'external-pr' WHEN NEW.domain = 'mcp_result' THEN 'tool-output' WHEN NEW.domain = 'longmemeval' THEN 'eval-data' WHEN NEW.domain = 'conv' OR NEW.source LIKE 'conv%' THEN 'conversation' WHEN NEW.source LIKE 'session:%' OR NEW.source LIKE 'anchor%' OR NEW.domain IN ('autonomous','episodic_memory','longterm_memory','rag') THEN 'laforge-memory' WHEN NEW.source LIKE 'http%' THEN 'web-crawl' WHEN NEW.source LIKE 'app/%' OR NEW.source LIKE 'tools/%' OR NEW.source LIKE 'ctf/%' OR NEW.source LIKE 'proxy_deno/%' THEN 'laforge-code' ELSE 'laforge' END) NOT IN ('laforge', 'laforge-code', 'laforge-memory', 'web-crawl')
BEGIN
  SELECT RAISE(IGNORE);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_fts_ad AFTER DELETE ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
  VALUES ('delete', old.rowid, old.text, old.source, old.domain);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rowid, text, source, domain)
  VALUES (new.rowid, new.text, new.source, new.domain);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_fts_au AFTER UPDATE OF text, source, domain ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
  VALUES ('delete', old.rowid, old.text, old.source, old.domain); -- l'ancienne entree sort de l'index,
  -- puis la nouvelle y entre (deux instructions, comme dans la base de reference)
  INSERT INTO rag_chunks_fts(rowid, text, source, domain)
  VALUES (new.rowid, new.text, new.source, new.domain);
END;

CREATE TRIGGER IF NOT EXISTS rag_chunks_fts_bi BEFORE INSERT ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
  SELECT 'delete', rowid, text, source, domain FROM rag_chunks
  WHERE id = new.id;
END;

-- ── tables des graines (seed/*.jsonl) ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS biblio_raw (
    id TEXT PRIMARY KEY, type TEXT, title TEXT NOT NULL, authors TEXT, year INTEGER, doi TEXT, url TEXT,
    pdf_url TEXT, description TEXT, triggered_by_idea_id TEXT, source_kind TEXT,
    payload_hash TEXT NOT NULL UNIQUE, parent_hash TEXT, status TEXT DEFAULT 'unverified', rejection_reason TEXT,
    search_results_json TEXT, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT, digested_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_biblio_created ON biblio_raw(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_biblio_idea ON biblio_raw(triggered_by_idea_id);
CREATE INDEX IF NOT EXISTS idx_biblio_status ON biblio_raw(status);
CREATE INDEX IF NOT EXISTS idx_biblio_status_type ON biblio_raw(status, type);
CREATE INDEX IF NOT EXISTS idx_biblio_type ON biblio_raw(type);
CREATE INDEX IF NOT EXISTS idx_biblio_year ON biblio_raw(year);

CREATE TABLE IF NOT EXISTS biblio_topics (
    entry_id TEXT NOT NULL, topic TEXT NOT NULL, weight REAL DEFAULT 1.0, source TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (entry_id, topic),
    FOREIGN KEY (entry_id) REFERENCES biblio_raw(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_topics_entry ON biblio_topics(entry_id);
CREATE INDEX IF NOT EXISTS idx_topics_topic ON biblio_topics(topic);

CREATE TABLE IF NOT EXISTS forge_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('human','llm','worker','system')),
    display_name TEXT NOT NULL,
    ring_level INTEGER NOT NULL DEFAULT 5 CHECK(ring_level BETWEEN 0 AND 10),
    capabilities TEXT NOT NULL DEFAULT '[]', token_hash TEXT DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), last_seen TEXT DEFAULT NULL, meta TEXT NOT NULL DEFAULT '{}',
    os_account TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_ent_active ON forge_entities(is_active);
CREATE INDEX IF NOT EXISTS idx_ent_ring ON forge_entities(ring_level);
CREATE INDEX IF NOT EXISTS idx_ent_type ON forge_entities(entity_type);

CREATE TABLE IF NOT EXISTS system_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT NOT NULL, ring INTEGER DEFAULT 0, title TEXT NOT NULL,
    content TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trajectories (
    job_id TEXT PRIMARY KEY, steps_json TEXT, metadata_json TEXT, started_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_traj_started ON trajectories(started_at);
