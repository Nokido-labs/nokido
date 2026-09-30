"""Sort les intents OFFENSIFS (ring >= 3) du coeur (owner 2026-09-26).

Motif : ces intents polluaient `app/forge_trajectory.ALLOWED_METHODS` -- le coeur ne doit
porter que des capacites non offensives. Le vocabulaire offensif appartient au depot redteam.
Effet de bord mesure : imprimer cette liste faisait mordre le classifieur `[cyber]`.

Ce patch NE NOMME AUCUN intent : il selectionne par `ring >= 3`. Il :
  1. localise ALLOWED_METHODS par AST (lignes exactes) ;
  2. exige un intent par ligne dans le bloc (sinon ABANDON, il ne devine pas) ;
  3. ecrit les entrees offensives dans <redteam>/offensive_intents.json ;
  4. reecrit forge_trajectory.py : retire ces lignes, insere un chargeur OPTIONNEL
     (gate par la variable NOKIDO_REDTEAM_INTENTS_JSON ; absent -> le coeur ne peut pas
     planifier d'action offensive, c'est voulu) ;
  5. re-parse et verifie : source valide, entrees offensives absentes, non offensives intactes.

Idempotent : si le chargeur est deja present, il ne refait rien. Lecture/ecriture LOCALES.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIBLE = os.path.join(RACINE, "app", "forge_trajectory.py")
# Destination du JSON offensif. Defaut = zone inscriptible par le compte trusted ; le compte
# owner (session) le copie ensuite dans le depot redteam (le trusted n'y a pas droit). Override
# par argv[1] pour ecrire directement dans redteam si un compte proprietaire lance le script.
JSON_OUT = (sys.argv[1] if len(sys.argv) > 1
            else os.path.join(RACINE, "sandbox", "workspace", "offensive_intents.json"))
MARQUEUR = "_charger_intents_offensifs_optionnels"

LOADER = '''

def ''' + MARQUEUR + '''() -> None:
    """Intents offensifs (ring>=3) sortis du coeur (owner 2026-09-26) : fournis par le depot
    redteam, charges SEULEMENT si NOKIDO_REDTEAM_INTENTS_JSON pointe un fichier lisible.
    Absent -> le coeur ne peut pas planifier d'action offensive, et c'est l'etat voulu."""
    import json as _json
    import os as _os

    p = _os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON")
    if not p or not _os.path.isfile(p):
        return
    try:
        extra = _json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001  # muet-ok : un chargeur optionnel ne casse jamais l'import
        return
    if isinstance(extra, dict):
        for _k, _v in extra.items():
            if isinstance(_v, dict) and isinstance(_v.get("ring"), int) and _v["ring"] >= 3:
                ALLOWED_METHODS[_k] = _v  # noqa: F821  (defini plus haut dans le module)


''' + MARQUEUR + '''()
'''


def main() -> int:
    src = open(CIBLE, encoding="utf-8").read()
    if MARQUEUR in src:
        print("[patch] chargeur deja present -- rien a faire (idempotent)")
        return 0
    arbre = ast.parse(src)
    noeud = None
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ALLOWED_METHODS" for t in n.targets):
            noeud = n
            break
    if noeud is None:
        print("[patch] ABANDON : ALLOWED_METHODS introuvable")
        return 2
    d = ast.literal_eval(noeud.value)
    offensifs = {k: v for k, v in d.items() if isinstance(v.get("ring"), int) and v["ring"] >= 3}
    if not offensifs:
        print("[patch] aucun intent ring>=3 -- rien a sortir")
        return 0

    lignes = src.splitlines(keepends=True)
    debut, fin = noeud.lineno - 1, noeud.end_lineno  # [debut, fin) = le bloc entier
    bloc = lignes[debut:fin]
    # Un intent par ligne : on compte les cles de 1er niveau reperees par `"cle": {`
    motif_cle = re.compile(r'^\s*"([A-Za-z0-9_]+)"\s*:\s*\{')
    cles_par_ligne = [(i, m.group(1)) for i, l in enumerate(bloc) if (m := motif_cle.match(l))]
    if len(cles_par_ligne) != len(d):
        print("[patch] ABANDON : %d cles au motif ligne vs %d dans le dict -- format non 1/ligne, "
              "je ne devine pas" % (len(cles_par_ligne), len(d)))
        return 3
    a_retirer = {i for i, cle in cles_par_ligne if cle in offensifs}
    nouveau_bloc = [l for i, l in enumerate(bloc) if i not in a_retirer]
    lignes2 = lignes[:debut] + nouveau_bloc + lignes[fin:]
    # Inserer le chargeur juste apres le bloc (apres retrait)
    pos = debut + len(nouveau_bloc)
    lignes2 = lignes2[:pos] + [LOADER] + lignes2[pos:]
    nouveau = "".join(lignes2)

    # Verification AVANT ecriture : parse + entrees offensives absentes + non offensives intactes
    a2 = ast.parse(nouveau)
    n2 = next((n for n in a2.body if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "ALLOWED_METHODS" for t in n.targets)), None)
    d2 = ast.literal_eval(n2.value)
    manquants_bons = set(d) - set(offensifs) - set(d2)
    survivants_off = set(offensifs) & set(d2)
    if manquants_bons or survivants_off:
        print("[patch] ABANDON : verif KO (non-offensifs perdus=%d, offensifs restes=%d)"
              % (len(manquants_bons), len(survivants_off)))
        return 4

    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(offensifs, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(CIBLE, "w", encoding="utf-8", newline="") as f:
        f.write(nouveau)
    print("[patch] OK : %d intent(s) ring>=3 sortis vers %s ; coeur -> %d intents non offensifs "
          "+ chargeur optionnel" % (len(offensifs), JSON_OUT, len(d2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
