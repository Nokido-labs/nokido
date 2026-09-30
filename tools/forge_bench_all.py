"""tools/forge_bench_all.py — Benchmark exhaustif providers LLM (locaux + cloud free).

Usage :
    LAFORGE_PYTHON tools/forge_bench_all.py [--quick|--full] [--prompt CODE|MATH|TEXT]

Tests :
- llama.cpp natif :8091 (target qwen 7B + draft 1.5B)
- llama-cpp-python :8090 (API only)
- Ollama tous modèles (load/unload auto)
- Cloud free tier : Groq, GitHub Models, OpenRouter (:free), Mistral, Gemini
  Lit les tokens depuis Nokido.env. Skippe si token absent.

Output : sandbox/bench_<date>.json + tableau ASCII rangé par tok/s.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Charger Nokido.env -----------------------------------------------------
ENV: dict[str, str] = {}
env_file = ROOT / "Nokido.env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip().strip('"').strip("'")


PROMPTS = {
    "CODE": "Write a Python function that performs BFS on a graph (adjacency list). Include short comments.",
    "MATH": "Compute step-by-step: (37 * 41) + (sqrt(144) * 7). Show your reasoning.",
    "TEXT": "Summarize the difference between sync and async I/O in 5 sentences.",
}


def post_json(
    url: str, body: dict, headers: dict, timeout: float = 60.0
) -> tuple[dict, float, str]:
    """Post JSON, retourne (response_json, latency_s, error_str)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={**headers, "Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
        return json.loads(txt), time.time() - t0, ""
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200] if e.fp else ""
        return {}, time.time() - t0, f"HTTP {e.code}: {body}"
    except Exception as e:
        return {}, time.time() - t0, f"{type(e).__name__}: {str(e)[:160]}"


