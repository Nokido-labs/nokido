# -*- coding: utf-8 -*-
"""NR (owner 2/11, « tu dis que les veilles tournent mais Docker est coupe ») : l'etape crawl ATTEND crawl4ai.

Mesure du 2/11 : la veille par URL (wj_7f2de14742, 12 URL) commence au crawl ; Docker etait eteint (releve a 11 h 16) ;
forge_crawl_tool RECLAMAIT crawl4ai mais n'attendait pas -> repli urllib sans navigateur sur toutes les URL ->
completed_empty. Desormais, avant de crawler : sonde de sante ; absent -> reclamation (demander_crawl4ai, lancer=True)
puis attente BORNEE ; toujours absent -> motif EXPLICITE (jamais un vide silencieux), le repli continue."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_chain_executor as ce  # noqa: E402


def _horloge():
    t = [0.0]

    def maintenant():
        return t[0]

    def dormir(s):
        t[0] += s
    return maintenant, dormir


def test_crawl4ai_present_aucune_attente():
    maintenant, dormir = _horloge()
    demandes = []
    ok, motif = ce.attendre_crawl4ai(lambda: True, lambda: demandes.append(1), dormir, maintenant, budget_s=180)
    assert ok is True and demandes == [] and maintenant() == 0.0


def test_crawl4ai_absent_reclame_puis_attend_qu_il_reponde():
    maintenant, dormir = _horloge()
    demandes, reponses = [], iter([False, False, False, True])
    ok, motif = ce.attendre_crawl4ai(lambda: next(reponses), lambda: demandes.append(1), dormir, maintenant,
                                     budget_s=180, pas_s=10)
    assert ok is True and demandes == [1] and 0 < maintenant() <= 180


def test_crawl4ai_jamais_la_motif_explicite_et_budget_respecte():
    maintenant, dormir = _horloge()
    ok, motif = ce.attendre_crawl4ai(lambda: False, lambda: None, dormir, maintenant, budget_s=60, pas_s=10)
    assert ok is False and "CRAWL4AI_INDISPONIBLE" in motif and maintenant() <= 60 + 10
