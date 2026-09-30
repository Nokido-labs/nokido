"""forge_sft_train.py — fine-tune SFT (LoRA) d'un petit modèle coder sur le golden-dataset.
But : rendre le modèle EXPERT de TES conventions/projets → son 1er jet (intuition) statistiquement
plus proche de la vérité → moins de boucles REPL → meilleur score natif (HumanEval/BFCL).

PIPELINE : forge_sft_export.py → RAG/sft/golden.jsonl → forge_sft_train.py → adapter LoRA.

Deps (à installer dans laforge_py314 si absentes) :
    pip install peft trl datasets accelerate    (transformers + torch déjà présents)
Base par défaut : Qwen2.5-Coder-1.5B-Instruct (CPU/APU-tractable sur petit dataset).
    7B = GPU quasi requis. 0.5B = ultra-rapide, moins fort.

Lance :
    python tools/forge_sft_train.py --golden RAG/sft/golden.jsonl --base Qwen/Qwen2.5-Coder-1.5B-Instruct --epochs 3
Sortie : RAG/sft/adapter/ (LoRA). Charger ensuite via peft.

⚠️ Sur CPU/APU c'est LENT. OK pour petit modèle + petit golden ; gros = impraticable sans GPU.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_golden(path: str) -> list[dict]:
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(ROOT / "RAG" / "sft" / "golden.jsonl"))
    ap.add_argument("--base", default="Qwen/Qwen2.5-Coder-3B-Instruct")  # sweet spot 780M (panel)
    ap.add_argument("--out", default=str(ROOT / "RAG" / "sft" / "adapter"))
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=2e-5)  # 2e-4 effondrait le modele (panel multi-LLM 2026-05-31)
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--bf16", action="store_true", help="bf16 (Ryzen AVX-512), plus rapide ; defaut fp32 fiable")
    ap.add_argument("--completion-only", action="store_true",
                    help="masque le prompt user, loss sur la reponse assistant only (SFT propre)")
    ap.add_argument("--eval-frac", type=float, default=0.1, help="part held-out interne pour early-stopping")
    ap.add_argument("--patience", type=int, default=2)
    args = ap.parse_args()

    rows = load_golden(args.golden)
    print(f"[sft] {len(rows)} exemples golden depuis {args.golden}")
    if len(rows) < 8:
        print("[sft] trop peu d'exemples (<8) — accumule plus de golden d'abord (HumanEval/GOAP/swebench).")
        return

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, EarlyStoppingCallback
    from trl import DataCollatorForCompletionOnlyLM, SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    def fmt(ex):  # chat → texte via le template du modèle
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}

    ds_all = Dataset.from_list(rows).map(fmt, remove_columns=["messages", "source", "id"])
    # split interne train/eval → early-stopping détecte l'effondrement AVANT la fin du run
    n_eval = max(4, int(len(ds_all) * args.eval_frac))
    split = ds_all.train_test_split(test_size=n_eval, seed=42)
    ds_train, ds_eval = split["train"], split["test"]
    print(f"[sft] train={len(ds_train)} eval={len(ds_eval)} lr={args.lr} rank={args.rank} bf16={args.bf16}")

    model = AutoModelForCausalLM.from_pretrained(
        args.base, dtype=torch.bfloat16 if args.bf16 else torch.float32)
    lora = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "v_proj"],  # conservateur → limite le catastrophic forgetting
    )
    cfg = SFTConfig(
        output_dir=args.out, num_train_epochs=args.epochs, per_device_train_batch_size=1,
        gradient_accumulation_steps=4, learning_rate=args.lr, lr_scheduler_type="cosine",
        warmup_ratio=0.1, logging_steps=5, report_to=[], max_length=args.max_seq,
        dataset_text_field="text", eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
        use_cpu=True, bf16=args.bf16, fp16=False,  # APU sans CUDA → CPU (bf16 = AVX-512 si dispo)
    )
    collator = None
    if args.completion_only:  # loss assistant-only (template réponse Qwen)
        collator = DataCollatorForCompletionOnlyLM(
            response_template="<|im_start|>assistant\n", tokenizer=tok)
    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=ds_train, eval_dataset=ds_eval,
        peft_config=lora, processing_class=tok, data_collator=collator,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=args.patience)],
    )
    trainer.train()
    trainer.save_model(args.out)
    print(f"[sft] adapter LoRA sauvé → {args.out}  (charger via peft.PeftModel.from_pretrained)")


if __name__ == "__main__":
    main()
