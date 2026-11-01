# Security Policy

## Reporting a Vulnerability

Nokido takes security seriously. If you discover a vulnerability, please follow
**private disclosure** before opening a public issue.

**Primary channel :** GitHub **private vulnerability reporting** — open the
repository's *Security* tab and click *Report a vulnerability*. The report is
visible only to you and the maintainer (@user) until a fix is published.

No e-mail address is published for this project: the private advisory is the
single, traceable channel, and it keeps the whole exchange (report, fix,
credit) in one place.

Include in your report :

- A clear description of the issue and its impact.
- Reproduction steps or a minimal proof-of-concept.
- The Nokido version / commit SHA you tested.
- Your name / pseudonym for acknowledgement (or "anonymous").

We aim to:

- Acknowledge receipt within **72 hours**.
- Provide an initial assessment within **7 days**.
- Coordinate a fix and disclosure timeline with you.

**Please do not** open public GitHub issues, Discussions, or social media posts
for security-sensitive matters until a patch is available.

---

## Supported Versions

Nokido is on the `alpha` branch and pre-1.0. Public-facing supported lines :

| Branch  | Status          | Security patches |
|---------|-----------------|------------------|
| `main`  | Stable release  | ✅ Active         |
| `beta`  | Pre-release     | ✅ Active         |
| `alpha` | Development     | ✅ Best-effort    |
| Other   | —               | ❌ Unsupported    |

---

## Threat model — what Nokido defends against

Nokido ships a **Zero-Trust local architecture** with multiple layers :

1. **Semantic Firewall** (`forge_semantic_firewall.py`) — pre-flight DLP +
   injection detection + ring check + canary ; post-flight SSRF beacon +
   social engineering + canary leak + hallucination + language drift.
2. **Sovereign Membrane** (`forge_sovereign_membrane.py`) — HMAC-aliased
   anonymization of hostnames, paths, IPs, tokens, UUIDs before any
   cloud egress.
3. **6-ring RBAC** (`forge_integrity.py`) — MASTER · SYSTEM · DEV ·
   TRUSTED · COLLAB · UNTRUSTED with capability tokens HMAC.
4. **DPAPI machine-wide vault** (Windows) / **Keychain / libsecret**
   (macOS / Linux) via `forge_machine_vault.py`. Never in `.env`, never
   in tracked code.
5. **Pre-commit secret scan** — Gitleaks (`.gitleaks.toml`) + Nokido AST
   `forge_secret_guard`. Any agent commit fails closed on suspected leak.
6. **Bash guard hook** (`tools/bash_guard.py`) — blocks dangerous shell
   patterns (`git remote -v` with embedded PAT, dump env, read of
   `.env`/`.git/config`, etc.).
7. **Ephemeral sandboxing** — code execution in stateless, network-isolated
   Docker containers (MCP Docker bridge). Sandbox accounts
   `LaForgeSbxOnline` / `LaForgeSbxOffline` (non-admin) for `run` /
   `orchestrate` outside SYSTEM.
8. **Local-first by default** — hub binds `127.0.0.1`. Cloud egress is
   opt-in per provider. No telemetry.

---

## Commit signing

All commits authored by the maintainer are **SSH-signed** (ed25519,
`gpg.format = ssh`). Verify any commit locally :

```
git log -5 --format="%G? %h %s"     # G = good signature
git log --show-signature -1
```

Verification requires the signer's public key in an allowed-signers file :

```
git config --global gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers
```

> **Not enforced server-side.** GitHub gates branch protection (required
> signatures, blocking status checks) behind a paid plan for **private**
> repositories, and this repository is private. Enforcement is therefore
> client-side only — `commit.gpgsign = true` plus the pre-commit gate.
> **Do not assume an unsigned commit was rejected upstream**: commits
> predating this policy are unsigned, and automation running under the
> sandbox service accounts does not carry the signing configuration.

---

