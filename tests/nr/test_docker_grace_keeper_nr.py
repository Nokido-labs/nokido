"""NR -- delai de grace avant l'arret de Docker, module par intentions et palier (28/10).

Sans etat vivant : tmp_path + monkeypatch. Jamais le vrai docker.wanted / claims / release_at, jamais le vrai Docker.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_agent.tools.forge_docker_keeper as K  # noqa: E402
import nokido_agent.app.forge_watch_agent as W  # noqa: E402
from nokido_agent.app.forge_chain_executor import ChainExecutor  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_GRACE_S", raising=False)
    monkeypatch.setattr(K, "WANT_TTL_S", 900.0)


# -- (1) delai_de_grace pure --------------------------------------------------
def test_base_et_extension_par_intention():
    assert K.delai_de_grace(0, "CALME") == 180
    assert K.delai_de_grace(2, "CALME") == 180 + 240


def test_plafond_ttl_de_docker_wanted():
    assert K.delai_de_grace(50, "CALME") == 900


def test_base_surchargeable(monkeypatch):
    monkeypatch.setenv("LAFORGE_DOCKER_GRACE_S", "60")
    assert K.delai_de_grace(1, "CALME") == 180


def test_paliers():
    assert K.delai_de_grace(1, "RALENTISSEMENT") == 150
    assert K.delai_de_grace(1, "GENE") == 30
    assert K.delai_de_grace(0, "GENE") == 30
    assert K.delai_de_grace(0, "DETRESSE") == 0
    assert K.delai_de_grace(5, "CRITIQUE") == 0


def test_gene_ne_rallonge_pas_une_base_courte(monkeypatch):
    monkeypatch.setenv("LAFORGE_DOCKER_GRACE_S", "10")
    assert K.delai_de_grace(0, "GENE") == 10


@pytest.mark.parametrize("p", ["ILLISIBLE", "INCONNU", None])
def test_palier_illisible_base_sans_extension(p):
    d = K.delai_de_grace(3, p)
    assert d == 180 and d != 0


def test_intentions_inconnues_pas_d_extension():
    assert K.delai_de_grace(None, "CALME") == 180


# -- (2) intentions_docker_en_attente -----------------------------------------
def _base(tmp_path, jobs):
    base = tmp_path / "chain.db"
    ChainExecutor(base)
    c = sqlite3.connect(base)
    c.executescript(W.DDL_WATCH)
    for jid, status, step in jobs:
        c.execute("INSERT INTO watch_jobs (id, theme, status, step, created_at, updated_at) "
                  "VALUES (?,?,?,?,'2026-10-28','2026-10-28')", (jid, "t", status, step))
    c.commit()
    c.close()
    return base


def test_compte_les_chaines_qui_reclameront_docker(tmp_path):
    base = _base(tmp_path, [("a", "pending", "search"), ("b", "running", "crawl"),
                            ("c", "en_cours", "refine"), ("d", "pending", "ingest"),
                            ("e", "completed", "search"), ("f", "failed", "crawl")])
    assert K.intentions_docker_en_attente(base) == 3


def test_aucune_attente_est_zero_pas_none(tmp_path):
    assert K.intentions_docker_en_attente(_base(tmp_path, [])) == 0


def test_base_illisible_rend_none(tmp_path):
    assert K.intentions_docker_en_attente(tmp_path / "absente.db") is None
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"pas une base sqlite" * 50)
    assert K.intentions_docker_en_attente(junk) is None


def test_lecture_seule_et_requete_par_index(tmp_path):
    base = _base(tmp_path, [("a", "pending", "search")])
    avant = base.read_bytes()
    K.intentions_docker_en_attente(base)
    assert base.read_bytes() == avant
    c = sqlite3.connect(base)
    for sql, args in K._REQUETES_INTENTIONS:
        plan = " | ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, args))
        assert "SCAN" not in plan.upper(), plan
        assert "idx_watch_status" in plan, plan
    c.close()


# -- (3)/(4) release_claim ----------------------------------------------------
def _keeper(monkeypatch, tmp_path, palier="CALME", n=0):
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    arrets, audits = [], []
    monkeypatch.setattr(K, "_release_docker", lambda: arrets.append(1) or {"stopped": ["x"]})
    monkeypatch.setattr(K, "_audit", lambda action, reason="", **kw: audits.append((action, reason, kw)))
    monkeypatch.setattr(K, "palier_courant", lambda: palier)
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda *a, **k: n)
    # Isolation (10/11 soir) : _tick_release_at lit les intentions VIVANTES ; 8 veilles reelles en file retenaient
    # Docker et rendaient deux tests rouges selon l'etat de la machine.
    from nokido_agent.app import forge_resource_manager as _RM
    monkeypatch.setattr(_RM, "get_active_intents", lambda *a, **k: [])
    return arrets, audits


def _ra():
    return K.WANT_FLAG.with_name("docker.release_at")


def test_derniere_reclamation_differe_l_arret(monkeypatch, tmp_path):
    arrets, audits = _keeper(monkeypatch, tmp_path, "CALME", 2)
    K.claim_docker("wj_a")
    r = K.release_claim("wj_a")
    assert arrets == [] and not K.WANT_FLAG.exists()
    d = json.loads(_ra().read_text(encoding="utf-8"))
    assert d["delai"] == 420 and d["intentions"] == 2 and d["palier"] == "CALME" and d["motif"]
    assert d["echeance"] > 0 and r["released"] is True and r["differe"] is True
    assert any(a[0] == "release" and "420" in a[1] for a in audits)


def test_delai_zero_arret_immediat(monkeypatch, tmp_path):
    arrets, audits = _keeper(monkeypatch, tmp_path, "CRITIQUE", 3)
    K.claim_docker("wj_a")
    K.release_claim("wj_a")
    assert arrets == [1] and not _ra().exists() and not K.WANT_FLAG.exists()
    assert any("CRITIQUE" in a[1] for a in audits)


def test_une_reclamation_restante_ne_pose_rien(monkeypatch, tmp_path):
    arrets, _ = _keeper(monkeypatch, tmp_path)
    K.claim_docker("a")
    K.claim_docker("b")
    assert K.release_claim("a")["released"] is False
    assert not _ra().exists() and arrets == []


def test_claim_annule_release_at(monkeypatch, tmp_path):
    arrets, audits = _keeper(monkeypatch, tmp_path)
    K.claim_docker("a")
    K.release_claim("a")
    assert _ra().exists()
    K.claim_docker("b")
    assert not _ra().exists() and K.WANT_FLAG.exists() and arrets == []
    assert any(a[0] == "release_annule" for a in audits)


def test_pendant_la_grace_docker_wanted_reste_retire(monkeypatch, tmp_path):
    _keeper(monkeypatch, tmp_path)
    K.claim_docker("a")
    K.release_claim("a")
    assert not K.WANT_FLAG.exists()


# -- tick : echeance ----------------------------------------------------------
def test_tick_n_arrete_pas_avant_l_echeance(monkeypatch, tmp_path):
    arrets, _ = _keeper(monkeypatch, tmp_path, "CALME", 0)
    K.claim_docker("a")
    K.release_claim("a")
    d = json.loads(_ra().read_text(encoding="utf-8"))
    assert K._tick_release_at(d["echeance"] - 10) is None
    assert arrets == [] and _ra().exists()


def test_tick_arrete_a_l_echeance(monkeypatch, tmp_path):
    arrets, audits = _keeper(monkeypatch, tmp_path, "CALME", 0)
    K.claim_docker("a")
    K.release_claim("a")
    d = json.loads(_ra().read_text(encoding="utf-8"))
    r = K._tick_release_at(d["echeance"] + 1)
    assert arrets == [1] and r and not _ra().exists()
    assert any(a[0] == "release" and "echeance" in a[1] for a in audits)


def test_tick_n_arrete_pas_si_une_reclamation_est_revenue(monkeypatch, tmp_path):
    arrets, _ = _keeper(monkeypatch, tmp_path)
    K.claim_docker("a")
    K.release_claim("a")
    d = json.loads(_ra().read_text(encoding="utf-8"))
    K._ecrire_claims(["b"])  # reclamation revenue sans passage par claim_docker
    assert K._tick_release_at(d["echeance"] + 1) is None
    assert arrets == [] and not _ra().exists()


def test_tick_avance_l_arret_si_le_palier_se_degrade(monkeypatch, tmp_path):
    arrets, _ = _keeper(monkeypatch, tmp_path, "CALME", 2)
    K.claim_docker("a")
    K.release_claim("a")
    d = json.loads(_ra().read_text(encoding="utf-8"))
    monkeypatch.setattr(K, "palier_courant", lambda: "DETRESSE")
    assert K._tick_release_at(d["echeance"] - 300) is not None
    assert arrets == [1]


def test_release_at_illisible_n_arrete_rien_et_se_dit(monkeypatch, tmp_path):
    arrets, audits = _keeper(monkeypatch, tmp_path)
    _ra().write_text("{pas du json", encoding="utf-8")
    assert K._tick_release_at(10 ** 12) is None
    assert arrets == []
    assert any(a[0] == "release_at_illisible" for a in audits)


def test_palier_courant_reutilise_palier_pression_ram(monkeypatch):
    import nokido_agent.app.forge_resource_manager as R
    monkeypatch.setattr(R, "get_snapshot", lambda: {"ram_pct": 90.0, "ram_free_gb": 5.0})
    assert K.palier_courant() == "GENE"
    monkeypatch.setattr(R, "get_snapshot", lambda: {"ram_pct": 50.0, "ram_free_gb": 0.3})
    assert K.palier_courant() == "CRITIQUE"

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(R, "get_snapshot", boom)
    assert K.palier_courant() == "ILLISIBLE"
