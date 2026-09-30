#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_warm_code_model.py — rend le modele de CODE resident, en detache.

POURQUOI CE FICHIER. Le routeur juge un slot local disponible sur `/api/ps`,
donc sur la presence d'un modele RESIDENT. Ollama repond en 0,06 s mais
`ollama_loaded` est vide -> les quatre slots locaux sortent available=false et
la cascade rend « RPM limit », motif qui ne decrit pas la cause.

Charger un modele de 4,5 Go depasse le plafond de duree du canal MCP (120 s) :
tout appel synchrone est tue avant la fin, et Ollama annule le chargement. Le
lanceur detache (`run_job`) n'accepte AUCUN argument. D'ou ce module sans
argument, qui fait une seule chose et survit au plafond.

Le binaire `ollama` n'est pas dans le PATH du compte de service : on passe par
l'API HTTP, jamais par la ligne de commande.

`keep_alive` borne la depense : Ollama decharge le modele tout seul.
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : rend le modele de code resident, en detache"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _base(valeur: str) -> str:
    """OLLAMA_HOST vaut souvent `127.0.0.1:11434`, sans schema : urlopen refuse."""
    valeur = (valeur or "").strip().rstrip("/")
    if not valeur:
        return "http://127.0.0.1:11434"
    return valeur if "://" in valeur else "http://" + valeur


OLLAMA = _base(os.environ.get("OLLAMA_HOST", ""))
MODELE = os.environ.get("NOKIDO_CODE_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")
KEEP_ALIVE = os.environ.get("NOKIDO_CODE_KEEP_ALIVE", "30m")


def residents() -> list:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=10) as r:
            return [m.get("name") for m in json.load(r).get("models", [])]
    except OSError as exc:
        print("[warm] /api/ps injoignable : %s" % exc)
        return []


def main() -> int:
    deja = residents()
    if any(MODELE.split(":")[0] in (m or "") for m in deja):
        print("[warm] deja resident : %s" % deja)
        return 0

    corps = json.dumps({"model": MODELE, "prompt": "ok", "stream": False,
                        "keep_alive": KEEP_ALIVE,
                        "options": {"num_predict": 4}}).encode("utf-8")
    req = urllib.request.Request(OLLAMA + "/api/generate", data=corps,
                                 headers={"Content-Type": "application/json"})
    debut = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            r.read()
    except OSError as exc:
        print("[warm] echec apres %.0fs : %s" % (time.time() - debut, exc))
        return 1
    print("[warm] %s resident en %.0fs (keep_alive=%s)"
          % (MODELE, time.time() - debut, KEEP_ALIVE))
    print("[warm] residents : %s" % residents())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
