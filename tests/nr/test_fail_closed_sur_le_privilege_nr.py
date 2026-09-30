"""NR — un jeton de hub absent n'accorde plus l'administration.

Revue defensive LOCAL-IPC du 2026-09-18, point 6. `_resolve_ring` ouvrait par :

    if not HUB_TOKEN: return (0, "local") if local else (-1, "no_token")

soit `ring 0` (SYSTEM) pour toute requete LOCALE des lors que le jeton du hub
etait vide, sans que rien ne soit presente.

LA DISTINCTION QUI COMPTE : le mode « pas de jeton configure » est documente et
assume. ACCEPTER un appel sans preuve est un choix defendable ; lui accorder
l'ADMINISTRATION n'en est pas un. La route reste ouverte, le privilege non.

CE N'EST PAS THEORIQUE. Un jeton vide n'arrive pas qu'en installation neuve : un
coffre illisible depuis le compte qui lance le hub rend la MEME valeur vide.
C'est `RESOURCE_UNAVAILABLE` traite comme `DISABLED_BY_POLICY` — la confusion que
la constitution semantique interdit nommement. Le corps atteint le loopback
depuis plusieurs comptes, dont le bac a sable : une panne de lecture devenait une
elevation de privilege.

ETAT MESURE LE JOUR DU CORRECTIF : le jeton est PRESENT au coffre, donc cette
branche n'est pas empruntee et le changement n'a aucun effet en fonctionnement
normal. Il ne mord que dans le cas degrade. Un correctif dont on ne peut pas dire
s'il change quelque chose aujourd'hui se relit mal plus tard — c'est dit ici.

Le durcissement existait DEJA vingt lignes plus bas, sur le repli legacy (« une
identite hors registre retombe sur 3, JAMAIS 0 ») : il n'avait pas ete applique a
cette branche-ci. Deux chemins pour une meme decision, un seul durci.

LIMITE, nommee : importer `nokido_hub` demarre des sondes de boot, on ne l'importe
donc pas. Ce test lit l'AST du module — ce qui suffit pour la propriete visee,
« aucun chemin de cette fonction n'accorde le ring 0 sans preuve », qui est une
propriete STRUCTURELLE.
"""

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "nokido_hub.py"

# Ring le plus privilegie. Aucun chemin sans preuve ne doit l'atteindre.
_ADMINISTRATION = 0
# Plancher applique par le repli legacy, repris ici pour ne pas inventer un
# second vocabulaire de niveaux.
_ISOLE = 3


@pytest.fixture(scope="module")
def arbre():
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _fonction(arbre, nom):
    return next(
        (n for n in ast.walk(arbre)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom),
        None,
    )


def test_la_resolution_de_ring_n_accorde_jamais_l_administration_en_dur(arbre):
    """LA MORSURE — la forme exacte du defaut du 2026-09-18."""
    fn = _fonction(arbre, "_resolve_ring")
    assert fn is not None, "la resolution d'identite a disparu ou a ete renommee"
    fautifs = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) and n.value.elts:
            premier = n.value.elts[0]
            if isinstance(premier, ast.Constant) and premier.value == _ADMINISTRATION:
                fautifs.append(ast.unparse(n))
    assert not fautifs, (
        "un chemin de `_resolve_ring` rend le ring d'ADMINISTRATION en dur : "
        f"{fautifs}. C'est le fail-open du 2026-09-18 — un jeton vide, et toute "
        "requete locale devient SYSTEM."
    )


def test_le_plancher_existe_et_reste_non_privilegie(arbre):
    fn = _fonction(arbre, "_ring_local_sans_preuve")
    assert fn is not None, (
        "la fonction de plancher a disparu : la decision est retournee en ligne, "
        "donc elle n'est plus nommee ni testable"
    )
    rendus = [
        n.value.elts[0].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)
        and n.value.elts and isinstance(n.value.elts[0], ast.Constant)
    ]
    assert rendus, "le plancher ne rend aucun ring explicite"
    assert all(r >= _ISOLE for r in rendus), (
        f"le plancher accorde un ring privilegie : {rendus} (attendu >= {_ISOLE})"
    )


def test_le_plancher_se_signale_au_journal(arbre):
    """Un appel accepte sans preuve doit LAISSER UNE TRACE, sinon on ne peut pas
    distinguer un mode de developpement voulu d'une lecture de coffre qui a
    echoue — deux causes, un seul symptome."""
    fn = _fonction(arbre, "_ring_local_sans_preuve")
    appels = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert appels & {"warning", "error", "critical"}, (
        "le plancher ne journalise rien : un appel accepte sans preuve passerait "
        "inapercu"
    )


def test_le_repli_legacy_garde_son_propre_plancher(arbre):
    """NON-REGRESSION — le durcissement voisin, celui qui existait deja, ne doit
    pas disparaitre pendant qu'on s'occupe de son jumeau."""
    fn = _fonction(arbre, "_resolve_ring")
    src = ast.unparse(fn)
    assert "_agent_ring(" in src, (
        "le repli legacy n'appelle plus `_agent_ring` : son plancher fail-closed "
        "a saute"
    )
