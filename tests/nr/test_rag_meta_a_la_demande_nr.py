# -*- coding: utf-8 -*-
"""NR -- en mode dense DELEGUE au sidecar, le hub ne recharge plus le texte de tout le corpus (owner 2026-10-19 :
« disque toujours a 100 % et ram a plus de 80 % »).

RCA AGY 6aacc26fe, recoupee sur pieces : `_load_dense_cache` (forge_mcp_registry) relit, meme quand Qdrant porte
le dense, `SELECT id, source, domain, text, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL` -- 1,15 M
lignes de %NOKIDO_DATA%\\embeddings.db (46,5 Go) : 10 min 35 s a ~93 Mo/s au boot du 19/10 14:04, RSS du hub 0,30 -> 2,19 Go,
puis `_rendre_cache_dense` jette tout a 14:15:43. Le journal du jour montre ce cycle charger -> rendre SEPT fois
(00:49, 02:29, 02:47, 03:42, 05:35, 11:29, 14:15) : chaque recherche qui suit un rendu relit le corpus. Le
commentaire d'origine (« 264 Mo, pas 4,7 Go ») datait d'un corpus deux fois plus petit.

Contrat :
  1. en mode delegue, `_load_dense_cache` garde ids / exts / folders mais AUCUN texte : la meta du cache ne porte
     pas de champ `text` (le texte n'est lu que pour les resultats) ;
  2. `_meta_par_ids(ids)` rend {id: {source, domain, text[:512]}} par requete indexee sur la cle, pour les seuls ids
     demandes ; un id absent de la base est ABSENT du resultat (jamais une meta vide inventee) ;
  3. le chemin de recherche dense s'en sert pour le top-K.
Le mode local (matrice en RAM) n'est pas touche.
"""
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mcp_registry as reg  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def _classe():
    for _nom, obj in inspect.getmembers(reg, inspect.isclass):
        if obj.__module__ == reg.__name__ and "_load_dense_cache" in obj.__dict__:
            return obj
    pytest.fail("aucune classe de forge_mcp_registry ne porte _load_dense_cache")


class _Faux:
    def __init__(self, db):
        self.db_path = db
        self._sidecar_attente_faite = True

    def _sidecar_dense_actif(self):
        return True, "delegue au sidecar (test)"


@pytest.fixture()
def base(tmp_path):
    db = tmp_path / "e.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
              "ext TEXT, folder TEXT, embedding BLOB)")
    lignes = [("c%d" % i, "src%d" % i, "dom", "texte %d " % i + "x" * 900, ".py", "app",
               b"\x00" * 4096 if i != 3 else None) for i in range(6)]
    c.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?,?)", lignes)
    c.commit()
    c.close()
    return db


def test_le_cache_delegue_ne_porte_aucun_texte(base):
    cache = _classe()._load_dense_cache(_Faux(base))
    assert cache["ids"] == ["c0", "c1", "c2", "c4", "c5"]       # meme filtre embedding IS NOT NULL
    assert len(cache["exts"]) == len(cache["folders"]) == 5
    assert cache["mat"].shape[0] == 0                            # sentinelle de delegation inchangee
    assert not any("text" in (m or {}) for m in cache["meta"].values()), "texte charge pour tout le corpus"


def test_meta_a_la_demande_pour_les_seuls_ids_demandes(base):
    meta = _classe()._meta_par_ids(_Faux(base), ["c2", "c5", "inconnu"])
    assert set(meta) == {"c2", "c5"}
    assert meta["c2"]["source"] == "src2" and meta["c2"]["domain"] == "dom"
    assert meta["c2"]["text"].startswith("texte 2") and len(meta["c2"]["text"]) == 512


def test_la_recherche_dense_lit_la_meta_a_la_demande():
    src = inspect.getsource(reg)
    i = src.find("def _rag_dense_search")
    assert i >= 0, "_rag_dense_search introuvable"
    j = src.find("\n    def ", i + 10)
    assert "_meta_par_ids" in src[i:j if j > 0 else None]
