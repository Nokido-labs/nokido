# -*- coding: utf-8 -*-
"""Reprise fine du crawl, et budgets qui bornent vraiment.

Deux defauts mesures le 2026-08-30 :

- le resultat du node de crawl n'etait persiste qu'a la FIN de la boucle, donc un
  crash a la 6e URL sur 8 faisait TOUT recrawler -- le pire niveau de reprise
  face a un crawler intermittent, celui qui refait le travail deja reussi ;
- chaque APPEL avait sa borne, mais ni la boucle de crawl ni la CHAINE n'en
  avaient : un job pouvait vieillir indefiniment sans que rien ne le declare
  bloque, et « en cours depuis toujours » se lit comme « en cours ».
"""
import asyncio
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.37)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _faux_watch_agent(monkeypatch):
    mod = types.ModuleType("forge_watch_agent")
    mod._is_binary_payload = lambda _t: False
    mod._is_boilerplate = lambda _t: False
    monkeypatch.setitem(sys.modules, "forge_watch_agent", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent", mod)


def _executor(tmp_path):
    import forge_chain_executor as ce

    return ce.ChainExecutor(db_path=tmp_path / "chain.db")


# ── #4 : reprise par URL ─────────────────────────────────────────────────────

def test_une_url_deja_soldee_n_est_pas_recrawlee(monkeypatch, tmp_path):
    """Le coeur de la reprise fine : ce qui a reussi ne se refait pas."""
    import forge_chain_executor as ce
    import forge_crawl_tool as fct

    _faux_watch_agent(monkeypatch)
    appels = {"n": 0}

    def _crawl(_url, _t=15):
        appels["n"] += 1
        return {"text": "N" * 900, "backend": "crawl4ai", "qualite": "full",
                "chars": 900, "variante": "origine"}

    monkeypatch.setattr(fct, "crawl_url_detail", _crawl, raising=False)
    ex = _executor(tmp_path)
    contexte = {
        "refined": [{"url": "http://a.test", "content": "snip"},
                    {"url": "http://b.test", "content": "snip"}],
        # a.test porte deja un verdict d'une passe precedente
        "crawl_fait": {"http://a.test": {"content": "D" * 900, "crawled": True,
                                         "crawl_backend": "urllib",
                                         "crawl_quality": "degraded"}},
    }
    out = asyncio.run(ex._call_crawl({"id": "n", "chain_id": "c"}, contexte))

    assert appels["n"] == 1, "seule l'URL non soldee doit etre crawlee"
    par = {r["url"]: r for r in out}
    # Le verdict d'avant est RESTAURE, pas perdu ni recalcule.
    assert par["http://a.test"]["crawl_backend"] == "urllib"
    assert par["http://b.test"]["crawl_backend"] == "crawl4ai"


def test_chaque_url_est_soldee_au_fur_et_a_mesure(monkeypatch, tmp_path):
    """Sans persistance par URL, un crash en cours de boucle perd tout."""
    import forge_crawl_tool as fct

    _faux_watch_agent(monkeypatch)
    monkeypatch.setattr(fct, "crawl_url_detail",
                        lambda _u, _t=15: {"text": "N" * 900, "backend": "crawl4ai",
                                           "qualite": "full", "chars": 900,
                                           "variante": "origine"}, raising=False)
    ex = _executor(tmp_path)
    asyncio.run(ex._call_crawl(
        {"id": "n", "chain_id": "chaine1"},
        {"refined": [{"url": "http://a.test"}, {"url": "http://b.test"}]}))

    fait = ex.get_context("chaine1").get("crawl_fait") or {}
    assert set(fait) == {"http://a.test", "http://b.test"}
    assert fait["http://a.test"]["crawl_quality"] == "full"


def test_budget_de_boucle_epuise_est_dit_et_non_tu(monkeypatch, tmp_path):
    """Un crawl qu'on n'a PAS fait n'est pas un crawl sans resultat."""
    import forge_chain_executor as ce
    import forge_crawl_tool as fct

    _faux_watch_agent(monkeypatch)
    monkeypatch.setattr(ce, "_BUDGET_CRAWL_S", -1.0)  # budget deja epuise
    appels = {"n": 0}

    def _crawl(_url, _t=15):
        appels["n"] += 1
        return {"text": "N" * 900, "backend": "crawl4ai", "qualite": "full",
                "chars": 900, "variante": "origine"}

    monkeypatch.setattr(fct, "crawl_url_detail", _crawl, raising=False)
    ex = _executor(tmp_path)
    out = asyncio.run(ex._call_crawl({"id": "n", "chain_id": "c"},
                                     {"refined": [{"url": "http://a.test"}]}))
    assert appels["n"] == 0
    assert out[0]["crawl_quality"] == "budget_epuise"


# ── #5 : deadline globale et etat STALLED ────────────────────────────────────

def test_age_illisible_ne_vaut_pas_zero(monkeypatch):
    """Un horodatage qu'on ne sait pas lire ferait passer une chaine ancienne
    pour toute fraiche s'il rendait 0."""
    import forge_chain_executor as ce

    assert ce._age_s(None) is None
    assert ce._age_s("pas une date") is None
    assert ce._age_s(datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")) < 60


def test_une_chaine_hors_budget_passe_stalled_et_n_est_pas_jouee(monkeypatch, tmp_path):
    """`stalled` est TERMINAL et distinct de `failed` : budget epuise, pas travail
    mauvais. Et aucun node ne doit etre dispatche apres la bascule."""
    import forge_chain_executor as ce

    ex = _executor(tmp_path)
    vieux = (datetime.now(tz=timezone.utc) - timedelta(seconds=99999)
             ).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(str(tmp_path / "chain.db"))
    conn.execute(
        "INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, "
        "agent_role, status, created_at) VALUES (?,?,?,?,?,?,?)",
        ("n1", "vieille", 0, "search", "SearchAgent", "pending", vieux))
    conn.commit()
    conn.close()

    dispatches = {"n": 0}

    async def _jamais(_node, _ctx):
        dispatches["n"] += 1
        return []

    monkeypatch.setattr(ex, "dispatch_agent", _jamais)
    asyncio.run(ex.execute_pending())

    assert dispatches["n"] == 0, "aucun node ne doit etre joue apres la bascule"
    conn = sqlite3.connect(str(tmp_path / "chain.db"))
    statut, erreur = conn.execute(
        "SELECT status, error FROM agent_chain_nodes WHERE id='n1'").fetchone()
    conn.close()
    assert statut == "stalled"
    assert "budget de chaine epuise" in (erreur or ""), "le motif doit etre NOMME"


def test_une_chaine_dans_les_temps_est_jouee_normalement(monkeypatch, tmp_path):
    """Le garde ne doit pas mordre sur une chaine fraiche."""
    import forge_chain_executor as ce

    ex = _executor(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "chain.db"))
    conn.execute(
        "INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, "
        "agent_role, status, created_at) VALUES (?,?,?,?,?,?,?)",
        ("n1", "fraiche", 0, "search", "SearchAgent", "pending",
         datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    dispatches = {"n": 0}

    async def _ok(_node, _ctx):
        dispatches["n"] += 1
        return ["un resultat"]

    monkeypatch.setattr(ex, "dispatch_agent", _ok)
    asyncio.run(ex.execute_pending())
    assert dispatches["n"] == 1
