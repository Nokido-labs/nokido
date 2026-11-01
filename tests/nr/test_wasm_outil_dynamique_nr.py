"""NR 29/10 (owner : pilote WASM S19, « le gain en securite ne doit pas etre neglige ») -- forge_call_dynamic retombait
en execution DANS le processus du hub quand le bac a sable etait indisponible (repli ouvert, « jamais bloquer »).
Sous l'interrupteur sandbox/dynamic_wasm.switch, l'outil s'execute en WASM (CPython WASI sous wasmtime : seul son
dossier monte, pas de reseau, memoire et duree plafonnees) ; WASM indisponible = REFUS, jamais de repli in-process.
Chemin REEL (wasmtime + python.wasm installes) ; absents : le test est saute en le DISANT, jamais compte vert."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

# MEMES objets module que ceux qu'utilise forge_tool_forger (import par nokido_agent.app) : sinon un monkeypatch
# viserait une copie et le test du refus prouverait du vide.
from nokido_agent.app import forge_sandbox_exec as SX  # noqa: E402
from nokido_agent.app import forge_tool_forger as TF  # noqa: E402

_WASM_PRET = SX.wasm_pret()


def _outil(tmp_path, monkeypatch, corps):
    f = tmp_path / "outil_test.py"
    f.write_text(corps, encoding="utf-8")
    monkeypatch.setattr(TF, "_tool_path", lambda name: f)
    monkeypatch.setattr(TF, "_FICHIER_WASM_DYNAMIQUE", tmp_path / "dynamic_wasm.switch")
    (tmp_path / "dynamic_wasm.switch").write_text("pilote S19", encoding="utf-8")

    def interdit(name):
        raise AssertionError("execution in-process interdite sous l'interrupteur WASM")
    monkeypatch.setattr(TF, "_load_tool", interdit)


@pytest.mark.skipif(not _WASM_PRET, reason="wasmtime ou python.wasm absent : chemin WASM ILLISIBLE ici")
def test_outil_execute_en_wasm(tmp_path, monkeypatch):
    _outil(tmp_path, monkeypatch, "def outil_test(a, b):\n    return a + b\n")
    assert TF.forge_call_dynamic("outil_test", a=2, b=3) == {"result": 5, "tool": "outil_test", "isolation": "wasm"}


@pytest.mark.skipif(not _WASM_PRET, reason="wasmtime ou python.wasm absent : chemin WASM ILLISIBLE ici")
def test_outil_ne_lit_pas_hors_de_son_dossier(tmp_path, monkeypatch):
    _outil(tmp_path, monkeypatch, "def outil_test():\n    return open('C:/Windows/win.ini').read()[:10]\n")
    r = TF.forge_call_dynamic("outil_test")
    assert "error" in r and "result" not in r


def test_wasm_indisponible_refus_sans_repli(tmp_path, monkeypatch):
    _outil(tmp_path, monkeypatch, "def outil_test():\n    return 1\n")
    monkeypatch.setattr(SX, "WASMTIME", str(tmp_path / "absent.exe"))
    r = TF.forge_call_dynamic("outil_test")
    assert "error" in r and "WASM" in r["error"] and "result" not in r
