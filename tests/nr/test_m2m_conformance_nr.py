# -*- coding: utf-8 -*-
"""Le compteur de conformite M2M doit donner un DENOMINATEUR, pas un ressenti.

Contexte mesure le 2026-09-01 : le bus publiait 2836 `m2m_violation` sur deux
mois et AUCUN message conforme. Un numerateur sans denominateur ne permet pas
de decider si le garde peut passer en mode `error` -- 2836 sur 3000 et 2836 sur
300000 appellent des decisions opposees.

Le test porte sur le POINT DE CONTROLE reel (`forge_m2m_protocol.check`), pas
seulement sur l'utilitaire : un compteur non cable compte zero et se lit comme
un trafic parfait.

Zero service externe : l'etat est redirige vers tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_m2m_conformance as cf  # noqa: E402
import forge_m2m_protocol as mp  # noqa: E402


@pytest.fixture(autouse=True)
def _etat_jetable(monkeypatch, tmp_path):
    monkeypatch.setattr(cf, "_ETAT", tmp_path / "m2m_conformance.json")
    cf.reinitialiser()
    yield
    cf.reinitialiser()


def test_vide_ne_se_lit_pas_comme_un_trafic_nul():
    d = cf.etat()
    assert d["messages_total"] == 0
    # Un taux de 0.0 se lirait « 0 % conforme ». L'absence de mesure est None.
    assert d["taux_conformite"] is None
    assert "reserve" in d, d


def test_compte_total_et_conformes():
    cf.noter("notify", {"code": "M2M_OK", "intent": "OK_DONE"})
    cf.noter("notify", {"code": "M2M_OK_PROSE", "words": 3})
    cf.noter("postal", {"code": "M2M_WARN_PROSE", "words": 40,
                        "violations": ["prose 40 mots > 15"]})
    d = cf.etat()
    assert d["messages_total"] == 3
    assert d["messages_conformes"] == 2
    assert d["non_conformes"] == 1
    assert d["prose_trop_longue"] == 1
    assert d["taux_conformite"] == pytest.approx(2 / 3)
    assert d["par_canal"] == {"notify": 2, "postal": 1}


def test_ventile_les_champs_manquants():
    cf.noter("notify", {"code": "M2M_ERR_MISSING_FIELD",
                        "violations": ["champ intent/intent_code absent",
                                       "champ requis manquant: pointer_ref"]})
    d = cf.etat()
    assert d["missing_intent"] == 1
    assert d["missing_pointer_ref"] == 1


def test_invalid_pointer_ref_est_declare_non_emis():
    """Un zero sans emetteur doit se declarer, sinon il se lit comme une mesure."""
    cf.noter("notify", {"code": "M2M_OK", "intent": "OK_DONE"})
    d = cf.etat()
    assert d["invalid_pointer_ref"] == 0
    assert "invalid_pointer_ref" in d["non_emis"], d


@pytest.mark.parametrize("ref,attendu", [
    (None, "MANQUANT"),
    ("", "MANQUANT"),
    ("   ", "MANQUANT"),
    ("bb:discovered_facts/x", "NON_VERIFIABLE"),
    ("schema_inconnu_xyz", "NON_VERIFIABLE"),
])
def test_pointer_statut_ne_pretend_jamais_avoir_resolu(ref, attendu):
    assert cf.pointer_statut(ref) == attendu


def test_le_compteur_est_cable_au_point_de_controle():
    """Test d'EFFET : c'est `check()` qui doit compter, pas le test.

    Sans ce cas, le module pourrait etre parfait et n'etre appele par personne
    -- le motif « organe correct, aucun emetteur » deja paye deux fois.
    """
    avant = cf.etat()["messages_total"]
    mp.check("notify", {"intent": "OK_DONE", "pointer_ref": "commit abc1234"})
    mp.check("notify", "mot " * 60)
    apres = cf.etat()
    assert apres["messages_total"] == avant + 2, apres
    assert apres["messages_conformes"] == 1, apres
    assert apres["prose_trop_longue"] == 1, apres


def test_un_verdict_illisible_ne_casse_pas_le_canal():
    cf.noter("notify", None)
    cf.noter("notify", "pas un verdict")
    assert cf.etat()["messages_total"] == 0
