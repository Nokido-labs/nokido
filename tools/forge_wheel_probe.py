"""tools/forge_wheel_probe.py - Probe critical wheels on the active Python.

Tests import for each Nokido-critical package + reports version + free-threaded compat.
Run on miniforge3 base (3.12), laforge_py314 (3.14 GIL), laforge_py314t (3.14t no-GIL).
Output JSON for cross-env diff.

Usage:
    LAFORGE_PYTHON tools/forge_wheel_probe.py
    %USERPROFILE%/miniforge3/envs/laforge_py314t/python.exe tools/forge_wheel_probe.py --json
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys

# Critical wheel list for Nokido runtime.
# Group = visual cluster only.
CRITICAL_WHEELS = {
    "core": [
        "httpx",
        "aiohttp",
        "fastapi",
        "starlette",
        "uvicorn",
        "pydantic",
        "pydantic_core",
        "tomli",
        "msgpack",
    ],
    "mcp": [
        "mcp",
        "anyio",
    ],
    "rag_embed": [
        "numpy",
        "faiss",
        "rank_bm25",
        "onnxruntime",
        "transformers",
        "sentence_transformers",
        "tokenizers",
    ],
    "ml_torch": [
        "torch",
        "torchvision",
        "torchaudio",
    ],
    "ipc": [
        "zmq",
    ],
    "system": [
        "psutil",
        "win32api",
        "pywintypes",
    ],
    "lint_test": [
        "ruff",
        "pyright",
        "pytest",
        "beartype",
    ],
    "skills": [
        "tqdm",
        "rich",
        "textual",
    ],
}


def probe(name: str) -> dict:
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "?")
        return {"name": name, "ok": True, "version": str(ver)}
    except ImportError as e:
        return {"name": name, "ok": False, "error": f"ImportError: {e}"[:160]}
    except Exception as e:
        return {"name": name, "ok": False, "error": f"{type(e).__name__}: {e}"[:160]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    runtime = {
        "python": sys.version.split()[0],
        "version_tuple": list(sys.version_info[:3]),
        "free_threaded": hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled(),
        "executable": sys.executable,
        "platform": sys.platform,
    }

    results = {}
    flat = []
    for group, names in CRITICAL_WHEELS.items():
        rs = [probe(n) for n in names]
        results[group] = rs
        flat.extend(rs)

    ok = sum(1 for r in flat if r["ok"])
    total = len(flat)

    if args.json:
        print(json.dumps({"runtime": runtime, "results": results, "ok": ok, "total": total}, indent=2))
        return 0

    print(f"=== {runtime['python']} (free-threaded={runtime['free_threaded']}) ===")
    print(f"exec: {runtime['executable']}\n")
    for group, rs in results.items():
        print(f"[{group}]")
        for r in rs:
            mark = "OK" if r["ok"] else "FAIL"
            extra = r.get("version", r.get("error", ""))
            print(f"  {mark:4s} {r['name']:25s} {extra}")
        print()
    print(f"== TOTAL: {ok}/{total} OK ==")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
