# -*- coding: utf-8 -*-
"""Inscrit les generations DEPOSEES dans l'arbre versionne.

__FORGE_COLOR__ = "qualite/build : inscription gouvernee des generations mesurees"

POURQUOI (2026-09-09). `docs/generations/` n'est pas inscriptible par les comptes
sandbox, sous lesquels tourne `run_job` — donc la CI mesure sa generation, la juge
STABLE, et ne peut PAS l'inscrire. Elle depose alors dans
`sandbox/generations_en_attente/` et le dit. Mais PERSONNE ne venait chercher : la
vitalite avait son passeur (`forge_vitalite_inscrire.py`), la generation n'en avait
aucun. Mesure du jour : GEN-00011 mesuree STABLE sur le sha 45a601ea5, restee en
attente, et le critere de sortie de la phase 0 — un statut FERME PAR COMMIT —
inatteignable non pas faute de mesure, mais faute de PASSEUR.

    run action=trusted_script path=tools/forge_generation_inscrire.py

🔑 APPEND-ONLY. Une generation est un objet IMMUABLE : elle date un sha et un
verdict. On n'en reecrit jamais une deja inscrite — si le depot en attente differe
de la cible, on REFUSE et on le DIT, plutot que de choisir en silence laquelle des
deux versions est la vraie.

🔑 On conclut par RELECTURE de la cible, jamais sur l'absence d'erreur (meme regle
que le passeur de vitalite : un `write_text` qui ne leve pas n'est pas une preuve
que le fichier est la et lisible).

🔑 Une borne dit COMBIEN : chaque depot est classe et compte (INSCRITE, IDENTIQUE,
DIVERGENTE, ILLISIBLE), pour qu'un rattrapage reste possible sur ce qui est ecarte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Le lecteur a trois etats est PARTAGE avec forge_vitalite_inscrire : le recopier
# est precisement ce que le cliquet de clones a refuse le 2026-09-09.

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_lecture_json import lire as _lire

ROOT = Path(__file__).resolve().parents[1]
CIBLE_DIR = ROOT / "docs" / "generations"
DEPOT_DIR = ROOT / "sandbox" / "generations_en_attente"


def _rel(p: Path) -> str:
    """Chemin DIT relatif au depot s'il y vit, absolu sinon -- ne leve JAMAIS.

    Meme precaution que forge_vitalite_inscrire : `relative_to` a deja fait perdre
    un verdict rc=0 sur l'affichage du chemin (run GitHub 34138167173, 2026-09-07).
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# `_lire` etait recopie ici depuis forge_vitalite_inscrire (52 noeuds identiques) :
# cliquet de clones rompu et CI GitHub rouge le 2026-09-09 (run 34342552425).
# Il est desormais importe de forge_lecture_json (voir en tete de fichier).


def inscrire(depot_dir: Path = DEPOT_DIR, cible_dir: Path = CIBLE_DIR) -> dict:
    """Rend un bilan CLASSE. N'ecrase jamais une generation deja inscrite."""
    bilan = {"inscrites": [], "identiques": [], "divergentes": [],
             "illisibles": [], "non_relues": []}
    if not depot_dir.is_dir():
        return bilan
    for depot in sorted(depot_dir.glob("*.json")):
        donnees, etat = _lire(depot)
        if etat != "LU":
            bilan["illisibles"].append((depot.name, etat))
            continue
        cible = cible_dir / depot.name
        deja, etat_cible = _lire(cible)
        if etat_cible.startswith("ILLISIBLE"):
            # On ne remplace pas ce qu'on n'a pas su lire : on ignore ce qu'on
            # detruirait.
            bilan["illisibles"].append((depot.name, "cible " + etat_cible))
            continue
        if etat_cible == "LU":
            # Deja inscrite. Immuable : on ne reecrit pas, on CONSTATE.
            if deja == donnees:
                bilan["identiques"].append(depot.name)
            else:
                bilan["divergentes"].append(depot.name)
            continue
        cible_dir.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
        # RELECTURE : un write qui ne leve pas ne prouve pas que le fichier est la.
        relu, etat_relu = _lire(cible)
        if etat_relu == "LU" and relu.get("generation") == donnees.get("generation"):
            bilan["inscrites"].append((depot.name, donnees.get("statut", "?"),
                                       (donnees.get("depot") or {}).get("sha", "")[:9]))
        else:
            bilan["non_relues"].append((depot.name, etat_relu))
    return bilan


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="forge_generation_inscrire",
        description="Inscrit les generations deposees dans l'arbre versionne")
    # T0 (2026-09-09) : la CI de REFERENCE s'execute dans un worktree detache, et y
    # ecrit sa generation -- le worktree vivant sous sandbox/, l'ACL qui bloquait
    # docs/generations dans l'arbre principal ne s'y applique pas. Il faut donc
    # pouvoir REMONTER depuis ce worktree, sans quoi la preuve reste prisonniere de
    # l'endroit ou elle a ete produite : exactement le defaut que ce passeur corrige.
    ap.add_argument("--depuis", default=None, metavar="DIR",
                    help="repertoire source (defaut sandbox/generations_en_attente ; "
                         "pour un run --reference : <worktree>/docs/generations)")
    ap.add_argument("--vers", default=None, metavar="DIR",
                    help="repertoire cible (defaut docs/generations)")
    a = ap.parse_args(argv)
    depuis = Path(a.depuis) if a.depuis else DEPOT_DIR
    vers = Path(a.vers) if a.vers else CIBLE_DIR
    if not depuis.is_dir():
        # ABSENT se DIT : un repertoire source qu'on n'a pas trouve n'est pas un
        # repertoire vide, et surtout pas un succes.
        print("[generation] source ABSENTE (%s) : rien a inscrire" % _rel(depuis))
        return 0
    b = inscrire(depuis, vers)
    for nom, statut, sha in b["inscrites"]:
        print("[generation] INSCRITE %s (%s) sha=%s -> %s"
              % (nom, statut, sha, _rel(vers / nom)))
    if b["identiques"]:
        print("[generation] %d deja inscrite(s), identiques — depots residuels : %s"
              % (len(b["identiques"]), ", ".join(b["identiques"])))
    for nom in b["divergentes"]:
        print("[generation] ⚠ %s DIVERGE de la version inscrite — NON reecrite. "
              "Une generation est immuable : trancher a la main, ne pas deviner." % nom)
    for nom, etat in b["illisibles"] + b["non_relues"]:
        print("[generation] ⚠ %s : %s — rien d'inscrit pour celle-ci" % (nom, etat))
    if not any(b[k] for k in b):
        print("[generation] aucun depot en attente : rien a inscrire")
    # Un depot divergent ou illisible n'est PAS un succes silencieux.
    return 2 if (b["divergentes"] or b["illisibles"] or b["non_relues"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
