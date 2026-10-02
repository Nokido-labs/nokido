"""NR -- la soif mesure avec UN instrument classe, ne lit jamais une panne comme une lacune, et
n'escalade une douleur qu'a son OUVERTURE ou quand elle S'AGGRAVE.

MESURE 2026-10-01 (revue claude.ai mission_rsi_soif, chaque point VERIFIE dans le code avant
correction) :
- coverage_dense, branche lexicale `MATCH ? LIMIT 30` sans `ORDER BY rank` : banc reel sur 9
  questions (C:/tmp/corrections/banc_lexical_rank_2026-10-01.json) -> recouvrement 0/30 entre les
  30 premiers physiques et les 30 meilleurs, sur LES NEUF. Le reranker ne voyait jamais les
  meilleurs candidats lexicaux : faux gaps.
- coverage_score rendait gap=True quand le RAG levait (« prudence ») et feel_gap -- appele par le
  demon APRES coverage_dense -- rejugeait avec cet autre instrument : evenement critique et
  cortisol sur une source muette (UNKNOWN != NO).
- _sev_bump aggravait tout defaut present 3 cycles (un ⚠ devenait HIGH en 45 min), _propose_care
  persistait un evenement critique A CHAQUE CYCLE, et son `return` cachait les douleurs graves au
  tableau noir que lit le soin (pat_self_improvement).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_critical_events as ce  # noqa: E402
from nokido_agent.app import forge_db_path as fdb  # noqa: E402
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402
from nokido_agent.app import forge_swarm_blackboard as bb  # noqa: E402


def _demon():
    spec = importlib.util.spec_from_file_location("demon_soif_transition", RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Rep:
    def __init__(self, d):
        self.d = d

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------------------------------------------------------------- lexical classe

MEILLEUR = "alpha beta gamma " * 20


@pytest.fixture
def base_fts(tmp_path, monkeypatch):
    """41 chunks : 40 qui ne citent qu'un terme, puis le MEILLEUR, insere en DERNIER (rowid 41)."""
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT)")
    c.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text)")
    for i in range(1, 41):
        t = "remplissage %d alpha et rien d'autre" % i
        c.execute("INSERT INTO rag_chunks(rowid, id, text) VALUES (?, ?, ?)", (i, "f%d" % i, t))
        c.execute("INSERT INTO rag_chunks_fts(rowid, text) VALUES (?, ?)", (i, t))
    c.execute("INSERT INTO rag_chunks(rowid, id, text) VALUES (41, 'meilleur', ?)", (MEILLEUR,))
    c.execute("INSERT INTO rag_chunks_fts(rowid, text) VALUES (41, ?)", (MEILLEUR,))
    c.commit()
    c.close()
    monkeypatch.setattr(fdb, "db_path", lambda *a, **k: db)
    monkeypatch.setattr(ev, "manifold_error", lambda v: None)
    return db


def test_le_meilleur_candidat_lexical_atteint_le_reranker(base_fts, monkeypatch):
    vus = []

    def urlopen(req, timeout=None):
        url = req.full_url
        if ":8099/" in url:
            return _Rep({"data": [{"embedding": [0.1, 0.2]}]})
        if ":6333/" in url:
            return _Rep({"result": []})          # dense muet : seul le lexical propose
        if ":8100/" in url:
            vus.extend(json.loads(req.data)["documents"])
            return _Rep({"results": [{"relevance_score": 0.0}]})
        raise AssertionError("appel inattendu : %s" % url)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    cov = ev.coverage_dense("alpha beta gamma")
    assert cov["ok"] is True and cov["n_candidates"] == 30
    assert any(d.startswith("alpha beta gamma") for d in vus), \
        "le meilleur passage lexical (insere en dernier) n'est pas presente au reranker : LIMIT sans ORDER BY rank"


def test_un_oeil_lexical_ferme_n_est_pas_un_gap(tmp_path, monkeypatch):
    """Branche lexicale en echec (ici : index FTS absent) -> le reranker n'a juge que le dense ;
    un mauvais score ne prouve pas l'absence : abstention DITE, jamais gap certain."""
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT)")
    c.execute("INSERT INTO rag_chunks VALUES ('c1', 'un texte sans rapport')")
    c.commit()
    c.close()
    monkeypatch.setattr(fdb, "db_path", lambda *a, **k: db)
    monkeypatch.setattr(ev, "manifold_error", lambda v: 0.1)   # dans la variete : pas d'abstention de ce cote

    def urlopen(req, timeout=None):
        url = req.full_url
        if ":8099/" in url:
            return _Rep({"data": [{"embedding": [0.1, 0.2]}]})
        if ":6333/" in url:
            return _Rep({"result": [{"payload": {"chunk_id": "c1"}}]})
        if ":8100/" in url:
            return _Rep({"results": [{"relevance_score": -9.0}]})
        raise AssertionError("appel inattendu : %s" % url)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    cov = ev.coverage_dense("alpha beta gamma")
    assert cov["gap"] is None and cov["verdict"] == "aveugle_lexical_abstention", cov
    assert cov["lexical_err"], "l'echec lexical doit etre DIT dans le resultat"


# ---------------------------------------------------------------- UNKNOWN != NO

