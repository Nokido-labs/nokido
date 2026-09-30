"""NR — aucun module de app/ ou tools/ ne doit etre non-parsable.

DEFAUT MESURE le 2026-09-08. `app/forge_mcp_registry.py` -- le registre d'outils
du hub, CRITICAL_FILE de 8699 lignes -- ne parsait plus dans l'arbre de travail :
`IndentationError: unexpected indent` ligne 422. Un patcheur automatique avait
substitue textuellement « import sqlite3 » par
« from forge_spike_router import evaluate_intent » sur 20 sites, pour injecter une
couche SpikeRouter dans dispatch(). Les lignes visees etaient des imports GROUPES,
donc la substitution a (a) emporte des modules STDLIB dans un `from` Nokido
(`from forge_spike_router import evaluate_intent, hashlib, json as _json`),
(b) perdu l'indentation -- colonne 0 au milieu d'un corps de methode -- et
(c) perdu des ALIAS : `import sqlite3 as _sq` etait reinsere en `import sqlite3`,
si bien que `_sq` designait evaluate_intent la ou le code appelle `_sq.connect()`.

CE QUE CA COUTAIT. Le hub tournait encore sur son code EN MEMOIRE : le fichier
casse etait invisible tant que personne ne redemarrait. Au premier restart, le hub
ne serait pas reparti -- et la cause aurait ete cherchee dans le restart, pas dans
une modification non commitee vieille de plusieurs heures. C'est la meme famille
que « code commite n'est pas code charge », prise dans l'autre sens : ici c'est le
code SUR DISQUE qui etait mort pendant que le processus vivait.

POURQUOI CE NR EXISTE. Le defaut a ete trouve par accident, en passant un contrat
sans rapport sur app/ et tools/. Un fichier qui ne parse pas est detectable en une
seconde et pour tout le depot : il n'y a aucune raison que ca depende de la chance.

TROIS ETATS, JAMAIS DEUX (constitution semantique) : un fichier est VALIDE,
INVALIDE, ou ILLISIBLE. Un fichier qu'on n'a pas pu lire n'est pas un fichier sain,
et il est NOMME plutot que compte comme vert.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.60)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
DOSSIERS = ("app", "tools")

# Zones d'archive : du code fige, conserve pour l'histoire et jamais importe.
# On ne le corrige pas, donc on ne le mesure pas -- mais on le DIT ici plutot que
# de le laisser disparaitre en silence dans un filtre.
EXCLUS = {"_attic", "backups", "legacy", "__pycache__", "node_modules", ".venv"}


@lru_cache(maxsize=1)
def _sources():
    """Rend ((rel, source), ...) pour tout app/ et tools/, lu UNE fois.

    Les trois contrats de ce fichier parcouraient chacun ~2400 fichiers : la
    suite passait la minute et le canal d'appel du hub la coupait a 70 s pour une
    mesure strictement identique trois fois. Un garde trop lent finit desarme
    aussi surement qu'un garde qui crie a faux.
    """
    out = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if EXCLUS & set(chemin.relative_to(RACINE).parts):
                continue
            rel = chemin.relative_to(RACINE).as_posix()
            try:
                out.append((rel, chemin.read_text(encoding="utf-8", errors="strict")))
            except (OSError, UnicodeDecodeError) as exc:
                out.append((rel, exc))
    return tuple(out)


@lru_cache(maxsize=1)
def _modules():
    """Rend (valides, invalides, illisibles) sur app/ et tools/.

    MIS EN CACHE : le scan lit et parse ~2400 fichiers (~14 s). Sans cache,
    chaque test du fichier le refaisait, et la suite depassait la minute pour
    une mesure strictement identique. Un garde qui coute cher se fait desarmer
    aussi surement qu'un garde qui crie a faux.
    """
    valides, invalides, illisibles = [], [], []
    for dossier in DOSSIERS:
        if not (RACINE / dossier).is_dir():
            illisibles.append((dossier, "dossier absent"))
    for rel, source in _sources():
        if isinstance(source, Exception):
            illisibles.append((rel, type(source).__name__))
            continue
        try:
            ast.parse(source)
        except SyntaxError as exc:
            invalides.append((rel, f"ligne {exc.lineno}: {exc.msg}"))
        else:
            valides.append(rel)
    return tuple(valides), tuple(invalides), tuple(illisibles)


def test_le_perimetre_n_est_pas_vide():
    """Un garde qui ne regarde rien passe au vert pour rien."""
    valides, _, _ = _modules()
    assert len(valides) > 500, (
        f"seulement {len(valides)} modules vus dans {DOSSIERS} -- "
        "perimetre suspect, le garde ne prouverait rien"
    )


def test_aucun_module_non_parsable():
    """Le contrat. Un .py du depot qui ne parse pas est une panne differee."""
    _, invalides, _ = _modules()
    assert not invalides, "modules non parsables :\n" + "\n".join(
        f"  {rel} -- {motif}" for rel, motif in invalides
    )


def test_aucun_module_illisible():
    """ILLISIBLE n'est pas SAIN : on le nomme au lieu de le compter vert."""
    _, _, illisibles = _modules()
    assert not illisibles, "modules illisibles (ni valides ni invalides) :\n" + "\n".join(
        f"  {rel} -- {motif}" for rel, motif in illisibles
    )


