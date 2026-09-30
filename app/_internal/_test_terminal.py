"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch__test_terminal
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
import sys, os

print("isatty stdout:", sys.stdout.isatty())
print("isatty stdin :", sys.stdin.isatty())
print("TERM         :", os.environ.get("TERM", "non defini"))
print("COLORTERM    :", os.environ.get("COLORTERM", "non defini"))
print("WT_SESSION   :", os.environ.get("WT_SESSION", "non defini"))
try:
    import textual

    print("Textual      :", textual.__version__)
    # Tester si Textual peut détecter un terminal
    from textual.app import App

    app = App()
    print("App()        : OK")
except Exception as e:
    print("Textual ERR  :", e)
