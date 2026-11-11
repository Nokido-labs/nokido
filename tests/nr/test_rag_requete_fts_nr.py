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


def lexique_declare(noeud):
    """4/11 (owner, levier RSI « lexique ») : mots admis HORS de la question = ceux des VALEURS des dictionnaires
    LITTERAUX ecrits dans requete_fts (ex. {"plante": "exception error"}). Une chaine quelconque ne suffit pas : sinon
    tout mot invente passerait. Le lexique est du code visible, juge par la lockbox et le banc rappel_lexical."""
    mots = set()
    for n in ast.walk(noeud) if noeud is not None else []:
        if isinstance(n, ast.Dict):
            for v in n.values:
                vals = v.elts if isinstance(v, (ast.List, ast.Tuple, ast.Set)) else [v]
                for e in vals:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        mots |= {m.lower() for m in re.split(r"[\W_]+", e.value) if m}
    return mots


def contrat_viole(f, question, vocabulaire=frozenset()):
    """Motif de la premiere violation du contrat de requete_fts sur `question`, None si le contrat tient.
    `vocabulaire` : mots du lexique DECLARE dans la fonction (lexique_declare), admis en plus de la question."""
    expr = f(question)
    if not isinstance(expr, str):
        return "pas une chaine"
    termes = _termes(expr)
    if len(termes) > 15:
        return "plus de 15 termes"
    # 4/11 (owner) : sous-mots d'un snake_case ([\W_]+) et phrases "a b" admis, chaque mot venant de la question
    mots = ({m.lower() for m in re.split(r"\W+", question) if m}
            | {m.lower() for m in re.split(r"[\W_]+", question) if m} | set(vocabulaire))
    if any(any(w.lower() not in mots for w in t.split()) for t in termes if t):
        return "terme absent de la question"
    if expr:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        try:
            con.execute("SELECT * FROM t WHERE t MATCH ?", (expr,)).fetchall()
        except sqlite3.OperationalError as e:
            return "FTS5 refuse : %s" % e
    return None


def test_contrat_accepte_sous_mots_et_phrases():
    """Owner 4/11 (series localisation_code) : le contrat interdisait ce que les axes du banc demandent -- `_` est dans
    \\w, donc `_scores_lexicaux` restait UN mot et ses sous-mots (scores, lexicaux) etaient « absents de la question » ;
    une phrase FTS5 "a b" (axe ponderation) l'etait aussi. Sous-mots et phrases tires de la question sont admis ; un
    mot INVENTE reste refuse."""
    q = "forge_rag_engine.py et _scores_lexicaux"
    assert contrat_viole(lambda s: '"scores lexicaux" OR forge OR engine*', q) is None
    assert contrat_viole(lambda s: "inexistant OR forge", q) == "terme absent de la question"
    assert contrat_viole(lambda s: '"scores inventes"', q) == "terme absent de la question"


LEXIQUE_SRC = ('def requete_fts(question):\n'
               '    import re\n'
               '    LEXIQUE = {"plante": "exception error", "pouls": ["heartbeat"]}\n'
               '    mots = [w.lower() for w in re.split(r"\\W+", question or "") if len(w) > 3]\n'
               '    extra = []\n'
               '    for w in mots:\n'
               '        v = LEXIQUE.get(w, [])\n'
               '        extra += v.split() if isinstance(v, str) else list(v)\n'
               '    return " OR ".join((mots + extra)[:15])\n')


def test_contrat_admet_un_lexique_declare(tmp_path):
    fic = tmp_path / "lexique_essai.py"
    fic.write_text(LEXIQUE_SRC, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("lexique_essai", fic)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vocab = lexique_declare(ast.parse(LEXIQUE_SRC).body[0])
    assert {"exception", "error", "heartbeat"} <= vocab
    assert contrat_viole(mod.requete_fts, "le service plante sans pouls", vocab) is None
    assert contrat_viole(mod.requete_fts, "le service plante sans pouls") == "terme absent de la question"
    assert lexique_declare(ast.parse('def g(q):\n    return "invente OR " + q\n').body[0]) == set()


def test_contrat(tmp_path):
    f = _charger(tmp_path)
    vocab = lexique_declare(_fonction("requete_fts"))   # 4/11 : lexique declare dans la fonction, admis
    for q in QUESTIONS:
        assert contrat_viole(f, q, vocab) is None, (q, contrat_viole(f, q, vocab))
    assert f("") == ""
    assert f("a bc") == "" or contrat_viole(f, "a bc") is None


GAIN_Q = "Quel est le role du port dans le hub pour les clients with tokens"


def gain_rsi_tenu(f):
    """Le gain du 30/10 tient-il ? Lu comme FTS5 (guillemets et * retires, phrases decoupees) : owner 4/11 -- la forme
    (`port*`, `"role port"`) n'est pas le gain ; la PRESENCE des mots porteurs et l'ABSENCE des mots vides le sont."""
    mots = {w for t in _termes(f(GAIN_Q)) for w in t.split()}
    # mots vides compares A LA CASSE, comme le test d'origine (alpha garde « Quel » capitalise -- limite connue, pas
    # le contrat de ce gain) ; mots porteurs sans casse
    return not ({"pour", "dans", "quel", "with"} & mots) and {"port", "clients", "tokens"} <= {m.lower() for m in mots}


def test_le_gain_rsi_prouve_est_garde(tmp_path):
    """Candidat AMELIORE du banc rappel_lexical (29/10, rappel@10 0,609 -> 0,630 sur le mini-index fige), integre le
    30/10 apres jugement : les mots vides pour/dans/quel/with ne partent plus dans l'expression FTS."""
    assert gain_rsi_tenu(_charger(tmp_path))


def test_gain_rsi_lit_la_forme_fts5():
    assert gain_rsi_tenu(lambda q: '"role port" OR clients* OR tokens')       # serie 3 : refuse a tort
    assert not gain_rsi_tenu(lambda q: "pour OR port OR clients OR tokens")    # mot vide revenu
    assert not gain_rsi_tenu(lambda q: "port OR clients")                      # mot porteur perdu


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
