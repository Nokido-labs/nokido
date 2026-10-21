"""NR 18/10 -- ForgeSwarm phase REDUCE : synthese DETERMINISTE des resultats d'essaim (forge_swarm_reducer).

Decision owner 18/10 (bb architecture_rules P2_ecarts_doc_code_a_construire_20261018) : le module promis par
docs/roadmap_forge_swarm.md (« Phase 3 REDUCE : reduce(results, goal) -> dict ») est A CONSTRUIRE. Anti-dup
AGY (job_fdf084d7) : run_forge_swarm collecte les resultats puis commit/discard, ZERO synthese. Premier pas
retenu : synthese deterministe, sans LLM, branchee sur les deux sorties de run_forge_swarm.

Contrat : chaque pas est range dans UNE categorie (reussie / echouee / sautee / non executee) ; une chaine
« ERR: » ou « TIMEOUT: » est un echec ; un pas attendu sans resultat n'est PAS une reussite ; la synthese
est bornee et DIT combien elle omet ; meme entree -> meme sortie.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_swarm_reducer as SR  # noqa: E402

RESULTATS = {
    "t2": {"task_id": "t2", "ok": False, "op": "patch", "attempts": 3, "error": "SEARCH introuvable"},
    "t1": {"task_id": "t1", "ok": True, "op": "patch", "attempts": 1, "error": None},
    "t3": {"task_id": "t3", "ok": False, "skipped": True, "error": "dépendance échouée"},
    "t4": "TIMEOUT: 120 s",
}


def test_chaque_pas_dans_une_seule_categorie():
    s = SR.reduce(RESULTATS, "ajouter un cache", attendus=["t1", "t2", "t3", "t4", "t5"])
    assert s["reussies"] == ["t1"]
    assert [e["task_id"] for e in s["echouees"]] == ["t2", "t4"]
    assert s["sautees"] == ["t3"]
    assert s["non_executees"] == ["t5"], "un pas attendu sans resultat n'est pas une reussite"
    assert s["ok"] is False and s["n"] == 5
    assert s["echouees"][0]["error"] == "SEARCH introuvable"
    assert "TIMEOUT" in s["echouees"][1]["error"]


def test_succes_complet_et_message_de_commit_borne():
    ok = {"a": {"task_id": "a", "ok": True, "op": "patch"}, "b": {"task_id": "b", "ok": True, "op": "create"}}
    s = SR.reduce(ok, "x" * 200, touched=["app/a.py", "app/b.py"])
    assert s["ok"] is True and s["reussies"] == ["a", "b"]
    premiere = s["message_commit"].splitlines()[0]
    assert len(premiere) <= 72, premiere
    assert "2/2" in s["message_commit"] and "app/a.py" in s["message_commit"]


def test_deterministe_et_borne_dit_ce_qu_il_omet():
    beaucoup = {"t%03d" % i: {"task_id": "t%03d" % i, "ok": False, "error": "e" * 300} for i in range(40)}
    s1 = SR.reduce(beaucoup, "but")
    s2 = SR.reduce(dict(reversed(list(beaucoup.items()))), "but")
    assert s1 == s2, "meme entree (ordre different) -> meme synthese"
    assert len(s1["resume"]) <= SR.RESUME_MAX
    assert "omis" in s1["resume"], "la borne doit DIRE combien elle ecarte"


def test_run_forge_swarm_rend_la_synthese(monkeypatch):
    import forge_swarm_orchestrator as O

    class _Overlay:
        def __init__(self, root):
            pass

        def commit(self, dry_run=False):
            return ["app/x.py"]

        def discard(self):
            pass

    async def _worker(step, overlay, infer_fn, emit=None):
        return {"task_id": step["id"], "ok": True, "op": "patch", "attempts": 1, "error": None}

    monkeypatch.setattr(O, "validate_swarm_plan", lambda plan, root, graph=None: (True, []))
    monkeypatch.setattr(O, "VFSOverlay", _Overlay)
    monkeypatch.setattr(O, "run_worker", _worker)
    plan = [{"task_id": "p1", "deps": []}, {"task_id": "p2", "deps": ["p1"]}]
    out = asyncio.run(O.run_forge_swarm(plan, ROOT, infer_fn=None))
    assert out["ok"] is True and out["touched"] == ["app/x.py"]
    assert out["synthese"]["reussies"] == ["p1", "p2"]
    assert out["synthese"]["touches"] == ["app/x.py"]
