"""NR : PORTEE du motif « adaptateur d'entree » sur le depot REEL.

Decision owner du 2026-09-12. Le cliquet clones a rompu sur six lignes de
`main()` strictement identiques entre `hook_context_firewall` et
`hook_tool_budget_gate` : try, parse de stdin, except return, delegation.
Deux gardes INDEPENDANTS, chacun devant survivre a la panne de l'autre.

DEUX ALTERNATIVES REJETEES, chacune mesuree avant d'etre ecartee :
  - un helper partage economisait six lignes en creant un failure domain
    COMMUN a deux garde-fous actifs ;
  - `--ecrire-socle` figeait les 385 groupes courants pour en resoudre UN.
  - monter MIN_NOEUDS de 25 a 26 etait tentant (le boilerplate pese
    EXACTEMENT 25) mais retirait QUATRE groupes de la surveillance, dont
    TROIS etrangers au probleme. Un seuil deplace pour un cas precis est une
    liste d'exceptions qui s'ignore.

OU VIVENT LES TESTS, et pourquoi cela compte. Les tests UNITAIRES du predicat
(cas admis, quatorze branches de rejet, plafond inclusif, temoin porteur de
logique) sont dans `tests/nr/test_dup_detector_nr.py`, parce que
`forge_mutation_ratchet.SURFACES` mappe `tools/forge_dup_detector.py` sur CE
fichier-la. Mesure du 2026-09-12 : places ici, ils etaient verts et ne tuaient
AUCUN mutant -- 8/14 tues, score inchange, quatre faiblesses persistantes. Un
test hors de la suite declaree ne garde rien, exactement comme un NR hors de
`PURE_TESTS`.

CE FICHIER garde ce qui n'a PAS sa place dans une suite de mutation : le scan
du depot reel (2201 fichiers, ~18 s). La suite de mutation est rejouee UNE FOIS
PAR MUTANT -- y mettre un test lent multiplierait le cout par quatorze.
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_dup_detector as d  # noqa: E402


def test_la_portee_reste_BORNEE_sur_le_depot_reel():
    """Garde anti-elargissement : mesure 2026-09-12 = 2 fonctions, exactement.

    Si quelqu'un relache le predicat, ce test mord AVANT que des clones reels
    ne disparaissent silencieusement de la surveillance. La borne est laxe (4)
    pour tolerer un ajout legitime, mais elle existe : sans plafond de taille,
    la premiere version captait aussi `forge_suite_pure_triage._compte_tests`
    (58 noeuds), qui n'est pas du boilerplate.
    """
    admises = []
    illisibles = []
    for f in d.collect(["app", "tools"]):
        try:
            src = open(f, encoding="utf-8", errors="replace").read()
            arbre = ast.parse(src, filename=f)
        except (OSError, SyntaxError) as e:
            illisibles.append((d._rel(f), type(e).__name__))
            continue
        if d._est_genere(src):
            continue
        for n in ast.walk(arbre):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _, taille = d.empreinte(n)
                if d.est_adaptateur_entree(n, taille):
                    admises.append("%s::%s" % (d._rel(f), n.name))

    assert len(admises) <= 4, (
        "le predicat s'est elargi : %d fonctions admises (%s). Mesure de "
        "reference : 2." % (len(admises), ", ".join(sorted(admises)[:8])))
    assert admises, (
        "aucune fonction admise : le predicat ne mesure plus rien, et un vert "
        "ne prouverait alors que le silence de l'instrument")
    assert not illisibles, (
        "fichiers non lus : %r -- la portee ne peut pas etre affirmee sur un "
        "corpus partiellement scanne" % illisibles[:5])
