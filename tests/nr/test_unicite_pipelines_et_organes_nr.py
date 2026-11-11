"""NR -- geste owner 3 (8/11) : unicite des pipelines d'ingestion et audit des organes candidats a l'archivage.

Verifie :
1. L'inscription de ce NR dans PURE_TESTS (tools/ci_local.py).
2. Qu'aucun module archive dans app/_attic/ n'est importe par app/ ou tools/.
3. Que les signatures de forge_ingestion_pipeline (run_ingestion_pipeline, daemon_loop -- gitingest AST + PageRank)
   et de forge_ingest_pipeline (process_document, store_chunks -- chunking L1/L2/L3 + SQLite) sont distinctes,
   justifiant le maintien des 2 appelants sur forge_ingestion_pipeline.
4. Que forge_autonomous_loops et forge_homeostasis_orchestrator s'importent et que leurs 2 appelants
   (pat_repo_ingestion et _watchdog_daemons) fonctionnent de maniere hermetique.
"""
from __future__ import annotations

import ast
from datetime import datetime
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_inscrit_dans_pure_tests():
    """Ce NR doit figurer dans PURE_TESTS (tools/ci_local.py) pour proteger la suite pure."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '"tests/nr/test_unicite_pipelines_et_organes_nr.py"' in src


def test_aucun_module_archive_importe_par_app_ou_tools():
    """Aucun module archive sous app/_attic/ ne doit etre importe par un module vivant de app/ ou tools/."""
    attic = ROOT / "app" / "_attic"
    actifs = {p.stem for d in ("app", "tools") for p in (ROOT / d).glob("*.py")}
    archives = {p.stem for p in attic.glob("*.py") if p.stem.startswith("forge_")} - actifs
    assert "forge_hybrid_retriever" in archives

    violations = []
    for d in ("app", "tools"):
        for p in sorted((ROOT / d).glob("*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError, ValueError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        cible = alias.name.split(".")[-1]
                        if cible in archives:
                            violations.append(f"{d}/{p.name} -> {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    cible = node.module.split(".")[-1]
                    if cible in archives:
                        violations.append(f"{d}/{p.name} -> {node.module}")
    assert not violations, f"Module(s) archive(s) importe(s) dans app/ ou tools/ : {violations}"


def test_signatures_ingestion_pipeline_vs_ingest_pipeline_distinctes():
    """Prouve que forge_ingestion_pipeline et forge_ingest_pipeline ont des contrats distincts (pas de bascule aveugle)."""
    from nokido_agent.app import forge_ingest_pipeline as ingest_mod
    from nokido_agent.app import forge_ingestion_pipeline as ingestion_mod

    assert callable(getattr(ingestion_mod, "run_ingestion_pipeline", None))
    assert callable(getattr(ingestion_mod, "daemon_loop", None))
    assert callable(getattr(ingest_mod, "process_document", None))
    assert callable(getattr(ingest_mod, "store_chunks", None))
    assert not hasattr(ingest_mod, "run_ingestion_pipeline")
    assert not hasattr(ingest_mod, "daemon_loop")


def test_forge_autonomous_loops_et_homeostasis_orchestrator_s_importent():
    """Verifie que forge_autonomous_loops et forge_homeostasis_orchestrator s'importent proprement."""
    from nokido_agent.app import forge_autonomous_loops as L
    from nokido_agent.app import forge_homeostasis_orchestrator as H

    assert callable(getattr(L, "pat_repo_ingestion", None))
    assert callable(getattr(H, "_watchdog_daemons", None))
    assert any(d.get("name") == "ingestion_pipeline" for d in H.DAEMON_WATCHDOGS)


def test_appelant_1_pat_repo_ingestion_hermetique(monkeypatch, tmp_path):
    """Verifie hermetiquement le 1er appelant (forge_autonomous_loops.pat_repo_ingestion)."""
    from nokido_agent.app import forge_autonomous_loops as L

    d = tmp_path / "gitingest"
    d.mkdir()
    dump = (
        "===\n"
        "FILE: src/engine.py\n"
        "===\n"
        "class Engine:\n"
        "    pass\n\n"
        "def run_engine():\n"
        "    return 42\n"
    )
    (d / "demo_repo.txt").write_text(dump, encoding="utf-8")

    ancres = []
    monkeypatch.setattr(L, "_GITINGEST_DIR", d)
    monkeypatch.setattr(L, "_GITINGEST_PROCESSED", d / ".processed")
    monkeypatch.setattr(L, "_ram_gate", lambda *a, **k: True)
    monkeypatch.setattr(L, "_anchor", lambda **kw: ancres.append(kw))

    res = L.pat_repo_ingestion()
    assert res["processed"] == 1
    assert res["failed"] == 0
    comp_file = d / "demo_repo_compressed.json"
    assert comp_file.exists()
    comp_data = json.loads(comp_file.read_text(encoding="utf-8"))
    assert len(comp_data["core_modules"]) == 1
    assert comp_data["core_modules"][0]["name"] == "engine"
    assert "Engine" in comp_data["core_modules"][0]["classes"]
    assert "run_engine" in comp_data["core_modules"][0]["functions"]
    assert len(ancres) == 1
    assert (d / ".processed").read_text(encoding="utf-8").splitlines() == ["demo_repo.txt"]


def test_appelant_2_watchdog_daemons_hermetique(monkeypatch, tmp_path):
    """Verifie hermetiquement le 2e appelant (forge_homeostasis_orchestrator._watchdog_daemons)."""
    from nokido_agent.app import forge_health_diagnostic as HD
    from nokido_agent.app import forge_homeostasis_orchestrator as H

    hb = tmp_path / "ingestion_pipeline.heartbeat"
    etat_file = tmp_path / "watchdog_daemons_state.json"
    cmd_attendue = [sys.executable, str(ROOT / "app" / "forge_ingestion_pipeline.py"), "--daemon"]

    monkeypatch.setattr(
        H,
        "DAEMON_WATCHDOGS",
        [{"name": "ingestion_pipeline", "heartbeat": hb, "cmd": cmd_attendue, "stale_s": 600}],
    )
    monkeypatch.setattr(H, "_WATCHDOG_ETAT", etat_file)
    monkeypatch.setattr(HD, "_daemons_au_repos_declare", lambda: (set(), "aucun"))

    spawns = []

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd, **kwargs):
        spawns.append(cmd)
        return _FakeProc()

    import subprocess
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    # 1. Heartbeat frais -> ok, aucune relance
    hb.write_text(json.dumps({"ts": datetime.now().isoformat(), "status": "idle"}), encoding="utf-8")
    r_frais = H._watchdog_daemons()
    assert r_frais["ingestion_pipeline"].startswith("ok(")
    assert spawns == []

    # 2. Heartbeat rance -> relance via cmd pointant vers forge_ingestion_pipeline.py --daemon
    hb.write_text(json.dumps({"ts": "2020-01-01T00:00:00", "status": "idle"}), encoding="utf-8")
    r_rance = H._watchdog_daemons()
    assert r_rance["ingestion_pipeline"].startswith("relance(")
    assert len(spawns) == 1
    assert spawns[0] == cmd_attendue
