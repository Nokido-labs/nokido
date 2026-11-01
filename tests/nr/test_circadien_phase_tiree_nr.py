"""NR -- une phase tiree hors de son creneau fait son travail, ou le dit et le rattrape (owner 31/10).

MESURE du 2026-10-31 : la CI de reference a fini rc=1 sur un seul gate, pip-audit NON MESURE -- rapport du
20/10, perime (> 7 j). Le runner circadien tirait bien NREM1 (19 h 21, « inactivite mesuree : NREM1 en
dette »), mais le handler du producteur lisait l'HORLOGE (fenetre 22 h - 2 h), rendait « hors phase », ne
lancait rien, et la phase se soldait quand meme. Meme defaut sur npsc (NREM1), specs (REM), fts (NREM3).

Choix owner : la phase TIREE decide pour pip_audit, npsc, specs ; la reconstruction FTS garde sa fenetre
(verrou RAG de 30 min de jour le 14/08) mais n'est plus muette : differee, notee, rattrapee dans son creneau,
sans garder NREM3 en dette (sinon re-tir toutes les 30 min, restarts compris).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_circadian as C  # noqa: E402


def _hors_test(monkeypatch):
    # Les handlers de production refusent de partir sous pytest : on retire CE garde-la seulement, DANS le corps
    # du test -- pytest reecrit PYTEST_CURRENT_TEST a chaque phase, une fixture le leverait pour rien.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(C, "current_phase", lambda now=None: C.Phase.CREPUSCULE)  # 19 h 21


def _etat_repose() -> "C.PhysiologicalState":
    st = C.PhysiologicalState()
    st.last_completed = {p: time.time() for p in C.Phase}
    return st


def test_nrem1_tiree_hors_creneau_lance_la_mesure_pip_audit(monkeypatch, tmp_path):
    _hors_test(monkeypatch)
    lances = []
    hist = tmp_path / "pip_audit_history"
    hist.mkdir()

    def lanceur(script, **kw):
        lances.append((script, kw))
        return {"job_id": "job_test"}

    monkeypatch.setattr(C, "PHASE_PROGRAM", {C.Phase.NREM1: [C.PhaseAction(
        "audit_dependances", None, handler=lambda: C._mesurer_dependances_vulnerables(hist=hist, lanceur=lanceur))]})
    res = C.fire_phase(C.Phase.NREM1, state=_etat_repose())
    [r] = res["results"]
    assert r["pip_audit"] == "REQUESTED"
    assert lances and lances[0][0] == "tools/forge_pip_audit_mesure.py"
    assert res["differees"] == []


def test_appele_hors_fire_phase_l_horloge_garde_toujours(monkeypatch, tmp_path):
    _hors_test(monkeypatch)
    r = C._mesurer_dependances_vulnerables(hist=tmp_path, lanceur=lambda *a, **k: pytest.fail("lance"))
    assert r["pip_audit"] == "hors phase"


def test_la_phase_tiree_ne_fuit_pas_apres_le_tir(monkeypatch):
    _hors_test(monkeypatch)
    monkeypatch.setattr(C, "PHASE_PROGRAM", {C.Phase.REM: []})
    C.fire_phase(C.Phase.REM, state=_etat_repose())
    assert C._phase_effective() is C.Phase.CREPUSCULE


def test_fts_hors_fenetre_est_differe_sans_garder_la_dette(monkeypatch):
    _hors_test(monkeypatch)
    monkeypatch.setattr(C, "PHASE_PROGRAM", {C.Phase.NREM3: [C.PhaseAction(
        "fts_rebuild", None, handler=C._reconstruire_index_fts)]})
    st = _etat_repose()
    res = C.fire_phase(C.Phase.NREM3, state=st)
    assert res["results"][0]["fts"] == "hors phase"
    assert res["completed"] is True                      # pas de dette : pas de re-tir toutes les 30 min
    assert st.differees == {C.Phase.NREM3: ["fts_rebuild"]}
    # inactif a 15 h : NREM3 n'est PAS re-tiree (pas de boucle)
    p, _raison = C.phase_a_tirer(datetime(2026, 10, 31, 15, 0), st, True)
    assert p is not C.Phase.NREM3


def test_le_creneau_rattrape_l_action_differee_une_fois(monkeypatch):
    monkeypatch.setattr(C, "current_phase", lambda now=None: C.Phase.NREM3)
    st = _etat_repose()
    st.differees = {C.Phase.NREM3: ["fts_rebuild"]}
    p, raison = C.phase_a_tirer(datetime(2026, 11, 1, 2, 30), st, True)
    assert p is C.Phase.NREM3 and "rattrapage" in raison
    # sous charge : on attend le calme, on ne force pas
    assert C.phase_a_tirer(datetime(2026, 11, 1, 2, 30), st, False)[0] is None
    monkeypatch.setattr(C, "PHASE_PROGRAM", {C.Phase.NREM3: [C.PhaseAction(
        "fts_rebuild", None, handler=lambda: {"fts": "a jour"})]})
    C.fire_phase(C.Phase.NREM3, state=st)
    assert C.Phase.NREM3 not in st.differees          # la note tombe des que l'action a tourne
    assert C.phase_a_tirer(datetime(2026, 11, 1, 3, 0), st, True)[0] is None


def test_le_runner_auto_trace_le_resultat_des_actions(monkeypatch, tmp_path):
    import json as _json
    sys.path.insert(0, str(RACINE / "tools"))
    import forge_circadian_runner as run  # noqa: PLC0415

    monkeypatch.setattr(run, "JOURNAL_AUTO", tmp_path / "circadian_auto.jsonl")
    monkeypatch.setattr(run, "load_state", _etat_repose)
    monkeypatch.setattr(run, "save_state", lambda st: None)
    monkeypatch.setattr(run, "inactivite_mesuree", lambda: (True, "inactif (test)"))
    monkeypatch.setattr(run, "phase_a_tirer", lambda now, st, inactif: (C.Phase.NREM3, "test"))
    monkeypatch.setattr(run, "fire_phase", lambda p, state, dry_run: {
        "completed": True, "differees": ["fts_rebuild"],
        "results": [{"action": "fts_rebuild", "organ": "rein", "fts": "hors phase", "phase": "CREPUSCULE"}]})
    monkeypatch.setattr(sys, "argv", ["forge_circadian_runner.py", "--auto"])
    assert run.main() == 0
    lignes = [_json.loads(x) for x in (tmp_path / "circadian_auto.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["decision"] for x in lignes] == ["tire", "resultat"]
    assert "fts_rebuild=hors phase" in lignes[1]["raison"] and "differees=['fts_rebuild']" in lignes[1]["raison"]


def test_les_differees_survivent_au_redemarrage_du_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_STATE_PATH", tmp_path / "circadian_state.json")
    st = _etat_repose()
    st.differees = {C.Phase.NREM3: ["fts_rebuild"]}
    C.save_state(st)
    assert C.load_state().differees == {C.Phase.NREM3: ["fts_rebuild"]}
