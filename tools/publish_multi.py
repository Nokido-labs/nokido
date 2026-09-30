"""tools/publish_multi.py — Multi-platform publish au go-public AGPLv3.

Source roadmap_multi_platform_publish. Mirror push parallele :
- GitHub (origin, principal)
- Codeberg (mirror EU/sovereignty-friendly)
- GitLab (optionnel - audience differente)
- Sourcehut (optionnel - minimaliste fans)
- HuggingFace Spaces (demo deployment if applicable)

Plus posts auto :
- Show HN draft
- Reddit /r/selfhosted /r/sysadmin posts
- Lobste.rs link
- awesome-* PR drafts

Usage : LAFORGE_PYTHON tools/publish_multi.py --branch alpha --check
        LAFORGE_PYTHON tools/publish_multi.py --branch alpha --push --remotes github,codeberg
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : publication multi-plateforme au go-public AGPLv3"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


REMOTES_CONFIG = {
    "github": {
        "url_template": "https://github.com/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "Nokido",
    },
    "codeberg": {
        "url_template": "https://codeberg.org/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "Nokido",
    },
    "gitlab": {
        "url_template": "https://gitlab.com/{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "nokido",
    },
    "sourcehut": {
        "url_template": "https://git.sr.ht/~{owner}/{repo}",
        "default_owner": "user",
        "default_repo": "nokido",
    },
}


def check_remote_exists(remote_name: str) -> bool:
    """Verify git remote configured."""
    try:
        result = subprocess.run(
            ["git", "remote"], cwd=ROOT, capture_output=True, text=True, timeout=10
        , errors="replace")
        return remote_name in result.stdout.split()
    except Exception:
        return False


def push_remote(remote: str, branch: str, force_with_lease: bool = False) -> dict:
    """Push branch to remote. Returns dict with result."""
    if not check_remote_exists(remote):
        return {"remote": remote, "ok": False, "error": "remote not configured"}

    cmd = ["git", "push"]
    if force_with_lease:
        cmd.append("--force-with-lease")
    cmd.extend([remote, branch])

    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60, errors="replace")
        ok = result.returncode == 0
        return {
            "remote": remote,
            "ok": ok,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }
    except Exception as e:
        return {"remote": remote, "ok": False, "error": str(e)}


def gen_show_hn_post(version: str = "0.1") -> str:
    """Generate Show HN post draft."""
    return f"""Show HN: Nokido – Autonomous sovereign AI OS (local-first, AGPLv3)

After 18 months of building, releasing {version} of Nokido: an autonomous
AI operating system designed for sovereignty.

Key differentiators vs OpenHands / AutoGPT / SuperAGI :
- 100% local-first (no cloud telemetry, BGE-M3 embedding local)
- Multi-LLM cascade (Cerebras + Groq + Mistral free tiers + Ollama)
- Veille autonome closed-loop (detect knowledge gaps -> generate themes ->
  ingest papers from OpenAlex/arxiv -> embed)
- LAN observability via netcfg-agent
- TUI Textual v3 + Web HTMX dashboard
- Anti-saturation framework (Job Objects, CPU throttle)
- Sovereign memory architecture (LeCun JEPA + MemGPT-style hierarchical)

Stack : Python 3.14 + Deno 2 + Rust ONNX + Go dispatcher.

GitHub : https://github.com/Nokido-labs/nokido
Demo video : [TODO]

Looking for feedback on architecture, security model, and use cases.
"""


def gen_reddit_post(subreddit: str = "selfhosted") -> str:
    """Reddit post template."""
    return f"""# Nokido - Local-first AI OS with autonomous web monitoring

Just released Nokido (AGPLv3), an AI operating system focused on
self-hosting + sovereignty.

What it does :
- Monitors your interests autonomously (define themes, agent ingests papers)
- LAN observability (devices, services, vulns) via netcfg-agent
- TUI for ops + Web dashboard
- Multi-LLM cascade (free tier cloud + local Ollama fallback)
- All data stays local (BGE-M3 embeddings, FAISS index, SQLite WAL)

