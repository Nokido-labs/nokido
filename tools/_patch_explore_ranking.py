"""_patch_explore_ranking.py — patch ponctuel : classement du digest de forge_deep_explore.

Même convention que les `tools/_patch_deep_explore*.py` existants : script one-shot,
préfixé `_`, qui édite un fichier que ni le sandbox ni `governed_edit` ne peuvent écrire.

Pourquoi ce détour : `app/forge_mcp_registry.py` est CRITICAL_FILE, donc `governed_edit`
refuse ; et le compte sandbox n'a pas l'ACL d'écriture dessus — `os.access(p, W_OK)` y
répond pourtant `True`, car sous Windows il ne teste que l'attribut lecture-seule, jamais
les ACL. Mesuré le 2026-08-02 : un capteur de plus qui dit oui avant de refuser.
Exécution réelle : `run action=trusted_script path=tools/_patch_explore_ranking.py`.

Ce que le patch fait, et rien d'autre :
  1. la docstring cesse de promettre une « synthese via modele LOCAL » que le code ne
     faisait pas (il concatène des extraits bruts) ;
  2. import défensif de `forge_explore_rank.classer` ;
  3. `hits[:60]` (les 60 premiers dans l'ordre ALPHABÉTIQUE) devient un top-60 CLASSÉ,
     borné à 3 extraits par fichier ;
  4. la réponse expose `hits_montres` — un filtre qui écarte des données le DIT.

Sécurités : ancres exigées UNIQUES (sinon abandon sans écrire), sauvegarde hors dépôt,
`compile()` avant ET après écriture, rollback automatique si l'AST casse. Idempotent :
si le patch est déjà en place, les ancres ne matchent plus et le script s'arrête proprement.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

__FORGE_COLOR__ = "outillage/migration-ponctuelle"

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"
SAUVEGARDE = Path(r"C:\tmp\forge_mcp_registry.py.bak_ranking")

REMPLACEMENTS = [
    (
        "        recherche deterministe (regex) sur globs + synthese via modele LOCAL.",
        "        recherche DETERMINISTE (regex) sur globs, puis CLASSEMENT (forge_explore_rank)\n"
        "        et coupe. Aucune synthese LLM ici : le digest est fait d'extraits BRUTS --\n"
        "        la docstring promettait une synthese que le code ne faisait pas (2026-08-02).",
    ),
    (
        '        hits = res.get("hits", [])',
        '        hits = res.get("hits", [])\n'
        "        try:\n"
        "            from forge_explore_rank import classer as _classer_explore\n"
        "        except Exception:  # muet-ok : le classement est un confort, la recon reste utile\n"
        "            def _classer_explore(_h, _q, **_k):\n"
        "                return _h[:60]",
    ),
    (
        "        for h in hits[:60]:",
        "        montres = _classer_explore(hits, query)\n"
        "        for h in montres:",
    ),
    (
        '            "n_hits": len(hits),',
        '            "n_hits": len(hits),\n'
        "            # Un filtre qui ecarte des donnees le DIT (RULES_SHARED) : sinon la\n"
        "            # couverture est surestimee en silence.\n"
        '            "hits_montres": len(montres),',
    ),
]


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    if "_classer_explore" in src:
        print("[patch] deja applique — rien a faire")
        return 0
    patche = src
    for vieux, neuf in REMPLACEMENTS:
        n = patche.count(vieux)
        if n != 1:
            print(f"[patch] ABANDON : ancre trouvee {n} fois -> {vieux.strip()[:60]!r}")
            return 1
        patche = patche.replace(vieux, neuf)
    try:
        compile(patche, str(CIBLE), "exec")
    except SyntaxError as exc:
        print(f"[patch] ABANDON : AST invalide apres patch — {exc}")
        return 2
    SAUVEGARDE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(CIBLE, SAUVEGARDE)
    CIBLE.write_text(patche, encoding="utf-8")
    try:
        compile(CIBLE.read_text(encoding="utf-8"), str(CIBLE), "exec")
    except SyntaxError as exc:
        shutil.copy(SAUVEGARDE, CIBLE)
        print(f"[patch] ROLLBACK : relecture invalide — {exc}")
        return 3
    print(f"[patch] OK — {CIBLE.name} {len(patche)} chars, AST valide, sauvegarde={SAUVEGARDE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
