"""hook_search_guard.py -- PreToolUse guard (Read | Grep | Glob).

Forces search/read deport so raw results don't pile into the client context.
Fail-open: any unexpected error -> exit 0 (never block by accident).

- Read of a file > SIZE_LIMIT bytes with no `limit`/`offset` -> BLOCKED.
  Deport: hub `read_function_body` (one function), hub `read` windowed, or
  Read with limit/offset. Broad multi-file search -> Agent(Explore): its
  matches stay in the sub-agent context, not the client's.
- Grep with `head_limit: 0` (explicit unbounded content dump) -> BLOCKED.
- Glob -> allowed (paths only, cheap).

Safe for sub-agents (Explore): the blocked patterns are wasteful everywhere,
and Explore is designed to read excerpts, so it adapts rather than breaks.

Exit 2 = block (stderr fed back to the caller). Exit 0 = allow.
Wired: .claude/settings.local.json -> hooks.PreToolUse, matcher Read|Grep|Glob.
"""

import json
import os
import sys

SIZE_LIMIT = 14000  # bytes (~200 lines): above this an unbounded Read is waste


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name", "")
        ti = data.get("tool_input") or {}

        if tool == "Read":
            if ti.get("limit") or ti.get("offset"):
                return 0  # bounded read -- fine
            try:
                size = os.path.getsize(ti.get("file_path", ""))
            except OSError:
                return 0  # missing file -- let Read surface its own error
            if size > SIZE_LIMIT:
                print(
                    f"[search-guard] BLOQUE -- Read non borne sur "
                    f"{ti.get('file_path', '')} ({size} o, ~{size // 70} L). "
                    "Deporte: hub read_function_body (une fonction), get_file_skeleton "
                    "(la structure), ou Read avec limit/offset (une plage ; le hub "
                    "`read` rend le fichier entier). Recherche large multi-fichiers : "
                    "introspect puis forge_deep_explore.",
                    file=sys.stderr,
                )
                return 2
            return 0

        if tool == "Grep":
            if ti.get("head_limit") == 0:
                print(
                    "[search-guard] BLOQUE -- Grep head_limit:0 = dump contenu "
                    "non borne. Mets un head_limit, ou delegue a Agent(Explore).",
                    file=sys.stderr,
                )
                return 2
            return 0

        return 0  # Glob and anything else: allowed
    except Exception:
        return 0  # fail-open -- never block on a guard bug


if __name__ == "__main__":
    sys.exit(main())
