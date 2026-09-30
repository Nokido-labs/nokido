#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_provider_reachability.py — dimension REACHABILITY des providers.

POURQUOI (doctrine Functional Archaeology, 2026-08-16). L'archeologie par
EXISTENCE ne voit pas qu'un provider peut etre present et pourtant inatteignable :
present dans le runtime `ask` mais sans slot dans le LLMRouter (non routable),
ou avec un slot mais dans aucune chain de use_case (jamais atteint). L'analyse
owner l'a pose : existence != availability != routability != exposability !=
swarmability. Ici on mesure les deux premieres transitions du graphe
Provider -> Router -> Chain, en RECONCILIANT les espaces de noms divergents
(runtime `ollama` vs slot `ollama_local`) via forge_endpoint_registry.

LECTURE SEULE. Sortie : sandbox/provider_reachability.json + resume.

Non couvert ici (V2, dimensions suivantes) : swarm membership, exposition CLI
`--provider`, flags LAFORGE_ENABLE_*, et le MODEL_SERVING reel (readiness live).
Ce module ne les DEVINE pas : il les declare NON MESURES, jamais OK par defaut.
"""
from __future__ import annotations

import functools
import json
import os
import sys

# Amorce AVANT l'import du namespace, et la RACINE avec (2026-09-25) : l'import precedait
# l'amorce, qui n'inserait que app/ et tools/ -- lance par chemin, ce module mourait en
# ModuleNotFoundError (examen « fournisseurs » fige 28 jours). NR : test_point_entree_par_chemin_nr.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "app"), os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from nokido_agent.tools.forge_archeo_socle import ecrire_json, noms_par  # noqa: E402

# Providers internes/non-LLM : ni routables ni un manque quand absents du router.
INTERNES = {"router", "router_local", "swarm", "agent", "nervous", "wasm"}
NON_LLM = {"tavily"}                    # search API, pas de generation
OAUTH_CLI = {"claude_cli", "claude_agent_sdk", "gemini_cli", "codex_cli", "copilot_cli"}


def _slot_runtime(er, slot_name, slot):
    """Nom runtime canonique d'un slot, en reconciliant les namespaces.

    1) forge_endpoint_registry.resolve (alias_index : xai_grok3 -> grok) ;
    2) repli sur le prefixe litellm du 1er model (groq/llama -> groq)."""
    e = er.resolve(slot_name)
    if e and e.get("runtime"):
        return e["runtime"], False
    models = getattr(slot, "models", None) or []
    if models and "/" in models[0]:
        return models[0].split("/")[0], True
    return slot_name.split("_")[0], True


def analyser() -> dict:
    from nokido_agent.tools import forge_endpoint_registry as ER
    from nokido_agent.app import forge_llm_router as R

    inv = ER.build_inventory()
    runtime = {e["runtime"]: e for e in inv["endpoints"].values()}
    ghosts = inv.get("ghosts", [])

    rt = R.get_router()
    # slot -> runtime canonique
    slot_to_rt = {}
    ghost_slots = []
    for name, slot in rt._slots.items():
        run, approx = _slot_runtime(ER, name, slot)
        slot_to_rt[name] = run
        if ER.resolve(name) is None and name in ghosts:
            ghost_slots.append(name)
    providers_slotted = set(slot_to_rt.values())

    # chains -> slots atteints -> runtime atteints
    ucc = getattr(R, "USE_CASE_CHAINS", {}) or {}
    chain_slots = set()
    for ch in ucc.values():
        chain_slots.update(ch if isinstance(ch, (list, tuple)) else [])
    providers_chained = {slot_to_rt.get(sl, sl.split("_")[0]) for sl in chain_slots}

    # verdict par provider runtime
    verdicts = {}
    for name, e in runtime.items():
        if name in INTERNES:
            continue
        in_router = name in providers_slotted
        in_chain = name in providers_chained
        key = e.get("key_present")
        if name in NON_LLM:
            verdict = "NON_LLM"
        elif name in OAUTH_CLI:
            verdict = "OAUTH_HORS_ROUTER"        # a verifier cote swarm (V2)
        elif in_router and in_chain:
            verdict = "ROUTABLE"
        elif in_router and not in_chain:
            verdict = "SLOT_SANS_CHAIN"           # present-but-unreached
        elif key is True:
            verdict = "RUNTIME_SANS_SLOT_AVEC_CLE"  # utilisable via ask, hors cascade
        elif key is False:
            verdict = "SANS_SLOT_SANS_CLE"          # ni routable ni authentifie
        else:
            verdict = "RUNTIME_SANS_SLOT"           # local/oauth sans slot
        verdicts[name] = {"verdict": verdict, "in_router": in_router,
                          "in_chain": in_chain, "key_present": key,
                          "tier": e.get("tier")}

    # ── COUCHE SWARM : participants -> router_slot (3e espace de noms) ─────
    swarm = {"providers": [], "router_slots_casses": {}, "providers_hors_runtime": []}
    try:
        from nokido_agent.app import forge_swarm_team as ST
        team = ST._default_team()
        slots_reels = set(rt._slots.keys())
        sw_prov, casses = set(), {}
        for p in getattr(team, "participants", []):
            prov = getattr(p, "provider", None)
            if prov:
                sw_prov.add(prov)
            cfg = getattr(p, "config", {}) or {}
            rs = cfg.get("router_slot")
            if rs and rs not in slots_reels:
                # participant qui route vers un slot INEXISTANT = membre non executable
                casses[getattr(p, "id", "?")] = rs
        # provider swarm sans equivalent runtime reconcilie (via resolve)
        hors = sorted(p for p in sw_prov
                      if p not in runtime and p not in INTERNES
                      and ER.resolve(p) is None)
        swarm = {"providers": sorted(sw_prov),
                 "router_slots_casses": casses,
                 "providers_hors_runtime": hors}
    except Exception as exc:  # le swarm est optionnel, ne casse pas la mesure
        swarm = {"erreur": str(exc)[:150]}

    # regroupement des signaux d'attention (socle : meme geste dans le tracer)
    par = functools.partial(noms_par, verdicts, "verdict")

    return {
        "n_runtime": len(runtime),
        "n_slots": len(rt._slots),
        "use_cases": sorted(ucc.keys()) if isinstance(ucc, dict) else [],
        "verdicts": verdicts,
        "attention": {
            "slot_sans_chain_present_but_unreached": par("SLOT_SANS_CHAIN"),
            "runtime_sans_slot_avec_cle": par("RUNTIME_SANS_SLOT_AVEC_CLE"),
            "sans_slot_sans_cle": par("SANS_SLOT_SANS_CLE"),
            "oauth_hors_router_a_verifier_swarm": par("OAUTH_HORS_ROUTER"),
        },
        "ghost_slots_specs_fantomes_routes": sorted(ghost_slots),
        "ghosts_spec_sans_runtime": ghosts,
        "swarm": swarm,
        "non_mesure": ["cli_--provider_exposure",
                       "flags_LAFORGE_ENABLE", "model_serving_live"],
    }


def _rendre(res) -> None:
    print("[reachability] %s providers runtime, %s slots router, %s use_cases"
          % (res["n_runtime"], res["n_slots"], len(res["use_cases"])))
    for cle, liste in res["attention"].items():
        if liste:
            print("  %-42s %s" % (cle, ", ".join(liste)))
    if res["ghost_slots_specs_fantomes_routes"]:
        print("  slots FANTOMES routes (spec sans runtime) : %s"
              % ", ".join(res["ghost_slots_specs_fantomes_routes"]))
    sw = res.get("swarm", {})
    if sw.get("router_slots_casses"):
        print("  SWARM -> router_slot INEXISTANT (membre non executable) : %s"
              % sw["router_slots_casses"])
    if sw.get("providers_hors_runtime"):
        print("  SWARM providers sans equivalent runtime : %s"
              % ", ".join(sw["providers_hors_runtime"]))
    print("[reachability] NON MESURE (V2, jamais OK par defaut) : %s"
          % ", ".join(res["non_mesure"]))


def main() -> int:
    res = analyser()
    _rendre(res)
    print("[reachability] ecrit : %s"
          % ecrire_json(os.path.join(ROOT, "sandbox", "provider_reachability.json"), res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
