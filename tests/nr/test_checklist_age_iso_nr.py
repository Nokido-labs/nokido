"""NR -- la checklist ne fabrique plus un age negatif sur une date ISO (8/11).

Mesure : audit doc du 8/11, `contrat UI genere` « mesure vieille de -1.0 h » alors que genere_le valait
2026-09-26T18:43:29 (43 jours) : float() echouait sur l'ISO et la sentinelle -1.0 s'affichait comme un age.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_feature_checklist as fc  # noqa: E402

T0 = datetime(2026, 11, 8, 12, 0, 0).timestamp()


def test_date_iso_donne_un_age_positif():
    age = fc._age_heures("2026-11-08T10:00:00", maintenant=T0)
    assert age is not None and abs(age - 2.0) < 1e-6


def test_epoch_reste_lu():
    assert abs(fc._age_heures(T0 - 7200, maintenant=T0) - 2.0) < 1e-6


def test_date_illisible_rend_none_pas_une_sentinelle():
    assert fc._age_heures("pas une date", maintenant=T0) is None
    assert fc._age_heures(None, maintenant=T0) is None


def test_contrat_ancien_de_43_jours():
    age = fc._age_heures("2026-09-26T18:43:29", maintenant=T0)
    assert age is not None and age > 24 * 40
