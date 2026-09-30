"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_040314_astdoc
#FORGE:[score:85|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +4 docs
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
import sys, time, gc

sys.path.insert(0, "app")
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Static
from nokido_agent.app.skilltree import SkillTree

CYCLES = 0


class MiniApp(App):
    """Miniapp."""

    def compose(self) -> ComposeResult:
        """Compose."""
        yield Static("test")
        yield SkillTree(learner=None, id="sk-test")

    async def on_mount(self):
        """On mount."""
        t = self.query_one("#sk-test", SkillTree)
        # Simuler beaucoup d'updates comme en prod
        skills = [
            "python_async",
            "Async/IO",
            "devops_containers",
            "reseau_dns",
            "securite_audit",
            "python_data",
            "systeme_linux",
        ]
        for s in skills:
            t.add_or_update_skill(s, "learning")
        # Mise à jour répétée
        for i in range(50):
            for s in skills:
                t.add_or_update_skill(s, "verified" if i % 2 == 0 else "learning")
        self.set_timer(0.5, self.exit)


async def run_once():
    """Run once."""
    app = MiniApp()
    await app.run_async(headless=True)


# Lancer 10 cycles et surveiller la RAM
import os

try:
    import psutil

    proc = psutil.Process(os.getpid())
    has_psutil = True
except ImportError:
    has_psutil = False

print("=== SANDBOX RAM TEST ===")
for cycle in range(10):
    asyncio.run(run_once())
    gc.collect()
    if has_psutil:
        ram = proc.memory_info().rss / 1024**2
        print(f"Cycle {cycle + 1:2d}/10 — RAM: {ram:.1f} MB")
    else:
        print(f"Cycle {cycle + 1:2d}/10 — OK")

print("=== FIN SANDBOX — pas de crash ===")
