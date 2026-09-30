# Project: Antigravity CLI (agy) MCP Integration

## Architecture
- `app/forge_mcp_registry.py` will expose three new tools: `agy_run`, `agy_config`, `agy_add_dir` (canonically `forge.code.agy_run`, `forge.meta.agy_config`, `forge.fs.agy_add_dir`).
- The handlers `handle_agy_run`, `handle_agy_config`, `handle_agy_add_dir` will run in `app/forge_mcp_registry.py`.
- Subprocess execution will launch the `agy` executable via `subprocess.run` or `subprocess.Popen` with configurable timeouts, capturing stdout/stderr safely.
- Shell injections are prevented via input validation rejecting tokens like `;`, `&&`, `|`, `$()`, etc.
- Configurations read/write from `~/.gemini/antigravity-cli/settings.json` using secure JSON file parsing.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 1 | Codebase Discovery & Design | Explore registry structures and design security sanitization rules | None | DONE |
| 2 | E2E Test Infra & Test Cases | Create test suite `tests/test_agy_mcp.py` verifying all requirements | M1 | DONE |
| 3 | Tool Registration & Handlers | Implement tool schemas, namespaces, and handler stubs | M2 | DONE |
| 4 | Execution Wrapper & Configs | Implement subprocess invocation, sanitization, and settings.json update | M3 | DONE |

## Interface Contracts
### `agy_run`
- Inputs: `command: string` (custom sub-command to execute via agy, e.g. "task list"), `timeout: integer` (optional timeout in seconds, default 60), `explanation: string` (required reasoning for calling the tool).
- Output: `{"stdout": string, "stderr": string, "exit_code": integer, "success": boolean}`.

### `agy_config`
- Inputs: `action: string` ("read" or "write"), `key: string`, `value: string` (optional, required if action is "write"), `explanation: string` (required).
- Output: `{"success": boolean, "key": string, "value": string, "error": string}`.

### `agy_add_dir`
- Inputs: `path: string` (absolute path to add to workspace), `explanation: string` (required).
- Output: `{"success": boolean, "path": string, "error": string}`.

## Code Layout
- `app/forge_mcp_registry.py` - main MCP tool registry and inline handlers.
- `tests/test_agy_mcp.py` - test suite covering all tools, parameter mapping, subprocess invocation, sanitization, and config manipulation.
