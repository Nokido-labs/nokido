"""Parse bench_v5 results — multi-provider summary + winners/losers."""
import json
import sys
from pathlib import Path

if len(sys.argv) > 1:
    p = Path(sys.argv[1])
else:
    # Most recent bench_v5_*.json
    matches = sorted(Path(__file__).parent.glob("bench_v5_*.json"), reverse=True)
    if not matches:
        print("No bench_v5_*.json found")
        sys.exit(1)
    p = matches[0]

print(f"Reading: {p.name}\n")
d = json.loads(p.read_text(encoding="utf-8"))

results = d["results"]["results"]
print(f"Total results: {len(results)}\n")

# Aggregate by (provider, prompt_label)
agg = {}
errors_429 = []
errors_other = []

for r in results:
    pid = r.get("provider", {}).get("label") or r.get("provider", {}).get("id", "?")
    plabel = (r.get("prompt") or {}).get("label", "?")
    key = (pid, plabel)
    if key not in agg:
        agg[key] = {"pass": 0, "total": 0, "lat_ms": [], "tok_in": [], "tok_out": [], "errors": 0}
    agg[key]["total"] += 1
    if r.get("success"):
        agg[key]["pass"] += 1
    err = r.get("error")
    if err:
        agg[key]["errors"] += 1
        if "429" in str(err) or "rate" in str(err).lower():
            errors_429.append((pid, str(err)[:120]))
        else:
            errors_other.append((pid, str(err)[:120]))
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


print(f"{'Provider':25} {'Prompt':28} {'Pass':>10} {'Lat ms':>9} {'In tok':>8} {'Out tok':>8} {'Err':>4}")
print("-" * 95)
total_pass = 0
total_n = 0
for (pid, plabel), m in sorted(agg.items()):
    pct = round(m["pass"] / max(m["total"], 1) * 100, 0)
    print(
        f"{pid[:25]:25} {plabel[:28]:28} {m['pass']:>3}/{m['total']:<3} ({pct:>3.0f}%) "
        f"{avg(m['lat_ms']):>8} {avg(m['tok_in']):>8} {avg(m['tok_out']):>8} {m['errors']:>4}"
    )
    total_pass += m["pass"]
    total_n += m["total"]

print("-" * 95)
print(f"GRAND TOTAL: {total_pass}/{total_n} ({round(total_pass/max(total_n,1)*100,1)}%)\n")

# Per-provider rollup (across all 3 prompts)
print("=== Per-provider rollup ===")
prov = {}
for (pid, plabel), m in agg.items():
    if pid not in prov:
        prov[pid] = {"pass": 0, "total": 0, "lat": [], "tok_out": [], "errors": 0}
    prov[pid]["pass"] += m["pass"]
    prov[pid]["total"] += m["total"]
    prov[pid]["lat"].extend(m["lat_ms"])
    prov[pid]["tok_out"].extend(m["tok_out"])
    prov[pid]["errors"] += m["errors"]

prov_list = []
for pid, m in prov.items():
    pct = round(m["pass"] / max(m["total"], 1) * 100, 1)
    prov_list.append({
        "id": pid, "pass": m["pass"], "total": m["total"], "pct": pct,
        "lat": avg(m["lat"]), "tok_out": avg(m["tok_out"]), "errors": m["errors"]
    })

print(f"\n{'Provider':25} {'Pass rate':>14} {'Avg lat ms':>12} {'Out tok':>9} {'Errors':>7}")
print("-" * 75)
for x in sorted(prov_list, key=lambda y: -y["pct"]):
    print(f"{x['id'][:25]:25} {x['pass']:>3}/{x['total']:<3} ({x['pct']:>4.1f}%) {x['lat']:>11} {x['tok_out']:>9} {x['errors']:>7}")

# Top 3 winners by score
print("\n=== Top 3 winners (highest pass rate) ===")
for x in sorted(prov_list, key=lambda y: (-y["pct"], y["lat"]))[:3]:
    print(f"  {x['id']:25} {x['pct']:>5.1f}% lat={x['lat']}ms tok_out={x['tok_out']}")

# Top 3 losers
print("\n=== Top 3 losers (lowest pass rate) ===")
for x in sorted(prov_list, key=lambda y: (y["pct"], -y["lat"]))[:3]:
    print(f"  {x['id']:25} {x['pct']:>5.1f}% lat={x['lat']}ms tok_out={x['tok_out']} errors={x['errors']}")

# Errors
print(f"\n=== Errors ===")
print(f"  429/rate-limit: {len(errors_429)}")
for pid, e in errors_429[:5]:
    print(f"    {pid}: {e}")
print(f"  Other:          {len(errors_other)}")
for pid, e in errors_other[:5]:
    print(f"    {pid}: {e}")
