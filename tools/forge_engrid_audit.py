"""
tools/forge_engrid_audit.py — Audit forge_engrid_bridge.py + forge_engrid_engine.py integration.
Checks imports, fallback, task mapping, engine methods.
"""

import importlib.util
import json
import re
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent


def audit_imports(bridge_path: Path) -> dict:
    result = {}
    for symbol in ["SpikeRouter", "MetaCognitionGate", "engrid_generate", "engrid_audit"]:
        try:
            spec = importlib.util.spec_from_file_location("forge_engrid_bridge", bridge_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result[symbol] = "ok" if hasattr(mod, symbol) else "missing"
        except Exception as e:
            result[symbol] = f"error: {str(e)[:80]}"
    return result


def audit_fallback(bridge_src: str) -> bool:
    return "fallback" in bridge_src.lower() and "Generator" in bridge_src


def audit_task_mapping(bridge_src: str) -> dict:
    m = re.search(r"_TASK_TO_SPIKE\s*=\s*\{([^}]+)\}", bridge_src, re.DOTALL)
    if not m:
        return {}
    mapping = {}
    for line in m.group(1).splitlines():
        kv = re.search(r'"([^"]+)"\s*:\s*\(([^)]+)\)', line)
        if kv:
            mapping[kv.group(1)] = kv.group(2)
    return mapping


def audit_engrid_engine(engine_src: str) -> dict:
    public_methods = sum(
        1 for l in engine_src.splitlines() if re.match(r"\s+def [^_]", l) and "self" in l
    )
    return {
        "public_methods": public_methods,
        "tqdm_usage": "tqdm" in engine_src,
        "async_usage": "async def" in engine_src,
        "line_count": len(engine_src.splitlines()),
    }


def full_audit() -> dict:
    bridge_path = LAFORGE_ROOT / "app" / "forge_engrid_bridge.py"
    engine_path = LAFORGE_ROOT / "app" / "forge_engrid_engine.py"

    bridge_src = (
        bridge_path.read_text(encoding="utf-8", errors="replace") if bridge_path.exists() else ""
    )
    engine_src = (
        engine_path.read_text(encoding="utf-8", errors="replace") if engine_path.exists() else ""
    )

    checks = [
        ("bridge_file_exists", lambda: bridge_path.exists()),
        ("engine_file_exists", lambda: engine_path.exists()),
        ("engrid_generate_def", lambda: "def engrid_generate" in bridge_src),
        ("fallback_present", lambda: audit_fallback(bridge_src)),
        ("task_mapping_found", lambda: bool(audit_task_mapping(bridge_src))),
        ("engine_public_methods", lambda: audit_engrid_engine(engine_src)["public_methods"] > 0),
        ("engine_async", lambda: audit_engrid_engine(engine_src)["async_usage"]),
    ]

    report: dict = {}
    for name, fn in tqdm(checks, desc="auditing", unit="check"):
        try:
            result = fn()
        except Exception as e:
            result = f"error: {e}"
        report[name] = result
        status = "[OK]" if result is True else ("[FAIL]" if result is False else f"[{result}]")
        print(f"{status} {name}")

    report["task_mapping"] = audit_task_mapping(bridge_src)
    report["engine_stats"] = audit_engrid_engine(engine_src) if engine_src else {}

    # imports check (may be slow — optional)
    if bridge_path.exists():
        report["symbol_imports"] = audit_imports(bridge_path)

    return report


if __name__ == "__main__":
    report = full_audit()
    out = LAFORGE_ROOT / "sandbox" / "engrid_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nSaved: {out}")
