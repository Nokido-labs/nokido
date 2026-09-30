"""NR — les primitives d'exécution orphelines le RESTENT, et la chaîne reste connue.

Audit du 2026-09-19 (classe « exécution de code dynamique »). Deux constats tenus
ici, et une leçon de méthode.

## Ce qui est verrouillé

`app/forge_mcp_safe.py` porte trois primitives. Une seule est câblée :

    safe_exec   <- forge_python_worker              (chemin REEL, assumé)
    run_b64     <- personne                         (décode du base64 et l'exécute)
    mcp_safe    <- personne                         (décorateur qui exécute un argument)

`run_b64` est la plus dangereuse des trois : lui donner un appelant rendrait
inopérante TOUTE inspection textuelle en amont, puisqu'un filtre ne peut pas lire
ce qu'il ne voit pas. On ne la supprime pas — on gèle, on n'enterre pas — mais
elle ne doit pas acquérir d'appelant sans décision explicite. Ce test transforme
ce « sans décision » en échec de CI.

## La leçon de méthode, payée dans cet audit

Un scan d'imports a d'abord conclu que `forge_python_worker` n'avait **aucun
appelant**, donc que la chaîne était morte. C'était un faux négatif :
`forge_python_runner` le lance en **SUBPROCESS, par chemin de fichier**. Un
graphe d'imports ne voit pas ce lien. D'où le second test, qui vérifie que la
chaîne documentée est toujours celle du code — par imports ET par mention de
chemin.
"""
from __future__ import annotations

import ast
import glob
import os
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de app/, tools/,
#   web_hub (l.49)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

ORPHELINES = ("run_b64", "mcp_safe")
SOURCE = RACINE / "app" / "forge_mcp_safe.py"


def _fichiers_du_depot():
    for sub in ("app", "tools", os.path.join("app", "web_hub")):
        for f in glob.glob(str(RACINE / sub / "*.py")):
            yield f


def _appelants(noms: tuple[str, ...]) -> tuple[dict, int, list]:
    """Rend (appelants, fichiers_lus, illisibles). Le dénominateur fait partie du résultat."""
    trouve: dict[str, list[str]] = {n: [] for n in noms}
    lus, illisibles = 0, []
    for f in _fichiers_du_depot():
        rel = os.path.relpath(f, RACINE)
        if os.path.samefile(f, SOURCE) if os.path.exists(f) else False:
            continue
        try:
            arbre = ast.parse(Path(f).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError) as e:  # muet-ok : compté et rendu, jamais avalé
            illisibles.append((rel, type(e).__name__))
            continue
        lus += 1
        for n in ast.walk(arbre):
            if isinstance(n, ast.Call):
                fn = n.func
                q = fn.attr if isinstance(fn, ast.Attribute) else (
                    fn.id if isinstance(fn, ast.Name) else "")
                if q in trouve:
                    trouve[q].append("%s:%d" % (rel, n.lineno))
            elif isinstance(n, ast.ImportFrom) and n.module and "forge_mcp_safe" in n.module:
                for a in n.names:
                    if a.name in trouve:
                        trouve[a.name].append("%s:%d (import)" % (rel, n.lineno))
    return trouve, lus, illisibles


def test_les_primitives_orphelines_n_ont_toujours_aucun_appelant():
    trouve, lus, illisibles = _appelants(ORPHELINES)
    assert lus > 500, "denominateur suspect : %d fichiers lus seulement" % lus
    for nom in ORPHELINES:
        assert trouve[nom] == [], (
            "`%s` a acquis un appelant (%s). Ce n'est pas un detail : c'est un "
            "elargissement de la surface d'execution, et pour run_b64 cela rend "
            "toute inspection textuelle amont inoperante. A decider explicitement, "
            "pas a subir. Fichiers lus=%d, illisibles=%s"
            % (nom, trouve[nom], lus, illisibles))


def test_le_cliquet_mord(monkeypatch):
    """Sans cette preuve, le test precedent serait vert par construction."""
    trouve, lus, _ = _appelants(("safe_exec",))
    assert trouve["safe_exec"], (
        "`safe_exec` DOIT avoir un appelant (forge_python_worker) : si la sonde "
        "n'en trouve aucun, elle ne cherche pas au bon endroit et le test jumeau "
        "ne prouve rien. Fichiers lus=%d" % lus)


def test_la_chaine_d_atteignabilite_est_toujours_celle_qui_est_documentee():
    """`forge_python_runner` lance le worker par CHEMIN, pas par import.

    Un graphe d'imports rate ce lien — c'est le faux negatif paye pendant
    l'audit. On verifie donc la mention du chemin, pas seulement les imports.
    """
    runner = RACINE / "app" / "forge_python_runner.py"
    assert runner.exists(), "forge_python_runner a disparu : la chaine documentee est perimee"
    src = runner.read_text(encoding="utf-8", errors="replace")
    assert "forge_python_worker" in src, (
        "le runner ne reference plus le worker : soit la chaine a change, soit "
        "elle passe desormais ailleurs — dans les deux cas la doctrine du module "
        "forge_mcp_safe doit etre remise a jour")


def test_le_module_dit_qu_il_n_est_PAS_un_bac_a_sable():
    """Un nom rassurant a suffi a faire attribuer a ce fichier un garde absent.

    La docstring doit contredire son propre nom, sinon le prochain lecteur
    refera l'erreur.
    """
    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    doc = ast.get_docstring(arbre) or ""
    assert doc, "module sans docstring : son nom est alors la seule source d'information"
    bas = doc.lower()
    assert "trompeur" in bas or "n'est" in bas, (
        "la docstring doit dire explicitement que ce module ne valide RIEN")
    assert "run_b64" in doc, "les primitives orphelines doivent etre nommees"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
