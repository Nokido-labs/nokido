"""NR -- journal d'usage du RAG, HORS base RAG (chantier LoRA retrieval, 2026-10-02).

bb:lora_signal_usage_cause_2026-10-02 : `query_log` n'a jamais porte `selected_chunk_id`,
`synaptic_feedback_log` n'a aucun ecrivain, et la base RAG doit cesser de recevoir des
ecritures. Ce NR fige, par le CHEMIN REEL (`ToolRegistry._rag_dense_search`, faux embedder
et faux reranker HTTP) :
  * une recherche s'inscrit dans un fichier JSONL, hors de toute base SQLite, top-1 en
    positif FAIBLE, scores du reranker alignes sur l'ordre rendu ;
  * un journal non inscriptible ne casse PAS la recherche, et le DIT ;
  * les triplets sont corrects sur un journal fabrique (FORT par citation, FAIBLE seulement
    avec des scores francs) ;
  * forge_mcp_registry ne recoit qu'UN appel, garde par un `except`.
"""
from __future__ import annotations

import ast
import json
import logging
import sqlite3
import time
from pathlib import Path

import pytest

from nokido_agent.app import forge_embed_router as fer
from nokido_agent.app import forge_rag_usage_signal as us

pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]


class _Rep:
    def __init__(self, d):
        self.d = d

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def journal(tmp_path, monkeypatch):
    j = tmp_path / "logs" / "rag_usage_signal.jsonl"
    monkeypatch.setattr(us, "JOURNAL", j)
    monkeypatch.setitem(us.PERTES, "n", 0)
    return j


@pytest.fixture
def registre(tmp_path, monkeypatch, journal):
    np = pytest.importorskip("numpy")
    # Le registre importe forge_spike_router, donc torch (pack ml) : absent du lot pur de la
    # CI, ce cas SAUTE en le disant. Sur le poste owner, il passe par le chemin reel.
    pytest.importorskip("torch", reason="forge_mcp_registry exige torch (pack ml)")
    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    reg = ToolRegistry.__new__(ToolRegistry)
    ids = ["c_vrai", "c_voisin", "c_loin"]
    mat = np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]], dtype=np.float32)
    reg._dense_cache = {"ts": time.time(), "ids": ids, "mat": mat, "idpos": None, "exts": None,
                        "meta": {c: {"source": "doc:nokido", "domain": "d", "text": "texte " + c}
                                 for c in ids}}
    reg.db_path = tmp_path / "rag.db"
    sqlite3.connect(reg.db_path).close()
    reg._rag_query_filter = lambda topic: {}
    reg._rag_multi_query = lambda t: [t]
    reg._reorder_mid = lambda out: out
    reg._dense_refresh_bg = lambda: None
    monkeypatch.setattr(fer, "declare_wanted", lambda *a, **k: True)   # pas de sandbox/ reel
    return reg


def _services(monkeypatch, scores=None):
    """Faux :8099 (embedding) et :8100 (rerank). `scores` par texte ; None = reranker muet."""
    def urlopen(req, timeout=None):
        url = req.full_url
        if ":8099/" in url:
            return _Rep({"data": [{"embedding": [1.0, 0.0], "index": 0}]})
        if ":8100/" in url:
            if scores is None:
                raise ConnectionRefusedError("reranker eteint")
            docs = json.loads(req.data)["documents"]
            return _Rep({"results": [{"index": i, "relevance_score": scores[d.split()[-1]]}
                                     for i, d in enumerate(docs)]})
        raise AssertionError("appel inattendu %s" % url)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def _entrees(j):
    return [json.loads(l) for l in j.read_text(encoding="utf-8").splitlines() if l.strip()]


