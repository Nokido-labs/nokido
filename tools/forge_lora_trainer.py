"""
forge_lora_trainer.py — Fine-tuning LoRA de qwen2.5-coder:7b sur corpus Nokido
=================================================================================

Entraîne un adaptateur LoRA (Low-Rank Adaptation) sur le corpus Nokido :
  - Paires instruction → code documenté (docstrings Google-style)
  - Fonctions extraites du vault génomique (score ≥ 85)
  - Type hints + docstrings Args/Returns/Raises depuis app/

Hardware cible : Ryzen 8700G — CPU only (torch+cpu) ou iGPU via ROCm si dispo.
Durée estimée  : 2-4h CPU / 30-60min iGPU ROCm.

Usage :
  python tools/forge_lora_trainer.py --build-dataset
  python tools/forge_lora_trainer.py --train
  python tools/forge_lora_trainer.py --build-dataset --train
  python tools/forge_lora_trainer.py --test "Écris une fonction Python qui lit un fichier JSON."
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "lora"
MODEL_DIR = ROOT / "models" / "lora_laforge"
BASE_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"  # HuggingFace ID
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ── 1. Construction du dataset ────────────────────────────────────────────────


def build_dataset(min_score: int = 85, max_samples: int = 2000) -> Path:
    """Compile le dataset d'entraînement depuis le corpus Nokido.

    Sources :
    - Vault génomique (versions mutées avec score ≥ min_score)
    - Fonctions app/ avec docstrings Google-style (Args/Returns présents)
    - Paires experience_memory (succès uniquement)

    Args:
        min_score:   Score vault minimum pour inclure un exemple.
        max_samples: Nombre maximum d'exemples dans le dataset final.

    Returns:
        Path vers le fichier JSONL du dataset.
    """
    samples: list[dict] = []

    # ── Source 1 : fonctions avec docstrings riches ───────────────────────────
    print("📂 Extraction fonctions documentées depuis app/...")
    for fpath in sorted((ROOT / "app").glob("*.py"), key=lambda p: p.stat().st_size, reverse=True):
        try:
            src = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node)
                if not doc or len(doc) < 60:
                    continue
                if "Args:" not in doc and "Returns:" not in doc:
                    continue
                fn_lines = src.splitlines()[node.lineno - 1 : node.end_lineno]
                fn_code = "\n".join(fn_lines)
                if not (80 <= len(fn_code) <= 3000):
                    continue
                samples.append(
                    {
                        "instruction": (
                            f"Écris une fonction Python bien documentée "
                            f"nommée `{node.name}` avec docstring Google-style "
                            f"(Args, Returns, Raises)."
                        ),
                        "input": "",
                        "output": fn_code,
                    }
                )
        except Exception:
            pass

    print(f"  → {len(samples)} fonctions extraites")

    # ── Source 2 : vault génomique ────────────────────────────────────────────
    print("🧬 Extraction vault génomique...")
    vault = ROOT / "shadow_mutation" / "vault"
    vault_count = 0
    for genome_file in sorted(vault.rglob("genome.json")):
        try:
            g = json.loads(genome_file.read_text(encoding="utf-8"))
            score = g.get("score", 0)
            if score < min_score:
                continue
            mod = genome_file.parent.parent.name
            py_files = list(genome_file.parent.glob("*.py"))
            if not py_files:
                continue
            code = py_files[0].read_text(encoding="utf-8", errors="replace")
            # Tronquer à 3000 chars pour rester dans le contexte
            code = code[:3000]
            samples.append(
                {
                    "instruction": (
                        f"Améliore les docstrings du module Python `{mod}` "
                        f"avec des sections Args, Returns et Raises Google-style. "
                        f"Ne supprime aucune logique."
                    ),
                    "input": f"# Module: {mod} | Score: {score}/100",
                    "output": code,
                }
            )
            vault_count += 1
        except Exception:
            pass

    print(f"  → {vault_count} exemples vault")

    # ── Source 3 : paires experience_memory (succès) ──────────────────────────
    print("🧠 Extraction mémoire épisodique...")
    ep = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
    ep_count = 0
    if ep.exists():
        for line in ep.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
                if d.get("evolution_status") != "Success":
                    continue
                mod = d.get("module", "")
                feedback = d.get("feedback", "")
                factors = d.get("experience_feedback", {}).get("success_factors", [])
                if not factors:
                    continue
                samples.append(
                    {
                        "instruction": f"Quels sont les facteurs de succès pour muter le module `{mod}` ?",
                        "input": "",
                        "output": "\n".join(str(f) for f in factors[:8]),
                    }
                )
                ep_count += 1
            except Exception:
                pass

    print(f"  → {ep_count} exemples épisodiques")
    print(f"\nTotal brut : {len(samples)} exemples")

    # Déduplication + shuffle + cap
    seen_outputs: set[str] = set()
    deduped = []
    for s in samples:
        key = s["output"][:100]
        if key not in seen_outputs:
            seen_outputs.add(key)
            deduped.append(s)

    import random

    random.seed(42)
    random.shuffle(deduped)
    final = deduped[:max_samples]

    # Sauvegarde
    out = DATA_DIR / "nokido_train.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for s in final:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"✅ Dataset sauvegardé : {out}")
    print(f"   {len(final)} exemples | {sum(len(s['output']) for s in final) // 1024}KB total")
    return out


# ── 2. Fine-tuning LoRA ───────────────────────────────────────────────────────


def train(
    dataset_path: Path | None = None,
    epochs: int = 3,
    batch_size: int = 1,
    lr: float = 2e-4,
    max_seq_len: int = 1024,
    lora_r: int = 16,
    lora_alpha: int = 32,
) -> None:
    """Lance le fine-tuning LoRA sur le corpus Nokido.

    Utilise QLoRA (4-bit quantization) si bitsandbytes disponible,
    sinon LoRA standard (fp32 CPU).

    Args:
        dataset_path: Chemin vers le JSONL d'entraînement.
        epochs:       Nombre d'époques.
        batch_size:   Taille du batch (1 recommandé sur iGPU 8GB).
        lr:           Learning rate AdamW.
        max_seq_len:  Longueur maximale de séquence.
        lora_r:       Rang LoRA (16 = bon compromis perf/mémoire).
        lora_alpha:   Alpha LoRA (= 2 × lora_r recommandé).
    """
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    if dataset_path is None:
        dataset_path = DATA_DIR / "nokido_train.jsonl"

    if not dataset_path.exists():
        print("❌ Dataset absent — lance d'abord --build-dataset")
        return

    # ── Détection hardware ────────────────────────────────────────────────────
    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.float16
        print(f"🖥️  GPU CUDA : {torch.cuda.get_device_name(0)}")
    elif hasattr(torch, "xpu") and torch.xpu.is_available():
        device = "xpu"
        dtype = torch.float16
        print("🖥️  GPU Intel XPU")
    else:
        device = "cpu"
        dtype = torch.float32
        print("🖥️  CPU only (pas de GPU CUDA/ROCm détecté)")

    print(f"   Device={device} | dtype={dtype}")

    # ── Tokenizer ─────────────────────────────────────────────────────────────
    print(f"\n📦 Chargement tokenizer : {BASE_MODEL}")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True,
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # ── Modèle base ───────────────────────────────────────────────────────────
    print(f"📦 Chargement modèle : {BASE_MODEL}")
    load_kwargs: dict = {
        "trust_remote_code": True,
        "torch_dtype": dtype,
    }

    # QLoRA 4-bit si bitsandbytes dispo et CUDA présent
    qlora_enabled = False
    if device == "cuda":
        try:
            from transformers import BitsAndBytesConfig

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
            )
            load_kwargs["quantization_config"] = bnb_config
            qlora_enabled = True
            print("   QLoRA 4-bit activé")
        except Exception:
            pass

    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, **load_kwargs)

    if device == "cpu":
        model = model.to("cpu")

    # ── Config LoRA ───────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        bias="none",
        target_modules=[
            "q_proj",
            "v_proj",
            "k_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Dataset ───────────────────────────────────────────────────────────────
    raw = load_dataset("json", data_files=str(dataset_path), split="train")

    def _format(example: dict) -> dict:
        """Formate un exemple en prompt Alpaca pour Qwen."""
        instruction = example["instruction"]
        inp = example.get("input", "")
        out = example["output"]

        if inp:
            prompt = f"### Instruction:\n{instruction}\n\n### Input:\n{inp}\n\n### Response:\n{out}"
        else:
            prompt = f"### Instruction:\n{instruction}\n\n### Response:\n{out}"

        tokenized = tokenizer(
            prompt,
            truncation=True,
            max_length=max_seq_len,
            padding="max_length",
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    tokenized_ds = raw.map(_format, remove_columns=raw.column_names)
    print(f"   {len(tokenized_ds)} exemples tokenisés")

    # ── Training ──────────────────────────────────────────────────────────────
    output_dir = str(MODEL_DIR)
    args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        learning_rate=lr,
        fp16=(dtype == torch.float16 and device != "cpu"),
        bf16=False,
        logging_steps=10,
        save_strategy="epoch",
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        report_to="none",
        remove_unused_columns=False,
        dataloader_pin_memory=False,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized_ds,
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model, padding=True),
    )

    print("\n🚀 Démarrage fine-tuning LoRA")
    print(f"   epochs={epochs} | batch={batch_size} | lr={lr} | seq_len={max_seq_len}")
    print(f"   lora_r={lora_r} | lora_alpha={lora_alpha}")
    print(f"   output → {output_dir}\n")

    trainer.train()

    # Sauvegarde adaptateur LoRA
    model.save_pretrained(MODEL_DIR / "adapter")
    tokenizer.save_pretrained(MODEL_DIR / "adapter")
    print(f"\n✅ Adaptateur LoRA sauvegardé → {MODEL_DIR / 'adapter'}")


# ── 3. Test inférence ─────────────────────────────────────────────────────────


def test_inference(prompt: str) -> str:
    """Teste l'inférence avec l'adaptateur LoRA entraîné.

    Args:
        prompt: Instruction à envoyer au modèle fine-tuné.

    Returns:
        Réponse générée par le modèle.
    """
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    adapter_path = MODEL_DIR / "adapter"
    if not adapter_path.exists():
        return "❌ Adaptateur absent — lance d'abord --train"

    tokenizer = AutoTokenizer.from_pretrained(adapter_path, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, trust_remote_code=True, torch_dtype=torch.float32
    )
    model = PeftModel.from_pretrained(base, str(adapter_path))
    model.eval()

    full_prompt = f"### Instruction:\n{prompt}\n\n### Response:\n"
    inputs = tokenizer(full_prompt, return_tensors="pt")

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=512,
            temperature=0.2,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )

    return tokenizer.decode(outputs[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoRA fine-tuning Nokido")
    parser.add_argument(
        "--build-dataset",
        action="store_true",
        help="Construire le dataset depuis le corpus Nokido",
    )
    parser.add_argument("--train", action="store_true", help="Lancer le fine-tuning LoRA")
    parser.add_argument("--test", type=str, default="", help="Tester l'inférence avec un prompt")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--seq-len", type=int, default=1024)
    parser.add_argument("--min-score", type=int, default=85)
    args = parser.parse_args()

    if args.build_dataset:
        build_dataset(min_score=args.min_score)

    if args.train:
        train(
            epochs=args.epochs,
            batch_size=args.batch,
            lr=args.lr,
            lora_r=args.lora_r,
            max_seq_len=args.seq_len,
        )

    if args.test:
        print(test_inference(args.test))

    if not any([args.build_dataset, args.train, args.test]):
        parser.print_help()
