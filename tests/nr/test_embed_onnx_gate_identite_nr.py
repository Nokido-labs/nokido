# -*- coding: utf-8 -*-
"""NR — le gate d'identite du chemin ONNX ne fabrique ni fausse panne ni fausse cause.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du gate d'identite d'espace vectoriel"

Trois regressions PAYEES le 2026-09-06, dans cet ordre, en une demi-heure :

1. `embed_parallel` a rendu huit vecteurs VIDES (chemin en process eteint, backends
   distants tous KO) et la sonde a conclu « l'export ne sert PAS le meme espace » avec
   un cos de 0,0. Un vecteur ABSENT n'est pas un vecteur DIFFERENT.
2. Le module chargeait le modele en LOCAL et le tokenizer par NOM DE DEPOT
   (`BAAI/bge-m3`) : sous un compte sans egress, `OSError` -> tout le chemin ONNX
   paraissait mort alors que les fichiers tokenizer sont sur disque a cote du modele.
3. Session enfin chargee, cos = 0,69 UNIFORME sur huit textes sans rapport. La sonde a
   ecrit « ne sert PAS le meme espace » : un gate non franchi est un FAIT, mais la CAUSE
   ne se deduit pas du cosinus -- une valeur elevee et uniforme designe une transformation
   systematique, pas un autre modele.

Ces tests lisent le CODE seul (commentaires et docstrings retires) : le motif « un
instrument lit son propre vocabulaire » a deja ete paye six fois sur ce depot.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

OUTIL = ROOT / "tools" / "forge_embed_onnx_mesure.py"
MODULE = ROOT / "app" / "forge_bge_m3_shared.py"
COMMUN = ROOT / "tools" / "forge_embed_lot_commun.py"


def _code_seul(chemin: Path) -> str:
    """Source privee de ses commentaires et de ses chaines de documentation."""
    src = chemin.read_text(encoding="utf-8")
    sortie = []
    precedent = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and precedent in (
                tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT):
            continue  # docstring
        sortie.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            precedent = tok.type
    return " ".join(sortie)


@pytest.fixture(scope="module")
def vi():
    import forge_embed_onnx_mesure as m

    return m


def test_vecteurs_absents_donnent_indetermine_jamais_echec(vi):
    """Huit vecteurs vides : la mesure n'a pas eu lieu, ce n'est pas un espace different."""
    verdict, raison, extras = vi.verdict_identite(
        [[] for _ in range(8)], [[0.1] * 1024 for _ in range(8)],
        {"inprocess_enabled": False, "session_loaded": False})
    assert verdict == "INDETERMINE", f"attendu INDETERMINE, obtenu {verdict}"
    assert extras["vecteurs_servis"] == 0
    assert "espace" not in raison.lower(), (
        "la raison ne doit RIEN affirmer sur l'espace vectoriel : rien n'a ete mesure")


def test_vecteurs_tous_nuls_donnent_indetermine(vi):
    """Session declaree chargee mais vecteurs nuls : toujours INDETERMINE."""
    verdict, _r, extras = vi.verdict_identite(
        [[0.0] * 1024 for _ in range(4)], [[0.1] * 1024 for _ in range(4)],
        {"session_loaded": True})
    assert verdict == "INDETERMINE"
    assert extras["vecteurs_servis"] == 0


def test_identite_confirmee_donne_ok(vi):
    """Vecteurs identiques aux references : cos 1,0 -> OK."""
    refs = [[float(i % 7) + 1.0 for i in range(1024)] for _ in range(3)]
    verdict, raison, extras = vi.verdict_identite(
        [list(v) for v in refs], refs, {"session_loaded": True})
    assert verdict == "OK", raison
    assert extras["cos_moyen"] >= vi.COS_MINIMUM


def test_gate_non_franchi_ne_deduit_jamais_la_cause(vi):
    """cos eleve et UNIFORME : ECHEC du gate, mais la cause reste INDETERMINEE."""
    import math
    import random

    rnd = random.Random(1789)
    produits, refs = [], []
    for _ in range(8):
        base = [rnd.gauss(0, 1) for _ in range(1024)]
        bruit = [b * 0.72 + rnd.gauss(0, 0.55) for b in base]
        refs.append(base)
        produits.append(bruit)
    verdict, raison, extras = vi.verdict_identite(produits, refs, {"session_loaded": True})
    assert verdict == "ECHEC", f"cos moyen {extras.get('cos_moyen')}"
    assert "INDETERMINEE" in raison, (
        "un gate non franchi ne doit pas affirmer sa cause : " + raison)
    assert not math.isnan(extras["cos_moyen"])
    assert "cos_etendue" in extras, "l'etendue doit etre publiee, elle porte l'indice"


def test_l_outil_allume_explicitement_le_chemin_qu_il_mesure():
    """Sans LAFORGE_BGE_M3_INPROCESS=1, la sonde mesure une delegation, pas ONNX."""
    code = _code_seul(OUTIL)
    assert "LAFORGE_BGE_M3_INPROCESS" in code, (
        "l'outil doit poser le drapeau dans son CODE, pas seulement le documenter")


def test_le_tokenizer_local_prime_sur_le_depot_distant():
    """Le tokenizer est sur disque : le charger par nom de depot casse hors ligne."""
    arbre = ast.parse(MODULE.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(arbre)
               if isinstance(n, ast.FunctionDef) and n.name == "_get_tokenizer"), None)
    assert fn is not None, "_get_tokenizer a disparu"
    essais = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert essais, "le chargement local doit etre TENTE avant tout repli distant"
    mots = {kw.arg for n in ast.walk(essais[0]) if isinstance(n, ast.Call)
            for kw in n.keywords}
    assert "local_files_only" in mots, (
        "la premiere tentative doit etre strictement locale (local_files_only=True)")


def test_la_tete_de_pooling_par_defaut_est_cls():
    """La tete decide de l'ESPACE. Mesure 2026-09-06 : cls -> cos 1,0 contre la base,
    mean -> 0,6913. Un retour a la moyenne ecrirait des vecteurs hors espace SANS erreur.

    Verifie par AST sur la valeur par defaut reellement compilee, pas sur un commentaire.
    """
    arbre = ast.parse(MODULE.read_text(encoding="utf-8"))
    defaut = None
    for n in ast.walk(arbre):
        if not isinstance(n, ast.AnnAssign) or not isinstance(n.target, ast.Name):
            continue
        if n.target.id != "POOLING" or n.value is None:
            continue
        for c in ast.walk(n.value):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                    and c.func.attr == "get" and len(c.args) == 2 \
                    and isinstance(c.args[1], ast.Constant):
                defaut = c.args[1].value
    assert defaut == "cls", (
        f"la tete de pooling par defaut doit rester 'cls', trouvee {defaut!r}")


def test_le_pooling_est_compare_et_non_suppose():
    """La sonde mesure les DEUX tetes : une cause etablie vaut mieux qu'une cause deduite.

    Verifie par AST : `_code_seul` rejoint les jetons avec des espaces, donc y chercher
    une chaine litterale comme `"mean", "cls"` echoue sur du code pourtant correct. La
    structure se lit dans l'arbre, jamais dans du texte reassemble.
    """
    arbre = ast.parse(OUTIL.read_text(encoding="utf-8"))
    trouve = False
    for n in ast.walk(arbre):
        if isinstance(n, ast.For) and isinstance(n.iter, (ast.Tuple, ast.List)):
            valeurs = {e.value for e in n.iter.elts if isinstance(e, ast.Constant)}
            if {"mean", "cls"} <= valeurs:
                trouve = True
    assert trouve, "la sonde doit comparer les deux tetes sur une seule charge de session"


def test_la_lecture_reste_bornee_par_rowid():
    """Pas de LENGTH(text) BETWEEN : non indexable, il balaie une base de 24,9 Go.

    La lecture vit dans la brique COMMUNE depuis le 2026-09-06 : deux outils de mesure
    en portaient une copie et le cliquet de duplication les a attrapes. Le test suit le
    code -- il garde l'endroit ou la primitive vit reellement, pas celui ou elle vivait.
    """
    code = _code_seul(COMMUN)
    assert "rowid > ?" in code, "la selection doit rester bornee par rowid"
    assert "LENGTH(text) BETWEEN" not in code, (
        "predicat non indexable : il a deja couche le hub trois fois")
    assert "LENGTH(text) BETWEEN" not in _code_seul(OUTIL), (
        "la sonde ne doit pas reintroduire le predicat non indexable")


def test_la_sonde_ne_reintroduit_pas_une_copie_du_commun():
    """Anti-dup : le cosinus et l'echantillonneur viennent du commun, jamais recopies."""
    import ast

    arbre = ast.parse(OUTIL.read_text(encoding="utf-8"))
    definis = {n.name for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)}
    assert "_echantillon_vectorise" not in definis, (
        "l'echantillonneur appartient a forge_embed_lot_commun")
    # ⚠️ 2026-09-10 — cet oracle comparait `n.module == "forge_embed_lot_commun"`,
    # le nom d'AVANT la migration vers le namespace `nokido_agent`. L'import n'a
    # pas bouge ; c'est la comparaison qui a vieilli, et elle rendait `importes`
    # VIDE — donc une consommation du commun parfaitement intacte se lisait comme
    # une recopie. Le codemod refuse cette forme (`{...} <= importes`) a dessein :
    # elle se corrige a la main, en VISANT le chemin du jour.
    COMMUN_MODULE = "nokido_agent.tools.forge_embed_lot_commun"
    importes = {alias.asname or alias.name
                for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)
                and n.module == COMMUN_MODULE for alias in n.names}
    assert {"_cos", "echantillon_vectorise"} <= importes, (
        f"la sonde doit consommer le commun, importes = {sorted(importes)}")
