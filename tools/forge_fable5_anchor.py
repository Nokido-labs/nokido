#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_fable5_anchor.py - ancre les FAITS CANONIQUES Fable 5 (skill claude-api)
en domain=reference pour contrebalancer la veille web non-fiable (anti-poison RAG).
One-shot, run via trusted_script (ecriture RAG). Reutilisable si re-poison."""

__FORGE_COLOR__ = "memoire/lesson : ancre les faits canoniques Fable 5 en domain reference"  # organe declare le 2026-09-06 (audit de raccordement)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GROUNDED = (
    "Fable 5 (claude-fable-5) - FAITS CANONIQUES (source: skill claude-api, cache 2026-06-04), "
    "a OPPOSER a la veille web non-fiable (chunks watch_veille marques NON-FIABLE).\n\n"
    "VRAI :\n"
    "- Contexte 1M tokens (= defaut, le max), output max 128K.\n"
    "- Thinking TOUJOURS ON (omettre le param ; depth via output_config.effort low->high->xhigh->max).\n"
    "- Tokenizer NOUVEAU : ~+30% tokens pour le meme contenu -> re-baseliner avec count_tokens.\n"
    "- Mythos 5 (claude-mythos-5) = MEMES capacites/prix/API via Project Glasswing (PAS un "
    "'coeur brut non-restreint pour partenaires').\n"
    "- Async sub-agents = comportement prompt-tunable documente (delegation).\n"
    "- Compaction serveur (beta, declenche ~150K).\n"
    "- Task Budgets (beta) : le modele voit un COUNTDOWN de tokens sur toute la boucle agentique "
    "et s'auto-modere (distinct de max_tokens).\n"
    "- refusal stop_reason (HTTP 200, pas une erreur) + param `fallbacks` = retry server-side sur "
    "un AUTRE modele.\n"
    "- Pas de prefill assistant ; retention 30j requise (pas de ZDR).\n\n"
    "FAUX / HALLUCINE (veille Gemini wj_378f9926e8, NE PAS croire) :\n"
    "- '80.3% SWE-bench Pro / 29.3% FrontierCode / vs GPT-5.5 58%' = chiffres FABRIQUES, zero source.\n"
    "- 'Safety Routing Layer qui route auto cyber/bio -> Opus 4.8' = EMBELLISSEMENT du mecanisme "
    "refusal+fallbacks, PAS un classifieur de routage vers Opus.\n"
    "- 'ecrit systematiquement ses tests + verifie l'UI par vision' = generique non documente.\n\n"
    "MAPPING orchestration Nokido : Task Budgets -> budget tiktoken + run_job (countdown) ; "
    "async sub-agents -> forge_spawn_swarm (DAG parallele) ; compaction -> memory_compactor ; "
    "refusal+fallbacks -> cascade never-hang (forge_task_router/forge_llm_router force_local)."
)

try:
    from nokido_agent.app.forge_self_correction import anchor_solution

    r = anchor_solution(
        problem="Fable 5 orchestration : faits canoniques vs veille web hallucinee (anti-poison RAG)",
        solution=GROUNDED,
        example="Source canonique = skill claude-api. Surclasse les chunks watch_veille NON-FIABLE.",
        domain="reference",
    )
    print(f"[ok] anchored domain=reference :: {r}")
except Exception as e:  # noqa: BLE001
    print(f"[ERR] anchor_solution: {type(e).__name__}: {e}")
    raise SystemExit(1)
