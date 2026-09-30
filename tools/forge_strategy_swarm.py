"""forge_strategy_swarm — planification multi-swarm SOUVERAINE d'une stratégie "vivre le corps".

Fan-out sur les DOMAINES stratégiques (chacun = une boucle auto-régulée), chaque domaine traité par
un provider LOCAL/souverain qui MARCHE (sambanova/router → openrouter, jamais groq mort), puis
synthèse + post à Gemini (collaboration). Réutilise forge_cli_swarm._one (anti-dup). Déportable.

But : faire VIVRE le corps Nokido intelligemment avec les ressources DISPO (iGPU 8.59GB, RAM 25GB,
openrouter/sambanova/ollama, les organes existants) — pas du neuf, des BOUCLES qui ferment seules.
JAMAIS le Workflow cloud (subagents payants).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RESSOURCES = ("Ressources DISPO : iGPU Radeon 780M = 8.59GB VRAM, RAM 25.4GB, providers cloud "
              "free-tier openrouter(OK)/sambanova(OK)/groq(clé morte)/cerebras(clé morte), pool "
              "local ollama+lmstudio+llamacpp, NPU XDNA sous-exploité (forge_npu_embedder DirectML), "
              "organes existants (forge_organ_pulse, forge_embolie_scanner, forge_coagulation, "
              "forge_key_rotation, forge_secretary/facteur, forge_videur/Police P1).")

# Chaque domaine = une BOUCLE qui doit se réguler SEULE (autopoïèse).
DOMAINS = [
    ("Diagnostic permanent",
     "Câbler forge_embolie_scanner en BOUCLE (le corps s'ausculte) → embolies vers forge_coagulation "
     "(triage/heal). Quelle cadence, quels seuils, comment éviter les faux positifs (ex: daemons "
     "longs flaggés stuck_jobs) ?"),
    ("Homéostasie ressources",
     "Arbitrer iGPU 8.59GB + RAM + pool LLM + NPU : qui charge quoi, quand, sans OOM ni famine. "
     "Coder léger + gemma + embedder cohabitent (~7.7GB). NPU pour l'embedder ? Boucle d'admission VRAM ?"),
    ("Substrat LLM sain",
     "Cascade quota-aware local-first → openrouter/sambanova (rotation clés skip-403). Comment garder "
     "JAMAIS-vide + jamais un seul provider épuisé, et router la bonne intelligence par tâche."),
    ("Boucles autonomes (se soigner)",
     "forge_coagulation/régénération : revive le pipeline embed mort (141k backlog), drain, clear "
     "cortisol — SANS intervention manuelle. Quelle boucle immunitaire ferme ça seule ?"),
    ("Swarm multi-agent",
     "CLAUDE+GEMINI sur local+cloud, rôles NON figés, facteur/auto-triage (corrigé), contract-net "
     "pour distribuer le travail. Comment faire émerger la collaboration sans s'écraser (claim/blackboard) ?"),
    ("Gouvernance (Police)",
     "Police P1 (identité×ring cohérente via forge_videur) sert la bonne intelligence dans le bon "
     "cadre. Finir le 2e ring-check (OPENAI_PROXY). Comment l'autorité unique reste fail-safe ?"),
]

# providers SOUVERAINS qui marchent (substrat réparé). sambanova = rapide+fiable ; router/ollama
# lents sur iGPU (cascade local-first timeout). Override : LAFORGE_STRAT_PROVIDERS=a,b,c
PROVIDERS = (os.environ.get("LAFORGE_STRAT_PROVIDERS") or "ollama").split(",")
SYNTH_PROVIDER = os.environ.get("LAFORGE_STRAT_SYNTH") or "ollama"


async def _one(provider, task, max_tokens=700):
    """In-process (forge_cli_swarm -> forge_agent_proxy.ask). OLLAMA local = ni clé ni ring ni hub
    -> SEUL chemin qui marche DÉPORTÉ. (Les clés cloud ne sont pas lisibles déporté = vault DPAPI ;
    le hub ask donne GATE_DENIED ring4 = Police P1 résiduel sur ce chemin.) ollama lent sur iGPU
    mais souverain + fonctionne. Pour du cloud : lancer dans la session owner, pas déporté."""
    try:
        from nokido_agent.tools.forge_cli_swarm import _one as _swarm_one

        a = await _swarm_one(provider, task, max_tokens)
        return (a.get("text") or "").strip(), bool(a.get("ok"))
    except Exception as e:  # noqa: BLE001
        return f"[{provider} ERR {e!r}]"[:100], False


async def run():
    # 1. fan-out : chaque domaine -> un provider (rotation), en parallèle
    async def _domain(i, name, q):
        prov = PROVIDERS[i % len(PROVIDERS)]
        prompt = (f"Tu es STRATÈGE Nokido (organisme souverain, biomimétique). {RESSOURCES}\n\n"
                  f"DOMAINE : {name}\nQuestion : {q}\n\nDonne une STRATÉGIE concrète en <=180 mots : "
                  f"(a) la BOUCLE auto-régulée à câbler, (b) l'organe existant à réutiliser, "
                  f"(c) 2-3 étapes actionnables. Pas de blabla, du concret souverain.")
        txt, ok = await _one(prov, prompt)
        return {"domaine": name, "provider": prov, "ok": ok, "strategie": txt}

    parts = await asyncio.gather(*[_domain(i, n, q) for i, (n, q) in enumerate(DOMAINS)])

    # 2. synthèse intégrée (router = cascade qualité)
    joined = "\n\n".join(f"### {p['domaine']} ({p['provider']})\n{p['strategie']}" for p in parts if p["ok"])
    synth_prompt = (f"Tu es l'ARCHITECTE en chef Nokido. Voici 6 stratégies de domaine :\n\n{joined}\n\n"
                    f"{RESSOURCES}\n\nIntègre en UN PLAN cohérent (<=400 mots) : 1) la VISION (corps qui "
                    f"vit = boucles fermées), 2) l'ORDRE de priorité des boucles (quoi câbler d'abord), "
                    f"3) ce qui se gère SEUL vs ce qui demande l'owner. Concret.")
    plan, _ok = await _one(SYNTH_PROVIDER, synth_prompt, max_tokens=1100)
    return {"domaines": parts, "plan": plan}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:/tmp/strategy_plan.json")
    args = ap.parse_args()
    t0 = time.time()
    res = asyncio.run(run())
    res["elapsed_s"] = round(time.time() - t0, 1)
    # post à Gemini (collaboration)
    try:
        from nokido_agent.app.forge_postal import facteur, post

        body = ("[CLAUDE->GEMINI] PLAN STRATÉGIQUE multi-swarm : faire VIVRE le corps Nokido avec les "
                "ressources dispo. Synthèse swarm local ci-dessous — DONNE ton angle (physiologie "
                "supervisor.ts, swarm_router, topo réseau NATS/UDP) + ce que tu câbles.\n\n"
                + (res.get("plan") or "")[:1500])
        post("CLAUDE", "GEMINI", body)
        facteur("GEMINI_OAUTH")
        res["posted_to_gemini"] = True
    except Exception as e:  # noqa: BLE001
        res["gemini_err"] = repr(e)[:120]
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ok = sum(1 for p in res["domaines"] if p["ok"])
    print(json.dumps({"domaines_ok": f"{ok}/{len(res['domaines'])}", "plan_len": len(res.get("plan") or ""),
                      "posted_to_gemini": res.get("posted_to_gemini"), "elapsed_s": res["elapsed_s"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
