"""NR — e-Soleau par EMPREINTES : dossier probatoire compact, calcule sur le COMMIT.

Ce que ce garde verrouille (owner 2026-09-16) :
  - les empreintes sont celles du contenu COMMITE (`git archive`), jamais de l'arbre de
    travail partage — une modification non commitee ne doit PAS entrer dans la preuve ;
  - le dossier tient sous la tranche 15 EUR (< 50 Mo) et ne porte aucun chemin du poste ;
  - le drapeau CLI existe (chemin reel), pas seulement la fonction.

Hermetique : repo git jetable dans tmp_path, aucun reseau.
"""
from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.34)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import launch_public_mirror as L  # noqa: E402

# OCTETS, pas texte : sous Windows `write_text` traduit "\n" en CRLF, et le blob commite
# ne serait plus celui qu'on croit hacher (mesure 2026-09-16 : 10 octets au lieu de 9).
CONTENU_COMMITE = b"print(1)\n"
CONTENU_NON_COMMITE = b"print(2)\n"


def _git(repo: Path, *a: str) -> None:
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *a],
                   check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "alpha")
    _git(repo, "config", "user.email", "nr@test")
    _git(repo, "config", "user.name", "nr")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.py").write_bytes(CONTENU_COMMITE)
    (repo / "docs").mkdir()
    (repo / "docs" / "b.md").write_bytes(b"# b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    # modification NON commitee : doit rester HORS des empreintes
    (repo / "a.py").write_bytes(CONTENU_NON_COMMITE)
    return repo


def test_manifest_hache_le_commit_pas_l_arbre(tmp_path):
    repo = _repo(tmp_path)
    out = L.phase_esoleau_empreintes("alpha", root=repo, out_dir=tmp_path / "out")
    assert out.exists() and out.suffix == ".zip"
    with zipfile.ZipFile(out) as z:
        noms = set(z.namelist())
        assert {"MANIFEST_SHA256.txt", "TREE.txt", "README_IP.txt"} <= noms
        manifest = z.read("MANIFEST_SHA256.txt").decode("utf-8")
    lignes = [l for l in manifest.splitlines() if l.strip()]
    assert len(lignes) == 2, manifest
    attendu = hashlib.sha256(CONTENU_COMMITE).hexdigest()
    interdit = hashlib.sha256(CONTENU_NON_COMMITE).hexdigest()
    ligne_a = next(l for l in lignes if l.endswith("a.py"))
    assert ligne_a.startswith(attendu), ligne_a
    assert interdit not in manifest


def test_taille_sous_la_tranche_et_readme_sans_chemin_du_poste(tmp_path):
    repo = _repo(tmp_path)
    out = L.phase_esoleau_empreintes("alpha", root=repo, out_dir=tmp_path / "out")
    assert out.stat().st_size < 50 * 1024 * 1024
    with zipfile.ZipFile(out) as z:
        readme = z.read("README_IP.txt").decode("utf-8")
        tree = z.read("TREE.txt").decode("utf-8")
    assert "C:\\Users" not in readme and "C:/Users" not in readme
    assert str(tmp_path) not in readme and str(tmp_path) not in tree
    commit = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), "rev-parse", "alpha"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=True).stdout.strip()
    assert commit in readme and commit in tree
    # les docs IP absents de CE commit sont DITS, pas avales
    assert "Absents de ce commit" in readme and "docs/ip/DECISION_PUBLICATION.json" in readme


def test_le_drapeau_cli_existe():
    src = inspect.getsource(L.main)
    assert "--esoleau-empreintes" in src
    assert "phase_esoleau_empreintes(" in src


def test_un_root_hors_racine_est_refuse_pas_une_preuve_vide(tmp_path):
    """Piege mesure 2026-09-16 : un sous-dossier du depot fait remonter git au parent,
    `rev-parse` reussit et `git archive` sort un sous-arbre VIDE — preuve vide sans
    erreur. La phase doit REFUSER (fail-closed), jamais produire un zip."""
    import pytest
    repo = _repo(tmp_path)
    sous = repo / "docs"                      # existe, tracke, mais n'est PAS la racine
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)) as e:
        L.phase_esoleau_empreintes("alpha", root=sous, out_dir=tmp_path / "out")
    if isinstance(e.value, RuntimeError):
        assert "racine" in str(e.value)
    assert not list((tmp_path / "out").glob("*.zip")) if (tmp_path / "out").exists() else True
