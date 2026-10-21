# -*- coding: utf-8 -*-
"""NR -- decision owner 19/10 sur crawl4ai : plus de redemarrage automatique, memoire bornee, image epinglee.

Constat (journal du 19/10) : 30 demarrages A LA DEMANDE par crawl4ai.wanted -- le reveil a la demande marche,
`restart: always` n'est plus le mecanisme de reveil, il ne fait plus que relancer crawl4ai a chaque reveil de
Docker, meme sans besoin. Decision owner : « les trois » -- restart:no + mem_limit + image epinglee.

Contrat (tools/forge_docker_keeper.py, aucun module neuf) :
  1. apres un `docker start` reussi, le keeper pose `docker update --restart=no --memory=M --memory-swap=M` sur le
     conteneur EXISTANT (M = NOKIDO_CRAWL4AI_MEM, defaut 3g) -- jamais de recreation ;
  2. l'image est EPINGLEE par empreinte : le digest vu au premier demarrage est note (CRAWL4AI_EPINGLE) ; un digest
     different ensuite est DIT (verdict image_derive), jamais adopte en silence ; digest illisible = INCONNU ;
  3. un `docker update` en echec est dit dans le detail, il ne masque pas le demarrage.
"""
import json
import os
import time

from nokido_agent.tools import forge_docker_keeper as k


def _flag(tmp_path):
    p = tmp_path / "crawl4ai.wanted"
    p.write_text("x", encoding="utf-8")
    t = time.time() - 10
    os.utime(p, (t, t))
    return p


def _cli(appels, digest="sha256:aaa", update_rc=0):
    def faux(args):
        appels.append(args)
        if args[:2] == ["ps", "-a"]:
            return 0, "nokido-crawl4ai-1"
        if args[:1] == ["inspect"]:
            return 0, digest
        if args[:1] == ["update"]:
            return update_rc, "" if update_rc == 0 else "Error response from daemon"
        return 0, ""
    return faux


def _preparer(monkeypatch, tmp_path, appels, **kw):
    monkeypatch.setattr(k, "CRAWL4AI_FLAG", _flag(tmp_path))
    monkeypatch.setattr(k, "CRAWL4AI_EPINGLE", tmp_path / "crawl4ai_image_epinglee.json")
    monkeypatch.setattr(k, "_docker_cli", _cli(appels, **kw))
    monkeypatch.setitem(k._STATE, "last_crawl4ai_start_ts", 0.0)
    monkeypatch.delenv("NOKIDO_CRAWL4AI_MEM", raising=False)


def test_restart_no_et_memoire_bornee_apres_demarrage(monkeypatch, tmp_path):
    appels = []
    _preparer(monkeypatch, tmp_path, appels)
    r = k._demarrer_crawl4ai(1000.0)
    assert r["verdict"] == "DEMARRE"
    assert ["update", "--restart=no", "--memory=3g", "--memory-swap=3g", "nokido-crawl4ai-1"] in appels
    i_start = appels.index(["start", "nokido-crawl4ai-1"])
    assert any(a[:1] == ["update"] for a in appels[i_start:]), "la politique se pose apres le demarrage"
    assert not any(a and a[0] in ("run", "create", "compose", "rm") for a in appels)


def test_image_epinglee_au_premier_demarrage_puis_derive_dite(monkeypatch, tmp_path):
    appels = []
    _preparer(monkeypatch, tmp_path, appels, digest="sha256:aaa")
    k._demarrer_crawl4ai(1000.0)
    assert json.loads(k.CRAWL4AI_EPINGLE.read_text(encoding="utf-8"))["digest"] == "sha256:aaa"
    _preparer(monkeypatch, tmp_path, appels, digest="sha256:bbb")
    r = k._demarrer_crawl4ai(5000.0)
    assert r.get("image") == "image_derive"
    assert json.loads(k.CRAWL4AI_EPINGLE.read_text(encoding="utf-8"))["digest"] == "sha256:aaa"   # jamais adopte


def test_update_en_echec_est_dit_sans_masquer_le_demarrage(monkeypatch, tmp_path):
    appels = []
    _preparer(monkeypatch, tmp_path, appels, update_rc=1)
    r = k._demarrer_crawl4ai(1000.0)
    assert r["verdict"] == "DEMARRE" and r.get("politique") == "ECHEC"
