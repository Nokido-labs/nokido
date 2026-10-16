# -*- coding: utf-8 -*-
"""NR — app/forge_workflow.py : chaînage intra-phase en mode pipeline (Constat 1).

Contexte (Audit ChatGPT 15/10) :
En mode `pipeline`, `acc` était calculé (`acc = txt`) mais `_one()` injectait
toujours `prev` (le contexte d'entrée de la phase) capturé par fermeture.
Les agents suivants dans la phase pipeline ne recevaient jamais la sortie de l'agent
précédent.

Ce test vérifie sur le CHEMIN RÉEL (`run_plan`) qu'une phase pipeline à 2 agents
transmet bien la sortie de l'agent 1 dans le prompt d'entrée de l'agent 2.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))


@pytest.mark.asyncio
async def test_pipeline_intra_phase_chaining():
    """Vérifie que l'agent N+1 reçoit la sortie de l'agent N dans une phase pipeline."""
    from nokido_agent.app.forge_workflow import run_plan

    recus = {}

    async def mock_ask(provider: str, prompt: str, max_tokens: int) -> str:
        if "TON RÔLE = redacteur" in prompt:
            recus["redacteur"] = prompt
            return "CONTENU_PRODUIT_PAR_REDACTEUR_42"
        if "TON RÔLE = relecteur" in prompt:
            recus["relecteur"] = prompt
            return "VALIDATION_RELECTEUR_OK"
        return "REPONSE_DEFAUT"

    plan = {
        "name": "test-pipeline-chaining",
        "phases": [
            {
                "name": "P_REDAC_RELEC",
                "mode": "pipeline",
                "agents": [
                    {"role": "redacteur", "provider": "groq", "prompt": "redige article"},
                    {"role": "relecteur", "provider": "groq", "prompt": "relis article"},
                ],
            }
        ],
    }

    res = await run_plan(plan, context="trusted", ask_fn=mock_ask)

    assert "redacteur" in recus, "Le redacteur doit avoir ete appele"
    assert "relecteur" in recus, "Le relecteur doit avoir ete appele"

    # L'agent 2 (relecteur) DOIT avoir dans son prompt le résultat de l'agent 1 (redacteur)
    prompt_relecteur = recus["relecteur"]
    assert "CONTENU_PRODUIT_PAR_REDACTEUR_42" in prompt_relecteur, (
        f"L'agent relecteur n'a pas recu la sortie du redacteur ! Prompt recu : {prompt_relecteur}"
    )
    assert "### redacteur\nCONTENU_PRODUIT_PAR_REDACTEUR_42" in res.get("result")
    assert "### relecteur\nVALIDATION_RELECTEUR_OK" in res.get("result")
