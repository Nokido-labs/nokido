# Nokido — Security & Sovereignty Stack

Full reference for Nokido's security layers: NoiseGuardian, TrustBroker, IntegrityRing, PromptGuard, semantic firewall, env encryption. Load when the user asks about data protection, cloud safety, prompt injection, or sovereignty guarantees.

## The sovereign design principle

Nokido is built around one axiom: **the user's real intent and the full aggregate of findings never leave the machine in clear**.

Every cloud call is an explicit degradation — some context inevitably leaves, but the architecture limits what and ensures the operator knows what's at stake.

```
┌────────────────────────────────────────────────┐
│                Internal world                   │
│        (Ryzen local, real data, creds)         │
├────────────────────────────────────────────────┤
│                                                 │
│   ┌──────────────┐        ┌───────────────┐   │
│   │ decompose    │        │ synthesize    │   │
│   │ (local only) │        │ (local only)  │   │
│   └──────────────┘        └───────────────┘   │
│            │                       ▲            │
│            ▼                       │            │
│        per-silo prompts        silo outputs    │
│            │                       │            │
│            ▼                       │            │
├────────────────────────────────────────────────┤
│           Sovereign Membrane (enforced)         │
│                                                 │
│    ├─ NoiseGuardian  (review)                  │
│    ├─ TrustBroker    (anonymize)               │
│    ├─ NoiseInject    (semantic noise if flag)  │
│    └─ PromptGuard    (injection check in)      │
├────────────────────────────────────────────────┤
│               External world                    │
│              (cloud LLMs, APIs)                 │
└────────────────────────────────────────────────┘
```

## Integrity Rings — the capability system

Source: `app/forge_integrity.py` (33 KB).

### Principle

Every action in Nokido requires a ring level. Tokens are HMAC-SHA256 signed by `MCP_DEV_SECRET`, carry a ring + scope + issued-at timestamp.

**Rule reminder**: lower ring = more rights.

| Ring | Value | TTL | Can... |
|---|---|---|---|
| `MASTER` | -1 | 300 s | Anything. Rotate secrets. Bypass any check. |
| `SYSTEM` | 0 | permanent | Hub restart, snapshots, vault rollback, ring revocations |
| `DEV` | 1 | permanent | Edit `app/`, `tools/`. Run arbitrary Python. Override guardians. |
| `TRUSTED` | 2 | permanent | Read RAG (all), write RAG with verification, use all tools |
| `COLLAB` | 3 | permanent | Multi-agent shared work. Can read own + COLLAB ring. |
| `UNTRUSTED` | 4 | permanent | Read-only of UNTRUSTED ring. Submit for review. |

### Usage

```python
from app.forge_integrity import IntegrityRing, is_at_least, require_ring, capability_required

# Imperative check
if is_at_least(token.ring, IntegrityRing.DEV):
    ...

# Decorator
@capability_required("code_edit")
def edit_file(path, content, token):
    ...
```

### Token format

Wire format (base64url):
```
<ring_int>.<scope>.<unix_ts>.<hex_hmac>
```

Example after decode:
```
1.code_edit.1745432100.9f3c2a1b7e4...
```

Validation:
1. Check HMAC matches (signed with `MCP_DEV_SECRET`)
2. Check TTL not expired (ring -1 only, default infinite for others)
3. Check scope matches the requested operation
4. Return ring or raise `PermissionError`

### Getting a token

Tokens are issued at Nokido boot based on `Nokido.env`:
- `FORGE_MCP_TOKEN` → ring TRUSTED by default
- `MCP_DEV_SECRET` → can mint any ring up to DEV (via `forge_integrity.issue_token()`)
- MASTER ring tokens only via interactive prompt on Nokido TUI, never from MCP

## NoiseGuardian — outbound review

Source: `app/forge_noise_guardian.py` (15.7 KB).

Reviews every snippet before cloud transmission. Returns `(allowed: bool, reasons: list[str], risk_score: float)`.

### What it flags

