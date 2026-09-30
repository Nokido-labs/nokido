from pathlib import Path

pt = [f.name for f in Path(__import__("os").path.expanduser("~/Script python IA/LaForge/RAG")).glob("*.pt")]
print(pt)