def test_rag_en_panne_n_est_pas_une_lacune(monkeypatch):
    from nokido_agent.app import forge_self_correction as sc

    def panne(*a, **k):
        raise ConnectionError("RAG muet")

    monkeypatch.setattr(sc, "preflight_check_verbose", panne)
    cov = ev.coverage_score("une question quelconque")
    assert cov["gap"] is None and cov["ok"] is False and cov["verdict"] == "rag_indisponible"

    emis = []
    monkeypatch.setattr(ce, "persist", lambda *a, **k: emis.append(a) or 1)
    felt = ev.feel_gap("reference", "une question quelconque")
    assert felt["felt"] is False and emis == [], "une panne du RAG a produit un evenement de lacune"


def test_feel_gap_juge_avec_la_mesure_fournie(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("feel_gap a rejuge avec coverage_score alors que la mesure etait fournie")

    monkeypatch.setattr(ev, "coverage_score", interdit)
    from nokido_agent.app import forge_endocrine as fe

    monkeypatch.setattr(fe, "release", lambda *a, **k: None)   # JAMAIS de vraie hormone depuis un test
    emis = []
    monkeypatch.setattr(ce, "persist", lambda kind, sev, payload: emis.append((kind, sev)) or 1)
    abst = ev.feel_gap("reference", "q", cov={"ok": True, "gap": None, "n_candidates": 12})
    assert abst["felt"] is False and emis == []
    felt = ev.feel_gap("reference", "q", cov={"ok": True, "gap": True, "n_candidates": 0, "score": None})
    assert felt["felt"] is True and emis == [("knowledge_gap", "high")]


def test_le_demon_transmet_sa_mesure_a_feel_gap(monkeypatch):
    d = _demon()
    recu = {}
    monkeypatch.setattr(d.ev, "feel_gap", lambda **k: recu.update(k) or {})

    async def faux_fait(*a, **k):
        return {"ok": True}

    monkeypatch.setattr(bb, "apply_fact", faux_fait)
    cov = {"ok": True, "gap": True, "score": -6.2, "n_candidates": 9}
    d._propose_gap("une question", cov)
    assert recu.get("cov") is cov


# ---------------------------------------------------------------- douleur : transition seulement

@pytest.fixture
def corps(tmp_path, monkeypatch):
    d = _demon()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setattr(d, "__file__", str(tmp_path / "tools" / "forge_epistemic_daemon.py"))
    monkeypatch.setattr(d, "_ETAT_SOIN", sandbox / "self_care_state.json")
    # Lot B (2026-10-02) : le plafond par fenetre tient un REGISTRE des tirs ; hermetique, il vit
    # dans le tmp -- sinon le test lirait celui du vrai sandbox/ (illisible ou plein = voie lente).
    monkeypatch.setattr(d, "TIRS_ALGEDONIQUES", sandbox / "tirs_algedoniques.json")
    escalades, faits = [], []
    monkeypatch.setattr(ce, "persist", lambda kind, sev, payload: escalades.append((sev, payload)) or len(escalades))

    async def faux_fait(zone, texte, **k):
        faits.append((k.get("category"), k.get("key"), texte))
        return {"ok": True}

    monkeypatch.setattr(bb, "apply_fact", faux_fait)

    def diagnostic(*gaps):
        (sandbox / "health_diagnostic.json").write_text(json.dumps({"gaps": list(gaps)}), encoding="utf-8")

    def cycle():
        split = d._interoceptive_split()
        for item in split["soin"]:
            d._propose_care(item)
        return split

    return d, diagnostic, cycle, escalades, faits


def test_la_duree_n_aggrave_pas_un_avertissement(corps):
    d, diagnostic, cycle, escalades, _ = corps
    diagnostic("⚠ RAM du poste saturee a 91 pour cent depuis le matin")
    for _ in range(6):
        split = cycle()
    [item] = split["soin"]
    assert item["cycles"] == 6 and item["severity"] == "medium", item
    assert escalades == [], "un avertissement qui DURE a ete escalade comme une douleur grave"


def test_une_douleur_grave_s_escalade_une_fois_et_reste_visible_du_soin(corps):
    d, diagnostic, cycle, escalades, faits = corps
    diagnostic("❌ service NokidoCardiacNode DOWN depuis 3 cycles")
    for _ in range(4):
        cycle()
    assert len(escalades) == 1, "la meme douleur a ete re-escaladee a chaque cycle : %d" % len(escalades)
    sev, payload = escalades[0]
    assert sev == "critical" and payload["transition"] == "ouverture -> critical" and payload["sig"]
    soins = [f for f in faits if f[0] == "self_care"]
    assert len(soins) == 4 and len({f[1] for f in soins}) == 1, \
        "la douleur grave doit atteindre le tableau noir a chaque cycle, sous UNE cle"
    assert "[critical]" in soins[0][2]


def test_une_douleur_qui_s_aggrave_s_escalade_de_nouveau(corps):
    d, diagnostic, cycle, escalades, _ = corps
    d._propose_care({"fault": "f", "cycles": 1, "sig": "abc", "severity": "high", "sev_emise": None})
    d._propose_care({"fault": "f", "cycles": 2, "sig": "abc", "severity": "high", "sev_emise": "high"})
    d._propose_care({"fault": "f", "cycles": 3, "sig": "abc", "severity": "critical", "sev_emise": "high"})
    assert [e[0] for e in escalades] == ["high", "critical"]
    assert escalades[1][1]["transition"] == "high -> critical"


def test_l_ancien_etat_se_lit_encore(corps):
    d, diagnostic, cycle, escalades, _ = corps
    d._ETAT_SOIN.write_text(json.dumps({"aaaaaaaaaaaa": 4}), encoding="utf-8")
    assert d._lire_etat_soin() == {"aaaaaaaaaaaa": {"n": 4, "sev_emise": None}}
