# Code of Conduct

## Our Pledge

Nokido is built on the idea that **sovereignty, memory, and intelligence are
collective goods**. We commit to maintaining a project space that is welcoming,
respectful, and rigorous — open to contributors regardless of background,
experience level, or stack preference.

We pledge to make participation in this project a harassment-free experience
for everyone.

## Our Standards

Examples of behavior that contribute to a positive environment :

- Using welcoming and inclusive language.
- Respecting differing viewpoints and experiences.
- Gracefully accepting constructive criticism.
- Focusing on what is best for the project and its users.
- Showing empathy toward other community members.
- Backing claims with measurements, not vibes (Nokido is a benchmark-honest
  project — show your numbers).

Examples of unacceptable behavior :

- Personal attacks, trolling, derogatory or insulting comments.
- Public or private harassment.
- Publishing others' private information (doxxing).
- Sharing or requesting credentials, API keys, or session tokens in public
  spaces (issues, PRs, Discussions, chat).
- Submitting malicious code, hidden exfiltration logic, or supply-chain
  poisoning. The project takes that extremely seriously and will report
  to the relevant authorities.
- Other conduct which could reasonably be considered inappropriate in a
  professional setting.

## Project-specific norms

- **Measure, don't assume.** If you propose a perf claim, ship the runner
  too. Nokido has `tools/forge_*_runner.py` patterns for that.
- **Anti-duplication first.** Before adding a new `app/forge_*.py` module,
  search `rag_fts` and read existing modules. See `CLAUDE.md` §3.
- **No silent SQL LIKE on the RAG.** Always go through `rag_fts` or
  `RAGEngine.search`. It's rule #1 of the project.
- **No raw `python`.** Use the absolute interpreter path (`miniforge3`
  on Win, your venv's `python` on Linux/macOS).
- **Secrets in vault, never in `.env` committed.** See `forge_secrets.py`
  + `forge_machine_vault.py`.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to :

the maintainer (**@user**), privately, through the repository's *Security*
tab → *Report a vulnerability* form (it is private to you and the maintainer) —
state in the title that the report concerns the Code of Conduct.

All complaints will be reviewed and investigated promptly and fairly. The
project maintainers are obligated to maintain confidentiality with regard to
the reporter of an incident.

Maintainers may take any action they deem appropriate, up to and including a
temporary or permanent ban from the project, its forks, its Discussions, and
all related communication channels.

## Attribution

This Code of Conduct is adapted from the
[Contributor Covenant](https://www.contributor-covenant.org/), version 2.1,
available at <https://www.contributor-covenant.org/version/2/1/code_of_conduct.html>.
