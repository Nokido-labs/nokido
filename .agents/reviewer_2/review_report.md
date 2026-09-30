# Quality Review Report — agy MCP Integration

**Verdict**: REQUEST_CHANGES

## Findings

### [Critical] Finding 1: Execution of Arbitrary Binaries (Privilege Escalation)
- **What**: `handle_agy_run` does not restrict execution to the `agy` binary.
- **Where**: `app/forge_mcp_registry.py`, lines 2614-2628.
- **Why**: It splits the user-controlled `command` string via `shlex.split` and directly executes the resulting first token. A Ring 2 agent can execute any arbitrary executable on the system (e.g. `cmd.exe`, `python.exe`) rather than only `agy` CLI subcommands as designed.
- **Suggestion**: Force execution of `agy` by setting the first argument in `cmd_args` to the absolute path of `agy` (resolved via `shutil.which`) and treating the user command as subcommand arguments.

### [Critical] Finding 2: Path Traversal in Workspace Trust
- **What**: `handle_agy_add_dir` does not resolve directory paths.
- **Where**: `app/forge_mcp_registry.py`, lines 2788-2797.
- **Why**: It only checks if the path is absolute using `os.path.isabs`, but does not resolve path traversal components (e.g. `C:/projects/nokido/../../Windows/System32`). An attacker can add directories with `..` components to trust unauthorized locations.
- **Suggestion**: Fully resolve paths using `Path(path).resolve()` before verification and storage.

### [Major] Finding 3: PATH Hijacking Vulnerability
- **What**: `handle_agy_run` executes commands without path resolution.
- **Where**: `app/forge_mcp_registry.py`, line 2628.
- **Why**: The system resolves the executable from the environment PATH variable. In a sandbox environment or multi-tenant system, this allows an attacker to drop a fake executable (e.g. `task`) in a directory listed early in the PATH and hijack the command execution.
- **Suggestion**: Use `shutil.which` to locate the trusted `agy` binary path.

### [Major] Finding 4: Silent Config Destruction on Parse Fail
- **What**: Syntax error in `settings.json` causes entire configuration to be wiped on write.
- **Where**: `app/forge_mcp_registry.py`, lines 2745-2755 and 2816-2826.
- **Why**: If `settings.json` is malformed (fails to parse), the `try-except` block catches the exception and resets `config_data` to `{}`. A write operation will then overwrite the file, losing all other configuration keys.
- **Suggestion**: If parsing fails, raise/return a descriptive error to prevent overwriting the corrupted file.

### [Minor] Finding 5: Missing Default Timeout
- **What**: Timeout is not defaulted to 60 seconds.
- **Where**: `app/forge_mcp_registry.py`, lines 2625-2627.
- **Why**: The specification in `PROJECT.md` defines a default timeout of 60 seconds. Currently, it defaults to no timeout if omitted, which can cause hanging subprocesses.
- **Suggestion**: Set default `timeout = 60` if not provided in arguments.

## Verified Claims
- None (pytest execution timed out waiting for user approval).

## Coverage Gaps
- Pytest verification is a coverage gap as we could not run it due to the offline user. Recommendation: Accept risk of static-only review or request user/orchestrator run the command.

## Unverified Items
- Pytest execution of `tests/test_agy_mcp.py` — reason not verified: permission prompt timed out.
