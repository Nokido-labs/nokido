"""NR 18/10 -- le capteur de derive memoire ne presente plus une entree PERIMEE comme courante (audit RAM, owner).

Mesure du 18/10 21:49 : service_rss_state gardait NokidoLlamaNative a 5,11 Go (0 echantillon, dernier releve 26 min
plus tot -- le serveur 7B avait ete reveille par un appelant non identifie puis endormi par le RESOURCE_MANAGER en
49 s). Lue comme courante, cette entree a fait annoncer « 5 Go tenus » a tort. Critere sans seuil invente : chaque
passe horodate a l'identique tout ce qu'elle mesure ; une entree ABSENTE de la derniere passe est PERIMEE, rendue
avec son age, jamais rangee « sain » ni « derive ».
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_service_rss_watch as W  # noqa: E402

T = 1_792_352_894.0


def _etat(tmp_path, monkeypatch, etat):
    f = tmp_path / "service_rss_state.json"
    f.write_text(json.dumps(etat), encoding="utf-8")
    monkeypatch.setattr(W, "ETAT", f)
    monkeypatch.setattr(W, "_registre", lambda: {k: 1 for k in etat})


def test_entree_absente_de_la_derniere_passe_est_perimee(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch, {
        "Courant": {"pid": 1, "grandeur": "private", "rss_min": 0.7, "rss_dernier": 0.71, "n": 26, "dernier_ts": T},
        "Fige": {"pid": 2, "grandeur": "private", "rss_min": None, "rss_dernier": 5.11, "n": 0, "dernier_ts": T - 1560},
    })
    d = {x["service"]: x for x in W.derives()}
    assert d["Fige"]["etat"] == "perime" and d["Fige"]["age_min"] == 26
    assert d["Courant"]["etat"] == "sain"


def test_une_seule_passe_rien_n_est_perime(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch, {
        "A": {"pid": 1, "grandeur": "private", "rss_min": 0.5, "rss_dernier": 0.5, "n": 6, "dernier_ts": T},
        "B": {"pid": 2, "grandeur": "private", "rss_min": 0.4, "rss_dernier": 0.4, "n": 6, "dernier_ts": T},
    })
    assert {x["etat"] for x in W.derives()} == {"sain"}
