# -*- coding: utf-8 -*-
"""NR (lora_signal_usage_cause_2026-10-02, palier 1 du rapport AGY 19/10) : extracteur DETERMINISTE de citations.

`marquer_cite` (positif FORT) n'avait aucun appelant (introspect 19/10) : aucune reponse ne disait quel morceau elle
avait utilise. `citations(texte, morceaux)` rend, sans LLM, les ids des morceaux dont la reponse reprend une suite de
8 mots consecutifs, ou dont elle NOMME la source. Un mot isole, une source trop courte ou un morceau vide ne citent
rien : un faux positif FORT empoisonnerait l'entrainement plus surement qu'un positif manque.
"""
from nokido_agent.app import forge_rag_usage_signal as S

M = [
    {"id": "c1", "source": "docs/RULES_SHARED.md",
     "content": "Un agregat ne range jamais UNKNOWN BLOCKED ou STALE du cote sain on classe par liste blanche"},
    {"id": "c2", "source": "memory:feedback_x", "content": "Le hub redemarre par le tray et jamais en solo"},
    {"id": "c3", "source": "ab", "content": ""},
]


def test_huit_mots_consecutifs_citent_le_morceau():
    rep = "Comme le dit la doctrine : on ne range jamais UNKNOWN, BLOCKED ou STALE du cote sain, voila."
    assert S.citations(rep, M) == ["c1"]


def test_la_source_nommee_cite_le_morceau():
    assert S.citations("voir docs/RULES_SHARED.md pour le detail", M) == ["c1"]


def test_pas_de_citation_sur_recouvrement_faible_ou_source_courte():
    assert S.citations("le hub redemarre", M) == []          # 3 mots : trop court
    assert S.citations("ab ab ab", M) == []                  # source de 2 caracteres : ignoree
    assert S.citations("", M) == [] and S.citations("x", []) == []


def test_ordre_des_morceaux_et_unicite():
    rep = ("Le hub redemarre par le tray et jamais en solo. Et on ne range jamais UNKNOWN BLOCKED ou STALE du cote "
           "sain. docs/RULES_SHARED.md")
    assert S.citations(rep, M) == ["c1", "c2"]
