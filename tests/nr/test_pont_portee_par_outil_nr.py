# -*- coding: utf-8 -*-
"""NR — FIL DE DETENTE : une seconde portee sur le pont exige une table outil->portee.

ETAT MESURE le 2026-09-18, et il est SAIN :

    AUDIENCE = "nokido-github-bridge"
    SCOPE    = "github:read"          <- UNE seule portee
    L255     if charge.get("scope") not in portees:

La portee est verifiee UNE FOIS, a la porte -- pas par outil. Aujourd'hui c'est
suffisant, parce qu'il n'existe qu'une portee et que le pont ENTIER est
`github:read` : la porte et la capacite coincident.

CE QUI CASSE CETTE COINCIDENCE. Le jour ou une seconde portee s'ajoute
(`runtime.read` pour l'organe sensoriel, par exemple), un jeton portant l'UNE ou
l'AUTRE franchit la MEME porte, et plus rien en aval ne distingue les outils
qu'il peut atteindre. Une habilitation d'observation atteindrait alors les outils
d'ecriture -- non par une faille, mais parce que la frontiere n'existe qu'a
l'entree.

C'est l'invariant `CAPABILITY_DECLARED != CAPABILITY_REACHABLE`, et c'est le
motif du finding #9 du meme jour : un garde present dont la branche n'a aucun
appelant. On ne le decouvrira pas a la relecture -- le code aura l'air correct.

CE NR N'INTERDIT PAS la seconde portee. Il exige qu'elle vienne AVEC sa table
outil->portee, appliquee au dispatch. Il passe au ROUGE a l'instant ou l'une
arrive sans l'autre : c'est un fil de detente, pas un veto.

Il verrouille aussi la discipline que la passerelle s'impose deja par ecrit :
UNE SEULE implementation de l'autorisation. Deux verificateurs, et c'est le plus
permissif qui fait loi.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/pont : la portee doit borner les outils atteignables"

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

PONT = RACINE / "tools" / "forge_github_bridge.py"
ARBRE = ast.parse(PONT.read_text(encoding="utf-8"))

# Un nom de table acceptable : ce NR ne dicte pas l'implementation, il exige
# qu'une correspondance outil->portee EXISTE et soit lue.
NOMS_DE_TABLE = ("PORTEE_PAR_OUTIL", "PORTEES_PAR_OUTIL", "SCOPE_PAR_OUTIL",
                 "OUTIL_PORTEE", "SCOPE_BY_TOOL")


def _portees_declarees(arbre) -> dict:
    """Constantes de module qui ressemblent a une portee OAuth.

    Une portee se reconnait a sa FORME (`domaine:action`), pas a son nom : un
    jour quelqu'un l'appellera `PORTEE_OBSERVATION` et un test qui cherche
    `SCOPE` ne verrait rien.
    """
    out = {}
    for n in arbre.body:
        if not isinstance(n, ast.Assign):
            continue
        for cible in n.targets:
            if not isinstance(cible, ast.Name) or not cible.id.isupper():
                continue
            v = n.value
            if isinstance(v, ast.Constant) and isinstance(v.value, str) and ":" in v.value:
                if any(m in cible.id for m in ("SCOPE", "PORTEE")):
                    out[cible.id] = v.value
            elif isinstance(v, (ast.Tuple, ast.List, ast.Set)):
                vals = [e.value for e in v.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        and ":" in e.value]
                if vals and any(m in cible.id for m in ("SCOPE", "PORTEE")):
                    out[cible.id] = vals
    return out


def _table_presente(arbre) -> bool:
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name) and any(m in n.id for m in NOMS_DE_TABLE):
            return True
    return False


def test_l_etat_courant_est_bien_celui_qu_on_croit():
    """Ancre la mesure. Si l'etat change, ce NR doit etre RELU, pas contourne."""
    p = _portees_declarees(ARBRE)
    assert p, "aucune portee declaree : la passerelle a change de forme, relire ce NR"
    plates = []
    for v in p.values():
        plates.extend(v if isinstance(v, list) else [v])
    assert plates, "portees illisibles"


