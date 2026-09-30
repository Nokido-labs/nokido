# -*- coding: utf-8 -*-
"""forge_veille_campagne_run.py — lance la campagne de veille du 2026-08-30.

Wrapper mince, sur le patron de `forge_veille_run.py` / `forge_veille_codex_run.py` :
`run_job` n'accepte qu'un chemin `.py` sans arguments, donc le choix des cibles ne
peut pas passer par la ligne de commande. Ce fichier ne fait que designer la
campagne et deleguer — toute la logique reste dans `forge_veille_github_direct`.

Onze depots nommes par l'owner, a evaluer comme organes greffables : ShinkaEvolve
(auto-amelioration evolutive), DSPy (optimisation des programmes LLM), Memento
(apprentissage par cas), mini-SWE-agent, openai/codex, dstack, OpenHands, EvoAgentX,
Ray, AI-Scientist-v2, Darwin Godel Machine.

Reseau : lancer en `run_job online=true lane=veille`. Le drapeau reseau n'agit QUE
la, et la lane evite d'empiler des jobs lourds — les deux lecons du 2026-08-30.

    run action=run_job script=tools/forge_veille_campagne_run.py online=true lane=veille
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : lance la campagne de veille du 2026-08-30"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools.forge_veille_github_direct import CAMPAGNE_2026_08_30, main  # noqa: E402

if __name__ == "__main__":
    print("[campagne] %d depot(s) : %s"
          % (len(CAMPAGNE_2026_08_30), ", ".join(r for r, _ in CAMPAGNE_2026_08_30)),
          flush=True)
    raise SystemExit(main(CAMPAGNE_2026_08_30))
