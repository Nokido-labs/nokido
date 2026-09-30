"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch__copy_mixins
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

import ast, os

TMP = "/tmp"
APP = __import__("os").path.expanduser(r"~\Script python IA\LaForge\app")

files = ["forge_mixin_ai.py", "forge_mixin_patch.py", "forge_mixin_rag.py", "forge_mixin_ui.py"]
for f in files:
    src = open(f"{TMP}/{f}", "rb").read().decode("utf-8", "replace")
    dst = os.path.join(APP, f)
    open(dst, "w", encoding="utf-8").write(src)
    try:
        ast.parse(open(dst, encoding="utf-8").read())
        print(f"✅ {f} -> disque OK ({len(src.splitlines())}L)")
    except SyntaxError as e:
        print(f"❌ {f} SyntaxError L{e.lineno}")
