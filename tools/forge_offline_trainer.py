"""forge_offline_trainer.py — Batch offline training daemon for Nokido AMI nets.

LeCun AMI: world model learned via offline self-supervised batch replay.
Hassabis: sleep/consolidation = batch SGD on execution traces → cortical memory.

Trains every INTERVAL_S (6h) if MIN_NEW_TRACES new transitions exist:
  value_net | policy_net | cost_net | world_model NMLP | world_model JEPA | H-JEPA (optional)

Usage:
  LAFORGE_PYTHON tools/forge_offline_trainer.py --daemon
  LAFORGE_PYTHON tools/forge_offline_trainer.py --once
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
RAG = ROOT / "RAG"
SANDBOX = ROOT / "sandbox"

if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

logger = logging.getLogger("Nokido.OfflineTrainer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

TRACES_DB = RAG / "execution_traces.db"
HEARTBEAT = SANDBOX / "offline_trainer.heartbeat"
STATE_FILE = SANDBOX / "offline_trainer_state.json"
INTERVAL_S = 21_600  # 6h — matches health_diagnostic / hebbian_linker cycle
MIN_NEW_TRACES = 50  # skip all training if fewer new traces
THRESHOLD_LIGHT = 50  # value_net, policy_net, cost_net minimum
THRESHOLD_HEAVY = 500  # world_model, jepa, h_jepa need more signal

_HEAVY_MODELS = {"world_model", "jepa", "h_jepa"}

# Epochs for batch training (more than online SGD)
EPOCHS = {
    "value_net": 50,
    "policy_net": 50,
    "cost_net": 50,
    "world_model": 80,
    "jepa": 50,
    "h_jepa": 30,
}
LR = 0.001


# ─────────────────────────────────────────────────────────────────────────────
# State persistence
# ─────────────────────────────────────────────────────────────────────────────


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_trained_ts": 0.0, "last_trace_count": 0}


def _save_state(state: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _write_heartbeat(results: dict) -> None:
    SANDBOX.mkdir(exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps(
            {
                "ts": datetime.now().isoformat(),
                "pid": os.getpid(),
                "interval_s": INTERVAL_S,
                "last_results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Trace counting
# ─────────────────────────────────────────────────────────────────────────────

# Traces noise filter : exclure les system_tick d un ancien daemon historique
# (1588 entries sur 13693 = 11.6% pure bruit). Aucun writer actif dans le code
# courant - ces traces datent d un daemon supprime qui ne stockait aucune action
# exploitable, juste des battements de coeur "tasks:unknown" + variantes.
# Le verdict est uniforme : aucune transition utile a y apprendre.
_NOISE_FILTER_SQL = "task_type IS NOT NULL AND action_json NOT LIKE '%system_tick%'"


def _count_traces(since_ts: float = 0.0) -> int:
    if not TRACES_DB.exists():
        return 0
    try:
        con = sqlite3.connect(str(TRACES_DB))
        row = con.execute(
            f"SELECT COUNT(*) FROM traces WHERE ts > ? AND {_NOISE_FILTER_SQL}", (since_ts,)
        ).fetchone()
        con.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("count_traces error: %s", e)
        return 0


def _total_traces() -> int:
    if not TRACES_DB.exists():
        return 0
    try:
        con = sqlite3.connect(str(TRACES_DB))
        row = con.execute(f"SELECT COUNT(*) FROM traces WHERE {_NOISE_FILTER_SQL}").fetchone()
        con.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Per-model training wrappers
# ─────────────────────────────────────────────────────────────────────────────


def _train_value(db: Path) -> dict:
    from nokido_agent.app.forge_value_net import train

    return train(db_path=db, epochs=EPOCHS["value_net"], lr=LR)


def _train_policy(db: Path) -> dict:
    from nokido_agent.app.forge_policy_net import train

    return train(db_path=db, epochs=EPOCHS["policy_net"], lr=LR)


def _train_cost(db: Path) -> dict:
    from nokido_agent.app.forge_cost_net import train

    return train(db_path=db, epochs=EPOCHS["cost_net"], lr=LR)


def _train_world_model(db: Path) -> dict:
    from nokido_agent.app.forge_world_model import train

    return train(db_path=db, epochs=EPOCHS["world_model"], lr=LR)


def _train_jepa(db: Path) -> dict:
    from nokido_agent.app.forge_world_model import train_jepa

    return train_jepa(db_path=db, epochs=EPOCHS["jepa"], lr=LR)


def _train_h_jepa(db: Path) -> dict:
    try:
        from nokido_agent.app.forge_world_model import train_hierarchical_jepa

        return train_hierarchical_jepa(db_path=db, epochs=EPOCHS["h_jepa"], lr=LR)
    except (ImportError, AttributeError):
        return {"skipped": "train_hierarchical_jepa not available"}


# ─────────────────────────────────────────────────────────────────────────────
# Main training cycle
# ─────────────────────────────────────────────────────────────────────────────


def run_training_cycle(state: dict) -> dict:
    t0 = time.monotonic()
    total = _total_traces()
    new = _count_traces(since_ts=state["last_trained_ts"])

    logger.info("Traces total=%d new_since_last=%d", total, new)

    if new < MIN_NEW_TRACES:
        msg = f"skip — only {new} new traces (min={MIN_NEW_TRACES})"
        logger.info(msg)
        return {"skipped": msg, "total_traces": total, "new_traces": new}

    results: dict = {"total_traces": total, "new_traces": new}

    steps = [
        ("value_net", _train_value),
        ("policy_net", _train_policy),
        ("cost_net", _train_cost),
        ("world_model", _train_world_model),
        ("jepa", _train_jepa),
        ("h_jepa", _train_h_jepa),
    ]

    from tqdm import tqdm

    for name, fn in tqdm(steps, desc="offline_train", unit="model"):
        if name in _HEAVY_MODELS and new < THRESHOLD_HEAVY:
            logger.info(
                "skip %s — %d new traces < %d (heavy threshold)", name, new, THRESHOLD_HEAVY
            )
            results[name] = {"skipped": f"only {new} new traces (heavy_min={THRESHOLD_HEAVY})"}
            continue
        logger.info("Training %s ...", name)
        t_start = time.monotonic()
        try:
            res = fn(TRACES_DB)
            elapsed = round(time.monotonic() - t_start, 1)
            results[name] = {**res, "elapsed_s": elapsed}
            logger.info("%s done in %.1fs — loss=%s", name, elapsed, res.get("final_loss", "?"))
            if name == "policy_net":
                n_policy = res.get("n", 0)
                rate = n_policy / total if total > 0 else 0.0
                if rate < 0.15:
                    logger.warning(
                        "policy_net success_rate=%.1f%% (%d/%d) < 15%% — "
                        "system succeeds too rarely; check execute_fn reward signal",
                        100.0 * rate,
                        n_policy,
                        total,
                    )
        except Exception as exc:
            logger.error("%s FAILED: %s", name, exc)
            results[name] = {"error": str(exc)[:200]}

    results["cycle_elapsed_s"] = round(time.monotonic() - t0, 1)
    state["last_trained_ts"] = time.time()
    state["last_trace_count"] = total
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Anchor + lesson
# ─────────────────────────────────────────────────────────────────────────────


def _anchor(results: dict) -> None:
    # Ne pas ancrer un cycle no-op : si le training a été skip (pas assez de
    # nouvelles traces), ancrer "Trained 0 models / Results: {}" ne fait que
    # polluer lessons_learned.md + le RAG à chaque réveil. On ancre seulement
    # quand au moins un modèle a réellement été entraîné.
    if "skipped" in results or not any(
        isinstance(v, dict) and ("final_loss" in v or "error" in v)
        for v in results.values()
    ):
        return
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        summary = {
            k: v.get("final_loss", v.get("skipped", "err"))
            for k, v in results.items()
            if isinstance(v, dict)
        }
        anchor_solution(
            problem="offline_trainer: batch training AMI nets on execution_traces.db",
            solution=f"Trained {len(summary)} models. Traces={results.get('total_traces', '?')}. "
            f"Results: {json.dumps(summary)}",
            example="LAFORGE_PYTHON tools/forge_offline_trainer.py --once",
            domain="systeme",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    import io as _io
    import sys as _sys

    if hasattr(_sys.stdout, "buffer"):
        _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")

    global MIN_NEW_TRACES
    import argparse

    ap = argparse.ArgumentParser(description="Nokido AMI offline batch trainer")
    ap.add_argument("--daemon", action="store_true", help="loop every INTERVAL_S")
    ap.add_argument("--once", action="store_true", help="one cycle then exit")
    ap.add_argument(
        "--min-traces",
        type=int,
        default=MIN_NEW_TRACES,
        help=f"min new traces to trigger training (default {MIN_NEW_TRACES})",
    )
    args = ap.parse_args()
    MIN_NEW_TRACES = args.min_traces

    if not args.once and not args.daemon:
        ap.error("--once or --daemon required")

    state = _load_state()

    if args.once:
        results = run_training_cycle(state)
        _save_state(state)
        _write_heartbeat(results)
        _anchor(results)
        print(json.dumps(results, indent=2, default=str))
        return 0

    # daemon loop
    logger.info("Offline trainer daemon started — interval=%ds pid=%d", INTERVAL_S, os.getpid())
    from nokido_agent.app.forge_guarded_change import guarded_change  # gate anti-régression

    while True:
        try:
            # gate : un cycle de training qui lève est ancré (anchor_error)
            # au lieu d'être juste loggé. db_snapshot=False (modèles in-memory).
            with guarded_change("offline_trainer: training cycle", db_snapshot=False):
                results = run_training_cycle(state)
            _save_state(state)
            _write_heartbeat(results)
            _anchor(results)
        except Exception as exc:
            logger.error("cycle error: %s", exc)
            _write_heartbeat({"error": str(exc)})
        logger.info("Sleeping %ds until next cycle", INTERVAL_S)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
