# Nokido — ClawHub Skill Marketplace

Documentation for the ClawHub integration — Nokido's skill marketplace with 627 remote skills and 8 installed locally. Load when the user mentions `@skill`, ClawHub, skill installation, or wants to extend Nokido's capabilities.

## What ClawHub is

ClawHub (`https://clawhub.ai`) is an **external skill registry** — similar in spirit to Anthropic's skills but hosted independently, queryable via REST API, and with content not controlled by Anthropic.

Nokido uses ClawHub as a **lazy capability extension** mechanism: when an operator asks for a capability Nokido doesn't have (e.g. "audit a Kubernetes cluster's RBAC"), the system can search the catalog, install the matching skill, audit it locally, and run it in an isolated silo.

**API endpoint:** `https://clawhub.ai/api/v1`

## Principle of sovereignty

ClawHub never sees mission context. The bridge enforces:

```
User intention "audit K8s RBAC"
         │
         ▼
┌────────────────────────────────┐
│ ClawHub.search("k8s security") │  ← only query, no context
│ ← returns skill metadata       │
└────────────────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ SkillGuardian.review()         │  ← LOCAL (deepseek-coder)
│ - scan SKILL.md for malice     │
│ - check required tools         │
│ - validate frontmatter         │
└────────────────────────────────┘
         │ (approved)
         ▼
┌────────────────────────────────┐
│ SkillSiloRunner.execute()      │  ← isolated silo
│ qwen2.5-coder:7b local         │
│ no Nokido RAG exposure        │
└────────────────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ RAG.index(result)              │  ← ring=TRUSTED
│ → domain matched from SKILL.md │
└────────────────────────────────┘
```

ClawHub sees **only the HTTP query**. Results run local. Nokido's RAG is never exposed to the network.

## The @skill TUI command

Source: `app/forge_handler_skill.py`.

| Command | Action |
|---|---|
| `@skill search <query>` | Search the ClawHub catalog |
| `@skill install <slug>` | Install + SkillGuardian review + index to RAG |
| `@skill run <slug> [context]` | Run in isolated silo |
| `@skill list` | List installed skills |
| `@skill info <slug>` | Show details of an installed skill |
| `@skill remove <slug>` | Uninstall |
| `@skill status` | Bridge status (connected? last fetch? install queue?) |

Example session:
```
@skill search pentest kubernetes
> Found 12 matches in ClawHub catalog:
>   1. k8s-security-audit    (89% match, cyber/k8s)
>   2. kube-bench-runner     (71%, cyber/k8s)
>   3. rbac-analyzer         (68%, cyber/k8s)
>   ...

@skill install k8s-security-audit
> Fetching skill from ClawHub...
> SkillGuardian review: PASSED (no dangerous patterns)
> Indexing 23 chunks to RAG (domain=security)
> Skill installed. Run with: @skill run k8s-security-audit

@skill run k8s-security-audit --context "kubectl config current-context is prod-eu-1"
> Silo running on qwen2.5-coder:7b (domain=security)...
> [output here, stored in RAG]
```

## Bridge internals (forge_clawhub_bridge.py, 28.5 KB)

Main classes:

| Class | Role |
|---|---|
| `SkillFile` | Represents a single `.md` file within a skill package |
| `ClawSkill` | A complete skill: metadata + list of SkillFile |
| `ClawHubClient` | HTTP client for the `/api/v1/` endpoints |
| `SkillGuardian` | Local review (deepseek-coder) — vets content before install |
| `SkillSiloRunner` | Executes a skill in an isolated local silo |
| `SkillStore` | Local persistence of installed skills |
| `ClawHubBridge` | High-level orchestrator (used by `@skill` handler) |

### ClawHubClient API calls

| Method | Endpoint |
|---|---|
| `search(query, limit=20)` | `GET /api/v1/skills/search?q=...` |
| `fetch(slug)` | `GET /api/v1/skills/{slug}` |
| `list_categories()` | `GET /api/v1/categories` |
| `get_stats(slug)` | `GET /api/v1/skills/{slug}/stats` |

