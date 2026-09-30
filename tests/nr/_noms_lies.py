# -*- coding: utf-8 -*-
"""Helper (hors collecte : prefixe `_`) — un nom LU doit etre LIE sur son chemin.

Sert les NR de l'audit « noms non definis » (mesures/audits/noms_non_definis.md).
Les chemins vises sont des handlers de la TUI, des replis et des chemins d'erreur :
les executer demande l'application, un hub, SSH, Ollama... absents en CI. On
verifie donc la LIAISON statiquement, avec `symtable` -- la table des symboles que
le compilateur CPython construit lui-meme, pas une imitation de ses regles de portee.

Trois constats, trois fonctions :

- `noms_globaux_non_lies(fichier, fonction)` : noms qu'une fonction (et ce qu'elle
  imbrique : fonctions, lambdas, comprehensions) lit comme GLOBAUX, alors que le
  module ne les lie nulle part et que ce ne sont pas des builtins -> NameError
  au premier passage.
- `lus_avant_affectation(fichier, fonction)` : variables LOCALES dont une lecture
  precede, dans le texte, leur premiere affectation -> UnboundLocalError sur au
  moins un chemin. Approximation volontaire (ordre des lignes, pas flot de
  controle) : suffisante pour garder un cas precis, trop grossiere pour un
  balayage general.
- `attributs_absents(fichier, module)` : `module.attr` lus alors que `module` est
  lie par `import module` et que ce module reel n'a pas cet attribut
  (ex. `datetime.now()` sur le MODULE datetime) -> AttributeError.

Un module qui fait `from x import *` rend la liaison indecidable : les fonctions
levent alors `ValueError` plutot que d'accuser au hasard.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import symtable
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

# Poses par l'import lui-meme dans tout module, absents de `dir(builtins)`.
_DUNDERS_DE_MODULE = {"__file__", "__builtins__", "__path__", "__cached__", "__annotations__"}


def _source(fichier: str) -> str:
    return (RACINE / fichier).read_text(encoding="utf-8", errors="replace")


def _refuser_import_etoile(arbre: ast.AST, fichier: str) -> None:
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
            raise ValueError("%s : `from %s import *` rend la liaison indecidable"
                             % (fichier, n.module))


def _tables(racine: symtable.SymbolTable, chemin: str) -> list:
    """Toutes les tables de `chemin` ("f", "Classe.m", "f.interne").

    Une meme fonction peut etre definie plusieurs fois (debris de monolithe) :
    on les rend TOUTES, pour que la verification porte sur chacune.
    """
    courantes = [racine]
    for morceau in chemin.split("."):
        suivantes = [e for t in courantes for e in t.get_children()
                     if e.get_name() == morceau]
        if not suivantes:
            raise LookupError("fonction introuvable : %s" % chemin)
        courantes = suivantes
    return courantes


def _descendants(table: symtable.SymbolTable):
    yield table
    for enfant in table.get_children():
        yield from _descendants(enfant)


def _lies_au_module(racine: symtable.SymbolTable) -> set:
    lies = set()
    for s in racine.get_symbols():
        if s.is_assigned() or s.is_imported() or s.is_namespace():
            lies.add(s.get_name())
    # `global x` + affectation dans une fonction lie aussi `x` au module.
    for t in _descendants(racine):
        if t is racine:
            continue
        for s in t.get_symbols():
            if s.is_declared_global() and s.is_assigned():
                lies.add(s.get_name())
    return lies


def noms_globaux_non_lies(fichier: str, fonction: str) -> set:
    src = _source(fichier)
    _refuser_import_etoile(ast.parse(src), fichier)
    racine = symtable.symtable(src, fichier, "exec")
    lies = _lies_au_module(racine) | set(dir(builtins)) | _DUNDERS_DE_MODULE
    manquants = set()
    for table in _tables(racine, fonction):
        for t in _descendants(table):
            for s in t.get_symbols():
                if s.is_global() and s.is_referenced() and s.get_name() not in lies:
                    manquants.add(s.get_name())
    return manquants


def noms_non_lies_du_module(fichier: str) -> set:
    """Comme `noms_globaux_non_lies`, pour TOUTES les portees du module
    (fonctions, methodes, classes, lambdas, comprehensions)."""
    src = _source(fichier)
    _refuser_import_etoile(ast.parse(src), fichier)
    racine = symtable.symtable(src, fichier, "exec")
    lies = _lies_au_module(racine) | set(dir(builtins)) | _DUNDERS_DE_MODULE
    manquants = set()
    for t in _descendants(racine):
        if t is racine:
            continue
        for s in t.get_symbols():
            if s.is_global() and s.is_referenced() and s.get_name() not in lies:
                manquants.add(s.get_name())
    return manquants


class _Occurrences(ast.NodeVisitor):
    """Premieres lignes de lecture / d'affectation, sans descendre dans les
    portees imbriquees (elles ont leur propre table)."""

    def __init__(self):
        self.lecture: dict = {}
        self.ecriture: dict = {}

    def _noter(self, d: dict, nom: str, ligne: int) -> None:
        if nom not in d or ligne < d[nom]:
            d[nom] = ligne

    def visit_Name(self, n: ast.Name) -> None:
        cible = self.ecriture if isinstance(n.ctx, (ast.Store, ast.Del)) else self.lecture
        self._noter(cible, n.id, n.lineno)

    def visit_AugAssign(self, n: ast.AugAssign) -> None:
        if isinstance(n.target, ast.Name):
            self._noter(self.lecture, n.target.id, n.lineno)
        self.generic_visit(n)

    def visit_ExceptHandler(self, n: ast.ExceptHandler) -> None:
        if n.name:
            self._noter(self.ecriture, n.name, n.lineno)
        self.generic_visit(n)

    def visit_Import(self, n) -> None:
        for a in n.names:
            self._noter(self.ecriture, (a.asname or a.name).split(".")[0], n.lineno)

    visit_ImportFrom = visit_Import

    def _portee(self, n) -> None:
        self._noter(self.ecriture, n.name, n.lineno)
        for d in getattr(n, "decorator_list", []):
            self.visit(d)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _portee

    def visit_Lambda(self, n) -> None:
        pass

    def _comprehension(self, n) -> None:
        # Seul l'iterable du premier `for` est evalue dans la portee englobante.
        self.visit(n.generators[0].iter)

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comprehension


def _defs(arbre: ast.AST, chemin: str) -> list:
    courants = [arbre]
    for morceau in chemin.split("."):
        suivants = []
        for c in courants:
            for n in ast.walk(c):
                if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and n.name == morceau and n is not c):
                    suivants.append(n)
        if not suivants:
            raise LookupError("fonction introuvable : %s" % chemin)
        courants = suivants
    return courants


def lus_avant_affectation(fichier: str, fonction: str) -> set:
    arbre = ast.parse(_source(fichier))
    fautifs = set()
    for d in _defs(arbre, fonction):
        occ = _Occurrences()
        for instr in d.body:
            occ.visit(instr)
        declares = {nom for n in ast.walk(d) if isinstance(n, (ast.Global, ast.Nonlocal))
                    for nom in n.names}
        args = {a.arg for a in d.args.args + d.args.kwonlyargs + d.args.posonlyargs}
        args |= {a.arg for a in (d.args.vararg, d.args.kwarg) if a}
        for nom, ligne in occ.lecture.items():
            if nom in declares or nom in args or nom not in occ.ecriture:
                continue
            if ligne < occ.ecriture[nom]:
                fautifs.add(nom)
    return fautifs


def _noms_de_tete(fichier_module: Path) -> set:
    """Noms lies au niveau module d'un fichier (def, class, affectation, import),
    branches `if`/`try` comprises."""
    arbre = ast.parse(fichier_module.read_text(encoding="utf-8", errors="replace"))
    noms = set()

    def _cibles(n):
        if isinstance(n, ast.Name):
            noms.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                _cibles(e)

    def _bloc(instrs):
        for n in instrs:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                noms.add(n.name)
            elif isinstance(n, ast.Assign):
                for c in n.targets:
                    _cibles(c)
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
                _cibles(n.target)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    noms.add((a.asname or a.name).split(".")[0])
            for champ in ("body", "orelse", "finalbody"):
                if isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                    _bloc(getattr(n, champ, []) or [])
            if isinstance(n, ast.Try):
                for h in n.handlers:
                    _bloc(h.body)

    _bloc(arbre.body)
    return noms


def imports_introuvables(fichier: str, fonction: str) -> set:
    """`from nokido_agent.app.X import Y` (ou `app.X`) faits dans `fonction` alors
    que app/X.py ne lie pas `Y` au niveau module -> ImportError a l'execution."""
    arbre = ast.parse(_source(fichier))
    fautifs = set()
    for d in _defs(arbre, fonction):
        for n in ast.walk(d):
            if not isinstance(n, ast.ImportFrom) or not n.module:
                continue
            for prefixe in ("nokido_agent.app.", "app."):
                if n.module.startswith(prefixe):
                    chemin = RACINE / "app" / n.module[len(prefixe):].replace(".", "/")
                    cible = chemin.with_suffix(".py")
                    if not cible.exists():  # module paquet : app/x/y/__init__.py
                        cible = chemin / "__init__.py"
                    break
            else:
                continue
            if not cible.exists():
                fautifs.add("%s (module absent)" % n.module)
                continue
            lies = _noms_de_tete(cible)
            for a in n.names:
                if a.name not in lies:
                    fautifs.add("%s.%s" % (n.module, a.name))
    return fautifs


