# relaydeck ↔ Nokido — audit comparatif (veille 2026-06-21)

`relaydeck` = "local-first fleet OS for CLI coding agents" : wrappe des CLI vendor
(Claude Code/Codex/Cursor/OpenCode/Antigravity/pi) en **PTY unattended**, daemon
FastAPI/SSE/WS, inbox SQLite durable inter-agents, peer discovery par purpose/tags,
plugins (harnesses/providers/skills/automations), dashboard, Telegram, vault on-host.
Zéro cloud/télémétrie. = **jumeau externe de la vision Nokido** → validation + idées.

## Carte feature → module Nokido (équivalences)

| relaydeck | Nokido équivalent | État |
|---|---|---|
| Fleet OS (daemon gère workers) | supervisor `proxy_deno/core/services.toml` + LaForge-Master | ✅ couvert (plus riche : waves, runAs, heartbeat) |
| Inbox SQLite durable + late-drain | `app/forge_postal.py` (RAG/postal.db : queued→delivered→acked, dédup, hops, dead-letter) | ✅ couvert (cycle de vie + accusés plus fin) |
| Peer discovery (purpose/tags) | `config/agent_identities.json` + `_AGENT_LIST` + ring `forge_integrity` | ⚠️ partiel : identité oui, **discovery par tags = non** |
| Harnesses multi-CLI (PTY unattended) | bridges MCP (Claude/Gemini/Cline/Codex/agy) + cowork autonome + adaptateur ACP | ⚠️ partiel : CLI branchés, mais **pas de wrapper PTY-unattended générique** |
| Multi-provider (Anthropic/OpenAI/OpenRouter/Ollama) | `forge_agent_proxy` (~40 providers) + `forge_endpoint_registry` | ✅ couvert (largement supérieur) |
| Observabilité (PTY live, usage, status) | web hub :7400/:7401, traces, `forge_organ_pulse`, heartbeats | ✅ couvert |
| Dashboard web (agent lens config/events/inbox) | web hub Deno/FastAPI + SSE | ✅ couvert |
| Plugin system (harness/provider/skill/automation) | skills Nokido + clawhub + `dyn_skill_forge` | ✅ couvert |
| Secret vault on-host | vault **DPAPI** | ✅ couvert (DPAPI > fichier chiffré) |
| Telegram remote control | — | ❌ absent (roadmap BLE buddy ≠ Telegram) |

**Verdict** : Nokido couvre ~80% de relaydeck, souvent en plus profond (postal
lifecycle, 40 providers, DPAPI, supervisor waves). relaydeck = preuve externe que
l'architecture fleet-souveraine-locale de Nokido est la bonne. 3 idées net-new à miner.

## À MINER (net-new, backlog priorisé)

1. **PTY-unattended harness générique** — relaydeck transforme N'IMPORTE quel CLI en
   worker supervisé en PTY (stdin/stdout pilotés, headless). Nokido branche les CLI
   via MCP/ingress mais n'a pas le wrapper « prends un binaire CLI quelconque, lance-le
   en PTY, pilote-le ». Colle au travail ACP récent (`forge_acp_server` + service
   `NokidoAcpWs`) : un harness PTY = exposer tout CLI comme worker fleet. netcfg a
   déjà du PTY (`forge_pty.py`) → réutiliser comme socle. **P1**.
2. **Peer discovery par purpose/tags** — au lieu du `_AGENT_LIST` statique, taguer chaque
   agent (purpose/capabilities) et permettre `find_peers(tag)`. Extension naturelle de
   `agent_identities.json` + portail. **P2**.
3. **Canal de contrôle distant (Telegram-like)** — relaydeck pilote la flotte par Telegram.
   Nokido n'a pas de canal mobile (BLE buddy = roadmap local). Un bot Telegram → hub
   `run`/`notify`/`ask` gouverné = contrôle mobile souverain. **P3** (surface d'attaque
   à firewaller : passer par le videur + ring).

## Anti-dup
NE PAS réimplémenter : inbox (forge_postal couvre mieux), multi-provider (forge_agent_proxy),
supervisor (services.toml), vault (DPAPI), dashboard. Seuls #1/#2/#3 ci-dessus sont net-new.
