# -*- coding: utf-8 -*-
"""forge_capability_benchmark.py — ce que Nokido SAIT FAIRE, mesure, par dimension. Lecture seule.

__FORGE_COLOR__ ci-dessous : qualite. Le module LIT des mesures ; il n'en produit aucune.

HISTOIRE. Ce fichier etait un BOUCHON (mission rsi-frein-auto, 2026-10-02) : une classe
`CapabilityBenchmarker` qui fabriquait une « question de sonde » via `PersonaEngine` et
imprimait « En attente de la reponse reelle du modele » -- aucun modele n'etait jamais
appele, aucun score jamais rendu. Son nom promettait une capacite que le corps n'avait pas.

CE QU'IL FAIT. Il lit les capacites DEJA mesurees par les bancs scelles (via
`forge_generation.capacites_mesurees`, ex. `retrieval_dense_ndcg10@<sha>` mesure par
`forge_bench_beir --capacite` sur l'examen gele) et les rend sous UNE forme :

    {dimension: {"etat": "CONNU", "score": float, "bruit": float|None, "n": int|None,
                 "age_s": float|None}}

Une dimension absente, ou dont le score est illisible, est INCONNU -- jamais zero, jamais
« pas de capacite » : une capacite non mesuree n'est pas une capacite nulle.

CE QU'IL NE FAIT PAS. Il ne lance aucun banc (c'est `forge_bench_beir` et ses pairs) et ne
juge aucun gain (c'est `forge_generation._verdict_capacites` / `frein_si_recul`).

Usage :
    LAFORGE_PYTHON app/forge_capability_benchmark.py              # toutes les dimensions
    LAFORGE_PYTHON app/forge_capability_benchmark.py --dimension retrieval_dense_ndcg10@...
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/benchmark : capacites mesurees par dimension, lues et datees"

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONNU, INCONNU = "CONNU", "INCONNU"


def _source() -> tuple:
    """(brut, raison) : la mesure telle que `forge_generation` la sert, ou pourquoi on ne l'a pas."""
    try:
        from nokido_agent.app import forge_generation as _gen
    except Exception as exc:  # noqa: BLE001 - registre des generations introuvable : dit
        return None, "forge_generation illisible (%s)" % type(exc).__name__
    f = getattr(_gen, "capacites_mesurees", None)
    if f is None:
        return None, "capacites_mesurees absent de forge_generation (version anterieure)"
    try:
        return f(), ""
    except Exception as exc:  # noqa: BLE001 - mesure illisible : INCONNU partout, et dit
        return None, "capacites_mesurees a leve (%s: %s)" % (type(exc).__name__, str(exc)[:120])


def capacites(maintenant: float | None = None) -> dict:
    """Toutes les dimensions mesurees. Rend {"source", "raison", "capacites": {...}}."""
    from nokido_agent.app.forge_generation import capacites_normalisees

    brut, raison = _source()
    if brut is None:
        return {"source": INCONNU, "raison": raison, "capacites": {}}
    out = {}
    for dim, e in capacites_normalisees(brut, maintenant).items():
        if not e["lisible"]:
            out[dim] = {"etat": INCONNU, "raison": e["motif"]}
            continue
        out[dim] = {"etat": CONNU, "score": e["score"], "bruit": e["bruit"], "n": e["n"],
                    "age_s": e["age_s"]}
    return {"source": CONNU, "raison": "" if out else "aucune dimension mesuree",
            "capacites": out}


def capacite(dimension: str, maintenant: float | None = None) -> dict:
    """Une dimension. Absente ou illisible -> {"etat": "INCONNU", "raison": ...}."""
    r = capacites(maintenant)
    e = r["capacites"].get(dimension)
    if e is None:
        return {"etat": INCONNU, "raison": r["raison"] or "dimension %r non mesuree" % dimension}
    return e


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Capacites mesurees de Nokido (lecture seule)")
    ap.add_argument("--dimension", default=None)
    a = ap.parse_args(argv)
    r = capacite(a.dimension) if a.dimension else capacites()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
