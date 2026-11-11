# 01 — Schema : bases et contrats MCP mesures

> Genere par `tools/forge_spec_extractor.py` (introspection, aucune valeur recopiee a la main) -- commit `bffa9f1a0`, 2026-11-11 01:34. Ne pas editer : relancer l'extracteur.


<!-- nokido:dynamique -->
## Bases (organe proprietaire : `forge_db_path`)

### rag (db_path) = bareme (authority_path) = journal conversation_log
`%NOKIDO_DATA%\embeddings.db` -- journal `wal`, 130 table(s), 269 objet(s)

```sql
CREATE INDEX idx_agent_messages_corr ON agent_messages(correlation_id);
CREATE INDEX idx_agent_messages_created_at ON agent_messages(created_at);
CREATE INDEX idx_agent_messages_from_agent ON agent_messages(from_agent);
CREATE INDEX idx_agent_messages_method ON agent_messages(method);
CREATE INDEX idx_agent_messages_status ON agent_messages(status);
CREATE INDEX idx_agent_messages_to ON agent_messages(to_agent, status);
CREATE INDEX idx_ai_surprise_ts ON active_inference_surprises(ts);
CREATE INDEX idx_archives_agent ON conv_archives(agent_id, archived_at);
CREATE INDEX idx_archives_session ON conv_archives(session_id);
CREATE INDEX idx_autoloop_audit_ts ON autonomous_loop_audit(ts);
CREATE INDEX idx_biblio_created ON biblio_raw(created_at DESC);
CREATE INDEX idx_biblio_idea   ON biblio_raw(triggered_by_idea_id);
CREATE INDEX idx_biblio_link_source ON biblio_link(source);
CREATE INDEX idx_biblio_status ON biblio_raw(status);
CREATE INDEX idx_biblio_status_type ON biblio_raw(status, type);
CREATE INDEX idx_biblio_type   ON biblio_raw(type);
CREATE INDEX idx_biblio_year   ON biblio_raw(year);
CREATE INDEX idx_chain_status ON agent_chain_nodes(status, chain_id);
CREATE INDEX idx_chunk_claims_chunk ON chunk_claims(chunk_id);
CREATE INDEX idx_chunks_canonical_active
        ON rag_chunks(canonical_id, active);
CREATE INDEX idx_chunks_epistemic
        ON rag_chunks(epistemic_weight DESC) WHERE active=1;
CREATE INDEX idx_ci_risk ON commit_intel(risk_level);
CREATE INDEX idx_ci_scope ON commit_intel(scope);
CREATE INDEX idx_claims_chunk ON chunk_claims(chunk_id);
CREATE INDEX idx_claims_extracted ON chunk_claims(extracted_at);
CREATE INDEX idx_coag_status ON coagulation_events(status);
CREATE INDEX idx_coag_worker ON coagulation_events(worker);
CREATE INDEX idx_cold_storage_domain ON rag_chunks_cold_storage(domain);
CREATE INDEX idx_cold_storage_id ON rag_chunks_cold_storage(id);
CREATE INDEX idx_cold_storage_source ON rag_chunks_cold_storage(source);
CREATE INDEX idx_conversation_log_session_id ON conversation_log(session_id);
CREATE INDEX idx_darwinian_status ON darwinian_candidates(status);
CREATE INDEX idx_domain ON rag_chunks(domain);
CREATE INDEX idx_domain_ext ON rag_chunks(domain, ext);
CREATE INDEX idx_emb_created    ON embeddings(created_at);
CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;
CREATE INDEX idx_emb_seq        ON embeddings(sequence_id);
CREATE INDEX idx_embed_a_faire ON rag_chunks(id) WHERE embedding IS NULL AND embedding_model IS NULL;
CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;
CREATE INDEX idx_endocrine_released ON endocrine_signals(released_at);
CREATE INDEX idx_ent_active ON forge_entities(is_active);
CREATE INDEX idx_ent_ring ON forge_entities(ring_level);
CREATE INDEX idx_ent_type ON forge_entities(entity_type);
CREATE INDEX idx_esess_ent ON entity_sessions(entity_id);
CREATE INDEX idx_event_log_agent_id ON event_log(agent_id);
CREATE INDEX idx_evlog_seq        ON event_log(sequence_id);
CREATE INDEX idx_evlog_session    ON event_log(session_id);
CREATE INDEX idx_evlog_target     ON event_log(target);
CREATE INDEX idx_evlog_timecode   ON event_log(timecode);
CREATE INDEX idx_evlog_type       ON event_log(event_type);
CREATE INDEX idx_evol_method ON motivation_evolution_notes(method);
CREATE INDEX idx_evol_ts ON motivation_evolution_notes(ts);
CREATE INDEX idx_ext ON rag_chunks(ext);
CREATE INDEX idx_feedback_chunk ON synaptic_feedback_log(chunk_id);
CREATE INDEX idx_feedback_ts ON synaptic_feedback_log(ts);
CREATE INDEX idx_folder ON rag_chunks(folder);
CREATE INDEX idx_gre_dst ON rag_graph_edges(dst);
CREATE INDEX idx_gre_src ON rag_graph_edges(src);
CREATE INDEX idx_il_id ON instruction_library(id);
CREATE INDEX idx_immune_kind ON immune_antibodies(kind);
CREATE INDEX idx_immune_seen ON immune_antibodies(last_seen DESC);
CREATE INDEX idx_jobs_agent ON jobs_state(agent);
CREATE INDEX idx_jobs_status ON jobs_state(status);
CREATE INDEX idx_jobs_trace ON jobs_state(trace_id);
CREATE INDEX idx_jti_exp ON jti_cache(exp);
CREATE INDEX idx_lang ON rag_chunks(lang);
CREATE INDEX idx_link_dst  ON biblio_link(dst_id);
CREATE INDEX idx_link_kind ON biblio_link(kind);
CREATE INDEX idx_link_src  ON biblio_link(src_id);
CREATE INDEX idx_locks_owner ON locks_state(owner_agent);
CREATE INDEX idx_locks_state ON locks_state(state);
CREATE INDEX idx_motiv_dead ON motivation_failures(dead_end);
CREATE INDEX idx_network_log_agent ON network_log(agent);
CREATE INDEX idx_network_log_channel ON network_log(channel);
CREATE INDEX idx_nl_ts      ON network_log(ts DESC);
CREATE INDEX idx_novelty_method ON novelty_archive(method);
CREATE INDEX idx_novelty_ts ON novelty_archive(ts);
CREATE INDEX idx_opsec_audit_ts ON opsec_audit_log(ts);
CREATE INDEX idx_orec_pending ON orchestrator_recommendations(applied_at) WHERE applied_at IS NULL;
CREATE INDEX idx_pq_priority ON promotion_queue(priority);
CREATE INDEX idx_pq_status ON promotion_queue(status);
CREATE INDEX idx_promcp_tool_metrics_ts ON promcp_tool_metrics(ts);
CREATE INDEX idx_promcp_tool_ts ON promcp_tool_metrics(tool, ts);
CREATE INDEX idx_provider_scores_status ON provider_scores(status);
CREATE INDEX idx_query_log_query ON query_log(query_text);
CREATE INDEX idx_query_log_ts ON query_log(timestamp);
CREATE INDEX idx_rag_chunks_active ON rag_chunks(active);
CREATE INDEX idx_rag_chunks_hash ON rag_chunks(hash);
CREATE INDEX idx_rag_chunks_ingested_at ON rag_chunks(ingested_at);
CREATE INDEX idx_rag_chunks_json_extract_meta_consensus ON rag_chunks(json_extract(meta,'$.consensus_level'));
CREATE INDEX idx_rag_chunks_json_extract_meta_ingested_a ON rag_chunks(json_extract(meta,'$.ingested_at'));
CREATE INDEX idx_rag_chunks_role_hint ON rag_chunks(role_hint);
CREATE INDEX idx_rag_disco ON rag_chunks(role_hint) WHERE role_hint='disco';
CREATE INDEX idx_rag_domain ON rag_chunks(domain);
CREATE INDEX idx_rag_fingerprint ON rag_chunks(json_extract(meta,'$.fingerprint'));
CREATE INDEX idx_rag_graph_edges_rel_type ON rag_graph_edges(rel_type);
CREATE INDEX idx_rag_origin ON rag_chunks(origin);
CREATE INDEX idx_rag_ring_expr ON rag_chunks(json_extract(meta,'$.ring'));
CREATE INDEX idx_rag_seq        ON rag_chunks(sequence_id);
CREATE INDEX idx_rag_session    ON rag_chunks(session_id);
CREATE INDEX idx_rag_snapshots_op ON rag_snapshots(op);
CREATE INDEX idx_rag_source ON rag_chunks(source);
CREATE INDEX idx_rag_updated    ON rag_chunks(updated_at);
CREATE INDEX idx_rbac_audit_ts ON rbac_mapping_audit(ts);
CREATE INDEX idx_reeval_newer ON claim_reevaluations(newer_claim_id);
CREATE INDEX idx_reeval_older ON claim_reevaluations(older_claim_id, reevaluation_type);
CREATE INDEX idx_snap_chunk     ON rag_snapshots(chunk_id);
CREATE INDEX idx_snap_seq       ON rag_snapshots(sequence_id);
CREATE INDEX idx_snap_session   ON rag_snapshots(session_id);
CREATE INDEX idx_snap_timecode  ON rag_snapshots(timecode);
CREATE INDEX idx_spl_agent    ON shared_prompt_log(agent_id);
CREATE INDEX idx_spl_mode     ON shared_prompt_log(mode);
CREATE INDEX idx_spl_session  ON shared_prompt_log(session_id);
CREATE INDEX idx_spl_timecode ON shared_prompt_log(timecode);
CREATE INDEX idx_switches_agent ON access_switches(agent_pattern);
CREATE INDEX idx_switches_expires ON access_switches(expires_at)
    WHERE expires_at IS NOT NULL;
CREATE INDEX idx_tasks_created    ON agent_tasks(created_at DESC);
CREATE INDEX idx_tasks_executor   ON agent_tasks(executor);
CREATE INDEX idx_tasks_intent_hash ON agent_tasks(intent_hash);
CREATE INDEX idx_tasks_seq      ON agent_tasks(sequence_id);
CREATE INDEX idx_tasks_session  ON agent_tasks(session_id);
CREATE INDEX idx_tasks_status     ON agent_tasks(status);
CREATE INDEX idx_tasks_type_verdict ON agent_tasks(task_type, forge_verdict);
CREATE INDEX idx_tasks_verdict_status ON agent_tasks(forge_verdict, status);
CREATE INDEX idx_topics_entry ON biblio_topics(entry_id);
CREATE INDEX idx_topics_topic ON biblio_topics(topic);
CREATE INDEX idx_traj_started ON trajectories(started_at);
CREATE INDEX idx_tu_agent ON token_usage(agent_id);
CREATE INDEX idx_tu_ts ON token_usage(ts DESC);
CREATE INDEX idx_watch_status ON watch_jobs(status, step);
CREATE TABLE access_switches (
    id              TEXT PRIMARY KEY,
    agent_pattern   TEXT NOT NULL,       -- fnmatch : 'GEMINI' | 'GEM*' | '*'
    resource_pattern TEXT NOT NULL,      -- fnmatch : 'sandbox/*' | 'app/*.py'
    action          TEXT NOT NULL,       -- write | read | run | query | *
    allowed         INTEGER NOT NULL DEFAULT 1,  -- 1=allow 0=deny
    condition_dsl   TEXT DEFAULT NULL,   -- DSL sandboxé ou NULL (pas de condition)
    expires_at      TEXT DEFAULT NULL,   -- ISO8601 UTC ou NULL (permanent)
    granted_by      TEXT NOT NULL,       -- agent ring 0 qui a accordé
    grant_reason    TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    version         INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE active_inference_priors (
    method TEXT NOT NULL,
    target_class TEXT,
    n_observations INTEGER DEFAULT 0,
    p_success REAL DEFAULT 0.5,
    mean_time_s REAL DEFAULT 1.0,
    var_time_s REAL DEFAULT 1.0,
    mean_elegance REAL DEFAULT 1.0,
    var_elegance REAL DEFAULT 0.5,
    last_updated REAL,
    PRIMARY KEY (method, target_class)
);
CREATE TABLE active_inference_signals (
    signal TEXT NOT NULL,
    context TEXT NOT NULL,
    n INTEGER DEFAULT 0,
    mean REAL DEFAULT 0.0,
    m2 REAL DEFAULT 0.0,
    last_updated REAL,
    PRIMARY KEY (signal, context)
);
CREATE TABLE active_inference_surprises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT,
    target_class TEXT,
    predicted_p_success REAL,
    actual_success INTEGER,
    predicted_time_s REAL,
    actual_time_s REAL,
    predicted_elegance REAL,
    actual_elegance REAL,
    surprise REAL,
    free_energy REAL,
    ts REAL NOT NULL
);
CREATE TABLE adr_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    adr_id      TEXT NOT NULL UNIQUE,          -- ADR-001, ADR-002...
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'Proposé', -- Proposé|Accepté|Obsolète|Supersédé
    context     TEXT NOT NULL DEFAULT '',
    decision    TEXT NOT NULL DEFAULT '',
    consequences_pos TEXT DEFAULT '',
    consequences_neg TEXT DEFAULT '',
    related_adr TEXT DEFAULT '',               -- JSON liste IDs liés
    tags        TEXT DEFAULT '',               -- JSON liste tags
    ring        INTEGER DEFAULT 1,             -- ring concerné
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    author      TEXT DEFAULT 'laforge',
    embedding_id INTEGER DEFAULT 0            -- lien vers rag_chunks
);
CREATE TABLE agent_chain_context (
    chain_id     TEXT PRIMARY KEY,
    global_vars  TEXT,
    updated_at   TEXT DEFAULT (datetime('now'))
);
CREATE TABLE agent_chain_nodes (
    id           TEXT PRIMARY KEY,
    chain_id     TEXT NOT NULL,
    step_index   INTEGER NOT NULL,
    step_name    TEXT NOT NULL,
    agent_role   TEXT NOT NULL,
    llm_preferred TEXT NOT NULL,
    llm_fallback  TEXT,
    input_from   TEXT,
    output_key   TEXT,
    status       TEXT DEFAULT 'pending',
    retry_count  INTEGER DEFAULT 0,
    max_retries  INTEGER DEFAULT 3,
    result_json  TEXT,
    error        TEXT,
    started_at   TEXT,
    done_at      TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
, runner_pid INTEGER, runner_cree REAL);
CREATE TABLE agent_chain_nodes_bak_20260528_181622(
  id TEXT,
  chain_id TEXT,
  step_index INT,
  step_name TEXT,
  agent_role TEXT,
  llm_preferred TEXT,
  llm_fallback TEXT,
  input_from TEXT,
  output_key TEXT,
  status TEXT,
  retry_count INT,
  max_retries INT,
  result_json TEXT,
  error TEXT,
  started_at TEXT,
  done_at TEXT,
  created_at TEXT
);
CREATE TABLE agent_chain_nodes_bak_20260528_214918(
  id TEXT,
  chain_id TEXT,
  step_index INT,
  step_name TEXT,
  agent_role TEXT,
  llm_preferred TEXT,
  llm_fallback TEXT,
  input_from TEXT,
  output_key TEXT,
  status TEXT,
  retry_count INT,
  max_retries INT,
  result_json TEXT,
  error TEXT,
  started_at TEXT,
  done_at TEXT,
  created_at TEXT
);
CREATE TABLE agent_chain_nodes_bak_20260528_225202(
  id TEXT,
  chain_id TEXT,
  step_index INT,
  step_name TEXT,
  agent_role TEXT,
  llm_preferred TEXT,
  llm_fallback TEXT,
  input_from TEXT,
  output_key TEXT,
  status TEXT,
  retry_count INT,
  max_retries INT,
  result_json TEXT,
  error TEXT,
  started_at TEXT,
  done_at TEXT,
  created_at TEXT
);
CREATE TABLE agent_chain_nodes_bak_20260529_001735(
  id TEXT,
  chain_id TEXT,
  step_index INT,
  step_name TEXT,
  agent_role TEXT,
  llm_preferred TEXT,
  llm_fallback TEXT,
  input_from TEXT,
  output_key TEXT,
  status TEXT,
  retry_count INT,
  max_retries INT,
  result_json TEXT,
  error TEXT,
  started_at TEXT,
  done_at TEXT,
  created_at TEXT
);
CREATE TABLE agent_messages (
    id            TEXT PRIMARY KEY,
    from_agent    TEXT NOT NULL,
    to_agent      TEXT NOT NULL,
    correlation_id TEXT,
    method        TEXT NOT NULL,
    payload       TEXT,
    result        TEXT,
    status        TEXT DEFAULT 'pending',
    created_at    TEXT DEFAULT (datetime('now')),
    read_at       TEXT
);
CREATE TABLE agent_profiles (
    agent_id        TEXT PRIMARY KEY,
    display_name    TEXT,
    tier            TEXT,
    specialites     TEXT,
    trait_humain    TEXT,
    limitations     TEXT,
    benchmarks      TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE TABLE agent_quota (
                agent_id   TEXT PRIMARY KEY,
                iter_count INTEGER DEFAULT 0,
                call_count INTEGER DEFAULT 0,
                last_reset TEXT DEFAULT (datetime('now')),
                blocked    INTEGER DEFAULT 0
            );
CREATE TABLE agent_tasks (
    -- Identité
    id           TEXT PRIMARY KEY,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now')),

    -- Rôles (interchangeables)
    orchestrator TEXT NOT NULL DEFAULT 'laforge',
    executor     TEXT NOT NULL DEFAULT 'any',

    -- Tâche
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    task_type    TEXT DEFAULT 'generic',
    priority     INTEGER DEFAULT 5,

    -- Plan structuré — JSON écrit par l'orchestrateur
    -- [{"step": 1, "action": "...", "tool": "...", "status": "pending"}]
    plan         TEXT DEFAULT '[]',

    -- État
    status       TEXT DEFAULT 'pending',
    -- pending → assigned → running → review → done | failed | cancelled

    -- Résultats — JSON écrit par l'exécutant
    -- [{"step": 1, "output": "...", "ok": true}]
    results      TEXT DEFAULT '[]',

    -- Validation La Forge
    forge_verdict TEXT DEFAULT '',   -- approved | rejected | amended
    forge_notes   TEXT DEFAULT '',

    -- Contexte RAG injecté par La Forge avant délégation
    rag_context  TEXT DEFAULT '',

    -- Métadonnées
    meta         TEXT DEFAULT '{}'
, sequence_id INTEGER, session_id  TEXT DEFAULT '', intent_embedding BLOB DEFAULT NULL, intent_hash TEXT DEFAULT '', bypass_llm INTEGER DEFAULT 0, replay_count INTEGER DEFAULT 0);
CREATE TABLE autonomous_loop_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    ts REAL NOT NULL,
    status TEXT,
    outcome TEXT,
    details TEXT
);
CREATE TABLE autonomous_loop_state (
    pattern TEXT PRIMARY KEY,
    last_run REAL DEFAULT 0,
    last_status TEXT,
    last_outcome TEXT,
    runs_total INTEGER DEFAULT 0,
    runs_success INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1
);
CREATE TABLE biblio_link (
    src_id   TEXT NOT NULL,
    dst_id   TEXT NOT NULL,
    kind     TEXT NOT NULL,
    weight   REAL DEFAULT 1.0,
    source   TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (src_id, dst_id, kind),
    FOREIGN KEY (src_id) REFERENCES biblio_raw(id) ON DELETE CASCADE,
    FOREIGN KEY (dst_id) REFERENCES biblio_raw(id) ON DELETE CASCADE
);
CREATE TABLE biblio_raw (
        id              TEXT PRIMARY KEY,
        type            TEXT,
        title           TEXT NOT NULL,
        authors         TEXT,
        year            INTEGER,
        doi             TEXT,
        url             TEXT,
        pdf_url         TEXT,
        description     TEXT,
        triggered_by_idea_id TEXT,
        source_kind     TEXT,
        payload_hash    TEXT NOT NULL UNIQUE,
        parent_hash     TEXT,
        status          TEXT DEFAULT 'unverified',
        rejection_reason TEXT,
        search_results_json TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT
    , digested_at TEXT);
CREATE TABLE biblio_topics (
    entry_id  TEXT NOT NULL,
    topic     TEXT NOT NULL,
    weight    REAL DEFAULT 1.0,
    source    TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (entry_id, topic),
    FOREIGN KEY (entry_id) REFERENCES biblio_raw(id) ON DELETE CASCADE
);
CREATE TABLE bibliography (
        id                  TEXT PRIMARY KEY,
        promoted_from_raw_id TEXT,
        title               TEXT NOT NULL,
        authors             TEXT,
        year                INTEGER,
        doi                 TEXT,
        url                 TEXT,
        pdf_url             TEXT,
        description         TEXT,
        promoted_by         TEXT,
        promoted_at         TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE canary_alerts (ts TEXT, session_id TEXT, canary TEXT, payload TEXT, status TEXT);
CREATE TABLE chunk_claims (
    id TEXT PRIMARY KEY,                       -- hash sha256[:16] de (chunk_id + text)
    chunk_id TEXT NOT NULL,                    -- FK rag_chunks.id
    text TEXT NOT NULL,                        -- claim atomique (1-2 phrases)
    predicates TEXT,                           -- JSON list: ["undetectable", "JPEG", "LSB"]
    confidence_authored REAL DEFAULT 0.5,      -- confidence du LLM extractor
    is_technical INTEGER DEFAULT 1,            -- 1=technique (testable), 0=normatif (opinion)
    abstract_embedding BLOB,                   -- BGE-M3 embedding du 1er tiers (768 floats = 3072 bytes)
    extracted_by TEXT,                         -- modele extractor: cerebras_llama-3.3-70b
    extracted_at TEXT DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (chunk_id) REFERENCES rag_chunks(id) ON DELETE CASCADE
);
CREATE TABLE claim_reevaluations (
    older_claim_id TEXT NOT NULL,
    newer_claim_id TEXT NOT NULL,
    reevaluation_type TEXT NOT NULL,           -- supports|contradicts|qualifies|supersedes|extends
    confidence REAL DEFAULT 0.5,               -- confidence du judge
    rationale TEXT,                            -- explication courte
    detected_by TEXT,                          -- model judge: cerebras_llama-3.3-70b
    detected_at TEXT DEFAULT (datetime('now', 'utc')),
    PRIMARY KEY (older_claim_id, newer_claim_id),
    FOREIGN KEY (older_claim_id) REFERENCES chunk_claims(id) ON DELETE CASCADE,
    FOREIGN KEY (newer_claim_id) REFERENCES chunk_claims(id) ON DELETE CASCADE
);
CREATE TABLE coagulation_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        worker      TEXT NOT NULL,
        severity    TEXT NOT NULL,    -- minor / major / embolie
        state_snapshot TEXT,
        status      TEXT NOT NULL,    -- active / dissolved / escalated
        ts_detected TEXT NOT NULL,
        ts_resolved TEXT
    );
CREATE TABLE commit_intel (
                sha TEXT PRIMARY KEY,
                short_sha TEXT,
                subject TEXT,
                commit_type TEXT,
                scope TEXT,
                date TEXT,
                modules_modified TEXT,       -- JSON
                symbols_added TEXT,           -- JSON
                symbols_modified TEXT,        -- JSON
                critical_symbols TEXT,        -- JSON
                modules_impacted TEXT,        -- JSON
                danger_patterns TEXT,         -- JSON
                risk_score REAL,
                risk_level TEXT,
                stats TEXT,                   -- JSON
                analyzed_at TEXT DEFAULT (datetime('now'))
            );
CREATE TABLE compute_nodes (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL CHECK(node_type IN ('docker','kaggle','local','ollama','llamacpp')),
    status      TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('ready','busy','offline','unknown')),
    capacity    INTEGER DEFAULT 1,
    current_load INTEGER DEFAULT 0,
    endpoint    TEXT DEFAULT '',
    last_seen   TEXT DEFAULT (datetime('now')),
    meta        TEXT DEFAULT '{}'
);
CREATE TABLE conv_archives (
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
CREATE VIRTUAL TABLE conv_archives_fts USING fts5(
    content,
    agent_id UNINDEXED,
    arch_id UNINDEXED,
    tokenize = 'porter unicode61'
);
CREATE TABLE 'conv_archives_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'conv_archives_fts_content'(id INTEGER PRIMARY KEY, c0, c1, c2);
CREATE TABLE 'conv_archives_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'conv_archives_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE 'conv_archives_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE conversation_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    ts           TEXT NOT NULL DEFAULT (datetime('now')),
    agent        TEXT NOT NULL DEFAULT 'CLAUDE',
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    turn_index   INTEGER DEFAULT 0,
    meta         TEXT DEFAULT '{}'
);
CREATE TABLE core_memory (
    agent_id TEXT PRIMARY KEY,
    persona TEXT,
    user_persona TEXT,
    facts TEXT,
    updated_at TEXT DEFAULT (datetime('now', 'utc'))
);
CREATE TABLE corrigibility_state (key TEXT PRIMARY KEY, value TEXT, set_by TEXT, reason TEXT, ts REAL);
CREATE TABLE darwinian_candidates (
        candidate_id     TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        code_content     TEXT NOT NULL,
        author           TEXT NOT NULL,
        ring             INTEGER NOT NULL,
        status           TEXT NOT NULL,
        submitted_at     TEXT NOT NULL,
        quarantine_until TEXT NOT NULL,
        trust_score      REAL NOT NULL,
        test_runs        INTEGER NOT NULL,
        test_passes      INTEGER NOT NULL,
        logs             TEXT NOT NULL,
        meta             TEXT NOT NULL
    );
CREATE TABLE delivery_integrity_findings (id TEXT PRIMARY KEY, kind TEXT, target TEXT, severity TEXT, detail TEXT, created_at TEXT, acked_at TEXT, ack_motif TEXT);
CREATE TABLE dsl_templates (
        template_id TEXT PRIMARY KEY,
        dsl         TEXT NOT NULL,
        expansion_json TEXT,
        usage_count INTEGER DEFAULT 1,
        created_at  TEXT DEFAULT (datetime('now')),
        last_used   TEXT
    );
CREATE TABLE edge_nodes (
    node_id       TEXT PRIMARY KEY,
    node_type     TEXT NOT NULL DEFAULT 'petal'
                  CHECK(node_type IN ('hub','petal','tulip','edge','wasm')),
    hostname      TEXT NOT NULL DEFAULT '',
    endpoint      TEXT DEFAULT '',
    os_type       TEXT DEFAULT 'unknown'
                  CHECK(os_type IN ('windows','linux','macos','android','wasm','unknown')),
    arch          TEXT DEFAULT 'x86_64'
                  CHECK(arch IN ('x86_64','arm64','armv7','wasm32','unknown')),
    capabilities  TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'offline'
                  CHECK(status IN ('online','offline','busy','degraded')),
    replication   TEXT DEFAULT 'none'
                  CHECK(replication IN ('none','litefs_read','litefs_write','manual')),
    last_seen     TEXT DEFAULT (datetime('now')),
    max_tasks     INTEGER DEFAULT 1,
    current_tasks INTEGER DEFAULT 0,
    meta          TEXT DEFAULT '{}'
);
CREATE TABLE embeddings (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT,
    embedding TEXT
, sequence_id INTEGER, session_id  TEXT DEFAULT '', created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '');
CREATE TABLE endocrine_rhythm_state (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        rhythm      TEXT NOT NULL,
        set_at      TEXT NOT NULL,
        ttl_s       INTEGER NOT NULL,
        reason      TEXT,
        source      TEXT
    );
CREATE TABLE endocrine_signals (
        hormone     TEXT PRIMARY KEY,
        level       REAL NOT NULL,
        released_at TEXT NOT NULL,
        ttl_s       INTEGER NOT NULL,
        half_life_s INTEGER NOT NULL,
        source      TEXT NOT NULL,
        reason      TEXT,
        meta        TEXT
    , episode_start TEXT, renew_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE entity_sessions (
    session_id    TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at      TEXT DEFAULT NULL,
    ip_hash       TEXT DEFAULT '',
    mode          TEXT DEFAULT 'solo',
    meta          TEXT DEFAULT '{}'
);
CREATE TABLE entity_tools_grant (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   TEXT NOT NULL REFERENCES forge_entities(entity_id),
    tool_name   TEXT NOT NULL REFERENCES forge_tools(tool_name),
    granted_by  TEXT NOT NULL DEFAULT 'usr_naarob',
    granted_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT DEFAULT NULL,
    reason      TEXT DEFAULT '',
    UNIQUE(entity_id, tool_name)
);
CREATE TABLE epistemic_extraction_vue (chunk_id TEXT PRIMARY KEY, statut TEXT NOT NULL, extracteur TEXT, vu_at TEXT NOT NULL);
CREATE TABLE epistemic_seen (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT,
    verdict TEXT,
    score REAL,
    seen_at REAL
);
CREATE TABLE event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timecode    TEXT    NOT NULL,          -- ISO8601 + ms : 2026-03-14T04:15:02.123Z
    sequence_id INTEGER NOT NULL,          -- monotone global, résout les collisions ms
    session_id  TEXT    NOT NULL DEFAULT '',
    agent_id    TEXT    NOT NULL DEFAULT 'laforge',
    event_type  TEXT    NOT NULL,          -- write | ingest | task_create | tool_call | ...
    target      TEXT    NOT NULL DEFAULT '',  -- path / chunk_id / task_id
    payload     TEXT    NOT NULL DEFAULT '{}', -- JSON des args
    prev_hash   TEXT    NOT NULL DEFAULT '',   -- hash de l'état précédent (Vector Clock)
    new_hash    TEXT    NOT NULL DEFAULT '',   -- hash après l'événement
    status      TEXT    NOT NULL DEFAULT 'ok'  -- ok | conflict | rolled_back
, backup_path TEXT DEFAULT '', checksum_before TEXT DEFAULT '');
CREATE TABLE event_log_archive(
  id INT,
  timecode TEXT,
  sequence_id INT,
  session_id TEXT,
  agent_id TEXT,
  event_type TEXT,
  target TEXT,
  payload TEXT,
  prev_hash TEXT,
  new_hash TEXT,
  status TEXT,
  backup_path TEXT,
  checksum_before TEXT
);
CREATE TABLE experience_replay (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    context_summary TEXT,
    friction TEXT,
    pivot TEXT,
    heuristique TEXT NOT NULL,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    weight REAL DEFAULT 0.5,
    agent_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_confirmed_at TEXT
);
CREATE TABLE file_hashes (
        path TEXT PRIMARY KEY,
        hash TEXT,
        size  INTEGER,
        mtime REAL,
        updated_at TEXT
    );
CREATE TABLE file_index (
        path TEXT PRIMARY KEY,
        hash TEXT,
        size INTEGER,
        mtime REAL,
        updated_at TEXT
    );
CREATE TABLE fleet_heartbeats (
    node_id         TEXT PRIMARY KEY,
    node_type       TEXT NOT NULL DEFAULT 'bridge',
    last_ping_at    TEXT DEFAULT (datetime('now')),
    last_ping_ms    REAL DEFAULT 0,
    status          TEXT DEFAULT 'unknown',
    missed_count    INTEGER DEFAULT 0,
    meta            TEXT DEFAULT '{}'
);
CREATE TABLE forge_entities (
    entity_id     TEXT PRIMARY KEY,
    entity_type   TEXT NOT NULL CHECK(entity_type IN ('human','llm','worker','system')),
    display_name  TEXT NOT NULL,
    ring_level    INTEGER NOT NULL DEFAULT 5 CHECK(ring_level BETWEEN 0 AND 10),
    capabilities  TEXT NOT NULL DEFAULT '[]',
    token_hash    TEXT DEFAULT '',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen     TEXT DEFAULT NULL,
    meta          TEXT NOT NULL DEFAULT '{}'
, os_account TEXT DEFAULT NULL);
CREATE TABLE forge_pool_registry (
            member TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            capability_tags TEXT NOT NULL,
            cost REAL DEFAULT 0.0,
            latency_ms REAL DEFAULT 1000.0,
            quota_restant REAL DEFAULT 100.0,
            available INTEGER DEFAULT 1,
            last_updated REAL NOT NULL
        );
CREATE TABLE forge_tools (
    tool_name       TEXT PRIMARY KEY,
    description     TEXT NOT NULL DEFAULT '',
    description_hash TEXT DEFAULT '',
    min_ring        INTEGER NOT NULL DEFAULT 2,
    is_active       INTEGER NOT NULL DEFAULT 1,
    category        TEXT DEFAULT 'general',
    timeout_s       INTEGER DEFAULT 30,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    meta            TEXT DEFAULT '{}'
);
CREATE TABLE git_historian_state (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                last_sha    TEXT,
                last_run_at TEXT DEFAULT (datetime('now')),
                indexed_n   INTEGER DEFAULT 0,
                skipped_n   INTEGER DEFAULT 0,
                adr_created INTEGER DEFAULT 0
            );
CREATE TABLE global_sequence (
    id          INTEGER PRIMARY KEY,       -- toujours 1 (singleton)
    last_seq    INTEGER NOT NULL DEFAULT 0,
    last_tick   TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE goap_plans (
                plan_id TEXT PRIMARY KEY,
                goal TEXT,
                plan_json TEXT,
                ring_max INTEGER,
                created_at REAL
            );
CREATE TABLE golden_paths (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_hash     TEXT NOT NULL UNIQUE,
    intent_sample   TEXT NOT NULL DEFAULT '',
    dag_plan_json   TEXT NOT NULL DEFAULT '[]',
    execution_ms    REAL DEFAULT 0,
    success_count   INTEGER DEFAULT 1,
    failure_count   INTEGER DEFAULT 0,
    last_used_at    TEXT DEFAULT (datetime('now')),
    created_at      TEXT DEFAULT (datetime('now')),
    created_by      TEXT DEFAULT 'laforge'
);
CREATE TABLE immune_antibodies (
        signature_hash TEXT PRIMARY KEY,
        pattern        TEXT NOT NULL,
        kind           TEXT NOT NULL,   -- injection / ssrf / pii_leak / canary / unknown
        count          INTEGER NOT NULL DEFAULT 1,
        first_seen     TEXT NOT NULL,
        last_seen      TEXT NOT NULL,
        severity       REAL NOT NULL,   -- 0.0-1.0
        confidence     REAL NOT NULL,   -- monte avec count
        meta           TEXT
    );
CREATE TABLE inspector_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT (datetime('now')),
                    status TEXT, ports_down INTEGER,
                    zombies INTEGER, errors INTEGER,
                    cpu_pct REAL, ram_pct REAL,
                    detail TEXT);
CREATE TABLE instruction_library (
    id          TEXT PRIMARY KEY,      -- §AUDIT:v1, §ZOTERO:v2...
    name        TEXT,
    version     TEXT DEFAULT 'v1',
    system_prompt TEXT,
    template    TEXT DEFAULT '',       -- {{target}} {{ring}} etc.
    variables   TEXT DEFAULT '[]',     -- JSON list des variables
    provider_hint TEXT DEFAULT '',     -- gemini | groq | mistral | any
    ring_minimum INTEGER DEFAULT 0,
    token_estimate INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE jobs_state (
                job_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                intent_type TEXT,
                parent_id TEXT,
                trace_id TEXT,
                payload_json TEXT,
                status TEXT NOT NULL,
                created_at INTEGER,
                updated_at INTEGER,
                error TEXT,
                result_summary TEXT
            );
CREATE TABLE jti_cache (
        jti  TEXT PRIMARY KEY,
        exp  INTEGER NOT NULL,
        agent TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE locks_state (
                resource TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                owner_agent TEXT,
                owner_token TEXT,
                locked_at REAL,
                released_at REAL,
                timeout_s REAL,
                queue_size INTEGER DEFAULT 0
            );
CREATE TABLE metric_integrity_findings (id TEXT PRIMARY KEY, kind TEXT, target TEXT, severity TEXT, detail TEXT, created_at TEXT);
CREATE TABLE motivation_evolution_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    note TEXT,
    elegance_before REAL,
    elegance_after REAL,
    ts REAL NOT NULL
);
CREATE TABLE motivation_failures (
    method TEXT NOT NULL,
    target TEXT,
    failure_count INTEGER DEFAULT 0,
    last_failure_at REAL,
    last_error TEXT,
    dead_end INTEGER DEFAULT 0,
    PRIMARY KEY (method, target)
);
CREATE TABLE network_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                direction   TEXT    NOT NULL,  -- 'IN' | 'OUT'
                method      TEXT,
                tool        TEXT,
                agent       TEXT,
                ring        INTEGER,
                latency_ms  REAL,
                status      TEXT,
                payload_in  TEXT,
                payload_out TEXT,
                headers     TEXT,
                client_ip   TEXT
            , channel TEXT DEFAULT 'HUB', provider TEXT, model TEXT, meta TEXT, session_id TEXT);
CREATE TABLE novelty_archive (
    sig_hash TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    target TEXT,
    behavior_signature TEXT,
    novelty_score REAL,
    success INTEGER,
    elegance REAL,
    ts REAL NOT NULL
);
CREATE TABLE novelty_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE opsec_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    old_level TEXT,
    new_level TEXT,
    set_by TEXT,
    reason TEXT,
    ts REAL NOT NULL
);
CREATE TABLE opsec_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    set_by TEXT,
    reason TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE orchestrator_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param TEXT NOT NULL,
                current_value TEXT,
                suggested_value TEXT,
                reason TEXT,
                confidence REAL,
                source_module TEXT,
                evidence TEXT,
                pattern_code TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                applied_at TEXT,
                applied_by TEXT,
                rolled_back_at TEXT,
                UNIQUE(param, pattern_code, suggested_value)
            );
CREATE TABLE oversight_audits (id TEXT PRIMARY KEY, task TEXT, consensus TEXT, escalate INTEGER, n_auditors INTEGER, detail TEXT, created_at TEXT);
CREATE TABLE promcp_tool_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    ts REAL NOT NULL,
    duration_ms REAL NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    payload_bytes INTEGER DEFAULT 0,
    result_bytes INTEGER DEFAULT 0
);
CREATE TABLE promotion_queue (
            chunk_id     TEXT PRIMARY KEY,
            priority     INTEGER DEFAULT 10,
            author_id    TEXT    DEFAULT 'collab:claude',
            source_exists INTEGER DEFAULT 1,
            status       TEXT    DEFAULT 'pending',
            enqueued_at  TEXT,
            processed_at TEXT,
            result       TEXT
        , source_type TEXT DEFAULT 'unknown', retry_count INTEGER DEFAULT 0, error_msg TEXT DEFAULT '', tool_name TEXT DEFAULT '');
CREATE TABLE proprioception_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            global_score INTEGER,
            axes_json TEXT,
            atlas_json TEXT
        );
CREATE TABLE provider_scores (
            provider    TEXT PRIMARY KEY,
            agent_id    TEXT,
            ttft_ms     INTEGER DEFAULT 9999,
            grade       TEXT DEFAULT 'UNKNOWN',
            status      TEXT DEFAULT 'unknown',
            measured_at TEXT DEFAULT (datetime('now')),
            priority    INTEGER DEFAULT 5
        );
CREATE TABLE qdrant_sync_pending (
    chunk_id TEXT PRIMARY KEY,
    queued_at REAL
);
CREATE TABLE query_log (id INTEGER PRIMARY KEY, query_text TEXT NOT NULL, filters_json TEXT, retrieved_chunks_ids TEXT, selected_chunk_id INTEGER, latency_ms INTEGER, timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')));
CREATE TABLE rag_chunks (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    source      TEXT NOT NULL,
    domain      TEXT DEFAULT 'general',
    role_hint   TEXT DEFAULT 'chat',
    embedding   BLOB,
    meta        TEXT DEFAULT '{}',
    ingested_at TEXT DEFAULT (datetime('now'))
, author TEXT DEFAULT '', sequence_id INTEGER, session_id  TEXT DEFAULT '', version_id  TEXT DEFAULT '', updated_at TEXT DEFAULT '', hash TEXT, indexed_at TEXT, quality_score REAL DEFAULT NULL, created_at INTEGER, origin TEXT GENERATED ALWAYS AS (CASE
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
END) VIRTUAL, ext TEXT GENERATED ALWAYS AS (CASE
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
  ELSE '' END) VIRTUAL, folder TEXT GENERATED ALWAYS AS (CASE WHEN instr(source, '/') > 0 THEN substr(source, 1, instr(source, '/') - 1) ELSE '' END) VIRTUAL, lang TEXT GENERATED ALWAYS AS (CASE ext WHEN 'py' THEN 'python' WHEN 'ts' THEN 'typescript' WHEN 'js' THEN 'javascript' WHEN 'rs' THEN 'rust' WHEN 'sh' THEN 'shell' WHEN 'ps1' THEN 'powershell' WHEN 'md' THEN 'markdown' WHEN 'sql' THEN 'sql' ELSE '' END) VIRTUAL, canonical_id TEXT, version TEXT DEFAULT 'v1', superseded_by TEXT, active INTEGER DEFAULT 1, epistemic_weight REAL DEFAULT 0.5, last_validated_at TEXT, retraction_status TEXT, embedding_model TEXT DEFAULT NULL, access_count INTEGER DEFAULT 0);
CREATE TABLE rag_chunks_cold_storage(
  id TEXT,
  text TEXT,
  source TEXT,
  domain TEXT,
  role_hint TEXT,
  embedding,
  meta TEXT,
  ingested_at TEXT,
  author TEXT,
  sequence_id INT,
  session_id TEXT,
  version_id TEXT,
  updated_at TEXT,
  hash TEXT,
  indexed_at TEXT,
  quality_score REAL,
  created_at INT,
  origin TEXT,
  ext TEXT,
  folder TEXT,
  lang TEXT,
  canonical_id TEXT,
  version TEXT,
  superseded_by TEXT,
  active INT,
  epistemic_weight REAL,
  last_validated_at TEXT,
  retraction_status TEXT,
  embedding_model TEXT
);
CREATE TABLE rag_chunks_dedup_archive(
  id TEXT,
  text TEXT,
  source TEXT,
  domain TEXT,
  role_hint TEXT,
  embedding,
  meta TEXT,
  ingested_at TEXT,
  author TEXT,
  sequence_id INT,
  session_id TEXT,
  version_id TEXT,
  updated_at TEXT,
  hash TEXT,
  indexed_at TEXT,
  quality_score REAL,
  created_at INT,
  canonical_id TEXT,
  version TEXT,
  superseded_by TEXT,
  active INT,
  epistemic_weight REAL,
  last_validated_at TEXT,
  retraction_status TEXT,
  embedding_model TEXT,
  access_count INT
);
CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(
        text, source, domain,
        content='rag_chunks',
        content_rowid='rowid'
    );
CREATE TABLE 'rag_chunks_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'rag_chunks_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'rag_chunks_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE 'rag_chunks_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE rag_chunks_polluted_bak_20260528_214857(
  id TEXT,
  text TEXT,
  source TEXT,
  domain TEXT,
  role_hint TEXT,
  embedding,
  meta TEXT,
  ingested_at TEXT,
  author TEXT,
  sequence_id INT,
  session_id TEXT,
  version_id TEXT,
  updated_at TEXT,
  hash TEXT,
  indexed_at TEXT,
  quality_score REAL,
  created_at INT,
  origin TEXT,
  ext TEXT,
  folder TEXT,
  lang TEXT,
  canonical_id TEXT,
  version TEXT,
  superseded_by TEXT,
  active INT,
  epistemic_weight REAL,
  last_validated_at TEXT,
  retraction_status TEXT,
  embedding_model TEXT
);
CREATE VIRTUAL TABLE "rag_fts"
            USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED);
CREATE TABLE rag_fts_cibles_20260823 ( rid INTEGER PRIMARY KEY, motif TEXT);
CREATE TABLE 'rag_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'rag_fts_content'(id INTEGER PRIMARY KEY, c0, c1, c2, c3);
CREATE TABLE 'rag_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'rag_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE rag_fts_fantomes_20260823 ( chunk_id TEXT, text TEXT, source TEXT, domain TEXT, motif TEXT, archived_at TEXT);
CREATE TABLE 'rag_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE rag_fts_manquants_20260824 (id TEXT PRIMARY KEY);
CREATE TABLE rag_graph_edges (
        src TEXT, dst TEXT, rel_type TEXT, weight REAL DEFAULT 1.0,
        PRIMARY KEY (src, dst, rel_type));
CREATE TABLE rag_graph_nodes (
        chunk_id TEXT PRIMARY KEY, source TEXT, domain TEXT, degree INTEGER DEFAULT 0, pagerank REAL DEFAULT 0.0);
CREATE TABLE rag_snapshots (
    snap_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    timecode    TEXT    NOT NULL,
    session_id  TEXT    NOT NULL DEFAULT '',
    agent_id    TEXT    NOT NULL DEFAULT 'laforge',
    chunk_id    TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT '',
    domain      TEXT    NOT NULL DEFAULT 'general',
    meta        TEXT    NOT NULL DEFAULT '{}',
    op          TEXT    NOT NULL DEFAULT 'insert',  -- insert | update | delete
    sequence_id INTEGER NOT NULL
);
CREATE TABLE rbac_mapping_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT
        );
CREATE TABLE resonance_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL DEFAULT (datetime('now')),
    agent_id     TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,              -- sha256 de la proposition
    proposal_text TEXT NOT NULL,              -- texte brut
    similar_seqs  TEXT DEFAULT '[]',          -- JSON [seq_id, score] des 3 derniers similaires
    drift_score   REAL DEFAULT 0.0,           -- 0.0=aligné 1.0=dérive totale
    adr_triggered TEXT DEFAULT '[]',          -- ADR IDs injectés
    correction    TEXT DEFAULT '',            -- texte de correction injectée
    action        TEXT DEFAULT 'pass'         -- pass|warn|correct|block
);
CREATE TABLE routing_telemetry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT DEFAULT (datetime('now')),
    prompt_hash     TEXT NOT NULL,
    prompt_sample   TEXT DEFAULT '',
    chosen_model    TEXT NOT NULL,
    chosen_provider TEXT NOT NULL,
    ttft_ms         REAL DEFAULT 0,
    success_score   REAL DEFAULT 0,
    task_type       TEXT DEFAULT 'general',
    ring            INTEGER DEFAULT 1,
    exported_kaggle INTEGER DEFAULT 0
);
CREATE TABLE sandbox_leases (
    lease_id    TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    container_id TEXT DEFAULT '',
    started_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    status      TEXT DEFAULT 'active' CHECK(status IN ('active','expired','released','killed')),
    killed_reason TEXT DEFAULT ''
);
CREATE TABLE shared_prompt_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    timecode    TEXT    NOT NULL DEFAULT (datetime('now')),
    sequence_id INTEGER NOT NULL DEFAULT 0,
    agent_id    TEXT    NOT NULL,          -- CLAUDE | CLINE_PLAN | CLINE_ACT | laforge
    role        TEXT    NOT NULL DEFAULT 'user',  -- user | assistant | system | tool
    mode        TEXT    NOT NULL DEFAULT '',       -- autonome | collaboration | comite
    content     TEXT    NOT NULL,
    meta        TEXT    NOT NULL DEFAULT '{}'
, is_private INTEGER DEFAULT 0, msg_hash TEXT DEFAULT '');
CREATE TABLE synaptic_feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,
    helpful INTEGER NOT NULL,
    agent TEXT,
    context TEXT,
    weight_before REAL,
    weight_after REAL,
    threshold_after REAL,
    ts REAL NOT NULL
);
CREATE TABLE synaptic_metrics (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE system_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL,
    ring INTEGER DEFAULT 0,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE task_dependencies (
    node_id         TEXT NOT NULL,
    depends_on_node TEXT NOT NULL,
    PRIMARY KEY (node_id, depends_on_node)
);
CREATE TABLE task_nodes (
    node_id     TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    step        INTEGER NOT NULL DEFAULT 1,
    tool        TEXT NOT NULL,
    args        TEXT DEFAULT '{}',
    status      TEXT DEFAULT 'pending' CHECK(status IN ('pending','running','done','failed','skipped')),
    result      TEXT DEFAULT '',
    started_at  TEXT DEFAULT NULL,
    done_at     TEXT DEFAULT NULL,
    retry_count INTEGER DEFAULT 0,
    error       TEXT DEFAULT ''
);
CREATE TABLE task_queue (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT    DEFAULT (datetime('now')),
            title      TEXT    NOT NULL,
            role       TEXT    DEFAULT 'EXECUTOR',
            priority   TEXT    DEFAULT 'NORMAL',
            status     TEXT    DEFAULT 'PENDING',
            context    TEXT    DEFAULT '',
            result     TEXT    DEFAULT '',
            started_at TEXT,
            done_at    TEXT
        );
CREATE TABLE task_routing (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT NOT NULL,
    node_id       TEXT NOT NULL REFERENCES edge_nodes(node_id),
    routed_at     TEXT DEFAULT (datetime('now')),
    reason        TEXT DEFAULT '',
    score         REAL DEFAULT 0.0,
    status        TEXT DEFAULT 'pending'
                  CHECK(status IN ('pending','accepted','rejected','done','timeout'))
);
CREATE TABLE token_usage (
    id            TEXT PRIMARY KEY,
    ts            TEXT DEFAULT (datetime('now')),
    agent_id      TEXT,           -- agt_gemini, agt_groq...
    provider      TEXT,           -- gemini-2.5-flash, llama-3.3-70b...
    model         TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens  INTEGER DEFAULT 0,
    cost_usd      REAL DEFAULT 0.0,  -- coût calculé
    latency_ms    REAL DEFAULT 0.0,
    source        TEXT DEFAULT 'broker', -- broker | hub | direct
    session_id    TEXT DEFAULT '',
    meta          TEXT DEFAULT '{}'
, cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER, cost_kind TEXT, cost_source TEXT, execution_id TEXT, execution_mode TEXT, measurement_kind TEXT, measurement_source TEXT, parent_execution_id TEXT, provenance TEXT, transport TEXT, writer_component TEXT);
CREATE TABLE trajectories (
                job_id TEXT PRIMARY KEY,
                steps_json TEXT,
                metadata_json TEXT,
                started_at REAL,
                updated_at REAL
            );
CREATE TABLE tui_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now')),
    consumed_at TEXT DEFAULT NULL,
    source      TEXT DEFAULT 'tui',     -- tui | llm | hub
    command     TEXT NOT NULL,          -- 'deploy' | 'test' | 'overdrive' | 'auto_on' ...
    payload     TEXT DEFAULT '{}',      -- JSON libre
    status      TEXT DEFAULT 'pending'  -- pending | consumed | cancelled
);
CREATE TABLE tui_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT DEFAULT (datetime('now')),
    read_at     TEXT DEFAULT NULL,
    source      TEXT DEFAULT 'llm',     -- llm | hub | system
    type        TEXT DEFAULT 'info',    -- info | success | warning | error | action
    message     TEXT NOT NULL,
    payload     TEXT DEFAULT '{}',
    status      TEXT DEFAULT 'unread'   -- unread | read | dismissed
);
CREATE TABLE user_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT DEFAULT (datetime('now')),
    user_id     TEXT NOT NULL,
    session_id  TEXT DEFAULT '',
    action      TEXT NOT NULL,
    resource    TEXT DEFAULT '',
    ring_used   INTEGER DEFAULT 3,
    status      TEXT DEFAULT 'ok'
                CHECK(status IN ('ok','denied','warn','error')),
    ip_hash     TEXT DEFAULT '',
    detail      TEXT DEFAULT ''
);
CREATE TABLE user_sessions (
    session_id    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(user_id),
    token_hash    TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now')),
    expires_at    TEXT NOT NULL,
    last_seen     TEXT DEFAULT (datetime('now')),
    ip_hash       TEXT DEFAULT '',
    user_agent    TEXT DEFAULT '',
    is_active     INTEGER DEFAULT 1,
    revoked_at    TEXT DEFAULT NULL,
    revoked_by    TEXT DEFAULT NULL
);
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL DEFAULT '',
    email         TEXT DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'viewer'
                  CHECK(role IN ('owner','admin','developer','viewer','agent')),
    ring_level    INTEGER NOT NULL DEFAULT 3
                  CHECK(ring_level BETWEEN 0 AND 10),
    is_active     INTEGER NOT NULL DEFAULT 1,
    hashed_token  TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now')),
    last_login    TEXT DEFAULT NULL,
    meta          TEXT DEFAULT '{}'
);
CREATE TABLE veille_digest_suggestions (
            id TEXT PRIMARY KEY, suggestion TEXT NOT NULL, organe TEXT, prio TEXT,
            sources TEXT, created_at TEXT NOT NULL);
CREATE TABLE veille_url_morte (url TEXT PRIMARY KEY, code INTEGER, vu_le TEXT);
CREATE TABLE watch_jobs (
    id           TEXT PRIMARY KEY,
    theme        TEXT NOT NULL,
    idea_id      TEXT NOT NULL DEFAULT 'veille_active',
    step         TEXT NOT NULL DEFAULT 'keywords',
    status       TEXT NOT NULL DEFAULT 'pending',
    keywords_json TEXT,
    search_results_json TEXT,
    refined_json TEXT,
    n_ingested   INTEGER DEFAULT 0,
    n_stored     INTEGER DEFAULT 0,
    agent        TEXT DEFAULT 'SYSTEM',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    error        TEXT
);
CREATE TABLE watch_jobs_bak_20260528_180756(
  id TEXT,
  theme TEXT,
  idea_id TEXT,
  step TEXT,
  status TEXT,
  keywords_json TEXT,
  search_results_json TEXT,
  refined_json TEXT,
  n_ingested INT,
  n_stored INT,
  agent TEXT,
  created_at TEXT,
  updated_at TEXT,
  error TEXT
);
CREATE TABLE watch_jobs_bak_20260528_190123(
  id TEXT,
  theme TEXT,
  idea_id TEXT,
  step TEXT,
  status TEXT,
  keywords_json TEXT,
  search_results_json TEXT,
  refined_json TEXT,
  n_ingested INT,
  n_stored INT,
  agent TEXT,
  created_at TEXT,
  updated_at TEXT,
  error TEXT
);
CREATE TABLE watch_jobs_bak_20260528_190420(
  id TEXT,
  theme TEXT,
  idea_id TEXT,
  step TEXT,
  status TEXT,
  keywords_json TEXT,
  search_results_json TEXT,
  refined_json TEXT,
  n_ingested INT,
  n_stored INT,
  agent TEXT,
  created_at TEXT,
  updated_at TEXT,
  error TEXT
);
CREATE TABLE watch_jobs_bak_20260528_192351(
  id TEXT,
  theme TEXT,
  idea_id TEXT,
  step TEXT,
  status TEXT,
  keywords_json TEXT,
  search_results_json TEXT,
  refined_json TEXT,
  n_ingested INT,
  n_stored INT,
  agent TEXT,
  created_at TEXT,
  updated_at TEXT,
  error TEXT
);
```

