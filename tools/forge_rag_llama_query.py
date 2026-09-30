"""
forge_rag_llama_query.py - RAG -> llama-server inference, standalone.

Pipeline:
  1. Encode query via brain_worker ZMQ :5557 (BGE-M3 1024D)
  2. Retrieve top-k chunks via forge_rag_engine (FAISS + BM25 + RRF)
  3. Compose prompt avec context injected
  4. POST llama-server :8091 /v1/chat/completions, Bearer token via DPAPI vault

Pre-requis (standalone, sans supervisor) :
  - llama-server isolated wrapper UP sur :8091 (tools/nokido_llamacpp_native.bat)
  - brain_worker isolated UP sur :5557 (tools/forge_embed_worker_isolated.py)
  - vault key FORGE_LLAMA_KEY (forge_machine_vault.vault_set)

Usage :
  LAFORGE_PYTHON tools/forge_rag_llama_query.py "ma question" [--top-k 5] [--max-tokens 512]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import msgpack  # type: ignore
import zmq  # type: ignore
from nokido_agent.app.forge_secrets import get_secret  # type: ignore


def embed_query(text: str, timeout_s: float = 15.0) -> list[float]:
    """BGE-M3 1024D via brain_worker ZMQ :5557 (protocole CLAUDE.md §13)."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.connect("tcp://127.0.0.1:5557")
    try:
        sock.send(
            msgpack.packb(
                {"cmd": "submit", "type": "embed", "texts": [text]},
                use_bin_type=True,
            )
        )
        if not sock.poll(int(timeout_s * 1000)):
            raise TimeoutError("submit timeout")
        rep = msgpack.unpackb(sock.recv(), raw=False)
        task_id = rep["task_id"]

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
            if not sock.poll(5000):
                raise TimeoutError("check timeout")
            res = msgpack.unpackb(sock.recv(), raw=False)
            status = res.get("status", "pending")
            if status == "completed":
                data = res.get("data")
                if isinstance(data, dict):
                    vecs = data.get("vecs", [])
                elif isinstance(data, list):
                    vecs = data
                else:
                    vecs = []
                if not vecs:
                    raise RuntimeError("empty embedding")
                return list(vecs[0])
            if status == "error":
                raise RuntimeError(res.get("error", "embed error"))
            time.sleep(0.3)
        raise TimeoutError("embed loop timeout")
    finally:
        sock.setsockopt(zmq.RCVTIMEO, 500)
        try:
            sock.close()
        except Exception:
            pass


def rag_search(query: str, top_k: int) -> list[dict]:
    """Hybrid search via forge_self_correction.preflight_check_verbose
    (RAGEngine -> FTS5 -> LIKE cascade, auto-init settings)."""
    from nokido_agent.app.forge_self_correction import preflight_check_verbose  # type: ignore

    v = preflight_check_verbose(query, "", limit=top_k)
    out = []
    for r in v.get("results", []):
        out.append(
            {
                "score": r.get("score", 0.0),
                "source": r.get("source", ""),
                "text": (r.get("preview") or "")[:1200],
                "tier": v.get("tier", "?"),
            }
        )
    return out


def compose_prompt(query: str, chunks: list[dict]) -> list[dict]:
    ctx_lines = []
    for i, c in enumerate(chunks, 1):
        ctx_lines.append(f"[{i}] ({c['source']})\n{c['text']}\n")
    context_block = "\n".join(ctx_lines) if ctx_lines else "(aucun contexte RAG)"
    system = (
        "Tu es un assistant Nokido. Reponds en t'appuyant exclusivement sur le "
        "contexte RAG fourni. Si le contexte ne contient pas la reponse, dis-le."
    )
    user = f"Contexte RAG :\n{context_block}\n\nQuestion : {query}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_llama(messages: list[dict], max_tokens: int = 512, temperature: float = 0.3) -> str:
    api_key = get_secret("FORGE_LLAMA_KEY") or get_secret("FORGE_LLAMA_KEY") or ""
    if not api_key:
        raise RuntimeError("FORGE_LLAMA_KEY introuvable (vault + env)")
    url = os.environ.get("LLAMACPP_URL", "http://127.0.0.1:8091") + "/v1/chat/completions"
    payload = {
        "model": "laforge-coder",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("query", help="Question utilisateur")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--json", action="store_true", help="Sortie JSON (debug)")
    args = p.parse_args(argv)

    t0 = time.monotonic()
    print("[1/4] embed query (BGE-M3 :5557)...", file=sys.stderr)
    _ = embed_query(args.query)  # warm path; RAGEngine refait son propre embed dedans
    print(f"      ok ({round(time.monotonic() - t0, 2)}s)", file=sys.stderr)

    t1 = time.monotonic()
    print(f"[2/4] rag search top-k={args.top_k}...", file=sys.stderr)
    chunks = rag_search(args.query, args.top_k)
    print(f"      {len(chunks)} chunks ({round(time.monotonic() - t1, 2)}s)", file=sys.stderr)

    print("[3/4] compose prompt...", file=sys.stderr)
    messages = compose_prompt(args.query, chunks)

    t2 = time.monotonic()
    print(f"[4/4] call llama :8091 (max_tokens={args.max_tokens})...", file=sys.stderr)
    answer = call_llama(messages, max_tokens=args.max_tokens, temperature=args.temperature)
    print(
        f"      ok ({round(time.monotonic() - t2, 2)}s, total {round(time.monotonic() - t0, 2)}s)",
        file=sys.stderr,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "query": args.query,
                    "chunks": chunks,
                    "answer": answer,
                    "elapsed_s": round(time.monotonic() - t0, 2),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
