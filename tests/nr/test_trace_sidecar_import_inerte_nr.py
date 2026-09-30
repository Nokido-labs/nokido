# -*- coding: utf-8 -*-
"""NR — importer `forge_trace_sidecar` ne doit RIEN demarrer.

CE QUI A ETE MESURE (2026-09-16). Le module portait au niveau module, donc
execute a l'import :

    L22  logging.basicConfig(... RotatingFileHandler(logs/trace_sidecar.log))
    L58  init_db()                       -> ouvre/cree une base
    L59  logging.info(f"... {count_traces()} ...")   -> requete la base
    L64  goal_emb = encode_state(GOAL_TEXT)          -> embedding
    L92  threading.Thread(target=_state_loop, daemon=True).start()
    L93  _refresh_state()

Autrement dit `import forge_trace_sidecar` DEMARRE le daemon. Et le test
d'appui genere (`test_appui_forge_trace_sidecar_nr.py`) fait exactement cet
import : chaque run de la suite lancait donc un thread de fond qui vivait
jusqu'a la fin du process, ouvrait un journal et touchait une base.

C'est la meme famille que `forge_trace_replay` (journal ouvert a l'import,
`PermissionError` sous un autre compte) mais PLUS LARGE : un handler de
journal se contourne, un thread et une base non. Le defaut n'est pas « un
handler de fichier », c'est « le point d'entree est le corps du module ».

CE QUE CE NR VERROUILLE — et pourquoi il ne lit pas le module en l'important :
un test qui importerait pour mesurer declencherait precisement ce qu'il
condamne. Le jugement se fait donc sur l'AST, ou rien ne s'execute.

⚠️ Piege paye le 2026-09-16 sur le NR jumeau : `ast.walk` depuis le module
descend DANS les `def`, donc un correctif qui deplace l'effet de bord dans une
fonction reste condamne par le test — le NR condamnait son propre correctif.
D'ou l'exclusion explicite des `FunctionDef/AsyncFunctionDef/ClassDef`.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CIBLE = ROOT / "tools" / "forge_trace_sidecar.py"

# Ce qui, execute a l'import, reclame un privilege, une ressource ou un fil
# d'execution. La liste est VOLONTAIREMENT plus large que « ouvre un journal ».
APPELS_INTERDITS = {
    "basicConfig", "FileHandler", "RotatingFileHandler",
    "TimedRotatingFileHandler",
    "open", "mkdir", "makedirs", "touch", "write_text",
    "init_db", "count_traces", "encode_state", "get_current_state_text",
    "start",            # threading.Thread(...).start()
    "connect",          # sqlite3.connect
}


def _arbre():
    return ast.parse(CIBLE.read_text(encoding="utf-8", errors="replace"))


def _effets_au_niveau_module(tree):
    """Les appels qui s'EXECUTENT a l'import — hors corps de fonction/classe.

    Un appel ecrit dans un `def` ne s'execute pas a l'import : le compter
    reviendrait a interdire le correctif lui-meme.
    """
    trouves = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                nom = getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)
                if nom in APPELS_INTERDITS:
                    trouves.append((getattr(node, "lineno", "?"), nom))
    return trouves


def test_l_import_du_sidecar_n_a_aucun_effet_de_bord():
    trouves = _effets_au_niveau_module(_arbre())
    assert not trouves, (
        "importer forge_trace_sidecar execute %d appel(s) a effet de bord : %s. "
        "Un import doit etre INERTE : ces appels vont dans `demarrer()`, "
        "appelee par `main()`." % (len(trouves), trouves))


def test_le_module_a_un_point_d_entree_nomme():
    """`demarrer()` et `main()` existent — sinon l'effet de bord n'a nulle part ou aller."""
    tree = _arbre()
    fonctions = {n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    manquantes = {"demarrer", "main"} - fonctions
    assert not manquantes, (
        "fonctions absentes : %s — deplacer l'effet de bord hors du corps du "
        "module suppose un endroit ou le mettre" % sorted(manquantes))


def test_le_garde_main_appelle_main():
    """Le chemin REEL (`python -m ...`) doit passer par `main()`.

    Cliquet niveau 4 de la methode : sans ca, `demarrer()` pourrait exister et
    n'etre appelee par personne — un mecanisme present sans effet reel.
    """
    tree = _arbre()
    gardes = [n for n in tree.body if isinstance(n, ast.If)
              and "__name__" in ast.unparse(n.test)]
    assert gardes, "aucun garde `if __name__ == '__main__':`"
    corps = ast.unparse(ast.Module(body=gardes[0].body, type_ignores=[]))
    assert "main()" in corps, (
        "le garde __main__ n'appelle pas main() : %r" % corps[:200])


def test_la_docstring_est_en_tete():
    """`__doc__` etait None : un `import` precedait la docstring.

    Meme defaut que sur `forge_trace_replay`. Une docstring qui n'est pas le
    premier statement n'est pas une docstring, c'est une chaine sans effet —
    et tout outil qui documente le module lit alors None.
    """
    tree = _arbre()
    assert ast.get_docstring(tree), (
        "le module n'a pas de docstring : le premier statement est %s"
        % type(tree.body[0]).__name__)
