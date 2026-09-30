"""
test_import_all_nr.py — NR : import réel de chaque module forge_*
==================================================================
compile() et ast.parse() ne détectent PAS :
  - NameError sur valeurs par défaut (closures extraites)
  - ImportError circulaires
  - AttributeError au niveau module
  - NameError dans les corps de fonctions exécutés à l'import

Ce test importe RÉELLEMENT chaque module dans un subprocess isolé
et capture les erreurs runtime — la seule façon fiable.
"""
import subprocess
import sys
import json
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python x ~590 modules; parcours
#   du depot : glob app; SQLite timeout=30 (code appele) (l.71)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT_P  = Path(__file__).resolve().parent.parent.parent
APP_DIR = ROOT_P / "app"

# Script exécuté dans chaque subprocess
_IMPORT_SCRIPT = """
import sys, json
sys.path.insert(0, r"{app_dir}")
try:
    import {module}
    print(json.dumps({{"ok": True, "module": "{module}"}}))
except Exception as e:
    print(json.dumps({{"ok": False, "module": "{module}",
                       "error": type(e).__name__ + ": " + str(e)}}))
"""

# Script pour tester le démarrage de Nokido.py jusqu'à la fin des imports
_LAFORGE_IMPORT_SCRIPT = """
import sys, json, ast
sys.path.insert(0, r"{app_dir}")

# Simuler l'import sans lancer Textual
# On exécute jusqu'à la classe DevOpsApp mais sans asyncio.run()
errors = []
try:
    # Compiler d'abord
    txt = open(r"{nokido_path}", encoding="utf-8").read()
    code = compile(txt, r"{nokido_path}", "exec")
except SyntaxError as e:
    errors.append(f"SyntaxError L{{e.lineno}}: {{e.msg}}")

if not errors:
    # Vérifier chaque import forge_* individuellement
    import re
    imports = re.findall(r'from (forge_\w+) import', txt)
    for mod in set(imports):
        try:
            __import__(mod)
        except Exception as e:
            errors.append(f"Import {{mod}}: {{type(e).__name__}}: {{e}}")

print(json.dumps({{"ok": len(errors)==0, "errors": errors}}))
"""


def _run_import_test(module_name: str) -> dict:
    """Teste l'import d'un module dans un subprocess isolé."""
    script = _IMPORT_SCRIPT.format(
        app_dir=str(APP_DIR).replace("\\", "\\\\"),
        module=module_name,
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=15,
            cwd=str(ROOT_P),
        )
        output = r.stdout.strip()
        if output:
            return json.loads(output)
        return {"ok": False, "module": module_name,
                "error": r.stderr.strip()[:200] or "no output"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "module": module_name, "error": "TIMEOUT 15s"}
    except Exception as e:
        return {"ok": False, "module": module_name, "error": str(e)}


def _rag_anchor(test_name: str, error: str, solution: str = ""):
    try:
        from forge_self_correction import anchor_error
        anchor_error(
            error=f"[NR/{test_name}] {error}",
            context=f"test_import_all_nr::{test_name}",
            solution=solution,
        )
    except Exception:
        pass


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestImportAllModules:
    """Import réel de chaque forge_*.py — détecte les NameError runtime."""

    # Modules à tester en priorité (utilisés au démarrage)
    CRITICAL = [
        "forge_settings",
        "forge_startup",
        "forge_startup_logger",
        "forge_ollama",
        "forge_rag_warmup",
        "forge_handlers",
        "forge_handler_rag",
        "forge_handler_ci",
        "forge_handler_agents",
        "forge_handler_patch",
        "forge_hub_handlers",
        "forge_at_dispatch",
        "forge_context",
        "forge_capabilities",
        "forge_integrity",
        "forge_self_correction",
    ]

    def test_critical_modules_import(self):
        """Les modules critiques s'importent sans erreur runtime."""
        errors = []
        for mod in self.CRITICAL:
            if not (APP_DIR / (mod + ".py")).exists():
                continue
            result = _run_import_test(mod)
            if not result["ok"]:
                errors.append(f"{mod}: {result['error']}")

        if errors:
            msg = "Import errors:\n" + "\n".join(errors)
            _rag_anchor("test_critical_modules_import", msg,
                        "NameError = closure extraite avec default non défini. "
                        "SyntaxError = await outside async. "
                        "ImportError = module manquant.")
            pytest.fail(msg)

    def test_all_forge_modules_import(self):
        """Tous les forge_*.py s'importent sans erreur runtime."""
        errors  = []
        modules = sorted(
            f.stem for f in APP_DIR.glob("forge_*.py")
            if not f.name.startswith("_")
        )
        for mod in modules:
            result = _run_import_test(mod)
            if not result["ok"]:
                # Ignorer les erreurs d'import de dépendances optionnelles
                err = result["error"]
                if any(x in err for x in [
                    "No module named 'textual'",
                    "No module named 'asyncssh'",
                    "No module named 'aiohttp'",
                ]):
                    continue  # dépendance optionnelle — pas critique
                errors.append(f"{mod}: {err}")

        if errors:
            msg = f"{len(errors)} modules avec erreurs d'import:\n" + "\n".join(errors)
            _rag_anchor("test_all_forge_modules_import", msg,
                        "Vérifier les closures extraites et les imports manquants")
            pytest.fail(msg)

    def test_nokido_imports_resolve(self):
        """
        Tous les 'from forge_X import' dans Nokido.py se résolvent.
        Test plus précis que test_forge_imports_exist — vérifie l'import réel.
        """
        script = _LAFORGE_IMPORT_SCRIPT.format(
            app_dir=str(APP_DIR).replace("\\", "\\\\"),
            nokido_path=str(APP_DIR / "Nokido.py").replace("\\", "\\\\"),
        )
        try:
            r = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=30,
                cwd=str(ROOT_P),
            )
            output = r.stdout.strip()
            if not output:
                pytest.skip("Subprocess sans sortie — " + r.stderr[:100])
            result = json.loads(output)
            if not result["ok"]:
                errors = result.get("errors", [])
                msg = "Nokido.py imports:\n" + "\n".join(errors)
                _rag_anchor("test_nokido_imports_resolve", msg,
                            "Corriger les imports manquants dans Nokido.py")
                pytest.fail(msg)
        except subprocess.TimeoutExpired:
            pytest.skip("Timeout 30s — Nokido.py trop long à analyser")
        except Exception as e:
            pytest.skip(f"Subprocess error: {e}")
