# -*- coding: utf-8 -*-
"""Non-regression — le circadien LIT ce que son ecrivain ECRIT.

Mesure du 2026-09-08, en verifiant si les cycles nocturnes avaient tourne (question
owner). Le circadien tourne bien : `sandbox/circadian_state.json` portait les six
phases, NREM1 comprise. Mais :

    sur le DISQUE   : {"last_fired": {"NREM1": ..., "AURORE": ..., ...}}   6 phases
    en MEMOIRE      : PhysiologicalState.last_completed = {}               0 phase

`load_state()` cherche la cle `last_completed`, le fichier porte `last_fired` — ecrit
par un autre producteur. Le dict lu est donc TOUJOURS VIDE, `debt_hours()` rend `inf`
pour toute phase, et `has_sleep_debt()` (dette > 48 h sur NREM1 ou NREM3) est VRAI en
PERMANENCE. Mesure APRES correctif : NREM1 41,3 h et NREM3 37,3 h — le corps dormait
tres bien pendant qu'il se declarait en dette.

Un garde qui crie toujours est un garde desarme : on cesse de le lire. Et c'est le
motif deja paye plusieurs fois dans ce depot — un lecteur et un ecrivain qui ne
parlent pas le meme mot, sans que rien ne le signale, parce que l'absence de cle
retombe silencieusement sur un defaut vide.

Le correctif ne change pas l'ecrivain : il rend le LECTEUR capable des deux formes.
Ecraser le format en place casserait le producteur reel, qu'on ne controle pas ici.

Hermetique : fichiers d'etat fabriques en tmp_path, chemin injecte. Aucune phase
declenchee, aucun service.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_circadian as C  # noqa: E402


def _ecrire_etat(tmp_path, payload) -> Path:
    p = tmp_path / "circadian_state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_lit_le_format_REELLEMENT_ecrit_sur_disque(monkeypatch, tmp_path):
    """`last_fired` est ce que le producteur ecrit — c'est lui qui fait autorite."""
    hier = time.time() - 3600.0
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_fired": {"NREM1": hier}}))
    st = C.load_state()
    assert C.Phase.NREM1 in st.last_completed
    assert 0.9 < st.debt_hours(C.Phase.NREM1) < 1.1


def test_lit_encore_l_ancien_format(monkeypatch, tmp_path):
    """Compatibilite : on ne casse pas un etat ecrit sous l'ancienne cle."""
    hier = time.time() - 7200.0
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_completed": {"NREM3": hier}}))
    st = C.load_state()
    assert C.Phase.NREM3 in st.last_completed
    assert 1.9 < st.debt_hours(C.Phase.NREM3) < 2.1


def test_une_phase_JAMAIS_tiree_reste_une_dette_infinie(monkeypatch, tmp_path):
    """`inf` doit rester le verdict quand il n'y a VRAIMENT rien — pas par defaut."""
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_fired": {"NREM1": time.time()}}))
    st = C.load_state()
    assert st.debt_hours(C.Phase.REM) == float("inf")


def test_une_phase_INCONNUE_du_fichier_ne_casse_pas_la_lecture(monkeypatch, tmp_path):
    """Un nom de phase retire du code ne doit pas rendre l'etat entier illisible."""
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_fired": {"PHASE_DISPARUE": 1.0,
                                                               "NREM1": time.time()}}))
    st = C.load_state()
    assert C.Phase.NREM1 in st.last_completed


def test_le_corps_ne_croit_plus_en_dette_permanente(monkeypatch, tmp_path):
    """Le symptome mesure : has_sleep_debt vrai en permanence sur un corps sain."""
    frais = time.time() - 600.0
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_fired": {"NREM1": frais,
                                                               "NREM3": frais}}))
    st = C.load_state()
    assert st.has_sleep_debt() is False


def test_une_VRAIE_dette_reste_signalee(monkeypatch, tmp_path):
    """Symetrie : le correctif ne doit pas eteindre le garde, seulement le rendre juste."""
    vieux = time.time() - 60 * 3600.0
    monkeypatch.setattr(C, "_STATE_PATH",
                        _ecrire_etat(tmp_path, {"last_fired": {"NREM1": vieux,
                                                               "NREM3": vieux}}))
    st = C.load_state()
    assert st.has_sleep_debt() is True


def test_un_fichier_illisible_ne_ment_pas(monkeypatch, tmp_path):
    """Illisible n'est pas 'a jour' : on retombe sur un etat vide, donc en dette."""
    p = tmp_path / "circadian_state.json"
    p.write_text("{ pas du json", encoding="utf-8")
    monkeypatch.setattr(C, "_STATE_PATH", p)
    st = C.load_state()
    assert st.debt_hours(C.Phase.NREM1) == float("inf")
