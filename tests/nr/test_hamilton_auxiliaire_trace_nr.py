# -*- coding: utf-8 -*-
"""NR 2026-11-04 (owner « Hamilton et PI : mesurer » -> « tracer + prolonger ») -- le delestage AUXILIAIRE de Hamilton
(c02568264, NON_SOI + detresse, EN OBSERVATION) est calcule par ordre_delestage et remonte par plan_hamilton, mais le
tick n'ecrivait que verdict/n_candidats dans regulation_tick.jsonl : une observation SANS TRACE (0 ligne mesurable
depuis le 3/11). Contrat : quand le plan porte `auxiliaire_observe`, la ligne du tick la porte (service, classe,
grandeur) ; sinon la cle est absente."""
import json

from nokido_agent.app import forge_resource_manager as RM


def _tick(tmp_path, monkeypatch, plan):
    journal = tmp_path / "regulation_tick.jsonl"
    monkeypatch.setattr(RM, "_REGULATION_TICK_PATH", journal)
    monkeypatch.setattr(RM, "_HAMILTON_ETAT_RAM_PATH", tmp_path / "etat.json")
    monkeypatch.setattr(RM, "_registre_corps", lambda: {})
    monkeypatch.setattr(RM, "_SNAPSHOT", {"ram_pct_plancher_60s": 99.0, "ram_free_gb": 1.0, "ram_total_gb": 32.0},
                        raising=False)
    monkeypatch.setattr(RM, "plan_hamilton", lambda *a, **k: plan)
    monkeypatch.setattr(RM, "palier_pression_ram", lambda *a, **k: "HAUT")
    monkeypatch.setattr(RM, "publier_palier_pression", lambda *a, **k: False)
    monkeypatch.setattr(RM, "vetos_sommeil_actifs", lambda: [])
    monkeypatch.setattr(RM, "regulation_hamilton_ram", lambda *a, **k: {"gestes": {}, "etat": {}, "motif": "obs"})
    RM._regulation_hamilton_tick()
    return [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_tick_trace_l_auxiliaire_observe(tmp_path, monkeypatch):
    plan = {"verdict": "NON_SOI", "delester": [], "auxiliaire_observe": [
        {"service": "NokidoSoif", "classe": "DIFFERABLE", "rss_mb": 812.0},
        {"service": "NokidoVeille", "classe": "DIFFERABLE", "rss_mb": 300.0}]}
    lignes = _tick(tmp_path, monkeypatch, plan)
    assert lignes and lignes[-1]["verdict"] == "NON_SOI"
    assert [x["service"] for x in lignes[-1]["auxiliaire_observe"]] == ["NokidoSoif", "NokidoVeille"], lignes[-1]
    assert lignes[-1]["auxiliaire_observe"][0]["rss_mb"] == 812.0


def test_sans_auxiliaire_pas_de_cle(tmp_path, monkeypatch):
    lignes = _tick(tmp_path, monkeypatch, {"verdict": "SOI", "delester": []})
    assert lignes and "auxiliaire_observe" not in lignes[-1]
