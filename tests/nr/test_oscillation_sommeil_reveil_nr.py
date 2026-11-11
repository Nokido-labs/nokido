# -*- coding: utf-8 -*-
"""NR 2026-11-07 -- oscillation sommeil/reveil de l'executif Hamilton (alertes de flaps, 502 du connecteur claude.ai).

Mesure 7/11 (sandbox/lifecycle_actions.jsonl, callers `_regulation_hamilton_tick:6037` ; sandbox/supervisor_ordres.jsonl,
agent_declare RESOURCE_MANAGER, secret supervisor) :
  00:33:58Z hamilton_arme « 33 service(s) pour 4920 Mo a rendre (1861 Mo vises) » -> 33 POST /sleep en 3 s, dont
            NokidoCaddyTLS (entree OAuth publique, gain negligeable) : la somme des candidats (1,8 Go, ~56 Mo chacun)
            n'atteignait jamais le besoin, la boucle les prenait TOUS ;
  00:53:18Z forge_docker_keeper vidage_ws_qdrant (EmptyWorkingSet, 5,43 Go de cache mappe rendus, RAM 84,1 %) ;
  00:53:29Z hamilton_arme « RAM 58.3 % : 33 reprise(s) dans le budget (plafond 73 %) » -> 33 POST /service/start ;
  00:55:40Z le cache de Qdrant se remplit, 35 services rendormis. Deux minutes de reveil, 23 demarrages de Caddy le 6/11.
Contrat (regle owner 31/10 : reveil par la DEMANDE, budget projete, jamais en bloc ni par un seuil seul) :
  (a) un service dont le gain MESURE est negligeable n'est pas endormi (meme grandeur que DELESTAGE_GAIN_MIN_KO de
      supervisor.ts) ; NokidoCaddyTLS est neverSleep dans services.toml (registre existant -> classe VITAL) ;
  (b) reprise par petits lots, et jamais avant une duree minimale de sommeil ;
  (c) chaque sommeil et chaque reveil est journalise : service, gain mesure, motif.
Chemin reel : `_regulation_hamilton_tick` -> `regulation_hamilton_ram` -> `gestes_observes` -> `_admettre_reprises` ->
`_ordre_superviseur` (capture), plan construit par le vrai `ordre_delestage`.
"""
# pylint: disable=protected-access,missing-function-docstring
import json
import time

from nokido_agent.app import forge_resource_manager as rm

TOTAL_GB = 23.7


def _candidats():
    """La fenetre du 7/11 : 30 petits DIFFERABLE (~40-60 Mo), Caddy (~25 Mo), trois gros."""
    c = [{"service": "NokidoPetit%02d" % i, "classe": "DIFFERABLE", "rss_mb": 40.0 + (i % 20)} for i in range(30)]
    c.append({"service": "NokidoCaddyTLS", "classe": "DIFFERABLE", "rss_mb": 25.0})
    c += [{"service": "NokidoGros1", "classe": "DIFFERABLE", "rss_mb": 300.0},
          {"service": "NokidoGros2", "classe": "DIFFERABLE", "rss_mb": 200.0},
          {"service": "NokidoGros3", "classe": "DIFFERABLE", "rss_mb": 150.0}]
    return c


def _tick(tmp_path, monkeypatch, ram_pct, etat=None, sous_pression_plan=True):
    ordres, audits = [], []
    etat_path = tmp_path / "hamilton_pauses_ram.json"
    if etat is not None:
        etat_path.write_text(json.dumps(etat), encoding="utf-8")
    monkeypatch.setattr(rm, "_HAMILTON_ETAT_RAM_PATH", etat_path)
    monkeypatch.setattr(rm, "_REGULATION_TICK_PATH", tmp_path / "regulation_tick.jsonl")
    monkeypatch.setattr(rm, "_registre_corps", lambda: {})
    monkeypatch.setattr(rm, "_SNAPSHOT", {"ram_pct_plancher_60s": ram_pct, "ram_pct": ram_pct, "ram_free_gb": 4.0,
                                          "ram_total_gb": TOTAL_GB}, raising=False)
    plan = (dict(rm.ordre_delestage(_candidats(), "SOI"), mode="OBSERVATION", verdict="SOI")  # = plan_hamilton
            if sous_pression_plan else {"verdict": None, "delester": []})
    monkeypatch.setattr(rm, "plan_hamilton", lambda *a, **k: plan)
    monkeypatch.setattr(rm, "publier_palier_pression", lambda *a, **k: True)
    monkeypatch.setattr(rm, "vetos_sommeil_actifs", lambda: {})
    monkeypatch.setattr(rm, "_demande_du_service", lambda s: None)
    monkeypatch.setattr(rm, "_ordre_superviseur", lambda svc, geste: ordres.append((svc, geste)))
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda action, domain, reason="", **kw: audits.append(
        dict(kw, action=action, domain=domain, reason=reason)))
    r = rm._regulation_hamilton_tick()
    return r, ordres, audits


