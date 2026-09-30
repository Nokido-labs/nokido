# Original User Request

## Initial Request — 2026-06-23T16:26:21+02:00

Integrate the Antigravity CLI (agy) as an MCP tool suite directly within the Nokido Sovereign Hub. The integration must expose both agentic task execution and local workspace/CLI configurations to Nokido agents as inline execution wrappers.

Working directory: %NOKIDO_ROOT%
Integrity mode: development

## Requirements

### R1. Direct agy CLI Tool Integration
The system must expose a set of MCP tools within Nokido that allow agents to interact with the Antigravity CLI (`agy`). These tools must cover both agent execution (submitting queries/tasks to the `agy` CLI) and configuration/metadata retrieval (reading or writing keys in `settings.json`, adding directories to the workspace, and checking quota/token usage).

### R2. Inline Execution Wrapper Architecture
The tools must be implemented as inline python handlers directly within Nokido's unified dispatcher (`forge_mcp_registry.py`), invoking the `agy` CLI executable via standard subprocess mechanisms rather than launching a standalone MCP server process. The integration must handle Windows shell formatting, timeouts, and capture stdout/stderr output cleanly.

### R3. Secure and Robust Input Sanitization
All commands dispatched to the `agy` CLI must be sanitized to prevent shell injection or unauthorized file access. Tool arguments (such as custom prompt strings or file paths) must be validated before execution, and the integration must handle errors gracefully without crashing the Nokido Sovereign Hub.

## Acceptance Criteria

### Tool Registration & Catalog
- [ ] The Nokido MCP catalog (`_all_tools()`) must expose the new `agy_*` tools (e.g. `forge.code.agy_run`, `forge.meta.agy_config`, `forge.fs.agy_add_dir`).
- [ ] All new tools must declare standard `inputSchema` arguments with parameter descriptions and include the required `explanation` field.

### Subprocess Invocation & Parsing
- [ ] Calling the agent execution tool (e.g. `agy_run`) runs the `agy` CLI asynchronously.
- [ ] The wrapper must correctly capture and return stdout, stderr, and the exit status.
- [ ] The wrapper must support configurable execution timeouts.

### Workspace & Config Management
- [ ] The config tool can read and write keys in `~/.gemini/antigravity-cli/settings.json` safely.
- [ ] The directory-adding tool must successfully update the workspace paths recognized by `agy`.

### Security and Code Quality
- [ ] Tool arguments are validated to reject shell injection tokens (e.g., `;`, `&&`, `|`) in raw inputs.
- [ ] The codebase changes pass standard linting and formatting without warnings.

### Automated Testing & Verification
- [ ] A test suite at `tests/test_agy_mcp.py` verifies tool registration, parameter mapping, execution of the subprocess, config file manipulation, and error states.
- [ ] The test suite passes successfully.
