"""NR 31/10 -- une dette RESOLUE ne ressort plus a chaque tour parce que sa resolution vit dans une autre zone.

Mesure 31/10 : le hook affichait « DETTES OUVERTES ... bug_delivery_integrity_faux_attestation_pointeur_spec_20261022 -
{"intent": "REVIEW_FINDING" ... ». dettes_ouvertes ne lit que ZONE_DETTES (active_bugs), ou l'enregistrement d'origine est
reste ; la resolution (« [RESOLU 2026-10-28 ...] corrige par d6536f0a4 ») a ete ecrite dans architecture_rules SOUS LA
MEME CLE. _est_close ne voyait que la valeur de la meme entree. Deux rendus delegues rejetes (mauvais fichier ; test
sur la CLE au lieu de la valeur).
"""
from __future__ import annotations

import time

from nokido_agent.app import forge_memoire_active as MA
from nokido_agent.app import forge_swarm_blackboard as BB

T = time.time() - 9 * 86400


def _zones(monkeypatch, zones):
    monkeypatch.setattr(BB, "read_zone", lambda zone, *a, **k: {"zone": zone, "facts": zones.get(zone, [])})


def _fait(cle, valeur):
    return {"key": cle, "value": valeur, "trust": 0.9, "updated_at": T, "created_at": T}


def test_resolue_dans_une_autre_zone_n_est_plus_listee(monkeypatch):
    _zones(monkeypatch, {
        MA.ZONE_DETTES: [_fait("bug_x", '{"intent": "REVIEW_FINDING", "pointer_ref": "file:a.py"}'),
                         _fait("bug_y", "toujours ouvert")],
        "architecture_rules": [_fait("bug_x", "[RESOLU 2026-10-28 ; constate le 30/10] corrige par d6536f0a4")],
    })
    entrees, _ = MA.dettes_ouvertes(limit=5)
    textes = " ".join(str(e) for e in entrees)
    assert "bug_x" not in textes and "bug_y" in textes


def test_meme_cle_ailleurs_mais_non_close_reste_ouverte(monkeypatch):
    _zones(monkeypatch, {
        MA.ZONE_DETTES: [_fait("bug_z", "ouvert")],
        "architecture_rules": [_fait("bug_z", "precision : la cause est dans le juge")],
    })
    entrees, _ = MA.dettes_ouvertes(limit=5)
    assert "bug_z" in " ".join(str(e) for e in entrees)
