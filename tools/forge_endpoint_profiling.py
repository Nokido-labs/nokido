#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quelle est la SPECIALITE de chaque endpoint, et quel role lui confier ?

Le routeur attribue aujourd'hui ses `use_case` par habitude : les chaines ont
ete ecrites en avril et jamais confrontees a ce que les endpoints font
REELLEMENT. Resultat mesure le 2026-08-18 : sept chaines sur seize demarraient
par un slot mort, et le seul critere disponible etait l'ordre de la liste.

Ce module mesure quatre grandeurs, puis PROPOSE un role — il ne le decide pas.
Changer qui repond a quoi modifie le comportement de Nokido : c'est une
decision, pas une optimisation automatique.

  LATENCE   temps jusqu'a la reponse complete d'un prompt court
  DEBIT     tokens generes par seconde sur une reponse plus longue
  CONTEXTE  fenetre annoncee par le catalogue (jamais devinee)
  CAPACITES outils / sorties structurees, quand le fournisseur les publie
  QUOTA     en-tetes `x-ratelimit-*` quand ils existent, NON MESURE sinon

Les roles proposes reprennent les `use_case` du routeur, pour que la
proposition soit directement comparable a l'existant :

  sentinel/speed   latence faible — surveiller, classer, router
  code             modele oriente code (nom, ou specialite annoncee)
  reasoning        modele de raisonnement — planifier, arbitrer
  context          grande fenetre — resumer, digerer des logs
  tool_call        outils supportes — orchestrer
  general          repond correctement sans specialite marquee
  fallback_local   local : lent parfois, mais sans quota ni egress

    run action=run_job script=tools/forge_endpoint_profiling.py online=true
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : specialite et role de chaque endpoint LLM"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools.forge_endpoint_commun import catalogue, plus_petits, requete, taille_apparente  # noqa: E402

SORTIE = ROOT / "sandbox" / "endpoint_profiling.json"
TIMEOUT = 45
PAR_FOURNISSEUR = 3

# Seules les surfaces PROUVEES joignables le 2026-08-18 : profiler un endpoint
# qui rend 402 mesurerait la panne, pas la specialite.
SURFACES = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("ollama", "", "http://127.0.0.1:11434/v1"),
    ("lmstudio", "LMSTUDIO_TOKEN", "http://127.0.0.1:1234/v1"),
]

_INDICES_CODE = ("coder", "code", "codestral", "devstral", "starcoder")
_INDICES_RAISON = ("-r1", "r1-", "reason", "think", "-o1", "qwq", "nemotron")


# `requete`, `catalogue` et le tri par taille viennent du socle commun.
_taille = taille_apparente


