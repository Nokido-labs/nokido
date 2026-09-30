# forge_llamacpp_scorer.py — Backend llama.cpp direct pour NLGraph bench
# Avantages vs Ollama : pas de HTTP, pas de cold-start, controle KV cache
# Usage: python app/forge_llamacpp_scorer.py --model path/to/model.gguf
import subprocess, json, re, time, os
from pathlib import Path

LLAMA_CLI = Path.home() / "llama-vulkan" / "llama-cli.exe"
DEFAULT_MODEL = Path.home() / "llama-vulkan" / "models" / "qwen2.5-coder-7b-q4km.gguf"


class LlamaCppScorer:
    """Score NLGraph cases using llama-cli directly (no Ollama)."""

    def __init__(self, model_path=None, n_gpu_layers=99, ctx_size=2048, threads=8):
        self.model = str(model_path or DEFAULT_MODEL)
        self.ngl = n_gpu_layers
        self.ctx = ctx_size
        self.threads = threads

    def generate(self, prompt, max_tokens=512, temperature=0.1):
        cmd = [
            str(LLAMA_CLI),
            "-m",
            self.model,
            "-ngl",
            str(self.ngl),
            "-c",
            str(self.ctx),
            "-t",
            str(self.threads),
            "-n",
            str(max_tokens),
            "--temp",
            str(temperature),
            "-p",
            prompt,
            "--no-display-prompt",
            "--log-disable",
        ]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, timeout=120, encoding="utf-8", errors="replace")
        dur = time.time() - t0
        return r.stdout.strip(), dur

    def evaluate(self, tc):
        from nokido_agent.app.forge_nlgraph_scorer import TASK_HINTS, LLMScorer

        hint = TASK_HINTS.get(tc.task, "")
        prompt = (
            f"<|im_start|>system\n"
            f"You are a graph theory expert. Think step by step. End with: Final answer: YOUR_ANSWER<|im_end|>\n"
            f"<|im_start|>user\n"
            f"{tc.graph_text}\n\n{tc.question}"
        )
        if hint:
            prompt += f"\n\n{hint}"
        prompt += "<|im_end|>\n<|im_start|>assistant\n"

        try:
            resp, dur = self.generate(prompt, max_tokens=1024)
            ext = LLMScorer.extract(resp, tc.task)
            sc = LLMScorer.score(ext, tc.ground_truth, tc.task)
            return {
                "task": tc.task,
                "graph_id": tc.graph_id,
                "ground_truth": tc.ground_truth,
                "extracted": ext,
                "score": sc,
                "duration_s": round(dur, 2),
                "backend": "llama.cpp",
            }
        except Exception as e:
            return {
                "task": tc.task,
                "graph_id": tc.graph_id,
                "ground_truth": tc.ground_truth,
                "extracted": "",
                "score": 0.0,
                "error": str(e),
                "backend": "llama.cpp",
            }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from nokido_agent.app.forge_nlgraph_runner import GraphGenerator

    print(f"llama-cli: {LLAMA_CLI}")
    print(f"Model: {DEFAULT_MODEL}")
    print(f"Exists: cli={LLAMA_CLI.exists()}, model={DEFAULT_MODEL.exists()}")

    if LLAMA_CLI.exists() and DEFAULT_MODEL.exists():
        scorer = LlamaCppScorer()
        gen = GraphGenerator(seed=42)
        cases = gen.generate_all("easy")

        # Quick test: 2 connectivity cases
        test_cases = [c for c in cases if c.task == "connectivity"][:2]
        for tc in test_cases:
            r = scorer.evaluate(tc)
            st = "OK" if r["score"] == 1.0 else "FAIL"
            print(f"  {tc.task}: {st} ({r['duration_s']:.1f}s) truth={tc.ground_truth} got={r['extracted'][:15]}")