| Pattern | Example | Risk |
|---|---|---|
| IP addresses | `localhost`, `localhost` | Medium (reveals network) |
| MAC addresses | `aa:bb:cc:dd:ee:ff` | Low (unique to hardware) |
| CVE references | `CVE-2021-44228` | Low (public info) |
| Internal paths | `~\Script python IA\...` | **High** (reveals user identity) |
| Credentials | API keys, passwords, tokens | **Critical** (refuse or inject noise) |
| Email addresses | `...@company.com` | Medium |
| Company names | From `Nokido.env::COMPANY_NAME` | Medium |

### Default behavior

- **Low risk** → pass through with a warning in `audit_log`
- **Medium risk** → pass if `noise=False`, rewrite if `noise=True`
- **High risk** → refuse unless `noise=True` explicit
- **Critical risk** → always refuse, regardless of `noise` flag

### Manual invocation

```python
from app.forge_noise_guardian import NoiseGuardian

result = NoiseGuardian.review(
    "The server at localhost has CVE-2021-44228",
    domain="security",
)
# result.allowed = True
# result.risk_score = 0.3
# result.reasons = ["IP detected", "CVE detected (public OK)"]
# result.cleaned = "The server at <IP_0> has CVE-2021-44228"
```

## NoiseInject — semantic noise

Source: `app/forge_noise_inject.py` (7.4 KB).

When `noise=True` and NoiseGuardian permits, `forge_noise_inject` modifies the snippet before sending to cloud:

1. Replace specific IPs with `<IP_N>` tokens
2. Replace paths with `<PATH_N>` tokens
3. Rewrite sentences around sensitive content to reduce specificity
4. Maintain a mapping in-memory to reverse tokens in returned output

Original:
```
Scan localhost for CVE-2021-44228 in our Apache Log4j deployment.
```

After inject (what cloud sees):
```
Scan <IP_0> for CVE-2021-44228 in a reference Apache Log4j deployment.
```

Returned output has `<IP_0>` swapped back to `localhost` before being delivered to the user.

**Limitation**: if the cloud LLM rephrases too much, the token may not round-trip. The mapping is best-effort. Use sparingly.

## TrustBroker — PI anonymization

Source: `tools/forge_trust_broker.py` (13.6 KB).

Two classes:
- `SecretAnonymizer` — pattern-based PI scrubbing (stricter than NoiseGuardian)
- `OrchestratorTrustBroker` — aggregates anonymized snippets, maintains trust scores per cloud provider

### When TrustBroker fires

- Right after NoiseGuardian (belt-and-suspenders)
- Before every outbound POST from `forge_llm_router`
- On every `write_file` to a cloud-accessible location

### Trust scoring

Each provider has a trust score 0.0-1.0 in `forge_hot_load_manager`:
- `github_gpt41_mini` → 0.8 (Microsoft, generally compliant)
- `gemini_flash` → 0.7 (Google, data-retention-opt-out honored)
- `openrouter_*` → 0.5 (proxied, unknown backend)
- `hf_*` → 0.6 (public router, known routing)
- `deepseek_*` → 0.3 (unclear data retention — use sparingly)

Trust score affects:
- NoiseGuardian threshold (lower trust = stricter review)
- NoiseInject intensity (lower trust = more aggressive rewriting)
- Retry policy on errors

## PromptGuard — inbound injection defense

Source: `app/forge_prompt_guard.py` (19.1 KB).

Scans inbound LLM responses (and user inputs from untrusted sources like RAG chunks with `ring=UNTRUSTED`) for prompt injection attempts.

### Classes

- `InjectionResult` — output of the check: `(is_injection, confidence, patterns_matched, severity)`
- `ConflictReport` — when user intent contradicts system instructions

### Patterns detected

- **Instruction takeover**: "ignore previous instructions", "disregard the above", "new task:"
- **Role inversion**: "you are now a different AI", "pretend to be"
- **System prompt extraction**: "what are your instructions", "print your system prompt"
- **Context manipulation**: hidden Unicode direction characters, zero-width spaces
- **Indirect injection via code blocks**: instructions placed in code comments or string literals

### Integration

PromptGuard runs:
1. On every message entering a silo (before `route_llm`)
2. On every response returning from cloud (`forge_llm_router::_handle_response`)
3. On every RAG chunk retrieved with `ring=UNTRUSTED`