def test_une_seconde_portee_exige_sa_table_outil_vers_portee():
    """LE FIL DE DETENTE.

    Tant qu'il n'y a qu'une portee, la verification a la porte suffit. Des qu'il
    y en a deux, elle ne suffit plus : il faut dire QUEL outil chaque portee
    autorise.
    """
    p = _portees_declarees(ARBRE)
    plates = []
    for v in p.values():
        plates.extend(v if isinstance(v, list) else [v])
    distinctes = sorted(set(plates))
    if len(distinctes) <= 1:
        return  # etat sain : porte == capacite
    assert _table_presente(ARBRE), (
        "La passerelle declare %d portees (%s) mais AUCUNE table outil->portee.\n"
        "La verification a la porte (`scope not in portees`) laisse alors un jeton "
        "d'une portee atteindre les outils de l'autre : la frontiere n'existe qu'a "
        "l'entree.\n"
        "-> declarer une table (%s) et la LIRE au dispatch, avec un refus nomme."
        % (len(distinctes), ", ".join(distinctes), " | ".join(NOMS_DE_TABLE))
    )


def test_morsure_un_pont_a_deux_portees_sans_table_est_DETECTE(tmp_path):
    """CONTROLE NEGATIF — sans lui, une detection cassee rendrait toujours vert.

    On fabrique exactement la situation dangereuse et on verifie que la logique
    ci-dessus la VOIT.
    """
    faux = tmp_path / "pont.py"
    faux.write_text(
        'AUDIENCE = "x"\n'
        'SCOPE = "github:read"\n'
        'SCOPE_RUNTIME = "runtime:read"\n'
        'def verifier(c, portees=(SCOPE, SCOPE_RUNTIME)):\n'
        '    return c.get("scope") in portees\n',
        encoding="utf-8",
    )
    a = ast.parse(faux.read_text(encoding="utf-8"))
    p = _portees_declarees(a)
    plates = []
    for v in p.values():
        plates.extend(v if isinstance(v, list) else [v])
    assert len(set(plates)) == 2, f"les deux portees doivent etre vues : {p}"
    assert not _table_presente(a), "aucune table ne doit etre trouvee dans ce faux pont"


def test_morsure_un_pont_a_deux_portees_AVEC_table_passe(tmp_path):
    """CONTROLE NEGATIF SYMETRIQUE — le fil ne doit pas interdire la seconde
    portee, seulement l'exiger accompagnee."""
    faux = tmp_path / "pont_ok.py"
    faux.write_text(
        'SCOPE = "github:read"\n'
        'SCOPE_RUNTIME = "runtime:read"\n'
        'PORTEE_PAR_OUTIL = {"repo_info": SCOPE, "db_state": SCOPE_RUNTIME}\n'
        'def dispatch(outil, portee):\n'
        '    return PORTEE_PAR_OUTIL.get(outil) == portee\n',
        encoding="utf-8",
    )
    a = ast.parse(faux.read_text(encoding="utf-8"))
    assert _table_presente(a), "une table presente doit etre reconnue"


def test_une_seule_implementation_de_l_autorisation():
    """La passerelle se l'impose PAR ECRIT ; on le rend executable.

    « La recopier ailleurs fabriquerait une seconde implementation de
    l'autorisation, et c'est la plus permissive des deux qui finit toujours par
    faire loi. » -- docstring de la passerelle.
    """
    src = PONT.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    comparaisons = [
        n.lineno for n in ast.walk(arbre)
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Call)
        and isinstance(n.left.func, ast.Attribute)
        and n.left.func.attr == "get"
        and any(isinstance(a, ast.Constant) and a.value == "scope" for a in n.left.args)
    ]
    assert len(comparaisons) <= 1, (
        "la portee est comparee a %d endroits (lignes %s) : deux implementations "
        "de l'autorisation, et la plus permissive fera loi" % (len(comparaisons), comparaisons)
    )
