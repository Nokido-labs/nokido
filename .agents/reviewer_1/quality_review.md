## Review Summary

**Verdict**: REQUEST_CHANGES

## Findings

### [Critical] Finding 1: Lack of Executable Restriction in `handle_agy_run` (Ring Bypass)

- **What**: The tool `agy_run` allows running arbitrary shell commands without prepending the `agy` binary or enforcing that `agy` is the target executable.
- **Where**: `app/forge_mcp_registry.py` (lines 2594-2659)
- **Why**: The tool requires Ring 2. However, the standard `run` tool for running generic shell commands requires Ring 1. By executing arbitrary commands directly, a Ring 2 agent can call any command in the PATH (such as `git` or `whoami`), bypassing the Ring 1 safety constraints.
- **Suggestion**: Restrict execution to the `agy` executable by forcing the first item in the argument list to be `agy` (or prepend `agy` to the arguments). For example:
  ```python
  cmd_args = ["agy"] + shlex.split(command)
  ```

### [Major] Finding 2: Lack of Path Canonicalization in `handle_agy_add_dir`

- **What**: Path inputs to `agy_add_dir` are checked for being absolute but are not canonicalized.
- **Where**: `app/forge_mcp_registry.py` (lines 2795-2796)
- **Why**: An attacker can register paths like `C:/workspace/../Windows/System32`. While technically absolute, it contains directory traversal sequences. If subsequent checks on trusted paths rely on prefix matching, they may grant access to untrusted parent directories.
- **Suggestion**: Canonicalize the path before appending it to `trustedWorkspaces` using `os.path.abspath(os.path.realpath(path))` or `Path(path).resolve()`.

### [Major] Finding 3: Windows Batch Expansion Vulnerability (`%` not in blacklist)

- **What**: The blacklist pattern in `handle_agy_run` does not block the `%` symbol.
- **Where**: `app/forge_mcp_registry.py` (line 2605)
- **Why**: On Windows, wrapping scripts for `agy` (such as `agy.cmd` or `agy.bat`) are invoked via `cmd.exe`. `cmd.exe` parses parameters by expanding `%VAR%` variables. The omission of `%` in the blacklist can lead to information leaks or execution environment manipulation.
- **Suggestion**: Add `%` to the blacklist pattern `[;&|`$<>\(\)\*!\[\]\{\}\n\r\^]`.

### [Minor] Finding 4: TOCTOU Race Condition on `settings.json` Size and Symlink Checks

- **What**: Symlink and size checks on `settings.json` are performed prior to file operations.
- **Where**: `app/forge_mcp_registry.py` (lines 2678-2685, 2806-2813)
- **Why**: Between checking the path and reading/writing the file, another process could modify the path or replace the file.
- **Suggestion**: Open the file first and perform fstat checks on the file descriptor to ensure the checks are atomically bound to the opened file.

## Verified Claims

- Mapping of `_NAMESPACE_ALIASES` → verified via static code analysis → PASS
- Tool registrations in `_raw_tool_catalog()` → verified via static code analysis → PASS
- Fallback ring assignments in `_get_ring_needed()` → verified via static code analysis → PASS
- Subprocess execution parameters (`shell=False`, capture output) → verified via static code analysis → PASS
- Settings file write atomicity via tempfile → verified via static code analysis → PASS

## Coverage Gaps

- **Dynamic test execution** — risk level: low (since tests are well-written and mocked, code aligns with test expectations) — recommendation: execute tests once user is online and command approval can be granted.

## Unverified Items

- Real-world execution of `agy` CLI binary — reason not verified: `agy` binary not present/accessible in static review workspace, and commands timed out.
