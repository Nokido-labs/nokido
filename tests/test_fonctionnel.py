"""
test_fonctionnel.py — Tests fonctionnels Nokido v13
Vérifie les bugs A+B et le routing NLU hors TUI.
Usage : python tests/test_fonctionnel.py (depuis la racine LaForge/)
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


# ════════════════════════════════════════════════════════════
# 1. BUG-A : SHELL_COMMANDS existe dans forge_llm
# ════════════════════════════════════════════════════════════
print("\n═══ BUG-A : SHELL_COMMANDS ═══")
try:
    from forge_llm import SHELL_COMMANDS
    check("Import SHELL_COMMANDS", True)
    check("Type frozenset", isinstance(SHELL_COMMANDS, frozenset), f"got {type(SHELL_COMMANDS)}")
    check("Contient 'ls'", "ls" in SHELL_COMMANDS)
    check("Contient 'docker'", "docker" in SHELL_COMMANDS)
    check(">= 50 entrées", len(SHELL_COMMANDS) >= 50, f"seulement {len(SHELL_COMMANDS)}")
except Exception as e:
    check("Import SHELL_COMMANDS", False, str(e))


# ════════════════════════════════════════════════════════════
# 2. BUG-B : TTLCache importable dans forge_orchestrator
# ════════════════════════════════════════════════════════════
print("\n═══ BUG-B : TTLCache ═══")
try:
    from cachetools import TTLCache as _TTC
    check("cachetools installé", True)
except ImportError as e:
    check("cachetools installé", False, str(e))

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "forge_orchestrator",
        os.path.join(os.path.dirname(__file__), "..", "app", "forge_orchestrator.py"),
    )
    with open(spec.origin, "r", encoding="utf-8") as f:
        src = f.read()
    check("'from cachetools import TTLCache' présent", "from cachetools import TTLCache" in src)
    check("TTLCache utilisé (instanciation)", "TTLCache(" in src)
except Exception as e:
    check("Vérification forge_orchestrator", False, str(e))


# ════════════════════════════════════════════════════════════
# 3. IntentClassifier hors TUI
# ════════════════════════════════════════════════════════════
print("\n═══ IntentClassifier (hors TUI) ═══")
try:
    from forge_llm import IntentClassifier, AgentType
    ic = IntentClassifier()
    check("Instanciation IntentClassifier", True)

    test_cases = [
        ("ls -la /tmp",               AgentType.ACTION, "shell cmd direct"),
        ("docker ps",                  AgentType.ACTION, "shell cmd docker"),
        ("bonjour",                    AgentType.CHAT,   "chat starter"),
        ("oui merci",                  AgentType.CHAT,   "chat conv courte"),
        ("qu'est-ce que kubernetes ?", AgentType.CHAT,   "question FR → CHAT"),
        ("git status",                 AgentType.ACTION, "shell cmd git"),
        ("cat /etc/passwd",            AgentType.ACTION, "shell cmd cat"),
    ]

    for text, expected, desc in test_cases:
        try:
            result, cmd = ic.classify_with_cmd(text)
            check(f"classify '{text}' → {expected.value}",
                  result == expected,
                  f"got {result.value} (cmd={cmd})")
        except Exception as e:
            check(f"classify '{text}'", False, f"CRASH: {e}")

except Exception as e:
    check("Import IntentClassifier", False, str(e))


# ════════════════════════════════════════════════════════════
# 4. Dépendances __main__
# ════════════════════════════════════════════════════════════
print("\n═══ Dépendances __main__ ═══")
try:
    from forge_llm import settings as llm_settings
    val = llm_settings.ollama_url
    check("settings.ollama_url hors TUI → None (pas de crash)", val is None, f"got {val!r}")
    val2 = llm_settings.max_concurrent_tasks
    check("settings.max_concurrent_tasks hors TUI → None", val2 is None, f"got {val2!r}")
except Exception as e:
    check("SettingsProxy hors TUI", False, f"CRASH: {e}")


# ════════════════════════════════════════════════════════════
# 5. AutocompleteEngine — cohérence commandes
# ════════════════════════════════════════════════════════════
print("\n═══ AutocompleteEngine ═══")
try:
    import re as _re

    with open(os.path.join(os.path.dirname(__file__), "..", "app", "forge_orchestrator.py"),
              "r", encoding="utf-8") as f:
        src = f.read()

    # Commandes @ déclarées dans AutocompleteEngine
    at_cmds_auto = set(_re.findall(
        r'"(@\w+)"',
        src.split("class AutocompleteEngine")[1].split("sub_commands")[0]
    ))

    # Commandes @ gérées — cherche dans forge_handlers.py + Nokido.py
    # (refactor v2 : les handlers sont importés depuis forge_handler_*.py)
    at_cmds_handle = set()
    for fname in ["Nokido.py", "forge_handlers.py"]:
        fpath = os.path.join(os.path.dirname(__file__), "..", "app", fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            fsrc = f.read()
        # Cherche dans _handle_at
        if "async def _handle_at" in fsrc:
            block = fsrc.split("async def _handle_at")[1].split("\n        async def ")[0]
            at_cmds_handle |= set(_re.findall(r'cmd\s*==\s*"(@\w+)"', block))
        # Cherche aussi les imports depuis forge_handler_*
        # _handle_rag importé = @rag géré, etc.
        for m in _re.finditer(r'from forge_handler_(\w+) import.*?_handle_(\w+)', fsrc):
            at_cmds_handle.add(f"@{m.group(2)}")

    missing = at_cmds_auto - at_cmds_handle

    check(f"Autocomplete: {len(at_cmds_auto)} commandes déclarées", len(at_cmds_auto) > 0)
    check(f"_handle_at: {len(at_cmds_handle)} commandes gérées", len(at_cmds_handle) > 0,
          "0 commandes — vérifier forge_handlers.py ou Nokido.py")
    check("Toutes les @ autocomplete sont dans _handle_at",
          len(missing) == 0,
          f"manquantes dans handler: {missing}")

except Exception as e:
    check("Cohérence commandes @", False, str(e))


# ════════════════════════════════════════════════════════════
print(f"\n{'═'*50}")
print(f"  RÉSULTAT : {PASS} ✅  /  {FAIL} ❌")
print(f"{'═'*50}")

# ── Verdict — NE PAS appeler sys.exit() au niveau module ──
# pytest importe ce fichier → sys.exit() causerait un INTERNALERROR
# Utiliser if __name__ == '__main__' pour l'usage CLI
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
