# ============================================================================
# forge_jepa_finetune_colab.py — Fine-tune LoRA de BGE-M3 sur le dataset
# contrastif Nokido (sandbox/jepa_dataset/pairs.jsonl), pour Colab/Kaggle (T4).
#
# Décision 2026-06-01 : dataset MAIGRE (374 paires / 10 clusters, génériques).
# => EXPÉRIENCE de flow, pas un gain modèle attendu. Garde-fous : split
# held-out + LR 2e-5 + early-stop (leçon sft_local_method : 2e-4 collapse).
# Si l'eval held-out ne s'améliore PAS vs baseline frozen → conclusion =
# JEPA-lite reste la réponse (la data, pas le compute, est le mur).
#
# UPLOAD : déposer sandbox/jepa_dataset/pairs.jsonl (déjà sanitizé, 0 fuite
# vérifiée) dans la session Colab/Kaggle. NE PAS uploader de DB brute.
#
# Coller chaque bloc "# %%" comme une cellule, OU exécuter tel quel en Colab.
# ============================================================================

# %% [1] Install (Colab/Kaggle)
# !pip -q install -U "sentence-transformers>=3.0" peft accelerate

# %% [2] Charger le dataset (pairs.jsonl uploadé)
import json
import random

PAIRS_PATH = "pairs.jsonl"  # uploadé dans la session
records = [json.loads(l) for l in open(PAIRS_PATH, encoding="utf-8")]
random.seed(42)
random.shuffle(records)
n_eval = max(20, len(records) // 10)
eval_rows, train_rows = records[:n_eval], records[n_eval:]
print(f"train={len(train_rows)} eval={len(eval_rows)} (total={len(records)})")

# %% [3] Modèle BGE-M3 + adaptateur LoRA (PEFT)
from sentence_transformers import SentenceTransformer, losses
from sentence_transformers import SentenceTransformerTrainer, SentenceTransformerTrainingArguments
from datasets import Dataset
from peft import LoraConfig

model = SentenceTransformer("BAAI/bge-m3", device="cuda")
lora = LoraConfig(task_type="FEATURE_EXTRACTION", r=16, lora_alpha=32, lora_dropout=0.05,
                  target_modules=["query", "key", "value", "dense"])
model.add_adapter(lora)  # st>=3 : LoRA via PEFT, ~0.3% params entraînés

# %% [4] Datasets HF (anchor/positive [+ negative])
def to_ds(rows):
    has_neg = all("negative" in r for r in rows)
    if has_neg:
        return Dataset.from_dict({
            "anchor":   [r["anchor"] for r in rows],
            "positive": [r["positive"] for r in rows],
            "negative": [r["negative"] for r in rows],
        })
    return Dataset.from_dict({
        "anchor":   [r["anchor"] for r in rows],
        "positive": [r["positive"] for r in rows],
    })

train_ds, eval_ds = to_ds(train_rows), to_ds(eval_rows)
# MultipleNegativesRankingLoss : in-batch negatives + le 'negative' explicite si présent.
loss = losses.MultipleNegativesRankingLoss(model)

# %% [5] Baseline AVANT fine-tune (eval held-out) — pour mesurer un vrai gain
from sentence_transformers.evaluation import TripletEvaluator
ev = None
if "negative" in eval_ds.column_names:
    ev = TripletEvaluator(eval_ds["anchor"], eval_ds["positive"], eval_ds["negative"], name="held_out")
    print("BASELINE (frozen BGE-M3):", ev(model))

# %% [6] Train LoRA (T4) — LR 2e-5, 3 epochs, batch 16, early-ish (data minuscule)
args = SentenceTransformerTrainingArguments(
    output_dir="bge-m3-laforge-lora",
    num_train_epochs=3,
    per_device_train_batch_size=16,
    learning_rate=2e-5,                 # 2e-4 = collapse (leçon sft_local_method)
    warmup_ratio=0.1,
    fp16=True,
    eval_strategy="epoch" if ev else "no",
    save_strategy="epoch",
    load_best_model_at_end=bool(ev),
    metric_for_best_model="held_out_cosine_accuracy" if ev else None,
    logging_steps=10,
)
trainer = SentenceTransformerTrainer(
    model=model, args=args, train_dataset=train_ds,
    eval_dataset=eval_ds if ev else None, loss=loss, evaluator=ev,
)
trainer.train()

# %% [7] Eval APRÈS + verdict
if ev:
    after = ev(model)
    print("APRÈS fine-tune:", after)
    print(">>> Si held_out_cosine_accuracy <= baseline : data trop maigre, "
          "garder JEPA-lite. Sinon, l'adaptateur a un signal.")

# %% [8] Sauver l'adaptateur LoRA (léger) + télécharger
model.save_pretrained("bge-m3-laforge-lora")
# Colab : zip + download
# !zip -r bge-m3-laforge-lora.zip bge-m3-laforge-lora
# from google.colab import files; files.download("bge-m3-laforge-lora.zip")

# %% [9] RÉINTÉGRATION Nokido (après download, local)
# Placer l'adaptateur dans data/llm_models/bge-m3-laforge-lora/ puis charger via
# PEFT au moment de l'embed (forge_npu_embedder / brain_worker). NE PAS écraser
# le BGE-M3 base. L'aligner avec l'espace AMI (forge_world_model projection
# 1024->384) — cf roadmap_ami_lecun "JEPA end-to-end".
