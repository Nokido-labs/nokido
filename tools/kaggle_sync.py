"""
tools/kaggle_sync.py — Synchronisation notebook + dataset Kaggle
=================================================================
Pousse le notebook ET le dataset en une seule commande.
Le notebook est inclus dans le dataset pour être auto-chargeable.

Usage :
  python tools/kaggle_sync.py              # push tout
  python tools/kaggle_sync.py --notebook   # notebook seulement
  python tools/kaggle_sync.py --dataset    # dataset seulement
"""

import argparse
import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB_SRC = ROOT / "docs" / "nokido_graphcodebert.ipynb"
DS_DIR = ROOT / "kaggle_dataset"

# Identifiant Kaggle : plus en dur (il portait le nom civil ; decision owner
# 2026-09-30). Variable standard du CLI Kaggle.
KERNEL_OWNER = __import__("os").environ.get("KAGGLE_USERNAME", "<KAGGLE_USERNAME non defini>")
KERNEL_SLUG = "notebooknokido"
DATASET_ID = f"{KERNEL_OWNER}/laforge-export"


def inject_version(nb: dict) -> tuple:
    """Injecte VERSION_ID + URL de rechargement dans C0."""
    version = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")

    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            src = cell.get("source", [])
            if isinstance(src, list):
                # Remplace ou insère VERSION_ID
                new_line = f"# VERSION_ID: {version}\n"
                if src and "VERSION_ID" in src[0]:
                    src[0] = new_line
                else:
                    src.insert(0, new_line)
                cell["source"] = src
            break
    return nb, version


def push_notebook() -> None:
    from kaggle import KaggleApi

    api = KaggleApi()
    api.authenticate()

    nb = json.loads(NB_SRC.read_text(encoding="utf-8"))
    nb, version = inject_version(nb)

    tmp = tempfile.mkdtemp()
    try:
        nb_tmp = os.path.join(tmp, "nokido_graphcodebert.ipynb")
        with open(nb_tmp, "w", encoding="utf-8") as f:
            json.dump(nb, f, indent=2, ensure_ascii=False)

        # Copie aussi le notebook dans le dataset pour accès direct
        nb_ds = DS_DIR / "nokido_graphcodebert.ipynb"
        shutil.copy(nb_tmp, nb_ds)

        meta = {
            "id": f"{KERNEL_OWNER}/{KERNEL_SLUG}",
            "title": "notebookNokido",
            "code_file": "nokido_graphcodebert.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": False,
            "enable_gpu": False,
            "enable_tpu": False,
            "enable_internet": True,
            "dataset_sources": [DATASET_ID],
        }
        with open(os.path.join(tmp, "kernel-metadata.json"), "w") as f:
            json.dump(meta, f, indent=2)

        api.kernels_push(folder=tmp)
        print(f"Notebook pushé VERSION_ID={version}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def push_dataset(notes: str = None) -> None:
    from kaggle import KaggleApi

    api = KaggleApi()
    api.authenticate()

    # Inclut le notebook dans le dataset
    nb_ds = DS_DIR / "nokido_graphcodebert.ipynb"
    if NB_SRC.exists() and not nb_ds.exists():
        shutil.copy(NB_SRC, nb_ds)

    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M")
    version_notes = notes or f"Auto-sync {ts} — notebook inclus"

    api.dataset_create_version(
        folder=str(DS_DIR),
        version_notes=version_notes,
        convert_to_csv=False,
        dir_mode="zip",
        delete_old_versions=False,
    )
    print(f"Dataset poussé: {version_notes}")
    print(
        "Le notebook est accessible dans le dataset: /kaggle/input/laforge-export/nokido_graphcodebert.ipynb"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--notebook", action="store_true")
    ap.add_argument("--dataset", action="store_true")
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()

    if not args.notebook and not args.dataset:
        # Push tout par défaut
        push_dataset(args.notes)
        push_notebook()
    else:
        if args.dataset:
            push_dataset(args.notes)
        if args.notebook:
            push_notebook()
