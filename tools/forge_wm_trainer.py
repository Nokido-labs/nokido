from logging.handlers import RotatingFileHandler

"""
Phase B — World Model auto-retrain daemon.
Checks trace count every CHECK_INTERVAL.
Triggers train() when NEW_TRACES_THRESHOLD new traces since last run.
Saves model + logs metrics to lessons.
"""
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [wm_trainer] %(message)s",
    handlers=[
        RotatingFileHandler(
            str(ROOT / "logs" / "wm_trainer.log"), maxBytes=10485760, backupCount=5
        ),
        logging.StreamHandler(),
    ],
)

CHECK_INTERVAL = 900  # check every 15 min
NEW_TRACES_THRESHOLD = 500  # retrain when 500 new traces
MIN_TRACES_TO_TRAIN = 100  # never train with fewer than this

_state_file = ROOT / "RAG" / "wm_trainer_state.json"


def _load_state() -> dict:
    if _state_file.exists():
        try:
            return json.loads(_state_file.read_text())
        except Exception:
            pass
    return {"last_trained_at": 0.0, "last_trace_count": 0, "n_runs": 0}


def _save_state(s: dict):
    _state_file.write_text(json.dumps(s, indent=2))


def _run_training(n_traces: int) -> dict:
    from nokido_agent.app.forge_world_model import train, train_jepa

    logging.info(f"Training NMLP on {n_traces} traces...")
    result_nmlp = train(epochs=30, lr=0.001, batch_size=32)
    logging.info(f"NMLP done: {result_nmlp}")
    logging.info(f"Training JEPA on {n_traces} traces...")
    try:
        result_jepa = train_jepa(epochs=30, lr=0.001)
        logging.info(f"JEPA done: {result_jepa}")
    except Exception as e:
        logging.warning(f"JEPA train skipped: {e}")
        result_jepa = {}
    return {"nmlp": result_nmlp, "jepa": result_jepa}


def _anchor(n_traces: int, result: dict):
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"World model auto-retrain triggered at {n_traces} traces",
            solution=f"Trained 30 epochs, final_loss={result.get('final_loss'):.4f}, elapsed={result.get('elapsed_s', 0):.1f}s",
            example=f"forge_wm_trainer.py auto-ran after {NEW_TRACES_THRESHOLD} new traces",
            domain="mpc",
        )
    except Exception as e:
        logging.warning(f"anchor err: {e}")


def main():
    from nokido_agent.app.forge_execution_tracer import count_traces

    state = _load_state()
    logging.info(f"start — last_count={state['last_trace_count']} n_runs={state['n_runs']}")

    while True:
        try:
            n = count_traces()
            delta = n - state["last_trace_count"]

            if n >= MIN_TRACES_TO_TRAIN and delta >= NEW_TRACES_THRESHOLD:
                logging.info(f"{delta} new traces since last train (total={n}) — triggering")
                result = _run_training(n)
                state["last_trained_at"] = time.time()
                state["last_trace_count"] = n
                state["n_runs"] += 1
                _save_state(state)
                _anchor(n, result)
            else:
                logging.info(f"traces={n} delta={delta}/{NEW_TRACES_THRESHOLD} — waiting")

        except Exception as e:
            logging.warning(f"trainer loop err: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