### taches (tasks_path)
`%NOKIDO_ROOT%\sandbox\task_queue.db` -- journal `wal`, 1 table(s), 3 objet(s)

```sql
CREATE INDEX idx_task_queue_status ON task_queue(status, priority, id);
CREATE INDEX idx_task_queue_ts ON task_queue(ts);
CREATE TABLE task_queue ( id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT (datetime('now')), title TEXT NOT NULL, role TEXT DEFAULT 'EXECUTOR', priority TEXT DEFAULT 'NORMAL', status TEXT DEFAULT 'PENDING', context TEXT DEFAULT '', result TEXT DEFAULT '', started_at TEXT, done_at TEXT);
```

### m2m (m2m_path)
`%NOKIDO_ROOT%\sandbox\m2m.db` -- journal `wal`, 2 table(s), 10 objet(s)

```sql
CREATE INDEX idx_agent_messages_corr ON agent_messages(correlation_id);
CREATE INDEX idx_agent_messages_created_at ON agent_messages(created_at);
CREATE INDEX idx_agent_messages_from_agent ON agent_messages(from_agent);
CREATE INDEX idx_agent_messages_method ON agent_messages(method);
CREATE INDEX idx_agent_messages_status ON agent_messages(status);
CREATE INDEX idx_agent_messages_to ON agent_messages(to_agent, status);
CREATE INDEX idx_locks_owner ON locks_state(owner_agent);
CREATE INDEX idx_locks_state ON locks_state(state);
CREATE TABLE agent_messages (
    id            TEXT PRIMARY KEY,
    from_agent    TEXT NOT NULL,
    to_agent      TEXT NOT NULL,
    correlation_id TEXT,
    method        TEXT NOT NULL,
    payload       TEXT,
    result        TEXT,
    status        TEXT DEFAULT 'pending',
    created_at    TEXT DEFAULT (datetime('now')),
    read_at       TEXT
);
CREATE TABLE locks_state (
                resource TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                owner_agent TEXT,
                owner_token TEXT,
                locked_at REAL,
                released_at REAL,
                timeout_s REAL,
                queue_size INTEGER DEFAULT 0
            , holder_pid INTEGER, holder_boot REAL, holder_host TEXT);
```

