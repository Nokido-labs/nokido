# agy MCP Tools — Reference

Three MCP tools that wrap the **agy** (Antigravity) CLI, implemented **inline** in
`app/forge_mcp_registry.py`. They let Nokido clients drive agy through the
governed hub instead of a raw shell.

- Author: `agt_antigravity`. Validation/visibility/bridge: `agt_claude`.
- Tests: `tests/test_agy_mcp.py` — **51 E2E** (all passing).
- Status: handlers + dispatch live. **Discovery over `tools/list`** depends on the
  `_TOOL_MIN_RING` visibility entries (see [Discovery & rings](#discovery--rings)).

---

## Tool catalog

| Internal | Namespaced name | Alias | Call ring | Handler |
|---|---|---|---|---|
| `agy_run` | `forge.code.agy_run` | `forge_agy_run` | ≤ 2 | `handle_agy_run` |
| `agy_config` | `forge.meta.agy_config` | `forge_agy_config` | read ≤ 3 / write ≤ 1 | `handle_agy_config` |
| `agy_add_dir` | `forge.fs.agy_add_dir` | `forge_agy_add_dir` | ≤ 2 | `handle_agy_add_dir` |

Lower ring = more privileged. Names resolve through `resolve_tool_name()` before dispatch.

---

### `agy_run` — execute an agy command

Runs an `agy` subcommand and returns its exit code + stdout/stderr.

**Args**: `command` (str, required), `timeout` (int, optional — default **60s**).

**Returns**: `{success, exit_code, stdout, stderr}` (or `{success:false, error}`).

**Hardening**:
- Length cap: `command` ≤ 500 chars.
- **Injection filter**: rejects any of `; & | ` $ < > ( ) * ! [ ] { } \n \r ^ %`
  (the `^` and `%` close the Windows `.bat`/`%batch%` variable-injection vector).
- Parsed with `shlex.split`; executed with `shell=False`.
- Binary resolved via `shutil.which("agy")`; a redundant leading `agy` token is stripped.
- `subprocess.run` with `timeout` → `TimeoutExpired` returns a clean error, never hangs.

---

### `agy_config` — read/write agy `settings.json`

Reads or writes a single key in `~/.gemini/antigravity-cli/settings.json`.

**Args**: `action` (`"read"` | `"write"`, required), `key` (str, required),
`value` (write only).

**Returns**: `{success, key, value}` (or `{success:false, error}`).

**Hardening**:
- Fixed path under `Path.home()/.gemini/antigravity-cli` — no caller-supplied path.
- **Symlink guard**: rejects if the file or any parent is a symlink.
- **TOCTOU-safe size check**: `os.fstat(fd)` on the *open* descriptor (≤ 1 MB), not a
  pre-open `stat`.
- **Write is schema-bounded**: only the known `SETTINGS_SCHEMA` keys are accepted,
  each type-checked (with strict `bool`-vs-other separation); `trustedWorkspaces` must
  be a list of strings.
- **Atomic write**: `tempfile.mkstemp` in the same dir → `os.replace` (no partial file;
  temp cleaned on failure).

---

### `agy_add_dir` — add a trusted workspace

Appends an absolute directory to `trustedWorkspaces` in the same `settings.json`.

**Args**: `path` (str, required — absolute).

**Returns**: `{success, path}` (or `{success:false, error}`).

**Hardening**:
- Path must be **absolute** (`Path(path).is_absolute()`).
- **Traversal guard**: rejects `..` path parts and literal `../` / `..\` sequences.
- Same symlink guard, TOCTOU-safe size check, and atomic write as `agy_config`.
- Idempotent: a path already present is not duplicated.

---

## Security model — the 4 audited vulnerabilities

These were found in peer review and fixed before merge:

| Vuln | Mitigation (in code) |
|---|---|
| **Ring bypass** | Call-tier enforced by RBAC (`forge_mcp_rbac.check_tool_capability`) + gate (`_get_ring_needed`, fallback: `agy_config` write 1 / read 3, `agy_run` & `agy_add_dir` 2). |
| **Path traversal** | `agy_add_dir` requires absolute paths and rejects `..`; `agy_config`/`agy_add_dir` use a fixed home-relative settings path + symlink guard on file and parents. |
| **`%batch` injection** | `agy_run` injection regex rejects shell/batch metacharacters incl. `^` and `%`; `shlex.split` + `shell=False`. |
| **TOCTOU race** | Size validated via `os.fstat` on the open fd; atomic `mkstemp` → `os.replace`; symlink check before open. |

---

## Discovery & rings

- **Call gate** (can the agent *invoke* it): `_get_ring_needed` / RBAC, as above.
- **Visibility** (does it appear in `tools/list`): `get_tool_list` filters by the
  `_TOOL_MIN_RING` allowlist — a tool absent from it is invisible to MCP clients
  (`ring ≤ 3`). Required entries:

  ```python
  "agy_run": 2,
  "agy_config": 3,
  "agy_add_dir": 2,
  ```

  Kept **out** of `_TOOLS_PUBLIC` (privileged dev tools; not exposed to unidentified
  ring-4 callers). Changes to `_TOOL_MIN_RING` need a **hub reload** (import-cached).

## STDIO bridge

The tools reach Claude Desktop through `tools/mcp_stdio_bridge.py`, a transparent
`tools/call` proxy to the hub that validates each call via `forge_sentinel`. Once the
visibility entries above are live, `agy_*` appear in the bridge's `tools/list` and are
callable end-to-end (proven by `sandbox/workspace/agy_bridge_e2e.py`).
