# Security Analysis: Aligning Nokido with "Don't Let AI Agents YOLO Your Files"

**Author**: `ANTIGRAVITY`  
**Date**: 2026-07-26  
**Status**: Completed  
**Reference Paper**: *Don't Let AI Agents YOLO Your Files: Shifting Information and Control to Filesystems for Agent Safety and Autonomy*  

---

## 1. Introduction & Core Concept of the Paper
The referenced paper conducts a systematic study of agent filesystem misuse, demonstrating that agents frequently:
1. **Corrupt critical code/data** through poorly formatted or incomplete writes.
2. **Delete/override** configuration files, leading to denial of service.
3. **Leak secrets** by reading outside their workspace boundaries and sending them to LLM providers.

To solve this tradeoff between safety and autonomy, the paper advocates shifting control from the agent/application layer (which is highly vulnerable to jailbreaks/prompt injections) to the **Filesystem/OS layer** using:
- **Isolated User Namespaces & OS Sandbox Accounts**.
- **Ephemeral/Copy-on-Write (CoW) workspaces**.
- **Intent-based, Task-scoped Write Permissions**.

---

## 2. Nokido's Current Security Architecture
Nokido implements a hybrid dual-layer defense:
1. **OS-Level Sandboxing (`forge_sandbox_exec.py`)**: Spawns agent-run command lines under restricted Windows Batch users (`LaForgeSbxOffline` / `LaForgeSbxOnline`) with restricted system access.
2. **Application-Level ACLs (`forge_workspace_guard.py`)**: Defines a `WorkspaceGuard` class enforcing Ring levels (0 to 9) and list filters (`ALWAYS_DENIED`, `READ_ONLY`).

---

## 3. Gap Analysis
By confronting the paper's findings with Nokido's codebase, we identify the following critical security gaps:

### Gap 1: In-Process Tool Execution Privilege Escalation
Nokido's Hub runs in a privileged context (e.g. `SYSTEM` under NSSM). While command lines are spawned under low-privilege users, many file editing tools (such as `replace_file_content` or `write_to_file`) are executed **in-process** inside the Hub's thread. If `WorkspaceGuard` has a parsing or logical error, the agent gains direct, un-sandboxed `SYSTEM` write access to the host machine.

### Gap 2: Lack of Ephemeral/Copy-on-Write Workspaces
Agents currently edit files directly inside the live repository (`%NOKIDO_ROOT%\`). If an agent corrupts a file, we rely on Git (`git restore`) or rollback decorators. If the Git state gets locked or corrupted, the host repository is permanently damaged.

### Gap 3: Coarse-Grained Ring Authorization
Nokido defines access control at the *agent level* (e.g., all Ring 1 agents can write to `sandbox/`). It lacks **Task-Scoped Write Authorization**, where an agent is only authorized to write to files explicitly declared in its active task description (e.g., if Task A is about editing `docs/`, the agent should be blocked from writing to `app/`).

---

## 4. Recommended Security Patterns to Import

### Pattern 1: Ephemeral Copy-on-Write Shadow Workspaces
For any task assigned to an agent, the homeostat should mount a temporary Copy-on-Write shadow folder (or a simple copy of target files to an ephemeral workspace outside the repository). The agent edits the shadow files. Only after a successful test run (`auto_test` or `pytest`) are the diffs merged back to the host repository.

### Pattern 2: Task-Scoped Write Boundaries
Extend `WorkspaceGuard` to query the active task database (`sandbox/tasks.db`). Before permitting a file write, the guard checks if the target path matches the scope described in the task payload. Writes to unauthorized paths are blocked, even if they are within the allowed write zones.

### Pattern 3: Sandbox-only Write Delegation
Ensure that no file mutation tool is executed with the Hub's `SYSTEM` privilege. All file write operations should be delegated to a sandboxed helper process running under the restricted `LaForgeSbxOffline` account, guaranteeing OS-level enforcement.
