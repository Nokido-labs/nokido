# Analysis: Antigravity CLI (agy) Integration in Nokido Sovereign Hub

This document details the analysis and design for integrating the Antigravity CLI (`agy`) as an MCP tool suite in the Nokido Sovereign Hub.

---

## 1. Registry Mechanics & Dispatch Chain

The Nokido Sovereign Hub handles all MCP tool registration, visibility control, and execution dispatch through `app/forge_mcp_registry.py`.

### A. Namespace Structure & Aliasing
Tool names undergo normalization before dispatch. This is governed by `_NAMESPACE_ALIASES` and `resolve_tool_name()`:
* **`_NAMESPACE_ALIASES`**: A dictionary that maps three families of tool names to an internal short name:
  1. **Canonical Namespace Form**: `forge.{category}.{tool}` (e.g., `forge.code.read` -> `read`).
  2. **Historical Prefix Form**: `forge_{tool}` (e.g., `forge_read` -> `read`).
  3. **Short Form**: `read` -> `read`.
* **Normalization Call**: `resolve_tool_name(name)` uses this dictionary to resolve any alias to the internal short name (e.g., `handle_read`).

### B. Tool Discovery & Schema Registration
* **`_raw_tool_catalog(self)`**: Returns a list of dictionaries defining the metadata and JSON schemas (`name`, `description`, `inputSchema`) of all core tools.
* **`_all_tools(self)`**: Merges the raw catalog with dynamic tools and automatically injects the `explanation` field into `inputSchema.properties` for every tool via `_inject_explanation_field()`.
* **`get_tool_list(self, ring, agent)`**: Filters tools based on the caller agent's ring level and authorization overrides (`self._AGENT_TOOL_DENY`). Rings `0-3` expose tools mapped in `_TOOL_MIN_RING` that satisfy `ring <= min_ring`. Ring `4+` exposes only a minimal public subset defined in `_TOOLS_PUBLIC`.

### C. Dispatch Call Chain
When an MCP client invokes a tool, the request passes through `async def dispatch(self, name, args, agent, ring)`:
1. **Normalization**: The name is resolved to the internal short name.
2. **Explanation Enforcement**: Checks if the required `explanation` argument is present.
3. **RBAC Rules**: Executes dynamic RBAC scoping checks via `forge_mcp_rbac.check_tool_capability()` if available.
4. **Behavioral Breaker Rules**: Runs throttle/coupe-circuit mechanisms (e.g., `forge_recon_breaker` for `read`).
5. **Ring Level Verification**:
   - Calls `self._get_ring_needed(name, args)` to retrieve the minimum required ring level. The level is fetched first from the SQLite database `forge_tools` table, with a fallback to hardcoded mappings (e.g., `write` and `run.python` require Ring 0, normal `run` requires Ring 1).
   - If the caller's ring is greater than the required ring, execution is blocked with a security violation error: `"SECURITY: Acces refuse (agent ring {ring} > max autorise {ring_needed})"`.
6. **Dynamic Access Switches**: Checks dynamic DB-driven rule toggles via `forge_access_switches.check_access()`.
7. **Execution**: The handler method `handle_<short_name>` is dynamically looked up and executed: `result = await handler(args, agent, ring)`.
8. **Logging & Output Capping**: The call is logged to the event bus and the output is audited/capped to prevent tokens/context exhaustion (reversible CCR compression).

---

## 2. Existing Testing Patterns

Analysis of `tests/test_forge_mcp_registry_namespace.py` highlights how the registry is mocked and tested:
* **Sandbox Subclassing**: Unit tests isolate the registry by subclassing `ToolRegistry` (e.g., `class _DummyRegistry(ToolRegistry)`).
* **Mock Handlers**: Inside the subclass initializer, real handlers are replaced with light mock trackers to intercept arguments:
  ```python
  async def _track(args, agent, ring):
      self.calls.append({"args": args, "agent": agent, "ring": ring})
      return "TRACKED_OK"
  self.handle_read = _track
  ```
* **Stubbing Externals**: The internal EventBus (`self._event_bus`) and database-dependent functions (`_get_ring_needed`) are stubbed out to make testing purely local and zero-dependency.

---

## 3. Secure Input Validation & Sanitization Design

To prevent command injection when executing `agy` subcommands via subprocess, a double-defense sanitization strategy must be implemented.

### A. Subprocess Invocation Rules
* **No `shell=True`**: All subprocess invocations must pass arguments as an explicit array of strings (`shell=False`). This ensures the OS executes the CLI binary directly, bypassing command shells (bash, cmd, powershell) that parse control characters.
* **Path Resolution**: The absolute path of the `agy` binary must be resolved using `shutil.which("agy")` before execution to prevent PATH hijacking.

