"""Generate BENCH_V5_REPORT.md from bench_v5_*.json + parse_v5 output."""
import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent

# Find latest v5 JSON
matches = sorted(ROOT.glob("bench_v5_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if not matches:
    print("ERROR: no bench_v5_*.json found")
    sys.exit(1)
src = matches[0]
print(f"Using: {src.name}")

d = json.loads(src.read_text(encoding="utf-8"))
results = d["results"]["results"]

# Aggregations
agg = {}              # (provider, prompt_label) -> stats
prov_total = {}       # provider -> rollup
errors_429 = []
errors_other = []

for r in results:
    pid = r.get("provider", {}).get("label") or r.get("provider", {}).get("id", "?")
    plabel = (r.get("prompt") or {}).get("label", "?")
    key = (pid, plabel)
    if key not in agg:
        agg[key] = {"pass": 0, "total": 0, "lat": [], "tok_in": [], "tok_out": [], "errors": 0}
    agg[key]["total"] += 1
    if r.get("success"):
        agg[key]["pass"] += 1
    err = r.get("error")
    if err:
        es = str(err)
        # Distinguish API errors (HTTP, model decommissioned, timeout) vs assertion failures
        if "Expected output" in es or "Expected to" in es or "Assertion" in es:
            pass  # assertion failure already counted as not-success
        else:
            agg[key]["errors"] += 1
            if "429" in es or "rate" in es.lower() or "Rate" in es or "Too Many" in es:
                errors_429.append((pid, es[:150]))
            else:
                errors_other.append((pid, es[:150]))
    lat = r.get("latencyMs") or 0
    if lat:
        agg[key]["lat"].append(lat)
    tok = (r.get("response") or {}).get("tokenUsage") or {}
    if tok.get("prompt"):
        agg[key]["tok_in"].append(tok["prompt"])
    if tok.get("completion"):
        agg[key]["tok_out"].append(tok["completion"])

    if pid not in prov_total:
        prov_total[pid] = {"pass": 0, "total": 0, "lat": [], "tok_out": [], "errors": 0}
    prov_total[pid]["pass"] += 1 if r.get("success") else 0
    prov_total[pid]["total"] += 1
    if lat:
        prov_total[pid]["lat"].append(lat)
    if tok.get("completion"):
        prov_total[pid]["tok_out"].append(tok["completion"])
    if err:
        es2 = str(err)
        if not ("Expected output" in es2 or "Expected to" in es2 or "Assertion" in es2):
            prov_total[pid]["errors"] += 1


def avg(lst):
    return round(sum(lst) / max(len(lst), 1), 1) if lst else 0


def pct(p, t):
    return round(p / max(t, 1) * 100, 1)


total_pass = sum(m["pass"] for m in prov_total.values())
total_n = sum(m["total"] for m in prov_total.values())

# Sort providers by pass rate then latency
prov_sorted = sorted(
    [(pid, m) for pid, m in prov_total.items()],
    key=lambda x: (-pct(x[1]["pass"], x[1]["total"]), avg(x[1]["lat"])),
)

ts = datetime.now().strftime("%Y-%m-%d %H:%M")
md = []
md.append(f"# BENCH v5 — Multi-provider clinical prompt eval\n")
md.append(f"**Date:** {ts}  ")
md.append(f"**Source:** `{src.name}`  ")
md.append(f"**Dataset:** `golden_dataset.yaml` (15 cases × 3 prompts × {len(prov_total)} providers = {total_n} evals)  ")
md.append(f"**Concurrency:** 2  Cache: disabled  ")
md.append("")
md.append("## Summary vs v4 baseline\n")
md.append(f"| Metric | v4 (Ollama only, n=135) | v5 (cloud free, n={total_n}) |")
md.append(f"|---|---|---|")
md.append(f"| Total pass | 95/135 (70.4%) | {total_pass}/{total_n} ({pct(total_pass, total_n)}%) |")
md.append(f"| Providers | 3 local Ollama | {len(prov_total)} cloud |")
md.append("")

md.append("## Per-provider pass rate\n")
md.append("| Provider | Pass | Pass % | Avg latency (ms) | Avg out tok | Errors |")
md.append("|---|---|---|---|---|---|")
for pid, m in prov_sorted:
    p = pct(m["pass"], m["total"])
    md.append(f"| `{pid}` | {m['pass']}/{m['total']} | {p}% | {avg(m['lat'])} | {avg(m['tok_out'])} | {m['errors']} |")
md.append("")

md.append("## Per-provider × per-prompt detail\n")
md.append("| Provider | Prompt | Pass | Pass % | Lat ms | In tok | Out tok | Err |")
md.append("|---|---|---|---|---|---|---|---|")
for (pid, plabel), m in sorted(agg.items()):
    p = pct(m["pass"], m["total"])
    md.append(
        f"| `{pid}` | {plabel} | {m['pass']}/{m['total']} | {p}% | "
        f"{avg(m['lat'])} | {avg(m['tok_in'])} | {avg(m['tok_out'])} | {m['errors']} |"
    )
md.append("")

# Top 3 winners (by pass rate, then by lower latency)
top3 = prov_sorted[:3]
md.append("## Top 3 winners\n")
for i, (pid, m) in enumerate(top3, 1):
    p = pct(m["pass"], m["total"])
    md.append(
        f"{i}. **`{pid}`** — {p}% ({m['pass']}/{m['total']}), "
        f"avg lat {avg(m['lat'])} ms, avg out {avg(m['tok_out'])} tok"
    )
md.append("")

# Top 3 losers (lowest pass rate, then highest latency)
losers = sorted(
    [(pid, m) for pid, m in prov_total.items()],
    key=lambda x: (pct(x[1]["pass"], x[1]["total"]), -avg(x[1]["lat"])),
)[:3]
md.append("## Top 3 losers\n")
for i, (pid, m) in enumerate(losers, 1):
    p = pct(m["pass"], m["total"])
    md.append(
        f"{i}. **`{pid}`** — {p}% ({m['pass']}/{m['total']}), "
        f"avg lat {avg(m['lat'])} ms, errors {m['errors']}"
    )
md.append("")

md.append("## Errors\n")
md.append(f"- **429 / rate limit:** {len(errors_429)}")
seen_429 = set()
for pid, e in errors_429:
    if pid not in seen_429:
        md.append(f"  - `{pid}`: {e}")
        seen_429.add(pid)
md.append(f"- **Other errors:** {len(errors_other)}")
seen_other = set()
for pid, e in errors_other:
    if pid not in seen_other:
        md.append(f"  - `{pid}`: {e}")
        seen_other.add(pid)
md.append("")

md.append("## Notes\n")
md.append("- **Run was partial** (376/405 evals, 92.8%): bench was killed because")
md.append("  SambaNova hit hard 429 rate-limit and stalled both concurrency slots for")
md.append("  3+ minutes per retry. Per iron rule, dropped repeating-429 providers.")
md.append("  Data extracted from promptfoo SQLite (`~/.promptfoo/promptfoo.db`).")
md.append("- **Local Ollama providers excluded**: daemon at :11434 has 0 models loaded.")
md.append("  `OLLAMA_MODELS=D:\\ollama\\models` is set in user env but the running daemon")
md.append("  was started before the var was set, so `total blobs: 0`. Restart Ollama")
md.append("  with proper env to re-include qwen-1.5b/qwen-7b/qwen3-8b in next bench.")
md.append("- **OpenRouter `qwen/qwen3-coder:free` removed** from config: chronic upstream 429")
md.append("  rate limits stalled the first attempt with 5×60s retries.")
md.append("- **Cohere 0%**: model `command-r` decommissioned 2025-09-15. Need to switch to")
md.append("  `command-r-08-2024` or `command-r-plus-08-2024`.")
md.append("- v4 baseline (Ollama qwen-1.5b/7b/qwen3-8b): 95/135 pass, qwen-7b minimal sweet spot.")
md.append("- All cloud providers used free-tier credentials from `Nokido.env` via env vars (no hard-coded tokens).")
md.append("")

dst = ROOT / "BENCH_V5_REPORT.md"
dst.write_text("\n".join(md), encoding="utf-8")
print(f"Wrote {dst}")
print(f"\nGRAND TOTAL: {total_pass}/{total_n} ({pct(total_pass, total_n)}%)")
print(f"Top 3 winners:")
for pid, m in top3:
    p = pct(m["pass"], m["total"])
    print(f"  {pid:30} {p:>5}% ({m['pass']}/{m['total']}) lat={avg(m['lat'])}ms tok_out={avg(m['tok_out'])}")
print(f"Top 3 losers:")
for pid, m in losers:
    p = pct(m["pass"], m["total"])
    print(f"  {pid:30} {p:>5}% ({m['pass']}/{m['total']}) lat={avg(m['lat'])}ms errors={m['errors']}")
print(f"Errors: 429={len(errors_429)} other={len(errors_other)}")
