"""
tools/kaggle_push.py — Push et déclenche le notebook Kaggle
=============================================================
Usage :
  python tools/kaggle_push.py                    # push + run
  python tools/kaggle_push.py --dry-run          # push sans run
  python tools/kaggle_push.py --kernel notebookdnokido

Modifie automatiquement la cellule VERSION_ID avant le push
pour forcer Kaggle à relancer l'exécution.
"""

__FORGE_COLOR__ = "infra/deploy : push et declenche le notebook Kaggle"  # organe declare le 2026-09-06 (audit de raccordement)

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

# L'identifiant Kaggle portait le nom civil EN DUR (decision owner 2026-09-30 :
# pseudonyme dans tout le code publie). Variable standard du CLI Kaggle ; absente,
# le marqueur ci-dessous fait refuser le push par Kaggle, lisiblement.
KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME", "<KAGGLE_USERNAME non defini>")

KERNEL_META = {
    "id": f"{KAGGLE_USERNAME}/notebooknokido",
    "title": "notebookNokido",
    "code_file": "nokido_graphcodebert.ipynb",
    "language": "python",
    "kernel_type": "notebook",
    "is_private": False,
    "enable_gpu": False,
    "enable_tpu": False,
    "enable_internet": True,
    "dataset_sources": [f"{KAGGLE_USERNAME}/laforge-export"],
    "competition_sources": [],
    "kernel_sources": [],
}


def inject_version(nb: dict) -> dict:
    """Injecte VERSION_ID dans la première cellule code pour forcer le re-run."""
    version = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
    marker = f"# VERSION_ID: {version}\n"

    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            src = cell.get("source", [])
            if isinstance(src, list):
                # Remplace ou insère le marker en première ligne
                if src and src[0].startswith("# VERSION_ID:"):
                    src[0] = marker
                else:
                    src.insert(0, marker)
                cell["source"] = src
            break
    return nb, version


def push_notebook(kernel_id: str = None, dry_run: bool = False) -> None:
    from kaggle import KaggleApi

    api = KaggleApi()
    api.authenticate()

    # Charge et modifie le notebook
    nb = json.loads(NB_SRC.read_text(encoding="utf-8"))
    nb, version = inject_version(nb)

    # Crée un dossier temp
    tmp = tempfile.mkdtemp()
    try:
        nb_tmp = os.path.join(tmp, "nokido_graphcodebert.ipynb")
        with open(nb_tmp, "w", encoding="utf-8") as f:
            json.dump(nb, f, indent=2, ensure_ascii=False)

        meta = dict(KERNEL_META)
        if kernel_id:
            meta["id"] = kernel_id

        with open(os.path.join(tmp, "kernel-metadata.json"), "w") as f:
            json.dump(meta, f, indent=2)

        if dry_run:
            print(f"[DRY-RUN] VERSION_ID={version}")
            print(f"[DRY-RUN] kernel={meta['id']}")
            return

        api.kernels_push(folder=tmp)
        print(f"✅ Notebook pushé — VERSION_ID={version}")
        print(f"   Kernel: {meta['id']}")
        print(f"   URL: https://www.kaggle.com/code/{meta['id']}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def push_dataset(version_notes: str = None) -> None:
    from kaggle import KaggleApi

    api = KaggleApi()
    api.authenticate()

    notes = (
        version_notes
        or f"Auto-update {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M')}"
    )
    api.dataset_create_version(
        folder=str(DS_DIR),
        version_notes=notes,
        convert_to_csv=False,
        dir_mode="zip",
        delete_old_versions=False,
    )
    print(f"✅ Dataset mis à jour — {notes}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", default=None, help="Kernel slug override")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dataset", action="store_true", help="Push dataset aussi")
    ap.add_argument("--notes", default=None, help="Notes version dataset")
    args = ap.parse_args()

    if args.dataset:
        push_dataset(args.notes)

    push_notebook(args.kernel, args.dry_run)
