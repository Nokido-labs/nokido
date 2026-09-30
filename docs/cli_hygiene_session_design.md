# Design Document: Async Session Resume & CLI Output Hygiene

**Author**: `ANTIGRAVITY`  
**Date**: 2026-07-26  
**Status**: Proposal (Design + Non-Intrusive Prototype)  
**Pointer Reference**: `blackboard:architecture_rules:reflexion_collab_claude_agy_cli`  

---

## 1. Async Session Resume for Subagents

When a subagent runs a long-horizon task, a client timeout or process crash shouldn't wipe its progress. We design a Session Registry to track and resume execution states.

### Session Lifecycle State Machine
```
[Created] --> [Active] --(Crash / Timeout)--> [Stale]
                 |                              |
                 v                              v
             [Finished]                  [Resumed / Re-attached]
```

### Schema for Session Registry
```sql
CREATE TABLE IF NOT EXISTS session_registry (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    status TEXT CHECK(status IN ('active', 'stale', 'resumed', 'finished')) NOT NULL,
    checkpoint_json TEXT,  -- Context state variables, current task index
    output_log_path TEXT,  -- Path to stdout log file
    updated_at REAL NOT NULL
);
```

---

## 2. CLI Output Hygiene Pipeline

To conserve context tokens and improve legibility, outputs from external shell commands or tools must pass through a sanitization pipeline before reaching the agent:

1. **ANSI Code Stripper**: Removes terminal color codes (e.g. `\x1b[31m`).
2. **Carriage Return (`\r`) Collapser**: Collapses progress bars (like pip install or cargo build) keeping only the final line.
3. **Traceback Auto-Summarizer**: Extracts Python/Node tracebacks and formats them into a single-line error summary.
4. **Intelligent Truncation**: Truncates massive outputs (> 2000 chars) preserving the head (first 500) and tail (last 500) with a placeholder indicating truncated lines.

---

## 3. Prototype Implementation
A functional prototype `tools/forge_cli_hygiene_session_prototype.py` demonstrates both the session management registry and the output hygiene sanitization logic.
