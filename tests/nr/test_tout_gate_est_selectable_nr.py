"""NR 2026-09-09 — TOUT producteur de resultat de gate passe par la selection.

LA REGLE, ET POURQUOI ELLE VIT ICI ET PAS DANS LE CODE. Aucune syntaxe Python
n'oblige un `results.append(...)` a consulter `--only` : on peut toujours en ajouter
un qui s'execute quoi qu'il arrive. La regle ne peut donc pas etre portee par le
code -- elle est portee par un CLIQUET, comme le socle de secrets, le socle de
clones ou le ratchet de couverture NR.

CE QUI L'A RENDUE NECESSAIRE, le meme jour. J'ai branche le selecteur sur `_run` en
le decrivant comme « le point de passage unique des 21 gates ». La mesure AST dit
autre chose : sur 30 producteurs de resultat, 20 passent par `_run` et 10 non. Le NR
comportemental etait vert (7/7, le predicat est correct) pendant que le correctif
restait INOPERANT -- `ci_local.py --only "ruff critique"` depassait 120 s parce que
`pytest (suite pure)` (542 s) continuait de tourner. Un vert au contrat coexistait
avec un cablage faux.

C'est le motif recidivant du depot : « une fonction existe, son nom est correct, mais
le chemin reel qui devait l'invoquer n'est pas celui qu'on croyait ». Je l'ai
reproduit dans la phrase meme ou je le citais.

CE QUE CE CLIQUET INTERDIT : ajouter un gate qui produit un resultat sans etre
selectable. Il ne verifie pas que `--only` fonctionne -- c'est le role du NR
comportemental (test_selecteur_only_nr) -- il verifie que PERSONNE n'y echappe.
Corriger les quatre blocs connus sans ce cliquet ferait satisfaire le NR du jour,
puis decouvrir un cinquieme chemin hors modele au prochain gate ajoute.

DEUX FORMES DE COUVERTURE SONT ACCEPTEES, et une seule suffit :
  1. passer par `_run(...)`, ou le selecteur est consulte en tete ;
  2. vivre sous un `if` dont le test mentionne la decision de selection.
Tout le reste est NU, et un producteur nu est nomme avec sa ligne : une borne doit
dire COMBIEN et OU, pas seulement TROP.

Zero service externe : lecture AST du depot, aucun gate execute.
"""

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "ci_local.py"

# `_NON_DEMANDE` compte : tester la sentinelle rendue par `_run` EST une consultation
# de la selection, en aval plutot qu'en amont. Elle est acceptee la ou le travail a
# deja ete evite par `_run` -- jamais comme moyen de laisser tourner un gate lourd.
# `_ui_doit_tourner` / `_lancer_ui` : le garde du gate ui-acceptance a change de FORME
# le 2026-09-09, pas de force. Il etait un `elif` de l'auto-detection — donc une branche
# MORTE que ce cliquet acceptait pourtant, parce que le `if` englobant citait
# `_ui_demande`. Autrement dit le cliquet validait un garde qui ne gardait rien.
# La decision est desormais une fonction PURE qui prend `only` en parametre et applique
# l'exclusivite en PREMIER, prouvee par 5 NR dans `test_selecteur_only_nr.py`.
# On reconnait cette forme ici ; on ne desserre pas l'exigence : un producteur reste
# couvert soit par `_run`, soit par un `if` qui consulte reellement la selection.
MARQUEURS_SELECTION = ("_demande", "_ONLY", "_ui_demande", "_NON_DEMANDE",
                       "_ui_doit_tourner", "_lancer_ui")


def _arbre_avec_parents() -> ast.AST:
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(arbre):
        for enfant in ast.iter_child_nodes(n):
            enfant.parent = n
    return arbre


def _garde_en_amont(noeud) -> str | None:
    """Rend le test du `if` englobant qui consulte la selection, ou None."""
    p = getattr(noeud, "parent", None)
    while p is not None:
        if isinstance(p, ast.If):
            t = ast.unparse(p.test)
            if any(m in t for m in MARQUEURS_SELECTION):
                return t
        p = getattr(p, "parent", None)
    return None


def _producteurs() -> list:
    """Tous les `results.append(...)` du fichier, avec leur mode de couverture."""
    out = []
    for n in ast.walk(_arbre_avec_parents()):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "append" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "results" and n.args):
            continue
        a0 = n.args[0]
        via_run = (isinstance(a0, ast.Call) and isinstance(a0.func, ast.Name)
                   and a0.func.id == "_run")
        out.append({"ligne": n.lineno, "via_run": via_run,
                    "garde": _garde_en_amont(n), "expr": ast.unparse(a0)[:70]})
    return out


def test_il_y_a_bien_des_producteurs_a_surveiller():
    """Contre-epreuve : sur une liste vide, tous les tests suivants passeraient."""
    prod = _producteurs()
    assert len(prod) >= 20, (
        "seulement %d producteurs trouves : l'analyse ne reconnait plus le motif "
        "`results.append(...)`, ce cliquet ne garde donc plus rien" % len(prod))


def test_le_selecteur_est_consulte_dans_le_lanceur_commun():
    """Sans cette garde, les 20 gates qui passent par `_run` seraient tous nus."""
    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    i = src.find("def _run(")
    assert i > 0, "lanceur `_run` introuvable : ce cliquet ne mesure plus rien"
    corps = src[i:i + 2000]
    assert "_demande(name)" in corps, (
        "`_run` ne consulte plus la selection : les gates qui passent par lui "
        "s'executeraient malgre `--only`")


def test_aucun_producteur_de_resultat_n_echappe_a_la_selection():
    """LE cliquet. Chaque producteur nu est NOMME avec sa ligne."""
    nus = [p for p in _producteurs() if not p["via_run"] and not p["garde"]]
    if nus:
        detail = "\n".join("    L%-6d %s" % (p["ligne"], p["expr"]) for p in nus)
        raise AssertionError(
            "%d producteur(s) de resultat echappent au selecteur `--only` :\n%s\n"
            "  Chacun s'executera malgre `--only`, ce qui vide le drapeau de son "
            "objet : c'est ainsi que `--only \"ruff critique\"` a depasse 120 s le "
            "2026-09-09, `pytest (suite pure)` (542 s) tournant toujours.\n"
            "  Deux facons de couvrir un producteur : le faire passer par `_run`, ou "
            "le placer sous un `if` qui consulte %s."
            % (len(nus), detail, " / ".join(MARQUEURS_SELECTION)))