def bench_openai_compat(
    name: str,
    url: str,
    model: str,
    prompt: str,
    api_key: str = "",
    max_tok: int = 200,
    extra_provider: str = "",
) -> dict:
    """Backend OpenAI-compat (llama.cpp, Ollama-via-/v1, Groq, OpenRouter, Mistral, GitHub Models)."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_provider:
        headers["HTTP-Referer"] = "https://nokido.local"
        headers["X-Title"] = "Nokido Bench"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok,
        "temperature": 0.2,
    }
    resp, lat, err = post_json(url, body, headers)
    if err:
        return {"name": name, "model": model, "ok": False, "err": err, "latency_s": round(lat, 2)}
    try:
        text = resp["choices"][0]["message"]["content"] or ""
        usage = resp.get("usage", {}) or {}
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", len(text) // 4)
        tps = round(out_tok / max(lat, 0.01), 1)
        return {
            "name": name,
            "model": model,
            "ok": True,
            "latency_s": round(lat, 2),
            "tokens_in": in_tok,
            "tokens_out": out_tok,
            "tok_per_s": tps,
            "preview": text[:120].replace("\n", " "),
        }
    except (KeyError, IndexError, TypeError) as e:
        return {
            "name": name,
            "model": model,
            "ok": False,
            "err": f"parse error: {e}: {str(resp)[:160]}",
            "latency_s": round(lat, 2),
        }


def bench_ollama_native(name: str, model: str, prompt: str, max_tok: int = 200) -> dict:
    """Ollama API native (/api/generate). Plus fiable que /v1 pour load/unload auto."""
    url = "http://127.0.0.1:11434/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tok, "temperature": 0.2},
    }
    resp, lat, err = post_json(url, body, {}, timeout=180.0)
    if err:
        return {"name": name, "model": model, "ok": False, "err": err, "latency_s": round(lat, 2)}
    text = resp.get("response", "")
    in_tok = resp.get("prompt_eval_count", 0)
    out_tok = resp.get("eval_count", 0)
    eval_dur_ns = resp.get("eval_duration", 0) or 1
    # tok/s pure inference (sans load model time)
    tps = round(out_tok / (eval_dur_ns / 1e9), 1) if out_tok and eval_dur_ns else 0
    return {
        "name": name,
        "model": model,
        "ok": True,
        "latency_s": round(lat, 2),
        "tokens_in": in_tok,
        "tokens_out": out_tok,
        "tok_per_s": tps,
        "preview": text[:120].replace("\n", " "),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="CODE", choices=list(PROMPTS.keys()))
    ap.add_argument("--max-tok", type=int, default=200)
    ap.add_argument("--quick", action="store_true", help="Skip cloud + heavy locals (32B, 14B)")
    ap.add_argument("--full", action="store_true", help="Tout y compris 32B/14B")
    ap.add_argument(
        "--out", default=None, help="JSON output path (default: sandbox/bench_<date>.json)"
    )
    args = ap.parse_args()

    prompt = PROMPTS[args.prompt]
    results: list[dict] = []

    # ---- LOCAL : llama.cpp natif :8091 ----
    print("=== llama.cpp natif :8091 ===", flush=True)
    r = bench_openai_compat(
        "llamacpp_native_8091",
        "http://127.0.0.1:8091/v1/chat/completions",
        "qwen",
        prompt,
        max_tok=args.max_tok,
    )
    results.append(r)
    print_row(r)

    # ---- LOCAL : llama-cpp-python :8090 ----
    print("=== llama-cpp-python :8090 ===", flush=True)
    r = bench_openai_compat(
        "llamacpp_python_8090",
        "http://127.0.0.1:8090/v1/chat/completions",
        "qwen",
        prompt,
        max_tok=args.max_tok,
    )
    results.append(r)
    print_row(r)

    # ---- LOCAL : Ollama (tous modèles) ----
    ollama_models = [
        ("ollama_qwen2.5_coder_1.5b", "qwen2.5-coder:1.5b"),
        ("ollama_qwen2.5_coder_7b", "qwen2.5-coder:latest"),
        ("ollama_nokido_qwen", "laforge-qwen:latest"),
        ("ollama_qwen3_8b", "qwen3:8b"),
        ("ollama_deepseek_coder_67", "deepseek-coder:6.7b"),
        ("ollama_gemma4_e4b", "gemma4:e4b-it-q4_K_M"),
    ]
    if not args.quick:
        ollama_models += [
            ("ollama_deepseek_r1_14b", "deepseek-r1:14b"),
        ]
    if args.full:
        ollama_models += [
            ("ollama_qwen2.5_coder_32b", "qwen2.5-coder:32b-instruct-q4_K_M"),
        ]
    for name, model in ollama_models:
        print(f"=== Ollama {model} ===", flush=True)
        r = bench_ollama_native(name, model, prompt, max_tok=args.max_tok)
        results.append(r)
        print_row(r)

    # ---- CLOUD FREE TIER ----
    if args.quick:
        print("\n[skipping cloud (--quick)]")
    else:
        print("\n=== CLOUD FREE TIERS ===", flush=True)

        # Groq (free tier généreux) — 4 modèles à tester
        if ENV.get("GROQ_API_KEY"):
            for name, model in [
                ("groq_llama_3.3_70b", "llama-3.3-70b-versatile"),
                ("groq_llama_3.1_8b", "llama-3.1-8b-instant"),
                ("groq_qwen3_32b", "qwen/qwen3-32b"),
                ("groq_kimi_k2", "moonshotai/kimi-k2-instruct"),
            ]:
                print(f"=== {name} ===", flush=True)
                r = bench_openai_compat(
                    name,
                    "https://api.groq.com/openai/v1/chat/completions",
                    model,
                    prompt,
                    ENV["GROQ_API_KEY"],
                    max_tok=args.max_tok,
                )
                results.append(r)
                print_row(r)

        # GitHub Models (free preview)
        if ENV.get("GITHUB_MODELS_TOKEN"):
            for name, model in [
                ("github_gpt41_mini", "openai/gpt-4.1-mini"),
                ("github_gpt4o_mini", "openai/gpt-4o-mini"),
                ("github_deepseek_v3", "deepseek/DeepSeek-V3-0324"),
                ("github_llama_70b", "meta/Llama-3.3-70B-Instruct"),
            ]:
                print(f"=== {name} ===", flush=True)
                r = bench_openai_compat(
                    name,
                    "https://models.github.ai/inference/chat/completions",
                    model,
                    prompt,
                    ENV["GITHUB_MODELS_TOKEN"],
                    max_tok=args.max_tok,
                )
                results.append(r)
                print_row(r)

        # OpenRouter (modèles :free)
        if ENV.get("OPENROUTER_API_KEY"):
            for name, model in [
                ("openrouter_qwen_coder_free", "qwen/qwen-2.5-coder-32b-instruct:free"),
                ("openrouter_llama_70b_free", "meta-llama/llama-3.3-70b-instruct:free"),
                ("openrouter_deepseek_v3_free", "deepseek/deepseek-chat:free"),
            ]:
                print(f"=== {name} ===", flush=True)
                r = bench_openai_compat(
                    name,
                    "https://openrouter.ai/api/v1/chat/completions",
                    model,
                    prompt,
                    ENV["OPENROUTER_API_KEY"],
                    max_tok=args.max_tok,
                    extra_provider="openrouter",
                )
                results.append(r)
                print_row(r)

        # Mistral (free tier)
        if ENV.get("MISTRAL_API_KEY"):
            for name, model in [
                ("mistral_small_free", "mistral-small-latest"),
            ]:
                print(f"=== {name} ===", flush=True)
                r = bench_openai_compat(
                    name,
                    "https://api.mistral.ai/v1/chat/completions",
                    model,
                    prompt,
                    ENV["MISTRAL_API_KEY"],
                    max_tok=args.max_tok,
                )
                results.append(r)
                print_row(r)

    # ---- Output ----
    out_path = (
        Path(args.out)
        if args.out
        else (ROOT / "sandbox" / f"bench_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "prompt": prompt,
                "prompt_label": args.prompt,
                "max_tokens": args.max_tok,
                "ts_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n→ JSON: {out_path}")

    # ---- Tableau résumé ranked ----
    print("\n" + "=" * 90)
    print(f"{'NAME':<35} {'tok/s':>8} {'lat(s)':>8} {'tok_out':>8}  STATUS")
    print("-" * 90)
    ok_results = [r for r in results if r.get("ok")]
    ok_results.sort(key=lambda r: r.get("tok_per_s", 0), reverse=True)
    for r in ok_results:
        tag = "🟢"
        print(
            f"{r['name']:<35} {r.get('tok_per_s', 0):>8} {r.get('latency_s', 0):>8} "
            f"{r.get('tokens_out', 0):>8}  {tag} {r.get('preview', '')[:25]}"
        )
    fails = [r for r in results if not r.get("ok")]
    for r in fails:
        print(
            f"{r['name']:<35} {'-':>8} {r.get('latency_s', 0):>8} {'-':>8}  🔴 {r.get('err', '')[:55]}"
        )
    return 0


def print_row(r: dict) -> None:
    if r.get("ok"):
        print(
            f"  ✓ {r.get('tok_per_s', 0)} tok/s  {r.get('latency_s', 0)}s  out={r.get('tokens_out', 0)}",
            flush=True,
        )
    else:
        print(f"  ✗ {r.get('err', '?')[:80]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
