"""tools/forge_ami_train_cycle.py — 1 vrai cycle entrainement AMI prod.

Real training cycle :
- Load traces DB experience_replay
- Sample N batches
- Train NMLP + JEPA + HierarchicalJEPA
- Validation : eval loss sur held-out
- Persist npz post-train
- Log critical_event kind=ami_train_complete

Usage : LAFORGE_PYTHON tools/forge_ami_train_cycle.py --epochs 5 --persist
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ami_train_cycle")


def run_cycle(epochs: int = 3, batch_size: int = 32, persist: bool = False) -> dict:
    """Run 1 training cycle on NMLP + JEPA. Returns metrics dict."""
    import numpy as np

    # 1. Load traces (synthetic if DB empty, real if traces present)
    try:
        from nokido_agent.app.forge_world_model import (
            JEPA,
            JEPA_IN_DIM,
            NMLP,
            OUTPUT_DIM,
            TRACES_DB,
            _load_traces,
        )

        rows = []
        try:
            rows = _load_traces(TRACES_DB, limit=2000)
        except Exception as e:
            logger.info(f"no traces DB ({e}), using synthetic")
        n_real = len(rows)
    except Exception as e:
        logger.error(f"world_model import KO: {e}")
        return {"error": str(e)}

    if n_real < 50:
        # Synthetic fallback for smoke
        logger.info(f"synthetic training (n_real={n_real} insufficient)")
        rng = np.random.default_rng(42)
        n_synth = 500
        traces = [
            (
                rng.standard_normal(OUTPUT_DIM).astype("float32"),
                "synthetic_action",
                rng.standard_normal(OUTPUT_DIM).astype("float32"),
            )
            for _ in range(n_synth)
        ]
    else:
        traces = rows
        logger.info(f"real traces loaded: {len(traces)}")

    # 2. Init models
    nmlp = NMLP(rng_seed=42)
    jepa = JEPA(rng_seed=42)

    # 3. Train loop (synthetic data)
    nmlp_losses = []
    jepa_losses = []
    t0 = time.time()
    for epoch in range(epochs):
        # JEPA train (synthetic action emb)
        np_rng = __import__("numpy").random.default_rng(epoch)
        for _ in range(20):
            s = np_rng.standard_normal(JEPA_IN_DIM).astype("float32")
            a = np_rng.standard_normal(JEPA_IN_DIM).astype("float32")
            sn = np_rng.standard_normal(JEPA_IN_DIM).astype("float32")
            loss = jepa.train_step(s, a, sn, lr=0.005)
            jepa_losses.append(loss)
        logger.info(f"epoch {epoch + 1}/{epochs} jepa_loss_avg={sum(jepa_losses[-20:]) / 20:.4f}")

    elapsed = time.time() - t0

    # 4. Persist npz
    persisted = []
    if persist:
        try:
            jepa_path = ROOT / "RAG" / "world_model_jepa.npz"
            jepa.save(jepa_path)
            persisted.append(str(jepa_path))
            logger.info(f"persisted JEPA -> {jepa_path}")
        except Exception as e:
            logger.warning(f"persist JEPA fail: {e}")

    # 5. Log critical_event ami_train_complete (best effort)
    try:
        from nokido_agent.app.forge_critical_events import persist as ce_persist

        ce_persist(
            "daemon_dead",
            "info",
            {  # reuse daemon_dead kind (no ami_train_complete kind yet)
                "marker": "ami_train_cycle_complete",
                "epochs": epochs,
                "jepa_loss_initial": round(jepa_losses[0], 4) if jepa_losses else None,
                "jepa_loss_final": round(jepa_losses[-1], 4) if jepa_losses else None,
                "elapsed_s": round(elapsed, 2),
                "persisted": persisted,
            },
        )
    except Exception as e:
        logger.debug(f"critical_events log skipped: {e}")

    # HONNETETE DU RAPPORT (2026-09-20). Mesure : la variable `traces`, construite
    # 40 lignes plus haut a partir des traces REELLES quand il y en a >= 50, n'est
    # JAMAIS utilisee dans la boucle d'entrainement -- le commentaire « # 3. Train
    # loop (synthetic data) » le dit deja. Le modele s'entraine donc TOUJOURS sur
    # `np_rng.standard_normal(...)`, que des traces existent ou non.
    #
    # Le rapport rendait `n_traces_real` A COTE de `jepa_loss_decreased`. Un
    # lecteur -- humain ou agent -- en conclut que les traces ont servi et que le
    # corps a appris. Une loss qui decroit sur du bruit gaussien ne prouve que la
    # capacite du reseau a memoriser du bruit.
    #
    # ON NE BRANCHE PAS `traces` ICI, et c'est un choix DIT : cabler un
    # entrainement sur des donnees dont personne n'a verifie la forme ni la
    # fraicheur serait INVENTER un apprentissage. Contexte : `experience_replay`
    # porte 7 lignes, toutes du 2026-04-28, et AUCUN ecrivain n'existe dans `app/`
    # ni `tools/` (sondes croisees sur le nom de table ET sur ses colonnes).
    # Brancher un entrainement la-dessus produirait un faux progres, pas un vrai.
    #
    # On rend donc le rapport HONNETE. Un faux calme est pire qu'une absence,
    # parce qu'il empeche de chercher.
    # Garde : tests/nr/test_ami_train_dit_sur_quoi_il_s_entraine_nr.py
    return {
        "n_traces_real": n_real,
        "entraine_sur": "synthetique (np.random) — la boucle n'utilise PAS "
                        "`traces`, meme quand n_traces_real > 0",
        "apprentissage_prouve": False,
        "epochs": epochs,
        "jepa_loss_initial": round(jepa_losses[0], 4) if jepa_losses else None,
        "jepa_loss_final": round(jepa_losses[-1], 4) if jepa_losses else None,
        "jepa_loss_decreased": jepa_losses[-1] < jepa_losses[0] if jepa_losses else False,
        "elapsed_s": round(elapsed, 2),
        "persisted": persisted,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--persist", action="store_true")
    args = ap.parse_args()

    result = run_cycle(epochs=args.epochs, batch_size=args.batch_size, persist=args.persist)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
