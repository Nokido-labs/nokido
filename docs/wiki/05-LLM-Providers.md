---
type: guide
title: 05 — LLM providers
status: draft
resource: repo://docs/wiki/05-LLM-Providers.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 05 — LLM providers

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

Nokido routes to **30 providers** (3 local + 3 CLI-OAuth + 24 cloud) via
cascade priority. Each one has a tier, a quota, a list of capabilities, and a
vault-stored API key (CLI-OAuth providers use no key — see below).

## 🖥️ Web admin UI

Open <http://127.0.0.1:8766/admin/providers> after [installing](01-Installation.md).

The page shows every provider with :

- **Tier** : `local` (free, infinite) / `free` (cloud free-tier) /
  `subscription_quota` / `paid_api`.
- **Capabilities** : chat, code, reasoning, vision, long_context, tool_call,
  rag, multimodal, thinking.
- **Context window** size.
- **Quota status** : calls/month, calls/day, percentage used.
- **Vault key** : the canonical env-var name (e.g. `GROQ_API_KEY`).
- **Status** : ✓ key present / ✗ no key / n/a (local).

Per row :

- 🔑 **Set key** — paste API key into a password input → POSTs to
  `/api/providers/<name>/key` → `forge_secrets.set_secret()` → vault DPAPI
  (Win) / Keychain (macOS) / libsecret (Linux).
- ▶ **Test** — hits the provider's health endpoint via `forge_provider_watcher`
  if available.
- ✗ **Remove** — `vault_delete(<key>)`, invalidates the cache.

Filters at the top : by name (substring), by tier, "only missing keys".

## 🎯 Tier 0 — Local (free, infinite)

| Provider | Engine | Port | Notes |
|---|---|---|---|
| `ollama_local` | Ollama | :11434 | Pull models via `ollama pull`. Default: `qwen2.5-coder:latest`. |
| `llamacpp_local` | llama.cpp `llama-server` | :8091 | OpenAI-compat. Its supervised service `NokidoLlamaNative` is **disabled by default** (`services.toml`). |
| `lmstudio_native` | LM Studio | :1234 | Manual model loading via the LM Studio UI. |
| `ollama_mimo_v2` | Ollama | :11434 | Second local Ollama slot. |

No API key needed for local. The hub probes the ports on startup.

## 🔑 Tier 0.5 — CLI OAuth (subscription free-tier, no API key)

