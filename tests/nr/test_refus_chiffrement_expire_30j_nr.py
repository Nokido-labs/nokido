"""NR -- le refus `--sans-chiffrement` EXPIRE a 30 jours (decision owner 2026-10-22).

Ensuite l'installation redemande : chiffrer, ou re-refuser avec motif. Horloge simulee, fichier en tmp_path.
Une date illisible est PERIMEE : un refus n'est jamais valable par defaut.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]
MAINTENANT = datetime.datetime(2026, 11, 30, 12, 0, 0)


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def prerequis(tmp_path, monkeypatch):
    m = _charger("app/forge_install_prerequis.py", "prerequis_refus_30j_nr")
    monkeypatch.setattr(m, "FICHIER_REFUS_CHIFFREMENT", tmp_path / "refus.json")
    monkeypatch.setattr(m, "_maintenant", lambda: MAINTENANT)
    return m


def _ecrire(m, date):
    m.FICHIER_REFUS_CHIFFREMENT.write_text(
        json.dumps({"date": date, "compte": "t", "motif": "banc"}), encoding="utf-8")


def _il_y_a(jours):
    return (MAINTENANT - datetime.timedelta(days=jours)).isoformat(timespec="seconds")


def test_duree_nommee_30_jours(prerequis):
    assert prerequis.DUREE_REFUS_JOURS == 30


def test_refus_de_29_jours_encore_valable(prerequis):
    _ecrire(prerequis, _il_y_a(29))
    assert prerequis.refus_chiffrement()["motif"] == "banc"
    assert prerequis.refus_perime() is None


def test_refus_de_31_jours_perime(prerequis):
    _ecrire(prerequis, _il_y_a(31))
    assert prerequis.refus_chiffrement() is None
    p = prerequis.refus_perime()
    assert p["date"] == _il_y_a(31)
    assert p["echeance"].startswith((MAINTENANT - datetime.timedelta(days=1)).date().isoformat())


@pytest.mark.parametrize("date", ["pas une date", "", None, 12])
def test_date_illisible_perimee(prerequis, date):
    _ecrire(prerequis, date)
    assert prerequis.refus_chiffrement() is None
    assert prerequis.refus_perime() is not None


def test_un_refus_frais_ecrit_par_consigner_est_valable(prerequis, monkeypatch):
    monkeypatch.setattr(prerequis, "_maintenant", datetime.datetime.now)
    prerequis.consigner_refus_chiffrement("m")
    assert prerequis.refus_perime() is None


def test_la_garde_redemande_et_cite_date_et_echeance(prerequis, monkeypatch, capsys):
    _ecrire(prerequis, _il_y_a(31))
    m = _charger("tools/forge_composants.py", "composants_refus_30j_nr")
    monkeypatch.setattr(m, "prerequis", lambda: prerequis)
    poses = []
    monkeypatch.setattr(m, "COMPOSANTS", ("f",))
    monkeypatch.setattr(m, "POSEURS", {"f": lambda: poses.append(1) or (True, "ok")})
    monkeypatch.setattr(m, "chiffrement_present", lambda: False)
    rc = m.main(["--composant", "f"])
    sortie = capsys.readouterr()
    txt = sortie.out + sortie.err
    assert rc == 2 and not poses
    assert _il_y_a(31) in txt and "echeance" in txt.lower() and "--sans-chiffrement" in txt
