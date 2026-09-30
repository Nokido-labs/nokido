# Contributing to Nokido

Welcome. Nokido is an **alpha-stage**, AGPLv3, sovereignty-first AI Operating
System. Contributions are very welcome — but they follow a few non-negotiable
rules that come straight from the project's philosophy (see `MANIFESTO.md`
and `CLAUDE.md`).

---

## Quick start for contributors

```bash
# Clone + branch from alpha (active dev) or beta (release-prep)
git clone https://github.com/Nokido-labs/nokido.git
cd Nokido
git checkout -b feat/my-thing alpha

# Install dev extras
bash install.sh                # default: hub,rag,llm,docs
EXTRAS=full bash install.sh    # everything except heavy ML
source .venv/bin/activate
pip install -e ".[dev,security]"

# Validate setup
pytest -x tests/test_forge_scorecard.py
laforge-secrets status         # vault diagnostic
```

If you're on Windows :

```powershell
.\install.ps1                  # detects miniforge3
```

---

## Branch policy

| Branch  | Purpose                          | Push policy        |
|---------|----------------------------------|--------------------|
| `main`  | Stable releases (tagged)         | Maintainer only    |
| `beta`  | Release-prep, public-facing      | PR + review        |
| `alpha` | Active development               | PR or direct (dev) |
| `feat/*`, `fix/*`, `docs/*`, `chore/*` | Topic branches | Anyone (PR target = `alpha`) |

Always branch from `alpha`. Target your PR back to `alpha`. The maintainer
periodically promotes `alpha` → `beta` → `main`.

---

## The 11 rules of Nokido (from `CLAUDE.md` §7)

Every PR is reviewed against these. Failing any of them = the PR doesn't merge.

1. **Never raw SQL `LIKE` on the RAG.** Use `rag_fts` (FTS5) or
   `RAGEngine.search`.
2. **Never create `app/forge_*.py` without a prior `rag_fts` query** to check
   for existing coverage. Anti-duplication is the project's first reflex.
3. **Never `INSERT INTO rag_chunks` without an explicit `id`** (TEXT PRIMARY KEY).
4. **Never send a prompt cloud without `SemanticFirewall.pre_flight` +
   `.post_flight`.** Cloud egress is a privileged action.
5. **Always `read_lessons(3000)` at session start** if you're an LLM-assisted
   contributor.
6. **Always `anchor_solution()` after a non-trivial architectural decision** —
   so future sessions find your reasoning.
7. **Always run `session_summary()` after a block of commits.**
8. **Always document the relationships between co-modified modules.**
9. **Always `tqdm` on long loops** in generated scripts.
10. **Never `nssm restart LaForgeMCP` directly** — pass through `LaForge-Master`
    (Windows only).
11. **Never inline `python` raw.** Use the absolute interpreter path.

---

## Pull request workflow

1. **Open an issue first** for non-trivial changes — talk it through, especially
   for security-sensitive areas (firewall, membrane, RBAC, vault).
2. **Branch from `alpha`.**
3. **Keep PRs focused.** One topic = one PR. Refactors stay separate from
   features.
4. **Add tests.** New modules under `app/forge_*.py` need at least one unit
   test under `tests/`. Use the `@pytest.mark.unit` marker for fast tests.
5. **Update the right docs.** Touching a public-facing API ? Update `README.md`,
   `docs/ARCHITECTURE.md`, and your module's docstring.
6. **No raw secrets.** All bearers / API keys go through the vault. Pre-commit
   Gitleaks will reject leaks automatically.
7. **Run the linters.**
   ```bash
   ruff check app/ tools/
   pytest -m unit
   ```
8. **Sign-off your commits.** `git commit -s` — by signing, you confirm the
   contribution is yours and you have the right to license it under AGPLv3.
9. **Reference the issue.** `Closes #42` or `Refs #42` in the PR body.

---

## Commit message conventions

