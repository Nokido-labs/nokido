# -*- coding: utf-8 -*-
"""NR — une borne doit dire COMBIEN, pas seulement TROP.

MESURE DU 2026-09-21 (mandat owner « corrige ce gate muet »)
    `forge_git_gate._recidive_warn` affichait `muets[:12]` et s'arretait la.
    Sur `tools/nokido_hub.py` il y avait **22** sites muets. Le gate en
    montrait 12, sans jamais dire qu'il en cachait 10.

    Consequence VECUE le jour meme : huit sites corriges, le gate en affiche
    douze a nouveau -- dont neuf jamais vus avant. Le compte identique d'un
    commit a l'autre se lit « rien n'a bouge », alors que le travail avait
    bien porte. Une borne muette transforme un progres en surplace.

        LA LISTE EST BORNEE, LE DEFAUT NE L'EST PAS

    Meme motif que `text[:3000]` qui avait detruit le corps de 377 documents
    de veille : borner est legitime, taire la coupure ne l'est pas.

SECOND DEFAUT, MESURE EN MEME TEMPS
    Le marqueur d'echappatoire n'etait lu QUE sur la ligne du `except`. Or on
    l'ecrit naturellement sur la ligne du `pass` -- c'est elle qui est muette.
    Sept marqueurs poses de bonne foi n'ont donc RIEN marque, et leurs sites
    sont restes signales.

    L'echappatoire reste EXPLICITE : il faut toujours ecrire `muet-ok`. On
    elargit ou le gate le LIT, jamais ce qu'il exige. Un test symetrique
    verifie qu'un `muet-ok` eloigne n'absout rien.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]


def _gate():
    if str(_RACINE) not in sys.path:
        sys.path.insert(0, str(_RACINE))
    spec = importlib.util.spec_from_file_location(
        "forge_git_gate_nr", _RACINE / "tools" / "forge_git_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fichier_muet(dossier: Path, combien: int, nom: str = "muets.py") -> str:
    corps = "\n".join(
        "def f%d():\n    try:\n        pass\n    except Exception:\n        pass\n" % i
        for i in range(combien))
    (dossier / nom).write_text(corps, encoding="utf-8")
    return nom


def test_le_gate_annonce_le_nombre_total(tmp_path, monkeypatch, capsys):
    """15 sites muets : le total doit apparaitre, pas seulement 12 lignes."""
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    nom = _fichier_muet(tmp_path, 15)
    g._recidive_warn([nom])
    sortie = capsys.readouterr().out
    assert "15" in sortie, (
        "le gate n'annonce pas le TOTAL : un progres reel se lit alors comme "
        "un surplace. Sortie:\n%s" % sortie)


def test_le_gate_dit_ce_qu_il_n_affiche_pas(tmp_path, monkeypatch, capsys):
    """Ce qui est coupe doit etre NOMME, sinon la couverture est surestimee."""
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    nom = _fichier_muet(tmp_path, 15)
    g._recidive_warn([nom])
    sortie = capsys.readouterr().out
    assert "3" in sortie and ("autre" in sortie.lower() or "affich" in sortie.lower()), (
        "les 3 sites coupes ne sont pas annonces. Sortie:\n%s" % sortie)


def test_pas_de_bruit_quand_tout_tient(tmp_path, monkeypatch, capsys):
    """CONTRE-EPREUVE : sous la borne, aucune mention de troncature.

    Un garde qui annonce une coupure inexistante apprend a etre ignore.
    """
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    nom = _fichier_muet(tmp_path, 3)
    g._recidive_warn([nom])
    sortie = capsys.readouterr().out
    assert "3" in sortie
    assert "non affich" not in sortie.lower(), (
        "une troncature est annoncee alors que tout tient : bruit. Sortie:\n%s" % sortie)


def test_le_marqueur_sur_la_ligne_du_except_absout(tmp_path, monkeypatch, capsys):
    """Comportement HISTORIQUE : il ne doit pas regresser."""
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        pass\n"
        "    except Exception:  # muet-ok : voulu\n        pass\n", encoding="utf-8")
    g._recidive_warn(["m.py"])
    assert "MUET" not in capsys.readouterr().out


def test_le_marqueur_sur_la_ligne_du_pass_absout_aussi(tmp_path, monkeypatch, capsys):
    """Sept marqueurs poses la n'ont RIEN marque (mesure 2026-09-21).

    C'est la ligne du `pass` qui est muette : l'auteur y ecrit son marqueur.
    On elargit ou le gate LIT, jamais ce qu'il EXIGE.
    """
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        pass\n"
        "    except Exception:\n        pass  # muet-ok : voulu\n", encoding="utf-8")
    g._recidive_warn(["m.py"])
    sortie = capsys.readouterr().out
    assert "MUET" not in sortie, (
        "un marqueur pose sur la ligne du `pass` n'absout pas : sept l'ont ete "
        "de bonne foi et n'ont rien marque. Sortie:\n%s" % sortie)


def test_un_marqueur_eloigne_n_absout_rien(tmp_path, monkeypatch, capsys):
    """SYMETRIQUE, sans quoi l'elargissement deviendrait une echappatoire.

    Un `muet-ok` dix lignes plus bas ne concerne pas ce handler.
    """
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        pass\n    except Exception:\n        pass\n"
        "\n\n\n\n\n# muet-ok : ce commentaire ne concerne PAS le handler ci-dessus\n",
        encoding="utf-8")
    g._recidive_warn(["m.py"])
    assert "MUET" in capsys.readouterr().out, (
        "un marqueur eloigne a absous un handler : l'echappatoire n'est plus "
        "explicite")


def test_un_handler_qui_trace_n_est_jamais_signale(tmp_path, monkeypatch, capsys):
    """Le gate vise le SILENCE, pas le `except`."""
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    (tmp_path / "m.py").write_text(
        "def f():\n    try:\n        pass\n"
        "    except Exception as e:\n        print(e)\n", encoding="utf-8")
    g._recidive_warn(["m.py"])
    assert "MUET" not in capsys.readouterr().out


def test_les_tests_restent_hors_perimetre(tmp_path, monkeypatch, capsys):
    """Un NR a le droit d'avaler : il construit des cas fautifs expres."""
    g = _gate()
    monkeypatch.setattr(g, "ROOT", tmp_path)
    (tmp_path / "tests").mkdir()
    _fichier_muet(tmp_path / "tests", 20, "test_x.py")
    g._recidive_warn(["tests/test_x.py"])
    assert "MUET" not in capsys.readouterr().out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
