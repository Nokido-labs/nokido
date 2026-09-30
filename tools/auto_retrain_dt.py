#!/usr/bin/env python
"""auto_retrain_dt.py — Retrain DT router si assez de nouvelles donnees.

Usage (one-shot):
    %USERPROFILE%/miniforge3/python.exe tools/auto_retrain_dt.py
"""

__FORGE_COLOR__ = "metabolisme/routage : retrain du routeur DT sur nouvelles donnees"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_PATH = ROOT / "shadow_mutation" / "rag_index" / "router_decisions.jsonl"
STATE_PATH = ROOT / "sandbox" / "dt_last_retrain.json"
MIN_NEW_SAMPLES = 50
MIN_ACCURACY = 0.85


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"ts": 0, "n_samples": 0, "accuracy": 0.0}


def _count_new_lines(since_ts: float) -> int:
    if not DATA_PATH.exists():
        return 0
    count = 0
    for line in DATA_PATH.read_text("utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("ts", 0) > since_ts:
                count += 1
        except Exception:
            pass
    return count


def main() -> None:
    state = _load_state()
    new_lines = _count_new_lines(state["ts"])
    last_acc = state.get("accuracy", 1.0)

    print(f"[auto_retrain] new_lines={new_lines} last_acc={last_acc:.3f}")

    if new_lines < MIN_NEW_SAMPLES and last_acc >= MIN_ACCURACY:
        print(f"[auto_retrain] skip (new<{MIN_NEW_SAMPLES} and acc>={MIN_ACCURACY})")
        return

    from nokido_agent.app.forge_llm_router_dt import retrain

    print("[auto_retrain] retraining...")
    result = retrain()
    print(f"[auto_retrain] done: {result}")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "n_samples": result.get("samples", 0),
                "accuracy": result.get("accuracy", 0.0),
            }
        ),
        "utf-8",
    )


if __name__ == "__main__":
    main()
