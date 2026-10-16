"""NR - la CI de reference se joue en UN etage par defaut (owner 15/10 : accelerer la CI).

Avant : deux etages par script recopie (32 copies dans C:/tmp/corrections), l'etage complet
rejouant toutes les gates deja jouees (~8 min en double sur ~27). `tools/forge_ci_reference.py`
est l'outil unique : un appel `ci_local --reference SHA --turbo`, `--deux-etages` sur demande,
refus d'un sha vide. Aucun ci_local reel n'est lance : l'executeur est simule.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_reference as C  # noqa: E402


def _executeur(rc_par_etage=None):
    appels = []

    def executer(cmd, **_k):
        appels.append(list(cmd))
        rc = 0
        if rc_par_etage and "tools/ci_local.py" in cmd:
            rc = rc_par_etage.get("gates" if "--no-tests" in cmd else "complete", 0)
        return types.SimpleNamespace(returncode=rc, stdout="Tous les gates bloquants passent", stderr="")

    return appels, executer


def _ci_local(appels):
    return [c for c in appels if "tools/ci_local.py" in c]


def test_un_seul_etage_par_defaut(tmp_path):
    appels, ex = _executeur()
    assert C.main(["--sha", "abc123", "--dossier", str(tmp_path)], executer=ex) == 0
    assert "tools/forge_changelog.py" in appels[0]
    (seul,) = _ci_local(appels)
    assert seul[-3:] == ["--reference", "abc123", "--turbo"] and "--no-tests" not in seul
    assert (tmp_path / "ci_complete_abc123.txt").exists()


def test_deux_etages_sur_demande_et_gates_rouges_arretent(tmp_path):
    appels, ex = _executeur({"gates": 1})
    assert C.main(["--sha", "abc123", "--deux-etages", "--dossier", str(tmp_path)], executer=ex) == 1
    (gates,) = _ci_local(appels)
    assert "--no-tests" in gates and "--no-mutation" in gates  # la suite complete n'est PAS lancee


def test_deux_etages_verts_jouent_les_deux(tmp_path):
    appels, ex = _executeur()
    assert C.main(["--sha", "abc123", "--deux-etages", "--dossier", str(tmp_path)], executer=ex) == 0
    assert [("--no-tests" in c) for c in _ci_local(appels)] == [True, False]


def test_sha_vide_refuse_sans_rien_lancer(tmp_path):
    appels, ex = _executeur()
    assert C.main(["--sha", "   ", "--dossier", str(tmp_path)], executer=ex) == 2
    assert appels == []


def test_point_d_entree_reel_exige_un_sha():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_ci_reference.py")],
                       capture_output=True, text=True, errors="replace", timeout=60, cwd=str(ROOT))
    assert r.returncode == 2 and "--sha" in (r.stderr + r.stdout)
