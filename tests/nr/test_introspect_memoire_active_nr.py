"""NR — introspect porte la memoire de travail et lit les fiches `memory:` (geste 2b).

Mesures du 8/11 :
  - `forge_memoire_active.projeter` n'a qu'un appelant (`claude_inbox_tick`) : un
    client NON-Claude en session interactive n'a jamais la projection de la
    memoire de travail — Claude l'a a chaque tour. `introspect` doit la rendre.
  - les fiches `memory:` vivent dans `rag_chunks_fts`, que `rag_fts` (lu par la
    veille d'introspect) ne porte pas. `introspect` doit les lire AUSSI via
    `find_fiches`, requete INDEXEE (MATCH), jamais un balayage.

HERMETIQUE : aucun appel reseau, aucune base reelle — `projeter`/`rendre` et
`find_fiches` sont simules par monkeypatch ; index d'enquetes, oplog et base RAG
pointes sur des fichiers jetables de `tmp_path`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nokido_agent.app import forge_keeper_base as fkb  # noqa: E402
from nokido_agent.app import forge_memoire_active as fma  # noqa: E402
from app import forge_introspect as intro  # noqa: E402


@pytest.fixture()
def banc(tmp_path):
    """Index d'enquetes, oplog et base RAG jetables : introspect hors du disque reel."""
    return {
        "index": tmp_path / "enquetes.json",
        "oplog": tmp_path / "oplog.jsonl",
        "base": tmp_path / "absente.db",
    }


def test_memoire_active_presente(banc, monkeypatch):
    monkeypatch.setattr(fma, "projeter",
                        lambda intention, budget_chars=1200: {"texte": intention},
                        raising=False)
    monkeypatch.setattr(fma, "rendre", lambda proj: "PROJECTION::" + proj["texte"],
                        raising=False)
    res = intro.introspect("introspect memoire", 2000, index_enquetes=banc["index"],
                           oplog=banc["oplog"], base_rag=banc["base"])
    assert "memoire_active" in res, "introspect doit porter la memoire de travail"
    assert "PROJECTION::introspect memoire" in res["memoire_active"]


def test_projeter_leve_illisible(banc, monkeypatch):
    def _boom(intention, budget_chars=1200):
        raise RuntimeError("panne simulee")

    monkeypatch.setattr(fma, "projeter", _boom, raising=False)
    res = intro.introspect("introspect panne", 2000, index_enquetes=banc["index"],
                           oplog=banc["oplog"], base_rag=banc["base"])
    champ = res.get("memoire_active")
    assert isinstance(champ, str) and champ.startswith("<ILLISIBLE"), \
        "un echec nomme la cause, jamais silencieux, jamais une exception"
    assert "panne simulee" in champ


def test_fiches_memory_dans_reponse(banc, monkeypatch):
    motif = {}

    def _faux_find_fiches(pattern, *, limit=8, plafond_s=None):
        motif["pattern"] = pattern
        return [{"source": "memory:lecon-mesuree", "preview": "une lecon qui compte"}]

    monkeypatch.setattr(fkb, "find_fiches", _faux_find_fiches, raising=False)
    res = intro.introspect("lecon mesuree fiches", 2000, index_enquetes=banc["index"],
                           oplog=banc["oplog"], base_rag=banc["base"])
    assert "memory:lecon-mesuree" in str(res), \
        "une fiche memory: trouvee par find_fiches doit figurer dans la reponse"
    assert motif.get("pattern"), "find_fiches doit etre appele avec une requete FTS (MATCH), jamais un scan"
