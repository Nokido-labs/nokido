"""forge_bench_questions.py — Question-set BEIR via llama.cpp Vulkan (:8091).

Etape 2. Genere ~N questions depuis sample.jsonl via NokidoLlamaNative (:8091,
qwen-coder 7B sur GPU/Vulkan) -- local, GPU, rapide, zero cle cloud. Produit
queries.jsonl + qrels.json (BEIR, single-gold). Tourne en trusted_script.

Run : run action=trusted_script path=tools/forge_bench_questions.py [N]
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "sandbox" / "rag_bench"
SAMPLE = BENCH / "sample.jsonl"
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
GEN_URL = "http://127.0.0.1:8091/v1/chat/completions"
HEALTH = "http://127.0.0.1:8091/health"
MIN_LEN, MAX_LEN = 250, 4000
PROMPT_CHARS = 1200

PROMPT = (
    "Voici un extrait de documentation technique. Genere UNE seule question "
    "factuelle et precise a laquelle cet extrait repond directement. La question "
    "doit etre autonome (comprehensible sans l'extrait). Reponds UNIQUEMENT la "
    "question.\n\n--- EXTRAIT ---\n{txt}"
)


def _wait_server(timeout: int = 150) -> bool:
    for _ in range(timeout // 3):
        try:
            with urllib.request.urlopen(HEALTH, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def _ask(text: str) -> str:
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": PROMPT.format(txt=text[:PROMPT_CHARS])}],
            "max_tokens": 80,
            "temperature": 0.3,
        }
    ).encode()
    req = urllib.request.Request(
        GEN_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"].strip()


def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit(f"[questions] {SAMPLE} absent")
    if not _wait_server():
        raise SystemExit("[questions] :8091 indisponible")
    chunks = [
        c
        for c in (json.loads(l) for l in SAMPLE.open(encoding="utf-8"))
        if MIN_LEN <= len(c["text"]) <= MAX_LEN
    ]
    step = max(1, len(chunks) // N)
    picked = chunks[::step][:N]
    print(f"[questions] :8091 ok, {len(chunks)} eligibles, {len(picked)} cibles", flush=True)

    qrels = {}
    ok = fail = 0
    t0 = time.time()
    with (BENCH / "queries.jsonl").open("w", encoding="utf-8") as qf:
        for i, c in enumerate(picked):
            try:
                q = _ask(c["text"]).split("\n")[0].strip().strip('"').strip()
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 3:
                    print(f"[questions] err: {type(e).__name__}: {str(e)[:130]}", flush=True)
                continue
            if not q or len(q) < 8:
                fail += 1
                continue
            qid = f"q{i:04d}"
            qf.write(json.dumps({"_id": qid, "text": q}, ensure_ascii=False) + "\n")
            qf.flush()
            qrels[qid] = {c["id"]: 1}
            ok += 1
            if ok % 30 == 0:
                print(f"[questions] {ok} ok / {fail} fail / {time.time() - t0:.0f}s", flush=True)
    (BENCH / "qrels.json").write_text(
        json.dumps(qrels, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[questions] TERMINE OK={ok} FAIL={fail} en {time.time() - t0:.0f}s")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
