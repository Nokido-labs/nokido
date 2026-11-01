"""NR : `task action=status` SANS task_id ni job_id rend la vue des delegations en vol.

P1_suivi_delegations_tout_cli_20261022 (derogation owner 26/10) : seul Claude Code avait la
vue (`forge_job_watch_cli --delegations`, via Monitor) ; un CLI sans Monitor recevait
`not_found`. La vue est la MEME fonction (`delegations_en_vol`), pas une seconde lecture de
tasks.db : `reaffectations` reste None quand la trace est illisible (INCONNU n'est pas « aucune »).
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry  # noqa: E402


class _Reg:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "sandbox").mkdir(parents=True, exist_ok=True)

    _task_db = ToolRegistry._task_db


def _status(reg, args, agent="CLAUDE"):
    return json.loads(asyncio.run(ToolRegistry.handle_task_status(reg, args, agent, 2)))


def _vue(monkeypatch):
    vus = []

    def faux(db=None, maintenant=None, de=None):
        vus.append(de)
        return [{"task_id": "job_x", "agent": "OPENCODE_GLM", "statut": "running", "de": "CLAUDE",
                 "age_s": 60, "depuis_progres_s": None, "reaffectations": None}]

    import nokido_agent.tools.forge_job_watch_cli as cli
    monkeypatch.setattr(cli, "delegations_en_vol", faux)
    return vus


def test_sans_id_rend_les_delegations_du_demandeur(monkeypatch, tmp_path):
    vus = _vue(monkeypatch)
    d = _status(_Reg(tmp_path), {})
    assert d["ok"] is True and d["vue"] == "delegations" and d["de"] == "CLAUDE"
    assert vus == ["CLAUDE"]
    assert d["delegations"][0]["task_id"] == "job_x"
    assert d["delegations"][0]["reaffectations"] is None, "INCONNU ne doit pas devenir 0"


def test_de_explicite_et_etoile(monkeypatch, tmp_path):
    vus = _vue(monkeypatch)
    _status(_Reg(tmp_path), {"de": "GEMINI"})
    d = _status(_Reg(tmp_path), {"de": "*"})
    assert vus == ["GEMINI", None] and d["de"] == "*"


def test_avec_id_garde_le_comportement(monkeypatch, tmp_path):
    vus = _vue(monkeypatch)
    d = _status(_Reg(tmp_path), {"task_id": "tsk_inexistant"})
    assert d == {"ok": False, "reason": "not_found"} and vus == []
