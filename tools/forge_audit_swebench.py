#!/usr/bin/env python
"""forge_audit_swebench.py — éval grounded de ForgeAudit (ultrareview) via SWE-bench.

Méthode : les instances SWE-bench sont des bugs RÉELS avec patch humain (gold) =
vérité-terrain. Pour chaque instance :
  1. clone du repo @base_commit (état BUGGÉ, pré-fix).
  2. parse du gold-patch → fichiers + lignes OLD (= où vit le bug).
  3. enclosing_targets() → symboles que le fix humain a touchés (gold_syms).
  4. run_forge_audit() sur ces fichiers (reviewer read-only, 0 modif).
  5. HIT = un finding gardé dont le symbol_target ∈ gold_syms (match lenient).

Métriques :
  - localization_hit_rate = hits / instances  (le reviewer pointe le bon symbole ?)
  - precision_proxy       = findings gardés / (gardés + jetés)  (anti-hallucination)
  - avg_findings, avg_dropped

NB : read-only, aucune modif de repo. Réutilise ensure_dataset/_clone_repo du
runner SWE-bench (anti-dup). Lance via pwsh C:\\tmp\\audit_swebench_run.ps1
(session user : réseau pour clone + ollama local).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_HERE), str(_ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- briques réutilisées (anti-dup) -----------------------------------------
from nokido_agent.tools.forge_swebench_runner import ensure_dataset, _clone_repo, SWE_DIR  # noqa: E402
from nokido_agent.app.forge_audit import enclosing_targets, run_forge_audit  # noqa: E402
from nokido_agent.app.forge_audit_reducer import symbol_matches  # noqa: E402
from nokido_agent.app.forge_local_inference_pool import (  # noqa: E402
    LocalInferencePool, LensRoutedPool, DEFAULT_LENS_ROUTE,
    CLOUD_LENS_ROUTE, HYBRID_LENS_ROUTE, make_cloud_remote_fn,
)

try:
    from tqdm import tqdm  # noqa: E402
except Exception:  # pragma: no cover
    def tqdm(x, **k):
        return x

_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def gold_old_lines(patch: str) -> dict[str, set[int]]:
    """Gold-patch → {fichier.py: {lignes OLD touchées}}. Côté OLD = état buggé.

    Pour chaque hunk : ancre la ligne de départ (localise même les ajouts purs)
    + marque chaque ligne '-' (suppression = code buggé directement visé)."""
    files: dict[str, set[int]] = {}
    cur: str | None = None
    old_ln: int | None = None
    for line in patch.splitlines():
        if line.startswith("--- "):
            m = re.match(r"--- a/(.+)", line) or re.match(r"--- (.+)", line)
            cur = m.group(1).strip() if m else None
            old_ln = None
        elif line.startswith("+++ "):
            continue
        elif line.startswith("@@"):
            m = _HUNK.search(line)
            if m and cur and cur.endswith(".py"):
                old_ln = int(m.group(1))
                files.setdefault(cur, set()).add(old_ln)  # ancre du hunk
            else:
                old_ln = None
        elif cur and old_ln is not None and cur.endswith(".py"):
            if line.startswith("-") and not line.startswith("---"):
                files.setdefault(cur, set()).add(old_ln)
                old_ln += 1
            elif line.startswith("+"):
                pass  # ajout : côté NEW only, n'avance pas OLD
            else:
                old_ln += 1  # contexte
    return files


def _bus_emit(enabled: bool):
    if not enabled:
        return None
    try:
        from nokido_agent.app.forge_swarm_bus import publish
    except Exception:
        return None

    def _e(kind, data):
        try:
            publish(kind, data, topic="audit")
        except Exception:
            pass

    return _e


async def _audit_instance(inst: dict, work_dir: Path, lenses, pool, emit) -> dict | None:
    iid = inst.get("instance_id", "?")
    repo = inst.get("repo", "")
    base = inst.get("base_commit", "")
    patch = inst.get("patch", "") or ""
    gold = gold_old_lines(patch)
    py_files = [f for f in gold if "/test" not in f and not Path(f).name.startswith("test_")]
    if not py_files:
        return {"instance_id": iid, "skipped": "no_py_source_in_gold"}

    repo_path = _clone_repo(repo, base, work_dir)
    if repo_path is None:
        return {"instance_id": iid, "skipped": "clone_failed"}

    # symboles que le fix humain a touchés, par fichier
    gold_syms: dict[str, list[str]] = {}
    present = []
    for f in py_files:
        if (repo_path / f).exists():
            gold_syms[f] = enclosing_targets(f, gold[f], str(repo_path))
            present.append(f)
    if not present:
        return {"instance_id": iid, "skipped": "gold_files_absent_at_base"}

    rep = await run_forge_audit(present, str(repo_path), lenses=lenses, pool=pool, emit=emit)
    kept = rep["kept"]

    # HIT par fichier : un finding sur un symbole que l'humain a corrigé
    hit_files = []
    for f in present:
        gset = set(gold_syms[f])
        fsyms = [k.get("symbol_target", "") for k in kept if k.get("file") == f]
        if any(symbol_matches(s, gset) for s in fsyms):
            hit_files.append(f)

    return {
        "instance_id": iid,
        "repo": repo,
        "files": present,
        "gold_syms": gold_syms,
        "n_findings": len(kept),
        "n_dropped": rep["dropped"],
        "hit": bool(hit_files),
        "hit_files": hit_files,
        "findings": [
            {"file": k.get("file"), "symbol": k.get("symbol_target"),
             "lens": k.get("lens"), "sev": k.get("severity"), "issue": k.get("issue", "")[:160]}
            for k in kept
        ],
    }


async def _run(args) -> dict:
    insts = ensure_dataset(args.split, args.variant)[: args.max]
    lenses = [s.strip() for s in args.lenses.split(",") if s.strip()]
    if args.remote or args.hybrid:
        route = HYBRID_LENS_ROUTE if args.hybrid else CLOUD_LENS_ROUTE
        base = LocalInferencePool(prefer="ollama", max_parallel=args.parallel)
        base.backends = {"ollama": base.backends["ollama"]}
        pool = LensRoutedPool(route=route, base=base, remote_fn=make_cloud_remote_fn(public=args.public))
        mode = "HYBRIDE local+distant" if args.hybrid else "DISTANT cloud (cerebras/groq)"
        print(f"[pool] {mode} — route={ {k: route.get(k) for k in lenses} }", flush=True)
    elif args.swarm:
        base = LocalInferencePool(prefer="ollama", max_parallel=args.parallel)
        base.backends = {"ollama": base.backends["ollama"]}  # ollama-only : pas de fallback llamacpp poison (non-GBNF)
        pool = LensRoutedPool(base=base)  # routage/ensemble local par lens
        print(f"[pool] swarm souverain multi-modèle — route={ {k: DEFAULT_LENS_ROUTE[k] for k in lenses if k in DEFAULT_LENS_ROUTE} }", flush=True)
    else:
        pool = LocalInferencePool(prefer=args.prefer, max_parallel=args.parallel)
    work_dir = SWE_DIR / "repos"
    work_dir.mkdir(parents=True, exist_ok=True)
    emit = _bus_emit(args.emit)

    rows = []
    for inst in tqdm(insts, desc="audit-swebench"):
        try:
            r = await _audit_instance(inst, work_dir, lenses, pool, emit)
        except Exception as e:  # noqa: BLE001
            r = {"instance_id": inst.get("instance_id", "?"), "error": f"{type(e).__name__}: {e}"}
        if r:
            rows.append(r)
            tag = "HIT " if r.get("hit") else ("skip" if r.get("skipped") else ("ERR " if r.get("error") else "miss"))
            print(f"  [{tag}] {r['instance_id']}  findings={r.get('n_findings', 0)} dropped={r.get('n_dropped', 0)}"
                  + (f"  {r.get('skipped') or r.get('error')}" if (r.get('skipped') or r.get('error')) else ""), flush=True)

    scored = [r for r in rows if "hit" in r]
    hits = sum(1 for r in scored if r["hit"])
    tot_keep = sum(r["n_findings"] for r in scored)
    tot_drop = sum(r["n_dropped"] for r in scored)
    _route = (CLOUD_LENS_ROUTE if args.remote else HYBRID_LENS_ROUTE if args.hybrid
              else DEFAULT_LENS_ROUTE if args.swarm else None)
    summary = {
        "variant": args.variant, "split": args.split, "lenses": lenses, "prefer": args.prefer,
        "mode": "remote" if args.remote else ("hybrid" if args.hybrid else ("swarm" if args.swarm else "solo")),
        "route": {k: _route.get(k) for k in lenses} if _route else None,
        "instances_total": len(rows),
        "instances_scored": len(scored),
        "skipped": sum(1 for r in rows if r.get("skipped")),
        "errors": sum(1 for r in rows if r.get("error")),
        "hits": hits,
        "localization_hit_rate": round(hits / len(scored), 3) if scored else None,
        "avg_findings": round(tot_keep / len(scored), 2) if scored else None,
        "avg_dropped": round(tot_drop / len(scored), 2) if scored else None,
        "precision_proxy": round(tot_keep / (tot_keep + tot_drop), 3) if (tot_keep + tot_drop) else None,
    }
    out = {"summary": summary, "rows": rows}
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # évite UnicodeEncodeError cp1252 sur → ✅
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="ForgeAudit (ultrareview) éval via SWE-bench ground-truth")
    ap.add_argument("--variant", choices=["lite", "verified", "live"], default="verified")
    ap.add_argument("--split", choices=["test", "dev"], default="test")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--lenses", default="security,correctness")
    ap.add_argument("--prefer", default="ollama", help="backend pool préféré (ollama|llamacpp)")
    ap.add_argument("--swarm", action="store_true", help="swarm souverain LOCAL multi-modèle (ollama)")
    ap.add_argument("--remote", action="store_true", help="tier DISTANT cloud (cerebras/groq via firewall+vault) — rapide+fort")
    ap.add_argument("--hybrid", action="store_true", help="hybride : lens dure→cloud, reste→local")
    ap.add_argument("--public", action="store_true", help="code open-source → skip redaction DLP faux-positive (véto injection/ring conservé)")
    ap.add_argument("--parallel", type=int, default=2, help="concurrence pool (mettre 1 avec --swarm/32b pour la RAM)")
    ap.add_argument("--emit", action="store_true", help="publier les events sur le swarm-bus (UI web)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import asyncio
    t0 = time.time()
    out = asyncio.run(_run(args))
    out["summary"]["elapsed_s"] = round(time.time() - t0, 1)

    dest = Path(args.out) if args.out else (SWE_DIR / f"audit_eval_{args.variant}_{args.split}_{args.max}.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    s = out["summary"]
    print("\n" + "=" * 60)
    print(f"ForgeAudit × SWE-bench  ({s['variant']}/{s['split']}, lenses={s['lenses']})")
    print(f"  scored={s['instances_scored']}/{s['instances_total']}  skip={s['skipped']} err={s['errors']}")
    print(f"  localization_hit_rate = {s['localization_hit_rate']}  ({s['hits']} hits)")
    print(f"  avg_findings={s['avg_findings']}  avg_dropped={s['avg_dropped']}  precision_proxy={s['precision_proxy']}")
    print(f"  elapsed={s['elapsed_s']}s  →  {dest}")
    print("=" * 60)


if __name__ == "__main__":
    main()
