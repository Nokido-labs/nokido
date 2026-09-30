"""
Gitingest 5 repos AMI-roadmap + lance veille approfondie SearXNG.
Repos: letta, XAgent, LATS, DSPy
"""

import subprocess
import sys
import time
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "gitingest_ami"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))

REPOS = [
    ("letta", "https://github.com/letta-ai/letta"),
    ("xagent", "https://github.com/OpenBMB/XAgent"),
    ("lats", "https://github.com/lapisrocks/LanguageAgentTreeSearch"),
    ("dspy", "https://github.com/stanfordnlp/dspy"),
]

EXCLUDES = [
    "*.db",
    "*.gguf",
    "*.bin",
    "*.pyc",
    "*.whl",
    "*.exe",
    "*.dll",
    "*.pth",
    "*.onnx",
    "*.safetensors",
    "node_modules/*",
    "__pycache__/*",
    "*.png",
    "*.jpg",
    "*.gif",
    "*.svg",
    "*.ico",
]

MAX_SIZE = "204800"

results = {}

print("\n=== GITINGEST 4 REPOS AMI ===\n")
for name, url in tqdm(REPOS, desc="gitingest"):
    out = OUT_DIR / f"{name}.txt"
    args = [sys.executable, "-m", "gitingest", url, "-o", str(out), "-s", MAX_SIZE]
    for pat in EXCLUDES:
        args += ["-e", pat]
    print(f"\n[{name}] {url}")
    t0 = time.time()
    r = subprocess.run(args, capture_output=True, text=True, timeout=120, errors="replace")
    elapsed = time.time() - t0
    ok = r.returncode == 0 and out.exists()
    size = out.stat().st_size if out.exists() else 0
    results[name] = {"ok": ok, "size": size, "elapsed": elapsed, "rc": r.returncode}
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {size:,} bytes en {elapsed:.1f}s")
    if r.stderr and not ok:
        print(f"  STDERR: {r.stderr[:300]}")

print("\n=== INDEX RAG ===\n")
try:
    from nokido_agent.app.forge_rag_engine import RAGEngine

    rag = RAGEngine()
    for name, res in tqdm(results.items(), desc="rag index"):
        if not res["ok"]:
            continue
        out = OUT_DIR / f"{name}.txt"
        content = out.read_text(encoding="utf-8", errors="ignore")
        chunks = [content[i : i + 2000] for i in range(0, len(content), 2000)]
        for i, chunk in enumerate(chunks[:50]):
            rag.index(
                content=chunk, metadata={"source": f"gitingest:{name}", "repo": name, "chunk": i}
            )
        print(f"  [{name}] {min(len(chunks), 50)} chunks indexes")
except Exception as e:
    print(f"  RAG index error: {e}")

print("\n=== VEILLE APPROFONDIE ===\n")
try:
    from nokido_agent.app.forge_watch_agent import create_job

    theme = (
        "Letta MemGPT stateful agent persistent memory archival retrieval "
        "XAgent hierarchical planning inner-outer loop tool-use LLM "
        "LATS Language Agent Tree Search MCTS reflection backtracking "
        "DSPy declarative prompt optimization signatures modules teleprompter "
        "inference-time planning world model cost function autonomous agent 2025 2026"
    )
    chain_id = create_job(
        theme=theme,
        idea_id="ami_roadmap_veille",
        agent="CLAUDE_AMI_VEILLE",
    )
    print(f"  chain_id={chain_id}")
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem="Veille approfondie Letta/XAgent/LATS/DSPy pour roadmap AMI",
            solution=f"chain {chain_id}, gitingest 4 repos dans docs/gitingest_ami/",
            example="create_job(theme=ami_roadmap_veille)",
            domain="rag",
        )
    except Exception:
        pass
except Exception as e:
    print(f"  Watch job error: {e}")

print("\n=== RESUME ===")
for name, r in results.items():
    status = "OK" if r["ok"] else "FAIL"
    print(f"  {name:10s} [{status}] {r['size']:>8,} bytes")
print(f"\nDocs: {OUT_DIR}")
