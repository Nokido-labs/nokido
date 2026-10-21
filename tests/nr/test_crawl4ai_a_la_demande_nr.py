# -*- coding: utf-8 -*-
"""NR : crawl4ai demarre A LA DEMANDE par un drapeau crawl4ai.wanted (roadmap P2 crawl4ai, 19/10).

Aujourd'hui son seul demarreur est `restart: always` : il se leve a chaque reveil de Docker,
meme pour une recherche SearXNG seule (3,29 Go de vmmemWSL mesures le 15/10). Premier pas :
l'outil de crawl pose crawl4ai.wanted, le keeper `docker start` le conteneur EXISTANT (jamais
de creation : un second conteneur volerait le port 11235). Retirer `restart: always` vient
APRES, sur decision owner.
"""
import os
import time

import pytest

from nokido_agent.tools import forge_docker_keeper as k  # import reel : un importorskip SAUTAIT (RED muet)
from nokido_agent.app import forge_docker_agent as agent


def _flag(tmp_path, age_s):
    p = tmp_path / "crawl4ai.wanted"
    p.write_text("x", encoding="utf-8")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_drapeau_frais_veut_crawl4ai_et_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", _flag(tmp_path, 10))
    monkeypatch.setattr(k, "WANT_FLAG", tmp_path / "absent.wanted")
    monkeypatch.setattr(k, "AUTO_LAUNCH", False)
    assert k._crawl4ai_voulu() is True
    assert k._docker_wanted() is True


def test_drapeau_perime_ou_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", _flag(tmp_path, k.WANT_TTL_S + 60))
    assert k._crawl4ai_voulu() is False
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", tmp_path / "rien.wanted")
    assert k._crawl4ai_voulu() is False


def test_keeper_demarre_le_conteneur_existant_une_fois(monkeypatch, tmp_path):
    appels = []

    def faux_cli(args):
        appels.append(args)
        if args[:2] == ["ps", "-a"]:
            return 0, "nokido-crawl4ai-1"
        return 0, ""
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", _flag(tmp_path, 10))
    monkeypatch.setattr(k, "_docker_cli", faux_cli)
    monkeypatch.setitem(k._STATE, "last_crawl4ai_start_ts", 0.0)
    r = k._demarrer_crawl4ai(1000.0)
    assert r["verdict"] == "DEMARRE" and ["start", "nokido-crawl4ai-1"] in appels
    assert not any(a and a[0] in ("run", "create", "compose") for a in appels)
    n = len(appels)
    assert k._demarrer_crawl4ai(1010.0) is None and len(appels) == n  # refractaire


def test_keeper_sans_conteneur_le_dit_sans_creer(monkeypatch, tmp_path):
    appels = []
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", _flag(tmp_path, 10))
    monkeypatch.setattr(k, "_docker_cli", lambda a: (appels.append(a), (0, ""))[1])
    monkeypatch.setitem(k._STATE, "last_crawl4ai_start_ts", 0.0)
    assert k._demarrer_crawl4ai(5000.0)["verdict"] == "ABSENT"
    assert not any(a[0] == "start" for a in appels)


def test_keeper_ne_demarre_rien_sans_demande(monkeypatch, tmp_path):
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", tmp_path / "rien.wanted")
    monkeypatch.setattr(k, "_docker_cli", lambda a: pytest.fail("aucun appel docker sans demande"))
    assert k._demarrer_crawl4ai(9000.0) is None


def test_outil_de_crawl_reclame_crawl4ai_injoignable(monkeypatch):
    import urllib.request
    from nokido_agent.app import forge_crawl_tool as ct

    demandes = []
    monkeypatch.setattr(agent, "demander_crawl4ai", lambda par, lancer=True: demandes.append(lancer) or True)

    def injoignable(*a, **k):
        raise OSError("refuse")
    monkeypatch.setattr(urllib.request, "urlopen", injoignable)
    monkeypatch.setattr(ct, "_url_interdite", lambda u: None)  # gardes amont hors sujet ici
    monkeypatch.setattr(ct, "_robots_decision", lambda u: {"autorise": True, "motif": ""})
    try:
        ct.crawl_url_detail("https://example.org/page", 2, _fulltext_tried=True)
    except Exception:
        pass  # le repli peut echouer hors ligne ; seule compte la demande
    assert demandes and demandes[0] is True


def test_agent_pose_le_drapeau_et_ne_lance_que_sur_demande(monkeypatch, tmp_path):
    lances = []
    monkeypatch.setattr(agent, "CRAWL4AI_FLAG", tmp_path / "crawl4ai.wanted")
    monkeypatch.setattr(agent, "ensure_daemon", lambda: lances.append(1) or {"ok": True})
    assert agent.demander_crawl4ai("test", lancer=False) is True
    assert (tmp_path / "crawl4ai.wanted").exists() and lances == []
    agent.demander_crawl4ai("test", lancer=True)
    assert lances == [1]
