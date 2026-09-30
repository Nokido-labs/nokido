---
type: guide
title: 08 — Vault & secrets
status: draft
resource: repo://docs/wiki/08-Vault-and-Secrets.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 08 — Vault & secrets

<!-- revu-le: 2026-08-27 -->
> Updated: 2026-08-27

Nokido stores secrets in an OS-encrypted vault — **never** in `.env`
committed to git. This page covers the vault architecture, the CLI, and
the migration path from legacy `.env`-only setups.

## 🔐 Why not `.env`?

A `.env` file is :

- Easily committed by accident (one `git add .` and your tokens are public).
- Plaintext on disk, readable by any local process.
- Per-clone, per-host : you have to re-deploy on every machine.
- Not encrypted — backups, snapshots, and `Get-Childitem env:` expose it.

Nokido moved 33+ secrets out of `.env` into a machine-wide encrypted
vault in May 2026. The remaining `.env` only holds **config** (URLs,
ports, flags) — never secrets.

## 🗄️ Backends by OS

| OS | Backend | Module | Scope |
|---|---|---|---|
| Windows | DPAPI `CRYPTPROTECT_LOCAL_MACHINE` | `ctypes.windll.crypt32` (no pywin32 needed) | Machine-wide — readable by all local accounts (sandbox users included). |
| macOS | Keychain | `keyring` (Python) | Per-user. |
| Linux | libsecret / Secret Service | `keyring` (Python) | Per-user, requires `libsecret` package + a running keyring daemon (GNOME Keyring, KWallet, etc.). |

The backend is auto-detected at runtime via `sys.platform`. Module :
`app/forge_machine_vault.py::available()`.

### Why machine-wide on Windows ?

Nokido has multiple **non-user service accounts** :
`LaForgeSbxOnline`, `LaForgeSbxOffline`, `LaForgeTrustedRunners`,
`LaForge-Master` (SYSTEM). The DPAPI **user-scope** (default
`CRYPTPROTECT_LOCAL_MACHINE = 0`) would make each account's secrets
invisible to the others — running `brain_worker` under
`LaForgeSbxOffline` couldn't read the tokens written by user.

Machine-scope DPAPI (flag `0x04`) solves this : encryption with the
machine key, decryption by any local account. The vault file
(`data/machine_vault.dat`) can be world-readable on disk — the content
is still encrypted.

## 🔄 The chain of priority

`app/forge_secrets.py::get_secret()` walks the chain :

```
1. In-memory cache (per-session)
   ↓ miss
2. Machine vault (DPAPI / Keychain / libsecret)
   ↓ miss
3. WCM (Windows Credential Manager, per-user) — legacy
   ↓ miss
4. Nokido.env — last resort, with warning logged
   ↓ miss
5. os.environ — last-last resort, with warning logged
   ↓ miss
6. return None (or raise ValueError if required=True)
```

The cache (`_cache` / `_cache_miss`) avoids re-reading WCM on every call.

## 📋 CLI

### `nokido-secrets` — diagnostic & migrate

```bash
# Show which secrets are where
nokido-secrets status
# Output:
# Keyring: OK
# Coffre machine (12): ['FORGE_TOKEN_CLAUDE', 'FORGE_TOKEN_GEMINI', ...]
# Dans WCM (3): ['LEGACY_KEY_1', ...]
# Dans .env seulement (1): ['SEARXNG_HOST']
# Manquants (2): ['ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY']

# Set a secret (prompts for value)
nokido-secrets set --key GROQ_API_KEY

# Get (preview only — last 4 chars)
nokido-secrets get --key GROQ_API_KEY
# GROQ_API_KEY = ***xx1z
```

### `nokido-vault` — direct vault CRUD

```bash
# Roundtrip self-test
nokido-vault test

# List keys (never values)
nokido-vault list

# Set / get / delete
nokido-vault set -k CLE
nokido-vault get -k CLE
nokido-vault del -k CLE
```

### Python API

```python
from forge_secrets import get_secret, set_secret, require

# Single key
token = get_secret("FORGE_MCP_TOKEN", required=True)  # raises if absent

# Bulk
creds = require("GROQ_API_KEY", "GEMINI_API_KEY")
# creds = {"GROQ_API_KEY": "...", "GEMINI_API_KEY": "..."}

# Set
set_secret("MY_KEY", "secret-value")

# Invalidate cache after rotation
from forge_secrets import invalidate_cache
invalidate_cache("MY_KEY")
```

## 🧪 Bootstrap a fresh install

After `bash install.sh` :

```bash
# 1. The hub generates a master token automatically in Nokido.env.
#    Migrate it into vault :
nokido-secrets set -k FORGE_MCP_TOKEN
# (paste the token printed in Nokido.env)

# 2. Generate per-agent tokens (or migrate from existing legacy hub tokens) :
python tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env

# 3. Verify
python tools/forge_vault_seed_agent_tokens.py --verify
# Expected: 14/14 OK

# 4. Add provider API keys via the web UI :
#    http://127.0.0.1:8766/admin/providers
```

## 🔁 Rotation

To rotate a token :

