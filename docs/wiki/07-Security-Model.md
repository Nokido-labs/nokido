---
type: guide
title: 07 — Security model
status: draft
resource: repo://docs/wiki/07-Security-Model.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 07 — Security model

<!-- revu-le: 2026-09-29 -->
> Updated: 2026-09-29

Nokido operates on a **Zero-Trust local architecture**. This page summarizes
the threat model and defensive layers. The canonical disclosure policy is in
[SECURITY.md](../../SECURITY.md).

## 🎯 Threat model

Nokido defends against :

1. **Cloud provider data exfiltration** — when you `ask("groq", ...)`, the
   prompt may contain hostnames, tokens, paths, IPs. The
   `SovereignMembrane` replaces them with HMAC aliases before any cloud call.
2. **Prompt injection attacking the LLM** — `SemanticFirewall.pre_flight()`
   detects 15+ patterns (EN + FR) including jailbreak attempts, role
   injection, instruction override.
3. **SSRF / beacon leak in LLM output** — `post_flight()` scans for
   suspicious URLs, ICP token leaks, callback patterns.
4. **Local secret leak via shell tools** — `tools/bash_guard.py` blocks
   `git remote -v`, `cat .env`, `printenv`, `gci env:`, etc. unconditionally.
5. **Untrusted skills auto-install** — `SkillGuardian` reviews any new skill
   before it can be installed by `forge_clawhub_autoinstall`.
6. **Hub auth bypass** — every MCP request validates `Authorization` against
   the vault-loaded `_AGENT_TOKENS`. Fail-closed.
7. **Indirect prompt injection via web content** — a crawled/ingested page can
   hide instructions ("ignore previous…"). The web pipeline
   (`forge_crawl_tool.firewall_web` + the `:7779` egress gateway) scans fetched
   content with `detect_injection`, wraps it as untrusted data, and downweights
   it in the RAG. SSRF-guarded against internal / cloud-metadata targets.
8. **PII / secrets leaking via local logs at rest** — every log/trace sink
   scrubs sensitive data *before write* (`redact_for_log`, deterministic HMAC
   tags). A leaked `mcp_audit.log` / `execution_traces.db` / RAG dump reveals no
   cleartext. Reversible for authorized debug <7 days via a DPAPI vault.

Nokido does **not** defend against :

- A compromised local user account (we assume the local filesystem and
  process tree are trusted).
- A physical attacker with hardware access.
- Vulnerabilities in upstream LLM providers (Anthropic, OpenAI, Google…).

## 🛡️ The 11 defensive layers

### 1. Semantic Firewall

`app/forge_semantic_firewall.py`

```python
fw = get_firewall()
pf = fw.pre_flight(prompt, context=system_prompt, ring=2, provider="auto")
if not pf.ok: raise VetoSecurity(pf.reason)
# safe_task + safe_context have PII replaced
response = await llm_call(pf.safe_task, pf.safe_context)
pfr = fw.post_flight(response, task=prompt, session_id=session_id)
if not pfr.ok: return handle_drift(response, pfr.reason)
clean = fw.restore(response, pf.mapping)
return clean
```

Two checks per call : *before* (anonymize) and *after* (sniff for drift).

### 2. Sovereign Membrane

`app/forge_sovereign_membrane.py`

HMAC alias-based anonymization with **persistent aliasing per mission** :

```python
membrane = SovereignMembrane(mission_id="recon_20260424")
wrapped = membrane.wrap(raw_data)
# wrapped.content has hostnames -> [host:xxx], paths -> [path:yyy], etc.
response = await cloud_call(wrapped.content)
clean = membrane.unwrap(response, tool_calls=response.get("tool_calls"))
```

Aliases survive in `membrane.db` (SQLite WAL) so the same hostname maps to
the same alias across requests.

### 3. 6-ring RBAC

`app/forge_integrity.py::IntegrityRing`

Lower ring = more rights. Values of the `IntegrityRing` enum (compare with
`is_at_least()`, never `==`) :

| Ring | Name | Meaning |
|---|---|---|
| -1 | MASTER | Absolute supervisor, destructive actions ; time-locked (5 min), never handed to external agents |
| 0 | SYSTEM | Nokido core, DB migrations |
| 1 | DEV | Maintenance agents via MCP (token required) |
| 2 | TRUSTED | Workflows (TUI `@audit`, `@ci`, `@workflow`) |
| 3 | COLLAB | LLM committee, external agents |
| 4 | UNTRUSTED | Raw inputs, agents without a token |