def mesurer(base: str, cle: str, modele: str) -> dict:
    """Deux appels : un court pour la LATENCE, un plus long pour le DEBIT."""
    fiche = {"modele": modele}
    charge = json.dumps({"model": modele,
                         "messages": [{"role": "user", "content": "Reponds: ok"}],
                         "max_tokens": 8}).encode("utf-8")
    depart = time.time()
    try:
        with urllib.request.urlopen(requete(f"{base}/chat/completions", cle, charge),
                                    timeout=TIMEOUT) as r:
            r.read(2000)
        fiche["latence_s"] = round(time.time() - depart, 2)
    except urllib.error.HTTPError as exc:
        return {**fiche, "etat": "MORT", "motif": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {**fiche, "etat": "NON_MESURE", "motif": type(exc).__name__}

    charge = json.dumps({"model": modele,
                         "messages": [{"role": "user",
                                       "content": "Compte de 1 a 40, separes par des virgules."}],
                         "max_tokens": 160}).encode("utf-8")
    depart = time.time()
    try:
        with urllib.request.urlopen(requete(f"{base}/chat/completions", cle, charge),
                                    timeout=TIMEOUT) as r:
            corps = json.loads(r.read().decode("utf-8", errors="replace"))
        ecoule = max(0.001, time.time() - depart)
        usage = corps.get("usage") or {}
        sortis = int(usage.get("completion_tokens") or 0)
        if not sortis:
            texte = ((corps.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            sortis = max(1, len(texte) // 4)      # approximation assumee
        fiche["debit_tok_s"] = round(sortis / ecoule, 1)
        fiche["etat"] = "VIVANT"
    except Exception as exc:  # noqa: BLE001
        fiche["etat"] = "PARTIEL"
        fiche["motif"] = type(exc).__name__
    return fiche


def role_propose(fiche: dict, meta: dict) -> tuple[str, str]:
    """(role, justification MESUREE). Jamais un role sans sa raison."""
    nom = fiche["modele"].lower()
    contexte = int(meta.get("context_length") or meta.get("context_window") or 0)
    params = meta.get("supported_parameters") or []
    latence = fiche.get("latence_s", 99)
    debit = fiche.get("debit_tok_s", 0)

    if any(mot in nom for mot in _INDICES_CODE):
        return "code", f"nom oriente code, {debit} tok/s"
    if any(mot in nom for mot in _INDICES_RAISON):
        return "reasoning", f"modele de raisonnement, {latence}s de latence"
    if contexte >= 200_000:
        return "context", f"fenetre annoncee {contexte} tokens"
    if "tools" in params or "tool_choice" in params:
        return "tool_call", "outils supportes (annonce par le catalogue)"
    if latence <= 1.5 and debit >= 30:
        return "sentinel/speed", f"{latence}s de latence, {debit} tok/s"
    if fiche.get("local"):
        return "fallback_local", "aucun quota, aucun egress"
    return "general", f"{latence}s, {debit} tok/s, sans specialite marquee"


def quota(entetes: dict) -> str:
    restants = [f"{n}={v}" for n, v in entetes.items()
                if "ratelimit" in n.lower() and "remaining" in n.lower()]
    return " · ".join(restants) if restants else "NON MESURE"


def main() -> int:
    from nokido_agent.app.forge_secrets import get_secret

    profils = []
    for etiquette, env_key, base in SURFACES:
        cle = (get_secret(env_key) or "") if env_key else ""
        _code, modeles, entetes = catalogue(base, cle)
        if not modeles:
            print(f"\n=== {etiquette} — catalogue muet, NON MESURE")
            continue
        # On profile les plus petits : ils repondent, et le role se lit aussi
        # bien sur eux. Profiler un 405B a froid mesurerait le chargement.
        choisis = plus_petits(modeles, PAR_FOURNISSEUR)
        print(f"\n=== {etiquette} — {len(modeles)} modele(s) · quota: {quota(entetes)}")
        for meta in choisis:
            fiche = mesurer(base, cle, str(meta.get("id")))
            fiche["local"] = "127.0.0.1" in base
            fiche["fournisseur"] = etiquette
            if fiche.get("etat") in ("VIVANT", "PARTIEL"):
                role, pourquoi = role_propose(fiche, meta)
                fiche["role_propose"], fiche["justification"] = role, pourquoi
                print(f"  {fiche['modele'][:40]:42} {fiche.get('latence_s', '?'):>6}s "
                      f"{fiche.get('debit_tok_s', '?'):>7} tok/s  -> {role:16} ({pourquoi})")
            else:
                print(f"  {fiche['modele'][:40]:42} {fiche['etat']} — {fiche.get('motif', '')}")
            profils.append(fiche)

    retenus = [p for p in profils if p.get("role_propose")]
    print(f"\n{len(retenus)} endpoint(s) profile(s). Repartition proposee :")
    par_role: dict[str, list[str]] = {}
    for p in retenus:
        par_role.setdefault(p["role_propose"], []).append(f"{p['fournisseur']}:{p['modele']}")
    for role, membres in sorted(par_role.items()):
        print(f"  {role:16} {', '.join(m[:38] for m in membres)}")
    print("\nPROPOSITION, pas application : changer qui repond a quoi modifie le "
          "comportement de Nokido et reste une decision humaine.")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"profils": profils}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"detail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