Install : docker-compose up
Repo : https://github.com/Nokido-labs/nokido

Target use-cases :
- Self-hosters who want AI ops automation without sending data to OpenAI
- Security teams who need LAN visibility + threat intelligence
- Researchers who want closed-loop knowledge ingestion

Would love feedback from /r/{subreddit} community.
"""


def gen_lobsters_post() -> dict:
    return {
        "title": "Nokido: Autonomous local-first AI OS with closed-loop knowledge ingestion",
        "url": "https://github.com/Nokido-labs/nokido",
        "tags": ["ai", "selfhosted", "python", "security", "agpl"],
    }


def gen_awesome_pr() -> dict:
    """Awesome-list PR snippet."""
    return {
        "awesome-selfhosted": {
            "category": "AI / LLM",
            "entry": "- [Nokido](https://github.com/Nokido-labs/nokido) - "
            "Sovereign local-first AI OS with autonomous web monitoring + LAN observability. "
            "(`Source code`)[https://github.com/Nokido-labs/nokido] `AGPL-3.0` `Docker/Python`",
        },
        "awesome-llm": {
            "category": "Agentic Systems",
            "entry": "- [Nokido](https://github.com/Nokido-labs/nokido) - Closed-loop knowledge ingestion + multi-LLM cascade routing. `AGPL-3.0`",
        },
    }


def dry_run_check(branch: str, remotes: list[str]) -> dict:
    """Pre-flight check : verify branch exists, remotes configured, no unstaged."""
    checks = {}
    # Branch exists locally
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, timeout=5
        , errors="replace")
        current = result.stdout.strip()
        checks["current_branch"] = current
        checks["target_branch_matches"] = current == branch
    except Exception as e:
        checks["branch_check_err"] = str(e)

    # Remotes configured
    for r in remotes:
        checks[f"remote_{r}"] = check_remote_exists(r)

    # Unstaged changes
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=5
        , errors="replace")
        checks["unstaged_files"] = len(result.stdout.strip().splitlines())
        checks["clean_working_tree"] = result.stdout.strip() == ""
    except Exception:
        pass

    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--check", action="store_true", help="Dry-run pre-flight check")
    ap.add_argument("--push", action="store_true", help="Actually push (default dry-run)")
    ap.add_argument("--remotes", default="github,codeberg", help="Comma-separated remotes")
    ap.add_argument("--force-with-lease", action="store_true")
    ap.add_argument(
        "--gen-posts", action="store_true", help="Generate post drafts (Show HN/Reddit/etc.)"
    )
    args = ap.parse_args()

    remotes = [r.strip() for r in args.remotes.split(",")]

    if args.gen_posts:
        print("=== Show HN ===")
        print(gen_show_hn_post())
        print("\n=== Reddit /r/selfhosted ===")
        print(gen_reddit_post("selfhosted"))
        print("\n=== Lobste.rs ===")
        print(json.dumps(gen_lobsters_post(), indent=2))
        print("\n=== Awesome-list PRs ===")
        print(json.dumps(gen_awesome_pr(), indent=2))
        return

    if args.check:
        checks = dry_run_check(args.branch, remotes)
        print(json.dumps(checks, indent=2))
        return

    if args.push:
        # Mandatory pre-flight
        checks = dry_run_check(args.branch, remotes)
        if not checks.get("clean_working_tree", False):
            print(f"REFUSE push : unstaged_files={checks.get('unstaged_files', 0)}")
            sys.exit(1)
        results = []
        for r in remotes:
            res = push_remote(r, args.branch, args.force_with_lease)
            results.append(res)
            status = "OK" if res.get("ok") else "FAIL"
            print(
                f"[{status}] {r}: {res.get('stderr', '')[:200] if not res.get('ok') else 'pushed'}"
            )
        print(json.dumps(results, indent=2))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
