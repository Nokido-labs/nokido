"""NR — la désérialisation ne s'appuie pas sur une protection non déclarée.

## Le défaut, mesuré le 2026-09-19

Le dépôt porte **9 `torch.load`**. Un seul passe `weights_only=True`, un le
passe explicitement à `False`, et **sept** ne le passent pas du tout : ils
s'en remettent au défaut de la version installée.

Or ce défaut a changé : `weights_only=True` n'est le défaut **que depuis
torch 2.6**. En dessous, `torch.load` **dépickle** — il exécute du code à la
lecture d'un fichier de modèle.

`pyproject.toml` déclarait `torch>=2.2.0`. La protection existait donc dans
l'environnement de développement (torch 2.13), et **pas dans le contrat** : un
contributeur installant l'extra `ml` pouvait obtenir une version où elle
n'existe pas. C'est la même famille que « un garde branché sur un signal que
personne n'émet » — ici, un garde fourni par une dépendance qu'on n'exige pas.

## Ce que ce test verrouille

Que la contrainte reste cohérente avec ce sur quoi le code compte. Si un jour
tous les `torch.load` deviennent explicites, la contrainte pourra être relâchée
— et ce test devra être **réécrit**, pas contourné.

## Ce qu'il ne prétend pas

Il ne dit pas qu'un défaut est exploitable : tous les chemins mesurés lisent des
constantes de module, dans des répertoires que seul le dépôt écrit. C'est un
durcissement de contrat, pas la fermeture d'une brèche démontrée.
"""
from __future__ import annotations

import ast
import glob
import os
import sys
import tomllib
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture + ast de app/,
#   tools/, web_hub (l.53)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

VERSION_SURE = (2, 6)   # `weights_only=True` par defaut


def _torch_loads() -> tuple[list, list, int, list]:
    """(implicites, explicites_false, fichiers_lus, illisibles)."""
    implicites, faux, lus, illisibles = [], [], 0, []
    for sub in ("app", "tools", os.path.join("app", "web_hub")):
        for f in glob.glob(str(RACINE / sub / "*.py")):
            rel = os.path.relpath(f, RACINE)
            try:
                arbre = ast.parse(Path(f).read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError) as e:  # muet-ok : compte et rendu
                illisibles.append((rel, type(e).__name__))
                continue
            lus += 1
            for n in ast.walk(arbre):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "load"
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "torch"):
                    continue
                valeur = None
                for kw in n.keywords:
                    if kw.arg == "weights_only":
                        valeur = ast.unparse(kw.value)
                if valeur is None:
                    implicites.append("%s:%d" % (rel, n.lineno))
                elif valeur == "False":
                    faux.append("%s:%d" % (rel, n.lineno))
    return implicites, faux, lus, illisibles


def test_la_contrainte_torch_couvre_ce_sur_quoi_le_code_compte():
    implicites, _faux, lus, illisibles = _torch_loads()
    assert lus > 500, "denominateur suspect : %d fichiers lus" % lus
    if not implicites:
        pytest.skip("plus aucun torch.load implicite : la contrainte peut etre relachee, "
                    "mais ce test doit alors etre RECRIT, pas contourne")

    with open(RACINE / "pyproject.toml", "rb") as f:
        pj = tomllib.load(f)
    deps = []
    for liste in (pj["project"].get("optional-dependencies") or {}).values():
        deps += list(liste)
    deps += list(pj["project"].get("dependencies") or [])
    contraintes = [d for d in deps if d.lower().replace(" ", "").startswith("torch>=")]
    assert contraintes, (
        "%d torch.load s'en remettent au defaut de la version, et aucune "
        "contrainte `torch>=` n'est declaree : la protection depend d'un hasard "
        "d'installation. Sites : %s" % (len(implicites), implicites[:4]))

    for c in contraintes:
        brut = c.lower().replace(" ", "").split("torch>=")[1]
        brut = brut.split(",")[0].strip('"\'')
        v = tuple(int(x) for x in brut.split(".")[:2] if x.isdigit())
        assert v >= VERSION_SURE, (
            "contrainte `%s` : sous torch %s, `torch.load` DEPICKLE par defaut, "
            "et %d appels du depot s'en remettent a ce defaut. Sites : %s"
            % (c, ".".join(map(str, VERSION_SURE)), len(implicites), implicites[:4]))


def test_un_weights_only_False_EXPLICITE_reste_rare_et_assume():
    """Desactiver une protection active se fait a l'unite, pas par habitude."""
    _implicites, faux, _lus, _ill = _torch_loads()
    assert len(faux) <= 1, (
        "%d appels desactivent explicitement weights_only : %s. Chacun doit "
        "avoir une raison (charger un dict de metadonnees, par exemple) et non "
        "etre copie d'un voisin" % (len(faux), faux))


def test_aucun_yaml_load_non_sur():
    """`yaml.load` sans SafeLoader execute du code. Zero mesure le 2026-09-19."""
    trouves, lus = [], 0
    for sub in ("app", "tools", os.path.join("app", "web_hub")):
        for f in glob.glob(str(RACINE / sub / "*.py")):
            rel = os.path.relpath(f, RACINE)
            try:
                arbre = ast.parse(Path(f).read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):  # muet-ok : non parsable != yaml.load
                continue
            lus += 1
            for n in ast.walk(arbre):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "load"
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "yaml"):
                    loader = [kw for kw in n.keywords if kw.arg == "Loader"]
                    if not loader or "Safe" not in ast.unparse(loader[0].value):
                        trouves.append("%s:%d" % (rel, n.lineno))
    assert lus > 500, "denominateur suspect : %d" % lus
    assert not trouves, "yaml.load sans SafeLoader : %s" % trouves


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