### journal inspector_log
`%NOKIDO_ROOT%\sandbox\journal_inspector.db` -- journal `delete`, 1 table(s), 1 objet(s)

```sql
CREATE TABLE inspector_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT (datetime('now')),
                    status TEXT, ports_down INTEGER,
                    zombies INTEGER, errors INTEGER,
                    cpu_pct REAL, ram_pct REAL,
                    detail TEXT);
```

### journal token_usage
`%NOKIDO_ROOT%\sandbox\journal_token_usage.db` -- journal `wal`, 1 table(s), 3 objet(s)

```sql
CREATE INDEX idx_token_usage_slot ON token_usage (source, agent_id, ts);
CREATE INDEX idx_token_usage_ts ON token_usage(ts);
CREATE TABLE token_usage ( id TEXT PRIMARY KEY, ts TEXT DEFAULT (datetime('now')), agent_id TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0, total_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0.0, latency_ms REAL DEFAULT 0.0, source TEXT DEFAULT 'broker', session_id TEXT DEFAULT '', meta TEXT DEFAULT '{}', cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_kind TEXT, cost_source TEXT, execution_id TEXT, execution_mode TEXT, measurement_kind TEXT, measurement_source TEXT, parent_execution_id TEXT, provenance TEXT, reasoning_tokens INTEGER, transport TEXT, writer_component TEXT, attempts INTEGER, served_model TEXT);
```

