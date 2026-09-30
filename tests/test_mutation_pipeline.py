"""
tests/test_mutation_pipeline.py
Tests unitaires du pipeline de mutation — à lancer avant chaque dry-run.
Usage: python tests/test_mutation_pipeline.py
"""
import sys, ast, json, subprocess
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "app"))

PASS, FAIL = [], []

def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))

# ── 1. extract_pure_python ──────────────────────────────────────────────────
print("\n1. extract_pure_python")
from LocalMutationManager import extract_pure_python
import ast as _ast

cases = [
    ("markdown_fermé",   "```python\ndef f(a): return a\n```"),
    ("markdown_ouvert",  "```python\ndef f(a): return a"),
    ("backtick_colon",   "```python:\ndef f(a): return a"),
    ("import_builtins",  "import builtins\ndef f(a: str) -> str: return a"),
    ("tronqué_paren",    "def f(a, b=None\n    return a"),
    ("texte_fr",         "Voici le code:\ndef f(a): return a"),
]
for name, text in cases:
    result = extract_pure_python(text)
    ok = result is not None
    if ok:
        try: _ast.parse(result); ok = True
        except SyntaxError: ok = False
    check(f"extract/{name}", ok, repr(result)[:60] if not ok else "")

# ── 2. Ollama disponible ─────────────────────────────────────────────────────
print("\n2. Ollama")
import urllib.request as _ur, json as _j

def ollama_gen(model, prompt, max_tokens=200):
    try:
        pl = _j.dumps({"model":model,"messages":[{"role":"user","content":prompt}],
                       "stream":False,"options":{"num_predict":max_tokens}}).encode()
        req = _ur.Request("http://localhost:11434/api/chat", data=pl,
                          headers={"Content-Type":"application/json"}, method="POST")
        with _ur.urlopen(req, timeout=60) as r:
            return _j.loads(r.read()).get("message",{}).get("content","")
    except Exception as e:
        return f"[ERR] {e}"

for model in ["qwen2.5-coder:1.5b", "qwen2.5-coder:7b-instruct-q4_K_M", "deepseek-coder:6.7b"]:
    text = ollama_gen(model, "def add(a,b): return a+b\nAdd type hints. Code only.")
    check(f"ollama/{model[:20]}", len(text) > 30 and "[ERR]" not in text, text[:60])

# ── 3. Ollama ne tronque pas sur chunk long ───────────────────────────────────
print("\n3. Troncature")
long_chunk = """def _safe_llm_text(res: dict, fallback: str = "") -> str:
    \"\"\"Extrait le texte d\'une réponse LLM.
    
    Args:
        res: résultat LLM
        fallback: valeur par défaut si vide
    
    Returns:
        str: texte extrait ou fallback
    \"\"\"
    turns = res.get("results", [])
    for turn in turns:
        text = str(turn.get("response", "")).strip()
        if text and text not in ("None", "null", "{}", "[]"):
            return text
    return fallback"""

text = ollama_gen("qwen2.5-coder:7b-instruct-q4_K_M",
                  f"Add type hints. Code only:\n```python\n{long_chunk}\n```", max_tokens=2048)
check("troncature/qwen7b_2048tokens", len(text) > 300, f"got {len(text)}c")

# ── 4. best_block top-level ───────────────────────────────────────────────────
print("\n4. best_block selection")
from ChunkQueueManager import ChunkQueueManager
import tempfile, os

sample = """import os

def top_level_fn(a, b):
    return a + b

class MyClass:
    def method(self):
        pass
    
    def another(self):
        pass
"""
with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
    f.write(sample)
    tmp = f.name

try:
    cqm = ChunkQueueManager([tmp], max_chunk_size=1200)
    fn_blocks, _, _ = cqm.get_next_chunk()
    top_level = [b for b in fn_blocks if b.splitlines()[0].startswith(("def ","async def ","class "))]
    check("best_block/top_level_only", len(top_level) >= 1, f"got {len(fn_blocks)} blocks")
    if top_level:
        first = top_level[0]
        check("best_block/not_indented", not first.startswith("    "), repr(first[:40]))
finally:
    os.unlink(tmp)

# ── Résumé ────────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"PASS: {len(PASS)} | FAIL: {len(FAIL)}")
if FAIL:
    print(f"ECHECS: {FAIL}")
    sys.exit(1)
else:
    print("Tous les tests passent — dry-run autorisé ✅")
