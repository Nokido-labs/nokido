"""forge_sft_eval.py — éval HELD-OUT : base vs adapter LoRA sur des problèmes HumanEval
JAMAIS vus à l'entraînement (pas de leakage) = mesure HONNÊTE du gain SFT.

Génère LOCALEMENT (Qwen-1.5B base, puis base+adapter) sur HumanEval[holdout_start:],
teste via le harness déterministe du runner, compare les pass-rates.

Convention split : on entraîne le SFT sur les golden des problèmes 0..holdout_start-1
(via forge_sft_export --he-train-max holdout_start) et on évalue sur holdout_start.. .

Lance (PYTHONUTF8=1 conseillé) :
    python tools/forge_sft_eval.py --holdout-start 120 --n 44 --adapter RAG/sft/adapter
⚠️ Génération 1.5B CPU = lent (n×2 forwards). 44×2 ≈ 20-40 min APU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _gen_eval(model, tok, entries, label: str) -> int:
    from nokido_agent.tools.forge_humaneval_runner import _extract_code, _run_tests

    passed = 0
    for e in entries:
        msgs = [{"role": "user",
                 "content": f"Complète cette fonction Python. Renvoie UNIQUEMENT le corps (indenté).\n\n{e['prompt']}"}]
        text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inp = tok(text, return_tensors="pt")
        out = model.generate(**inp, max_new_tokens=400, do_sample=False, pad_token_id=tok.eos_token_id)
        resp = tok.decode(out[0][inp["input_ids"].shape[1]:], skip_special_tokens=True)
        body = _extract_code(resp, e)
        ok, _ = _run_tests(e, body)
        passed += int(ok)
        print(f"  [{label}] {e['task_id']} {'PASS' if ok else 'FAIL'}", flush=True)
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-Coder-3B-Instruct")  # doit matcher forge_sft_train
    ap.add_argument("--adapter", default=str(ROOT / "RAG" / "sft" / "adapter"))
    ap.add_argument("--holdout-start", type=int, default=120)
    ap.add_argument("--n", type=int, default=44)
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from nokido_agent.tools.forge_humaneval_runner import ensure_dataset

    entries = ensure_dataset()[args.holdout_start: args.holdout_start + args.n]
    print(f"[eval] HELD-OUT {len(entries)} problèmes (HumanEval {args.holdout_start}..{args.holdout_start + len(entries) - 1})", flush=True)

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    base = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.float32)
    base.eval()
    nb = _gen_eval(base, tok, entries, "base")
    print(f"\n[eval] BASE : {nb}/{len(entries)} = {round(100 * nb / len(entries), 1)}%\n", flush=True)

    adapted = PeftModel.from_pretrained(base, args.adapter)
    adapted.eval()
    na = _gen_eval(adapted, tok, entries, "sft ")
    print(f"\n{'=' * 50}")
    print(f"BASE : {nb}/{len(entries)} = {round(100 * nb / len(entries), 1)}%")
    print(f"SFT  : {na}/{len(entries)} = {round(100 * na / len(entries), 1)}%")
    print(f"DELTA: {na - nb:+d} problèmes ({round(100 * (na - nb) / len(entries), 1):+} pts) — held-out, 0 leakage")
    print("=" * 50)


if __name__ == "__main__":
    main()
