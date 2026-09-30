#!/usr/bin/env python3
"""
forge_jepa_finetune_local.py — Fine-tune LoRA BGE-M3 EN LOCAL sur CPU.

Alternative au notebook Colab quand pas d'accès navigateur. CPU forcé =>
AUCUN GPU/DirectML => 0 risque BSOD (incident_bsod_directml_brainworker),
juste lent. Adapté aux 374 paires (data maigre = experience flow).

Lecture : sandbox/jepa_dataset/pairs.jsonl (déjà sanitizé).
Sortie  : sandbox/jepa_dataset/bge-m3-laforge-lora/ (adaptateur LoRA léger).
Log     : BASELINE vs APRÈS (held_out_cosine_accuracy) = le juge.

Déport : lancer via run_job online=true (download HF). Poll job_status.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""        # pas de GPU
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ROOT / "sandbox" / "jepa_dataset" / "pairs.jsonl"
OUT = ROOT / "sandbox" / "jepa_dataset" / "bge-m3-laforge-lora"


def _log(m: str) -> None:
    print(f"[jepa-ft] {m}", flush=True)


def _ensure_deps() -> None:
    need = []
    try:
        import torch  # noqa
    except ImportError:
        need.append("torch")
    try:
        import sentence_transformers  # noqa
        from sentence_transformers import SentenceTransformerTrainer  # noqa  (requiert v3+)
    except Exception:
        need.append("sentence-transformers>=3.0")
    try:
        import peft  # noqa
    except ImportError:
        need.append("peft")
    try:
        import datasets  # noqa
    except ImportError:
        need.append("datasets")
    if not need:
        return
    _log(f"install deps manquantes: {need}")
    cmd = [sys.executable, "-m", "pip", "install", "-q"]
    if "torch" in need:
        # torch CPU-only (pas de CUDA download)
        subprocess.run(cmd + ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"], check=False)
        need = [n for n in need if n != "torch"]
    if need:
        subprocess.run(cmd + need, check=False)


def main() -> int:
    if not PAIRS.exists():
        _log(f"ERREUR: {PAIRS} absent (lancer forge_jepa_dataset.py).")
        return 1
    _ensure_deps()

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from sentence_transformers import (
        SentenceTransformer, losses,
        SentenceTransformerTrainer, SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.evaluation import TripletEvaluator

    torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))  # laisser des cœurs au hub

    records = [json.loads(l) for l in open(PAIRS, encoding="utf-8")]
    random.seed(42)
    random.shuffle(records)
    n_eval = max(20, len(records) // 10)
    eval_rows, train_rows = records[:n_eval], records[n_eval:]
    _log(f"train={len(train_rows)} eval={len(eval_rows)}")

    _log("chargement BGE-M3 (CPU, ~2.3GB au 1er run)...")
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    lora = LoraConfig(task_type="FEATURE_EXTRACTION", r=16, lora_alpha=32,
                      lora_dropout=0.05, target_modules=["query", "key", "value", "dense"])
    model.add_adapter(lora)

    def to_ds(rows):
        has_neg = all("negative" in r for r in rows)
        cols = {"anchor": [r["anchor"] for r in rows], "positive": [r["positive"] for r in rows]}
        if has_neg:
            cols["negative"] = [r["negative"] for r in rows]
        return Dataset.from_dict(cols)

    train_ds, eval_ds = to_ds(train_rows), to_ds(eval_rows)
    loss = losses.MultipleNegativesRankingLoss(model)

    ev = None
    if "negative" in eval_ds.column_names:
        ev = TripletEvaluator(eval_ds["anchor"], eval_ds["positive"], eval_ds["negative"], name="held_out")
        base = ev(model)
        _log(f"BASELINE (frozen): {base}")

    args = SentenceTransformerTrainingArguments(
        output_dir=str(OUT),
        num_train_epochs=3,
        per_device_train_batch_size=8,        # CPU -> petit batch
        learning_rate=2e-5,                   # 2e-4 = collapse (sft_local_method)
        warmup_ratio=0.1,
        fp16=False, bf16=False,               # CPU
        eval_strategy="epoch" if ev else "no",
        save_strategy="no",
        logging_steps=10,
        report_to=[],
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=args, train_dataset=train_ds,
        eval_dataset=eval_ds if ev else None, loss=loss, evaluator=ev,
    )
    _log("train CPU (lent)...")
    trainer.train()

    if ev:
        after = ev(model)
        _log(f"APRES: {after}")
        _log(">>> VERDICT: si held_out_cosine_accuracy <= baseline -> data trop "
             "maigre, garder JEPA-lite. Sinon l'adaptateur a un signal.")

    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUT))
    _log(f"adaptateur LoRA -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
