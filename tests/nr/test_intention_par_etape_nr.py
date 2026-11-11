# -*- coding: utf-8 -*-
"""NR 2026-11-04 -- intention PAR ETAPE (debat 2 tour 2, owner 3/11 ; 3 delegations ratees, fait par Claude). Une veille
DEMARREE retenait Docker pendant toutes ses etapes, y compris celles qui ne s'en servent pas (keywords via Ollama,
verify_kw, refine, ingest, store). Seules `search` (SearXNG) et `crawl` (crawl4ai) en ont besoin
(app/forge_watch_agent.py::create_job).

Contrat :
  a) seul noeud running = keywords, suivant verify_kw -> pas d'intention Docker ;
  b) noeud running juste avant search/crawl -> intention Docker (anticipation) ; idem entre deux etapes ;
  c) search/crawl running ou retry_pending -> intention Docker ;
  d) chaine entierement pending (non admise) -> rien ; chaine finie -> rien ;
  e) chains_active reste calcule (autres regulateurs) ;
  f) intentions ILLISIBLES -> on ne coupe pas (intention_docker vrai) ; ancien format sans chains_docker -> chains_active ;
  g) les decideurs de relache Docker (keeper, ensure_service) lisent intention_docker, plus chains_active.
"""
import sqlite3
from pathlib import Path

import pytest

from nokido_agent.app import forge_db_path as DB
from nokido_agent.app import forge_resource_manager as RM

RACINE = Path(__file__).resolve().parents[2]
ETAPES = ["keywords", "verify_kw", "search", "refine", "crawl", "ingest", "store"]


def _base(tmp_path, monkeypatch, chaines):
    f = tmp_path / "chaines.db"
    c = sqlite3.connect(f)
    c.execute("CREATE TABLE agent_chain_nodes (id TEXT, chain_id TEXT, step_index INTEGER, step_name TEXT, "
              "status TEXT)")
    for cid, statuts in chaines.items():
        for i, (etape, st) in enumerate(zip(ETAPES, statuts)):
            c.execute("INSERT INTO agent_chain_nodes VALUES (?,?,?,?,?)", ("n_%s_%d" % (cid, i), cid, i, etape, st))
    c.commit()
    c.close()
    monkeypatch.setattr(DB, "db_path", lambda *a, **k: str(f))
    monkeypatch.setattr(RM, "_veilles_admissibles", lambda *a, **k: False)
    return RM.get_active_intents()


P, R, D, X = "pending", "running", "done", "retry_pending"


@pytest.mark.parametrize("statuts, attendu", [
    ([R, P, P, P, P, P, P], 0),          # a) keywords running, suivant verify_kw
    ([D, R, P, P, P, P, P], 1),          # b) verify_kw running, suivant search
    ([D, D, D, R, P, P, P], 1),          # b) refine running, suivant crawl
    ([D, D, D, D, P, P, P], 1),          # b) entre refine (fini) et crawl (pas encore pris)
    ([D, D, R, P, P, P, P], 1),          # c) search running
    ([D, D, D, D, X, P, P], 1),          # c) crawl retry_pending
    ([D, D, D, D, D, R, P], 0),          # ingest running : plus besoin de Docker
    ([P, P, P, P, P, P, P], 0),          # d) non demarree
    ([D, D, D, D, D, D, D], 0),          # d) finie
])
def test_intention_docker_par_etape(tmp_path, monkeypatch, statuts, attendu):
    out = _base(tmp_path, monkeypatch, {"wj_1": statuts})
    assert out["chains_docker"] == attendu, (statuts, out)
    assert RM.intention_docker(out) is bool(attendu)


def test_chains_active_reste_calcule(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, {"wj_1": [R, P, P, P, P, P, P]})
    assert out["chains_active"] > 0 and out["chains_docker"] == 0


def test_illisible_on_ne_coupe_pas_et_ancien_format():
    assert RM.intention_docker({"chains_docker": None, "chains_active": 0}) is True
    assert RM.intention_docker({}) is False                        # ancien format (doublures) : lecture d'avant
    assert RM.intention_docker({"chains_active": 0}) is False      # ancien format : compatibilite
    assert RM.intention_docker({"chains_active": 2}) is True


def test_les_decideurs_lisent_intention_docker():
    for rel in ("tools/forge_docker_keeper.py", "tools/forge_ensure_service.py"):
        src = (RACINE / rel).read_text(encoding="utf-8")
        assert '(get_active_intents() or {}).get("chains_active")' not in src, rel   # l'ancienne decision directe
        assert 'if intents.get("chains_active")' not in src, rel
        assert "intention_docker" in src, rel
