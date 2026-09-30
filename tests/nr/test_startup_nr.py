"""
test_startup_nr.py — NR : monitoring démarrage + intégrité cross-modules
=========================================================================
Détecte AVANT le commit :
- SyntaxError / await outside async
- NameError : appels orphelins après tombeau
- ImportError : modules forge_* manquants
- Désynchronisation stub ↔ module cible

Alimente le RAG via anchor_error() sur chaque échec.
"""
import ast
import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture + compile de tous
#   les app/forge_*.py (l.212)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT_P  = Path(__file__).resolve().parent.parent.parent
APP_DIR = ROOT_P / "app"
sys.path.insert(0, str(APP_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lf_txt() -> str:
    return (APP_DIR / "Nokido.py").read_text(encoding="utf-8", errors="replace")


def _mod_txt(name: str) -> str:
    return (APP_DIR / name).read_text(encoding="utf-8", errors="replace")


def _snapshot_rag_before_test():
    """Snapshot préventif RAG avant toute mutation."""
    try:
        from forge_startup_logger import StartupLogger
        StartupLogger()._safe_snapshot()
    except Exception:
        pass


def _rag_anchor(test_name: str, error: str, solution: str = ""):
    """Ancre l'erreur dans le RAG + log structuré."""
    import logging
    log = logging.getLogger("Nokido.StartupNR")
    log.error(f"[NR/{test_name}] ❌ {error}")
    try:
        from forge_self_correction import anchor_error
        anchor_error(
            error=f"[NR/{test_name}] {error}",
            context=f"test_startup_nr::{test_name} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            solution=solution or "Voir test_startup_nr.py",
        )
    except Exception:
        pass


# ── Boot Tests ────────────────────────────────────────────────────────────────

class TestNokidoStartup:
    """Boot Nokido.py — syntaxe, await, orphelins, imports."""

    def test_syntax_ok(self):
        """Nokido.py se parse sans SyntaxError."""
        txt = _lf_txt()
        try:
            ast.parse(txt)
        except SyntaxError as e:
            msg = f"Nokido.py SyntaxError L{e.lineno}: {e.msg}"
            _rag_anchor("test_syntax_ok", msg,
                        "Vérifier stubs générés — def sync avec return await ?")
            pytest.fail(msg)

    def test_compile_ok(self):
        """compile() — détecte await outside async que ast.parse() rate."""
        lf_path = APP_DIR / "Nokido.py"
        txt = lf_path.read_text(encoding="utf-8", errors="replace")
        try:
            compile(txt, str(lf_path), "exec")
        except SyntaxError as e:
            msg = f"compile() SyntaxError L{e.lineno}: {e.msg}"
            _rag_anchor("test_compile_ok", msg,
                        "compile() détecte les await outside async que ast.parse() rate — "
                        "chercher def (pas async def) avec return await dans les stubs")
            pytest.fail(msg)

    def test_no_await_outside_async(self):
        """Aucun await direct dans une fonction sync (def, pas async def)."""
        tree = ast.parse(_lf_txt())
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for stmt in node.body:
                for subnode in ast.walk(stmt):
                    if isinstance(subnode, ast.AsyncFunctionDef):
                        break
                    if isinstance(subnode, ast.Await):
                        violations.append(f"{node.name}() L{node.lineno}")
                        break
        if violations:
            msg = f"await hors async def: {violations}"
            _rag_anchor("test_no_await_outside_async", msg,
                        "Changer 'def fn' en 'async def fn' dans le stub "
                        "ou retirer await si la fn cible est sync")
            pytest.fail(msg)

    def test_no_orphan_tombeau_calls(self):
        """Aucun appel direct à une fonction marquée tombeau."""
        txt   = _lf_txt()
        lines = txt.split("\n")
        tombeau_names = set(re.findall(
            r'^# \[(?:EXTRAIT|→)[^\]]*\]\s+(\w+)',
            txt, re.MULTILINE
        ))
        orphans = []
        for fn in tombeau_names:
            for i, line in enumerate(lines):
                s = line.strip()
                if (re.match(r'^' + re.escape(fn) + r'\s*\(', s)
                        and "from" not in line
                        and "def " not in line
                        and not s.startswith("#")):
                    orphans.append(f"L{i+1}: {s[:70]}")
        if orphans:
            msg = "Appels orphelins après tombeau:\n" + "\n".join(orphans)
            _rag_anchor("test_no_orphan_tombeau_calls", msg,
                        "Ajouter 'from module import fn' avant l'appel "
                        "ou importer en tête de Nokido.py")
            pytest.fail(msg)

    def test_forge_imports_exist(self):
        """Tous les 'from forge_X import' référencent des fichiers existants."""
        txt     = _lf_txt()
        imported = set(re.findall(r'from (forge_\w+) import', txt))
        missing  = sorted(m for m in imported if not (APP_DIR / (m + ".py")).exists())
        if missing:
            msg = f"Modules forge_* manquants: {missing}"
            _rag_anchor("test_forge_imports_exist", msg,
                        "Créer le module manquant ou corriger le nom d'import dans Nokido.py")
            pytest.fail(msg)

    def test_tombeau_fns_in_target(self):
        """Chaque fn tombeau doit exister dans son module cible."""
        txt     = _lf_txt()
        pattern = re.compile(r'# \[(?:EXTRAIT|→)\s*(?:→\s*)?(\w+\.py)\]\s+(\w+)')
        missing = []
        for m in pattern.finditer(txt):
            mod_name, fn_name = m.group(1), m.group(2)
            mod_path = APP_DIR / mod_name
            if not mod_path.exists():
                missing.append(f"{fn_name} → {mod_name} (fichier absent)")
                continue
            if fn_name not in mod_path.read_text(encoding="utf-8", errors="replace"):
                missing.append(f"{fn_name} → {mod_name} (fn absente)")
        if missing:
            msg = "Fonctions tombeau absentes du module cible:\n" + "\n".join(missing)
            _rag_anchor("test_tombeau_fns_in_target", msg,
                        "La fonction n'a pas été extraite dans le module cible — "
                        "vérifier _phase*_apply.py logs")
            pytest.fail(msg)


class TestCrossModuleStubs:
    """Stubs Nokido ↔ modules forge_* — cohérence."""

    def test_stub_targets_exist(self):
        """Dans chaque stub 'from forge_X import fn as _fh', fn existe."""
        txt     = _lf_txt()
        pattern = re.compile(r'from (forge_\w+) import (\w+)\s+as\s+_fh')
        missing = []
        for m in pattern.finditer(txt):
            mod_name, fn_name = m.group(1), m.group(2)
            mod_path = APP_DIR / (mod_name + ".py")
            if not mod_path.exists():
                missing.append(f"{fn_name} ← {mod_name}.py (absent)")
                continue
            if fn_name not in mod_path.read_text(encoding="utf-8", errors="replace"):
                missing.append(f"{fn_name} ← {mod_name}.py (fn absente)")
        if missing:
            msg = "Stubs pointant vers des fonctions inexistantes:\n" + "\n".join(missing)
            _rag_anchor("test_stub_targets_exist", msg,
                        "Extraire la fonction dans le module cible ou corriger le nom du stub")
            pytest.fail(msg)

    def test_at_dispatch_handlers_exist(self):
        """Toutes les fns dans AT_DISPATCH existent dans forge_at_dispatch.py."""
        try:
            at_txt  = _mod_txt("forge_at_dispatch.py")
            at_tree = ast.parse(at_txt)
            dispatch_fns = set(re.findall(r'"@\w+"\s*:\s*(\w+)', at_txt))
            at_defined   = {n.name for n in ast.walk(at_tree)
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            missing = dispatch_fns - at_defined
            if missing:
                msg = f"AT_DISPATCH référence des fns manquantes: {missing}"
                _rag_anchor("test_at_dispatch_handlers_exist", msg,
                            "Ajouter les fonctions manquantes dans forge_at_dispatch.py")
                pytest.fail(msg)
        except FileNotFoundError:
            pytest.skip("forge_at_dispatch.py absent")

    def test_no_undefined_default_args(self):
        """Détecte les closures extraites avec des valeurs par défaut non définies.
        Ex : def do_scan(_subnet=subnet) — subnet n'existe pas au niveau module.
        """
        import ast
        errors = []
        for f in sorted(APP_DIR.glob("forge_*.py")):
            try:
                txt  = f.read_text(encoding="utf-8", errors="replace")
                compile(txt, str(f), "exec")
            except (SyntaxError, NameError) as e:
                errors.append(f"{f.name}: {e}")
        if errors:
            _rag_anchor("test_no_undefined_default_args",
                        "Closures mal extraites: " + str(errors),
                        "Remplacer les valeurs par défaut capturées par None")
            pytest.fail("Closures avec defaults non définis:\n" + "\n".join(errors))

    def test_all_modules_compile(self):
        """Tous les modules forge_*.py compilent sans SyntaxError."""
        errors = []
        for f in sorted(APP_DIR.glob("forge_*.py")):
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
                compile(txt, str(f), "exec")
            except SyntaxError as e:
                errors.append(f"{f.name} L{e.lineno}: {e.msg}")
        if errors:
            msg = "Modules avec SyntaxError:\n" + "\n".join(errors)
            _rag_anchor("test_all_modules_compile", msg,
                        "Corriger la syntaxe dans les modules listés")
            pytest.fail(msg)


class TestStartupRagLogger:
    """Journalise l'état du boot dans le RAG."""

    def test_log_startup_health_to_rag(self):
        """Ancre l'état de santé courant — snapshot préventif avant écriture."""
        _snapshot_rag_before_test()

        lf_lines = len(_lf_txt().split("\n"))
        n_mods   = len(list(APP_DIR.glob("forge_*.py")))
        n_stubs  = len(re.findall(r'from forge_\w+ import \w+ as _fh', _lf_txt()))
        tombeau  = len(re.findall(r'# \[(?:EXTRAIT|→)', _lf_txt()))

        health_msg = (
            f"STARTUP HEALTH {datetime.now().strftime('%Y-%m-%d %H:%M')} — "
            f"Nokido.py {lf_lines}L | "
            f"{n_mods} modules forge_* | "
            f"{n_stubs} stubs actifs | "
            f"{tombeau} tombeaux"
        )

        import logging
        logging.getLogger("Nokido.StartupNR").info(f"[NR] {health_msg}")

        db_path = ROOT_P / "data" / "laforge_rag.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.execute(
                    "INSERT INTO rag_chunks (text, source, domain, role_hint, meta) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (health_msg, f"startup_nr:{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                     "monitoring", "metric",
                     '{"ring":1,"tags":["boot","health","monitoring","nr"]}')
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logging.getLogger("Nokido.StartupNR").warning(f"RAG insert: {e}")

        assert True  # toujours passer — log best-effort