If injection detected → the message is quarantined, flagged, operator alerted via `notify` with marker 🛂 `NEED_ADMIN`.

## Semantic Firewall (4 layers)

Source: `app/forge_semantic_firewall.py`.

Four successive checks on outgoing text:

```
Layer 1: Syntactic scan
   - regex patterns for obvious leaks
   - known credential formats (AWS keys, GitHub PATs, Stripe keys)

Layer 2: Semantic scan
   - embeddings similarity to known-dangerous patterns
   - context classifier: is this leaking mission info?

Layer 3: Behavioral scan
   - was this output uncommonly long? asymmetric with input?
   - does it echo back large chunks of input verbatim?

Layer 4: Deception scan
   - does the output claim to be "just a test" or "educational"?
   - does it frame a dangerous action as harmless?
```

Only outputs passing all 4 layers proceed. Otherwise → quarantine + alert.

## Env encryption (forge_env_crypt.py)

Source: `app/forge_env_crypt.py` (20.1 KB).

Encrypts `Nokido.env` at rest. Default when `LAFORGE_ENV_ENCRYPTED=true`:

- Master key derived from machine-bound secret (DPAPI on Windows, Keychain on macOS, libsecret on Linux)
- AES-256-GCM with per-section nonces
- Plaintext never touches disk after initial setup
- Decryption happens in-process, never stored

Enable:
```cmd
python -m tools.nokido_modules env_crypt init --password <master_password>
```

## Trauma Vault

Source: `app/forge_trauma_vault.py`.

**Memory of failures** with plasticity model. Not security-per-se, but protective:

- When a silo fails, the trauma is recorded with context
- STDP (Spike-Timing-Dependent Plasticity) — recent + frequent failures reinforce the aversion
- Winding number protection — topological guard preventing recursive patterns
- When a similar task is proposed, Nokido surfaces the trauma: "last time this pattern failed, reason: ..."

Reduces repeated failures. Unique to the Engrid v3 design.

## MCP-level security (forge_mcp_security.py)

Source: `app/forge_mcp_security.py` (11.7 KB).

Enforces MCP transport-level protections:

- **Path sandbox**: `write` cannot escape `LaForge/` workspace
- **Audit log**: every MCP call logged with ring, scope, agent, timing
- **Rate limit**: `MCP_RATE_LIMIT` req/min per agent (default 60)
- **Payload size**: `MCP_MAX_PAYLOAD_KB` limit (default 512)
- **CORS**: only `MCP_ALLOWED_ORIGINS` accepted

Check via:
```python
run(action="audit_log")
# Shows recent MCP calls with security metadata
```

## Conversation sanitization

Source: `app/forge_conv_sanitizer.py` (22.7 KB) + `app/forge_sanitizer_analyst.py`.

For long multi-turn conversations, the sanitizer:
- Removes duplicate content
- Collapses redundant chunks
- Extracts "residual" data (paths, IDs, patterns) to a structured side-store
- Keeps only the semantic gist in the token-priced context

Allows longer conversations without token explosion.

## Sovereign membrane (the top-level enforcer)

Source: `app/forge_sovereign_membrane.py`.

The membrane is the **single point** where all the above security layers converge. Any bidirectional flow between internal and external world passes through it:

```python
from app.forge_sovereign_membrane import SovereignMembrane

# Outbound
clean_snippet, metadata = SovereignMembrane.outbound_scrub(
    snippet=original,
    target_provider="github_gpt41_mini",
    noise=True,
    domain="security",
)

# Inbound
validated_response, tag = SovereignMembrane.inbound_validate(
    raw_response=cloud_reply,
    source_provider="github_gpt41_mini",
    expected_ring=IntegrityRing.UNTRUSTED,
)
```

Every cloud call in `forge_llm_router` wraps this. Direct cloud access bypassing the membrane is prohibited (`MCP_STRICT_MODE=true` enforces this at MCP level).

## Auth for external actors (Bearer + X-Agent-Name)

### For clients connecting to Nokido MCP

