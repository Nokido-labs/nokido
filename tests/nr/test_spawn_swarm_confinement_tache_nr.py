"""7/11 (job_36d79edd) : forge_spawn_swarm sans `root` d'un appelant lie a une tache ecrivait dans l'ARBRE PRINCIPAL.
Vrai handler, depot jetable : lie a une tache, sans root -> son worktree ; root etranger -> refus ; non lie -> inchange."""
import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent))

from nokido_agent.app import forge_mcp_registry as R  # noqa: E402
from nokido_agent.tools import forge_worktree as W  # noqa: E402

T1 = "job_aaaaaaaa_1_x"


@pytest.fixture()
def monde(tmp_path, monkeypatch):
    principal = tmp_path / "nokido"
    principal.mkdir()
    (principal / "f.txt").write_text("racine", encoding="utf-8")
    wt = tmp_path / "nokido_worktrees" / "taches" / ("claude_headless_%s" % W.court_tache(T1))
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: x\n", encoding="utf-8")
    (wt / "f.txt").write_text("worktree", encoding="utf-8")
    monkeypatch.setattr(W, "taches_en_cours", lambda agent, db=None: [T1])
    vus = []

    async def faux_essaim(tasks, root, infer, **kw):
        vus.append(Path(root))
        return {"ok": True}

    class Pool:
        def make_infer_fn(self):
            return None

    m = types.ModuleType("nokido_agent.app.forge_local_inference_pool")
    m.LocalInferencePool = Pool
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_local_inference_pool", m)
    monkeypatch.setattr("nokido_agent.app.forge_swarm_orchestrator.run_forge_swarm", faux_essaim)
    reg = object.__new__(R.ToolRegistry)
    reg.root = principal
    return reg, principal, wt, vus


def _appel(reg, agent="CLAUDE_HEADLESS", **args):
    args.setdefault("tasks", [{"task_id": "a", "prompt": "x", "op": "delete", "targets": ["f.txt"]}])
    return asyncio.run(reg._handle_spawn_swarm("forge_spawn_swarm", args, agent, 2))


def test_lie_sans_root_vise_le_worktree(monde):
    reg, principal, wt, vus = monde
    _appel(reg, _tache=T1)
    assert vus == [wt]
    assert (principal / "f.txt").read_text(encoding="utf-8") == "racine"


def test_lie_root_etranger_refuse(monde):
    reg, principal, wt, vus = monde
    for root in (str(principal), str(principal.parent)):
        out = _appel(reg, _tache=T1, root=root)
        assert "hors" in out and "worktree" in out
    assert vus == []


def test_lie_root_dans_son_worktree_accepte(monde):
    reg, principal, wt, vus = monde
    (wt / "sub").mkdir()
    _appel(reg, _tache=T1, root=str(wt / "sub"))
    assert vus == [wt / "sub"]


def test_tache_inconnue_refus_net(monde):
    reg, principal, wt, vus = monde
    out = _appel(reg, _tache="job_zzzzzzzz_9_x")
    assert "REFUS" in out and vus == []


def test_executeur_sans_entete_reste_confine(monde):
    """Le cas de l'incident : l'identite decide, pas la presence d'un en-tete ; jamais la racine."""
    reg, principal, wt, vus = monde
    _appel(reg)
    assert vus == [wt]


def test_executeur_sans_entete_root_racine_refuse(monde):
    reg, principal, wt, vus = monde
    out = _appel(reg, root=str(principal))
    assert "hors" in out and vus == []


def test_owner_garde_la_racine(monde):
    reg, principal, wt, vus = monde
    _appel(reg, agent="AGT_CLAUDE")
    assert vus == [principal]


def test_le_hub_transmet_la_tache_a_l_essaim_et_retire_celle_du_client():
    sys.path.insert(0, str(ROOT / "tools"))
    import nokido_hub as hub

    req = types.SimpleNamespace(headers={"LaForge-Tache": "aaaaaaaa1234"}, client=None)
    assert hub._args_avec_provenance("forge_spawn_swarm", {}, req)["_tache"] == "aaaaaaaa1234"
    nu = types.SimpleNamespace(headers={}, client=None)
    assert hub._args_avec_provenance("forge_spawn_swarm", {"_tache": "evil"}, nu)["_tache"] == ""