<!-- nokido:statique -->
## Outils MCP (`tests/schemas_mcp_structure.json`)

58 outil(s) dans l'instantane de la CI. Ring minimal lu dans `forge_tools` (petit = plus de privilege ; -99 = outil coupe) .

| Outil | Requis | Parametres | Ring min | Actif |
|---|---|---|---|---|
| `absorb_rfc_knowledge` | concept_query | 2 | repli code | ? |
| `acp` | op | 8 | repli code | ? |
| `agy_add_dir` | path | 2 | repli code | ? |
| `agy_config` | action, key | 4 | repli code | ? |
| `agy_run` | command | 3 | repli code | ? |
| `ask` | message, provider | 6 | 3 | True |
| `auto_ingest` | action | 2 | repli code | ? |
| `auto_test` | filepath | 2 | 3 | True |
| `biblio` | action | 8 | 3 | True |
| `blackboard_propose_fact` | fact, zone_name | 6 | repli code | ? |
| `blackboard_read_zone` | zone_name | 6 | repli code | ? |
| `bundle` | calls | 2 | repli code | ? |
| `crawl` | url | 3 | 3 | True |
| `cross_platform_fs` | action, dest, src | 5 | repli code | ? |
| `delegate_to_local_scout` | path, prompt | 3 | repli code | ? |
| `docker_action` | argv | 3 | repli code | ? |
| `event` | action | 7 | 0 | True |
| `forge_call_dynamic` | name | 3 | repli code | ? |
| `forge_deep_explore` | intent | 5 | 4 | True |
| `forge_list_dynamic_tools` | -- | 1 | repli code | ? |
| `forge_spawn_swarm` | tasks | 4 | repli code | ? |
| `forge_stats` | -- | 1 | repli code | ? |
| `forge_trigger_audit` | target_files | 4 | repli code | ? |
| `get_file_skeleton` | file_path | 4 | repli code | ? |
| `get_function_dependencies` | function_name | 3 | repli code | ? |
| `github` | repo | 6 | repli code | ? |
| `governed_edit` | path | 5 | 3 | True |
| `graph_cve_propagate` | cve_id, entry_module | 4 | repli code | ? |
| `graph_edge_score` | dst, src | 5 | repli code | ? |
| `graph_ppr` | seed | 4 | repli code | ? |
| `hub` | action | 18 | 3 | True |
| `introspect` | query | 3 | repli code | ? |
| `loop_orchestrate` | -- | 3 | repli code | ? |
| `manage_forge_lifecycle` | action, organ_name | 4 | 3 | True |
| `md` | action | 4 | repli code | ? |
| `memory` | action | 8 | repli code | ? |
| `netcfg` | action | 11 | repli code | ? |
| `nokido_ensure_service` | service | 3 | 4 | True |
| `oracle_python_repl` | code | 3 | repli code | ? |
| `orchestrate` | task | 7 | repli code | ? |
| `plan` | goal | 4 | repli code | ? |
| `query` | -- | 5 | 2 | True |
| `query_documentation` | docset_name, search_query | 3 | repli code | ? |
| `query_local_json` | key_filter, path | 4 | repli code | ? |
| `rag` | action | 6 | 3 | True |
| `read` | action | 10 | 3 | True |
| `read_function_body` | file_path, function_name | 5 | repli code | ? |
| `research_agent` | objective | 6 | 3 | True |
| `route_task` | payload, task_type | 4 | 3 | True |
| `run` | action | 17 | 3 | True |
| `search_local_file` | path, pattern | 4 | repli code | ? |
| `secret` | action | 3 | repli code | ? |
| `skill` | action | 5 | 3 | True |
| `task` | action | 12 | 3 | True |
| `tool_scope` | action | 4 | repli code | ? |
| `trigger_autonomous_evolution` | intention | 4 | 1 | True |
| `web_search` | query | 3 | 3 | True |
| `write` | content, path | 3 | 3 | True |
