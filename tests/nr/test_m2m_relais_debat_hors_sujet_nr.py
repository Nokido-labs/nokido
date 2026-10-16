"""NR -- le relais du debat anti-regression ne se relance plus sur un courrier hors sujet.

Mesure 2026-10-14 : pat_m2m_debate_relay relancait backtest ET arene sur N'IMPORTE QUEL courrier
d'ANTIGRAVITY -- dont les accuses de tache et les resultats relayes par l'auto-repondeur
([GEMINI-AUTO·...]) -- deux fois le meme soir, pour une demande sans rapport (avis sur les skills).
Chemin reel : pat_m2m_debate_relay(), postal / backtest / arene / tableau noir factices.
"""
from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_agent.app.forge_autonomous_loops as fal  # noqa: E402

ACCUSE_TACHE = ('[GEMINI-AUTO·executeur-agy] {"intent": "HANDOFF_NEXT", "pointer_ref": '
                '"tasks.db:job_1", "note": "transmis a l\'executeur agy"}')
DEBAT = "ACK-BACKTEST : l'axe ax16 rate les regressions de signal, je propose un axe d'extinction."


@pytest.mark.parametrize("corps,attendu", [
    (ACCUSE_TACHE, False),
    ("[GEMINI-AUTO·fort:groq] Valide, je te remets l'artefact.", False),
    ("Voici mon avis sur les 28 skills.", False),
    (DEBAT, True),
    ("Le backtest anti-regression donne 6 % de rappel.", True),
])
def test_le_sujet_du_debat_est_reconnu(corps, attendu):
    assert fal._sujet_antiregression({"body": corps}) is attendu


@pytest.fixture
def relais(tmp_path, monkeypatch):
    import nokido_agent.app.forge_postal as fp
    postes, appels = [], {"backtest": 0, "arene": 0}
    monkeypatch.setattr(fal, "_M2M_ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(fal, "_frames_du_pair", lambda wm: [])
    monkeypatch.setattr(fp, "channels_with_pending", lambda: [])
    monkeypatch.setattr(fp, "facteur", lambda *a, **k: {})
    monkeypatch.setattr(fp, "post", lambda *a, **k: postes.append(a) or {"id": "mail_x", "recipient_channel": ""})
    faux_b = types.ModuleType("forge_axis_backtest")
    faux_b.AXES = ["ax16"]
    faux_b.commits_de_correction = lambda *a, **k: appels.__setitem__("backtest", appels["backtest"] + 1) or []
    faux_b.backtest = lambda axe, commits: {"rappel_pct": 0.0, "bruit_hors_cible_pct": 0.0,
                                            "commits_juges": 0, "RATES": []}
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_axis_backtest", faux_b)
    import nokido_agent.tools as _tools_pkg
    monkeypatch.setattr(_tools_pkg, "forge_axis_backtest", faux_b, raising=False)
    monkeypatch.setattr(fal.subprocess, "Popen",
                        lambda *a, **k: appels.__setitem__("arene", appels["arene"] + 1))
    import nokido_agent.app.forge_swarm_blackboard as bb
    monkeypatch.setattr(bb, "apply_fact_sync", lambda *a, **k: {"ok": True})
    return fp, postes, appels


def _boite(fp, monkeypatch, corps):
    maintenant = time.time()
    monkeypatch.setattr(fp, "secretaire", lambda ident, **k: [
        {"id": "mail_1", "sender": "ANTIGRAVITY", "body": corps, "ts_delivered": maintenant}] if ident == "CLAUDE" else [])
    return maintenant


def test_un_accuse_de_tache_ne_relance_ni_backtest_ni_arene(relais, monkeypatch):
    fp, postes, appels = relais
    t = _boite(fp, monkeypatch, ACCUSE_TACHE)
    out = fal.pat_m2m_debate_relay()
    assert out["hors_sujet"] == 1 and out["reponses_pair"] == 0
    assert appels == {"backtest": 0, "arene": 0} and postes == []
    assert json.loads(fal._M2M_ETAT.read_text(encoding="utf-8"))["dernier_postal_ts"] == pytest.approx(t)


def test_un_courrier_du_debat_relance_toujours(relais, monkeypatch):
    fp, postes, appels = relais
    _boite(fp, monkeypatch, DEBAT)
    out = fal.pat_m2m_debate_relay()
    assert out["reponses_pair"] == 1 and appels["backtest"] == 1 and appels["arene"] == 1
    assert any(a[1] == "ANTIGRAVITY" for a in postes)
