"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_patch_rag_warmup
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
patch_rag_warmup.py — Injecte rag_warmup_spawn() dans forge_rag_warmup.py
Execution: python app/patch_rag_warmup.py
"""
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
target = ROOT / "app" / "forge_rag_warmup.py"
content = target.read_text(encoding="utf-8", errors="ignore")

SPAWN_FN = '''
def rag_warmup_spawn() -> str:
    """
    Lance le warmup RAG (index app/) en process detache.
    Retourne task_id immediatement — zéro blocage MCP/stdio.
    """
    try:
        from forge_runner import spawn as _sp
        lines = [
            "from pathlib import Path as _P",
            "import sys as _s",
            "_s.path.insert(0, str(_P(__file__).resolve().parent.parent / 'app'))",
            "try:",
            "    from forge_rag_index_app import index_app_dir as _idx",
            "    _result = _idx(str(_P(__file__).resolve().parent.parent / 'app'))",
            "except Exception as _e:",
            "    _result = repr(_e)",
        ]
        tid = _sp("\\n".join(lines), prefix="rag_warm")
        try:
            from live_bridge import bridge as _br
            _br.json_set("rag_warmup.tid", tid)
            _br.json_set("rag_warmup.status", "started")
        except Exception:
            pass
        return tid
    except Exception as e:
        return repr(e)

'''

MARKER = "\nasync def rag_self_warmup("
if "rag_warmup_spawn" in content:
    print("already present")
elif MARKER in content:
    idx = content.find(MARKER)
    content = content[:idx] + SPAWN_FN + content[idx:]
    target.write_text(content, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)
    print("PASS injected")
else:
    # Append at end
    content = content + SPAWN_FN
    target.write_text(content, encoding="utf-8")
    py_compile.compile(str(target), doraise=True)
    print("PASS appended")
