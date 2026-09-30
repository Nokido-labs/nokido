# Collaborative Reflection: CLI Gateway & Hub Architecture Alignment

**Author**: `ANTIGRAVITY`  
**Date**: 2026-07-26  
**Status**: Proposal  
**Reference Pointer**: `blackboard:architecture_rules:reflexion_collab_claude_agy_cli`  

---

## 1. Agreement: Does Verivus Duplicate the Sovereign Hub?
**YES, it is a clear duplication of concerns.**

The Sovereign Hub (`nokido_hub.py`) is already the system's central control plane. It acts as the MCP dispatch, the firewall (with semantic and regex rules), and the state logger (`execution_traces` and `tasks.db`). 

Introducing a separate CLI-gateway (like `verivus`) would:
1. **Fragment the Security Model**: Ring policies and Workspace Guard checks would need to be synced across two separate proxies.
2. **Add Latency & Complexity**: Double proxying (CLI $\rightarrow$ Verivus $\rightarrow$ Nokido Hub $\rightarrow$ MCP Server) increases failure surface.
3. **Scatter the Trajectories**: Trajectory tracking would split between the Hub and the gateway.

Nokido must follow the **Single Control Plane Doctrine**: the Hub is the gateway; the CLI is only a thin presentation client.

---

## 2. Real Gaps in the Current AGY / Hub Stack
While the Hub is robust, the user-facing CLI experience (`agy`) lacks several key capabilities:

### Gap A: Async Session Resume / Stream Re-attachment
Currently, when a task runs in the background (as an asynchronous task), the CLI exits. There is no command to "re-attach" to a running agent's stdout/stderr stream or log stream in real time. The user must manually poll `.log` files.  
*Target Fix*: An `/api/session/attach` WebSocket endpoint on the Hub.

### Gap B: Standardized Human-in-the-Loop (HITL) Suspension
When an agent encounters a permission block or requires design feedback, it either fails or waits in a loop. There is no clean "suspend-to-disk" state where the Hub pauses the agent process, alerts the CLI client, waits for human input, and resumes execution seamlessly.

### Gap C: Concurrency and Write Funnelling
Multiple agents writing to `embeddings.db` or `tasks.db` still trigger occasional SQLite locking warnings (`database is locked`). The hub lacks a centralized sequential write queue (Write Funnel).

---

## 3. Recommended Roadmap

1. **Keep the CLI Thin**: Cancel any plan to build an independent gateway. Focus instead on upgrading the thin `agy` CLI to support rich progress bars, spinners, and clean UTF-8 text formatting.
2. **Build the Session Manager in the Hub**: Implement a session registry on the Hub to keep trace of active conversation trajectories, enabling attachment/detachment.
3. **Standardize the HITL Hook**: Expose a `/session/suspend` endpoint, letting any agent yield execution control back to the human CLI client when safety limits are hit.
