"""NR — un symbole libre resolvable a UNE SEULE source doit etre importe.

SUITE DIRECTE du defaut du 2026-09-08 : le grand decoupage de `Nokido.py` a migre
des classes vers des modules dedies SANS ecrire les imports correspondants. Le
fichier porte souvent le commentaire « X importe depuis Y », ce qui SE LIT comme
un import et n'en est pas un. `forge_agent_hardware` levait `NameError` des sa
premiere ligne executable ; `forge_mixin_ai` de meme.

CE QUE CE CONTRAT COUVRE, et seulement lui. Mesure du 2026-09-08 sur 2407
fichiers de `app/` et `tools/` : 84 symboles metier libres, dont

  * 21 resolus a UNE SEULE source du depot  -> MECANIQUE, c'est ce fichier
  *  7 fournis par la stdlib ou une lib tierce -> autre contrat
  * 38 definis a PLUSIEURS endroits          -> a TRANCHER, hors contrat
  * 18 vraiment introuvables                 -> a INSTRUIRE, hors contrat

Les deux dernieres categories sont volontairement EXCLUES : un symbole a deux
definitions demande de choisir laquelle, et un symbole absent demande d'enqueter.
Mettre tout sous contrat le rendrait intenable, et un garde qu'on ne peut pas
tenir finit desarme. On observe avant d'enforcer.

CE QU'IL FAUT FAIRE POUR LE METTRE AU VERT : pour chaque ligne rapportee, ajouter
l'import du symbole depuis la source NOMMEE dans le message. Rien d'autre --
aucune reecriture, aucun renommage.

⚠️ VERIFIER L'USAGE AVANT DE POSER L'IMPORT. Piege paye le meme jour : `datetime`
etait appele comme CLASSE (`datetime.now()`), donc `from datetime import datetime`
et non `import datetime`, qui aurait cree un bug SILENCIEUX dans quatre fichiers.
Et `Protocol` dans `forge_at_dispatch` n'est pas `typing.Protocol` mais un enum
METIER : poser l'import typing y aurait masque le vrai symbole manquant.
"""

from __future__ import annotations

import ast
import builtins
import sys
from functools import lru_cache
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + ast (l.130)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
DOSSIERS = ("app", "tools")
EXCLUS = {"_attic", "backups", "legacy", "__pycache__", "node_modules", ".venv"}

_DUNDERS = {
    "__file__", "__name__", "__doc__", "__package__",
    "__spec__", "__loader__", "__builtins__", "__debug__", "__path__",
}
_TIERS = {
    "Path", "NoneType", "List", "Dict", "Optional", "Any", "Callable", "Tuple",
    "Set", "Union", "Protocol", "Sequence", "Iterable", "Iterator", "Mapping",
    "dataclass", "asdict", "field", "astuple",
    "Horizontal", "Vertical", "AutocompleteInput", "SentenceTransformer",
}
# Fichiers de travail jetables : ils ne sont pas une unite de comportement a
# regresser, et le census les ecarte deja de la couverture pour ce motif.
_JETABLES = ("tmp_", "_batch", "diag_", "paste_")

# SOURCES qu'on refuse de proposer comme cible d'import, meme quand elles sont
# l'unique definition connue. Mesure du 2026-09-08 : le contrat naif produisait
# deux recommandations DANGEREUSES.
#   * `vm <- tools/tmp_diag.py` : importer depuis un script jetable. Le symbole
#     est en realite une variable locale perdue par un decoupage.
#   * `save_orchestrator`, `_mem_mgr`, `HAS_PREDICTIF`, `intent_classifier`
#     <- `app/Nokido.py` : c'est le POINT D'ENTREE de l'application. L'importer
#     depuis un module qu'il importe lui-meme fabrique un cycle.
# Ces cas ne sont pas « mecaniques » : ils demandent d'instruire ou le symbole
# doit vivre. Les laisser dans le contrat ferait produire du mauvais code a qui
# le met au vert -- un garde qui dicte une faute est pire qu'un garde absent.
_SOURCES_REFUSEES = ("app/Nokido.py",)


def _definitions_du_module(arbre: ast.Module) -> set[str]:
    """Noms definis AU NIVEAU MODULE, y compris sous try/if/with."""
    trouves: set[str] = set()

    def marche(corps):
        for noeud in corps:
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                trouves.add(noeud.name)
            elif isinstance(noeud, ast.Assign):
                for cible in noeud.targets:
                    if isinstance(cible, ast.Name):
                        trouves.add(cible.id)
            elif isinstance(noeud, ast.AnnAssign) and isinstance(noeud.target, ast.Name):
                trouves.add(noeud.target.id)
            elif isinstance(noeud, (ast.Try, ast.If, ast.With)):
                for champ in ("body", "orelse", "finalbody"):
                    marche(getattr(noeud, champ, []) or [])
                for gestionnaire in getattr(noeud, "handlers", []) or []:
                    marche(gestionnaire.body)

    marche(arbre.body)
    return trouves


def _noms_libres(arbre: ast.Module) -> set[str]:
    lies = set(dir(builtins)) | _DUNDERS
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


@lru_cache(maxsize=1)
def _analyse():
    """Rend (definitions_par_symbole, libres_par_module). Un seul parcours."""
    fichiers = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if EXCLUS & set(chemin.relative_to(RACINE).parts):
                continue
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue  # couvert par test_modules_parsables_nr
            fichiers.append((chemin.relative_to(RACINE).as_posix(), arbre))

    definitions: dict[str, set[str]] = {}
    for rel, arbre in fichiers:
        for nom in _definitions_du_module(arbre):
            definitions.setdefault(nom, set()).add(rel)

    libres = {rel: _noms_libres(arbre) for rel, arbre in fichiers}
    return definitions, libres


def test_le_perimetre_est_reel():
    """Un contrat qui ne regarde rien passerait au vert pour rien."""
    definitions, libres = _analyse()
    assert len(libres) > 500, f"seulement {len(libres)} modules analyses"
    assert len(definitions) > 1000, f"seulement {len(definitions)} symboles indexes"


def test_aucun_symbole_a_source_unique_reste_libre():
    """Le contrat MECANIQUE : source connue et unique => l'import doit exister."""
    definitions, libres = _analyse()
    standard = set(sys.stdlib_module_names)
    fautifs = []
    for rel, noms in sorted(libres.items()):
        if any(Path(rel).name.startswith(p) for p in _JETABLES):
            continue
        for nom in sorted(noms):
            if nom in standard or nom in _TIERS:
                continue
            sources = {
                s for s in definitions.get(nom, set()) - {rel}
                if s not in _SOURCES_REFUSEES
                and not any(Path(s).name.startswith(p) for p in _JETABLES)
            }
            if len(sources) == 1:
                source = next(iter(sources))
                fautifs.append(f"  {rel} : {nom} <- a importer depuis {source}")
    assert not fautifs, (
        "symboles utilises sans import alors que leur source est UNIQUE et connue "
        f"({len(fautifs)} sites) :\n" + "\n".join(fautifs)
    )
