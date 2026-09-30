"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_040314_astdoc
#FORGE:[score:85|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +14 docs
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
sandbox_nokido.py — Test headless complet Nokido v0.13.2
Simule le boot TUI sans lancer la vraie TUI (headless=True)
Vérifie : compose(), on_mount(), walk_children, skill_map, render()
"""
import sys, asyncio, gc, time

sys.path.insert(0, "app")

import psutil, os

proc = psutil.Process(os.getpid())

results = []


def check(name, fn):
    """Check."""
    try:
        fn()
        results.append(f"  ✅ {name}")
    except Exception as e:
        results.append(f"  ❌ {name} : {e}")


# ─── TEST 1 : AST de tous les fichiers modifiés ──────────────────────────────
import ast, pathlib


def test_ast():
    """Test ast."""
    files = ["Nokido.py", "skilltree.py", "brain_worker.py", "forge_runtime.py"]
    for f in files:
        ast.parse(open(f, encoding="utf-8").read())


check("AST tous fichiers", test_ast)


# ─── TEST 2 : Import skilltree + collision _nodes ────────────────────────────
def test_skilltree_import():
    """Test skilltree import."""
    from nokido_agent.app.skilltree import SkillTree, SkillNode

    t = SkillTree()
    assert type(t._nodes).__name__ == "NodeList", f"_nodes = {type(t._nodes)}"
    assert hasattr(t, "_skill_map")


check("skilltree import + _nodes OK", test_skilltree_import)


# ─── TEST 3 : render() retourne Text ─────────────────────────────────────────
def test_render():
    """Test render."""
    from nokido_agent.app.skilltree import SkillNode
    from rich.text import Text

    for status in ["unknown", "searching", "learning", "verified", "mastered"]:
        n = SkillNode("Async/IO", "python_async", depth=1)
        n._reactive_status = status
        r = n.render()
        assert isinstance(r, Text), f"render() → {type(r)} pour status={status}"


check("SkillNode.render() → Text", test_render)

# ─── TEST 4 : Mini TUI headless avec SkillTree ───────────────────────────────
from textual.app import App, ComposeResult
from textual.widgets import Static
from nokido_agent.app.skilltree import SkillTree, SkillLearner

CRASH_INFO = []


class SandboxApp(App):
    """Sandboxapp."""

    def compose(self) -> ComposeResult:
        """Compose."""
        yield Static("sandbox")
        yield SkillTree(learner=None, id="sk-test")

    async def on_mount(self):
        """On mount."""
        try:
            t = self.query_one("#sk-test", SkillTree)
            # Simuler add_or_update avec noms problématiques
            for name, status in [
                ("python_async", "learning"),
                ("Async/IO", "searching"),  # slash → était le crash
                ("general", "verified"),
                ("devops", "mastered"),
            ]:
                t.add_or_update_skill(name, status)
        except Exception as e:
            CRASH_INFO.append(str(e))
        self.set_timer(0.3, self.exit)


async def test_tui():
    """Test tui."""
    app = SandboxApp()
    await app.run_async(headless=True)
    if CRASH_INFO:
        raise RuntimeError(f"on_mount crash: {CRASH_INFO}")


def run_tui():
    """Run tui."""
    asyncio.run(test_tui())


check("Mini TUI headless SkillTree", run_tui)

# ─── TEST 5 : 5 cycles TUI pour vérifier stabilité RAM ───────────────────────
ram_before = proc.memory_info().rss / 1024**2


async def run_cycle():
    """Run cycle."""
    app = SandboxApp()
    await app.run_async(headless=True)


def test_ram_stability():
    """Test ram stability."""
    for _ in range(5):
        asyncio.run(run_cycle())
        gc.collect()
    ram_after = proc.memory_info().rss / 1024**2
    delta = ram_after - ram_before
    if delta > 50:
        raise RuntimeError(f"Fuite RAM : +{delta:.0f}MB sur 5 cycles")


check("Stabilité RAM 5 cycles", test_ram_stability)


# ─── TEST 6 : Version bumped ──────────────────────────────────────────────────
def test_version():
    """Test version."""
    import re

    src = open("Nokido.py", encoding="utf-8").read()
    v = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', src).group(1)
    assert v == "0.13.2", f"Version = {v}, attendu 0.13.2"


check("Version 0.13.2", test_version)


# ─── TEST 7 : brain_worker load_generator=False ───────────────────────────────
def test_brain_worker_no_gen():
    """Test brain worker no gen."""
    src = open("brain_worker.py", encoding="utf-8").read()
    assert "load_generator: bool = False" in src
    assert "BrainService(port=args.port, load_generator=False)" in src


check("brain_worker load_generator=False", test_brain_worker_no_gen)


# ─── TEST 8 : forge_runtime load_generator=False ─────────────────────────────
def test_forge_runtime_no_gen():
    """Test forge runtime no gen."""
    src = open("forge_runtime.py", encoding="utf-8").read()
    assert "load_generator: bool = False" in src


check("forge_runtime load_generator=False", test_forge_runtime_no_gen)

# ─── Rapport final ────────────────────────────────────────────────────────────
ram_final = proc.memory_info().rss / 1024**2
print()
print("═══ SANDBOX v0.13.2 ═══════════════════════")
for r in results:
    print(r)
fails = sum(1 for r in results if "❌" in r)
print("───────────────────────────────────────────")
print(f"RAM finale : {ram_final:.0f} MB")
print(f"{'✅ SANDBOX OK' if fails == 0 else f'❌ {fails} FAIL(S)'}")
print("═══════════════════════════════════════════")
sys.exit(fails)