All requests go over HTTPS. No authentication required for read-only endpoints. No user tracking cookies accepted.

### SkillGuardian review

Runs **local** via `deepseek-coder:6.7b` (Ollama). Checks:

1. **Malicious code patterns** — eval, exec, rm -rf, reverse shells in code samples
2. **Unbounded shell commands** — anything that could fork-bomb or exfil
3. **Suspicious network calls** — beacons, DGA-like URLs
4. **Frontmatter consistency** — `name` matches filename, `description` present
5. **License** — rejects if explicit proprietary without permissive grant

Output: `(approved: bool, reasons: list[str])`.

If rejected, the bridge logs the reasons and **does not install**. Operator can override with `@skill install <slug> --force` (ring=DEV required).

### SkillSiloRunner execution

When `@skill run` is called:

1. Load the SKILL.md + dependent files from `skills/clawhub/<slug>/`
2. Build a silo prompt with:
   - System prompt: SKILL.md content (minus frontmatter)
   - User message: the context passed with `--context`
   - Supporting context: related files per skill's internal references
3. Route to `qwen2.5-coder:7b` (local Ollama)
4. Capture full output
5. Index to RAG with `domain` extracted from SKILL.md metadata
6. Return to user

## Installed skills (current state)

Source: `skills/clawhub/` — 13 entries, 6 with SKILL.md content. Total RAG chunks from skills: **~1467**.

| Skill | Size | Files | RAG domain | Chunks |
|---|---|---|---|---|
| `ctf-pwn` | 352 KB | 16 md | exploit | 179+ |
| `ctf-reverse` | 322 KB | 15 md | security | 150+ |
| `ctf-web` | 322 KB | 17 md | security | 182+ |
| `nmap-recon` | 4 KB | 3 md | recon | 5 |
| `security-auditor` | 11 KB | 2 md | security | 16 |
| `sql-injection-testing` | 7 KB | 2 md | security | 9 |
| `ctf-solver` | 0 KB | 0 | — | 0 (placeholder) |
| `ctf-osint` | 1 KB | metadata only | — | 0 |
| `payloads` | 0 KB | 0 | — | 0 (placeholder) |
| `agentic-security-audit` | 1 KB | metadata only | — | 0 |
| `code-review-fix` | 0 KB | metadata only | — | 0 |
| `iterative-code-review` | 1 KB | metadata only | — | 0 |

### CTF skill deep files

The three "real" CTF skills (pwn, reverse, web) ship with detailed technique guides beyond their SKILL.md:

**ctf-pwn** (16 files, 352 KB):
- `SKILL.md` (main entry), `overflow-basics.md`, `rop-and-shellcode.md`, `rop-advanced.md`
- `format-string.md`, `heap-techniques.md`, `sandbox-escape.md`, `kernel.md`, `kernel-techniques.md`, `kernel-bypass.md`
- `advanced.md`, `advanced-exploits.md`, `advanced-exploits-2.md`, `advanced-exploits-3.md`, `advanced-exploits-4.md`

**ctf-reverse** (15 files, 322 KB):
- `SKILL.md`, `languages.md`, `languages-compiled.md`, `languages-platforms.md`
- `patterns.md`, `patterns-ctf.md`, `patterns-ctf-2.md`, `patterns-ctf-3.md`
- `platforms.md`, `platforms-hardware.md`
- `tools.md`, `tools-dynamic.md`, `tools-advanced.md`, `anti-analysis.md`

**ctf-web** (17 files, 322 KB):
- `SKILL.md`, `server-side.md`, `server-side-advanced.md`, `server-side-advanced-2.md`, `server-side-exec.md`, `server-side-exec-2.md`, `server-side-deser.md`
- `client-side.md`, `client-side-advanced.md`, `sql-injection.md`, `node-and-prototype.md`, `web3.md`
- `auth-and-access.md`, `auth-infra.md`, `auth-jwt.md`, `cves.md`

## Remote catalog (627 skills — approximate distribution)

