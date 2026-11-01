"""NR -- le secours depose dans la BONNE file (outil hub `task` : assign puis status), pas forge_task_bus.

Faux client hub : aucun vrai depot."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import pytest  # noqa: E402
import forge_cli_swarm as S  # noqa: E402

FORT = "ollama_cloud_gptoss:gpt-oss:120b"


@pytest.fixture
def monde(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    monkeypatch.setattr(S, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(S, "SORTIE_DIR", tmp_path)
    monkeypatch.setattr(S, "_tourner_membre", lambda m, t, n: {
        "provider": FORT, "ok": True, "text": "reponse 12 ms", "outils_appeles": [],
        "extraits": ["extrait 12 ms"], "ancrage": {"sans_source": []}})
    monkeypatch.setattr(S, "_synthetiser", lambda *a, **k: {"text": "", "error": "vide"})
    monkeypatch.setattr(S, "_pre_flight_envoi", lambda t, v: (True, None))
    monkeypatch.setattr(S, "_appeler_voie", lambda v, p, timeout=180: {"text": "", "error": "backend non prêt"})
    h = {"t": 0.0}
    monkeypatch.setattr(S, "_horloge", lambda: h["t"])
    monkeypatch.setattr(S, "_dormir", lambda s: h.__setitem__("t", h["t"] + s))
    import app.forge_task_bus as TB

    def interdit(*a, **k):
        raise AssertionError("forge_task_bus utilise")
    monkeypatch.setattr(TB, "create_task", interdit)
    monkeypatch.setattr(TB, "get_task", interdit)

    def installer(statut_par_agent):
        appels = []
        agents = {}

        def hub(outil, arguments):
            appels.append((outil, dict(arguments)))
            assert outil == "task"
            if arguments["action"] == "assign":
                tid = "t%d" % len(agents)
                agents[tid] = arguments["agent"]
                return json.dumps({"ok": True, "task_id": tid})
            return json.dumps(statut_par_agent(agents[arguments["task_id"]]))
        monkeypatch.setattr(S, "_appel_hub", hub)
        return appels
    return installer


def _run():
    return asyncio.run(S.swarm_pointeur("q", ["p"], membres=[FORT]))


def test_depot_via_outil_hub_task_et_resultat_lu(monde):
    # REMPLACEE (decision owner 29/10) : ancienne = le job depose via `task assign` puis lit le statut ;
    # nouvelle = AUCUN appel hub depuis le job, la demande est ecrite pour le lanceur (ring <= 3).
    appels = monde(lambda ag: {"status": "review", "result_summary": "ligne ancree 12 ms"})
    res = _run()
    assert appels == []
    assert res["synthese_par"] is None and res["synthesis"] is None
    assert res["demande_synthese"]["executeurs"] == ["CLAUDE_HEADLESS", "ANTIGRAVITY"]


def test_tous_echouent_synthese_par_none(monde):
    # REMPLACEE : ancienne = deux depots en echec ; nouvelle = aucun depot (appels vide), essais des voies ask seuls
    appels = monde(lambda ag: {"status": "failed"})
    res = _run()
    assert appels == []
    assert res["synthese_par"] is None
    assert len(res["synthese_essais"]) >= 2