```bash
# 1. Generate a new value
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Overwrite in vault
nokido-vault set -k FORGE_TOKEN_CLAUDE
# (paste new value)

# 3. Restart the hub so the new token is loaded
nssm restart LaForge-Master   # Windows
# OR: kill the running laforge-hub, restart

# 4. Update the client config (Claude Desktop config / Codex config.toml / etc.)
```

The cache is invalidated automatically when `set_secret` is called from
the same process. Cross-process invalidation = restart.

## 🚨 Recovery — vault corrupted or lost

If `data/machine_vault.dat` is corrupted or deleted. Since the vault hardening of
2026-09-28 (2b), the **reserved names** (`FORGE_MCP_TOKEN`, JWT secrets...) are written
only under SYSTEM (owner's dev mode, `ps_clm`) : run the seeder there for them, or its
refusal will say so.

```bash
# Wipe + rebuild
rm data/machine_vault.dat

# Re-seed from a backup .env (if you kept one)
python tools/forge_vault_seed_agent_tokens.py --from-env-file /path/to/backup.env

# Or regenerate hub tokens fresh
python tools/forge_vault_seed_agent_tokens.py --from-stdin <<EOF
FORGE_MCP_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
FORGE_TOKEN_CLAUDE=$(python -c "import secrets; print(secrets.token_hex(32))")
FORGE_TOKEN_GEMINI=$(python -c "import secrets; print(secrets.token_hex(32))")
# ...
EOF
```

After rebuild, update every client config that references the old
bearers (`tools/forge_mcp_json_sync.py`, see [04 — MCP clients setup](04-MCP-Clients-Setup.md)).

## 💽 Encryption at rest — volume `V:`

The large databases (`%NOKIDO_DATA%\embeddings.db`) live in a VeraCrypt container mounted at
boot by the SYSTEM task `LaForge-VC-Boot` (`tools/nokido_start.ps1` triggers it and
waits for `%NOKIDO_DATA%\embeddings.db`, up to 90 s, then fails loudly). The keyfile is held by
**SYSTEM only** (reserved vault) : no owner copy, no GUI step.

`tools/forge_at_rest_veracrypt.py` :

| Command | Effect |
|---|---|
| `--status` | state of the volume |
| `--verifier-cle` | proves the key opens the volume header **without VeraCrypt** (PBKDF2 + AES-XTS, `VERA` magic) : `OUVRE` / `NON` / `ILLISIBLE` — never unmounts to find out |
| `--rekey` | dry-run of a header re-key ; `--appliquer` writes : both header groups backed up and read back, new key stored and read back **before** any write, header re-read after, automatic restore on failure |
| `--rekey-restaurer` / `--rekey-clore` | restore the saved headers / close the re-key window |

A re-key changes the **header key**, not the volume master key : revoking an exposed
master key needs a new container and a copy.

## 🛡️ Security properties

- **At-rest encryption** : DPAPI uses AES-CBC with the machine key. Keychain
  uses AES-256-GCM. libsecret depends on the underlying agent
  (GNOME-Keyring : AES-GCM).
- **Process isolation** : decryption requires the LocalMachine key (Win) or
  user-session unlock (macOS/Linux). A network attacker who pulls the file
  cannot decrypt without local access.
- **No persistence in logs** : `forge_secrets` never logs secret *values*,
  only key *names* and `***xxxx`-style previews.
- **Pre-commit guard** : `bash_guard` blocks `cat .env`, `printenv`, etc.
  unconditionally. Gitleaks pre-commit hook scans staged diffs.

## 🪪 Reuse — the redaction vault (reversible log DLP)

The same DPAPI primitive (`forge_machine_vault._protect` / `_unprotect`) backs a
**second, distinct vault** for the log-DLP layer ([Security model §9](07-Security-Model.md)) —
not a secrets store, a privacy trade-off.

When a log sink scrubs PII *reversibly*, the original value is stored
DPAPI-encrypted in `sandbox/redaction_vault.db`, keyed by its deterministic HMAC
tag (`[EMAIL:7f3a]`). An authorized local debugger restores the cleartext via
`forge_semantic_firewall.deanonymize_log(text)` — but only for **7 days** :
`forge_log_retention` prunes entries past the window, after which the logs are
**irreversible at rest** (the tag remains, the value is gone). Off-machine leak =
useless (DPAPI machine key absent). Default for logs is irreversible ;
reversibility is opt-in per sink (`net_log`).

## ❓ FAQ

**Q. Can I sync the vault across machines?**
No — DPAPI machine-scope ties the keys to *this* machine's hardware-derived
key. For cross-machine deployment, use a 1Password / Vault / Bitwarden CLI
adapter (not bundled, but trivial to add as a backend).

**Q. What about Docker containers?**
The container's vault is per-container (volume-mounted `vault_data`). On
container start, you can mount a `Nokido.env` and run
`forge_vault_seed_agent_tokens.py` once. After that, the volume persists.

**Q. How do I see what's in the vault without leaking?**
`nokido-vault list` shows key *names*. `nokido-secrets get -k KEY`
shows `***xxxx` (last 4 chars only). Full values never echoed.

**Q. Does the hub need ring 0 to read vault keys?**
No — the vault is read in-process by `forge_secrets`. The ring check is
on the *MCP tool dispatch* (e.g. `query` is ring 0). Vault access is
gated by OS process identity, not by MCP rings.
