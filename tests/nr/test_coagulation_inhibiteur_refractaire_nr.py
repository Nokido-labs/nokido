"""NR -- la coagulation a un INHIBITEUR et une PERIODE REFRACTAIRE (fin de la CIVD du 20/10).

Mesure 20/10 : forge_remediation emettait embed_consolidation_debt et oauth_cli_atrophy a chaque cycle ;
forge_coagulation._triage les classait « heal » (_REMEDIABLE contient embed et oauth) et relancait
run_remediation_cycle -- qui reemettait les memes signaux : cascade sans inhibiteur, toutes les ~5 min, avec un
balayage de 46 Go a chaque tour (owner : « usures disques abusives » ; « imiter la coagulation du corps »).
Dans le corps : (1) les anticoagulants empechent un caillot de s'auto-entretenir -- un signal produit PAR le soin
n'est pas une nouvelle lesion ; (2) apres une reponse, une periode refractaire. L'alarme, elle, n'est jamais eteinte :
un signal de securite ou de service emis par la remediation s'escalade toujours.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_coagulation as C  # noqa: E402


def test_un_signal_produit_par_le_soin_ne_relance_pas_le_soin():
    ev = {"kind": "embed_consolidation_debt", "severity": "warn",
          "payload": '{"vector_pending": 9000, "origine": "forge_remediation"}'}
    assert C._triage(ev)[0] == "ack"


def test_une_lesion_exterieure_reste_soignee():
    ev = {"kind": "embed_consolidation_debt", "severity": "warn", "payload": '{"vector_pending": 9000}'}
    assert C._triage(ev)[0] == "heal"


def test_l_alarme_du_soin_s_escalade_toujours():
    ev = {"kind": "service_down", "severity": "high", "payload": '{"origine": "forge_remediation"}'}
    assert C._triage(ev)[0] == "escalate"


def test_la_remediation_signe_ses_signaux(monkeypatch):
    import nokido_agent.app.forge_critical_events as CE
    import forge_remediation as R

    vus = []
    monkeypatch.setattr(CE, "persist", lambda kind, sev, payload: vus.append(payload) or 1)
    R._signal("embed_consolidation_debt", "warn", {"vector_pending": 1})
    assert vus and vus[0].get("origine") == "forge_remediation", vus


def _brancher(monkeypatch, tmp_path, horloge):
    import nokido_agent.app.forge_critical_events as CE
    import nokido_agent.app.forge_remediation as RM

    lots = {"n": 0}

    def unprocessed(limit):  # une lesion exterieure a chaque passe (un lot < limit : une seule lecture par passe)
        lots["n"] += 1
        return [{"id": lots["n"], "kind": "orphan_lock", "severity": "warn", "payload": "{}"}]

    soins = []
    monkeypatch.setattr(CE, "unprocessed", unprocessed)
    monkeypatch.setattr(CE, "mark_processed", lambda ids: len(ids))
    monkeypatch.setattr(CE, "purge_older_than", lambda j: 0)
    monkeypatch.setattr(RM, "run_remediation_cycle", lambda armed=False: soins.append(1) or {"ok": True})
    monkeypatch.setattr(C, "_log", lambda *a, **k: None)
    monkeypatch.setattr(C, "_REFRACTAIRE", tmp_path / "refractaire.json", raising=False)
    monkeypatch.setattr(C.time, "time", lambda: horloge["t"])
    return soins


def test_periode_refractaire_entre_deux_soins(tmp_path, monkeypatch):
    horloge = {"t": 1_000_000.0}
    soins = _brancher(monkeypatch, tmp_path, horloge)
    C.coagulate()
    horloge["t"] += 60
    out = C.coagulate()
    assert len(soins) == 1, "un 2e soin complet 60 s apres le 1er : pas de periode refractaire"
    assert "refractaire" in str(out.get("remediation", "")).lower(), out
    horloge["t"] += C.REFRACTAIRE_S + 1
    C.coagulate()
    assert len(soins) == 2, "passe la periode refractaire, une nouvelle lesion est de nouveau soignee"
