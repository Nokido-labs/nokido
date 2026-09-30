# Test Infrastructure Documentation (TEST_INFRA.md)

This document describes the testing infrastructure, design philosophy, architecture, and methodologies applied to the integration of the Antigravity CLI (`agy`) as an MCP tool suite within the Nokido Sovereign Hub.

---

## 1. Test Philosophy

The testing architecture for Nokido relies on the **4-Tier Test Design Methodology**, which provides layered isolation, comprehensive coverage, and robust defense-in-depth verification:

- **Tier 1: Feature Coverage**: Verifies that each individual component, function, interface, registry mapping, schema validation, and execution path functions correctly in isolation under standard conditions.
- **Tier 2: Boundary & Corner Cases**: Stress-tests components against malicious input, command injections, invalid parameters, timeouts, corrupt database files, and resource limit overflows.
- **Tier 3: Cross-Feature Combinations**: Validates integration correctness across sequential feature invocations that share state (e.g., config modification followed by command execution).
- **Tier 4: Real-World Workloads**: Simulates real-world user workflows and developer environment setup pipelines to guarantee end-to-end reliability.

To ensure compliance with the **Integrity Mandate**, no mocks or fake logic are hardcoded to fool tests. Mocks are strictly used as test doubles for external subprocesses and OS environment files.

---

## 2. Feature Inventory

The test suite covers the following features across the three new MCP tools:

1. **`agy_run` (Canonical: `forge.code.agy_run`)**
   - Tool registration and schema publication.
   - Ring 2 execution authorization checks.
   - Shell injection protection (rejections of chainers like `;`, `&&`, `|`, `$()`, `` ` ``, `^`, redirection operators `<`, `>`, globbing `*`, and newlines).
   - Safe subprocess execution without shell execution context (`shell=False`).
   - Timeout handling and exit code propagation.

2. **`agy_config` (Canonical: `forge.meta.agy_config`)**
   - Ring 3 read authorization / Ring 1 write authorization checks.
   - Secure reading and writing of `~/.gemini/antigravity-cli/settings.json`.
   - Settings validation against the predefined schema (`SETTINGS_SCHEMA`).
   - Type verification and list filtering.
   - Atomic writes (write to a temporary file in the same directory, then rename) to prevent settings corruption on failure.
   - Graceful recovery from malformed/corrupt configurations.

3. **`agy_add_dir` (Canonical: `forge.fs.agy_add_dir`)**
   - Ring 2 authorization check.
   - Directory validation ensuring the path is non-empty and absolute.
   - Appending paths to the `trustedWorkspaces` array inside `settings.json`.

---

## 3. Test Architecture

### Test Runner
We use **pytest** as the primary test runner for the Nokido project. 
- Command: `python -m pytest tests/test_agy_mcp.py -v --tb=short`

### Layout
- Source Directory: `app/` containing registry implementations.
- Test Directory: `tests/` containing co-located tests.
- Test File: `tests/test_agy_mcp.py` isolates the test coverage.

### Formats & Isolation
To prevent the tests from modifying the developer's actual home directory configurations or executing real destructive commands:
- **Home Directory Mocking**: The `mock_home` pytest fixture overrides `pathlib.Path.home` using `unittest.mock.patch` to direct all settings reads and writes to a unique temporary directory created by pytest (`tmp_path`).
- **Subprocess Mocking**: Subprocess invocations of the `agy` CLI are intercepted using `unittest.mock.patch("subprocess.run")` and `MagicMock` instances returning customizable returncodes, stdout, and stderr.
- **Event Bus & Database Stubbing**: Database accesses for Ring evaluation and logging event publishes are stubbed or mocked, making the unit and E2E tests fully self-contained and network-isolated.

---

## 4. Real-World Application Scenarios (Tier 4)

Tier 4 tests model realistic scenarios representing daily workflows:

1. **`test_workload_developer_workspace_init`**: Simulates the first-time setup of a developer workspace. It checks telemetry default settings, opts out of telemetry, sets the preferred code editor, registers the Nokido directory in `trustedWorkspaces`, and performs a task lookup command.
2. **`test_workload_telemetry_opt_out_with_event_bus`**: Simulates a privacy-conscious user opting out of telemetry. It checks that the state change is published to the central Nokido EventBus log.
3. **`test_workload_editor_config_lifecycle`**: Simulates configuring alternative code editors (e.g. Vim, VS Code) in settings and verifies they are restored to default clean state.
4. **`test_workload_bulk_workspace_authorization`**: Simulates configuring several workspaces at once and verifies they are written atomically to settings without race conditions or JSON corruption.
5. **`test_workload_pipeline_cli_mock`**: Simulates a workflow pipeline: creating a task, querying the active tasks list, and completing the task.

---

## 5. Coverage Thresholds

| Test Tier | Focus Area | Required Tests | Configured Tests |
|-----------|------------|----------------|------------------|
| **Tier 1**| Basic Features & Schemas | >= 15 | 18 |
| **Tier 2**| Boundaries & Sanitization | >= 15 | 18 |
| **Tier 3**| Combinations & State Checks | >= 3 | 3 |
| **Tier 4**| End-to-End User Workloads | >= 5 | 5 |
| **Total** | **Comprehensive Suite** | **>= 38** | **44** |