Providers that drive a third-party CLI already authenticated (OAuth in the user profile) —
**zero API key**, the quota is the subscription. Spawn `<cli> -p "<prompt>"`, text output,
`SemanticFirewall` pre/post **automatic** (Golden Rule #4). Run in the user's context
(auth lives in `~/`), so `USERPROFILE`/`HOME` point at the real user (the hub runs as SYSTEM).

Three slots on 2026-09-29 (tier `subscription_quota`) : `claude_agent_sdk`, `claude_cli`
(legacy `claude -p`, same quota pool as the Agent SDK) and `gemini_cli` (`gemini -p`,
Google AI Studio free quota). The former `copilot_cli` slot is gone.

| Provider | CLI | Notes |
|---|---|---|
| `claude_agent_sdk` | Agent SDK | Claude subscription |
| `claude_cli` | `claude -p` | legacy, same pool |
| `gemini_cli` | `gemini -p` | headless spawn |

## ⚡ Tier 1 — Free cloud (generous quotas)

24 free-tier slots on 2026-09-29, among them : `groq`, `gemini_flash`, `gemini_flash_lite`,
`cohere_command_r`, `cohere_command_r_plus`, `sambanova`, `sambanova_llama_405b`, the
GitHub Models family (`github_gpt41_mini`, `github_gpt4o_mini`, `github_codestral`,
`github_llama_70b`, `github_deepseek_v3`), the OpenRouter free family
(`openrouter_qwen_coder`, `openrouter_gpt_oss`, ...), `cerebras`, `nvidia_nim`.

Quotas and models move with the vendors : the **live** list, with each slot's quota,
key and status, is `/admin/providers` ; the source is `app/forge_provider_specs.py::PROVIDER_SPECS`.
Do not copy a quota from this page into a decision.

## 💵 Tier 2 — Paid / opt-in

Disabled by default — explicitly enable per call.

Eight `paid_api` slots on 2026-09-29 : `claude`, `openai`, `mistral_large`, `mistral_small`,
`xai_grok3`, `xai_grok3_mini`, `deepseek`, `perplexity`.

## 🔀 Routing engine

The cascade is configured in `app/forge_provider_specs.py::PROVIDER_SPECS`
and consumed by `app/forge_llm_router.py::USE_CASE_CHAINS`.

When you call `ask(provider="auto", ...)`, the router :

1. Picks the *use_case* from the prompt (heuristic + `forge_dt_router`).
2. Builds a cascade chain for that use_case (preferring local → free → paid).
3. For each provider :
   - Skip if quota > 80% (`forge_provider_quota.should_skip`).
   - Skip if no key in vault.
   - Skip if `is_available()` returns False (health check).
   - Otherwise call `ask()` and return on success.
4. If all fail, return the cascade-degraded envelope.

You can pin a provider with `ask(provider="groq", ...)` to bypass cascade.

## 🧠 Use cases

`USE_CASE_CHAINS` (in `app/forge_llm_router.py`) held **17 use cases** on 2026-09-29 :
`speed`, `sentinel`, `inspect`, `collab`, `mesh`, `reasoning`, `debate`, `strategy`,
`context`, `synthesis`, `code`, `mermaid`, `eu`, `general`, `orchestration`, `tool_call`,
`agent_code`. Each maps to an ordered chain of slots — e.g. `code` starts with
`lmstudio_native`, `openrouter_qwen_coder`, `mistral_small` ; `reasoning` with
`nvidia_nemotron_super`, `openrouter_free`, `gemini_pro`. Read the dict itself for the
current chains : this page does not copy them any more.

Adjust per your priorities by editing `PROVIDER_SPECS` (the source of truth)
or `USE_CASE_CHAINS` (the route table).

## 📊 Quota tracking

`forge_provider_quota.py` records every call in `embeddings.db.token_usage` :

- `usage_this_month(provider) → {calls, tokens, cost_usd}`
- `quota_status(provider) → {pct_calls, pct_tokens, ok}`
- `should_skip(provider, threshold=0.8) → bool`

The web UI surfaces these. The cascade router respects `should_skip()`
automatically.

## 🔐 Why the vault and not `.env`?

`.env` is a flat file that gets committed by accident, copied across hosts,
or read by every process. The vault :

- Is OS-encrypted at rest (DPAPI / Keychain / libsecret).
- Has cache + invalidation API (`forge_secrets.invalidate_cache`).
- Is readable by the local accounts on Windows (machine-scope DPAPI) — needed by the
  `LaForgeSbxOnline` / `LaForgeSbxOffline` sandbox accounts — **except the reserved
  names** (master token, JWT secrets...), which only SYSTEM reads, from the reserved vault
  (vault hardening 2b, 2026-09-28).
- Has a CLI : `nokido-vault test|list|get|set|del`.
- Has a diagnostic : `nokido-secrets status`.

If you absolutely need an `.env` fallback (e.g. CI), the chain still works :
`get_secret()` reads the reserved vault (reserved names only) → machine vault → WCM →
`Nokido.env` → `os.environ`.

## 🧰 Adding a custom provider

1. Add a spec to `app/forge_provider_specs.py::PROVIDER_SPECS` :

   ```python
   "my_custom": {
       "tier": "paid_api",
       "cost_usd_per_1m_in": 5.0, "cost_usd_per_1m_out": 15.0,
       "context": 200000,
       "capabilities": ["chat", "code", "reasoning"],
       "notes": "Internal provider via Tailscale.",
   }
   ```

2. Implement the provider class under `app/forge_provider_<vendor>.py` with
   an `ask()` method matching the `Provider` interface (cf.
   `forge_agent_proxy.py`).

3. Register the vault key mapping in `app/forge_provider_admin.py::PROVIDER_VAULT_KEY` :

   ```python
   "my_custom": "MY_CUSTOM_API_KEY",
   ```

4. Restart the hub. The new provider appears in the web UI.

## 📡 Observe traffic

```bash
# Recent calls per agent -- `network_log` lives in the hub's main DB (forge_db_path.db_path())
sqlite3 <hub DB> \
  "SELECT agent, tool, COUNT(*) FROM network_log WHERE ts > datetime('now','-1 hour') GROUP BY agent, tool"

# Secrets state
nokido-secrets status
```

Quota state per provider : `/admin/providers`, or `forge_provider_quota.quota_status(<provider>)`.

The TUI's RAG pane (Ctrl+K) also shows recent calls.
