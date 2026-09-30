"""Parse bench_v4 results — breakdown by prompt variant × model."""
import json
from pathlib import Path

p = Path(__file__).parent / "bench_v4_post_optims.json"
d = json.loads(p.read_text(encoding="utf-8"))

results = d["results"]["results"]
prompts_meta = d["results"]["prompts"]
print(f"Total results: {len(results)}")

# Aggregate by (provider, prompt_label)
agg = {}
for r in results:
    pid = r.get("provider", {}).get("label") or r.get("provider", {}).get("id", "?")
    plabel = (r.get("prompt") or {}).get("label", "?")
    key = (pid, plabel)
    if key not in agg:
        agg[key] = {"pass": 0, "total": 0, "lat_ms": [], "tok_in": [], "tok_out": []}
    agg[key]["total"] += 1
    if r.get("success"):
        agg[key]["pass"] += 1
    lat = r.get("latencyMs") or 0
    if lat:
        agg[key]["lat_ms"].append(lat)
    tok = (r.get("response") or {}).get("tokenUsage") or {}
    if tok.get("prompt"):
        agg[key]["tok_in"].append(tok.get("prompt"))
    if tok.get("completion"):
        agg[key]["tok_out"].append(tok.get("completion"))

def avg(lst):
    return round(sum(lst) / max(len(lst), 1), 1)

print(f"\n{'Provider':30} {'Prompt':25} {'Pass':>6} {'Lat ms':>8} {'In tok':>8} {'Out tok':>8}")
print("-" * 90)
for (pid, plabel), m in sorted(agg.items()):
    pct = round(m["pass"] / max(m["total"], 1) * 100, 0)
    print(f"{pid[:30]:30} {plabel[:25]:25} {m['pass']:>2}/{m['total']:<2} ({pct:>3.0f}%) "
          f"{avg(m['lat_ms']):>8} {avg(m['tok_in']):>8} {avg(m['tok_out']):>8}")

# Top variant by model
print("\n=== Best variant per provider ===")
by_provider = {}
for (pid, plabel), m in agg.items():
    by_provider.setdefault(pid, []).append((plabel, m))
for pid, variants in by_provider.items():
    best = max(variants, key=lambda x: x[1]["pass"])
    print(f"  {pid}: {best[0]} ({best[1]['pass']}/{best[1]['total']})")