## Trust boundary — hub calls vs. a client's native tools

Nokido's guards apply to what goes **through the hub** (MCP on `:8766`), and
only to that. Be precise about where the line is:

- **Through the hub** — every MCP tool call. The caller's identity is resolved
  from its per-agent token (`app/forge_videur.py`), and an optional
  `LaForge-Provenance` header is validated, never trusted raw
  (`tools/nokido_hub.py::_provenance_http`). Execution runs in a tiered
  sandbox: `run` defaults to an offline account with loopback only, and
  egress needs an explicit `network=true`. Repository writes go through
  `governed_edit` (syntax check, secret scan, edit locks, re-read of the disk).
  Text bound for a cloud model passes the semantic firewall. Calls are
  journaled.
- **Native to the client** — a client's own file, shell or editor tools (for
  example Claude Code's Read/Write/Bash, an IDE editor, a CLI's shell). They
  run in the client's process with **your** user rights. The hub does not see
  them and cannot stop them.

What narrows that gap, and what it is **not**:

- In Claude Code, local `PreToolUse` hooks (`tools/forge_tool_gate.py`,
  `tools/bash_guard.py`) route native calls on the repository to the hub, or
  deny them (`LAFORGE_THIN_CLIENT_ENFORCE`). Hooks live in a settings file that
  you control. They are defense in depth, not a boundary.
- Clients without hooks are held to the same rules by discipline only
  ([`docs/RULES_CLIENTS_SANS_HOOKS.md`](docs/RULES_CLIENTS_SANS_HOOKS.md)).
- Autonomous executors write natively in **their own git worktree**.
  `governed_edit` refuses them on the shared tree. Their work reaches the main
  branch only as a commit that is reviewed and integrated.
- Every commit, on any surface, runs the pre-commit gate
  (`tools/forge_git_gate.py`). A secret blocks the commit; other checks, such
  as a firewall redaction token like `[SECRET_n]` copied into a file, warn.

In practice: treat any client that has native tools enabled as holding your
full user rights. The hub is a policy enforcement point for traffic that
passes through it. It is not a sandbox around the client.

## Known limitations

- Nokido is **alpha software**. APIs, schemas, and security primitives can
  change between commits. Pin to a tag for production-like usage.
- The pre-public branches may contain test credentials. Always rotate hub
  bearer tokens before deploying to a non-developer environment :
  `python tools/forge_vault_seed_agent_tokens.py --verify`.
- The Semantic Firewall reduces but does not eliminate prompt injection
  risk against cloud providers. Treat all cloud LLM output as untrusted
  by default.
- Ring 0 / MASTER privileges grant arbitrary code execution. Never expose
  a master-token endpoint over the network without TLS + mTLS.
- Some dependencies carry advisories with **no upstream fix available**. They are
  not silently ignored: each one is recorded in
  [`docs/cve_sans_correctif.md`](docs/cve_sans_correctif.md) with its exploitation
  precondition, its actual usage in this codebase, and the mechanically checkable
  condition under which the decision must be reopened. A vulnerability with no
  released fix is not a vulnerability that disappears.

---

## Scope

In scope :

- Code in `app/`, `tools/`, `proxy_deno/`, `go_services/`, `rust_ext/`.
- Default Docker images published from this repo.
- The MCP hub HTTP/STDIO interface.
- `pyproject.toml` extras and their direct integration code.

Out of scope :

- Third-party LLM providers (Anthropic, OpenAI, Google, Groq, …) — report
  to them directly.
- Vulnerabilities in user-installed extras (`torch`, `faiss-cpu`,
  `keyring`, …) — report upstream.
- Issues requiring local privileged access (we assume the local
  filesystem and process tree are trusted).

---

## Recognition

Verified reports get credited (with consent) in the release notes and a
`SECURITY-HALL-OF-FAME.md` once a fix ships. No monetary bounty program yet.

Thanks for keeping Nokido sovereign.
