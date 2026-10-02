"""NR 2026-10-01 : le cliquet golden ne prend plus un fichier NON LU pour une dette corrigee.

Un fichier illisible rendait un INFO « lecture » au lieu de ses ERROR, et un dossier que `os.walk`
n'ouvrait pas disparaissait du scan : le cliquet comptait les deux comme un RECUL, et `--ecrire-socle`
l'aurait gele. Enquete du jour (33 entrees en baisse) : toutes corrigees dans le code -- mais l'outil
n'aurait rien dit dans le cas contraire. Chemin reel : `main()` avec ses drapeaux.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_golden_rules_ast_non_lu_nr", ROOT / "tools" / "forge_golden_rules_ast.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _arbre(tmp_path):
    d = tmp_path / "code"
    d.mkdir()
    (d / "a.py").write_text("x = 1\n", encoding="utf-8")
    (d / "b.py").write_text("y = 2\n", encoding="utf-8")
    return d


def test_ecrire_socle_refuse_si_un_fichier_est_illisible(tmp_path, monkeypatch, capsys):
    m = _module()
    d = _arbre(tmp_path)
    socle = tmp_path / "socle.json"
    monkeypatch.setattr(m, "SOCLE", str(socle))
    vrai = m.scan_file

    def _scan(path, apprises=None):
        if path.endswith("b.py"):
            return [{"rule": "lecture", "severity": "INFO", "path": "code/b.py", "line": 0,
                     "message": "illisible : acces refuse"}]
        return vrai(path, apprises)
    monkeypatch.setattr(m, "scan_file", _scan)
    monkeypatch.setattr(sys, "argv", ["forge_golden_rules_ast.py", str(d), "--ecrire-socle"])
    assert m.main() == 3
    assert not socle.exists(), "le socle a ete ecrit alors qu'un fichier n'a pas ete lu"
    assert "NON LU" in capsys.readouterr().out


def test_ecrire_socle_refuse_si_un_dossier_n_a_pas_ete_ouvert(tmp_path, monkeypatch, capsys):
    m = _module()
    d = _arbre(tmp_path)
    socle = tmp_path / "socle.json"
    monkeypatch.setattr(m, "SOCLE", str(socle))
    vrai_walk = m.os.walk

    def _walk(top, *a, **k):
        rappel = a[1] if len(a) > 1 else k.get("onerror")
        if rappel is not None:
            rappel(PermissionError(13, "Acces refuse", str(Path(top) / "prive")))
        return vrai_walk(top, *a, **k)
    monkeypatch.setattr(m.os, "walk", _walk)
    monkeypatch.setattr(sys, "argv", ["forge_golden_rules_ast.py", str(d), "--ecrire-socle"])
    assert m.main() == 3
    assert not socle.exists()
    assert "dossier(s) non ouvert(s)" in capsys.readouterr().out


def test_le_cliquet_signale_le_non_lu_sans_bloquer(tmp_path, monkeypatch, capsys):
    """Observer avant d'enforcer : en mode --socle, le non-lu est DIT, pas encore bloquant."""
    m = _module()
    d = _arbre(tmp_path)
    socle = tmp_path / "socle.json"
    socle.write_text('{"par_regle_et_fichier": {}, "depuis_par_cle": {}}', encoding="utf-8")
    monkeypatch.setattr(m, "SOCLE", str(socle))
    monkeypatch.setattr(m, "scan_file", lambda path, apprises=None: [
        {"rule": "lecture", "severity": "INFO", "path": "code/a.py", "line": 0, "message": "illisible"}])
    monkeypatch.setattr(sys, "argv", ["forge_golden_rules_ast.py", str(d), "--socle"])
    assert m.main() == 0
    assert "NON LU : 1 fichier(s)" in capsys.readouterr().out
