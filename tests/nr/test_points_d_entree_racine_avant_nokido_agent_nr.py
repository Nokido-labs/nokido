"""NR -- tout point d'entree Python d'un service rend la RACINE importable AVANT `nokido_agent`.

Mesure du 2026-09-24 (verite terrain = journaux des services) : 6 services mouraient en
`ModuleNotFoundError: No module named 'nokido_agent'` a chaque demarrage -- Hebbian (386 fois),
QdrantSync (285), GateConsumer (279), Capture (329), DeportEmbed (514), GeminiAutonomous (4 038).
`nokido_agent` est un dossier de la RACINE ; deux classes de defaut :
  - ORDRE : l'insertion venait APRES l'import (QdrantSync ; Hebbian, dont le bloc d'amorce avait
    ete injecte juste apres l'import qu'il devait rendre possible) ;
  - CHEMIN : on ajoutait app/ ou tools/ (le dossier du script), jamais la racine.
Meme famille que le 05/09 (test_heartbeat_amorce_syspath_nr), mais hors de sa portee (batteurs).
Un 1er instrument (rejeu des prefixes) rendait des FAUX POSITIFS, dont le hub : la regle retenue
ici est celle qui a donne 0 violation une fois l'alias `_sys_amorce` reconnu.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les
#   tools/*.py (l.94)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
TOML = ROOT / "proxy_deno" / "core" / "services.toml"
CORRIGES = {
    "app/forge_hebbian_linker.py", "tools/forge_qdrant_sync_daemon.py", "app/forge_gate_consumer.py",
    "tools/cli_tail_capture.py", "tools/forge_reindex_deport.py", "tools/forge_gemini_autonomous_agent.py",
}
RACINE_ECRITE = ("ROOT", "_RACINE_AMORCE", "parent.parent", "parents[1]")


def _nka(x) -> bool:
    return ((isinstance(x, ast.ImportFrom) and (x.module or "").startswith("nokido_agent"))
            or (isinstance(x, ast.Import) and any(a.name.startswith("nokido_agent") for a in x.names)))


def _mute(y) -> bool:
    """Insertion dans `<alias de sys>.path` (insert/append) -- `_sys_amorce.path` compte."""
    for c in ast.walk(y):
        if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("insert", "append")
                and isinstance(c.func.value, ast.Attribute) and c.func.value.attr == "path"):
            return True
    return False


def _violation(corps) -> int | None:
    for i, x in enumerate(corps):
        if _nka(x):
            ok = any(_mute(y) for y in corps[:i]
                     if not isinstance(y, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            return None if ok else x.lineno
    return None


def _entrees():
    d = tomllib.load(TOML.open("rb"))
    for s in d["service"]:
        if not str(s.get("cmd", "")).startswith("${PY"):
            continue
        cwd = Path(str(s.get("cwd", "${ROOT}")).replace("${ROOT}", str(ROOT)))
        a = [str(x) for x in s.get("args", [])]
        f = (cwd / (a[a.index("-m") + 1] + ".py")) if "-m" in a else next(
            (cwd / x for x in a if x.endswith(".py")), None)
        if f and f.exists():
            yield s["name"], f


def test_aucun_import_nokido_agent_avant_son_amorce():
    fautes = []
    vus = 0
    for nom, f in _entrees():
        vus += 1
        ligne = _violation(ast.parse(f.read_text(encoding="utf-8", errors="replace")).body)
        if ligne:
            fautes.append("%s (%s L%d)" % (nom, f.name, ligne))
    assert vus >= 40, "moins de points d'entree lus que mesure (~70) : le lecteur ne voit plus le TOML"
    assert not fautes, "import nokido_agent AVANT toute insertion dans sys.path :\n  " + "\n  ".join(fautes)


def test_les_six_corriges_ajoutent_la_racine():
    for rel in sorted(CORRIGES):
        corps = ast.parse((ROOT / rel).read_text(encoding="utf-8")).body
        inserts = [ast.unparse(y) for y in corps
                   if not isinstance(y, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and _mute(y)]
        texte = "\n".join(inserts) + "\n" + "\n".join(
            ast.unparse(y) for y in corps if isinstance(y, (ast.Assign, ast.AnnAssign)))
        assert inserts and any(k in texte for k in RACINE_ECRITE), (
            "%s n'ajoute plus la RACINE au chemin d'import (app/ ou tools/ ne suffisent pas)" % rel)


def test_aucun_outil_n_importe_nokido_agent_avant_son_amorce():
    """Meme defaut HORS des services (mesure 2026-09-26 : 12 outils sur 1261, dont
    forge_ui_coherence -- ModuleNotFoundError sous le compte du hub). Un outil se lance par
    son chemin (run_job, CI, hooks) : la racine doit etre importable AVANT nokido_agent."""
    fautes, illisibles, vus = [], [], 0
    for f in sorted((ROOT / "tools").glob("*.py")):
        try:
            corps = ast.parse(f.read_text(encoding="utf-8", errors="replace")).body
        except SyntaxError:
            illisibles.append(f.name)
            continue
        vus += 1
        ligne = _violation(corps)
        if ligne:
            fautes.append("%s L%d" % (f.name, ligne))
    assert vus >= 1000, "moins d'outils lus que mesure (1261) : le lecteur ne voit plus tools/"
    assert not illisibles, "outils illisibles par ast -- la regle ne les couvre PAS : %s" % illisibles
    assert not fautes, "import nokido_agent AVANT toute insertion dans sys.path :\n  " + "\n  ".join(fautes)


def test_garde_du_garde_alias_et_ordre():
    ok = ast.parse("import sys as _s\n_s.path.insert(0, 'R')\nfrom nokido_agent.app import x\n").body
    ko = ast.parse("import sys\nfrom nokido_agent.app import x\nsys.path.insert(0, 'R')\n").body
    assert _violation(ok) is None, "l'alias de sys n'est plus reconnu : faux positifs garantis"
    assert _violation(ko) == 2, "une insertion APRES l'import n'est plus detectee"
