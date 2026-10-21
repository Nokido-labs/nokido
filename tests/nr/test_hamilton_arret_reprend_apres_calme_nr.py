"""NR -- Hamilton : un service ARRETE sous pression durable est REPRIS apres le calme, jamais oublie endormi.

Lecture du code (20/10) : sous une pression qui dure plus que pause_max (45 s, pour un tick de 60 s), gestes_observes rend
ARRETER puis EFFACE l'entree (etat.pop) ; or _ordre_superviseur a deja envoye le sommeil au SUSPENDRE et n'ordonne rien
sur ARRETER. Pression retombee : plus aucune entree -> plus jamais de REPRENDRE -> le DIFFERABLE reste endormi en
silence (DeportEmbed / Consolidator « battements perimes » relances a la main le 19/10). ARRETER garde le suivi.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as R  # noqa: E402

PAUSE, CALME = 45.0, 120.0
T0 = 1_792_000_000.0   # un horodatage reel (pause_ts == 0 serait lu comme absent)


def test_un_service_arrete_est_repris_apres_le_calme():
    g, etat = R.gestes_observes(["svc"], {}, T0, PAUSE, CALME)
    assert g == {"svc": "SUSPENDRE"}
    g, etat = R.gestes_observes(["svc"], etat, T0 + 60.0, PAUSE, CALME)   # pression durable : au-dela de pause_max
    assert g == {"svc": "ARRETER"}
    vus = []
    t = T0 + 60.0
    for _ in range(12):                                                # la pression retombe
        t += 60.0
        g, etat = R.gestes_observes([], etat, t, PAUSE, CALME)
        vus.append(g.get("svc"))
    assert "REPRENDRE" in vus, vus


def test_un_service_arrete_n_est_pas_resuspendu_tant_que_la_pression_dure():
    _, etat = R.gestes_observes(["svc"], {}, T0, PAUSE, CALME)
    _, etat = R.gestes_observes(["svc"], etat, T0 + 60.0, PAUSE, CALME)
    g, etat = R.gestes_observes(["svc"], etat, T0 + 120.0, PAUSE, CALME)
    assert g.get("svc") != "SUSPENDRE"                               # pas un nouveau sommeil en boucle
