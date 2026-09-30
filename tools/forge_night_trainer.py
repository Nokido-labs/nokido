"""
forge_night_trainer.py — Trainer nocturne : backprop global + DPO LoRA.

Phase 1 : Backprop global PyTorch (WorldModel + ValueNet + PolicyNet + CostNet)
Phase 2 : Extraction paires DPO depuis traces
Phase 3 : Fine-tune LoRA sur laforge-qwen via Ollama Modelfile (si unsloth dispo)

Cycle biologique : lance en daemon NSSM la nuit, charge LoRA au boot hub.
Daemon-ready : boucle infinie, sleep jusqu'à minuit, log vers logs/night_trainer.log.

Usage:
    python tools/forge_night_trainer.py [--now] [--phase 1|2|3|all]
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "logs" / "night_trainer.log"
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [night] %(message)s",
    handlers=[
        RotatingFileHandler(str(LOG_PATH), maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("night_trainer")


# ---------------------------------------------------------------------------
# Phase 1 — Backprop global PyTorch
# ---------------------------------------------------------------------------


def phase1_pytorch_training(epochs_wm: int = 20, epochs_nets: int = 15) -> dict:
    log.info("=== Phase 1 : Backprop global PyTorch ===")
    results = {}

    try:
        from nokido_agent.tools.forge_pytorch_world_model import train as train_wm
        from nokido_agent.tools.forge_pytorch_world_model import train_jepa

        log.info("NMLP training...")
        r = train_wm(epochs=epochs_wm, lr=5e-4)
        results["world_model"] = r
        log.info(f"NMLP done: {r}")

        log.info("JEPA training...")
        r = train_jepa(epochs=epochs_wm, lr=5e-4)
        results["jepa"] = r
        log.info(f"JEPA done: {r}")
    except Exception as e:
        log.warning(f"WorldModel skip: {e}")
        results["world_model"] = {"error": str(e)}

    try:
        from nokido_agent.tools.forge_pytorch_nets import train_cost, train_policy, train_value

        log.info("ValueNet training...")
        r = train_value(epochs=epochs_nets, lr=5e-4)
        results["value_net"] = r
        log.info(f"ValueNet done: {r}")

        log.info("PolicyNet training...")
        r = train_policy(epochs=epochs_nets, lr=5e-4)
        results["policy_net"] = r
        log.info(f"PolicyNet done: {r}")

        log.info("CostNet training...")
        r = train_cost(epochs=epochs_nets, lr=5e-4)
        results["cost_net"] = r
        log.info(f"CostNet done: {r}")
    except Exception as e:
        log.warning(f"Nets skip: {e}")
        results["nets"] = {"error": str(e)}

    return results


# ---------------------------------------------------------------------------
# Phase 2 — DPO extraction
# ---------------------------------------------------------------------------


def phase2_dpo_extraction(limit: int = 30000, max_pairs: int = 8000) -> dict:
    log.info("=== Phase 2 : DPO extraction ===")
    try:
        from nokido_agent.tools.forge_dpo_extractor import run as dpo_run

        result = dpo_run(limit=limit, max_pairs=max_pairs)
        log.info(f"DPO done: {result}")
        return result
    except Exception as e:
        log.warning(f"DPO skip: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Phase 3 — LoRA fine-tune via Ollama Modelfile
# ---------------------------------------------------------------------------


def phase3_lora_finetune() -> dict:
    """
    Stratégie LoRA pour Ollama :
    - Si unsloth + GPU VRAM ≥ 8GB -> LoRA direct sur GGUF
    - Sinon -> Ollama Modelfile SYSTEM prompt update (fallback soft)
    """
    log.info("=== Phase 3 : LoRA / Modelfile update ===")

    dpo_path = ROOT / "RAG" / "dpo_pairs.jsonl"
    if not dpo_path.exists():
        return {"error": "dpo_pairs.jsonl not found — run phase2 first"}

    # Essai unsloth (GPU)
    try:
        # `torch` est importe pour SONDER la presence du GPU : l'echec de cet
        # import fait tomber le try vers la voie CPU. Il est donc VOULU et non
        # utilise -- on le declare, on ne le supprime pas (ruff F401).
        import torch  # noqa: F401
        from unsloth import FastLanguageModel

        model_name = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=model_name,
            max_seq_length=2048,
            dtype=None,
            load_in_4bit=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=16,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            lora_alpha=16,
            lora_dropout=0.05,
            bias="none",
        )

        import json

        from datasets import Dataset
        from trl import DPOConfig, DPOTrainer

        pairs = [json.loads(ligne) for ligne in dpo_path.read_text().splitlines() if ligne.strip()]
        dataset = Dataset.from_list(
            [
                {"prompt": p["prompt"], "chosen": p["chosen"], "rejected": p["rejected"]}
                for p in pairs[:2000]
            ]
        )
        config = DPOConfig(
            output_dir=str(ROOT / "RAG" / "lora_output"),
            num_train_epochs=1,
            per_device_train_batch_size=2,
            learning_rate=5e-5,
            beta=0.1,
            fp16=True,
            save_strategy="no",
            logging_steps=50,
        )
        trainer = DPOTrainer(model=model, args=config, train_dataset=dataset, tokenizer=tokenizer)
        trainer.train()
        model.save_pretrained(str(ROOT / "RAG" / "lora_output"))
        log.info("[phase3] LoRA saved to RAG/lora_output")
        return {"method": "unsloth_lora", "status": "done"}

    except ImportError:
        log.info("[phase3] unsloth non dispo — fallback Ollama Modelfile")
    except Exception as e:
        log.warning(f"[phase3] unsloth error: {e} — fallback Modelfile")

    # Fallback : mettre à jour le SYSTEM prompt Ollama avec les meilleures traces
    try:
        import json as _json

        pairs = [_json.loads(ligne) for ligne in dpo_path.read_text().splitlines() if ligne.strip()]
        top_chosen = [p["chosen"][:200] for p in pairs[:10]]
        examples = "\n".join(f"- {ex}" for ex in top_chosen)

        modelfile = f"""FROM laforge-qwen
