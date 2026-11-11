"""NR -- `--ecrire` n'ecrase plus un doc complet par un rendu ILLISIBLE ; `--verifier` dit ILLISIBLE, pas PERIME (8/11).

Mesure : sous le compte sandbox (job_68e775f29aa3), 01_SCHEMA rendu en 3 824 car. « ILLISIBLE » contre ~61 000 sur
disque : --ecrire l'aurait remplace, et --verifier le disait PERIME (fausse derive).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_spec_extractor as fse  # noqa: E402

COMPLET = "# 01 schema\n\n" + "| table | colonne |\n" * 50


def _monter(tmp_path, monkeypatch, rendu):
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "01_SCHEMA.md").write_text(COMPLET, encoding="utf-8")
    monkeypatch.setattr(fse, "ROOT", tmp_path)
    monkeypatch.setattr(fse, "rendre_tout", lambda: {"01_SCHEMA.md": rendu})
    return specs / "01_SCHEMA.md"


def test_ecrire_garde_le_doc_complet_si_rendu_illisible(tmp_path, monkeypatch):
    p = _monter(tmp_path, monkeypatch, "# 01 schema\n\nILLISIBLE (PermissionError)\n")
    assert fse.main(["--ecrire"]) == 1
    assert p.read_text(encoding="utf-8") == COMPLET


def test_forcer_ecrit_quand_meme(tmp_path, monkeypatch):
    p = _monter(tmp_path, monkeypatch, "# 01 schema\n\nILLISIBLE (PermissionError)\n")
    assert fse.main(["--ecrire", "--forcer"]) == 0
    assert "ILLISIBLE" in p.read_text(encoding="utf-8")


def test_ecrire_un_rendu_lisible_ecrit(tmp_path, monkeypatch):
    p = _monter(tmp_path, monkeypatch, "# 01 schema\n\n| neuf |\n")
    assert fse.main(["--ecrire"]) == 0
    assert "neuf" in p.read_text(encoding="utf-8")


def test_verifier_dit_illisible_pas_perime(tmp_path, monkeypatch, capsys):
    _monter(tmp_path, monkeypatch, "# 01 schema\n\nILLISIBLE (PermissionError)\n")
    rc = fse.main(["--verifier"])
    out = capsys.readouterr().out
    assert rc == 1, "ILLISIBLE n'est jamais range FRAIS (liste blanche)"
    assert "ILLISIBLE" in out and "PERIME" not in out.split("BILAN")[0]
