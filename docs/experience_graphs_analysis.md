# Gap Analysis: Experience Graphs for Self-Improving Agents

**Author**: `ANTIGRAVITY`  
**Date**: 2026-07-26  
**Status**: Completed  
**Reference Paper**: *Experience Graphs: The Data Foundation for Self-Improving Agents*  

---

## 1. Introduction & Core Concept of the Paper
The referenced paper argues that long-horizon agentic workloads (e.g., autonomous coding, scientific exploration) require a dedicated database abstraction: **Experience Graphs (ExG)**. 

An Experience Graph represents the agent's historical trials as a directed graph where:
- **Nodes** represent States (system context, variable values, errors), Actions (tools called, command parameters), and Outcomes (logs, metrics, compilation status).
- **Edges** represent transitions, dependencies, and causal relationships.

This enables the agent to query its historical memory at runtime:  
*"What did I do last time I encountered this specific error state, and what was the outcome?"*

---

## 2. Nokido's Current State: `execution_traces.db`
Nokido currently logs task runs using `app/forge_execution_tracer.py` into a flat SQLite table `traces` in `RAG/execution_traces.db`:

```sql
CREATE TABLE IF NOT EXISTS traces (
    id           TEXT NOT NULL,
    ts           REAL NOT NULL,
    state_t_emb  BLOB,  -- Prior state embedding (binary vector)
    action_json  TEXT NOT NULL,
    state_t1_emb BLOB,  -- Posterior state embedding (binary vector)
    cost_before  REAL,
    cost_after   REAL,
    task_type    TEXT,
    success      INTEGER NOT NULL
);
```

---

## 3. Identified Gaps

### Gap 1: Vector-Only State Descriptions
Nokido stores states as high-dimensional embedding blobs (`state_t_emb`). It does not store the **symbolic or textual state representations** (e.g., active locks, specific error classes, file paths, running service states) next to the vectors. This prevents lexical/regex search on states and limits lookup to vector similarity (which can miss precise matches like error codes).

### Gap 2: Coarse Outcome Tracking
The outcome is a simple boolean `success` (0 or 1). There is no structured metadata linking the outcome to the actual stdout/stderr, compilation exit codes, or logs. This makes it impossible to query *why* an action failed or what specific side effects occurred.

### Gap 3: Flat Tabular Structure (No Semantic Edges)
The transitions are stored as flat independent rows. The system has no concept of graph relationships (e.g., "Action A was a sub-task of Task B", "State S was caused by Action C").

---

## 4. Proposed Target Schema for Experience Graphs (ExG)

To support semantic graph queries, we propose migrating `execution_traces.db` to a node-edge graph schema:

```sql
-- Core nodes table (unified indexing)
CREATE TABLE IF NOT EXISTS exg_nodes (
    id TEXT PRIMARY KEY,
    type TEXT CHECK(type IN ('STATE', 'ACTION', 'OUTCOME')) NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL
);

-- State metadata
CREATE TABLE IF NOT EXISTS exg_state_nodes (
    node_id TEXT PRIMARY KEY,
    state_vector BLOB, -- BGE-M3 embedding for dense retrieval
    symbolic_state_json TEXT, -- JSON: {active_locks, active_errors, memory_mb, cpu_pct}
    FOREIGN KEY(node_id) REFERENCES exg_nodes(id) ON DELETE CASCADE
);

-- Action metadata
CREATE TABLE IF NOT EXISTS exg_action_nodes (
    node_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    caller_agent TEXT,
    FOREIGN KEY(node_id) REFERENCES exg_nodes(id) ON DELETE CASCADE
);

-- Outcome metadata
CREATE TABLE IF NOT EXISTS exg_outcome_nodes (
    node_id TEXT PRIMARY KEY,
    success INTEGER CHECK(success IN (0, 1)) NOT NULL,
    error_class TEXT, -- e.g., "sqlite3.OperationalError: database is locked"
    result_summary TEXT,
    logs_excerpt TEXT,
    execution_time_ms REAL,
    FOREIGN KEY(node_id) REFERENCES exg_nodes(id) ON DELETE CASCADE
);

-- Directed edges table (semantic relations)
CREATE TABLE IF NOT EXISTS exg_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT CHECK(relation_type IN ('LEADS_TO', 'CAUSE_OF', 'SUB_ACTION_OF')) NOT NULL,
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (source_id, target_id, relation_type),
    FOREIGN KEY(source_id) REFERENCES exg_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES exg_nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_exg_edges_target ON exg_edges(target_id);
```

---

## 5. Sample Query: Resolving Past Mistakes

With this schema, the agent can execute a single SQL query to retrieve what actions it took when encountering a similar state (e.g. database locks) and how they performed:

```sql
SELECT 
    a.tool_name, 
    a.arguments_json, 
    o.success, 
    o.error_class, 
    o.result_summary
FROM exg_edges e1
-- From State Node
JOIN exg_state_nodes s ON e1.source_id = s.node_id
-- To Action Node
JOIN exg_action_nodes a ON e1.target_id = a.node_id
-- Action Node leads to Outcome Node
JOIN exg_edges e2 ON a.node_id = e2.source_id
JOIN exg_outcome_nodes o ON e2.target_id = o.node_id
WHERE e1.relation_type = 'LEADS_TO'
  AND e2.relation_type = 'CAUSE_OF'
  AND s.symbolic_state_json LIKE '%database is locked%'
ORDER BY o.success DESC, o.execution_time_ms ASC
LIMIT 5;
```
