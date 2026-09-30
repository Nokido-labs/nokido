"""NR — outils de debug CI : EFFET (pas import). Comble le cliquet NR-coverage des 2
modules ajoutes le 2026-09-15.

- `forge_ci_github_log` : le filtre `_PAT` sépare les lignes d'ERREUR du bruit bénin.
- `forge_restore_from_head` : restaure RÉELLEMENT un fichier depuis HEAD (repo git tmp).

Hermétique : repo git en tmp, aucun réseau, aucun gh réel.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.56)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ci_github_log as GL  # noqa: E402
import forge_restore_from_head as RH  # noqa: E402


def test_github_log_filtre_retient_les_erreurs():
    for erreur in (
        "Traceback (most recent call last):",
        "E   AssertionError: boum",
        "tests/nr/x.py::test_y FAILED",
        "Process completed with exit code 1",
        "ModuleNotFoundError: no module named x",
        "===== 3 failed, 1 passed =====",
    ):
        assert GL._PAT.search(erreur), erreur


def test_github_log_filtre_ignore_le_benin():
    for benin in (
        "installing dependencies",
        "un commentaire tout a fait ordinaire",
        "checkout du depot en cours",
    ):
        assert not GL._PAT.search(benin), benin


def test_github_log_sans_arg_ne_plante_pas():
    # EFFET du garde d'usage : rc 2 sans run_id (pas d'appel reseau)
    argv0 = sys.argv
    try:
        sys.argv = ["forge_ci_github_log.py"]
        assert GL.main() == 2
    finally:
        sys.argv = argv0


def _git(repo, *a):
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *a],
                   check=True, capture_output=True, text=True, errors="replace")


def test_restore_ramene_la_version_committee(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    f = repo / "f.txt"
    f.write_text("ORIG\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")
    f.write_text("MODIFIE\n", encoding="utf-8")          # working tree diverge de HEAD

    monkeypatch.setattr(RH, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["forge_restore_from_head.py", "f.txt"])
    rc = RH.main()

    assert rc == 0
    assert f.read_text(encoding="utf-8") == "ORIG\n"     # restauré depuis HEAD


def test_restore_sans_arg_refuse(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["forge_restore_from_head.py"])
    assert RH.main() == 2
