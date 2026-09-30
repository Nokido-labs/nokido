# -*- coding: utf-8 -*-
"""Inscrit le registre de vitalite DEPOSE dans l'arbre versionne.

__FORGE_COLOR__ = "qualite/build : inscription gouvernee du cliquet de vitalite"

POURQUOI (2026-09-07). `tests/nr/` n'est pas inscriptible par les comptes sandbox,
sous lesquels tourne `run_job` — donc la CI ne pouvait PAS faire avancer son propre
cliquet de vitalite. Un cliquet qui n'avance jamais n'est pas un cliquet : gele, il
finit par declarer tous les gardes anergiques d'un coup, a 14 jours, et a tort.

La CI depose donc sa mesure dans `sandbox/vitalite_en_attente/` (toujours
inscriptible) et l'inscription devient un geste GOUVERNE — meme patron que la capture
de generation. `LaForgeTrusted` ecrit `tests/nr` :

    run action=trusted_script path=tools/forge_vitalite_inscrire.py

🔑 On MERGE par date, on n'ecrase pas : un run partiel (`--fast`) ne mesure qu'une
fraction des gardes, et une copie brute effacerait la fraicheur des autres.
On conclut par RELECTURE de la cible, jamais sur l'absence d'erreur.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
#
# ELLE DOIT PRECEDER L'IMPORT DU NAMESPACE. Meme inversion que
# `forge_memory_compactor` (codemod a44b64df6), MESUREE ICI le 2026-09-11 en
# lancant le geste que la CI reclame elle-meme en fin de run :
# `run action=trusted_script path=tools/forge_vitalite_inscrire.py` mourait en
# ModuleNotFoundError, donc le registre de vitalite ne pouvait plus etre inscrit
# -- les comptes sandbox n'ecrivent pas dans tests/nr/, ce script est le SEUL
# chemin. NR : tests/nr/test_point_entree_par_chemin_nr.py
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Lecteur a trois etats PARTAGE (2026-09-09) : il vivait ici et a ete recopie dans
# forge_generation_inscrire, ce que le cliquet de clones a refuse. Factorise plutot
# que de regeler son socle.
from nokido_agent.tools.forge_lecture_json import lire as _lire  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "tests" / "nr" / "vitalite_gardes.json"
DEPOT = ROOT / "sandbox" / "vitalite_en_attente" / "vitalite_gardes.json"


def _rel(p: Path) -> str:
    """Chemin DIT relatif au depot s'il y vit, absolu sinon -- ne leve JAMAIS.

    Mesure 2026-09-07 (run GitHub 34138167173) : `CIBLE.relative_to(ROOT)` levait
    ValueError sur le runner (tmp_path de pytest hors du depot) apres une
    inscription REUSSIE -- le verdict rc=0 se perdait sur l'affichage du chemin.
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _fraicheur(v) -> tuple:
    """Cle de comparaison d'un garde. Un verdict REEL prime sur un UNKNOWN.

    Rend un tuple ordonnable meme sur une entree partielle ou inattendue : une
    valeur qu'on ne sait pas lire vaut la plus ANCIENNE possible, pour qu'elle ne
    remplace jamais une entree qu'on sait dater.
    """
    if not isinstance(v, dict):
        return ("", "")
    return (str(v.get("dernier_reel") or ""), str(v.get("dernier_unknown") or ""))


# `_lire` vivait ICI et a ete recopie dans forge_generation_inscrire le 2026-09-09 :
# 52 noeuds identiques, cliquet de clones rompu, CI GitHub rouge (run 34342552425).
# La fonction est desormais importee de forge_lecture_json (voir en tete de fichier).


def main() -> int:
    depot, e_depot = _lire(DEPOT)
    if e_depot != "LU":
        print("[vitalite] depot %s : rien a inscrire" % e_depot)
        return 0 if e_depot == "ABSENT" else 2

    cible, e_cible = _lire(CIBLE)
    if e_cible.startswith("ILLISIBLE"):
        # On n'ecrase pas un fichier qu'on n'a pas su lire : on ne sait pas ce
        # qu'il contient, donc on ne sait pas ce qu'on detruirait.
        print("[vitalite] cible %s — inscription REFUSEE (on n'ecrase pas "
              "l'illisible)" % e_cible)
        return 2

    a, b = cible.get("gardes", {}), depot.get("gardes", {})
    fusion = dict(a)
    remplaces = 0
    for cle, v in b.items():
        # ⚠️ La valeur d'un garde est un DICT, pas une date :
        #   {"dernier_reel": "2026-08-30", "dernier_unknown": "2026-08-20",
        #    "etat": "PASS", "unknown_consecutifs": 0}
        # Comparer `str(dict)` marchait par ACCIDENT (`sort_keys` met `dernier_reel`
        # en tete du repr) et se retournait des qu'un garde n'avait QUE
        # `dernier_unknown` : 'dernier_r' < 'dernier_u', donc l'entree SANS verdict
        # reel aurait gagne contre celle qui en a un. On compare la FRAICHEUR, pas
        # une representation.
        if cle not in fusion or _fraicheur(v) > _fraicheur(fusion[cle]):
            fusion[cle] = v
            remplaces += 1

    # L'ENVELOPPE se fusionne aussi, sinon un depot `PARTIAL` DEGRADE une cible
    # `FULL` : le fichier resterait aussi complet qu'avant, mais se declarerait
    # partiel — et l'anergie cesserait de bloquer sur un registre pourtant sur.
    # `perimetre` decrit la couverture du FICHIER, pas du dernier run.
    _RANG = {"FULL": 2, "PARTIAL": 1, "UNKNOWN": 0}
    sortie = dict(depot)
    sortie["gardes"] = fusion
    sortie["observe_le"] = max(str(depot.get("observe_le") or ""),
                               str(cible.get("observe_le") or "")) or None
    if sortie["observe_le"] is None:
        sortie.pop("observe_le")
    _pd, _pc = depot.get("perimetre", "UNKNOWN"), cible.get("perimetre", "UNKNOWN")
    sortie["perimetre"] = _pd if _RANG.get(_pd, 0) >= _RANG.get(_pc, 0) else _pc
    try:
        CIBLE.parent.mkdir(parents=True, exist_ok=True)
        CIBLE.write_text(json.dumps(sortie, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n", encoding="utf-8")
    except OSError as e:
        print("[vitalite] ECHEC d'ecriture (%s) : ce compte n'ecrit pas tests/nr — "
              "lancer en `trusted_script`" % type(e).__name__)
        return 2

    relu, e_relu = _lire(CIBLE)
    if e_relu != "LU" or relu.get("gardes") != fusion:
        print("[vitalite] RELECTURE INCOHERENTE (%s) — inscription NON confirmee"
              % e_relu)
        return 2
    print("[vitalite] inscrit : %d garde(s), dont %d rafraichi(s) depuis le depot"
          % (len(fusion), remplaces))
    print("           cible : %s" % _rel(CIBLE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