def attributs_absents(fichier: str, module: str) -> set:
    """`module.attr` lus dans `fichier` alors que `module` y est lie par
    `import module` (au niveau du module) et que le vrai module n'a pas `attr`.

    Ne regarde pas les portees qui re-lient `module` localement.
    """
    arbre = ast.parse(_source(fichier))
    lie_comme_module = any(
        isinstance(n, ast.Import) and any(a.name == module and not a.asname for a in n.names)
        for n in arbre.body)
    if not lie_comme_module:
        return set()
    reel = importlib.import_module(module)
    absents = set()

    def _parcourir(noeud, masque: bool) -> None:
        for enfant in ast.iter_child_nodes(noeud):
            m = masque
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                corps = enfant.body if isinstance(enfant.body, list) else [enfant.body]
                m = masque or any(
                    (isinstance(x, (ast.Import, ast.ImportFrom))
                     and any((a.asname or a.name) == module for a in x.names))
                    or (isinstance(x, ast.Name) and x.id == module
                        and isinstance(x.ctx, ast.Store))
                    for c in corps for x in ast.walk(c))
            if (not m and isinstance(enfant, ast.Attribute)
                    and isinstance(enfant.value, ast.Name) and enfant.value.id == module
                    and not hasattr(reel, enfant.attr)):
                absents.add("%s.%s (ligne %d)" % (module, enfant.attr, enfant.lineno))
            _parcourir(enfant, m)

    _parcourir(arbre, False)
    return absents
