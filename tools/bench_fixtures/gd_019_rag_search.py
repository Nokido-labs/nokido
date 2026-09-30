import sys

sys.path.insert(0, __import__("os").path.expanduser("~/Script python IA/LaForge/app"))
from nokido_agent.app.forge_rag_engine import RAGEngine

e = RAGEngine()
r = e.search("CostNet PyTorch training", top_k=3)
print(f"rag_hits: {len(r)}")
