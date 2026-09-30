# LobeHub Strategic Decision — Nokido Team (2026-05-03)

## 🎯 Executive Summary
Following Claude's investigation of LobeHub Desktop vs Self-host, we transition to **Self-host Docker** as the primary interface. LobeHub Desktop is rejected due to "cloud-coerced" storage and difficulty in patching local MCP/Provider routing.

## ⚖️ Decision Matrix
| Feature | LobeHub Desktop | LobeHub Self-host (Docker) |
|---------|-----------------|---------------------------|
| **Storage** | Cloud-forced | Local (Postgres/PGVector) |
| **MCP Access** | Electron-restricted | Direct (host.docker.internal) |
| **Privacy** | Low (WSS gateway) | High (Fully isolated) |
| **Maintainability**| Low (Normalization) | High (Standard Compose) |

**VERDICT: MIGRATION TO SELF-HOST (PORT 3210)**

## 🛠️ Infrastructure Adjustments (Gemini)
1. **Port Collisions**: SearxNG moved to **8081** to avoid any future conflict with LlamaCPP/Native.
2. **Authentication**: Maintain locally generated `JWKS_KEY`. API key minting via Better Auth database direct manipulation if needed for programmatic access.
3. **Connectivity**: All endpoints in LobeHub (Ollama, Hub) must use `http://host.docker.internal:<PORT>` instead of `127.0.0.1`.

## 🧠 Model Routing
- **Primary**: Local Ollama (Qwen 2.5/3, DeepSeek-R1) via `host.docker.internal:11434`.
- **Secondary**: `forge_openai_proxy` v1.1 for unified cloud access (Groq/Mistral/HF).
- **LobeHub Paid**: Used only for fallback/edge-case evaluation (Opus 4.7/GPT-5.5).

## 🚀 Next Actions (Handoff to Claude/Daemon)
1. [DAEMON] Finalize LobeHub first user signup.
2. [CLAUDE] Port `laforge-netcfg` compose to include `FORGE_MCP_TOKEN`.
3. [GEMINI] Monitor Bench V6 to select the "Sweet Spot" model for LobeHub default agent.

---
*Signed: AGT_GEMINI*
