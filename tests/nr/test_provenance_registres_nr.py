"""NR -- la provenance d'un reveil s'inscrit dans les REGISTRES existants, pas dans une table a part (owner 19/10).

« si tu respectais bien les rfc ce trou ne devrait pas exister, les identites et les provenances doivent etre
tracees, et les intentions egalement. tu as normalement un registre de log, ne l'oublie pas ». Au commit acf8e4035
le gate firehose l'a dit aussi : `emissions_journal` et `provenances` absentes de forge_log_retention.

Contrat :
  * la provenance porte le contexte de trace W3C (TRACEPARENT, convention de propagation vers les processus) ;
  * un reveil est une INTENTION : il est inscrit au registre des intentions (forge_intention_journal.record,
    journal immuable chaine), intent_type "reveil", cible = le signal, motif et provenance dans la charge ;
  * le registre des logs (forge_log_retention._purge_signal_emissions) purge le journal date et les provenances
    au-dela de leur retention et DIT ce qu'il a retire ; les tables bornees par UPSERT restent sans purge.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_signal_coupling as sc  # noqa: E402

TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


@pytest.fixture
def base(tmp_path, monkeypatch):
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "DB", tmp_path / "signal_emissions.db", raising=False)
    monkeypatch.setenv("TRACEPARENT", TRACE)
    inscrits = []
    for nom in ("forge_intention_journal", "nokido_agent.app.forge_intention_journal"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "record", lambda *a, **k: inscrits.append((a, k)) or {"ok": True})
    return inscrits


def test_la_provenance_porte_le_traceparent(base):
    sc.emit_signal("docker.wanted", emitter="e", motif="m")
    assert sc.qui_a_reveille("docker.wanted")[0]["trace"] == TRACE


def test_un_reveil_est_inscrit_au_registre_des_intentions(base):
    sc.emit_signal("crawl4ai.wanted", emitter="forge_docker_agent.demander_crawl4ai", motif="veille")
    assert len(base) == 1
    a, k = base[0]
    tout = dict(zip(("agent", "intent_type", "target", "payload"), a)) | k
    assert tout["intent_type"] == "reveil" and tout["target"] == "crawl4ai.wanted"
    assert tout["payload"]["motif"] == "veille" and tout["payload"]["trace"] == TRACE
    assert tout["payload"]["pid"]


def test_un_pouls_n_est_pas_une_intention(base):
    sc.emit_signal("harness_worker.heartbeat", emitter="t")
    assert base == []


def test_le_registre_des_logs_purge_et_le_dit(tmp_path, monkeypatch):
    import forge_log_retention as lr

    monkeypatch.setattr(lr, "ROOT", tmp_path)
    (tmp_path / "sandbox").mkdir()
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "DB", tmp_path / "sandbox" / "signal_emissions.db", raising=False)
    vieux = time.time() - 400 * 86400
    sc.emit_signal("H", emitter="t", level=0.5, ttl_s=60, ts=vieux)
    sc.emit_signal("H", emitter="t", level=0.5, ttl_s=60)
    sc.emit_signal("docker.wanted", emitter="t", ts=vieux)
    sc.emit_signal("docker.wanted", emitter="t")
    r = lr._purge_signal_emissions(dry=False)
    assert r["emissions_journal_purges"] == 1 and r["provenances_purges"] == 1
    cx = sqlite3.connect(str(tmp_path / "sandbox" / "signal_emissions.db"))
    assert cx.execute("SELECT COUNT(*) FROM emissions_journal").fetchone()[0] == 1
    assert cx.execute("SELECT COUNT(*) FROM provenances").fetchone()[0] == 1
