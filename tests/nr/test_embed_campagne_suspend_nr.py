"""NR — une garde de charge SUSPEND la campagne, elle ne l'abandonne pas.

Mesure 2026-09-06 : la campagne de vectorisation locale (40 lots) s'est arretee au
lot 2 sur un `ARRET_RAM` alors qu'une fenetre d'attente etait configuree. Defaut de
CONCEPTION, pas de garde : « pas maintenant » avait ete code comme « plus jamais ».
L'owner venait de demander que l'autoregulation fonctionne : un corps qui se retient
sous charge doit REPRENDRE quand la charge tombe.

Trois garanties, sur une campagne simulee (aucun service, aucun reseau) :
  1. un lot arrete par la garde ne consomme PAS son tour : la campagne fait bien N lots
     utiles, meme si des lots sont suspendus entre-temps ;
  2. sans fenetre d'attente configuree, un `ARRET_RAM` arrete la campagne (il n'y a rien
     a attendre) ;
  3. un lot INEXPLOITABLE (`INDETERMINE`) arrete la campagne dans tous les cas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_embed_8099_mesure_bornee as M  # noqa: E402


def _args(**kw):
    d = dict(chunks=10, batch=2, ram_arret=87.0, periode=1.0, garder=False, lots=3,
             attendre_min=1.0)
    d.update(kw)
    return argparse.Namespace(**d)


def _simule(monkeypatch, tmp_path, verdicts):
    """Chaque appel de lot rend le verdict suivant de la liste, via le rapport disque."""
    out = tmp_path / "rapport.json"
    monkeypatch.setattr(M, "OUT", out)
    monkeypatch.setattr(M, "_attendre_fenetre", lambda *a, **k: True)
    suite = list(verdicts)
    appels: list[str] = []

    def _faux_lot(a):
        v = suite.pop(0) if suite else "BORNE"
        appels.append(v)
        out.write_text(json.dumps({"verdict": v, "ecrits": 100}), encoding="utf-8")
        return 0 if v == "BORNE" else 1

    monkeypatch.setattr(M, "_un_lot", _faux_lot)
    monkeypatch.setattr(M.time, "sleep", lambda *_a: None)
    return appels


def test_un_lot_suspendu_ne_consomme_pas_son_tour(monkeypatch, tmp_path):
    appels = _simule(monkeypatch, tmp_path,
                     ["BORNE", "ARRET_RAM", "ARRET_RAM", "BORNE", "BORNE"])
    rc = M._campagne(_args(lots=3))
    assert rc == 0
    # 3 lots UTILES malgre 2 suspensions -> 5 appels
    assert appels == ["BORNE", "ARRET_RAM", "ARRET_RAM", "BORNE", "BORNE"], appels


def test_sans_fenetre_configuree_un_arret_ram_termine_la_campagne(monkeypatch, tmp_path):
    appels = _simule(monkeypatch, tmp_path, ["BORNE", "ARRET_RAM", "BORNE"])
    rc = M._campagne(_args(lots=3, attendre_min=0.0))
    assert rc != 0
    assert appels == ["BORNE", "ARRET_RAM"], appels


def test_un_lot_inexploitable_arrete_toujours_la_campagne(monkeypatch, tmp_path):
    appels = _simule(monkeypatch, tmp_path, ["BORNE", "INDETERMINE", "BORNE"])
    rc = M._campagne(_args(lots=3))
    assert rc != 0
    assert appels == ["BORNE", "INDETERMINE"], appels
