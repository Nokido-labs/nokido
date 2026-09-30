"""_patch_explore_collecte.py — patch ponctuel : découpler COLLECTE et AFFICHAGE dans deep_explore.

Suite directe de `_patch_explore_ranking.py`, et correction de son insuffisance — mesurée
le 2026-08-02 juste après l'avoir appliqué :

    collecte max_hits=90   ->   90 hits, dont 0 des modules cherchés
    collecte max_hits=2000 -> 1425 hits, dont 47 des modules cherchés

`breadth` bornait la RECHERCHE elle-même. Le classement, lui, n'agit qu'à l'affichage : il
ne peut pas repêcher ce qui n'a jamais été collecté. Premier remède insuffisant, parce
qu'il traitait l'endroit où le bruit se VOYAIT et non l'endroit où l'information se PERDAIT.

Un troisième plafond mordait en silence : `digest[:8000]` avec des extraits de 400
caractères ne laisse passer que ~19 extraits — la diversité gagnée par le plafond
par-fichier était reperdue à la troncature finale. Les extraits passent donc à 240.

Trois budgets, désormais explicites et indépendants :
  collecte   400 / 1200 / 3000  — local, déterministe, 0 token : chercher large ne coûte
                                  que du CPU, et ne pas trouver coûte une session ;
  affichage   20 /   30 /   60  — ce qui entre réellement dans le contexte de l'agent ;
  par_fichier 2                 — pour que le budget d'affichage couvre des modules variés.

Exécution : `run action=trusted_script path=tools/_patch_explore_collecte.py`.
Sécurités identiques : ancres uniques, sauvegarde hors dépôt, `compile()` avant et après,
rollback automatique, idempotent.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

__FORGE_COLOR__ = "outillage/migration-ponctuelle"

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"
SAUVEGARDE = Path(r"C:\tmp\forge_mcp_registry.py.bak_collecte")

REMPLACEMENTS = [
    (
        '        max_hits = {"narrow": 40, "medium": 90, "wide": 180}.get(breadth, 90)',
        "        # Budgets DISTINCTS (mesure 2026-08-02) : borner la COLLECTE revenait a ne\n"
        "        # jamais voir le module cherche -- a 90 hits, 0 extrait des modules vises ;\n"
        "        # a 2000, 47. Chercher large est local et gratuit ; c'est l'AFFICHAGE qui\n"
        "        # coute des tokens, donc lui seul reste serre.\n"
        '        collecte = {"narrow": 400, "medium": 1200, "wide": 3000}.get(breadth, 1200)\n'
        '        affichage = {"narrow": 20, "medium": 30, "wide": 60}.get(breadth, 30)',
    ),
    (
        "            return fle.search(query, _globs, context=2, max_hits=max_hits)",
        "            return fle.search(query, _globs, context=2, max_hits=collecte)",
    ),
    (
        "        montres = _classer_explore(hits, query)",
        "        montres = _classer_explore(hits, query, par_fichier=2, plafond=affichage)",
    ),
    (
        '            _parts.append(str(h.get("excerpt", ""))[:400])',
        "            # 240 et non 400 : a 8000 chars de digest, des extraits longs ne laissent\n"
        "            # passer que ~19 entrees et annulent la diversite gagnee plus haut.\n"
        '            _parts.append(str(h.get("excerpt", ""))[:240])',
    ),
]


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    if "affichage = {" in src:
        print("[patch] deja applique — rien a faire")
        return 0
    if "_classer_explore" not in src:
        print("[patch] ABANDON : _patch_explore_ranking.py doit etre applique d'abord")
        return 1
    patche = src
    for vieux, neuf in REMPLACEMENTS:
        n = patche.count(vieux)
        if n != 1:
            print(f"[patch] ABANDON : ancre trouvee {n} fois -> {vieux.strip()[:60]!r}")
            return 2
        patche = patche.replace(vieux, neuf)
    try:
        compile(patche, str(CIBLE), "exec")
    except SyntaxError as exc:
        print(f"[patch] ABANDON : AST invalide apres patch — {exc}")
        return 3
    SAUVEGARDE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(CIBLE, SAUVEGARDE)
    CIBLE.write_text(patche, encoding="utf-8")
    try:
        compile(CIBLE.read_text(encoding="utf-8"), str(CIBLE), "exec")
    except SyntaxError as exc:
        shutil.copy(SAUVEGARDE, CIBLE)
        print(f"[patch] ROLLBACK : relecture invalide — {exc}")
        return 4
    print(f"[patch] OK — {CIBLE.name} {len(patche)} chars, AST valide, sauvegarde={SAUVEGARDE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
