# Test Readiness Status (TEST_READY.md)

This file contains the current state of test readiness, execution details, and feature checklists for the Antigravity CLI (`agy`) MCP integration.

---

## 1. Test Runner Command

To run the full E2E test suite in isolation, use:

```bash
%USERPROFILE%/miniforge3/python.exe -m pytest tests/test_agy_mcp.py -v --tb=short
```

To run all tests in the project (including this new suite):

```bash
%USERPROFILE%/miniforge3/python.exe -m pytest tests/ -v --tb=short
```

---

## 2. Coverage Summary

Our test suite implements **44 tests** structured according to the 4-Tier test design methodology:

| Tier | Category | Implemented Count | Minimum Required | Status |
|------|----------|-------------------|------------------|--------|
| **Tier 1** | Feature Coverage | 18 | 15 | ✅ READY |
| **Tier 2** | Boundary & Corner Cases | 18 | 15 | ✅ READY |
| **Tier 3** | Cross-Feature Combinations | 3 | 3 | ✅ READY |
| **Tier 4** | Real-World Workloads | 5 | 5 | ✅ READY |
| **Total** | **All Tiers** | **44** | **38** | ✅ READY |

*Note: Since the backend registry implementation (handlers and namespace mappings) is scheduled to be built in Milestones 3 & 4, the tests will fail on registry dispatch checks until the handlers are fully implemented. Tests checking namespace translation, schemas, and helper methods are ready to pass once mapped.*

---

## 3. Feature Checklist

- [x] **Namespace Schema Registrations**
  - [x] Schema check for `forge.code.agy_run`
  - [x] Schema check for `forge.meta.agy_config`
  - [x] Schema check for `forge.fs.agy_add_dir`
- [x] **Namespace Aliasing**
  - [x] `forge.code.agy_run` and `forge_agy_run` resolve to `agy_run`
  - [x] `forge.meta.agy_config` and `forge_agy_config` resolve to `agy_config`
  - [x] `forge.fs.agy_add_dir` and `forge_agy_add_dir` resolve to `agy_add_dir`
- [x] **Explanation Field Enforcement**
  - [x] Explanation check for `agy_run`
  - [x] Explanation check for `agy_config`
  - [x] Explanation check for `agy_add_dir`
- [x] **Input Sanitization & Injection Defense**
  - [x] Semicolon chain rejection
  - [x] Pipe chain rejection
  - [x] Ampersand chain rejection
  - [x] Subshell chainer rejection
  - [x] Backtick evaluation rejection
  - [x] Output redirection rejection
  - [x] Glob wildcards rejection
  - [x] Newline injection rejection
  - [x] Windows CMD caret character rejection
- [x] **Subprocess Invocation Parameters**
  - [x] Execution with `shell=False`
  - [x] Custom timeouts configurations
  - [x] Exit code and output status reporting
- [x] **Settings Reader & Writer**
  - [x] Schema validation and type filtering
  - [x] Path sanitization (symbolic link prevention)
  - [x] File size restriction checking (< 1MB)
  - [x] Atomic file writes using tempfiles
- [x] **Workspace Add Operation**
  - [x] Path existence checks
  - [x] Absolute path enforcement
  - [x] Append updates inside the `trustedWorkspaces` setting array
- [x] **RBAC Ring Integrations**
  - [x] Ring 2 validation check for `agy_run`
  - [x] Ring 3 validation check for `agy_config` (read)
  - [x] Ring 1 validation check for `agy_config` (write)
  - [x] Ring 2 validation check for `agy_add_dir`
