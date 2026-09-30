"""
forge_dpo_extractor.py — Extraction paires DPO depuis execution_traces.db.

Direct Preference Optimization data prep :
  - "chosen"  : actions avec cost_after < 0.2 (succès confirmé)
  - "rejected": actions avec cost_after > 0.5 (échec confirmé)
  - Paires formées par même task_type, états similaires (cosine > 0.7)

Sortie : JSONL -> RAG/dpo_pairs.jsonl  (compatible trl/unsloth DPOTrainer)

Usage:
    python tools/forge_dpo_extractor.py [--limit 5000] [--min-pairs 100]
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "execution_traces.db"
OUT_PATH = ROOT / "RAG" / "dpo_pairs.jsonl"

COST_GOOD_MAX = 0.15  # top quartile (<0.1 + bas 0.1-0.3)
COST_BAD_MIN = 0.30  # bottom half (0.3-0.5 range dans notre DB)
COSINE_MIN = 0.55  # similarité d'état min — baissé car même task_type suffit


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def load_traces(limit: int = 20000) -> dict:
    """Charge les traces classées en chosen/rejected par task_type."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT state_t_emb, action_json, state_t1_emb, cost_before, cost_after, task_type, success "
        "FROM traces WHERE state_t_emb IS NOT NULL AND state_t1_emb IS NOT NULL LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    chosen = []  # (state_emb, action_text, task_type)
    rejected = []

    for blob_s, action_j, blob_s1, cb, ca, task_type, success in rows:
        try:
            s_emb = np.frombuffer(blob_s, dtype="float32")
            if len(s_emb) != 384:
                continue
            action = action_j if isinstance(action_j, str) else json.dumps(action_j)
            ca = float(ca or 0.5)
            cb = float(cb or 0.5)
            task_type = task_type or "mpc_live"

            if ca < COST_GOOD_MAX or success:
                chosen.append((s_emb, action[:512], task_type))
            elif ca > COST_BAD_MIN and not success:
                rejected.append((s_emb, action[:512], task_type))
        except Exception:
            continue

    return {"chosen": chosen, "rejected": rejected}


def build_pairs(data: dict, max_pairs: int = 5000) -> list:
    """
    Forme paires (chosen, rejected) par task_type + similarité d'état.
    Retourne liste de dicts compatibles trl.DPOTrainer.
    """
    pairs = []
    chosen_by_type = {}
    rejected_by_type = {}

    for s, a, t in data["chosen"]:
        chosen_by_type.setdefault(t, []).append((s, a))
    for s, a, t in data["rejected"]:
        rejected_by_type.setdefault(t, []).append((s, a))

    common_types = set(chosen_by_type) & set(rejected_by_type)
    print(
        f"[dpo] task_types: {common_types} | chosen={len(data['chosen'])} rejected={len(data['rejected'])}"
    )

    for task_type in common_types:
        ch_list = chosen_by_type[task_type]
        rj_list = rejected_by_type[task_type]

        for c_emb, c_action in tqdm(
            ch_list[: max_pairs // max(len(common_types), 1)], desc=f"pairs:{task_type}"
        ):
            # Trouver le rejected le plus proche en état
            best_sim = -1.0
            best_rj = None
            for r_emb, r_action in rj_list[:200]:  # search window 200
                sim = _cosine(c_emb, r_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_rj = r_action

            if best_sim >= COSINE_MIN and best_rj:
                pairs.append(
                    {
                        "prompt": f"[{task_type}] Optimize system action to minimize cost",
                        "chosen": c_action,
                        "rejected": best_rj,
                        "task_type": task_type,
                        "state_sim": round(best_sim, 4),
                    }
                )
                if len(pairs) >= max_pairs:
                    break
        if len(pairs) >= max_pairs:
            break

    return pairs


def export_jsonl(pairs: list, out_path: Path = OUT_PATH) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return len(pairs)


def run(limit: int = 20000, max_pairs: int = 5000) -> dict:
    t0 = time.time()
    if not DB_PATH.exists():
        return {"error": "execution_traces.db not found"}

    print(f"[dpo] Loading traces (limit={limit})...")
    data = load_traces(limit)
    print(f"[dpo] chosen={len(data['chosen'])} rejected={len(data['rejected'])}")

    pairs = build_pairs(data, max_pairs=max_pairs)
    n = export_jsonl(pairs)
    elapsed = time.time() - t0

    print(f"[dpo] {n} paires DPO -> {OUT_PATH} ({elapsed:.1f}s)")
    return {"pairs": n, "output": str(OUT_PATH), "elapsed_s": elapsed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--max-pairs", type=int, default=5000)
    args = parser.parse_args()
    result = run(limit=args.limit, max_pairs=args.max_pairs)
    print(json.dumps(result, indent=2))
