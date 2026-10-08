---
type: guide
title: Nokido Wiki
status: draft
resource: repo://docs/wiki/Home.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# Nokido Wiki

<!-- revu-le: 2026-10-07 -->
> Updated: 2026-10-07

> 🌐 **English** · [Français](Home.fr.md)

Welcome to the **Nokido** wiki. Nokido is a **local-first runtime for an
artificial organism**: the nervous system and the physiology that let several
AIs — local models, cloud providers, coding agents — work together on your
machine without becoming a heap of independent agents. The
[README](../../README.md) gives the overview and the current status of each part.

This wiki is the **operator manual** — installation, configuration, day-to-day
workflows, troubleshooting. For the *why* behind Nokido's design, read
[MANIFESTO.md](../../MANIFESTO.md). For the technical internals, read
[docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## 🗺️ Table of contents

### Getting started
- [01 — Installation](01-Installation.md) · Docker, native, pip extras
- [17 — First launch](17-First-Launch.md) · 10-step setup walkthrough with the web admin UI
- [02 — Quick Start](02-Quick-Start.md) · First call, common workflows
- [03 — Architecture overview](03-Architecture.md) · Anatomy of the hub

### Connecting clients
- [04 — MCP clients setup](04-MCP-Clients-Setup.md) · Claude Desktop, Claude Code, Gemini CLI, Codex CLI, Cline
- [24 — Cloud peers](24-Cloud-Peers.md) · claude.ai and ChatGPT over HTTPS, owner quarantine
- [05 — LLM providers](05-LLM-Providers.md) · 29 providers, web admin UI

### Operating
- [06 — Hub API reference](06-Hub-API-Reference.md) · 25 MCP tools
- [07 — Security model](07-Security-Model.md) · Zero-trust layers
- [08 — Vault & secrets](08-Vault-and-Secrets.md) · DPAPI, Keychain, libsecret
- [09 — TUI reference](09-TUI-Reference.md) · Panes, keybindings
- [10 — Docker profiles](10-Docker-Profiles.md) · core, hub, full, all, dev
- [11 — Cross-OS notes](11-Cross-OS-Notes.md) · Windows vs Linux vs macOS

### Going deeper
- [12 — AMI cognitive stack](12-AMI-Cognitive-Stack.md) · LeCun, Friston, Hasani
- [13 — Hardware roadmap](13-Hardware-Roadmap.md) · NPU, neuromorphic, analog, photonic
- [18 — Launchers & service files](18-Launchers.md) · `.bat`, NSSM, systemd, plist
- [19 — Knowledge Pack](19-Knowledge-Pack.md) · Optional pre-vectorized Nokido code chunks (5-10 MB)
- [20 — Modules Reference](20-Modules-Reference.md) · Every module, defined by its own docstring, grouped by organ (generated)
- [23 — Orchestration & Workflows](23-Orchestration-and-Workflows.md) · GOAP, event loop, durable-execution direction (Temporal / Mistral)
- [21 — SSoT Cross-CLI](21-SSoT-Cross-CLI.md) · single source of truth, uniform "status of X" across CLIs, 5 domains
- [22 — Governance, cognition & self-safety](22-Governance-Cognition-Safety.md) · delivery integrity, knowledge curiosity, held-out gate, authority-weighted RAG, continuous Qdrant sync

### Help
- [14 — Troubleshooting](14-Troubleshooting.md)
- [15 — Glossary](15-Glossary.md)
- [16 — FAQ](16-FAQ.md)

---

## 📍 Quick links

| Resource | URL |
|---|---|
| Hub (running locally) | <http://127.0.0.1:8766> |
| Provider admin UI | <http://127.0.0.1:8766/admin/providers> |
| RBAC dashboard | <http://127.0.0.1:7400/rbac> |
| Health endpoint | <http://127.0.0.1:8766/health> |
| MCP endpoint | <http://127.0.0.1:8766/mcp> |
| Repository | <https://github.com/Nokido-labs/nokido> |
| Security contact | *Security* tab → *Report a vulnerability* |

---

*This wiki tracks branch `alpha` and `beta`. Public release reflects `main`.
Sections marked **alpha-only** are subject to change.*
