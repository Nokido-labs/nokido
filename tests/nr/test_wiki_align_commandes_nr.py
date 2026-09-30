"""NR -- l'aligneur du wiki renomme les commandes du cutover, et SEULEMENT quand le code le prouve.

Revue des pages > 60 j (2026-09-29) : 110 citations de `laforge-secrets` / `laforge-vault` /
`laforge-cli` / `laforge-hub`, commandes renommees `nokido-*` au cutover. Contrat :
  - cible declaree dans [project.scripts] ET source absente -> remplacee ;
  - sinon NON appliquee, et dit ;
  - `laforge-hub` jamais touche (c'est aussi le service Docker du compose) ;
  - ni `laforge-vault-x` (autre mot), ni `logs/laforge-cli.log` (un fichier).
Chemin reel : main() sur un wiki et un pyproject temporaires.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_OK = '[project]\nname = "x"\n\n[project.scripts]\nnokido-vault = "a:b"\nnokido-secrets = "a:c"\nnokido-cli = "a:d"\n\n[tool.x]\n'
PAGE = ("`laforge-vault list` puis laforge-secrets diag ; lancer laforge-cli.\n"
        "docker compose build laforge-hub ; laforge-vault-x reste ; tail logs/laforge-cli.log\n")


def _aligneur(tmp_path, monkeypatch, pyproject):
    spec = importlib.util.spec_from_file_location("nr_wiki_align", ROOT / "tools" / "forge_wiki_align.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "p.md").write_text(PAGE, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    monkeypatch.setattr(m, "WIKI", str(wiki))
    monkeypatch.setattr(m, "PYPROJECT", str(tmp_path / "pyproject.toml"))
    monkeypatch.setattr(sys, "argv", ["forge_wiki_align.py"])
    return m, wiki / "p.md"


def test_les_commandes_declarees_sont_renommees_et_rien_d_autre(tmp_path, monkeypatch):
    m, page = _aligneur(tmp_path, monkeypatch, PYPROJECT_OK)
    assert m.main() == 0
    t = page.read_text(encoding="utf-8")
    assert "`nokido-vault list`" in t and "nokido-secrets diag" in t and "lancer nokido-cli." in t
    assert "build laforge-hub" in t                     # service Docker : jamais touche
    assert "laforge-vault-x" in t                       # un autre mot
    assert "logs/laforge-cli.log" in t                  # un fichier, pas la commande


def test_une_cible_non_declaree_n_est_pas_appliquee_et_c_est_dit(tmp_path, monkeypatch, capsys):
    m, page = _aligneur(tmp_path, monkeypatch, '[project.scripts]\nnokido-vault = "a:b"\n')
    m.main()
    t = page.read_text(encoding="utf-8")
    assert "nokido-vault list" in t and "laforge-secrets diag" in t and "laforge-cli." in t
    assert "NON appliquees" in capsys.readouterr().out


def test_une_page_generee_n_est_jamais_retouchee(tmp_path, monkeypatch):
    m, page = _aligneur(tmp_path, monkeypatch, PYPROJECT_OK)
    generee = page.parent / "20-Modules-Reference.md"
    contenu = "<!-- nokido:genere outil=tools/forge_wiki_modules.py -->\nlaforge-vault et forge_mcts\n"
    generee.write_text(contenu, encoding="utf-8")
    m.main()
    assert generee.read_text(encoding="utf-8") == contenu


def test_une_source_encore_declaree_n_est_pas_renommee():
    spec = importlib.util.spec_from_file_location("nr_wiki_align2", ROOT / "tools" / "forge_wiki_align.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sures, ecartees = m.commandes_sures('[project.scripts]\nlaforge-vault = "a"\nnokido-vault = "b"\n')
    assert "laforge-vault" not in sures and "laforge-vault" in ecartees
