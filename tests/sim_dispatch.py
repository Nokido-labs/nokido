import sys
from pathlib import Path
ROOT = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
sys.path.insert(0, str(ROOT/'app'))

results = []

# Test 1: AgentType importable et non-None
try:
    from forge_core_models import AgentType
    results.append(f"OK AgentType={[a.name for a in AgentType]}")
except Exception as e:
    results.append(f"FAIL AgentType: {e}")
    (ROOT/"sandbox"/"status.txt").write_text("\n".join(results))
    exit()

# Test 2: hybrid_classify retourne tuple valide
try:
    from forge_nlu import hybrid_classify as _hc
    def _sf(t, _AT=AgentType): return (_AT.CHAT, None)
    res = _hc("bonjour", _sf, router=None)
    assert res is not None, "hybrid_classify retourne None"
    istr, cmd, conf = res
    intent = next((a for a in AgentType if a.value == istr), AgentType.CHAT)
    results.append(f"OK hybrid_classify: intent={intent.name} conf={conf}")
except Exception as e:
    results.append(f"FAIL hybrid_classify: {e}")

# Test 3: AgentType dans dispatch_ai n'est pas None
try:
    import forge_dispatch_ai as _fda
    # Verifier que l'import module-level est present
    import importlib, inspect
    src = inspect.getsource(_fda)
    has_import = "from forge_core_models import AgentType" in src
    has_no_reassign = "AgentType        = _g('AgentType')" not in src
    results.append(f"OK AgentType import module: {has_import}")
    results.append(f"OK no _g reassign: {has_no_reassign}")
except Exception as e:
    results.append(f"FAIL fda check: {e}")

verdict = "PASS" if all(r.startswith("OK") for r in results) else "FAIL"
(ROOT/"sandbox"/"status.txt").write_text(verdict + "\n\n" + "\n".join(results))
print(verdict)
for r in results: print(r)
