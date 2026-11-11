# -*- coding: utf-8 -*-
"""NR owner 4/11 (« observabilite parfaite ») : une lecture de 30 ms echappe a un echantillonnage a 1 s.

Le hub note donc ce qu'il ouvre (hook d'audit, anneau en memoire) et, quand ses compteurs sautent, ecrit qui venait
d'ouvrir quoi. Le hook ne doit jamais casser son porteur, le saut sans ouverture recente se dit, et l'interrupteur coupe
la lecture des compteurs a chaque tick.
"""
import importlib
import json
import sys
import threading
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
S = importlib.import_module("forge_fils_hub")


@pytest.fixture(autouse=True)
def anneau_vide():
    S._ANNEAU.clear()
    S._ARMEE["muet"] = False
    yield
    S._ANNEAU.clear()
    S._ARMEE["muet"] = False


def test_le_hook_note_l_ouverture_d_une_base_avec_son_appelant():
    S._noter_audit("sqlite3.connect", ("C:/x/m2m.db",))
    e = S._ANNEAU[-1]
    assert e["ev"] == "sqlite3.connect" and e["chemin"] == "C:/x/m2m.db"
    assert any("test_le_hook_note" in f for f in e["pile"]), "l'appelant est tout l'interet de la sonde"


def test_la_sonde_ne_se_compte_pas_elle_meme():
    """Mesure 4/11 : son propre journal occupait jusqu'a 18 des 20 ouvertures rendues, et masquait les vraies."""
    S._noter_audit("open", (str(S._JOURNAL), "a", 0))
    assert not S._ANNEAU


def test_le_hook_ignore_le_reste_et_ne_leve_jamais():
    S._noter_audit("compile", (b"x", "y"))
    assert not S._ANNEAU
    S._noter_audit("open", (3, "r", 0))       # descripteur, pas un chemin
    S._noter_audit("open", ())                # forme inattendue
    S._noter_audit("sqlite3.connect", None)   # forme inattendue : le hook tourne dans TOUT le hub


def _tick(valeurs, etat, ecrits, actif=True, maintenant=100.0):
    return S.tick_lectures(lire=lambda: valeurs, ecrire=ecrits.append, etat=etat, actif=lambda: actif, maintenant=maintenant)


def test_la_premiere_mesure_sert_de_reference_et_un_petit_debit_ne_dit_rien():
    etat, ecrits = {}, []
    _tick((1_000_000_000, 100), etat, ecrits)
    assert not ecrits, "le cumul depuis le demarrage n'est pas une rafale"
    _tick((1_001_000_000, 300), etat, ecrits)
    assert not ecrits


def test_un_saut_ecrit_le_volume_et_ce_qui_venait_d_etre_ouvert():
    etat, ecrits = {}, []
    _tick((0, 0), etat, ecrits, maintenant=100.0)
    S._ANNEAU.append({"t": 99.5, "ev": "sqlite3.connect", "chemin": "m2m.db", "fil": "f", "pile": ["a"]})
    S._ANNEAU.append({"t": 90.0, "ev": "open", "chemin": "vieux.log", "fil": "f", "pile": ["b"]})
    _tick((30_000_000, 7330), etat, ecrits, maintenant=100.1)
    assert len(ecrits) == 1
    r = ecrits[0]
    assert r["mo"] == 30.0 and r["lectures"] == 7330 and r["octets_par_lecture"] == 4092
    assert [o["chemin"] for o in r["ouvertures"]] == ["m2m.db"], "seulement la fenetre recente"
    assert "fils" in r, "les piles du moment accompagnent le saut"


def test_un_saut_sans_ouverture_recente_le_dit():
    etat, ecrits = {}, []
    _tick((0, 0), etat, ecrits, maintenant=100.0)
    _tick((55_000_000, 13300), etat, ecrits, maintenant=100.1)
    assert ecrits[0]["ouvertures"] == []
    assert "connexion deja ouverte" in ecrits[0]["note"], "un vide n'est pas une absence de cause"


def test_l_interrupteur_coupe_la_lecture_et_oublie_la_reference():
    etat, ecrits, lus = {"prec": (0, 0)}, [], []

    def lire():
        lus.append(1)
        return (99_000_000, 1)
    S.tick_lectures(lire=lire, ecrire=ecrits.append, etat=etat, actif=lambda: False, maintenant=1.0)
    assert not lus and not ecrits
    assert "prec" not in etat, "sinon la reprise fabriquerait un faux saut"


def test_un_compteur_illisible_ne_tue_pas_le_surveillant(caplog):
    def lire():
        raise PermissionError("refuse")
    etat, ecrits = {}, []
    S.tick_lectures(lire=lire, ecrire=ecrits.append, etat=etat, actif=lambda: True, maintenant=1.0)
    assert not ecrits


def test_armer_est_idempotent(monkeypatch):
    hooks, fils = [], []

    class Faux:
        def __init__(self, *a, **k):
            fils.append(k.get("name"))

        def start(self):
            pass
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    monkeypatch.setattr(threading, "Thread", Faux)
    monkeypatch.setitem(S._ARMEE, "fait", False)
    S.armer_sonde_lectures()
    S.armer_sonde_lectures()
    assert len(hooks) == 1 and len(fils) == 1, "un hook d'audit ne se retire pas : le poser deux fois serait definitif"


def test_le_journal_est_du_jsonl_borne(tmp_path, monkeypatch):
    p = tmp_path / "hub_lectures.jsonl"
    monkeypatch.setattr(S, "_JOURNAL", p)
    monkeypatch.setattr(S, "_JOURNAL_MAX_O", 400)
    for i in range(40):
        S._ecrire({"i": i, "bourre": "x" * 40})
    lignes = p.read_text(encoding="utf-8").splitlines()
    assert json.loads(lignes[-1])["i"] == 39, "la rotation garde le recent"
    assert p.stat().st_size <= 800
