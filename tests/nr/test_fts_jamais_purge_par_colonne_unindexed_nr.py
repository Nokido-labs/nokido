"""NR cliquet — aucune purge de `rag_fts` par une colonne UNINDEXED, nulle part.

`rag_fts` est `fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)`.
`DELETE FROM rag_fts WHERE chunk_id=?` (ou `source=?`) est donc un BALAYAGE COMPLET
de l'index lexical, verrou d'ecriture de la base RAG tenu du debut a la fin :

  - 2026-09-23 : 6,2 Go lus / 2 min 44 s par commit (forge_module_cards, post-commit) ;
  - 2026-09-27 : l'audit NREM1 en enchainait 17 -> verrou ~1 h chaque soir a 22 h,
    hub fige 2 614 s sur l'heure ; corrige, l'audit tient le verrou 0 s sur 145.

Le motif a ete corrige TROIS fois, site par site, et revenait ailleurs. Ce test le
ferme pour tout le depot : la seule forme admise passe par
`forge_db_path.purger_fts` (MATCH sur une phrase de l'ANCIEN texte, id en filtre).

On lit l'AST : seuls les arguments de `execute` / `executemany` comptent. Les
docstrings et commentaires qui CITENT le motif pour l'expliquer ne sont pas des
usages (un instrument ne lit jamais son propre vocabulaire).

EXCEPTIONS, chacune motivee :
  - purge d'un DOMAINE entier en une seule requete (`WHERE domain=...`) : UN balayage
    pour des milliers de lignes vaut mieux que des milliers de MATCH ; outil ponctuel.
    Le motif ci-dessous ne vise pas `domain`, c'est voulu.
  - `EXCEPTIONS` ci-dessous : meme raison, par fichier (les numeros de ligne bougent).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + ast (l.47)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
ZONES = ("app", "tools")
EXCEPTIONS = {
    # purge d'un PREFIXE de source en UNE requete (`chunk_id IN (sous-requete)`) :
    # un balayage pour N lignes, outil lance a la main par l'owner, duree mesuree
    # dans son propre rapport (`fts_secondes`).
    "tools/forge_veille_purge.py",
}
_PURGE_PAR_CLE = re.compile(
    r"DELETE\s+FROM\s+rag_fts\s+WHERE\s+(chunk_id|source|id)\s*(=|IN\b|LIKE\b|GLOB\b)", re.I)


def _sites():
    trouves = []
    for zone in ZONES:
        for f in sorted((RACINE / zone).rglob("*.py")):
            if "__pycache__" in f.parts or "_attic" in f.parts:
                continue
            if f.relative_to(RACINE).as_posix() in EXCEPTIONS:
                continue
            try:
                arbre = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(arbre):
                if not (isinstance(n, ast.Call) and n.args
                        and getattr(n.func, "attr", None) in ("execute", "executemany")):
                    continue
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and _PURGE_PAR_CLE.search(a.value):
                    trouves.append("%s:%d" % (f.relative_to(RACINE).as_posix(), n.lineno))
    return trouves


def test_aucune_purge_rag_fts_par_colonne_unindexed():
    sites = _sites()
    assert not sites, (
        "purge de rag_fts par colonne UNINDEXED = BALAYAGE COMPLET sous verrou "
        "d'ecriture (hub fige chaque soir a 22 h, 2026-09-27). Passer par "
        "forge_db_path.purger_fts(con, [(chunk_id, ancien_texte)]) -- ancien texte lu "
        "par cle primaire dans rag_chunks AVANT de le remplacer ou supprimer.\n  "
        + "\n  ".join(sites))


def test_le_capteur_voit_le_motif():
    """Anti-faux-vert : le capteur doit MORDRE sur la forme interdite."""
    src = 'con.execute("DELETE FROM rag_fts WHERE chunk_id=?", (c,))'
    n = ast.parse(src).body[0].value
    assert _PURGE_PAR_CLE.search(n.args[0].value)
    assert not _PURGE_PAR_CLE.search(
        "DELETE FROM rag_fts WHERE rowid IN (SELECT rowid FROM rag_fts "
        "WHERE rag_fts MATCH ? AND chunk_id = ?)"), "la forme ADMISE ne doit pas mordre"