Enforced at hub middleware (`_resolve_ring()` in `nokido_hub.py`) : the identity × ring
of each caller comes from ONE source, `forge_videur` (agent registry), or from a
short-lived `CapabilityToken` ; an unknown identity falls to an isolated ring, never 0.
Every tool has a `min_ring` ; the registry filters per-agent (see the table in
[04 — Auth model](04-MCP-Clients-Setup.md#-auth-model)).

### 4. Vault — DPAPI / Keychain / libsecret

`app/forge_machine_vault.py` + `app/forge_secrets.py`

Encrypted-at-rest, machine-wide on Windows (multi-user sandbox accounts
share access), per-user on macOS/Linux. Never `.env` committed. Since the vault
hardening of 2026-09-28 (2b), the **reserved names** (master token, JWT secrets...)
live in a SYSTEM-only reserved vault and are closed to every other account.

Chain : `get_secret()` → reserved vault (reserved names) → machine vault → WCM →
`Nokido.env` → `os.environ` (last resort with warning).

See [08 — Vault & secrets](08-Vault-and-Secrets.md).

### 5. Pre-commit secret scan

Two layers :

- **Gitleaks** via `.gitleaks.toml` — regex over default rules + Nokido
  allowlist (sample.env, templates, docs).
- **Nokido AST guard** (`forge_secret_guard`) — runs in the pre-commit
  hook installed by `install.sh` / `install.ps1`.

Both fail-closed : a suspected leak blocks the commit.

### 6. Bash guard hook

`tools/bash_guard.py`

PreToolUse hook for Bash/PowerShell. Two layers :

- **Layer 1 (unconditional)** — denylist of secret-leaking patterns
  (`git remote -v`, `cat .env`, `printenv`, `gci env:`, URLs with `userinfo`,
  echo of `*TOKEN` / `*SECRET` / `*KEY`).
- **Layer 2 (routing)** — every command segment must be a passthrough
  (curl `:8766`, `nssm restart Nokido*`, `git`, `gh`, `schtasks Nokido-*`).
  Otherwise blocked.

Dev mode (`sandbox/.bash_guard_armed`, TTL 30 min) bypasses layer 2 only —
secrets layer always applies.

**The other client-side guards.** `bash_guard` is one of many hooks (43 wirings checked
at session start on 2026-09-29) ; the main ones are below. They matter
because agent CLIs are often run with permission prompts disabled: the hooks are
then the *only* net, and a hook whose script is missing fails **silently**.

| Hook | Event | Role |
|---|---|---|
| `forge_tool_gate.py` | PreToolUse | routes reads/searches to the governed hub instead of raw native tools |
| `hook_search_guard.py` | PreToolUse | denies unbounded reads (>14 kB without `limit`, `head_limit:0`) |
| `hook_recon_first.py` | PreToolUse | forces a memory lookup before instrumenting a domain — once per domain per day |
| `hook_pretool_guard.py` | PreToolUse | anti-regression: asks for confirmation when an edit reintroduces an anchored bug |
| `hook_posttool_validate.py` | PostToolUse | validates the AST of every edited `.py`, at zero token cost |
| `hook_integrity_check.py` | SessionStart | **verifies the net itself**: each wired hook must exist and compile, three states (ok / dead / unreadable) |
| `hook_bash_compact.py` | PreToolUse | pipes verbose command output through a compactor before it enters context |
| `hook_capability_gate.py` | PreToolUse | recalls the form that WORKS for a capability (measured traps), before the wrong form is paid again |

`hook_integrity_check.py` exists because of a specific failure mode: a deleted or
broken hook is ignored without a word, so the protection disappears while the
configuration still *reads* as protected.

### 6.b Commit gate — `tools/forge_git_gate.py`

Runs on every commit. Blocks on **positive proof** only, never on an inability to
look — "I could not check" is reported, never silently treated as "clean".

- **`.py`** — AST parse of staged files. A broken `.py` fail-closes the hub.
- **`.ts`** — `deno lint` (parse) **and** `deno check` (types) on `proxy_deno/`.
  Both matter: a file that parses but has a type error still kills the
  supervisor, and every service it runs with it. Type-checking was added on
  2026-07-30 after `deno check` surfaced 18 errors the linter reported as clean.
- **secrets** — pre-commit scan (see layer 5) plus an entropy check.
- **muted error paths** — flags `except: pass` blocks that swallow a failure
  without a trace.

Note: `deno` must be readable by the account that commits. When it only exists
in the owner profile, service accounts cannot see it and the `.ts` gate skips —
announced, never a false green. A machine-wide copy closes that gap.

### 7. Execution under dedicated accounts

Code execution via `run` (`shell`, `python`, `run_job`) runs under dedicated
low-privilege Windows accounts, not the owner's :

- **`LaForgeSbxOffline`** — default ; outbound network blocked by firewall.
- **`LaForgeSbxOnline`** — only when network is asked (`network=true`, `online=true` jobs).
- **`LaForgeTrusted`** — `trusted_script`, which only runs a **committed** script
  (the executed code is exactly the reviewed code).
- **SYSTEM (`ps_clm`)** — only while the owner has armed the dev mode (TTL), in
  PowerShell constrained language.

Docker stays available as an on-demand prosthesis (`docker_action`, woken by
`docker.wanted`, switched off when nobody asks) — it is not the default sandbox.

### 8. Local-first by default

The hub binds `127.0.0.1`. Cloud egress is opt-in *per provider* (vault
key must be present + provider explicitly chosen). No telemetry. No
remote attestation. No "phone home" pings. The only public entry point, when the owner
opens it, is the separate cloud-peer connector (layer 11) — never the hub's `/mcp`.

For multi-host Nokido deployments, **wrap with Tailscale or WireGuard**.
Do not bind `0.0.0.0` directly.

### 9. Log DLP at rest

`app/forge_semantic_firewall.py::redact_for_log` + 5 sinks

The Semantic Firewall covered cloud *egress* only — local logs persisted raw.
Now every log/trace sink (`net_log`, `record_trace`, `anchor_error/solution`,
`critical_events.persist`) scrubs PII/secrets **before write** :

- Deterministic HMAC tags (`john@acme.com` → `[EMAIL:7f3a]`) — same value →
  same tag, so debug correlation survives, but the value is never stored. A
  leaked `mcp_audit.log` / `execution_traces.db` / RAG reveals no cleartext.
- Covers EMAIL / SECRET / SSH key + credit-card (Luhn) / IBAN / SSN / phone /
  title-anchored names — pure regex, no heavy ML model.
- **Reversible opt-in** : `net_log` stores the value encrypted in a DPAPI vault
  (`deanonymize_log()` <7 days for authorized local debug), pruned by
  `forge_log_retention` thereafter → irreversible at rest.

### 10. Web egress firewall

`app/forge_crawl_tool.py` + `tools/forge_web_egress.py` (`:7779`)

Web content is the classic indirect-injection vector. Three levels :

- **Cooperative** — the MCP `crawl` tool cleans (trafilatura → markdown), scans
  injection, and indexes oversized pages locally on the NPU instead of dumping
  them (token-frugal).
- **Gateway** — `:7779/fetch` exposes the same pipeline to non-MCP host CLIs
  (aichat / llm / curl), with an **SSRF guard** (blocks RFC1918 / loopback /
  cloud metadata).
- **Hard** — sandboxed agents have outbound sockets blocked, so they reach the
  web only through the firewalled hub.

See [Web Egress Gateway](Web-Egress.md).

### 11. Cloud peers — owner quarantine

`tools/forge_pair_mcp.py` + `tools/forge_pair_quarantaine.py` (`:8793`, HTTPS tunnel)

claude.ai / ChatGPT are **peers**, not operators : fixed read-only view, and every
deposit (fact, message, task) waits in quarantine. Approval and replies require the
owner account **with an elevated token** (UAC) — SYSTEM, hub accounts and the
non-elevated console where agents run are refused. Peers may only carry a whitelist
of intents (never `OK_DONE`, `LOCK_*`, `AUTHZ_*`…). See [24 — Cloud peers](24-Cloud-Peers.md).

## 🔐 Reporting a vulnerability

Private disclosure first :

*Security* tab → *Report a vulnerability* (GitHub private vulnerability reporting).

See [SECURITY.md](../../SECURITY.md) for the full policy. We aim for
72-hour acknowledgement and 7-day initial assessment.

## ⚠️ Known limitations

- Alpha software — APIs change between commits. Pin to a tag for stability.
- Pre-public branches may contain test credentials. Always rotate hub
  bearers before deploying anywhere visible.
- `SemanticFirewall` reduces but does not eliminate prompt injection risk.
- Ring 0 grants RCE. Never expose master-token over the network without
  TLS + mTLS.
- The `query` tool is raw SQL, ring 0 only. Other rings must use `rag`.
- The cloud-peer server runs as `LaForgeSbxOffline`, which can read the non-reserved
  secrets of the machine vault (vault hardening step 2b in progress).

## ✅ Hardening checklist (post-install)

- [ ] Rotated hub bearers from defaults : `nokido-vault list`.
- [ ] `.gitleaks.toml` runs in pre-commit hook : check `.githooks/`.
- [ ] No tokens in `Nokido.env` (they should be in vault).
- [ ] Docker compose binds `127.0.0.1:8766` not `0.0.0.0:8766` (verify `ports:`).
- [ ] Sandbox accounts created (Windows) : `LaForgeSbxOnline`, `LaForgeSbxOffline`.
- [ ] Hub healthcheck enabled (cf. compose) — auto-restart on hang.
- [ ] CI gitleaks workflow passing : `.github/workflows/gitleaks.yml`.
