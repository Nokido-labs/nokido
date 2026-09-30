# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/sense-of-agency
SENTIMENT D'AGENTIVITE — comparateur efference-copy (modele de Frith/Blakemore).

GAP adresse (doc cartographie_fonctions_cognitives_immaterialles, aveu propre du doc) :
  « le sentiment d'agentivite — la sensation d'etre l'auteur de ses propres actions —
  n'est pas implemente ; les agents executent des actions sans 'ressentir' qu'ils les
  causent. » C'est le SEUL des manques phenomenologiques qui soit tractable.

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  Les briques existent mais ne produisent PAS d'attribution d'agentivite :
    - forge_world_model.predict(state_emb, action) = FORWARD MODEL (efference copy) -> reutilise.
    - forge_active_inference.compute_surprise(pred, obs) = surprise du MONDE (etat inattendu),
      pas l'attribution "c'est MOI qui ai cause ca".
  L'agentivite = comparaison DIRECTIONNELLE entre l'effet PREDIT de mon action (Delta
  predit par le forward model) et l'effet OBSERVE (Delta reel), liee temporellement a
  l'action. Match directionnel + effet reel + contiguite -> "j'en suis l'auteur".
  Distinct de la surprise scalaire : un changement peut etre tres surprenant ET de moi
  (forte agentivite) ou peu surprenant ET externe (faible agentivite).

0 LLM, 0 cloud. numpy seul.
  LAFORGE_PYTHON app/forge_agency.py    # selftest : discrimine auteur vs externe vs sans-effet
"""
from __future__ import annotations
import os, sys, math, time

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)

import numpy as np

_intents: dict = {}


def _vec(x):
    return np.asarray(x, dtype=float).ravel()


def _sat(x, k=0.5):
    return 1.0 - math.exp(-max(0.0, x) / k)


def forward_predict(state_emb, action_text: str):
    """Effet predit de l'action (efference copy). Reutilise forge_world_model si dispo,
    sinon attend une prediction explicite via register(predicted=...)."""
    try:
        from nokido_agent.app import forge_world_model as wm
        return _vec(wm.predict(_vec(state_emb), action_text))
    except Exception:
        return None


def register(action_text: str, state_before, predicted=None, tau_s: float = 30.0) -> str:
    """Enregistre une action + son effet PREDIT (forward model). Retourne un intent_id.
    predicted=None -> tente forge_world_model.predict(state_before, action_text)."""
    before = _vec(state_before)
    if predicted is None:
        predicted = forward_predict(before, action_text)
    if predicted is None:
        raise ValueError("pas de prediction (world_model indispo) ; fournir predicted=")
    iid = f"act_{int(time.time() * 1000)}_{len(_intents)}"
    _intents[iid] = {"ts": time.time(), "action": action_text,
                     "before": before, "predicted": _vec(predicted), "tau": tau_s}
    return iid


def evaluate(intent_id: str, observed_state, keep: bool = False) -> dict:
    """Compare effet predit vs effet observe -> signal d'agentivite [0,1].
      attribution = cos(Delta_predit, Delta_observe)  (mon intention explique-t-elle le reel ?)
      efficacy    = un effet reel s'est-il produit ?  (sinon pas d'auteur)
      temporal    = contiguite a l'action (efference-copy = liee dans le temps)
      agency = attribution * efficacy * temporal."""
    it = _intents.get(intent_id)
    if it is None:
        return {"ok": False, "reason": "intent inconnu"}
    before, predicted, observed = it["before"], it["predicted"], _vec(observed_state)
    pd, od = predicted - before, observed - before
    npd, nod = float(np.linalg.norm(pd)), float(np.linalg.norm(od))

    attribution = 0.0
    if npd > 1e-9 and nod > 1e-9:
        attribution = max(0.0, float(np.dot(pd, od) / (npd * nod)))  # alignement directionnel
    rel_change = nod / (float(np.linalg.norm(before)) + 1e-9)
    efficacy = _sat(rel_change, k=0.25)
    dt = time.time() - it["ts"]
    temporal = math.exp(-dt / max(1e-3, it["tau"]))
    agency = round(attribution * efficacy * temporal, 3)

    if not keep:
        _intents.pop(intent_id, None)
    tag = "auteur" if agency >= 0.5 else ("externe" if efficacy >= 0.5 else "sans-effet")
    return {"ok": True, "agency": agency, "attribution": round(attribution, 3),
            "efficacy": round(efficacy, 3), "temporal": round(temporal, 3),
            "dt_s": round(dt, 2), "tag": tag}


def publish(result: dict, floor: float = 0.6) -> str:
    """Forte agentivite -> renforce la self-efficacy (dopamine) sur le bus endocrine."""
    if not result.get("ok") or result["agency"] < floor:
        return "below_floor"
    try:
        from nokido_agent.app import forge_endocrine as fe
        fe.release(hormone="agency_dopamine", level=result["agency"], ttl_s=120,
                   source="agency", reason=f"auteur attribution={result['attribution']}",
                   meta={"tag": result["tag"]})
        return "published"
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}:{e}"


def _selftest():
    rng = np.random.default_rng(0)
    d = 16
    before = rng.normal(size=d)
    intent = rng.normal(size=d) * 0.6           # l'effet que MON action vise
    predicted = before + intent

    cases = {
        "A_auteur(matche)":    before + intent + 0.05 * rng.normal(size=d),  # observe ~ predit
        "B_externe(orthog)":   before + rng.normal(size=d) * 0.6,            # change, mais pas mon intention
        "C_sans_effet":        before + 0.001 * rng.normal(size=d),          # rien ne bouge
        "D_inefficace":        before.copy(),                               # je predis, mais aucun effet
    }
    print("=== AGENCY selftest (efference-copy) ===")
    results = {}
    for name, observed in cases.items():
        iid = register("mon_action", before, predicted=predicted)
        r = evaluate(iid, observed)
        results[name] = r
        print(f"  [{r['tag']:<10}] agency={r['agency']:.3f} "
              f"(attrib={r['attribution']:.2f} effic={r['efficacy']:.2f} temp={r['temporal']:.2f})  {name}")
    ok = (results["A_auteur(matche)"]["agency"] > 0.5 and
          results["B_externe(orthog)"]["agency"] < results["A_auteur(matche)"]["agency"] and
          results["C_sans_effet"]["agency"] < 0.2 and
          results["D_inefficace"]["agency"] < 0.2)
    print(f"-> discriminateur d'auteur {'OK' if ok else 'KO'} : A>>B,C,D")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
