"""
test_await_async_nr.py — NR : vérifier qu'aucun 'await' n'existe dans une fonction sync
Détecte les erreurs "SyntaxError: await outside async function" AVANT le démarrage.
"""
import ast
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   (l.51)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"


def _collect_violations(path: Path) -> list[tuple[str, int, str]]:
    """
    Retourne la liste des fonctions sync contenant un await direct.
    Ignore les closures async internes (async def dans le corps).
    """
    try:
        txt  = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(txt)
    except (SyntaxError, OSError):
        return []

    violations = []

    def _has_direct_await(node: ast.AST) -> bool:
        """Retourne True si node contient un await direct (hors async def imbriquée)."""
        for child in ast.iter_child_nodes(node):
            # Stoppe la descente dans les async def imbriquées
            if isinstance(child, ast.AsyncFunctionDef):
                continue
            if isinstance(child, ast.Await):
                return True
            if _has_direct_await(child):
                return True
        return False

    for node in ast.walk(tree):
        # Seulement les FunctionDef sync (pas AsyncFunctionDef)
        if not isinstance(node, ast.FunctionDef):
            continue
        if _has_direct_await(node):
            violations.append((node.name, node.lineno, path.name))

    return violations


def _all_py_modules() -> list[Path]:
    return [
        f for f in APP_DIR.glob("*.py")
        if not f.name.startswith("_")
    ]


class TestAwaitOutsideAsync:
    """Vérifie qu'aucune fonction sync ne contient un await direct."""

    def test_nokido_no_await_in_sync(self):
        """Nokido.py — aucun await dans une fonction sync."""
        violations = _collect_violations(APP_DIR / "Nokido.py")
        assert violations == [], (
            f"Nokido.py: await dans fonction(s) sync: {violations}"
        )

    def test_forge_handlers_no_await_in_sync(self):
        """forge_handlers.py — aucun await dans une fonction sync."""
        violations = _collect_violations(APP_DIR / "forge_handlers.py")
        assert violations == [], (
            f"forge_handlers.py: await dans fonction(s) sync: {violations}"
        )

    def test_all_modules_no_await_in_sync(self):
        """Tous les modules app/ — aucun await dans une fonction sync."""
        all_violations = []
        for path in _all_py_modules():
            v = _collect_violations(path)
            all_violations.extend(v)

        assert all_violations == [], (
            f"await dans fonctions sync:\n" +
            "\n".join(f"  {name}() L{lineno} dans {mod}"
                      for name, lineno, mod in all_violations)
        )

    def test_nokido_syntax_ok(self):
        """Nokido.py — parse AST sans erreur."""
        txt = (APP_DIR / "Nokido.py").read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(txt)
        except SyntaxError as e:
            pytest.fail(f"Nokido.py SyntaxError L{e.lineno}: {e.msg}")

    def test_all_modules_syntax_ok(self):
        """Tous les modules app/ — parse AST sans erreur."""
        errors = []
        for path in _all_py_modules():
            try:
                ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as e:
                errors.append(f"{path.name} L{e.lineno}: {e.msg}")
        assert errors == [], "Erreurs de syntaxe:\n" + "\n".join(errors)