| Header | Example | Meaning |
|---|---|---|
| `Authorization` | `Bearer 3f4a2b1c...` | 64-hex token from `Nokido.env::FORGE_MCP_TOKEN` |
| `X-Agent-Name` | `CLAUDE` | Identifies the agent; colors logs; routes notifications |
| `Content-Type` | `application/json` | Required |
| `Accept` | `application/json, text/event-stream` | For streamable HTTP |

### For Nokido calling external APIs

Each cloud provider has its own env var:
- `GITHUB_MODELS_TOKEN` (GitHub Models)
- `GEMINI_API_KEY` (Google Gemini)
- `GROQ_API_KEY` (Groq)
- `DEEPSEEK_API_KEY` (DeepSeek)
- `MISTRAL_API_KEY` (Mistral)
- `XAI_API_KEY` (xAI Grok)
- `HF_TOKEN` (HuggingFace Router)
- `OPENROUTER_API_KEY` (OpenRouter)

Rotated via `Nokido.env` edit + hub restart. Never transmitted to other providers.

## Environment flags

| Variable | Default | Effect |
|---|---|---|
| `LAFORGE_SILO_USE_CASCADE` | `1` | If 0, silos stay local (Ollama only) |
| `LAFORGE_NOISE_DEFAULT` | `false` | Default value of `noise` flag in `trigger_autonomous_evolution` |
| `LAFORGE_ENV_ENCRYPTED` | `false` | Enable encrypted Nokido.env |
| `LAFORGE_AUDIT_VERBOSE` | `false` | More detailed audit log |
| `LAFORGE_TRUST_FLOOR` | `0.3` | Minimum trust score to use a cloud provider |
| `LAFORGE_SENTINEL_STRICT` | `false` | If true, sentinel refuses on any suspicion |
| `MCP_STRICT_MODE` | `false` | If true, dangerous MCP tools disabled |
| `MCP_RATE_LIMIT` | `60` | Req/min per agent |
| `MCP_MAX_PAYLOAD_KB` | `512` | Max POST body |
| `MCP_ALLOWED_ORIGINS` | `localhost,127.0.0.1` | CORS whitelist |
| `MCP_HTTP_HOST` | `127.0.0.1` | **Bind local only, never LAN** |

## Safety invariants (hard rules)

1. **`decompose` and `synthesize` never go cloud** — enforced in `forge_silo_engine._route_llm()` via `_local_only=True` flag.
2. **`KnowledgeGuardian` filters RAG per domain** before feeding a silo — a security silo never sees unrelated chunks.
3. **Sovereign membrane wraps every cloud call** — bypassing it requires ring=MASTER.
4. **`MCP_HTTP_HOST=127.0.0.1`** — never expose to LAN.
5. **`MASTER` ring TTL 300s** — can't be held persistently.
6. **RAG promotion monotonic** — `DRAFT → VERIFIED → GOLD`, never backwards except via ring 0/1 explicit revocation.

## Diagnostic commands

```python
# Audit log — last 100 security decisions
run(action="audit_log")

# Current ring / agent state
get_mode()

# Check NoiseGuardian on a sample
run(action="python", code="""
from app.forge_noise_guardian import NoiseGuardian
print(NoiseGuardian.review("test localhost with API key sk-abc123", domain="code").__dict__)
""")

# Check brain_worker sidecar integrity
run(action="python", code="""
import zmq
ctx = zmq.Context()
s = ctx.socket(zmq.REQ)
s.RCVTIMEO = 2000
s.connect('tcp://127.0.0.1:5557')
s.send_json({'cmd': 'status'})
print(s.recv_json())
""")
```

## What NOT to do

- **Don't disable NoiseGuardian** even for "internal only" tests. It's the last line of defense.
- **Don't set `noise=True` by default** everywhere — it adds latency, round-trip mapping issues, and obscures real reasoning.
- **Don't commit tokens or secrets** to Git. `Nokido.env` is gitignored; check before pushing.
- **Don't issue MASTER ring tokens programmatically** — only interactive TUI can mint them.
- **Don't bypass PromptGuard** — RAG chunks tagged `UNTRUSTED` are there for a reason.
- **Don't expose :8766 to LAN or the internet**. It's designed for 127.0.0.1 only.
- **Don't use DeepSeek for sensitive strategic reasoning** — trust score is 0.3 for a reason.
