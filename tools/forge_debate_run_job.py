# -*- coding: utf-8 -*-
"""forge_debate_run_job.py — worker DEPORTE du debat inter-agents (params-driven).

Spawne en SUBPROCESS par web_hub POST /api/debate/run : lit un fichier params JSON
{objective, constraint, rounds, latent}, appelle forge_debate_job.run_debate, ecrit le
resultat JSON dans --out. Le mode latent charge Qwen-0.5B + link/LoRA (torch) DANS CE
process — jamais dans web_hub :7400 (isolation memoire du service GUI). Isole aussi le
cache HF vers la zone agent-inscriptible.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # tools/ -> racine Nokido
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# HF cache -> zone agent-inscriptible (mode latent = charge Qwen ; evite Default\.cache WinError 5)
_HFC = ROOT / "sandbox" / "workspace" / "hf_cache"
try:
    _HFC.mkdir(parents=True, exist_ok=True)
    for _k in ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
               "SENTENCE_TRANSFORMERS_HOME", "XDG_CACHE_HOME"):
        os.environ.setdefault(_k, str(_HFC))
except Exception:  # noqa: BLE001
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    p = json.loads(Path(a.params).read_text(encoding="utf-8"))
    objective = (str(p.get("objective") or "")).strip() or "Debat sans objectif fourni."
    constraint = (str(p.get("constraint") or "")).strip() or "Repondre concis."
    try:
        rounds = max(1, min(3, int(p.get("rounds") or 1)))
    except Exception:  # noqa: BLE001
        rounds = 1
    latent = bool(p.get("latent"))

    from nokido_agent.tools import forge_debate_job as D

    # `participants=None` -> panel construit depuis `provider_scores` (mesure) et roles
    # derives de l'OBJECTIF COURANT. `DEFAULT_PARTICIPANTS` portait le cadrage d'un
    # debat de juin : passe tel quel, il produisait une sortie hors sujet meme avec des
    # providers sains (mesure 2026-09-05). Un panel explicite reste possible via params.
    parts = p.get("participants") or None
    res = asyncio.run(
        D.run_debate(objective, constraint, parts, rounds, latent=latent))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, default=str), encoding="utf-8")
    # Capsule cognitive a cote du resultat (2026-09-28) : ce que recoit une boite noire.
    try:
        print("capsule :", D.ecrire_capsule(res, a.out), flush=True)
    except Exception as exc:  # noqa: BLE001 -- la capsule ne fait jamais echouer le debat
        print("capsule NON ecrite :", type(exc).__name__, flush=True)
    print("OK", res.get("mode"), flush=True)


if __name__ == "__main__":
    main()