Nokido follows [Conventional Commits](https://www.conventionalcommits.org/) :

```
<type>(<scope>): <short summary>

<longer body if needed>

<footer with refs / breaking changes>
```

Types : `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `style`,
`build`, `ci`, `security`.

Examples :

```
feat(rag): add cross-encoder reranker fallback when bge-m3 model is absent
fix(firewall): post_flight false positive on legitimate <details> HTML tag
chore(deps): bump litellm to 1.42.0
docs(manifesto): add neuromorphic chip energy section
security(vault): cross-OS keyring fallback for macOS/Linux
```

For commits authored by an LLM (Claude Code, Codex CLI, Gemini CLI), the
project policy is **no `Co-Authored-By` trailer** — commits remain signed by
the human contributor only.

---

## Code style

- Python ≥ 3.12. Type hints encouraged but not enforced (the codebase is
  partially typed).
- `ruff` for linting (config in `pyproject.toml`).
- 120-char lines.
- No unnecessary comments. The code should be readable on its own. Reserve
  comments for **why**, not **what**.

---

## Security-sensitive contributions

Touching any of the following requires a **separate issue with the
`security` label** before submitting a PR :

- `app/forge_semantic_firewall.py`, `forge_sovereign_membrane.py`,
  `forge_integrity.py`, `forge_prompt_guard.py`.
- `app/forge_secrets.py`, `app/forge_machine_vault.py`.
- `tools/bash_guard.py`, `tools/hook_*.py`.
- `tools/nokido_hub.py` `_resolve_ring` / `_AGENT_LIST`.
- `.gitleaks.toml` allowlists.
- Any change that touches network egress, sandboxing, or RBAC ring resolution.

The maintainer reviews these PRs personally and may take longer to merge.

---

## Reporting bugs

Use the GitHub issue templates :

- **Bug report** — describe steps, expected vs actual, environment (OS,
  Python version, branch + commit SHA, hardware).
- **Feature request** — describe the use case before the proposed solution.
- **Security advisory** — see `SECURITY.md` (private disclosure first).

---

## License & CLA — read before opening a PR

Nokido ships under a **dual-licensing model** :

- [**AGPLv3-or-later**](LICENSE) — the default, free / open-source.
- [**Commercial License**](COMMERCIAL.md) — for proprietary / closed-
  source / SaaS use cases where AGPLv3 doesn't fit.

For the maintainer to be able to offer commercial licenses to companies
that cannot comply with AGPLv3, the project must hold a **broad
license on every Contribution**. You keep copyright — but you grant the
maintainer permission to re-license your code, including under
proprietary terms.

This is enforced by the **Contributor License Agreement (CLA)**, signed
**automatically on your first PR** via the CLA Assistant bot.

### What you have to do

1. Read the CLA : [docs/CLA.md](docs/CLA.md) (10 short sections, ~5 min).
2. Open your PR normally.
3. The CLA Assistant bot will comment, asking you to reply with :

   > I have read and agree to the CLA

   Reply once, you're set for **all future contributions** to Nokido.
4. Your signature is appended to
   [`docs/CLA-signatures.md`](https://github.com/Nokido-labs/nokido/blob/cla-signatures/docs/CLA-signatures.md) (public, auditable).

### Corporate contributions

If you contribute **as part of your employment** OR your employer holds
IP rights to your work, the Individual CLA is **not enough**. Your
employer needs to sign the **Corporate CLA (CCLA)** separately — open a
Discussion titled `[Nokido Corporate CLA]` (or mention @user) to request the
template.

### Why a CLA ?

Without it, every contributor would retain veto rights on commercial
relicensing of their code. That would make the dual-licensing model
impossible — and the dual model is what funds long-term maintenance
without compromising on AGPLv3 for the open-source community.

The CLA does **not** transfer copyright. It is a license, not an
assignment. You can use your own contribution in your own projects
under any license you like — the CLA only adds the maintainer's right
to relicense.

If you cannot or will not sign the CLA, you can still :

- File issues and bug reports.
- Propose changes in Discussions for the maintainer to re-implement
  independently.
- Fork Nokido under AGPLv3 (your fork is entirely yours).

But your code cannot be merged upstream without the CLA.

---

## Recognition

Contributors are listed in `CONTRIBUTORS.md` (created at first external PR).
Significant architectural contributions get a mention in the release notes.

---

Questions ? Open a Discussion, or mention @user.
