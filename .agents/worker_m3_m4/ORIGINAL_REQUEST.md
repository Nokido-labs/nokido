## 2026-06-23T14:33:14Z
You are a teamwork_preview_worker subagent named worker_m3_m4.
Your working directory is: %NOKIDO_WORKSPACE%/LaForge/.agents/worker_m3_m4/
Your parent conversation ID is: d6b53407-6743-4bf2-a5a4-673ee05a5f4a

Mission:
Implement the Antigravity CLI (agy) MCP tools integration in `app/forge_mcp_registry.py` and run tests in `tests/test_agy_mcp.py` to verify that all 44 test cases pass cleanly.

Context:
- Global Original Request: %NOKIDO_WORKSPACE%/LaForge/ORIGINAL_REQUEST.md
- Project Design: %NOKIDO_WORKSPACE%/LaForge/.agents/orchestrator/PROJECT.md
- Technical Design Analysis: %NOKIDO_WORKSPACE%/LaForge/.agents/explorer_m1/analysis.md
- Test Suite: %NOKIDO_WORKSPACE%/LaForge/tests/test_agy_mcp.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Detailed Instructions:
1. Modify `app/forge_mcp_registry.py` to:
   - Add aliases mapping to `_NAMESPACE_ALIASES`:
     ```python
     "forge.code.agy_run": "agy_run",
     "forge_agy_run": "agy_run",
     "forge.meta.agy_config": "agy_config",
     "forge_agy_config": "agy_config",
     "forge.fs.agy_add_dir": "agy_add_dir",
     "forge_agy_add_dir": "agy_add_dir",
     ```
   - Register the tools in `_raw_tool_catalog(self)`:
     - `forge.code.agy_run` (properties: `command` required string, `timeout` optional integer)
     - `forge.meta.agy_config` (properties: `action` enum ["read", "write"] required string, `key` required string, `value` optional any)
     - `forge.fs.agy_add_dir` (properties: `path` required string)
   - Register Ring level constraints in `_get_ring_needed(self, name, args)` fallback logic:
     - If `name == "agy_config"`: write action returns 1, read action returns 3.
     - If `name in ("agy_run", "agy_add_dir")`: returns 2.
   - Implement handlers in the `ToolRegistry` class, inserting `handle_agy_run`, `handle_agy_config`, and `handle_agy_add_dir` right before `handle_read`:
     - Implement subprocess command parsing via `shlex.split`, execution with `shell=False`, and command injection prevention using the sanitization regex `[;&|`$<>\(\)\*!\[\]\{\}\n\r\^]`. Enforce command length <= 500.
     - Implement settings.json reader/writer with atomic file replacement using temporary files, symbolic link resolution check, size checks (<1MB), and schema validation.
     - Implement directory validation in `handle_agy_add_dir` ensuring the path is non-empty and absolute, then append it to `trustedWorkspaces` array.

2. Run the test suite:
   ```bash
   %USERPROFILE%/miniforge3/python.exe -m pytest tests/test_agy_mcp.py -v --tb=short
   ```
   Ensure ALL 44 tests pass successfully. If there are failures, debug and fix the implementation until everything passes.

3. Write a handoff.md detailing changes made, test results, andLayout compliance.
4. Send a message to your parent.
