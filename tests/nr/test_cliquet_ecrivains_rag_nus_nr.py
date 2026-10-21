"""NR 18/10 -- cliquet des ECRIVAINS NUS du RAG (decision owner, item veille_watch_alerts_gate_denied, C_06b-2/3).

Cartographie du 18/10 (AGY, reclassee par AST) : 146 sites ecrivent dans rag_chunks / rag_fts ; 56 passent par
le chemin gouverne (write_retry / ecrire_chunk / open_writer / anchor_*), 90 par une connexion nue. Owner : figer le
compte (aucun nouvel ecrivain nu) et migrer app/ par lots. Ce NR ne laisse le compte que DESCENDRE : apres chaque
migration, abaisser PLAFOND a la valeur mesuree (le message d'echec la donne).

Un ecrivain est GOUVERNE si la fonction qui le contient (AST) appelle l'un des chemins gouvernes. Le NR exclut
tests/ et sa propre source : un instrument ne lit jamais son propre vocabulaire.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOTIF = re.compile(r"INSERT\s+(?:OR\s+(?:REPLACE|IGNORE)\s+)?INTO\s+rag_(?:chunks|fts)\b", re.I)
GOUVERNES = ("write_retry(", "ecrire_chunk(", "open_writer(", "anchor_solution(", "anchor_error(")
CANONIQUES = {"ecrire_chunk", "write_retry", "anchor_solution", "anchor_error"}
# Mesure du 18/10 PAR CET INSTRUMENT (une entree par instruction INSERT, d'ou 40/73 contre les 34/56 SITES de la
# cartographie AGY) ; ne fait que descendre.
# Lot 2 migre le 18/10 (4 modules app/, 4 INSERT ; livraison OPENCODE_GPTOSS 38e25d514 relue) : 32 -> 28.
PLAFOND = {"app": 28, "tools": 73}   # lot 1 migre (18/10) : conversation_logger, git_historian, skill_curator, extern_patterns


def _nus(dossier: str) -> list[str]:
    nus = []
    for f in sorted((ROOT / dossier).rglob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if "/_attic/" in rel or "__pycache__" in rel:
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        if not MOTIF.search(src):
            continue
        try:
            arbre = ast.parse(src)
        except SyntaxError:
            nus.append(rel + ":ILLISIBLE")
            continue
        fonctions = [n for n in ast.walk(arbre) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for m in MOTIF.finditer(src):
            ligne = src.count("\n", 0, m.start()) + 1
            englobe = [n for n in fonctions if n.lineno <= ligne <= (n.end_lineno or n.lineno)]
            fn = max(englobe, key=lambda n: n.lineno) if englobe else None
            if fn is not None and fn.name in CANONIQUES:
                continue
            corps = ast.get_source_segment(src, fn) if fn is not None else src
            if not any(g in (corps or "") for g in GOUVERNES):
                nus.append("%s:%d" % (rel, ligne))
    return nus


def test_aucun_nouvel_ecrivain_nu_dans_app():
    nus = _nus("app")
    assert len(nus) <= PLAFOND["app"], (
        "%d ecrivains nus dans app/ (plafond %d) -- un nouveau passe par une connexion nue : le faire passer "
        "par forge_db_path.write_retry/ecrire_chunk. Sites : %s" % (len(nus), PLAFOND["app"], nus))


def test_aucun_nouvel_ecrivain_nu_dans_tools():
    nus = _nus("tools")
    assert len(nus) <= PLAFOND["tools"], (
        "%d ecrivains nus dans tools/ (plafond %d). Sites : %s" % (len(nus), PLAFOND["tools"], nus))


def test_l_instrument_voit_des_ecrivains():
    """Garde de l'instrument : un motif casse rendrait les deux cliquets verts sur une absence."""
    assert _nus("app") or _nus("tools"), "aucun ecrivain vu : le motif ou le parse est casse, pas un vert"
