"""NR — le registre des dispatchers du coeur n'enregistre QUE des methodes defensives.

Symetrique du split de `ALLOWED_METHODS` (owner 2026-09-26, commit 82e03a1d9 ; owner 2026-09-27 « sort-les
du registre ») : les intents offensifs (ring>=3) sont hors du coeur et chargés SEULEMENT via la charge
redteam optionnelle (`forge_trajectory._charger_intents_offensifs_optionnels`). Le câblage des dispatchers
doit suivre la même règle : un `register_dispatcher(m, fn)` NON gardé ne vaut que si `m` est une méthode du
coeur défensif ; un handler offensif ne peut être câblé que sous une garde référençant `ALLOWED_METHODS`
(donc seulement quand la charge l'a inséré). Invariant : registre du coeur ⊆ whitelist défensive.

Statique (AST) : ne nomme aucun intent offensif, ne dépend d'aucun import lourd, et vaut pour tout futur ajout.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAJ = ROOT / "app" / "forge_trajectory.py"
DISP = ROOT / "app" / "forge_dispatchers.py"


def _cles_declarees_en_code(chemin: Path) -> set:
    """Clés de ALLOWED_METHODS DÉCLARÉES en code dans ce fichier : le littéral `ALLOWED_METHODS = {...}`
    ET les ajouts par subscript `ALLOWED_METHODS[<const>] = ...`. Les intents offensifs ne sont JAMAIS
    déclarés en code (ils viennent de la charge redteam au runtime), donc jamais comptés ici."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    cles = set()
    for nd in ast.walk(arbre):
        if isinstance(nd, ast.Assign):
            for t in nd.targets:
                if getattr(t, "id", "") == "ALLOWED_METHODS" and isinstance(nd.value, ast.Dict):
                    cles |= {k.value for k in nd.value.keys if isinstance(k, ast.Constant)}
                if (isinstance(t, ast.Subscript) and getattr(t.value, "id", "") == "ALLOWED_METHODS"
                        and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                    cles.add(t.slice.value)
    return cles


def _allowed_defensif() -> set:
    """Whitelist défensive = déclarée en code dans le coeur (trajectory) + ajouts du module dispatchers."""
    cles = _cles_declarees_en_code(TRAJ) | _cles_declarees_en_code(DISP)
    if not cles:
        raise AssertionError("ALLOWED_METHODS introuvable dans forge_trajectory.py")
    return cles


def _register_calls_non_gardes(arbre) -> list:
    """(ligne, methode) de chaque register_dispatcher(<str>, _) NON gardé par un `if ... ALLOWED_METHODS`."""
    parents = {}
    for p in ast.walk(arbre):
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    def _garde(node) -> bool:
        cur = node
        while cur in parents:
            par = parents[cur]
            if isinstance(par, ast.If) and any(
                isinstance(n, ast.Name) and n.id == "ALLOWED_METHODS" for n in ast.walk(par.test)
            ):
                return True
            cur = par
        return False

    out = []
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "register_dispatcher"
                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            if not _garde(n):
                out.append((n.lineno, n.args[0].value))
    return out


def test_registre_coeur_est_un_sous_ensemble_de_la_whitelist_defensive():
    allowed = _allowed_defensif()
    arbre = ast.parse(DISP.read_text(encoding="utf-8"))
    non_gardes = _register_calls_non_gardes(arbre)
    hors = sorted({m for _, m in non_gardes if m not in allowed})
    assert hors == [], (
        "register_dispatcher NON gardé pour des méthodes hors du coeur défensif : %s "
        "— les câbler sous une garde `if <m> in ALLOWED_METHODS` (charge redteam), jamais en dur." % hors
    )


def test_le_coeur_defensif_reste_cable():
    # garde-fou de sens : on n'a pas vidé le registre. Une méthode defensive banale reste câblée sans garde.
    arbre = ast.parse(DISP.read_text(encoding="utf-8"))
    non_gardes = {m for _, m in _register_calls_non_gardes(arbre)}
    assert "run_shell" in non_gardes and "rag_search" in non_gardes
