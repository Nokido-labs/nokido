"""NR : la proprioception ne balaye plus la base RAG, et ne rend plus de zeros.

Cause MESUREE le 2026-09-17 par le veilleur de gel du webhub, qui a photographie
la scene au lieu de la deviner. Deux piles, dans le meme dump :

    forge_anatomy_state.py:219  _rag_stats
    forge_anatomy_state.py:407  get_anatomy_state
    forge_parietal_fusion.py:82 fuse
    forge_vitals_tools.py:58    parietal_percept
    app/web_hub/app.py:968      vital_api          <- la route /vitals
    anyio/_backends/_asyncio.py:986 run            <- ouvrier du threadpool

`_rag_stats` faisait DEUX balayages complets de `rag_chunks` (24,9 Go) a chaque
appel. La route qui l'appelle est declaree `def`, donc synchrone : chaque requete
immobilise un ouvrier anyio pendant tout le balayage, et `/health` -- synchrone
lui aussi -- se met en file derriere. Vu du dehors : port LISTENING, process
vivant, sonde muette. La campagne UI a conclu SERVICE MORT EN COURS DE PASSE.

Le remede etait DEJA prescrit dans les regles du depot -- lire le snapshot du
producteur, ecrit hors du chemin chaud -- il n'avait simplement pas ete applique
ici. Ce NR verrouille les deux moities du contrat :

  1. AUCUN SQL n'est emis. On ne le verifie pas en relisant le code : on pose un
     espion sur l'ouverture de connexion, et on echoue si elle est appelee.
  2. Une mesure absente rend `None`, JAMAIS zero. L'ancienne version rendait
     `{0, 0, 0}` sur absence de base ET sur exception : une cecite devenait donc
     une mesure a vide, ce qui se lit comme un fait.
"""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE / "app") not in sys.path:
    sys.path.insert(0, str(RACINE / "app"))


@pytest.fixture()
def anat():
    return importlib.import_module("forge_anatomy_state")


class _EspionConnexion:
    """Refuse toute ouverture de connexion et retient l'appel."""

    def __init__(self):
        self.appels: list[str] = []

    def __call__(self, *a, **k):
        self.appels.append(str(a[0]) if a else "<sans argument>")
        raise AssertionError(
            "connexion SQLite ouverte depuis le chemin chaud : c'est exactement "
            "le balayage qui immobilisait un ouvrier du threadpool et rendait "
            "/health muet"
        )


def test_rag_stats_n_ouvre_aucune_connexion(anat, monkeypatch):
    espion = _EspionConnexion()
    monkeypatch.setattr(sqlite3, "connect", espion)
    res = anat._rag_stats()
    assert espion.appels == [], f"connexion(s) ouverte(s) : {espion.appels}"
    assert isinstance(res, dict)
    for cle in ("chunks", "embedded", "pending", "mesure", "raison"):
        assert cle in res, f"la cle {cle!r} manque : le contrat n'est pas tenu"


def test_une_mesure_absente_rend_none_et_jamais_zero(anat, monkeypatch):
    """Snapshot injoignable -> INCONNU dit, pas un corps a vide."""
    def _snapshot_absent(*a, **k):
        return {"frais": False, "vector_pending": None, "age_s": None,
                "raison": "aucun snapshot (test)"}

    import forge_memory_availability as fma
    monkeypatch.setattr(fma, "snapshot", _snapshot_absent)
    monkeypatch.setattr(sqlite3, "connect", _EspionConnexion())
    res = anat._rag_stats()
    assert res["mesure"] == "INCONNU"
    assert res["embedded"] is None, (
        "un compteur inconnu rendu a 0 se lit comme une base vide : c'est la "
        "confusion CECITE / MESURE que la constitution interdit"
    )
    assert res["raison"], "l'inconnu doit porter son motif, sinon il est muet"


def test_un_snapshot_frais_rend_les_compteurs(anat, monkeypatch):
    def _snapshot_frais(*a, **k):
        return {"frais": True, "total": 1_300_000, "vector_pending": 210_797,
                "age_s": 42.0, "raison": ""}

    import forge_memory_availability as fma
    monkeypatch.setattr(fma, "snapshot", _snapshot_frais)
    monkeypatch.setattr(sqlite3, "connect", _EspionConnexion())
    res = anat._rag_stats()
    assert res["mesure"] == "SNAPSHOT"
    assert res["chunks"] == 1_300_000
    assert res["pending"] == 210_797
    assert res["embedded"] == 1_300_000 - 210_797


def test_l_etat_anatomique_survit_a_une_mesure_absente(anat, monkeypatch):
    """Le pourcentage ne s'invente pas, et rien ne leve en aval."""
    def _snapshot_absent(*a, **k):
        return {"frais": False, "vector_pending": None, "age_s": None,
                "raison": "aucun snapshot (test)"}

    import forge_memory_availability as fma
    monkeypatch.setattr(fma, "snapshot", _snapshot_absent)
    monkeypatch.setattr(sqlite3, "connect", _EspionConnexion())
    # le calcul d'activite doit tolerer un pourcentage inconnu
    valeur = anat._organ_activity("brain_worker", {}, anat._rag_stats(), None)
    assert 0.0 <= valeur <= 1.0, (
        "un pourcentage inconnu ne doit ni lever ni fabriquer un bonus "
        "d'activite : on ne deduit rien d'une mesure absente"
    )


# --------------------------------------------------------- controle NEGATIF


def test_l_espion_sait_refuser():
    """Un test qui ne sait pas echouer ne prouve rien quand il passe."""
    espion = _EspionConnexion()
    with pytest.raises(AssertionError):
        espion("n_importe_quelle.db")
    assert espion.appels == ["n_importe_quelle.db"], (
        "l'espion n'enregistre pas l'appel qu'il vient de refuser"
    )
