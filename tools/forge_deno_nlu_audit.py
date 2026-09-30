"""
tools/forge_deno_nlu_audit.py — Audit Deno brain.ts NLU layer + nervous_system.ts event bus.
Extracts intents, events, LLM calls, missing handlers. Saves to sandbox/deno_nlu_audit.json.
"""

import json
import re
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
BRAIN_TS = LAFORGE_ROOT / "proxy_deno" / "core" / "brain.ts"
NS_TS = LAFORGE_ROOT / "proxy_deno" / "core" / "nervous_system.ts"


def audit_brain_ts(path: Path) -> dict:
    intents, events_emitted, events_listened, llm_calls, fetch_calls = (
        set(),
        set(),
        set(),
        set(),
        set(),
    )

    if not path.exists():
        return {
            "error": f"not found: {path}",
            "intents": [],
            "events_emitted": [],
            "events_listened": [],
            "llm_calls": [],
            "fetch_calls": [],
        }

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in tqdm(lines, desc="brain.ts", unit="line", leave=False):
        # case "intent_name":
        m = re.search(r'\bcase\s+"([^"]+)"', line)
        if m:
            intents.add(m.group(1))
        # emit("event_name"
        for m in re.finditer(r'\bemit\s*\(\s*"([^"]+)"', line):
            events_emitted.add(m.group(1))
        # on("event_name"
        for m in re.finditer(r'\bon\s*\(\s*"([^"]+)"', line):
            events_listened.add(m.group(1))
        # await llm... or llmCall
        if re.search(r"\bawait\s+llm|\bllmCall\b|\bllm\.\w+\(", line):
            snippet = line.strip()[:80]
            llm_calls.add(snippet)
        # fetch(
        if "fetch(" in line:
            m2 = re.search(r'fetch\s*\(\s*["\`]([^"\'`]+)', line)
            if m2:
                fetch_calls.add(m2.group(1)[:60])

    return {
        "intents": sorted(intents),
        "events_emitted": sorted(events_emitted),
        "events_listened": sorted(events_listened),
        "llm_calls": sorted(llm_calls),
        "fetch_calls": sorted(fetch_calls),
    }


def audit_nervous_system(path: Path) -> dict:
    event_types, handlers = set(), set()

    if not path.exists():
        return {"error": f"not found: {path}", "event_types": [], "handler_count": 0}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    handler_count = 0
    for line in tqdm(lines, desc="nervous_system.ts", unit="line", leave=False):
        m = re.search(r'\bcase\s+"([^"]+)"', line)
        if m:
            event_types.add(m.group(1))
        for m in re.finditer(r'\bon\s*\(\s*"([^"]+)"', line):
            handlers.add(m.group(1))
            handler_count += 1

    return {
        "event_types": sorted(event_types),
        "handlers": sorted(handlers),
        "handler_count": handler_count,
    }


def coverage_report(brain: dict, ns: dict) -> str:
    emitted = set(brain.get("events_emitted", []))
    handled = set(ns.get("handlers", []))
    missing = sorted(emitted - handled)
    lines = [
        f"Intents handled:     {len(brain.get('intents', []))}",
        f"Events emitted:      {len(emitted)}",
        f"Events handled:      {len(handled)}",
        f"LLM call patterns:   {len(brain.get('llm_calls', []))}",
        f"Missing handlers:    {len(missing)}",
    ]
    if missing:
        lines.append("  Unhandled events:")
        for ev in missing:
            lines.append(f"    ✗ {ev}")
    else:
        lines.append("  All emitted events have handlers ✓")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"Auditing: {BRAIN_TS}")
    brain = audit_brain_ts(BRAIN_TS)
    ns = audit_nervous_system(NS_TS)

    print("\n=== NLU Coverage Report ===")
    print(coverage_report(brain, ns))

    out = LAFORGE_ROOT / "sandbox" / "deno_nlu_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"brain": brain, "nervous_system": ns}, indent=2))
    print(f"\nSaved: {out}")
