"""NR du 27/10 : l'arene ne marque le dossier « vu » qu'apres un tour REUSSI.

Mesure (debat takehome, 18 tours) : groq echoue au tour aveugle (reponse vide), le dossier etait pourtant
marque vu ; au round 2 il ne recevait que l'etat partage et a repondu HORS SUJET (« securite des
pipelines »). Un dossier jamais lu n'a pas ete transmis.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N))
sys.path.insert(0, str(N / "tools"))
import forge_m2m_debate_antiregression as A  # noqa: E402


def test_dossier_renvoye_apres_un_tour_rate(tmp_path, monkeypatch):
    prompts = []

    async def faux_turn(provider, prompt, tokens):
        prompts.append(prompt)
        return ("", False) if len(prompts) == 1 else ("ACQUIS: ok", True)

    import nokido_agent.tools.forge_debate_job as dj
    monkeypatch.setattr(dj, "_turn", faux_turn)
    etat = {"tour": 0, "axes": {}, "tensions": [], "acquis": []}
    monkeypatch.setattr(A, "ssot_lire", lambda: etat)
    monkeypatch.setattr(A, "ssot_ecrire", lambda e: None)
    monkeypatch.setattr(A, "agent_testeur", lambda e, *a, **k: {})
    monkeypatch.setattr(A, "JOURNAL", tmp_path / "j.md")
    asyncio.run(A.arene_ssot("OBJECTIF_TEMOIN", [("SOLO", "faux", "ROLE_TEMOIN")], 2))
    assert len(prompts) == 2
    # tour 1 rate -> le tour 2 doit porter le dossier complet (role + objectif)
    assert "ROLE_TEMOIN" in prompts[1] and "OBJECTIF_TEMOIN" in prompts[1]
