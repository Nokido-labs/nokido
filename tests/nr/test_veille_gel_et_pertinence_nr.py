"""NR -- la veille de la soif respecte le GEL et ne retient que le PERTINENT, et le DIT.

Mesure 26/09 (veilles RSI de la soif, repli academique OpenAlex/arXiv) :
- 54 chunks hors sujet geles (accord owner) ; la relance suivante en a REACTIVE 6 sources. Cause :
  `_ingest` ecrit en `INSERT OR REPLACE` sur un id deterministe (`ra_<md5(url)>_NN`) -- la meme URL
  remplace la ligne gelee et `active` retombe a sa valeur par defaut. Le gel etait annule en silence.
- aucune borne de pertinence : « Large language models encode clinical knowledge », « GPT-4 Technical
  Report », « GLUE » etaient ingeres pour « misevolution in self-evolving LLM agents », et la synthese
  (`text[:150]` par source = l'en-tete de la page) finissait en « les LLM integrent des connaissances
  cliniques » avec l'etiquette REUSSIE.
Plancher mesure AVANT d'etre code (C:/tmp/corrections/mesure_pertinence_veilles_rsi.py) : sur les sources
etiquetees a la main, >= 1 terme distinctif ecarte 11/14 hors sujet et 3/13 gardes (marginaux) ; >= 2 en
perdait 8/13. Ce qui est ecarte est LISTE avec son motif : un filtre qui ecarte le dit.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele) (l.137)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_research_agent as ra  # noqa: E402

TEXTE = " ".join("mot%d" % i for i in range(900))
SCHEMA = ("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, role_hint TEXT, "
          "author TEXT, ingested_at TEXT, active INTEGER DEFAULT 1)")


def _base(tmp_path, monkeypatch):
    db = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(db))
    c.execute(SCHEMA)
    c.commit()
    c.close()
    monkeypatch.setattr(ra, "DB", db)
    return db


def _uid(url):
    import hashlib
    return "ra_" + hashlib.md5(url.encode()).hexdigest()[:10]


def test_ingest_refuse_une_source_gelee_et_la_laisse_gelee(tmp_path, monkeypatch):
    db = _base(tmp_path, monkeypatch)
    url = "https://doi.org/10.1038/s41586-023-06291-2"
    c = sqlite3.connect(str(db))
    c.execute("INSERT INTO rag_chunks (id, text, source, active) VALUES (?, 'gele', ?, 0)", (_uid(url) + "_00", url))
    c.commit()
    c.close()
    assert ra._ingest(url, "LLMs encode clinical knowledge", TEXTE, "research", "research:x") is False
    c = sqlite3.connect(str(db))
    lignes = c.execute("SELECT id, active, text FROM rag_chunks").fetchall()
    c.close()
    assert lignes == [(_uid(url) + "_00", 0, "gele")], "le gel a ete annule par la re-ingestion"


def test_le_controle_de_gel_emprunte_la_cle_primaire(tmp_path):
    # MESURE 26/09 sur la base vivante (45 Go, sans ANALYZE) : `active = 0` faisait choisir
    # idx_rag_chunks_active a SQLite -- un parcours de toutes les lignes gelees par ingestion.
    c = sqlite3.connect(str(tmp_path / "plan.db"))
    c.execute(SCHEMA)
    c.execute("CREATE INDEX idx_rag_chunks_active ON rag_chunks(active)")
    bornes = ("ra_0123456789_", "ra_0123456789`")
    naif = str(c.execute("EXPLAIN QUERY PLAN SELECT count(*) FROM rag_chunks WHERE id >= ? AND id < ? "
                         "AND active = 0", bornes).fetchall())
    assert "idx_rag_chunks_active" in naif, "la fixture ne reproduit plus le choix du planificateur"
    plan = str(c.execute("EXPLAIN QUERY PLAN " + ra._SQL_GELES, bornes).fetchall())
    c.close()
    assert "idx_rag_chunks_active" not in plan and "sqlite_autoindex_rag_chunks_1" in plan, plan


def test_ingest_d_une_source_neuve_ecrit_des_chunks_actifs(tmp_path, monkeypatch):
    db = _base(tmp_path, monkeypatch)
    assert ra._ingest("https://arxiv.org/abs/2505.22954", "Darwin Godel Machine", TEXTE, "research", "r") is True
    c = sqlite3.connect(str(db))
    etats = c.execute("SELECT active, count(*) FROM rag_chunks GROUP BY active").fetchall()
    c.close()
    assert etats == [(1, 2)]


def test_pertinence_sur_des_titres_reels_de_la_veille():
    # Titres reels ingeres le 26/09 ; content = titre, comme OpenAlex quand le resume manque.
    hors = [("misevolution in self-evolving LLM agents: agents weakening their own verification checks, "
             "and defenses", "Large language models encode clinical knowledge"),
            ("misevolution in self-evolving LLM agents: agents weakening their own verification checks, "
             "and defenses", "GPT-4 Technical Report"),
            ("deterministic held-out validation gate for accepting self-modifications of LLM agents",
             "GLUE: A Multi-Task Benchmark and Analysis Platform for Natural Language Understanding")]
    dedans = [("evaluator isolation and reward hacking in recursive self-improvement of coding agents "
               "(Darwin Godel Machine, AlphaEvolve)",
               "Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents"),
              ("multi-objective Pareto fitness with complexity penalty in LLM-driven code evolution",
               "Multi-Objective Evolution of Heuristic Using Large Language Model")]
    for obj, titre in hors:
        assert ra._pertinence(obj, {"title": titre, "content": titre}) < ra._PERTINENCE_MIN, titre
    for obj, titre in dedans:
        assert ra._pertinence(obj, {"title": titre, "content": titre}) >= ra._PERTINENCE_MIN, titre


def _brancher(monkeypatch, resultats, geles=()):
    prompts = []

    def llm(prompt, provider="auto"):
        prompts.append(prompt)
        if "requetes" in prompt:
            return ("self-evolving agents", "mock")
        if "Selectionne" in prompt:
            return ("1,2,3", "mock")
        return ("Synthese de test.", "mock")

    ingerees = []
    fetchs = []
    monkeypatch.setattr(ra, "_llm", llm)
    monkeypatch.setattr(ra, "_search", lambda q, n=5: (list(resultats), ""))
    monkeypatch.setattr(ra, "_fetch", lambda url: fetchs.append(url) or "en-tete de page " * 40)
    monkeypatch.setattr(ra, "_ingest", lambda url, title, text, domain, role: ingerees.append(url) or True)
    monkeypatch.setattr(ra, "_chunks_geles_url", lambda url: 3 if url in geles else 0)
    return prompts, ingerees, fetchs


OBJ = "misevolution in self-evolving LLM agents: agents weakening their own verification checks"
BON = {"title": "SEVerA: Verified Synthesis of Self-Evolving Agents", "url": "https://arxiv.org/abs/2603.25111",
       "content": "We study self-evolving agents that rewrite their verification. " + "x" * 200 + " MARQUEUR_RESUME"}
HORS = {"title": "Large language models encode clinical knowledge", "url": "https://doi.org/10.1038/s41586-023-06291-2",
        "content": "Large language models encode clinical knowledge"}
GELE = {"title": "A Comprehensive Survey of Self-Evolving AI Agents", "url": "https://arxiv.org/abs/2508.07407",
        "content": "self-evolving agents survey"}


def test_le_hors_sujet_n_est_pas_ingere_et_il_est_dit(monkeypatch):
    _, ingerees, _ = _brancher(monkeypatch, [BON, HORS])
    res = ra.research_agent(OBJ, max_rounds=1, max_urls=3)
    assert ingerees == [BON["url"]]
    motifs = {e["url"]: e["motif"] for e in res["ecartees"]}
    assert "pertinence" in motifs[HORS["url"]]
    assert res["retenues"] == [BON["url"]]


def test_une_source_gelee_n_est_ni_relue_ni_reingeree(monkeypatch):
    _, ingerees, fetchs = _brancher(monkeypatch, [BON, GELE], geles={GELE["url"]})
    res = ra.research_agent(OBJ, max_rounds=1, max_urls=3)
    assert GELE["url"] not in ingerees and GELE["url"] not in fetchs
    motifs = {e["url"]: e["motif"] for e in res["ecartees"]}
    assert "gel" in motifs[GELE["url"]]


def _juge(monkeypatch, reponse):
    prompts, ingerees, _ = _brancher(monkeypatch, [BON, BON2, TANGENT])

    def llm(prompt, provider="auto"):
        prompts.append(prompt)
        if "requetes" in prompt:
            return ("self-evolving agents", "mock")
        if "Selectionne" in prompt:
            return (reponse, "mock")
        return ("Synthese de test.", "mock")

    monkeypatch.setattr(ra, "_llm", llm)
    return prompts, ingerees


BON2 = {"title": "Who Grades the Grader? Co-Evolving Evaluation Metrics for Self-Improving Agents",
        "url": "https://arxiv.org/abs/2607.12790", "content": "self-evolving agents weakening verification checks"}
# Score lexical 1 (« defense ») : passe le plancher, un juge doit pouvoir l'ecarter. Titre reel du 26/09.
TANGENT = {"title": "Smart Grid Cyber-Physical Attack and Defense: A Review", "url": "https://doi.org/10.1109/access.2021.3058628",
           "content": "attack detection and verification of smart grid measurements"}  # score 1 : verification


def test_une_source_citee_deux_fois_par_le_juge_n_est_ingeree_qu_une_fois(monkeypatch):
    # Mesure 26/09 : « retenues » portait deux fois la meme URL (BRATS, SEVerA) -- `ingerees` gonfle.
    _, ingerees = _juge(monkeypatch, "1, 2, 1")
    res = ra.research_agent(OBJ, max_rounds=1, max_urls=8)
    assert sorted(ingerees) == sorted({BON["url"], BON2["url"]})
    assert res["ingested"] == 2 and len(res["retenues"]) == len(set(res["retenues"]))


def test_le_juge_peut_ne_rien_retenir(monkeypatch):
    _, ingerees = _juge(monkeypatch, "AUCUN")
    res = ra.research_agent(OBJ, max_rounds=1, max_urls=8)
    assert ingerees == [] and res["ingested"] == 0 and "AUCUN" in res["selection"]


def test_le_juge_n_est_pas_somme_de_tout_retenir_et_voit_le_resume(monkeypatch):
    # Mesure 26/09 : « Selectionne 7 numeros » pour 7 candidats -- le juge ne pouvait rien ecarter.
    prompts, _ = _juge(monkeypatch, "1,2")
    ra.research_agent(OBJ, max_rounds=1, max_urls=8)
    juge = [p for p in prompts if "Selectionne" in p][0]
    assert "au plus 8" in juge and "AUCUN" in juge and "weakening verification checks" in juge


def test_juge_illisible_seul_le_plancher_strict_retient_et_c_est_dit(monkeypatch):
    _, ingerees = _juge(monkeypatch, "ERR:no_provider_available")
    res = ra.research_agent(OBJ, max_rounds=1, max_urls=8)
    assert TANGENT["url"] not in ingerees and "illisible" in res["selection"]
    assert any(e["url"] == TANGENT["url"] for e in res["ecartees"])


def test_la_synthese_lit_le_resume_et_pas_l_en_tete_de_page(monkeypatch):
    prompts, _, _ = _brancher(monkeypatch, [BON])
    ra.research_agent(OBJ, max_rounds=1, max_urls=3)
    synthese = [p for p in prompts if "Resume en 3 phrases" in p]
    assert synthese and "MARQUEUR_RESUME" in synthese[0]
