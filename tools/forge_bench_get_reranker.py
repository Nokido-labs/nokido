"""forge_bench_get_reranker.py — Telecharge le GGUF du reranker bge-reranker-v2-m3.

Etape 3 du benchmark. Recupere bge-reranker-v2-m3-Q8_0.gguf (~636 MB, Apache-2.0)
depuis HuggingFace vers data/llm_models/. Idempotent.

Run : run action=trusted_script path=tools/forge_bench_get_reranker.py
"""

import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "llm_models" / "bge-reranker-v2-m3-Q8_0.gguf"
URL = (
    "https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/"
    "bge-reranker-v2-m3-Q8_0.gguf"
)


def main() -> None:
    if DEST.exists() and DEST.stat().st_size > 600_000_000:
        print(f"[reranker] deja present : {DEST.name} ({DEST.stat().st_size / 1e6:.0f} MB)")
        return
    DEST.parent.mkdir(parents=True, exist_ok=True)
    part = DEST.with_name(DEST.name + ".part")
    print(f"[reranker] download -> {DEST.name}", flush=True)
    t0 = time.time()
    req = urllib.request.Request(URL, headers={"User-Agent": "laforge-bench/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        mark = 0
        with part.open("wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done - mark >= 80 * 1024 * 1024:
                    mark = done
                    pct = f"{100 * done // total}%" if total else "?"
                    print(f"[reranker] {done / 1e6:.0f}/{total / 1e6:.0f} MB ({pct})", flush=True)
    part.replace(DEST)
    print(f"[reranker] OK {DEST.stat().st_size / 1e6:.0f} MB en {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