def _noms_libres_au_niveau_module(source: str) -> set[str]:
    """Noms charges HORS de toute fonction : ils sont evalues a l'IMPORT.

    La distinction est ce qui donne sa priorite au defaut. Un nom libre dans un
    corps de fonction ne casse qu'a l'APPEL du chemin concerne -- c'est une panne
    latente. Le meme nom au niveau module tue l'import, donc tout ce qui en depend.
    Mesure du 2026-09-08 sur app/ et tools/ : 31 modules portent des noms libres,
    mais **un seul** casse a l'import. Sans cette separation, on aurait ouvert un
    chantier de 31 corrections la ou 1 debloquait.
    """
    import builtins as _b

    arbre = ast.parse(source)
    lies: set[str] = set(dir(_b)) | {
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

    dans_fonction = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sous in ast.walk(noeud):
                dans_fonction.add(id(sous))

    return {
        n.id for n in ast.walk(arbre)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        and n.id not in lies and id(n) not in dans_fonction
    }


def test_aucun_nom_libre_au_niveau_module():
    """Un decoupage qui migre un symbole sans ecrire l'import tue l'import.

    Deux instances le meme jour : forge_agent_hardware (AgentRole et 5 autres
    migres vers forge_agents, import jamais ecrit) et forge_mixin_ai (la classe
    avait perdu son underscore de tete, son instanciation non). Aucune des deux
    n'etait visible en relecture : le fichier PORTAIT des commentaires disant que
    les symboles venaient d'ailleurs.

    Les noms libres en corps de FONCTION ne sont volontairement pas couverts ici :
    30 modules en ont, c'est une dette mesuree et documentee, pas un contrat qu'on
    peut tenir aujourd'hui. On observe avant d'enforcer.
    """
    fautifs = []
    for rel, source in _sources():
        if isinstance(source, Exception):
            continue  # couvert par test_aucun_module_illisible
        try:
            libres = _noms_libres_au_niveau_module(source)
        except SyntaxError:
            continue  # couvert par test_aucun_module_non_parsable
        if libres:
            fautifs.append(f"  {rel} -- {', '.join(sorted(libres))}")
    assert not fautifs, (
        "noms utilises au NIVEAU MODULE sans etre definis ni importes "
        "(l'import du module leve NameError) :\n" + "\n".join(fautifs)
    )


# Noms dont l'absence d'import est TOUJOURS un oubli, jamais une intention :
# un module de la bibliotheque standard, ou un symbole des deux modules que le
# depot importe partout. On ne met ici que ce qui est decidable sans contexte.
# `Protocol` en est ABSENT deliberement : mesure du 2026-09-08, forge_at_dispatch
# ecrit `protocol=Protocol.HTTP` -- un enum METIER, pas typing.Protocol. Poser
# l'import typing y aurait masque le vrai symbole manquant. Un nom ambigu ne va
# pas dans une liste de noms « toujours decidables ».
_TYPING = {
    "List", "Dict", "Optional", "Any", "Callable", "Tuple", "Set", "Union",
    "Iterable", "Iterator", "Sequence", "Mapping",
}
_DATACLASSES = {"dataclass", "asdict", "field", "astuple"}


def _noms_libres_partout(source: str) -> set[str]:
    """Noms charges non lies, y compris DANS les corps de fonction."""
    import builtins as _b

    arbre = ast.parse(source)
    lies: set[str] = set(dir(_b)) | {
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
    return {
        n.id for n in ast.walk(arbre)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in lies
    }


def test_aucun_import_standard_oublie():
    """Un import stdlib manquant est une NameError qui attend son chemin.

    Contrat INTERMEDIAIRE, et c'est deliberé. Mesure du 2026-09-08 : 31 modules
    de app/ et tools/ portent des noms libres, mais seul un sous-ensemble est
    DECIDABLE sans contexte -- `import time` oublie est toujours un oubli, tandis
    que `NetworkDiscovery` absent demande d'instruire ou le symbole a migre.
    33 occurrences dans 18 modules au moment de l'ecriture de ce test.

    Les symboles metier restent hors contrat : les mettre ici rendrait le garde
    intenable, et un garde qu'on ne peut pas tenir finit desarme.
    """
    import sys as _sys

    # FRAGMENTS greffes : du code destine a etre injecte dans un espace de noms
    # HOTE, qui lui fournit ses symboles. Y ajouter des imports serait faux, pas
    # prudent. Ecarte NOMMEMENT et avec motif, jamais par un filtre silencieux.
    fragments = {
        # se declare lui-meme « infra/util : (gele) » ; consomme sys, os, Path,
        # json, subprocess et ROOT depuis l'espace de noms que son hote construit
        # avant de l'evaluer.
        "tools/_run_python_new.py",
    }

    attendus = set(_sys.stdlib_module_names) | _TYPING | _DATACLASSES
    fautifs = []
    for rel, source in _sources():
        if isinstance(source, Exception) or rel in fragments:
            continue
        try:
            libres = _noms_libres_partout(source)
        except SyntaxError:
            continue  # couvert par test_aucun_module_non_parsable
        oublis = libres & attendus
        if oublis:
            fautifs.append(f"  {rel} -- {', '.join(sorted(oublis))}")
    assert not fautifs, (
        "imports de la bibliotheque standard oublies "
        "(NameError des que le chemin est emprunte) :\n" + "\n".join(fautifs)
    )


def test_le_capteur_voit_vraiment_un_fichier_casse(tmp_path):
    """Preuve que le garde n'est pas muet.

    Reproduit la forme EXACTE du defaut du 2026-09-08 : un import a la colonne 0
    insere au milieu d'un corps de methode indente.
    """
    casse = tmp_path / "faux_module.py"
    casse.write_text(
        "class T:\n"
        "    def m(self):\n"
        "        import sqlite3\n"
        "from forge_spike_router import evaluate_intent, hashlib\n"
        "        return sqlite3\n",
        encoding="utf-8",
    )
    try:
        ast.parse(casse.read_text(encoding="utf-8"))
    except SyntaxError:
        return  # le capteur voit -- c'est ce qu'on voulait prouver
    raise AssertionError(
        "le capteur n'a PAS vu un fichier casse de la forme exacte du defaut : "
        "ce garde serait muet"
    )
