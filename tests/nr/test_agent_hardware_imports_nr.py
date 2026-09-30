"""NR — forge_agent_hardware utilise des symboles qu'il n'importe pas.

DEFAUT MESURE le 2026-09-08. Le module a ete DECOUPE : ses classes ont migre vers
`forge_agents`, et le fichier porte encore les commentaires qui l'attestent
(« Distrib importe depuis forge_agents », lignes 52-68). Mais l'`import`
correspondant n'a JAMAIS ete ecrit : le seul import du fichier etait
`app.core.settings`. `AgentRole`, `Distrib`, `OSFamily`, `CPUArch`, `BenchResult`
et `logger` etaient donc des noms libres, et le module levait `NameError` des sa
premiere ligne executable (ROLE_ARCH_BONUS, ligne 99).

POURQUOI CA N'A PAS ETE VU. Le defaut est INVISIBLE en relecture : les commentaires
DISENT que les symboles viennent de forge_agents, ce qui se lit comme un import.
Seule l'execution le revele. Meme classe que la racine figee de `pyexec_server.ts`
(2026-09-08) et que la migration d'import « invisible jusqu'au redemarrage »
(2026-09-05) : un etat que le code AFFIRME et que personne ne MESURE.

CE QUE VERROUILLE CE NR — deux niveaux, volontairement :
  1. le chemin REEL : le module s'importe (c'est ce qui cassait) ;
  2. le contrat STATIQUE : aucun nom charge n'est libre. C'est lui qui empeche la
     regression de revenir en silence, parce qu'il ne depend pas de la ligne qui
     a casse aujourd'hui.

Le cycle forge_agents <-> forge_agent_hardware est DIFFERE (forge_agents fait son
`from forge_agent_hardware import _run_bench` DANS une fonction) : l'import
top-level est donc sur dans les deux sens, et le test 1 le prouve.
"""

from __future__ import annotations

import ast
import builtins
import importlib
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
MODULE = RACINE / "app" / "forge_agent_hardware.py"


def _noms_libres(source: str) -> set[str]:
    """Noms charges que rien ne definit dans le module ni n'importe.

    Traite les liaisons que l'AST cache : `except ... as e`, les arguments,
    les comprehensions, les `global`/`nonlocal`. Sans elles, un NR de ce type
    crie a faux -- et un garde qui crie a faux se fait desarmer.
    """
    arbre = ast.parse(source)
    lies: set[str] = set(dir(builtins))
    # Variables de module implicites : Python les fournit, aucun import ne les
    # declare. Mesure du 2026-09-08 : sans cette ligne, le meme contrat passe sur
    # app/ et tools/ accusait `__file__` dans 1407 fichiers sur 1416 -- un capteur
    # qui crie a faux se fait desarmer, donc il se corrige avant de servir.
    lies |= {
        "__file__", "__name__", "__doc__", "__package__",
        "__spec__", "__loader__", "__builtins__", "__debug__", "__path__",
    }

    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lies.add(noeud.name)
        elif isinstance(noeud, ast.Name) and isinstance(noeud.ctx, ast.Store):
            lies.add(noeud.id)
        elif isinstance(noeud, ast.Import):
            for alias in noeud.names:
                lies.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(noeud, ast.ImportFrom):
            for alias in noeud.names:
                lies.add(alias.asname or alias.name)
        elif isinstance(noeud, ast.arg):
            lies.add(noeud.arg)
        elif isinstance(noeud, ast.ExceptHandler) and noeud.name:
            lies.add(noeud.name)
        elif isinstance(noeud, (ast.Global, ast.Nonlocal)):
            lies.update(noeud.names)

    charges = {
        n.id for n in ast.walk(arbre)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return charges - lies


def test_le_module_existe_toujours():
    """Si le fichier disparait, le NR doit le DIRE, pas passer au vert."""
    assert MODULE.is_file(), f"module absent : {MODULE}"


def test_aucun_nom_libre_dans_le_module():
    """Le contrat qui empeche la regression de revenir en silence."""
    libres = _noms_libres(MODULE.read_text(encoding="utf-8", errors="replace"))
    assert not libres, (
        "noms utilises sans etre definis ni importes : "
        + ", ".join(sorted(libres))
        + " -- un commentaire disant « importe depuis X » n'est pas un import"
    )


def test_le_module_s_importe_vraiment():
    """Chemin REEL. C'est lui qui levait NameError.

    Une dependance tierce absente n'est pas le defaut vise : on le DIT et on
    saute, plutot que de rendre un rouge qui accuse le mauvais coupable.
    """
    try:
        module = importlib.import_module("app.forge_agent_hardware")
    except ModuleNotFoundError as exc:
        manquant = (exc.name or "").split(".")[0]
        if manquant in {"app", "forge_agent_hardware", "forge_agents"}:
            raise
        pytest.skip(f"dependance tierce absente de l'environnement : {manquant}")
    else:
        assert module is not None


def test_aucun_decorateur_de_classe_sur_une_fonction():
    """SECOND defaut du meme decoupage, trouve par le NR precedent.

    L'outil avait retire `class BenchResult:` et LAISSE son `@dataclass`, qui
    s'appliquait alors a la fonction suivante (`_run_bench`). Le module mourait
    en « 'function' object has no attribute '__mro__' » -- un message qui ne
    nomme ni le decorateur ni la classe disparue.

    Le contrat est plus large que le cas repare : tout decorateur reserve aux
    classes, pose sur une fonction, est un residu de decoupage.
    """
    reserves_aux_classes = {"dataclass", "final", "runtime_checkable"}
    arbre = ast.parse(MODULE.read_text(encoding="utf-8", errors="replace"))
    fautifs = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in noeud.decorator_list:
            cible = deco.func if isinstance(deco, ast.Call) else deco
            nom = getattr(cible, "id", None) or getattr(cible, "attr", None)
            if nom in reserves_aux_classes:
                fautifs.append(f"@{nom} sur {noeud.name} (ligne {noeud.lineno})")
    assert not fautifs, "decorateur de classe pose sur une fonction : " + " ; ".join(fautifs)


def test_les_symboles_migres_sont_resolus():
    """Les six noms que la migration a laisses derriere elle."""
    module = pytest.importorskip("app.forge_agent_hardware")
    source = MODULE.read_text(encoding="utf-8", errors="replace")
    for nom in ("AgentRole", "Distrib", "OSFamily", "CPUArch", "BenchResult", "logger"):
        if nom in source:
            assert hasattr(module, nom), f"{nom} cite par le module mais non resolu"
