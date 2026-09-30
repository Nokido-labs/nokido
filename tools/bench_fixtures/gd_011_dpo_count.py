from pathlib import Path

p = Path(__import__("os").path.expanduser("~/Script python IA/LaForge/RAG/dpo_pairs.jsonl"))
lines = len(p.read_text().splitlines()) if p.exists() else 0
print(f"dpo_pairs: {lines}")
