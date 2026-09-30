"""Non-régression : un terme à tiret ne doit pas rendre les index ILLISIBLES.

Mesuré le 2026-09-12, en cherchant ce que faisaient six skills : `balayer(
"forge-core")` a rendu **`verdict: PRESENT`** alors que ses DEUX index étaient
`illisible` — `OperationalError: no such column: core`.

La cause : le terme part brut dans `MATCH ?`, donc FTS5 l'interprète comme une
**requête** (avec sa syntaxe : colonnes, opérateurs, préfixes) et non comme du
texte à chercher. Un simple tiret suffit.

⚠️ Ce qui rend le défaut coûteux n'est pas l'erreur, c'est le VERDICT. L'outil
existe précisément pour empêcher de conclure à une absence sans avoir regardé —
et il rendait un verdict rassurant sur deux surfaces qu'il n'avait pas pu lire.
C'est le motif qu'il combat, retourné contre lui.

⚠️ La sémantique multi-mots ne doit PAS changer au passage : `balayer("forge
web")` cherche `forge` ET `web` (AND implicite de FTS5). Quoter le terme entier
en ferait une phrase exacte et raterait des documents que l'ancienne forme
trouvait — on échangerait un faux négatif contre un autre.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _mod():
    import forge_retrieval_sweep  # type: ignore

    return forge_retrieval_sweep


def _base(tmp_path: Path) -> Path:
    """Une vraie base au schéma réel : le défaut est dans le dialecte SQL, une
    table factice au mauvais schéma ne le reproduirait pas."""
    p = tmp_path / "mini.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(text, source)")
    con.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source)")
    for t in ("rag_fts", "rag_chunks_fts"):
        con.execute("INSERT INTO %s(text, source) VALUES(?,?)" % t,
                    ("le skill forge-core agrege une knowledge base", "skill:forge-core"))
        con.execute("INSERT INTO %s(text, source) VALUES(?,?)" % t,
                    ("forge et web dans la meme phrase", "doc:web"))
    con.commit()
    con.close()
    return p


def test_un_terme_a_tiret_ne_rend_pas_les_index_illisibles(tmp_path, monkeypatch):
    """Le cœur. Avant correctif : `no such column: core` sur les deux index."""
    m = _mod()
    base = _base(tmp_path)
    monkeypatch.setattr(m, "_db", lambda: base, raising=False)

    surfaces = m._fts("forge-core")
    illisibles = [s for s in surfaces if s.get("etat") == "illisible"]
    assert not illisibles, (
        "un terme a tiret casse la requete FTS5 : %s"
        % [(s["surface"], s.get("raison")) for s in illisibles]
    )
    lexicales = [s for s in surfaces if s["surface"] in ("rag_fts", "rag_chunks_fts")]
    assert lexicales and all(s.get("n_total") for s in lexicales), (
        "le terme existe dans la base et n'est pas trouve : %s" % lexicales
    )


def test_la_semantique_multi_mots_est_preservee(tmp_path, monkeypatch):
    """Deux mots restent un ET, pas une phrase exacte — sinon on echange un faux
    negatif contre un autre."""
    m = _mod()
    base = _base(tmp_path)
    monkeypatch.setattr(m, "_db", lambda: base, raising=False)

    surfaces = m._fts("forge web")
    lexicales = [s for s in surfaces if s["surface"] in ("rag_fts", "rag_chunks_fts")]
    assert lexicales, surfaces
    assert all(s.get("etat") != "illisible" for s in lexicales), lexicales
    assert all(s.get("n_total") for s in lexicales), (
        "« forge web » ne trouve plus le document qui contient les deux mots "
        "separement : la requete est devenue une phrase exacte (%s)" % lexicales
    )


def test_un_terme_a_syntaxe_FTS_ne_fait_pas_planter(tmp_path, monkeypatch):
    """Les guillemets et operateurs sont du TEXTE, pas de la syntaxe."""
    m = _mod()
    base = _base(tmp_path)
    monkeypatch.setattr(m, "_db", lambda: base, raising=False)

    for terme in ('forge "core"', "forge OR", "forge*", "(forge)", 'a"b'):
        surfaces = m._fts(terme)
        casses = [s for s in surfaces if s.get("etat") == "illisible"]
        assert not casses, (
            "le terme %r casse la requete : %s"
            % (terme, [(s["surface"], s.get("raison")) for s in casses])
        )


def test_un_verdict_ne_se_rend_pas_sur_des_surfaces_illisibles(tmp_path, monkeypatch):
    """Le vrai defaut mesure : `PRESENT` annonce alors que les deux index
    n'avaient pas pu etre lus. Un verdict doit dependre de ce qu'on a LU."""
    m = _mod()
    surfaces = [
        {"surface": "rag_fts", "etat": "illisible", "raison": "x"},
        {"surface": "rag_chunks_fts", "etat": "illisible", "raison": "x"},
        {"surface": "docs", "etat": "vide"},
    ]
    v = m.verdict_global(surfaces)
    assert v != "ABSENT", "des surfaces illisibles ne prouvent aucune absence"
    assert v in ("INDETERMINE", "INDÉTERMINÉ"), (
        "verdict « %s » sur deux index ILLISIBLES : c'est le faux calme que cet "
        "outil existe pour empecher" % v
    )
