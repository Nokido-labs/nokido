"""NR — le Hybrid Cortex compresse par AST REEL (pas un mock), preserve les
cibles d'edition, et coupe le flux dangereux.

POURQUOI. Avant reparation (audit 2026-08-21), `forge_hybrid_cortex` etait un
organe-coquille : `preflight_triage` renvoyait toujours 'cloud' (TODO Ollama fige)
et la compression passait par un squelette LIGNE-A-LIGNE nomme '_mock', pas par
l'AST que le design promet. Ces tests verrouillent l'EFFET reel : structure sans
corps, Source Exact preserve pour l'edition, kill-switch de securite. Zero reseau.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _zone in ("app", "tools"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mod():
    chemin = ROOT / "app" / "forge_hybrid_cortex.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_hybrid_cortex", chemin)
    m = importlib.util.module_from_spec(spec)
    sys.modules["forge_hybrid_cortex"] = m
    sys.modules["nokido_agent.app.forge_hybrid_cortex"] = m
    spec.loader.exec_module(m)
    return m


SRC = (
    '"""Module doc ligne un.\nsuite ignoree."""\n'
    'import os\n\n'
    'class Foo:\n'
    '    """classe foo."""\n'
    '    def bar(self, x):\n'
    '        secret_value = 12345\n'
    '        return secret_value + x\n\n'
    'def top(a, b):\n'
    '    return a - b\n'
)


def test_skeleton_est_AST_et_masque_le_corps():
    c = _mod().HybridCortex()
    sk = c._generate_skeleton("x.py", SRC)
    # structure presente
    assert "class Foo" in sk
    assert "def bar(self, x): ..." in sk
    assert "def top(a, b): ..." in sk
    assert '"""classe foo."""' in sk
    assert '"""Module doc ligne un."""' in sk
    # corps REEL masque
    assert "secret_value = 12345" not in sk
    assert "return secret_value" not in sk


def test_skeleton_fallback_si_non_parsable():
    c = _mod().HybridCortex()
    sk = c._generate_skeleton("bad.py", "def casse(:\n    pass\n")
    assert "fallback" in sk.lower()


def test_compress_preserve_la_cible_edition():
    c = _mod().HybridCortex()
    gros = SRC + ("# padding pour depasser le seuil\n" * 60)  # > 1500 chars
    ctx = {"files": {"a.py": gros, "cible.py": gros}}
    out = asyncio.run(c._compress_context(ctx, exclude=["cible.py"]))
    assert out["ast_compressed"] is True
    assert "AST SKELETON" in out["files"]["a.py"]      # compresse
    assert out["files"]["cible.py"] == gros            # Source Exact intact


def test_compress_ignore_petit_et_non_py():
    c = _mod().HybridCortex()
    ctx = {"files": {"small.py": "x = 1\n", "data.txt": "y" * 5000}}
    out = asyncio.run(c._compress_context(ctx, exclude=[]))
    assert out["files"]["small.py"] == "x = 1\n"        # trop petit -> intact
    assert out["files"]["data.txt"] == "y" * 5000       # non .py -> intact


def test_stream_prism_kill_switch():
    c = _mod().HybridCortex()
    assert asyncio.run(c.stream_prism("tout va bien, reponse normale")) is True
    assert asyncio.run(c.stream_prism("puis rm -rf / sur la machine")) is False


def test_triage_local_vs_cloud():
    c = _mod().HybridCortex()
    is_cloud_local, _ = c._triage("status", {}, [])
    assert is_cloud_local is False                      # tache locale
    is_cloud_code, _ = c._triage("corrige", {"files": {"a.py": "x=1"}}, [])
    assert is_cloud_code is True                        # code en contexte -> cloud
    is_cloud_edit, _ = c._triage("status", {}, ["a.py"])
    assert is_cloud_edit is True                        # edition -> cloud
