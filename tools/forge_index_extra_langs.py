"""forge_index_extra_langs.py — Indexe le code TypeScript / Rust dans le RAG.

`index_app_dir` n'indexait que app/ (Python). proxy_deno (TypeScript, systeme
nerveux Deno) et go_services (Rust, brain_worker/dispatcher) n'etaient jamais
vectorises -> le RAG paraissait 99% Python. Ce script indexe leurs sources via
index_file (chunker generique pour non-.py, id sha256, preservation embeddings).

Run : run action=trusted_script path=tools/forge_index_extra_langs.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_rag_index_app import _get_conn, index_file  # noqa: E402

_SKIP = {"node_modules", "target", "dist", ".git", "__pycache__", "build", "vendor", ".cache"}
PATTERNS = [
    "proxy_deno/**/*.ts",
    "proxy_deno/**/*.js",
    "go_services/**/*.rs",
    "go_services/**/*.go",
]


def main() -> None:
    conn = _get_conn()
    total_files = total_chunks = 0
    for pat in PATTERNS:
        for p in sorted(ROOT.glob(pat)):
            if any(x in p.parts for x in _SKIP):
                continue
            try:
                n = index_file(conn, p, force=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ERR {p.name}: {type(e).__name__}: {str(e)[:90]}")
                continue
            if n:
                total_files += 1
                total_chunks += n
    conn.close()
    print(
        f"[extra-langs] {total_files} fichiers TS/Rust indexes -> "
        f"{total_chunks} chunks (NULL embedding, a vectoriser)"
    )


if __name__ == "__main__":
    main()
