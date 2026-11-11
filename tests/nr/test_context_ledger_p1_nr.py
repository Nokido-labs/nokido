# -*- coding: utf-8 -*-
"""NR RED -- P1 du contexte servi (tour 3 tranche par l'owner le 2026-11-08) : HYBRIDE FTS5 + PPR.

Contrat ajoute a app/forge_context_ledger.py (base sous <racine>/sandbox, jamais embeddings.db) :

  essence enrichie   ToolRegistry._archive_blob(text, agent, label) n'indexe plus le label seul :
                     essence = "<label>:" + premiere ligne non vide du texte, CAVIARDEE
                     (forge_secret_guard / redact), <= 150 car. Deux archives differentes
                     n'ont plus la meme essence.
  contexte d'appel   observer(uri, essence="", racine=None, task_id=None, session=None, agent=None)
                     range task_id/session/agent dans meta (JSON).
  arcs               table context_arcs(src TEXT, dst TEXT, type TEXT) ; indexer() cree un arc
                     type "meme_tache" entre deux pointeurs de meme task_id (les deux sens) ;
                     purger_pointeurs_morts() supprime en cascade les arcs d'un pointeur purge.
  selection          table FTS5 context_fts sur les essences = graines ; expansion par
                     forge_graph_ppr.ppr sur les arcs ; score x scorecard (meta.grade :
                     OPTIMAL 1.2 / REJECTED 0.3, defaut 1.0) x log2(2+access_count) ;
                     ordre du manifeste = score decroissant, puis rowid (deterministe).

Aucun acces a la base RAG ; tout tourne en tmp_path.
"""
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET = "sk-ant-api03-" + "A" * 40


def _mod(nom):
    return importlib.import_module("nokido_agent.app." + nom)


@pytest.fixture()
def racine(tmp_path, monkeypatch):
    r = tmp_path / "donnees"
    (r / "sandbox" / "ccr").mkdir(parents=True)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(r))
    monkeypatch.delenv("LAFORGE_CONTEXT_LEDGER_OBS", raising=False)
    return r


def _ledger(r):
    m = _mod("forge_context_ledger")
    return m.ContextLedger(db_path=r / "sandbox" / "context_ledger.db", racine=r)


def _ccr(r, nom, texte):
    (r / "sandbox" / "ccr" / f"{nom}.txt").write_text(texte, encoding="utf-8")
    return "ccr://" + nom


def _rows(r, sql):
    conn = sqlite3.connect(str(r / "sandbox" / "context_ledger.db"))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_essence_enrichie_distincte_et_caviardee(racine):
    reg = _mod("forge_mcp_registry")
    soi = SimpleNamespace(root=racine)
    a = reg.ToolRegistry._archive_blob(soi, "pytest tests/nr rc=1 FAILED\n" + "x\n" * 300, "CLAUDE", "run")
    b = reg.ToolRegistry._archive_blob(soi, f"cle {SECRET} lue\n" + "y\n" * 300, "CLAUDE", "run")
    ess = dict(_rows(racine, "SELECT uri, essence FROM context_ledger"))
    ea, eb = ess["ccr://" + a], ess["ccr://" + b]
    assert ea != eb, "toutes les archives ont la meme essence : aucune selection possible"
    assert ea.startswith("run:") and "pytest tests/nr" in ea
    assert SECRET not in eb, "secret recopie dans l'index"
    assert max(len(ea), len(eb)) <= 150


def test_essence_fail_closed_sans_caviardeur(racine, monkeypatch):
    """Relecture Claude 2026-11-08 : caviardeurs introuvables = premiere ligne BRUTE indexee."""
    import builtins
    vrai_import = builtins.__import__

    def import_sans_caviardeur(nom, *a, **k):
        if "semantic_firewall" in nom or "conv_sanitizer" in nom:
            raise ImportError("caviardeur indisponible (NR)")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", import_sans_caviardeur)
    reg = _mod("forge_mcp_registry")
    m = reg.ToolRegistry._archive_blob(SimpleNamespace(root=racine), f"cle {SECRET} lue\n" + "y\n" * 300, "CLAUDE", "run")
    ess = dict(_rows(racine, "SELECT uri, essence FROM context_ledger"))["ccr://" + m]
    assert SECRET not in ess and ess == "run", ess