def _pause(depuis_s, calme_depuis_s, rss=56.0):
    now = time.time()
    return {"pause_ts": now - depuis_s, "calme_ts": now - calme_depuis_s, "rechutes": 0, "rss_mb": rss}


def test_gain_negligeable_jamais_endormi_ni_caddy(tmp_path, monkeypatch):
    # 80 % : besoin (80-65) % de 23,7 Go = 3,6 Go > somme des candidats -> avant : les 34 endormis d'un coup
    _r, ordres, _a = _tick(tmp_path, monkeypatch, 80.0)
    dormis = {s for s, g in ordres if g == "SUSPENDRE"}
    assert dormis == {"NokidoGros1", "NokidoGros2", "NokidoGros3"}, sorted(dormis)
    assert "NokidoCaddyTLS" not in {s for s, _g in ordres}


def test_caddy_est_never_sleep_au_registre_existant():
    toml = rm._services_du_toml()
    assert toml is not None and "NokidoCaddyTLS" in toml
    assert toml["NokidoCaddyTLS"].get("neverSleep") is True
    assert rm.classe_hamilton(toml["NokidoCaddyTLS"]) == "VITAL"


def test_chute_de_ram_ne_reveille_qu_un_petit_lot(tmp_path, monkeypatch):
    # 00:53:29Z : 33 services en pause depuis 20 min, calme ecoule, RAM tombee a 58,3 % (vidage du cache Qdrant)
    etat = {"NokidoPetit%02d" % i: _pause(1200, 600) for i in range(33)}
    _r, ordres, _a = _tick(tmp_path, monkeypatch, 58.3, etat=etat, sous_pression_plan=False)
    repris = [s for s, g in ordres if g == "REPRENDRE"]
    assert 0 < len(repris) <= rm._HAMILTON_REPRISE_LOT <= 3, repris


def test_duree_minimale_de_sommeil(tmp_path, monkeypatch):
    # endormi il y a 200 s, calme ecoule (130 s > 120 s), RAM tres basse : la duree minimale de sommeil le garde
    etat = {"NokidoRecent": _pause(200, 130)}
    _r, ordres, _a = _tick(tmp_path, monkeypatch, 40.0, etat=etat, sous_pression_plan=False)
    assert ("NokidoRecent", "REPRENDRE") not in ordres
    assert rm._HAMILTON_SOMMEIL_MIN_S >= 300
    etat = {"NokidoAncien": _pause(rm._HAMILTON_SOMMEIL_MIN_S + 10, 130)}
    _r, ordres, _a = _tick(tmp_path, monkeypatch, 40.0, etat=etat, sous_pression_plan=False)
    assert ("NokidoAncien", "REPRENDRE") in ordres


def test_chaque_sommeil_et_reveil_est_journalise(tmp_path, monkeypatch):
    _r, ordres, audits = _tick(tmp_path, monkeypatch, 80.0)
    sommeils = [a for a in audits if a["action"] == "hamilton_sommeil"]
    assert {a["target"] for a in sommeils} == {s for s, g in ordres if g == "SUSPENDRE"}
    gros1 = next(a for a in sommeils if a["target"] == "NokidoGros1")
    assert gros1["gain_mb"] == 300.0 and gros1["reason"]
    etat = {"NokidoPetit00": _pause(1200, 600, rss=80.0)}
    _r, ordres, audits = _tick(tmp_path, monkeypatch, 50.0, etat=etat, sous_pression_plan=False)
    reveils = [a for a in audits if a["action"] == "hamilton_reveil"]
    assert [a["target"] for a in reveils] == ["NokidoPetit00"] and ("NokidoPetit00", "REPRENDRE") in ordres
    assert reveils[0]["gain_mb"] == 80.0 and "budget" in reveils[0]["reason"]