# ── chemin reel ───────────────────────────────────────────────────────────────────────
def test_une_recherche_s_inscrit_hors_base_avec_scores_alignes(registre, journal, monkeypatch):
    _services(monkeypatch, {"c_vrai": 4.0, "c_voisin": 1.5, "c_loin": -6.0})
    out = registre._rag_dense_search("comment marche le coffre", 3)
    assert "c_vrai" in out
    (e,) = _entrees(journal)
    assert e["type"] == "recherche" and e["source"] == "handle_rag" and "+rerank" in e["mode"]
    assert e["ids"][0] == "c_vrai" and e["positif"] == "c_vrai" and e["force"] == us.FAIBLE
    assert dict(zip(e["ids"], e["scores"])) == {"c_vrai": 4.0, "c_voisin": 1.5, "c_loin": -6.0}
    # hors de toute base : le journal est du texte, et le module n'importe pas sqlite3
    assert journal.suffix == ".jsonl"
    src = ast.parse((RACINE / "app" / "forge_rag_usage_signal.py").read_text(encoding="utf-8"))
    importes = {a.name for n in ast.walk(src) if isinstance(n, ast.Import) for a in n.names}
    importes |= {n.module for n in ast.walk(src) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any("sqlite" in m for m in importes)


def test_sans_reranker_pas_de_scores_inventes(registre, journal, monkeypatch):
    _services(monkeypatch, None)
    registre._rag_dense_search("comment marche le coffre", 3)
    (e,) = _entrees(journal)
    assert e["scores"] is None and e["positif"] == "c_vrai"


def test_journal_non_inscriptible_ne_casse_pas_la_recherche_et_le_dit(registre, journal, monkeypatch,
                                                                    caplog, tmp_path):
    bloque = tmp_path / "bloque"
    bloque.write_text("un fichier, pas un dossier", encoding="utf-8")
    monkeypatch.setattr(us, "JOURNAL", bloque / "rag_usage_signal.jsonl")
    _services(monkeypatch, {"c_vrai": 4.0, "c_voisin": 1.5, "c_loin": -6.0})
    with caplog.at_level(logging.WARNING, logger="Nokido.RagUsage"):
        out = registre._rag_dense_search("comment marche le coffre", 3)
    assert "c_vrai" in out                                   # la recherche a rendu
    assert us.PERTES["n"] == 1 and "NON ECRIT" in caplog.text
    r = us.noter("q", ["a"])
    assert r["ok"] is False and r["pertes"] == 2


def test_le_registre_ne_recoit_qu_un_appel_garde():
    arbre = ast.parse((RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8"))
    appels = [n for n in ast.walk(arbre) if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "_noter_usage"]
    assert len(appels) == 1
    gardes = [t for t in ast.walk(arbre) if isinstance(t, ast.Try)
              and any(n is appels[0] for n in ast.walk(t))
              and any(getattr(h.type, "id", None) == "Exception" for h in t.handlers)]
    assert gardes, "l'appel au journal d'usage doit etre garde : il ne fait jamais echouer handle_rag"


# ── triplets sur un journal fabrique ──────────────────────────────────────────────────
def _fabriquer(j: Path, lignes):
    j.parent.mkdir(parents=True, exist_ok=True)
    j.write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lignes),
                 encoding="utf-8")


def test_triplets_fort_par_citation_et_faible_par_marge(journal):
    _fabriquer(journal, [
        {"type": "recherche", "id": "r1", "requete": "q1", "ids": ["a", "b", "c"],
         "scores": [5.0, 4.5, 1.0]},
        {"type": "citation", "ref": "r1", "chunk_id": "b", "force": "FORT"},
        {"type": "recherche", "id": "r2", "requete": "q2", "ids": ["x", "y", "z"],
         "scores": [5.0, 4.5, 1.0]},
        {"type": "recherche", "id": "r3", "requete": "q3", "ids": ["m", "n"], "scores": None},
        {"type": "citation", "ref": "inconnue", "chunk_id": "w", "force": "FORT"},
        "{ligne tronquee",
    ])
    r = us.triplets()
    par = {t["recherche"]: t for t in r["triplets"]}
    assert par["r1"] == {"requete": "q1", "positif": "b", "force": us.FORT,
                         "negatifs": ["a", "c"], "recherche": "r1"}
    # FAIBLE : y (4.5) est trop proche de x (5.0) pour etre un negatif ; z (1.0) l'est
    assert par["r2"]["positif"] == "x" and par["r2"]["negatifs"] == ["z"]
    assert "r3" not in par
    s = r["stats"]
    assert s["faibles_sans_scores"] == 1 and s["citations_orphelines"] == 1
    assert s["lignes_illisibles"] == 1
    assert [t["recherche"] for t in us.triplets(force_min=us.FORT)["triplets"]] == ["r1"]


def test_marquer_cite_puis_triplet_fort(journal):
    rid = us.noter("comment reconstruire l index", ["p", "q", "r"], [1.0, 0.9, 0.8])["id"]
    assert us.marquer_cite(rid, "q", par="extracteur")["ok"] is True
    assert us.marquer_cite("", "q")["ok"] is False
    (t,) = us.triplets()["triplets"]
    assert t["positif"] == "q" and t["force"] == us.FORT and t["negatifs"] == ["p", "r"]


def test_rotation_bornee(journal, monkeypatch):
    monkeypatch.setattr(us, "MAX_OCTETS", 300)
    monkeypatch.setattr(us, "ARCHIVES", 2)
    for i in range(40):
        assert us.noter("requete %d" % i, ["a", "b"], [2.0, 1.0])["ok"] is True
    fichiers = sorted(p.name for p in journal.parent.iterdir())
    assert fichiers == ["rag_usage_signal.jsonl", "rag_usage_signal.jsonl.1",
                        "rag_usage_signal.jsonl.2"]
    assert all(p.stat().st_size < 1000 for p in journal.parent.iterdir())