def test_observer_porte_le_contexte_d_appel(racine):
    m = _mod("forge_context_ledger")
    u = _ccr(racine, "ccr_t1", "contenu un\n")
    m.observer(u, essence="run:ls", racine=racine, task_id="job_42", session="s1", agent="CLAUDE")
    meta = json.loads(_rows(racine, "SELECT meta FROM context_ledger")[0][0])
    assert (meta.get("task_id"), meta.get("session"), meta.get("agent")) == ("job_42", "s1", "CLAUDE")


def test_arcs_meme_tache_et_purge_en_cascade(racine):
    led = _ledger(racine)
    u1 = _ccr(racine, "ccr_a1", "un\n")
    u2 = _ccr(racine, "ccr_a2", "deux\n")
    u3 = _ccr(racine, "ccr_a3", "trois\n")
    led.indexer(u1, "run:a", {"task_id": "T"})
    led.indexer(u2, "run:b", {"task_id": "T"})
    led.indexer(u3, "run:c", {"task_id": "AUTRE"})
    arcs = set(_rows(racine, "SELECT src, dst, type FROM context_arcs"))
    assert (u1, u2, "meme_tache") in arcs and (u2, u1, "meme_tache") in arcs
    assert not any(u3 in (s, d) for s, d, _ in arcs)
    (racine / "sandbox" / "ccr" / "ccr_a2.txt").unlink()
    led.purger_pointeurs_morts(dry=False)
    assert not any(u2 in (s, d) for s, d, _ in _rows(racine, "SELECT src, dst, type FROM context_arcs"))


def test_arcs_bornes_lineaires(racine):
    """Gate firehose 2026-11-08 : chaque pointeur reliait TOUS ceux de sa tache -> N^2 arcs."""
    led = _ledger(racine)
    n = 60
    for i in range(n):
        led.indexer(_ccr(racine, f"ccr_b{i}", f"b{i}\n"), f"run:b{i}", {"task_id": "GROS"})
    nb = _rows(racine, "SELECT count(*) FROM context_arcs")[0][0]
    assert nb <= 2 * 16 * n, f"{nb} arcs pour {n} pointeurs : croissance quadratique"


def test_servir_etend_par_ppr_aux_voisins_de_la_graine(racine):
    led = _ledger(racine)
    graine = _ccr(racine, "ccr_g", "graine\n")
    voisin = _ccr(racine, "ccr_v", "voisin\n")
    etranger = _ccr(racine, "ccr_e", "etranger\n")
    led.indexer(graine, "run:pytest moteur rouge", {"task_id": "T"})
    led.indexer(voisin, "edit:forge_worktree.py", {"task_id": "T"})
    led.indexer(etranger, "run:tasklist", {"task_id": "Z"})
    uris = [e["uri"] for e in led.servir("moteur", 2000)["manifeste"]["entrees"]]
    assert uris[:1] == [graine]
    assert voisin in uris, "le voisin de meme tache n'est pas servi : pas d'expansion PPR"
    assert etranger not in uris


def test_scorecard_reordonne_a_pertinence_egale(racine):
    led = _ledger(racine)
    rej = _ccr(racine, "ccr_r", "rejete\n")
    opt = _ccr(racine, "ccr_o", "optimal\n")
    led.indexer(rej, "run:moteur essai", {"grade": "REJECTED"})
    led.indexer(opt, "run:moteur essai", {"grade": "OPTIMAL"})
    uris = [e["uri"] for e in led.servir("moteur", 2000)["manifeste"]["entrees"]]
    assert uris == [opt, rej], "la scorecard ne pese pas : un livrable REJECTED passe devant"


def test_fts5_present_et_base_hors_rag(racine):
    led = _ledger(racine)
    led.indexer(_ccr(racine, "ccr_f", "f\n"), "run:fts", None)
    noms = {n for (n,) in _rows(racine, "SELECT name FROM sqlite_master")}
    assert "context_fts" in noms and "context_arcs" in noms
    assert "embeddings" not in str(led.db_path)
