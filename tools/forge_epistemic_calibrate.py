"""Step 8 epistemic: calibration coefficients alpha/beta/gamma/delta/epsilon via
regression logistique sur dataset historique de claims.

Workflow :
  1. Load dataset CSV (manual labels: still_true|refuted|qualified)
     ou bootstrap auto depuis DB existante (heuristique refutation count)
  2. Features par claim : trust_weight, recency_decay, citation_norm,
                          peer_review_bonus, refutation_penalty
  3. Logistic regression multi-class -> coefficients optimaux
  4. Validation cross-fold + report fit quality
  5. Output JSON data/epistemic_coefficients.json (lu par recompute.py futur)

Usage:
    LAFORGE_PYTHON tools/forge_epistemic_calibrate.py --bootstrap-from-db
    LAFORGE_PYTHON tools/forge_epistemic_calibrate.py --csv data/labels.csv
    LAFORGE_PYTHON tools/forge_epistemic_calibrate.py --apply  # write JSON config
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
CONFIG_PATH = ROOT / "data" / "epistemic_coefficients.json"

sys.path.insert(0, str(ROOT))
from nokido_agent.tools.forge_epistemic_recompute import (
    _count_refutations,
    _domain_half_life,
    _now_year,
    _parse_year,
    _peer_reviewed_heuristic,
    _trust_weight_heuristic,
)


def _features(chunk: dict, t_now: float) -> list[float]:
    """Vecteur features [trust, recency_decay, citation_norm, peer_review, refutation_penalty]."""
    pub_year = _parse_year(chunk.get("ingested_at"), fallback=t_now - 0.5)
    half_life = _domain_half_life(chunk.get("domain"))
    trust = _trust_weight_heuristic(chunk.get("source"), chunk.get("author"))
    peer_rev = 1.0 if _peer_reviewed_heuristic(chunk.get("source"), chunk.get("author")) else 0.0

    age = t_now - pub_year
    recency = math.exp(-age * math.log(2) / half_life)
    citation_norm = math.log1p(chunk.get("citation_count", 0)) / 6.0
    refutation_penalty = 1.0 / (1.0 + 0.5 * chunk.get("n_refutations", 0))

    return [trust, recency, min(1.0, citation_norm), peer_rev, refutation_penalty]


def bootstrap_dataset_from_db() -> list[tuple[list[float], int]]:
    """Genere dataset (X, y) depuis DB en utilisant heuristique label :
       y=2 (still_true)  : peer-reviewed + 0 refutations
       y=1 (qualified)   : peer-reviewed + 1+ refutations partielles
       y=0 (refuted)     : non peer-reviewed avec refutations OU explicit retraction
    Label artificiel pour bootstrap initial. Calibrer manuellement ensuite.
    """
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.row_factory = sqlite3.Row
    t_now = _now_year()

    dataset = []
    cur = conn.execute("""
        SELECT id, text, source, author, domain, ingested_at, retraction_status
        FROM rag_chunks
        WHERE (active IS NULL OR active = 1)
          AND text IS NOT NULL
          AND length(text) > 200
        LIMIT 200
    """)
    rows = [dict(r) for r in cur.fetchall()]

    # Pre-pass : compute trust + age + peer pour quartile-based labels au cold start
    enriched = []
    for chunk in rows:
        chunk["citation_count"] = 0
        chunk["n_refutations"] = _count_refutations(conn, chunk["id"])
        peer = _peer_reviewed_heuristic(chunk["source"], chunk["author"])
        trust = _trust_weight_heuristic(chunk["source"], chunk["author"])
        age = t_now - _parse_year(chunk.get("ingested_at"), fallback=t_now - 0.5)
        chunk["_peer"] = peer
        chunk["_trust"] = trust
        chunk["_age"] = age
        enriched.append(chunk)

    # Heuristique cold-start (sans refutations reelles) :
    #   y=2 (still_true)  : trust haut + recent + peer
    #   y=1 (qualified)   : trust moyen OU peer mais ancien
    #   y=0 (refuted)     : retraction explicite OU refutations OU
    #                       (trust bas + non-peer + ancien) = signal qualite faible
    for chunk in enriched:
        n_refs = chunk["n_refutations"]
        retracted = chunk.get("retraction_status") == "retracted"
        trust = chunk["_trust"]
        peer = chunk["_peer"]
        age = chunk["_age"]

        if retracted or n_refs > 1 or (not peer and trust < 0.45) or (age > 3.0 and not peer):
            y = 0
        elif peer and n_refs > 0 or trust < 0.6 or age > 1.5:
            y = 1
        else:
            y = 2

        X = _features(chunk, t_now)
        dataset.append((X, y))

    conn.close()
    return dataset


def load_csv_dataset(csv_path: str) -> list[tuple[list[float], int]]:
    """CSV columns expected:
    trust_weight, recency_decay, citation_norm, peer_review_bonus,
    refutation_penalty, label (0=refuted, 1=qualified, 2=still_true)
    """
    dataset = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            X = [
                float(row[k])
                for k in (
                    "trust_weight",
                    "recency_decay",
                    "citation_norm",
                    "peer_review_bonus",
                    "refutation_penalty",
                )
            ]
            y = int(row["label"])
            dataset.append((X, y))
    return dataset


def calibrate(dataset: list[tuple[list[float], int]]) -> dict:
    """Logistic regression multi-class. Retourne coefficients normalises."""
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score
    except ImportError:
        print("ERR: scikit-learn requis (pip install scikit-learn numpy)", file=sys.stderr)
        return {"error": "sklearn_missing"}

    X = np.array([d[0] for d in dataset])
    y = np.array([d[1] for d in dataset])

    if len(set(y)) < 2:
        return {"error": "single_class", "dataset_size": len(dataset)}

    # Use one-vs-rest multinomial
    clf = LogisticRegression(multi_class="multinomial", max_iter=1000, C=1.0)
    clf.fit(X, y)

    # Cross-val accuracy
    cv = cross_val_score(clf, X, y, cv=min(5, len(dataset) // 4)) if len(dataset) >= 20 else None

    # Extract coefficients (moyenne over classes pour single set)
    # coef_ shape (n_classes, n_features)
    feature_names = [
        "alpha_trust",
        "beta_recency",
        "gamma_citation",
        "delta_peer_review",
        "epsilon_refutation_penalty",
    ]

    # Approche 1 : prendre les coefs de la classe "still_true" (y=2)
    if 2 in clf.classes_:
        idx_truth = list(clf.classes_).index(2)
        raw_coefs = clf.coef_[idx_truth].tolist()
    else:
        raw_coefs = clf.coef_[0].tolist()

    # Normalisation : ramener absolu sum = 1
    abs_coefs = [abs(c) for c in raw_coefs]
    total = sum(abs_coefs) or 1.0
    normalized = [c / total for c in abs_coefs]

    return {
        "alpha": round(normalized[0], 3),
        "beta": round(normalized[1], 3),
        "gamma": round(normalized[2], 3),
        "delta": round(normalized[3], 3),
        "epsilon": round(normalized[4], 3),
        "raw_coefficients": dict(zip(feature_names, [round(c, 4) for c in raw_coefs])),
        "intercept": clf.intercept_.tolist(),
        "dataset_size": len(dataset),
        "class_distribution": dict(zip(*[c.tolist() for c in np.unique(y, return_counts=True)])),
        "cv_accuracy_mean": float(cv.mean()) if cv is not None else None,
        "cv_accuracy_std": float(cv.std()) if cv is not None else None,
        "calibrated_at": datetime.now(tz=UTC).isoformat(),
    }


def save_config(coefficients: dict, path: Path = CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(coefficients, indent=2), encoding="utf-8")
    print(f"[OK] coefficients written to {path}")


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--bootstrap-from-db",
        action="store_true",
        help="Generate dataset heuristically from DB chunks",
    )
    src.add_argument("--csv", metavar="FILE", help="Load labeled CSV dataset")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write coefficients to data/epistemic_coefficients.json",
    )
    args = ap.parse_args()

    if args.bootstrap_from_db:
        dataset = bootstrap_dataset_from_db()
        print(f"Bootstrap dataset: {len(dataset)} samples")
    else:
        dataset = load_csv_dataset(args.csv)
        print(f"CSV dataset: {len(dataset)} samples")

    if len(dataset) < 10:
        print("ERR: dataset trop petit (<10 samples). Labelliser plus de claims.", file=sys.stderr)
        sys.exit(1)

    result = calibrate(dataset)
    print(json.dumps(result, indent=2))

    if args.apply and "error" not in result:
        save_config(result)


if __name__ == "__main__":
    main()
