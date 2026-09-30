"""forge_soif_demo.py — boucle SOIF complete sur UN gap reel, de bout en bout.

Demonstration 25-07 : la soif de connaissance, sondee depuis l'INTENTION de Nokido
(et non la distance arbitraire), a trouve un gap CERTAIN reel et actionnable —
« HNSW recall approximatif vs exact » (rerank -6.28), le savoir qui manque a Nokido
pour basculer sa recherche RAG sur Qdrant en securite (etape 3 du chantier Qdrant,
laissee ouverte faute de ce savoir). Ce script joue la boucle entiere :
  gap ressenti -> veille approfondie (research_agent) -> integration RAG.

Deporte (run_job) : la veille est lourde (SearXNG + crawl + LLM). Sans reseau/SearXNG
elle rend peu — c'est aussi un resultat honnete (soif vivante mais organe de veille
a sec), a distinguer d'un echec du declencheur.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/epistemic : boucle soif complete sur un gap reel (demo)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GAP = ("HNSW approximate nearest neighbor recall versus exact brute force cosine "
       "search: recall@k tradeoff, ef_search / M parameters, when approximation "
       "degrades retrieval quality in RAG vector databases")


def main() -> int:
    from nokido_agent.app import forge_epistemic_veille as ev

    print(f"[soif] gap vise: {GAP[:70]}...", flush=True)
    cov = ev.coverage_dense(GAP)
    print(f"[soif] couverture avant veille: {cov}", flush=True)

    # feel_gap : emet le ressenti (critical_event + CORTISOL_EPISTEMIC)
    try:
        felt = ev.feel_gap(domain="reference", query=GAP)
        print(f"[soif] ressenti emis: gap={felt.get('gap')} objectif={str(felt.get('veille_objective'))[:60]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[soif] feel_gap KO: {e}", flush=True)

    # veille_on_gap run_now=True : research_agent comble le gap -> RAG
    try:
        res = ev.veille_on_gap(GAP, domain="reference", run_now=True, max_rounds=2, max_urls=6)
        print(f"[soif] VEILLE terminee: {json.dumps(res, ensure_ascii=False, default=str)[:400]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[soif] veille KO: {type(e).__name__}: {e}", flush=True)
        return 1

    # couverture APRES : le gap est-il comble ?
    cov2 = ev.coverage_dense(GAP)
    print(f"[soif] couverture APRES veille: {cov2}", flush=True)
    print(f"[soif] BILAN: avant={cov.get('score')} apres={cov2.get('score')} "
          f"-> {'COMBLE' if (cov2.get('score') or -99) > (cov.get('score') or -99) + 1 else 'peu/pas comble (veille a sec ?)'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
