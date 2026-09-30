"""tools/forge_swebench_repo_cache.py - pre-calc + cache repo_map des repos cibles SWE-bench.

Probleme : chaque LATS backtrack (depth 2+, refine) re-construit le repo_map
des 2000+ fichiers astropy/django/etc. = des minutes de waste. Pre-calc une
fois, cache disque, re-use.

Strategie :
  - <swebench_cache_dir()>/<instance_id>/   (SWEBENCH_CACHE_DIR, sinon sandbox/workspace/swebench_cache)
    ├── repo_map.json          (build_repo_map serialise complet)
    ├── repo_map.md            (markdown render pour LLM)
    ├── domain_maps/           (partition par sous-dossier top-level)
    │   ├── map_<sub1>.json
    │   └── map_<sub2>.json
    ├── manifest.json          (base_commit + ts + symbol_count + repo)
    └── repo/                  (clone shallow, reutilise par lats_runner)

API :
  - prepare_instance(inst) -> dict {cached: bool, repo_path, map_path, ...}
  - load_cached_map(instance_id) -> dict | None
  - load_cached_markdown(instance_id) -> str | None
  - clear_cache(instance_id) -> None

CLI :
  LAFORGE_PYTHON tools/forge_swebench_repo_cache.py --variant lite --max 20
  -> pre-build cache pour 20 instances (utile a lancer 1x avant un swarm run)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_repo_map import build_repo_map, render_markdown, symbols_to_jsonl  # noqa: E402
from nokido_agent.tools.forge_swebench_runner import ensure_dataset  # noqa: E402

from nokido_agent.app.forge_benchmark_adapter import swebench_cache_dir  # noqa: E402

# HORS de RAG/ depuis le 2026-09-27 (decision owner) : resolveur unique.
CACHE_ROOT = swebench_cache_dir()
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _instance_cache_dir(instance_id: str) -> Path:
    safe = instance_id.replace("/", "_")
    return CACHE_ROOT / safe


def _clone_or_reuse(inst: dict, cache_dir: Path) -> Path | None:
    """Clone le repo dans cache_dir/repo si pas deja. Checkout base_commit."""
    repo_path = cache_dir / "repo"
    manifest = cache_dir / "manifest.json"
    # Si manifest existe ET base_commit matche -> reuse
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            if m.get("base_commit") == inst.get("base_commit") and repo_path.exists():
                return repo_path
        except (json.JSONDecodeError, OSError):
            pass
    # Clone neuf
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)
    url = f"https://github.com/{inst['repo']}"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", url, str(repo_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        errors="replace")
        subprocess.run(
            ["git", "checkout", "-q", inst["base_commit"]],
            cwd=str(repo_path),
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        errors="replace")
        return repo_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [clone] FAIL {inst['repo']}@{inst['base_commit'][:8]}: {e}")
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
        return None


def _build_and_save_maps(
    repo_path: Path, cache_dir: Path, instance_id: str, base_commit: str, repo_name: str
) -> dict:
    """Build full repo_map + domain-partitioned maps + markdown."""
    t0 = time.monotonic()
    full = build_repo_map(repo_path, max_files=5000)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Serialize full
    symbols_to_jsonl(full, cache_dir / "repo_map.jsonl")
    md = render_markdown(full, max_chars=50000)
    (cache_dir / "repo_map.md").write_text(md, encoding="utf-8")
    # Partition par top-level subdir
    domains_dir = cache_dir / "domain_maps"
    domains_dir.mkdir(exist_ok=True)
    by_top: dict[str, list] = {}
    for s in full["symbols"]:
        top = s.file.split("/")[0] if "/" in s.file else "_root_"
        by_top.setdefault(top, []).append(s)
    for top, syms in by_top.items():
        sub_map = {"root": full["root"], "files": len({s.file for s in syms}), "symbols": syms}
        symbols_to_jsonl(sub_map, domains_dir / f"map_{top}.jsonl")
    # Manifest
    manifest = {
        "instance_id": instance_id,
        "repo": repo_name,
        "base_commit": base_commit,
        "built_at": time.time(),
        "files": full["files"],
        "symbols": len(full["symbols"]),
        "domains": sorted(by_top.keys()),
        "elapsed_s": round(time.monotonic() - t0, 1),
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def prepare_instance(inst: dict, force_rebuild: bool = False) -> dict:
    """Clone + build repo_map + cache. Idempotent : skip si deja cache et
    base_commit identique (sauf force_rebuild)."""
    iid = inst["instance_id"]
    cache_dir = _instance_cache_dir(iid)
    manifest_path = cache_dir / "manifest.json"
    if manifest_path.exists() and not force_rebuild:
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            if m.get("base_commit") == inst.get("base_commit"):
                return {"cached": True, "manifest": m, "cache_dir": str(cache_dir)}
        except json.JSONDecodeError:
            pass
    repo_path = _clone_or_reuse(inst, cache_dir)
    if repo_path is None:
        return {"cached": False, "error": "clone_failed", "cache_dir": str(cache_dir)}
    try:
        manifest = _build_and_save_maps(
            repo_path, cache_dir, iid, inst["base_commit"], inst["repo"]
        )
    except Exception as e:  # noqa: BLE001
        return {"cached": False, "error": f"build_failed: {e}", "cache_dir": str(cache_dir)}
    return {"cached": True, "manifest": manifest, "cache_dir": str(cache_dir)}


def load_cached_markdown(instance_id: str) -> str | None:
    """Retourne le repo_map markdown cache, ou None."""
    p = _instance_cache_dir(instance_id) / "repo_map.md"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def load_cached_manifest(instance_id: str) -> dict | None:
    p = _instance_cache_dir(instance_id) / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cached_repo_path(instance_id: str) -> Path | None:
    """Path du clone cache, ou None si absent."""
    p = _instance_cache_dir(instance_id) / "repo"
    return p if p.exists() else None


def clear_cache(instance_id: str) -> bool:
    cd = _instance_cache_dir(instance_id)
    if not cd.exists():
        return False
    shutil.rmtree(cd, ignore_errors=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["lite", "verified", "live"], default="lite")
    ap.add_argument("--split", default="test")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--force", action="store_true", help="rebuild meme si cache present")
    ap.add_argument("--instance", default=None, help="filter instance_id (csv)")
    args = ap.parse_args()

    all_inst = ensure_dataset(args.split, args.variant)
    if args.instance:
        ids = {x.strip() for x in args.instance.split(",") if x.strip()}
        instances = [i for i in all_inst if i["instance_id"] in ids]
    else:
        instances = all_inst[: args.max]

    print(f"[cache] {len(instances)} instances variant={args.variant} force={args.force}")
    ok = skip = fail = 0
    for i, inst in enumerate(instances):
        print(f"\n[{i + 1}/{len(instances)}] {inst['instance_id']}")
        r = prepare_instance(inst, force_rebuild=args.force)
        if not r.get("cached"):
            fail += 1
            print(f"  FAIL : {r.get('error', '?')}")
            continue
        m = r["manifest"]
        was_skip = "built_at" in m and m.get("built_at", 0) < time.time() - 60
        if was_skip and not args.force:
            skip += 1
            print(f"  CACHED (manifest from {int(time.time() - m['built_at'])}s ago)")
        else:
            ok += 1
            print(
                f"  BUILT files={m['files']} symbols={m['symbols']} "
                f"domains={len(m['domains'])} elapsed={m['elapsed_s']}s"
            )
    print(f"\n[cache] DONE : {ok} built | {skip} cached | {fail} fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
