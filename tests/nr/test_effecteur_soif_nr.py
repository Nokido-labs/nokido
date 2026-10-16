# -*- coding: utf-8 -*-
"""NR -- l'effecteur de soif : une douleur CHRONIQUE devient une enquete bornee, close par le CAPTEUR seul.

Debat tour 3 (AGY, Codex, swarm), decision Q4 ; owner 15/10 : « desarme, 1 enquete a blanc ».
Contrat, sur `effecteur_enquete` et le point d'entree `--enquete-a-blanc` :
  1. DESARME par defaut : il dit ce qu'il AURAIT confie, ne depose rien ;
  2. arme : une enquete deposee, puis BUDGET (au plus une par 24 h) ;
  3. recul 24 -> 48 -> 96 h par douleur ; 3 enquetes sans guerison -> QUARANTAINE_EPISTEMIQUE ;
  4. cloture par le CAPTEUR seul (absente 2 cycles) ; un capteur ILLISIBLE ne clot rien ;
     un rapport « RESOLU » est lu et note, il ne clot pas ;
  5. depot refuse -> BLOQUE_PAR_DEPENDANCE, aucune tentative comptee ; etat illisible -> rien depose ;
  6. `--enquete-a-blanc` n'avance AUCUN compteur de soin (il n'ecrit pas self_care_state.json).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = 3600.0
DOULEUR = {"fault": "Capacites : ratchet_check=REGRESSION", "cycles": 46, "sig": "9e12655ec128",
           "severity": "medium"}


def _demon():
    spec = importlib.util.spec_from_file_location("demon_effecteur_soif", RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def corps(tmp_path, monkeypatch):
    d = _demon()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setattr(d, "__file__", str(tmp_path / "tools" / "forge_epistemic_daemon.py"))
    monkeypatch.setattr(d, "_ETAT_SOIN", sandbox / "self_care_state.json")
    monkeypatch.setattr(d, "_EFFECTEUR_ETAT", sandbox / "enquetes" / "effecteur_etat.json")
    monkeypatch.setattr(d, "_WORKTREE_AGY", tmp_path / "agy")
    monkeypatch.delenv("LAFORGE_EFFECTEUR_ENQUETE", raising=False)
    (sandbox / "self_care_state.json").write_text(json.dumps({DOULEUR["sig"]: {"n": 46}}), encoding="utf-8")
    depots = []

    def deposer(description):
        depots.append(description)
        return {"task_id": "job_test_%d" % len(depots)}
    return d, depots, deposer, sandbox


def _etat(d):
    return json.loads(d._EFFECTEUR_ETAT.read_text(encoding="utf-8"))


def test_desarme_dit_ce_qu_il_aurait_confie_sans_deposer(corps):
    d, depots, deposer, _ = corps
    r = d.effecteur_enquete([DOULEUR], maintenant=1e9, deposer=deposer)
    assert r["etat"] == "DESARME" and r["aurait_confie"] == DOULEUR["sig"] and depots == []


def test_arme_depose_une_enquete_puis_budget(corps):
    d, depots, deposer, _ = corps
    r = d.effecteur_enquete([DOULEUR], maintenant=1e9, arme=True, deposer=deposer)
    assert r["etat"] == "DEPOSEE" and len(depots) == 1
    assert "LECTURE SEULE" in depots[0] and "VERDICT" in depots[0] and DOULEUR["sig"] in depots[0]
    e = _etat(d)["sigs"][DOULEUR["sig"]]
    assert e["statut"] == "ENQUETE_EN_COURS" and e["tentatives"] == 1 and e["prochaine_ts"] == 1e9 + 24 * H
    autre = dict(DOULEUR, sig="aaaaaaaaaaaa")
    r2 = d.effecteur_enquete([autre, DOULEUR], maintenant=1e9 + H, arme=True, deposer=deposer)
    assert r2["etat"] == "BUDGET" and len(depots) == 1


def test_recul_puis_quarantaine_apres_trois_enquetes(corps):
    d, depots, deposer, _ = corps
    t = 1e9
    for attendu_recul in (24, 48, 96):
        r = d.effecteur_enquete([DOULEUR], maintenant=t, arme=True, deposer=deposer)
        assert r["etat"] == "DEPOSEE", r
        e = _etat(d)["sigs"][DOULEUR["sig"]]
        assert e["prochaine_ts"] - t == attendu_recul * H
        t += 25 * H                                   # rapport absent apres 24 h (passe desarmee : constat seul)
        assert d.effecteur_enquete([DOULEUR], maintenant=t, arme=False, deposer=deposer)["evenements"]
        assert _etat(d)["sigs"][DOULEUR["sig"]]["statut"] == "RAPPORT_ABSENT"
        t = e["prochaine_ts"] + 1
    r = d.effecteur_enquete([DOULEUR], maintenant=t, arme=True, deposer=deposer)
    assert _etat(d)["sigs"][DOULEUR["sig"]]["statut"] == "QUARANTAINE_EPISTEMIQUE"
    assert r["ecartes"][DOULEUR["sig"]] == "QUARANTAINE_EPISTEMIQUE" and len(depots) == 3


def test_cloture_par_le_capteur_seul(corps):
    d, _depots, deposer, sandbox = corps
    d.effecteur_enquete([DOULEUR], maintenant=1e9, arme=True, deposer=deposer)
    rapport = d._WORKTREE_AGY / _etat(d)["sigs"][DOULEUR["sig"]]["rapport"]
    rapport.parent.mkdir(parents=True)
    rapport.write_text("cause etablie\nVERDICT: RESOLU\n", encoding="utf-8")
    r = d.effecteur_enquete([DOULEUR], maintenant=1e9 + H, deposer=deposer)
    e = _etat(d)["sigs"][DOULEUR["sig"]]
    assert e["statut"] == "RAPPORT_RENDU" and e["verdict"] == "RESOLU"   # note, PAS clos
    (sandbox / "self_care_state.json").write_text("{}", encoding="utf-8")     # la douleur a disparu
    d.effecteur_enquete([], maintenant=1e9 + 2 * H, deposer=deposer)
    assert _etat(d)["sigs"][DOULEUR["sig"]]["statut"] == "RAPPORT_RENDU"     # 1 cycle : pas encore
    d.effecteur_enquete([], maintenant=1e9 + 3 * H, deposer=deposer)
    assert _etat(d)["sigs"][DOULEUR["sig"]]["statut"] == "CLOS_PAR_LE_CAPTEUR"


def test_capteur_illisible_ne_clot_rien(corps):
    d, _depots, deposer, sandbox = corps
    d.effecteur_enquete([DOULEUR], maintenant=1e9, arme=True, deposer=deposer)
    (sandbox / "self_care_state.json").write_text("{illisible", encoding="utf-8")
    for k in range(3):
        d.effecteur_enquete([], maintenant=1e9 + (k + 1) * H, deposer=deposer)
    assert _etat(d)["sigs"][DOULEUR["sig"]]["statut"] != "CLOS_PAR_LE_CAPTEUR"


def test_depot_refuse_bloque_par_dependance_sans_tentative(corps):
    d, _depots, _deposer, _ = corps
    r = d.effecteur_enquete([DOULEUR], maintenant=1e9, arme=True, deposer=lambda _x: {"error": "401"})
    e = _etat(d)["sigs"][DOULEUR["sig"]]
    assert r["etat"] == "BLOQUE_PAR_DEPENDANCE" and e.get("tentatives", 0) == 0 and "401" in r["erreur"]


def test_etat_illisible_ne_depose_rien(corps):
    d, depots, deposer, _ = corps
    d._EFFECTEUR_ETAT.parent.mkdir(parents=True)
    d._EFFECTEUR_ETAT.write_text("{pas du json", encoding="utf-8")
    r = d.effecteur_enquete([DOULEUR], maintenant=1e9, arme=True, deposer=deposer)
    assert r["etat"] == "ETAT_ILLISIBLE" and depots == []


def test_enquete_a_blanc_n_avance_aucun_compteur(corps, monkeypatch, capsys):
    d, depots, _deposer, sandbox = corps
    (sandbox / "health_diagnostic.json").write_text(
        json.dumps({"gaps": ["⚠ Capacites : ratchet_check=REGRESSION"]}), encoding="utf-8")
    import re as _re, hashlib as _h
    clean = _re.sub(r"\s+", " ", _re.sub(r"[^\w\s:'\-\.\[\]]", " ", "⚠ Capacites : ratchet_check=REGRESSION")).strip()
    sig = _h.sha256(clean.encode()).hexdigest()[:12]
    avant = json.dumps({sig: {"n": 46, "sev_emise": None}})
    (sandbox / "self_care_state.json").write_text(avant, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["forge_epistemic_daemon.py", "--enquete-a-blanc"])
    assert d.main() == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["douleur"]["sig"] == sig and "LECTURE SEULE" in sortie["description"]
    assert (sandbox / "self_care_state.json").read_text(encoding="utf-8") == avant   # aucun compteur avance
    assert not d._EFFECTEUR_ETAT.exists() and depots == []
