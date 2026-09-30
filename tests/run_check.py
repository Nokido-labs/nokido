import py_compile
from pathlib import Path
ROOT = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
APP  = ROOT / 'app'
results = []

for fn in ["Nokido.py","forge_rag_warmup.py","forge_collab_modes.py",
           "forge_orchestrator.py","forge_commands.py","forge_disco.py"]:
    try:
        py_compile.compile(str(APP/fn), doraise=True)
        results.append("OK  py_compile " + fn)
    except Exception as e:
        results.append("FAIL " + fn + ": " + str(e)[:120])

def read(f): return (APP/f).read_text(encoding='utf-8', errors='ignore')

lf  = read("Nokido.py")
rwu = read("forge_rag_warmup.py")
col = read("forge_collab_modes.py")
orc = read("forge_orchestrator.py")
dis = read("forge_disco.py")

checks = [
    ("_rag_warmup_done avant if",     "_rag_warmup_done = None  # defini avant" in lf),
    ("_rag_self_warmup passe done",   "_done_event=_rag_warmup_done" in lf),
    ("rag_warmup sig done param",     "async def rag_self_warmup(app, _rag_warmup_done=None)" in rwu),
    ("RAG guard isinstance",          "isinstance(docs, list)" in col),
    ("RAG except guard",              "except Exception as _rag_e" in col),
    ("5 methodes orchestrator",       all("def "+m+"(" in orc for m in ["ping_pong","chef_dispatch","debate_compare","cline_loop","get_status"])),
    ("_handle_disco dans Nokido",    "async def _handle_disco(self" in lf),
    ("disco forge_context",           "import forge_context as _fc_disco" in dis),
    ("@collab dans forge_commands",   '"@collab"' in read("forge_commands.py")),
]

for name, ok in checks:
    results.append(("OK  " if ok else "FAIL ") + name)

verdict = "PASS" if all(r.startswith("OK") for r in results) else "FAIL"
out = verdict + "\n\n" + "\n".join(results)
(ROOT/"sandbox"/"status.txt").write_text(out, encoding="utf-8")
print(out)
