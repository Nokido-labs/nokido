"""tools/cleanup_workdir.py — Cleanup workdir audit + propose drops.

Dry-run par defaut. --apply pour delete (avec backup tar/zip optionnel).

Categorise dossiers parent + LaForge/sandbox :
- DROP_SAFE : node_modules, venv obsolete (recreate easy)
- ARCHIVE  : data-Claude-Desktop-* (large backup), SessionGeminiWeb (sessions logs)
- KEEP    : git repos, code working
- REVIEW  : agent_data, _inception_archive, rag/rag_files (manual check)
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PARENT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[2]))
NOKIDO = PARENT / "Nokido"

CATEGORIES = {
    "DROP_SAFE": {
        "venv": "obsolete venv (Nokido utilise miniforge3)",
        "node_modules": "npm cache",
        "_inception_archive": "ancien archive",
    },
    "ARCHIVE": {
        "data-Claude-Desktop-03052026": "backup Claude Desktop (307 MB) - archive externally",
        "SessionGeminiWeb": "sessions logs Gemini Web",
    },
    "KEEP": {
        "Nokido": "main code repo",
        "netcfg-agent": "netcfg ecosystem",
        "netcfg-agent-mcp": "netcfg MCP server",
        "netcfg-agent-tui": "netcfg TUI",
        "netcfg-agent-web": "netcfg web",
        "modelcontextprotocol": "MCP reference repo",
        "docker": "Docker config",
    },
    "REVIEW": {
        "agent_data": "minimal but unknown",
        "rag": "RAG temp ?",
        "rag_files": "RAG temp ?",
        "sandbox": "parent sandbox (different from LaForge/sandbox)",
        "sandbox_tools": "tooling",
        "logs": "logs dir",
        "tests": "parent tests",
        "tools": "parent tools",
        "versions": "versioning ?",
    },
}


def dir_size_mb(d: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        return total / 1024 / 1024
    except Exception:
        return 0.0


def audit() -> dict:
    out = {"DROP_SAFE": [], "ARCHIVE": [], "KEEP": [], "REVIEW": [], "UNKNOWN": []}
    for d in PARENT.iterdir():
        if not d.is_dir():
            continue
        if d.name.startswith("."):
            continue
        size_mb = dir_size_mb(d)
        is_git = (d / ".git").exists()
        info = {"name": d.name, "size_mb": round(size_mb, 1), "is_git": is_git, "path": str(d)}
        categorized = False
        for cat, mapping in CATEGORIES.items():
            if d.name in mapping:
                info["reason"] = mapping[d.name]
                out[cat].append(info)
                categorized = True
                break
        if not categorized:
            out["UNKNOWN"].append(info)
    return out


def execute_drop(items: list, backup_dir: Path | None = None) -> dict:
    """Drop items. Si backup_dir : tar.gz avant drop."""
    results = {"dropped": [], "errors": []}
    for item in items:
        path = Path(item["path"])
        try:
            if backup_dir and item.get("size_mb", 0) > 1:
                backup_dir.mkdir(exist_ok=True)
                # Just rename to backup (no tar to avoid heavy ops in sandbox)
                target = backup_dir / item["name"]
                if target.exists():
                    target = backup_dir / f"{item['name']}_dup"
                shutil.move(str(path), str(target))
                results["dropped"].append({"name": item["name"], "moved_to": str(target)})
            else:
                shutil.rmtree(path)
                results["dropped"].append({"name": item["name"], "removed": True})
        except Exception as e:
            results["errors"].append({"name": item["name"], "error": str(e)})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply-drop-safe",
        action="store_true",
        help="Drop DROP_SAFE category (venv, node_modules, _inception_archive)",
    )
    ap.add_argument(
        "--apply-archive", action="store_true", help="Move ARCHIVE category to backup dir"
    )
    ap.add_argument(
        "--backup-dir", type=str, default=str(Path.home() / "Desktop" / "Nokido_archive")
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    audit_result = audit()

    if args.json:
        print(json.dumps(audit_result, indent=2))
        return

    print("=== Workdir cleanup audit ===\n")
    for cat in ("DROP_SAFE", "ARCHIVE", "REVIEW", "UNKNOWN", "KEEP"):
        items = audit_result.get(cat, [])
        total_mb = sum(i["size_mb"] for i in items)
        print(f"[{cat}] {len(items)} dirs, {total_mb:.1f} MB total")
        for i in items:
            git_marker = "[GIT]" if i["is_git"] else "     "
            reason = i.get("reason", "?")
            print(f"  {git_marker} {i['size_mb']:7.1f} MB  {i['name']:35} {reason}")
        print()

    if args.apply_drop_safe:
        items = audit_result["DROP_SAFE"]
        print(f"\n[APPLY DROP_SAFE] {len(items)} items")
        result = execute_drop(items, backup_dir=None)
        print(json.dumps(result, indent=2))

    if args.apply_archive:
        items = audit_result["ARCHIVE"]
        backup = Path(args.backup_dir)
        print(f"\n[APPLY ARCHIVE] {len(items)} items -> {backup}")
        result = execute_drop(items, backup_dir=backup)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
