"""NR -- la fin d'une veille LIBERE Docker, et zero resultat = VIDE ASSUME (24/10).

MESURE. 7 chaines (wj_28a43f91f4...) `completed/done` avec search_results_json = 0 resultat, mais n_ingested 5..45
et n_stored 3..5 (contenu fabrique a sec), et Docker reste reclame jusqu'a coupure manuelle.
(a) fin terminale -> relache la reclamation, la derniere retire docker.wanted ; (b) deux chaines : la premiere
qui finit ne coupe pas ; (c) 0 resultat -> completed_empty, aucune etape aval jouee ; (d) la quarantaine ne supprime rien.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_agent.tools.forge_docker_keeper as K  # noqa: E402
import nokido_agent.app.forge_watch_agent as W  # noqa: E402
from nokido_agent.app.forge_chain_executor import ChainExecutor  # noqa: E402


def _keeper(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    arrets = []
    monkeypatch.setattr(K, "_release_docker", lambda: arrets.append(1) or {"stopped": ["x"]})
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    return arrets


def _sans_grace(monkeypatch):
    """Chemin IMMEDIAT (delai de grace 0, GO owner 28/10) : la grace elle-meme est couverte par
    test_docker_grace_keeper_nr et test_docker_grace_tick_reel_nr. Aucune lecture d'etat vivant."""
    monkeypatch.setenv("LAFORGE_DOCKER_GRACE_S", "0")
    monkeypatch.setattr(K, "palier_courant", lambda: "CALME")
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda *a, **k: 0)


def test_la_derniere_reclamation_retire_docker_wanted(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path)
    _sans_grace(monkeypatch)
    K.claim_docker("wj_a")
    assert K.WANT_FLAG.exists()
    r = K.release_claim("wj_a")
    assert r["released"] is True and not K.WANT_FLAG.exists() and arrets == [1]


def test_avec_deux_chaines_la_premiere_qui_finit_ne_coupe_pas(monkeypatch, tmp_path):
    arrets = _keeper(monkeypatch, tmp_path)
    _sans_grace(monkeypatch)
    K.claim_docker("wj_a")
    K.claim_docker("wj_b")
    assert K.release_claim("wj_a")["released"] is False
    assert K.WANT_FLAG.exists() and arrets == []
    assert K.release_claim("wj_b")["released"] is True
    assert not K.WANT_FLAG.exists() and arrets == [1]


def _chaine(tmp_path, monkeypatch):
    base = tmp_path / "chain.db"
    ex = ChainExecutor(base)
    c = sqlite3.connect(base)
    c.executescript(W.DDL_WATCH)
    c.execute("INSERT INTO watch_jobs (id, theme, status, step, n_ingested, created_at, updated_at) "
              "VALUES ('wj_t','theme','en_cours','search',0,'2026-10-24','2026-10-24')")
    for i, (nom, role) in enumerate([("search", "SearchAgent"), ("refine", "RefineAgent"),
                                     ("crawl", "CrawlAgent"), ("ingest", "IngestAgent"),
                                     ("store", "StoreAgent")]):
        c.execute("INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, agent_role, output_key, status) "
                  "VALUES (?,?,?,?,?,?, 'pending')", ("n%d" % i, "wj_t", i, nom, role, nom))
    c.commit()
    c.close()
    relaches = []
    monkeypatch.setattr(W, "_relacher_docker", lambda cid: relaches.append(cid))
    return ex, base, relaches


def test_zero_resultat_donne_completed_empty_sans_rien_en_aval(monkeypatch, tmp_path):
    ex, base, relaches = _chaine(tmp_path, monkeypatch)
    joues = []

    async def dispatch(node, context):
        joues.append(node["agent_role"])
        from nokido_agent.app.forge_chain_executor import _Resultats, MOTIF_MOTEURS_BLOQUES
        r = _Resultats()
        r.motif = MOTIF_MOTEURS_BLOQUES
        return r

    monkeypatch.setattr(ex, "dispatch_agent", dispatch)
    c = sqlite3.connect(base)
    c.row_factory = sqlite3.Row
    node = dict(c.execute("SELECT * FROM agent_chain_nodes WHERE id='n0'").fetchone())
    c.close()
    asyncio.run(ex.run_node(node))
    c = sqlite3.connect(base)
    statut, erreur, n_stored = c.execute("SELECT status, error, n_stored FROM watch_jobs WHERE id='wj_t'").fetchone()
    aval = [r[0] for r in c.execute("SELECT status FROM agent_chain_nodes WHERE step_index>0")]
    c.close()
    assert joues == ["SearchAgent"]
    assert statut == "completed_empty", statut
    assert erreur == "moteurs bloqués" and not n_stored
    assert aval == ["skipped"] * 4
    assert relaches == ["wj_t"]          # verdict terminal -> reclamation relachee


def test_le_transport_en_panne_donne_failed_et_n_ecrit_rien_en_aval(monkeypatch, tmp_path):
    ex, base, relaches = _chaine(tmp_path, monkeypatch)
    c = sqlite3.connect(base)
    c.execute("UPDATE agent_chain_nodes SET max_retries=1 WHERE id='n0'")
    c.commit()
    c.row_factory = sqlite3.Row
    node = dict(c.execute("SELECT * FROM agent_chain_nodes WHERE id='n0'").fetchone())
    c.close()

    async def dispatch(node, context):
        raise RuntimeError("recherche NON MESUREE : RemoteDisconnected")

    monkeypatch.setattr(ex, "dispatch_agent", dispatch)
    asyncio.run(ex.run_node(node))
    c = sqlite3.connect(base)
    statut = c.execute("SELECT status FROM watch_jobs WHERE id='wj_t'").fetchone()[0]
    aval = [r[0] for r in c.execute("SELECT status FROM agent_chain_nodes WHERE step_index>0")]
    c.close()
    assert statut == "failed", statut
    assert aval == ["skipped"] * 4 and relaches == ["wj_t"]


def test_le_script_de_quarantaine_ne_supprime_aucune_ligne():
    src = (ROOT / "tools" / "forge_veille_quarantaine_20261024.py").read_text(encoding="utf-8")
    assert "DELETE" not in src.upper().replace("DELETE_", "")
    assert "+active" in src
