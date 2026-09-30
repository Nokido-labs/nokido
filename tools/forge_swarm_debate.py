#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_swarm_debate.py - débat SWARM 3 tours, pool de spécialistes diversifiés.

Orchestre un débat à 3 rounds (map parallèle -> synthèse -> raffine) sur un panel
de personas-spécialistes distincts (backends cloud diversifiés). Appelle
forge_agent_proxy.ask EN DIRECT (in-process) = bypass du ring-gate hub + reach cloud.
Déporté via run_job (online=true). Écrit docs/swarm_debate_organ_tiers.md + reco finale.

Sujet (args/défaut) : faut-il transformer les ORGANES Nokido en agents bas-niveau ?
Proposition à challenger : modèle 3-tiers RÉFLEXE(module) / ACTEUR(event-driven 0-LLM) / AGENT(autonome).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "swarm_debate_organ_tiers.md"

# Spécialistes DISTINCTS (rôle, provider ask). Noms ask courts (cf. list_providers).
SPECIALISTS = [
    ("ARCHITECTE LOGICIEL (couplage, blast-radius, maintenabilité, distributed-monolith)", "groq"),
    ("SRE/PERFORMANCE (latence hot-path, observabilité d'une toile async, débogabilité)", "cerebras"),
    ("SÉCURITÉ (surface d'attaque, isolation, fail-closed, confused deputy)", "mistral"),
    ("INGÉNIEUR SYSTÈMES DISTRIBUÉS (actor model, message-passing, consistency, supervision/résilience)", "gpt4o_github"),
    ("FRUGALITÉ/SOUVERAINETÉ (coût tokens, RAM/iGPU, local-first, tax de l'agentification)", "cohere"),
]
# Providers LIVE+gratuits (cf. list_providers). gemini_cli (OAuth) ne marche PAS déporté
# (WinError 5, exige la session user) -> Gemini le PAIR participe via POSTAL, pas ici.
# deepseek(402)/grok(clé morte) écartés. Run en TRUSTED (écrit le repo + internet).

SEED = (
    "Nokido = OS d'agents local-first (700+ modules forge_*, hub HTTP, organes biomimétiques). "
    "QUESTION : faut-il transformer les ORGANES (modules) en agents bas-niveau ?\n"
    "PROPOSITION 3-TIERS à challenger : RÉFLEXE = module SYNCHRONE hot-path (RBAC/ring/firewall/"
    "RAG-search/gate) -> NE PAS agentifier (latence/complexité) ; ACTEUR RÉACTIF = event-driven "
    "déterministe ZÉRO-LLM (évolution des daemons/keepers) ; AGENT = état+proactif+autonome, déjà "
    "daemons (keepers/facteur/secrétaire/veille) -> formaliser sous contrat OrganAgent."
)


async def _ask_one(role: str, prov: str, task: str) -> tuple:
    # timeout par spécialiste : gemini_cli (OAuth) est lent (>120s) -> ne doit pas
    # bloquer le tour indéfiniment ; les rapides (groq/grok) répondent en <2s.
    _to = 200 if prov.endswith("_cli") else 60
    try:
        from nokido_agent.app.forge_agent_proxy import ask
        r = await asyncio.wait_for(
            ask(prov, f"TON RÔLE = {role}.\n\n{task}", max_tokens=420, rag_context=False), timeout=_to)
        txt = (r.get("text") or "").strip()
        return (role, prov, txt, bool(r.get("ok")) and bool(txt))
    except asyncio.TimeoutError:
        return (role, prov, f"[timeout {_to}s]", False)
    except Exception as e:  # noqa: BLE001
        return (role, prov, f"[KO: {type(e).__name__}: {e}]", False)


async def _round(task: str, label: str) -> list:
    print(f"[{label}] {len(SPECIALISTS)} spécialistes en parallèle...")
    res = await asyncio.gather(*[_ask_one(r, p, task) for r, p in SPECIALISTS])
    ok = [x for x in res if x[3]]
    print(f"[{label}] {len(ok)}/{len(SPECIALISTS)} ont répondu")
    return ok


async def _synth(answers: list, instr: str) -> str:
    if not answers:
        return "[aucune réponse]"
    from nokido_agent.app.forge_agent_proxy import ask
    joined = "\n\n".join(f"### {r} ({p})\n{t}" for r, p, t, _ in answers)
    s = await ask("groq", f"{instr} Cite les divergences notables.\n\n{joined}",
                  max_tokens=700, rag_context=False)
    return (s.get("text") or "").strip() or "[synthèse vide]"


async def main() -> int:
    # PRÉ-VOL via le RÉSOLVEUR : écarte les providers morts/inadaptés au contexte +
    # redirige le write si non-inscriptible. Plus d'erreur qui passe dans le flux.
    global SPECIALISTS, OUT
    import os
    from nokido_agent.app.forge_resolver import resolve_provider_panel, writable_path
    _ctx = os.environ.get("LAFORGE_CTX", "trusted")
    SPECIALISTS = resolve_provider_panel(SPECIALISTS, context=_ctx) or SPECIALISTS
    OUT, _red = writable_path(OUT, context=_ctx)
    print(f"[resolver] panel={[p for _, p in SPECIALISTS]} ctx={_ctx} out={OUT.name}")

    r1 = await _round(SEED + "\n\nDepuis ton rôle : VALIDE / RAFFINE / CONTESTE. 4-6 points denses, "
                      "risques concrets, zéro blabla.", "R1")
    s1 = await _synth(r1, "Synthétise ce débat : points d'ACCORD + TENSIONS structurelles.")

    r2 = await _round(f"Synthèse du tour 1 :\n{s1}\n\nDepuis ton rôle, CHALLENGE/RAFFINE les "
                      "tensions (surtout le tier ACTEUR et la frontière réflexe/agent). 4-6 points.", "R2")
    s2 = await _synth(r2, "Synthétise le tour 2 : ce qui CONVERGE, ce qui reste OUVERT.")

    r3 = await _round(f"Synthèse du tour 2 :\n{s2}\n\nCONVERGE : ta RECO FINALE sur le modèle 3-tiers "
                      "(garder tel quel / modifier / rejeter) + LA règle de décision réflexe-vs-agent. 3-5 points.", "R3")
    s3 = await _synth(r3, "RECO FINALE consolidée : le modèle de tiers retenu + le discriminateur + les nuances clés.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Débat Swarm — Organes Nokido -> agents bas-niveau ?\n\n"
        f"_Panel : {', '.join(p for _, p in SPECIALISTS)} (5 rôles distincts) · 3 tours._\n\n"
        f"## Tour 1 — prises de position\n{s1}\n\n"
        f"## Tour 2 — challenge des tensions\n{s2}\n\n"
        f"## RECO FINALE (convergence)\n{s3}\n",
        encoding="utf-8")
    print(f"[ok] écrit {OUT}")
    print("\n=== RECO FINALE ===\n" + s3[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
