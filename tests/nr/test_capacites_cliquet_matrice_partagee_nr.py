"""NR (owner 9/11 « intègre capacites-cliquet convenablement ») : le cliquet de capacites MESURE en CI de reference.

Constat du 9/11 (CI de reference af7a1d5d1, job_1e55f10838d1) : « [skip] capacites-cliquet : matrice absente de CET
arbre (regression_matrix.json) -- NON MESURE ». La matrice est une DONNEE d'usage (tiree de network_log), jamais
versionnee ; le worktree de reference, materialise depuis un sha, ne peut donc pas la porter. Le gate la cherchait
pourtant sous la racine du worktree : NON MESURE a chaque CI de reference, par construction.

Correctif : la CI de reference transmet le chemin de la matrice de l'arbre partage par `NOKIDO_REGMATRIX` (meme canal
que `NOKIDO_PROOF_DIR`) ; `forge_regression_matrix.MATRIX` et le gate de `ci_local` lisent ce chemin. Le registre
d'outils, lui, reste lu dans le worktree : la donnee d'usage vient du partage, le code juge vient du sha.
"""
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_LOCAL = ROOT / "tools" / "ci_local.py"


def test_la_matrice_suit_nokido_regmatrix(monkeypatch, tmp_path):
    cible = tmp_path / "partage" / "regression_matrix.json"
    monkeypatch.setenv("NOKIDO_REGMATRIX", str(cible))
    from nokido_agent.tools import forge_regression_matrix as RM
    RM = importlib.reload(RM)
    try:
        assert Path(RM.MATRIX) == cible
    finally:
        monkeypatch.delenv("NOKIDO_REGMATRIX")
        importlib.reload(RM)


def test_sans_variable_la_matrice_reste_sous_sandbox(monkeypatch):
    monkeypatch.delenv("NOKIDO_REGMATRIX", raising=False)
    from nokido_agent.tools import forge_regression_matrix as RM
    RM = importlib.reload(RM)
    assert Path(RM.MATRIX).parts[-2:] == ("sandbox", "regression_matrix.json")


def test_la_ci_de_reference_transmet_la_matrice_partagee():
    src = CI_LOCAL.read_text(encoding="utf-8")
    # le contexte de reference voyage par l'environnement : la matrice doit y etre, a cote de NOKIDO_PROOF_DIR
    i = src.index('_env["NOKIDO_PROOF_DIR"]')
    assert '_env["NOKIDO_REGMATRIX"]' in src[i - 1500: i + 1500]


def test_le_gate_lit_le_chemin_transmis():
    src = CI_LOCAL.read_text(encoding="utf-8")
    m = re.search(r"_matrice_cap\s*=\s*(.+)", src)
    assert m, "affectation de _matrice_cap introuvable"
    assert "NOKIDO_REGMATRIX" in m.group(1)
