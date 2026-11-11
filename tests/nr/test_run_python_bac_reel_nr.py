"""NR : `run action=python sandbox=<bac>` execute dans ce bac, ou refuse. Jamais en natif sans le dire.

Mesure du 2026-11-05 : `run action=python sandbox=wasm` rendait `sys.platform` = win32, lancait
`git --version` et listait `C:\\`, sans refus ni avertissement. La branche python de `handle_run` ne lisait
`sandbox` que pour gvisor : toute autre valeur, meme inconnue, finissait dans l'interpreteur du hub.
La branche shell, elle, refuse depuis le 2026-09-01 (`_sandbox_valide`).

Par le chemin reel : `ToolRegistry.handle_run`, point d'entree de l'outil `run`.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app import forge_sandbox_exec as _sx  # noqa: E402
from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402

JETON = "JETON_EXECUTE_7f3a"
CODE_JETON = "print('%s')" % JETON


def _run(**args) -> str:
    return asyncio.run(ToolRegistry().handle_run({"action": "python", **args}, "CLAUDE", 1))


def test_wasm_tourne_vraiment_en_wasi():
    """Le controle du 5/11, rejoue : plateforme WASI, ni sous-processus ni disque de l'hote."""
    if not _sx.wasm_pret():
        pytest.skip("wasmtime ou python.wasm absent : bac reel non verifiable ici")
    code = (
        "import os, sys\n"
        "print('PLATEFORME', sys.platform)\n"
        "print('DISQUE_HOTE', os.path.exists('C:/Windows') or os.path.exists('/Windows'))\n"
        "try:\n"
        "    import subprocess\n"
        "    print('SOUS_PROCESSUS', subprocess.run(['git', '--version'], capture_output=True).returncode)\n"
        "except Exception as e:\n"
        "    print('SOUS_PROCESSUS_REFUSE', type(e).__name__)\n"
    )
    r = _run(code=code, sandbox="wasm", timeout=60)
    assert "PLATEFORME wasi" in r, r[:400]
    assert "DISQUE_HOTE False" in r, r[:400]
    assert "SOUS_PROCESSUS_REFUSE" in r, r[:400]


def test_wasm_indisponible_refuse_sans_repli_natif(monkeypatch):
    monkeypatch.setattr(_sx, "wasm_pret", lambda: False)
    r = _run(code=CODE_JETON, sandbox="wasm")
    assert JETON not in r, "repli natif : le code a tourne hors du bac"
    assert r.startswith("ERR"), r[:200]
    assert "wasm" in r.lower()


def test_wasm_passe_le_code_sans_laisser_de_trace(monkeypatch):
    """Dossier monte purge, delai transmis, rc non nul visible : l'echec ne se lit pas comme un succes."""
    vus = {}

    def faux(dossier, code, delai_s=20, memoire_octets=0):
        vus["dossier"] = str(dossier)
        vus["delai"] = delai_s
        vus["entree"] = Path(dossier, "entree.py").read_text(encoding="utf-8")
        return 3, "SORTIE", "ERREUR"

    monkeypatch.setattr(_sx, "wasm_pret", lambda: True)
    monkeypatch.setattr(_sx, "executer_wasm", faux)
    r = _run(code=CODE_JETON, sandbox="wasm", timeout=45)
    assert vus["delai"] == 45
    assert CODE_JETON in vus["entree"]
    assert not os.path.exists(vus["dossier"]), "le dossier monte doit se purger seul"
    assert "rc=3" in r and "SORTIE" in r and "ERREUR" in r, r[:200]


def test_wasm_exception_du_pilote_refuse(monkeypatch):
    def faux(*a, **k):
        raise _sx.SandboxError("panne simulee")

    monkeypatch.setattr(_sx, "wasm_pret", lambda: True)
    monkeypatch.setattr(_sx, "executer_wasm", faux)
    r = _run(code=CODE_JETON, sandbox="wasm")
    assert r.startswith("ERR") and "panne simulee" in r and JETON not in r, r[:200]


def test_wasm_avec_reseau_refuse(monkeypatch):
    """WASM n'a aucun reseau : `network=true` ne se taira pas, il serait une promesse fausse."""
    monkeypatch.setattr(_sx, "wasm_pret", lambda: True)
    monkeypatch.setattr(_sx, "executer_wasm", lambda *a, **k: pytest.fail("ne doit pas etre lance"))
    r = _run(code=CODE_JETON, sandbox="wasm", network=True)
    assert r.startswith("ERR") and "network" in r, r[:200]


@pytest.mark.parametrize("bac", ["inexistant", "docker", "windows", "ps_clm", "console"])
def test_bac_non_porte_par_python_refuse(bac):
    """Inconnu ou porte seulement par action=shell : refus, jamais l'interpreteur du hub."""
    r = _run(code=CODE_JETON, sandbox=bac)
    assert JETON not in r, "%s : le code a tourne en natif" % bac
    assert bac in r, r[:200]


@pytest.mark.parametrize("args", [{}, {"sandbox": "local"}, {"sandbox": ""}])
def test_bac_local_reste_inchange(args):
    """Le chemin courant ne bouge pas : c'est lui que tout le monde emprunte."""
    assert JETON in _run(code=CODE_JETON, **args)
