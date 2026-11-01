"""NR lanceur automatique du secours de la synthese (faux hub, faux statut, tmp_path)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402
from tools import forge_secours_lanceur as lz  # noqa: E402


@pytest.fixture(autouse=True)
def _seuil_substance_neutre(monkeypatch):
    """29/10 : textes factices courts ; le garde de substance a ses NR (test_secours_texte_complet_nr)."""
    monkeypatch.setattr(sw, "SYNTHESE_MIN_CAR", 0)


class FauxHub:
    def __init__(self):
        self.depots = []
        self.statuts = {}

    def __call__(self, outil, args):
        assert outil == "task"
        if args["action"] == "assign":
            self.depots.append(args["agent"])
            return json.dumps({"ok": True, "task_id": "T%d" % len(self.depots)})
        return json.dumps(self.statuts.get(args["task_id"], {"status": "in_progress"}))


@pytest.fixture
def monde(tmp_path, monkeypatch):
    hub = FauxHub()
    monkeypatch.setattr(sw, "_appel_hub", hub)
    (tmp_path / "workspace").mkdir()
    # 29/10 : le lanceur lit le texte COMPLET (tasks.db par cle primaire), plus le result_summary (mesure : verdict
    # JSON integre a tort) ; le faux monde sert le meme texte par cette voie, assertions inchangees.
    monkeypatch.setattr(lz, "_texte_complet", lambda tid: (hub.statuts.get(tid) or {}).get("result_summary", ""))
    return hub, tmp_path


def _json(d, nom="cli_swarm_ptr_1.json", demande=True, age_s=0):
    res = {"task": "q", "synthesis": ""}
    if demande:
        res["demande_synthese"] = {"pointeur": "absent.json", "consigne": "c",
                                   "executeurs": ["CLAUDE_HEADLESS", "ANTIGRAVITY"], "raison": "r"}
    p = d / nom
    p.write_text(json.dumps(res), encoding="utf-8")
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


def test_un_depot_puis_idempotent(monde):
    hub, d = monde
    p = _json(d)
    lz.passer(d)
    assert hub.depots == ["CLAUDE_HEADLESS"]
    dep = json.loads(p.read_text(encoding="utf-8"))["secours_depose"]
    assert dep["task_id"] == "T1" and dep["agent"] == "CLAUDE_HEADLESS" and dep["ts"]
    lz.passer(d)
    assert hub.depots == ["CLAUDE_HEADLESS"]


def test_tache_done_integre_avec_cout(monde):
    hub, d = monde
    p = _json(d)
    lz.passer(d)
    hub.statuts["T1"] = {"status": "done", "result_summary": "Synthèse sans chiffre.", "cout_usd": 0.12}
    lz.passer(d)
    res = json.loads(p.read_text(encoding="utf-8"))
    assert res["secours_integre"]["task_id"] == "T1"
    assert res["secours_integre"]["cout_usd"] == 0.12
    assert "demande_synthese" not in res and res["synthesis"]
    assert (d / "workspace" / "secours_texte_T1.txt").is_file()
    lz.passer(d)
    assert hub.depots == ["CLAUDE_HEADLESS"]


def test_delai_bascule_antigravity(monde):
    hub, d = monde
    p = _json(d)
    lz.passer(d)
    res = json.loads(p.read_text(encoding="utf-8"))
    res["secours_depose"]["ts"] = time.time() - 601
    p.write_text(json.dumps(res), encoding="utf-8")
    lz.passer(d)
    assert hub.depots == ["CLAUDE_HEADLESS", "ANTIGRAVITY"]
    res = json.loads(p.read_text(encoding="utf-8"))
    assert res["secours_depose"]["agent"] == "ANTIGRAVITY"
    assert "délai" in json.dumps(res["secours_motifs"], ensure_ascii=False)


def test_ignores(monde):
    hub, d = monde
    _json(d, "cli_swarm_ptr_2.json", demande=False)
    _json(d, "cli_swarm_ptr_3.json", age_s=25 * 3600)
    lz.passer(d)
    assert hub.depots == []