SYSTEM \"\"\"Nokido Autonomous Agent — AMI LeCun/Hassabis.
Tu optimises les actions pour minimiser le coût système.
Exemples d'actions efficaces apprises par self-play :
{examples}

Toujours retourner JSON valide: {{"description": str, "steps": [str]}}\"\"\"
PARAMETER temperature 0.3
PARAMETER num_predict 256
"""
        mf_path = ROOT / "RAG" / "nokido_trained.Modelfile"
        mf_path.write_text(modelfile)

        import subprocess

        result = subprocess.run(
            ["ollama", "create", "laforge-trained", "-f", str(mf_path)],
            capture_output=True,
            text=True,
            timeout=120,
        errors="replace")
        if result.returncode == 0:
            log.info("[phase3] Modelfile laforge-trained créé avec succès")
            return {"method": "ollama_modelfile", "status": "done", "model": "laforge-trained"}
        else:
            return {"method": "ollama_modelfile", "status": "error", "stderr": result.stderr[:200]}

    except Exception as e:
        log.warning(f"[phase3] Modelfile error: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Anchor RAG post-training
# ---------------------------------------------------------------------------


def anchor_results(results: dict) -> None:
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem="Night trainer — backprop global + DPO + LoRA",
            solution=f"Phase1={results.get('phase1', {}).get('world_model', {}).get('final_loss', '?')} | Phase2={results.get('phase2', {}).get('pairs', '?')} paires | Phase3={results.get('phase3', {}).get('method', '?')}",
            example="python tools/forge_night_trainer.py --now --phase all",
            domain="mpc",
        )
    except Exception:
        pass


def json_safe(obj):
    try:
        import json

        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


# ---------------------------------------------------------------------------
# Scheduler daemon
# ---------------------------------------------------------------------------


def _seconds_until_midnight() -> float:
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
    return (midnight - now).total_seconds()


def run_once(phases: str = "all") -> dict:
    t0 = time.time()
    results = {}
    do_all = phases == "all"

    if do_all or "1" in phases:
        results["phase1"] = phase1_pytorch_training()

    if do_all or "2" in phases:
        results["phase2"] = phase2_dpo_extraction()

    if do_all or "3" in phases:
        # Gate anti-régression : phase3 réécrit le modèle ollama laforge-trained.
        # post_check : ollama répond encore après (sinon la régression est ancrée).
        import sys as _sys

        if str(ROOT / "app") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_guarded_change import guarded_change, hub_alive

        with guarded_change(
            "night_trainer: phase3 LoRA/Modelfile",
            post_check=lambda: hub_alive("http://localhost:11434/api/tags"),
        ):
            results["phase3"] = phase3_lora_finetune()

    if do_all or "4" in phases:
        log.info("=== Phase 4 : Golden Dataset benchmark ===")
        try:
            from nokido_agent.tools.forge_benchmark_runner import run as bench_run

            b = bench_run(agent="groq", max_tasks=20)
            results["phase4"] = {"pass_rate": b["pass_rate"], "n": b["n_tasks"]}
            log.info(f"Benchmark done: {b['pass_rate']}% ({b['passed']}/{b['n_tasks']})")
        except Exception as e:
            log.warning(f"Benchmark skip: {e}")
            results["phase4"] = {"error": str(e)}

    results["elapsed_s"] = round(time.time() - t0, 1)
    anchor_results(results)
    log.info(f"Night training complete: {results['elapsed_s']}s")
    return results


def daemon_loop(phases: str = "all") -> None:
    log.info("[night_trainer] Daemon started. Waiting for 02:00...")
    while True:
        sleep_s = _seconds_until_midnight()
        log.info(f"[night_trainer] Sleeping {sleep_s / 3600:.1f}h until 02:00")
        time.sleep(sleep_s)
        log.info("[night_trainer] 02:00 — starting night training cycle")
        try:
            results = run_once(phases)
            log.info(f"[night_trainer] Cycle done: {json_safe(results)}")
        except Exception as e:
            log.error(f"[night_trainer] Cycle error: {e}")


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="Run immediately (no wait)")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (loop nightly)")
    parser.add_argument("--phase", default="all", help="1|2|3|all")
    args = parser.parse_args()

    if args.now:
        result = run_once(args.phase)
        print(json.dumps(result, indent=2, default=str))
    elif args.daemon:
        daemon_loop(args.phase)
    else:
        # Mode par défaut : run now
        result = run_once(args.phase)
        print(json.dumps(result, indent=2, default=str))
