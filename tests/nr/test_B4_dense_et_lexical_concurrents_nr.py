"""Non-régression B4 : le canal lexical n'attend pas le canal dense.

Item de veille B4 : « paralléliser dense et lexical ». Mesure dans
`RAGEngine.search` avant correctif — trois attentes **en file**, alors que
seules les deux premières sont liées :

    qe        = await self.get_embeddings([query])      # réseau (embedder)
    embs,sims = await asyncio.to_thread(_vec_sims)      # dense — a besoin de qe
    bm_scores = await asyncio.to_thread(_lexical)       # lexical — n'a besoin de RIEN

`_lexical` ne lit que `query` et `self.chunks`. Il ne touche ni `qv`, ni
`embs`, ni `sims`. Il était pourtant lancé **après** que l'embedder ait répondu
et que le produit scalaire soit fini.

POURQUOI CELA COMPTE PLUS QUE LES QUELQUES MILLISECONDES DE FTS5. Le poste
coûteux n'est pas le lexical (sqlite, hors GIL, ~2-4 ms) : c'est l'appel réseau
à l'embedder, puis la similarité. Or le dépôt a mesuré que ce canal dense
**tombe** — sidecar injoignable, zéro embedding en RAM, backends d'embedding
indisponibles. Quand le dense rame ou expire, l'ancien ordre faisait attendre
le seul canal qui, lui, répondait. Le lexical PRIME : il ne doit dépendre de
personne.

⚠️ CE QUE CE TEST NE PROUVE PAS, et qu'il ne faut pas lui faire dire : il ne
mesure aucun gain de latence en production. Il prouve le **recouvrement** —
que le lexical a commencé avant la fin de l'embedding. Annoncer un gain
chiffré demanderait un banc, pas un test.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

_ATTENTE_EMBED = 0.30  # marge large : le verdict ne doit pas dependre de l'ordonnanceur


def _mod():
    import forge_rag_engine  # type: ignore

    return forge_rag_engine


def _base_minimale(chemin: Path) -> None:
    """Une VRAIE base au schéma réel : `_lexical` fait un JOIN sur `rowid`, une
    table factice ne prouverait que ma lecture du schéma."""
    con = sqlite3.connect(str(chemin))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, "
                "text TEXT, domain TEXT)")
    con.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text)")
    for i in range(4):
        con.execute("INSERT INTO rag_chunks(id, source, text, domain) VALUES(?,?,?,?)",
                    (f"c{i}", f"doc{i}.md", f"alignement corrigibilite agent {i}", "test"))
        con.execute("INSERT INTO rag_chunks_fts(rowid, text) VALUES(?,?)",
                    (i + 1, f"alignement corrigibilite agent {i}"))
    con.commit()
    con.close()


def _moteur(mod, horloge: dict):
    """Instance minimale — `__new__` pour ne pas payer le chargement du corpus."""
    eng = mod.RAGEngine.__new__(mod.RAGEngine)
    eng.chunks = [{"id": f"c{i}", "source": f"doc{i}.md",
                   "text": f"alignement corrigibilite agent {i}",
                   "embedding": None, "domain": "test"} for i in range(4)]
    eng.bm25_index = None
    eng.session_ctxs = {}
    eng.build_bm25 = lambda: None
    eng._bump_access = lambda ids: None

    async def _embeddings_lents(textes):
        horloge["embed_debut"] = time.monotonic()
        await asyncio.sleep(_ATTENTE_EMBED)
        horloge["embed_fin"] = time.monotonic()
        return [None]  # embedding indisponible : le dense se replie, l'attente a eu lieu

    eng.get_embeddings = _embeddings_lents
    return eng


def test_le_lexical_demarre_avant_la_fin_de_l_embedding(tmp_path, monkeypatch):
    """Le cœur de B4. Si le premier accès sqlite du canal lexical a lieu APRÈS
    que l'embedder ait rendu la main, les deux canaux sont en file."""
    mod = _mod()
    base = tmp_path / "mini.db"
    _base_minimale(base)
    monkeypatch.setattr(mod, "_EMBEDDINGS_DB", str(base), raising=False)

    horloge: dict = {}
    vrai_connect = sqlite3.connect

    def _connect_horodate(*a, **k):
        horloge.setdefault("lexical_debut", time.monotonic())
        return vrai_connect(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", _connect_horodate)

    eng = _moteur(mod, horloge)
    docs = asyncio.run(eng.search("alignement corrigibilite agent", k=2,
                                  rerank=False, compress=False))

    assert "lexical_debut" in horloge, (
        "le canal lexical n'a jamais ouvert la base : le test ne mesure rien"
    )
    assert "embed_fin" in horloge, "l'embedder stub n'a pas ete appele"
    assert horloge["lexical_debut"] < horloge["embed_fin"], (
        "le lexical a demarre %.0f ms APRES la fin de l'embedding : les deux "
        "canaux sont en file alors qu'ils sont independants"
        % ((horloge["lexical_debut"] - horloge["embed_fin"]) * 1000)
    )
    assert isinstance(docs, list)


def test_la_recherche_rend_toujours_ses_resultats(tmp_path, monkeypatch):
    """Le parallélisme ne vaut rien s'il change le résultat. Le canal dense est
    muet ici (aucun embedding) : le lexical doit rendre seul, comme avant."""
    mod = _mod()
    base = tmp_path / "mini.db"
    _base_minimale(base)
    monkeypatch.setattr(mod, "_EMBEDDINGS_DB", str(base), raising=False)

    eng = _moteur(mod, {})
    docs = asyncio.run(eng.search("alignement corrigibilite", k=3,
                                  rerank=False, compress=False))
    assert docs, "aucun document rendu alors que le lexical a des hits"
    assert all("content" in d and "score" in d for d in docs), docs


def test_un_lexical_qui_leve_ne_tue_pas_la_recherche(tmp_path, monkeypatch):
    """Une tâche concurrente qui lève doit être RÉCUPÉRÉE, pas laissée en
    exception jamais attendue — sinon la recherche meurt là où elle se
    repliait, et asyncio se contente d'un « exception was never retrieved »
    dans un journal que personne ne lit."""
    mod = _mod()
    base = tmp_path / "mini.db"
    _base_minimale(base)
    monkeypatch.setattr(mod, "_EMBEDDINGS_DB", str(base), raising=False)

    def _connect_casse(*a, **k):
        raise sqlite3.OperationalError("base injoignable (simule)")

    monkeypatch.setattr(sqlite3, "connect", _connect_casse)

    eng = _moteur(mod, {})
    docs = asyncio.run(eng.search("alignement corrigibilite", k=2,
                                  rerank=False, compress=False))
    assert isinstance(docs, list), (
        "une panne du canal lexical a propage jusqu'a l'appelant : le repli "
        "existait avant la mise en concurrence, il doit survivre"
    )
