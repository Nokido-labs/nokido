#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_execution_trace.py — ou meurt une capacite provider.

POURQUOI (doctrine Functional Archaeology). La reachability dit si un provider
est ATTEIGNABLE (runtime -> slot -> chain). Elle ne dit pas s'il EXECUTE : une
capacite peut etre routable et morte a la transition suivante — cle presente
mais non transmise (bug 209ae2 : condition inversee -> 401, tests verts), ou
cle simplement invalide. L'analyse owner : verifier CHAQUE transition de
  intent -> route -> provider -> credentials -> transport -> model -> response.

Ce module trace les transitions VERIFIABLES SANS appel cloud (cout nul) et
nomme la PREMIERE ou chaque provider meurt :
  GHOST            spec sans runtime -> aucune classe pour appeler
  UNROUTABLE       runtime mais aucun slot router
  UNREACHED        slot mais dans aucune chain de use_case
  CRED_UNWIRED     cle chargeable mais NON cablee dans le slot (bug 209ae2)
  CRED_INVALID     cle attendue absente ou invalide -> 401 garanti
  LIVE_UNVERIFIED  transitions statiques OK ; transport+model NON testes (live)
  LOCAL            backend local/oauth : pas de credentials cloud

LECTURE SEULE. transport reel et model serving = declares NON verifies (ils
exigent un appel ; jamais presumes OK). Sortie : sandbox/execution_trace.json.
"""
from __future__ import annotations

import functools
import json
import os
import sys

# Amorce AVANT l'import du namespace, et la RACINE avec (2026-09-25) : l'import precedait
# l'amorce, qui n'inserait que app/ et tools/ -- lance par chemin, ce module mourait en
# ModuleNotFoundError (ERREUR_OUTIL au circadien, examen fige 15 jours).
# NR : test_point_entree_par_chemin_nr.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "app"), os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from nokido_agent.tools.forge_archeo_socle import noms_par  # noqa: E402


def tracer() -> dict:
    from nokido_agent.app import forge_llm_router as R
    from nokido_agent.tools import forge_endpoint_registry as ER
    from nokido_agent.tools import forge_provider_reachability as RE
    try:
        from nokido_agent.app.forge_agent_proxy import _load_api_key
    except Exception:
        _load_api_key = None

    reach = RE.analyser()
    verdicts = reach["verdicts"]
    ghosts_slots = set(reach.get("ghost_slots_specs_fantomes_routes", []))

    rt = R.get_router()
    ucc = getattr(R, "USE_CASE_CHAINS", {}) or {}
    chain_slots = set()
    for ch in ucc.values():
        chain_slots.update(ch if isinstance(ch, (list, tuple)) else [])

    slots = {}
    for name, s in rt._slots.items():
        env = getattr(s, "env_key_name", None)
        wired = bool(getattr(s, "api_key", None))
        in_chain = name in chain_slots
        if name in ghosts_slots:
            etat = "GHOST"
        elif not in_chain:
            etat = "UNREACHED"
        elif not env:
            etat = "LOCAL"                       # local/oauth : pas de cred cloud
        else:
            loaded = bool(_load_api_key(env)) if _load_api_key else None
            if loaded and not wired:
                etat = "CRED_UNWIRED"            # le bug 209ae2
            elif loaded is False:
                etat = "CRED_INVALID"
            else:
                etat = "LIVE_UNVERIFIED"
        slots[name] = {"etat": etat, "env": env, "in_chain": in_chain}

    # verdict runtime-level (couches en amont : ghost/unroutable) via reachability
    runtime_morts = {
        "GHOST_spec_sans_runtime": reach.get("ghosts_spec_sans_runtime", []),
        "UNROUTABLE_runtime_sans_slot": (
            reach["attention"].get("runtime_sans_slot_avec_cle", [])
            + reach["attention"].get("sans_slot_sans_cle", [])),
    }

    par = functools.partial(noms_par, slots, "etat")

    return {
        "slots": slots,
        "morts_par_transition": {
            "GHOST_slot_sans_runtime": par("GHOST"),
            "UNREACHED_slot_sans_chain": par("UNREACHED"),
            "CRED_UNWIRED_cle_non_cablee_209ae2": par("CRED_UNWIRED"),
            "CRED_INVALID_cle_absente": par("CRED_INVALID"),
            "LIVE_UNVERIFIED_statique_ok": par("LIVE_UNVERIFIED"),
            "LOCAL": par("LOCAL"),
        },
        "runtime_morts_amont": runtime_morts,
        "non_verifie": ["transport_reel", "model_serving", "oauth_cli_swarm"],
    }


def main() -> int:
    res = tracer()
    out = os.path.join(ROOT, "sandbox", "execution_trace.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    print("[trace] ou meurt chaque slot dans la chaine d execution :")
    for transition, liste in res["morts_par_transition"].items():
        if liste:
            print("  %-42s %s" % (transition, ", ".join(liste)))
    print("[trace] morts en amont (runtime) : GHOST=%s | UNROUTABLE=%s"
          % (res["runtime_morts_amont"]["GHOST_spec_sans_runtime"],
             res["runtime_morts_amont"]["UNROUTABLE_runtime_sans_slot"]))
    print("[trace] NON VERIFIE (exige un appel, jamais presume OK) : %s"
          % ", ".join(res["non_verifie"]))
    print("[trace] ecrit : %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
