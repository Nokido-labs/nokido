# Adversarial Review Report — agy MCP Integration

**Overall risk assessment**: HIGH

## Challenges

### [Critical] Challenge 1: Command Hijacking and Execution of Arbitrary Binaries
- **Assumption challenged**: The implementation assumes the `command` input contains only safe subcommands for `agy` and that `shlex.split` prevents execution of arbitrary binaries.
- **Attack scenario**: An attacker invokes the tool with `command="python -c \"import os; os.system(...)`"`. Since `python` is a valid executable name and contains no forbidden characters, `shlex.split` creates `['python', '-c', '...']`. `subprocess.run` executes python, bypassing the entire shell sanitization regex.
- **Blast radius**: Full shell access and command execution on the host machine.
- **Mitigation**: Enforce `cmd_args = [agy_path] + shlex.split(command)` so that the executable is always the trusted `agy` binary.

### [High] Challenge 2: Workspace Authorization Path Traversal Bypass
- **Assumption challenged**: The implementation assumes checking `os.path.isabs` is sufficient to verify workspace directories.
- **Attack scenario**: An attacker passes `C:/workspace/../../Windows/System32`. The path is absolute, but resolves to `C:/Windows/System32`. It is appended to `trustedWorkspaces`. Any downstream safety checks performing prefix match validation against `trustedWorkspaces` will now permit file operations inside the system folder.
- **Blast radius**: Complete bypass of path containment checks.
- **Mitigation**: Canonicalize the path using `Path(path).resolve()` before adding it.

### [Medium] Challenge 3: settings.json Denial of Service (DoS) and Corruption
- **Assumption challenged**: The implementation assumes `settings.json` is always well-formed or that it's safe to clear it on error.
- **Attack scenario**: An attacker causes a disk write failure or injects a single malformed character into `settings.json`. The next call to `agy_config` or `agy_add_dir` reads the corrupted file, catches the exception, resets the config to `{}`, and writes it, permanently deleting all user configurations.
- **Blast radius**: Config settings loss.
- **Mitigation**: Abort the write and return a clear error if the file exists but cannot be parsed as valid JSON dict.

## Stress Test Results
- None.

## Unchallenged Areas
- Event bus logging and sqlite database querying — reason: not checked because of test environment constraints.