### B. Input Validation Regex
Even with `shell=False`, strict validation ensures that no special characters break command interpretation or trigger unexpected flags. We propose a regular expression to reject dangerous symbols:
```python
import re

# Rejects command separators, variables, redirection, subshell evaluation, 
# globbing wildcards, brackets, braces, and command chainers.
# Rejects Windows cmd escape symbol '^' as well.
SHELL_INJECTION_RE = re.compile(r"[;&|`$<>\(\)\*!\[\]\{\}\n\r\^]")
```

We design two validation modes:
1. **Strict (Default)**: Reject quotes (`'` and `"`) as well as `SHELL_INJECTION_RE` to enforce high-security inputs.
2. **Quoted Subcommand (Flexible)**: Allow quotes for parameter grouping when invoking `shlex.split(command)`, but still strictly reject all other operators.

---

## 4. Secure settings.json Config Handler Design

The Antigravity CLI configures settings via `settings.json`.

### A. Target File Location
On Windows systems, the file is located inside the user's profile path:
* **Path**: `C:\Users\<Username>\.gemini\antigravity-cli\settings.json`
* **Python Resolution**:
  ```python
  from pathlib import Path
  settings_path = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
  ```

### B. Secure Reader/Writer Implementation
```python
import os
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

# Valid settings configuration keys and their expected types
SETTINGS_SCHEMA = {
    "allowNonWorkspaceAccess": bool,
    "altScreenMode": str,
    "artifactReviewPolicy": str,
    "colorScheme": str,
    "editor": str,
    "enableTelemetry": bool,
    "enableTerminalSandbox": bool,
    "gcp": dict,
    "historySize": int,
    "model": str,
    "notifications": bool,
    "permissions": dict,
    "runningLightSpeed": str,
    "showFeedbackSurvey": bool,
    "showTips": bool,
    "statusLine": dict,
    "title": dict,
    "toolPermission": str,
    "trustedWorkspaces": list,
    "useG1Credits": bool,
    "verbosity": str,
}

def read_settings() -> Dict[str, Any]:
    path = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    if not path.exists():
        return {}
    try:
        # Prevent symbolic link traversal attacks by resolving target
        resolved = path.resolve(strict=True)
        # Limit size to prevent memory starvation (max 1MB)
        if resolved.stat().st_size > 1024 * 1024:
            raise ValueError("settings.json file size exceeds limit (1MB)")
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def write_settings(new_settings: Dict[str, Any]) -> bool:
    path = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
    current = read_settings()
    
    # Validation step: Filter and validate type of each setting key
    validated = {k: v for k, v in current.items() if k in SETTINGS_SCHEMA}
    for key, value in new_settings.items():
        if key not in SETTINGS_SCHEMA:
            continue  # Reject unknown properties
        expected_type = SETTINGS_SCHEMA[key]
        if not isinstance(value, expected_type):
            raise TypeError(f"Invalid type for key '{key}': expected {expected_type}, got {type(value)}")
        if key == "trustedWorkspaces":
            # Extra validation for workspace list items
            if not all(isinstance(x, str) for x in value):
                raise TypeError("trustedWorkspaces must be a list of strings")
        validated[key] = value

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic Write: Write to temporary file first, then replace original
        with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, suffix=".tmp", encoding="utf-8") as tf:
            json.dump(validated, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, str(path))
        return True
    except Exception:
        if 'temp_name' in locals() and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except Exception:
                pass
        return False
```

---

## 5. Proposed Tool Integrations

Three new tools will be added to `app/forge_mcp_registry.py` under namespaces corresponding to their functions:

### 1. `agy_run`
* **Internal Name**: `agy_run`
* **Canonical Name**: `forge.code.agy_run`
* **Description**: Execute a subcommand via the Antigravity CLI (`agy`). Shell injections are strictly blocked.
* **Input Schema**:
  ```json
  {
      "type": "object",
      "properties": {
          "command": {"type": "string", "description": "The sub-command to run under agy, e.g. 'task list'."},
          "timeout": {"type": "integer", "description": "Command timeout in seconds (default 60)."}
      },
      "required": ["command"]
  }
  ```
* **Required Ring**: **Ring 2** (allows standard workspace agents to run task lookups).

### 2. `agy_config`
* **Internal Name**: `agy_config`
* **Canonical Name**: `forge.meta.agy_config`
* **Description**: Read or write configuration keys in the Antigravity `settings.json` file.
* **Input Schema**:
  ```json
  {
      "type": "object",
      "properties": {
          "action": {"type": "string", "enum": ["read", "write"], "description": "Action to perform (read or write)."},
          "key": {"type": "string", "description": "The setting key to access."},
          "value": {"type": "string", "description": "The value to write (ignored for read)."}
      },
      "required": ["action", "key"]
  }
  ```
* **Required Ring**: **Ring 3** for `"read"`, **Ring 1** for `"write"` (since modifications change execution profiles).

### 3. `agy_add_dir`
* **Internal Name**: `agy_add_dir`
* **Canonical Name**: `forge.fs.agy_add_dir`
* **Description**: Add an absolute directory path to the trusted workspaces in `settings.json`.
* **Input Schema**:
  ```json
  {
      "type": "object",
      "properties": {
          "path": {"type": "string", "description": "Absolute file path of the directory to add to trusted workspaces."}
      },
      "required": ["path"]
  }
  ```
* **Required Ring**: **Ring 2** (prevents unprivileged agents from modifying executing directories).
