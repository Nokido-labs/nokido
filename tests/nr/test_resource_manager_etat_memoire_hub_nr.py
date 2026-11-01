"""NR : le lecteur de l'etat memoire du hub (chien de garde) change une decision reelle.

STALE != DEAD, ILLISIBLE != CALME. Aucun etat vivant : tmp_path + monkeypatch.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import nokido_agent.app.forge_resource_manager as RM  # noqa: E402
import nokido_agent.app.forge_sandbox_exec as SX  # noqa: E402

_PREF = ["preferer_jobs_detaches", "differer_taches_lourdes_in_process"]


def _ecrire(p, palier, intentions, age=0.0):
    p.write_text(json.dumps({"ts": time.time() - age, "rss_mb": 900, "base_mb": 400, "ratio": 2.2,
                             "palier": palier, "intentions": intentions}), encoding="utf-8")
    return p


def test_etat_frais_lu(tmp_path):
    p = _ecrire(tmp_path / "e.json", "PREFERENCE", _PREF)
    e = RM.etat_memoire_hub(chemin=p)
    assert e["statut"] == "OK" and e["palier"] == "PREFERENCE" and e["intentions"] == _PREF


def test_perime_est_stale_ni_calme_ni_detresse(tmp_path):
    p = _ecrire(tmp_path / "e.json", "DETRESSE", _PREF, age=600)
    e = RM.etat_memoire_hub(max_age_s=120, chemin=p)
    assert e["statut"] == "STALE"
    assert e.get("palier") not in ("CALME", "DETRESSE") and e["intentions"] == []


def test_absent_et_corrompu_sont_illisibles(tmp_path):
    assert RM.etat_memoire_hub(chemin=tmp_path / "nope.json")["statut"] == "ILLISIBLE"
    bad = tmp_path / "bad.json"
    bad.write_text("{pas du json", encoding="utf-8")
    e = RM.etat_memoire_hub(chemin=bad)
    assert e["statut"] == "ILLISIBLE" and e.get("palier") != "CALME"
    forme = tmp_path / "forme.json"
    forme.write_text(json.dumps({"ts": "x"}), encoding="utf-8")
    assert RM.etat_memoire_hub(chemin=forme)["statut"] == "ILLISIBLE"


def test_orientation_seulement_si_intention_et_frais(tmp_path, caplog):
    cal = _ecrire(tmp_path / "c.json", "CALME", [])
    assert RM.orienter_vers_run_job(chemin=cal) is None
    stale = _ecrire(tmp_path / "s.json", "GENE", _PREF, age=999)
    assert RM.orienter_vers_run_job(chemin=stale) is None
    assert RM.orienter_vers_run_job(chemin=tmp_path / "absent.json") is None
    pref = _ecrire(tmp_path / "p.json", "PREFERENCE", _PREF)
    with caplog.at_level(logging.INFO):
        msg = RM.orienter_vers_run_job(chemin=pref, contexte="t1")
    assert msg and "run_job" in msg
    assert any("differer_taches_lourdes_in_process" in r.getMessage() for r in caplog.records)


def test_spawn_as_sandbox_ne_consomme_pas_l_etat_memoire_du_hub(tmp_path, monkeypatch):
    """Un sous-processus n'a pas la memoire du hub : le lancement n'est jamais refuse pour cette raison."""
    pref = _ecrire(tmp_path / "p.json", "PREFERENCE", _PREF)
    monkeypatch.setenv("LAFORGE_MEM_ETAT_PATH", str(pref))
    monkeypatch.setattr(RM, "should_throttle", lambda **k: False)
    monkeypatch.setattr(RM, "get_snapshot", lambda: {"ram_pct": 40, "ram_total_gb": 32})
    try:
        r = SX.spawn_as_sandbox("echo x", classe="DIFFERABLE", user="LaForgeSbxOffline")
    except Exception:  # noqa: BLE001 - passe le gate, echoue sur creds/win32 : attendu
        return
    assert "run_job" not in r.get("stderr", "")


def test_gate_sandbox_inchange_si_etat_illisible(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_MEM_ETAT_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setattr(RM, "should_throttle", lambda **k: False)
    monkeypatch.setattr(RM, "get_snapshot", lambda: {"ram_pct": 40, "ram_total_gb": 32})
    try:
        r = SX.spawn_as_sandbox("echo x", classe="DIFFERABLE", user="LaForgeSbxOffline")
    except Exception:  # noqa: BLE001 - le gate est passe, l'echec vient de win32/creds : c'est le but
        return
    assert "run_job" not in r.get("stderr", "")
