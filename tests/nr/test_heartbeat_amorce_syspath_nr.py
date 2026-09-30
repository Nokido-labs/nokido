# -*- coding: utf-8 -*-
"""NR — un module de `tools/` qui bat doit pouvoir IMPORTER le chemin canonique.

Defaut mesure le 2026-09-05, consequence de la migration des pouls vers
`forge_heartbeat.beat_daemon` : `tools/forge_docker_keeper.py` importait
`forge_heartbeat` (qui vit dans `app/`) sans amorcer `sys.path`. Le keeper mourait
en `ModuleNotFoundError` AU PREMIER TICK, donc avant d'ecrire le moindre pouls.

Ce qui rend le defaut couteux, c'est son SILENCE : le superviseur repondait
`already_running` et `ensure` rendait `ok: true` pendant que chaque instance
mourait en 30 s. Le pouls restait fige sur celui de l'ancienne instance — un
`code_stale: true` que rien ne lisait. Docker (une PROTHESE) paraissait en panne
alors que l'organe qui la regule etait mort.

Piege du fichier lui-meme : `forge_docker_keeper` PORTAIT bien un
`sys.path.insert(... / "app")`, mais enfoui dans `_maybe_release()`, une branche
rare jamais atteinte avant le premier pouls. Une dependance satisfaite seulement
sur un chemin d'exception n'est pas une dependance satisfaite — d'ou une
verification par AST et par PORTEE, jamais par simple presence dans le fichier.
"""
import ast
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les
#   tools/*.py (l.62)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]


def _mute_syspath(noeud) -> bool:
    """True si ce noeud (ou un descendant) modifie `sys.path`.

    On ne cherche PAS le litteral « app » dans l'appel : le chemin passe souvent
    par une variable (`for _p in (ROOT / "app", ...)`) et l'exiger fabriquait un
    faux positif sur un module parfaitement sain — mesure du 05/09, verifiee.
    """
    for x in ast.walk(noeud):
        if not isinstance(x, ast.Call):
            continue
        f = x.func
        if isinstance(f, ast.Attribute) and f.attr in ("insert", "append", "extend"):
            cible = ast.unparse(f.value) if hasattr(ast, "unparse") else ""
            if cible.endswith("path") and "sys" in cible:
                return True
    return False


def _niveau_module(arbre) -> list:
    """Statements executes A L'IMPORT — donc SANS les corps de fonctions.

    `arbre.body` contient aussi les `FunctionDef`, et `ast.walk` descend dedans :
    tester `arbre.body` tel quel revenait a demander « une mutation existe-t-elle
    QUELQUE PART dans le fichier ? ». Ce garde a donc laisse passer
    `forge_tdr_sentinel`, dont l'unique insertion vit dans `_handle_tdr_event`,
    une branche qui ne s'execute QUE lors d'un TDR. Le garde reproduisait
    exactement le defaut qu'il devait detecter (mesure 2026-09-05).
    """
    return [n for n in arbre.body
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef))]


def _fautifs() -> list:
    out = []
    for f in sorted((ROOT / "tools").glob("*.py")):
        texte = f.read_text(encoding="utf-8", errors="replace")
        if "forge_heartbeat" not in texte:
            continue
        try:
            arbre = ast.parse(texte)
        except SyntaxError as exc:
            out.append("%s: ILLISIBLE (%s)" % (f.name, exc))
            continue
        # Une amorce au niveau MODULE (hors corps de fonction) couvre tout le fichier.
        if any(_mute_syspath(n) for n in _niveau_module(arbre)):
            continue
        # Une fonction du module qui amorce : l'APPELER dans sa portee vaut amorce,
        # car l'appel precede l'import et son execution est donc garantie. C'est
        # different de compter sur un appel ANTERIEUR fait ailleurs dans le flux —
        # cette dependance-la est justement ce qui a tue deux daemons.
        amorceuses = {n.name for n in ast.walk(arbre)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and _mute_syspath(n)}
        for fn in ast.walk(arbre):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            importe = any(isinstance(x, ast.ImportFrom) and x.module == "forge_heartbeat"
                          for x in ast.walk(fn))
            if not importe or _mute_syspath(fn):
                continue
            appelle_amorceuse = any(
                isinstance(x, ast.Call) and getattr(x.func, "id", "") in amorceuses
                for x in ast.walk(fn))
            if not appelle_amorceuse:
                out.append("%s: %s() importe forge_heartbeat sans amorce sys.path "
                           "dans sa portee" % (f.name, fn.name))
    return out


def test_aucun_batteur_sans_amorce():
    fautifs = _fautifs()
    assert not fautifs, (
        "module(s) qui mourront en ModuleNotFoundError au premier pouls :\n  "
        + "\n  ".join(fautifs))


def test_une_amorce_enfouie_dans_une_fonction_ne_compte_pas():
    """Garde du garde : le cas `forge_tdr_sentinel`, que ce NR laissait passer.

    Une insertion vivant dans une AUTRE fonction ne rend pas l'import disponible
    au moment du pouls. Si ce test casse, le garde est redevenu aveugle.
    """
    src = (
        "import sys\n"
        "from pathlib import Path\n"
        "def _rare():\n"
        "    sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))\n"
        "def _bat():\n"
        "    from forge_heartbeat import beat_daemon\n"
        "    return beat_daemon('x')\n"
    )
    arbre = ast.parse(src)
    assert not any(_mute_syspath(n) for n in _niveau_module(arbre)), \
        "une amorce enfouie dans une fonction est comptee comme niveau module"
    bat = [n for n in arbre.body
           if isinstance(n, ast.FunctionDef) and n.name == "_bat"][0]
    assert not _mute_syspath(bat), "la fonction qui bat n'a pas d'amorce propre"


def test_le_cas_paye_est_couvert():
    """Garde du garde : le fichier reellement tombe doit etre celui qu'on inspecte."""
    cible = ROOT / "tools" / "forge_docker_keeper.py"
    assert cible.exists()
    texte = cible.read_text(encoding="utf-8", errors="replace")
    assert "forge_heartbeat" in texte, "cible hors perimetre : le NR ne prouve plus rien"
