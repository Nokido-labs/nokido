"""NR -- reprise sans commit et faux signal « LIVRAISON INCOMPLETE » (6-7/11).

1. Worktree repris (travail non committe de la MEME tache) : `_sales_avant` ne doit pas exclure ce travail, sinon
   « commits produits : 0 ; fichiers non commites : 3 » et la tache finit done sans livrer.
2. `_fichiers_non_livres` ne cite que les fichiers DECLARES produits ; une mention negative ne compte pas.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("reprise_exec_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["reprise_exec_nr"] = m
    spec.loader.exec_module(m)
    return m


def _git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def test_reprise_ne_exclut_pas_le_travail_repris(ex, tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / ".claude_headless_mcp.json").write_text("{}")
    ex._WT_REPRIS.add(str(tmp_path.resolve()))
    try:
        avant = ex._sales_avant_de(tmp_path)
    finally:
        ex._WT_REPRIS.discard(str(tmp_path.resolve()))
    assert "a.py" not in avant
    # hors reprise : l'etat sale d'avant reste exclu (comportement historique)
    assert "a.py" in ex._sales_avant_de(tmp_path)


def test_mention_negative_ne_compte_pas(ex, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(
                            a, 0, stdout=" M config/agent_identities.json\n?? docs/rendu.md\n", stderr=""))
    txt = "Je n'ai pas touche config/agent_identities.json.\nFichier produit : docs/rendu.md"
    res = ex._fichiers_non_livres(txt)
    assert [c for c, _ in res] == ["docs/rendu.md"]


def test_artefact_declare_absent_reste_signale(ex, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="?? docs/rendu.md\n", stderr=""))
    txt = '{"intent":"OK_DONE","pointer_ref":"docs/rendu.md"}'
    assert [c for c, _ in ex._fichiers_non_livres(txt)] == ["docs/rendu.md"]
