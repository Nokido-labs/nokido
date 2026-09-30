"""tools/forge_veille_u1_run.py — chantier U1 : les depots de veille JAMAIS ingeres.

Owner 2026-09-08 : « 243 depots demandes jamais ingeres, lance ». La liste nominative
vit dans `sandbox/veille_depots_absents.json`, produite par le rapprochement de
`forge_veille_backlog_github` (qui RAPPROCHE et n'ingere rien).

Wrapper MINCE, sur le patron etabli de `forge_veille_campagne_run` : il DESIGNE la
campagne et delegue ; toute la logique d'ingestion reste dans
`forge_veille_github_direct.main`, qui sait deja chercher la bonne branche, chunker
par MarkdownChunker et ecrire avec `write_retry`. On ne reecrit ni le crawl ni
l'ingestion.

Deux differences avec une campagne nommee par l'owner, et elles comptent :

1. **On ne connait pas les fichiers de ces depots.** Une campagne nommee liste ses
   chemins un par un ; ici il y en a 243 et personne ne les a ouverts. On applique
   donc l'ordre de selection deja retenu par la veille — README d'abord, puis la
   documentation — et un depot dont AUCUN fichier ne repond est compte et NOMME, pas
   avale : sans ca, « 243 traites » ne se distingue pas de « 243 introuvables ».

2. **Le lot est borne et REPRENABLE.** Le journal `sandbox/veille_u1_faits.json`
   retient ce qui a deja ete traite, sinon l'ordre etant stable, chaque relance
   repasserait sur les memes depots de tete — piege paye le 2026-09-06 avec les
   ignorees du backfill.

Usage :
  run action=run_job script=tools/forge_veille_u1_run.py script_args="--limit 40"
  (reseau REQUIS -> online=true)
"""

from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : rattrape les depots de veille jamais ingeres (U1)"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

ABSENTS = ROOT / "sandbox" / "veille_depots_absents.json"
JOURNAL = ROOT / "sandbox" / "veille_u1_faits.json"

# Ordre de selection de la veille : le README porte l'essentiel de ce qu'un depot
# dit de lui-meme ; la doc vient ensuite. On ne descend pas dans le code : un depot
# de donnees ferait exploser le budget en chunks sans rien apprendre.
FICHIERS_PAR_DEFAUT = [
    "README.md",
    "README.rst",
    "docs/README.md",
    "AGENTS.md",
]


def charger_absents(chemin=ABSENTS):
    """Rend (liste, motif). Une source illisible se DIT, elle ne rend pas [] en silence."""
    p = Path(chemin)
    if not p.exists():
        return [], "fichier des absents INTROUVABLE : %s" % p
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [], "fichier des absents ILLISIBLE (%s: %s)" % (type(e).__name__, e)
    if isinstance(d, dict):
        absents = d.get("absents") or []
    elif isinstance(d, list):
        absents = d
    else:
        return [], "forme inattendue : %s" % type(d).__name__
    return [str(x) for x in absents if "/" in str(x)], "ok"


def deja_faits(chemin=JOURNAL):
    p = Path(chemin)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("faits", []))
    except Exception:  # noqa: BLE001 — journal illisible : on repart de zero, et on le dit
        print("[u1] journal de reprise ILLISIBLE — le lot repartira du debut", flush=True)
        return set()


def construire_cibles(absents, faits, limite):
    """Selectionne le prochain lot. Fonction PURE : aucun reseau, aucun disque."""
    restants = [r for r in absents if r not in faits]
    lot = restants[: max(0, int(limite))]
    return [(r, list(FICHIERS_PAR_DEFAUT)) for r in lot], len(restants)


def _noter(faits, nouveaux, chemin=JOURNAL):
    p = Path(chemin)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"faits": sorted(set(faits) | set(nouveaux))},
                            ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(prog="forge_veille_u1_run")
    ap.add_argument("--limit", type=int, default=40, help="depots par lot (defaut 40)")
    ap.add_argument("--dry-run", action="store_true", help="montre le lot sans ingerer")
    a = ap.parse_args()

    absents, motif = charger_absents()
    if not absents:
        print("[u1] AUCUNE cible — %s" % motif, flush=True)
        return 1
    faits = deja_faits()
    cibles, restants = construire_cibles(absents, faits, a.limit)
    print("[u1] %d absents au total, %d deja traites, %d restants -> lot de %d"
          % (len(absents), len(faits), restants, len(cibles)), flush=True)
    if not cibles:
        print("[u1] rien a faire : tous les depots connus ont ete traites", flush=True)
        return 0
    print("[u1] lot : %s" % ", ".join(r for r, _ in cibles), flush=True)
    if a.dry_run:
        print("[u1] dry-run — aucune ingestion", flush=True)
        return 0

    from nokido_agent.tools.forge_veille_github_direct import main as veiller

    rc = veiller(cibles)
    # Traite = TENTE. Un depot dont aucun fichier ne repond est note lui aussi,
    # sinon il reviendrait en tete de chaque lot pour toujours.
    _noter(faits, [r for r, _ in cibles])
    print("[u1] lot termine (rc=%s), %d depots notes comme tentes"
          % (rc, len(cibles)), flush=True)
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
