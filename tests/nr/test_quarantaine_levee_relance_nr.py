"""NR -- une quarantaine levee ne laisse pas un service attendu mort (racine R6, 17/10).

Mesure 17/10 : veille du poste 05:46 -> reveil 10:11 (journal System, Power-Troubleshooter) ; les 4 executeurs
interactifs, relances 3 fois en quelques secondes, echouent (1008, session sans jeton juste apres le reveil). Dans
proxy_deno/core/supervisor.ts, la levee d'une quarantaine QUICK-FAIL (et de la quarantaine horaire) remettait le service
a « stopped » SANS programmer de relance ni alerter : delegation morte jusqu'a la relance owner de 12:12.
"""
from __future__ import annotations

import re
from pathlib import Path

SUP = Path(__file__).resolve().parents[2] / "proxy_deno" / "core" / "supervisor.ts"


def _bloc_levee(marqueur: str) -> str:
    src = SUP.read_text(encoding="utf-8")
    i = src.index(marqueur)
    return src[i:i + 700]


def test_la_levee_de_la_quarantaine_rapide_reprogramme_la_relance():
    bloc = _bloc_levee("quick-fail quarantine released")
    assert re.search(r"_relancerApresQuarantaine\(state\)", bloc), bloc


def test_la_levee_de_la_quarantaine_horaire_reprogramme_la_relance():
    bloc = _bloc_levee("quarantine released, status -> stopped")
    assert re.search(r"_relancerApresQuarantaine\(state\)", bloc), bloc


def test_la_reprise_est_dite_et_ne_contredit_pas_un_ordre_d_arret():
    """Reprise DITE au journal ; seulement si le service est encore « stopped » par la levee elle-meme."""
    src = SUP.read_text(encoding="utf-8")
    i = src.index("function _relancerApresQuarantaine")
    corps = src[i:i + 500]
    assert "relance apres quarantaine" in corps and 'state.status !== "stopped"' in corps and "scheduleRestart(state)" in corps
