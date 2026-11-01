"""NR : la requete FTS du canal lexical vit dans UNE fonction pure, `requete_fts`, chargeable SEULE (owner 29/10).

Le banc d'amelioration `rappel_lexical` (tools/bancs/banc_rappel_lexical.py) juge cette fonction sur un mini-index
fige ; il l'extrait par AST de la copie du candidat, sans importer forge_rag_engine (index, embedders). Ce NR tient
le CONTRAT, pas une sortie exacte (la sortie exacte a prouve l'extraction e2b1c4f ; la figer interdisait toute
amelioration : 1er candidat du banc rejete GARDE_ROUGE le 29/10 pour avoir ecarte « pour ») :
(1) une chaine ; vide si aucun mot ; seulement des mots de la question, joints par OR, 15 au plus ; une expression que
FTS5 ACCEPTE (MATCH sans erreur de syntaxe) ; (2) l'autonomie de la fonction ; (3) le canal lexical reel l'appelle.
"""
import ast
import builtins
import importlib.util
import re
import sqlite3
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "app" / "forge_rag_engine.py"


def _arbre():
    return ast.parse(SRC.read_text(encoding="utf-8"))


def _fonction(nom):
    for n in _arbre().body:
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return n
    return None


def _charger(tmp_path):
    noeud = _fonction("requete_fts")
    assert noeud is not None, "requete_fts absente au niveau module de forge_rag_engine"
    seule = tmp_path / "requete_fts_seule.py"
    seule.write_text(ast.unparse(noeud) + "\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("requete_fts_seule", seule)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.requete_fts


QUESTIONS = ["Comment configurer le proxy LiteLLM pour LaForge ?", "Quel est le port HTTP du hub (8766) ?",
             "AND OR NOT NEAR \"guillemets\" (parentheses) * ^ : -", "forge_rag_engine.py et _scores_lexicaux",
             " ".join("mot%02d" % i for i in range(20)), "àéèç Ünïcode ß"]


def _termes(expr):
    return [t.strip().strip('"').rstrip("*") for t in expr.split(" OR ")] if expr else []


def contrat_viole(f, question):
    """Motif de la premiere violation du contrat de requete_fts sur `question`, None si le contrat tient."""
    expr = f(question)
    if not isinstance(expr, str):
        return "pas une chaine"
    termes = _termes(expr)
    if len(termes) > 15:
        return "plus de 15 termes"
    mots = {m.lower() for m in re.split(r"\W+", question) if m}
    if any(t.lower() not in mots for t in termes if t):
        return "terme absent de la question"
    if expr:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        try:
            con.execute("SELECT * FROM t WHERE t MATCH ?", (expr,)).fetchall()
        except sqlite3.OperationalError as e:
            return "FTS5 refuse : %s" % e
    return None


def test_contrat(tmp_path):
    f = _charger(tmp_path)
    for q in QUESTIONS:
        assert contrat_viole(f, q) is None, (q, contrat_viole(f, q))
    assert f("") == ""
    assert f("a bc") == "" or contrat_viole(f, "a bc") is None


def test_le_gain_rsi_prouve_est_garde(tmp_path):
    """Candidat AMELIORE du banc rappel_lexical (29/10, rappel@10 0,609 -> 0,630 sur le mini-index fige), integre le
    30/10 apres jugement : les mots vides pour/dans/quel/with ne partent plus dans l'expression FTS."""
    f = _charger(tmp_path)
    termes = f("Quel est le role du port dans le hub pour les clients with tokens").split(" OR ")
    assert not {"pour", "dans", "quel", "with"} & set(termes)
    assert {"port", "clients", "tokens"} <= set(termes)  # les mots porteurs restent


def test_le_contrat_rejette_ce_qu_il_doit():
    """Le contrat n'est pas une passoire : il refuse une syntaxe FTS cassee, un mot invente, plus de 15 termes."""
    assert contrat_viole(lambda q: "AND (", "x") is not None
    assert contrat_viole(lambda q: "invente", "rien a voir") is not None
    assert contrat_viole(lambda q: " OR ".join(["mot"] * 16), "mot") is not None
    assert contrat_viole(lambda q: 3, "x") is not None


def test_fonction_autonome():
    noeud = _fonction("requete_fts")
    assert noeud is not None
    locaux = {a.arg for a in noeud.args.args}
    for n in ast.walk(noeud):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            locaux.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            locaux.add(n.id)
    libres = {n.id for n in ast.walk(noeud) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert libres - locaux - set(dir(builtins)) == set()


def test_le_canal_lexical_l_appelle():
    for n in ast.walk(_arbre()):
        if isinstance(n, ast.FunctionDef) and n.name == "_scores_lexicaux":
            appels = {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            assert "requete_fts" in appels
            return
    raise AssertionError("_scores_lexicaux introuvable")
