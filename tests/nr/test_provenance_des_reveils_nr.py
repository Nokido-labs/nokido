"""NR -- qui reveille quoi, et pourquoi : la provenance d'un reveil est INFAILLIBLE (owner 19/10).

« c'est inadmissible qu'il n'y ait pas d'observabilite infaillible sur qui lance quoi et pourquoi ». Mesure du
jour : Docker reveille par `crawl4ai.wanted`, seule trace = `forge_docker_agent.demander_crawl4ai:forge_crawl_tool`
-- un MODULE, ni processus, ni job, ni test, ni motif. Il a fallu croiser l'audit du hub (muet : appel hors HTTP)
et la fenetre d'un job pour trouver le coupable (un test de ma CI impactee qui jouait toute la suite).

Contrat, au point de passage de TOUTES les emissions (`forge_signal_coupling.emit_signal`) :
  * un REVEIL (`*.wanted`) journalise sa provenance : pid, ppid, processus, job (LAFORGE_JOB_ID), test en cours
    (PYTEST_CURRENT_TEST), agent, pile d'appel, motif -- motif absent = "INCONNU" DIT, jamais vide ;
  * un pouls n'en journalise pas (cardinalite) ;
  * `qui_a_reveille(signal)` rend les dernieres provenances, la plus recente d'abord : la reponse a « qui a lance ».
"""
from __future__ import annotations

import os

import pytest

import forge_signal_coupling as sc  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        try:
            mod = __import__("importlib").import_module(nom)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "DB", tmp_path / "signal_emissions.db", raising=False)
    monkeypatch.setenv("LAFORGE_JOB_ID", "job_test42")


def test_un_reveil_dit_qui_ou_et_pourquoi(base):
    assert sc.emit_signal("crawl4ai.wanted", emitter="forge_docker_agent.demander_crawl4ai",
                          motif="crawl de veille demande par l'outil crawl")
    p = sc.qui_a_reveille("crawl4ai.wanted")[0]
    assert p["pid"] == os.getpid() and p["ppid"] == os.getppid()
    assert p["job"] == "job_test42"
    assert "test_un_reveil_dit_qui_ou_et_pourquoi" in (p["test"] or "")
    assert p["motif"] == "crawl de veille demande par l'outil crawl"
    assert p["processus"] and p["pile"]
    assert p["emetteur"] == "forge_docker_agent.demander_crawl4ai"


def test_motif_absent_est_inconnu_dit(base):
    sc.emit_signal("docker.wanted", emitter="x")
    assert sc.qui_a_reveille("docker.wanted")[0]["motif"] == "INCONNU"


def test_un_pouls_ne_journalise_pas_de_provenance(base):
    sc.emit_signal("crawl4ai.wanted", emitter="temoin")  # temoin positif : la table existe
    sc.emit_signal("harness_worker.heartbeat", emitter="t")
    assert sc.qui_a_reveille("harness_worker.heartbeat") == []
    assert len(sc.qui_a_reveille("crawl4ai.wanted")) == 1


def test_le_plus_recent_d_abord(base):
    sc.emit_signal("llama.wanted", emitter="a", motif="premier", ts=1000.0)
    sc.emit_signal("llama.wanted", emitter="b", motif="second", ts=2000.0)
    assert [p["motif"] for p in sc.qui_a_reveille("llama.wanted")] == ["second", "premier"]