Source: `PANEL_ORCHESTRATION.md`.

| Category | Count |
|---|---|
| AI / LLM agents | 228 |
| Code / Dev | 158 |
| DevOps / Infra | 140 |
| Data | 87 |
| Cyber / Pentest | 77 |
| Reporting / Doc | 75 |
| Mobile / HW | 28 |
| OSINT / Recon | 9 |
| **Total** | **627** |

## Auto-installation (forge_clawhub_autoinstall.py)

For **intention-driven** skill discovery. Used internally by `trigger_autonomous_evolution` when a domain needs capabilities not currently installed.

```python
from app.forge_clawhub_autoinstall import suggest_skills, install_skill

# Score all 627 catalog skills against an intention
matches = suggest_skills("audit kubernetes RBAC", top_k=3)
# [("k8s-security-audit", 8.5, "full description..."),
#  ("rbac-analyzer", 7.1, "..."),
#  ("kube-bench-runner", 6.8, "...")]

# Install (with SkillGuardian audit)
install_skill("k8s-security-audit", audit=True, index_rag=True)
```

Scoring = TF-IDF naïve on skill names + descriptions + tags. Good enough for discovery; refine by running `@skill info` on the top 3.

## Skill file format

A ClawHub skill = directory with:

```
skill-slug/
├── _meta.json           # registry metadata (name, version, author, stats)
├── SKILL.md             # main skill file with frontmatter + body
├── <additional>.md      # supporting reference files (optional)
└── createdAt.md, updatedAt.md, slug.md, displayName.md, tags.md, stats.md, summary.md
```

The frontmatter follows Anthropic's skill convention:
```yaml
---
name: k8s-security-audit
description: Use this skill when auditing Kubernetes cluster...
---
```

## Operator workflows

### Discover capabilities for a task

```
User: I need to check if my Kubernetes pods use non-root users.
Claude: (calls) @skill search kubernetes security
       > Returns matches
       (picks) @skill install k8s-security-audit
       > Audited OK, installed
       (runs) @skill run k8s-security-audit --context "kubectl config..."
       > Returns skill output, indexed to RAG
```

### Export a custom skill back to ClawHub

Not currently supported via MCP tools. Must be done manually:
1. Write SKILL.md + supporting files locally
2. Package as tarball
3. Submit via ClawHub web UI (requires account)
4. ClawHub moderators review (community-driven)

### Clean up installed skills

```
@skill list
> 13 skills installed
@skill remove ctf-solver
> Removing ctf-solver... RAG chunks unlinked (0 chunks, placeholder)
```

Note: removing a skill **does not** delete its RAG chunks automatically. Use `query("DELETE FROM rag_chunks WHERE source_skill='ctf-solver'")` after removal if you want a full clean.

## Failure modes specific to ClawHub

- **`ClawHubClient` timeout** → the HTTPS call hit a network issue. Bridge falls back to cached metadata if available.
- **`SkillGuardian` rejects installation** → content contained flagged patterns. Check stderr for the specific reason. Override requires ring=DEV.
- **Skill runs but outputs gibberish** → the SKILL.md is targeted at a model family Nokido doesn't have locally. Check the skill's declared model requirements.
- **`@skill search` returns zero results for a likely term** → catalog has API pagination. Bridge shows top-20 by default; try `@skill search <term> --limit 50`.
- **RAG chunk count drift** — Installation is idempotent but re-installing adds new chunks. Use `@skill remove` before reinstall if clean count matters.

## What NOT to do with ClawHub

- **Don't install a skill without SkillGuardian review.** The `--force` flag exists for dev use only.
- **Don't expose mission context to the search query.** Search with generic terms (`"kubernetes rbac"`), not specific details (`"my client's prod cluster eu-west-3"`).
- **Don't run a skill at higher ring than what its `SKILL.md` declares.** If the skill says `ring: TRUSTED`, don't escalate it to SYSTEM manually.
- **Don't bypass the SkillSiloRunner** — running skill content in your own silo mixes its context with Nokido's.
