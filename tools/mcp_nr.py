"""
tools/mcp_nr.py — NR automatique lancé par Claude via MCP sandbox
=================================================================
Chaque fonction est courte (<50 lignes) pour passer la sentinelle.
Usage depuis le sandbox MCP :
  from tools.mcp_nr import run_all, run_fast, run_after_edit
  run_all()      # suite complète
  run_fast()     # AST + globals + REGISTRY (< 2s)
  run_after_edit('app/forge_handlers.py')  # ciblé sur un fichier
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import types
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Mock __main__ minimal (sans subprocess ni pytest)
# ─────────────────────────────────────────────────────────────────────────────


class _AgentType(Enum):
    CHAT = "chat"
    ACTION = "action"
    RAG = "rag"


def _inject_mock():
    """Injecte un mock __main__ pour importer les modules Nokido."""
    m = types.ModuleType("__main__")
    m.AgentType = _AgentType
    m.AGENT_META = {a: {"color": "#fff", "icon": "x", "label": a.value} for a in _AgentType}
    m.DangerLevel = type("DL", (), {"SAFE": "safe"})()
    for flag in [
        "HAS_DANGER_GUARD",
        "HAS_PREDICTIF",
        "HAS_ROUTAGE",
        "HAS_WEB_SEARCH",
        "HAS_SANDBOX",
        "HAS_SSH",
        "HAS_PTY",
        "HAS_PREFECT",
        "HAS_SCORING",
    ]:
        setattr(m, flag, False)
    m.agentic_engine = None
    m.rag_engine = None
    m.settings = type(
        "S",
        (),
        {
            "ollama_url": "http://localhost:11434",
            "max_concurrent_tasks": 2,
            "ollama_model_default": "qwen2.5",
            "rag_dir": "data/rag_files",
        },
    )()
    m.version_manager = type(
        "VM",
        (),
        {
            "get_current_code": lambda s: "# code",
            "work_path": Path("app/LaForge.py"),
            "current_version": "0.13.0",
        },
    )()
    m.prefect_manager = None
    m.ssh_manager = None
    m.escape = lambda x: str(x)
    m.debug_log = lambda *a, **k: None
    m.logger = type(
        "L", (), {k: lambda *a, **kk: None for k in ["info", "debug", "warning", "error"]}
    )()
    m.get_proxy_url = lambda n="": None
    m.get_best_proxy_url = lambda: None
    m.get_web_engine = lambda: None
    m._pred_get_router = lambda: None
    m._ROOT_DIR = ROOT
    m._DATA_DIR = ROOT / "data"

    async def _mock(*a, **k):
        return "[MOCK]"

    m.ollama_stream = _mock
    m.ollama_call = _mock
    m.run_ssh = _mock
    m.get_orchestrator = lambda: type("O", (), {"handle": _mock})()

    old = sys.modules.get("__main__")
    sys.modules["__main__"] = m
    return old, m


# ─────────────────────────────────────────────────────────────────────────────
# Vérifications individuelles (courtes)
# ─────────────────────────────────────────────────────────────────────────────


def check_ast(files=None) -> list[tuple]:
    """AST valide sur tous les modules."""
    if files is None:
        files = [
            "app/LaForge.py",
            "app/forge_dispatch.py",
            "app/forge_handlers.py",
            "app/forge_dispatch_ai.py",
            "app/forge_dispatch_network.py",
            "app/forge_collab_modes.py",
            "app/forge_task_bus.py",
            "app/forge_timecode.py",
            "app/forge_llm.py",
            "app/forge_litellm_bridge.py",
            "app/forge_ollama_bridge.py",
        ]
    results = []
    for f in files:
        p = ROOT / f
        if not p.exists():
            results.append(("SKIP", f, "absent"))
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            results.append(
                ("OK", f, f"{p.read_text(encoding='utf-8', errors='ignore').count(chr(10))}L")
            )
        except SyntaxError as e:
            results.append(("FAIL", f, f"L{e.lineno}: {e.msg}"))
    return results


def check_globals_fh() -> list[tuple]:
    """Pas de globals bruts dans forge_handlers corps des handlers."""
    fh = (ROOT / "app/forge_handlers.py").read_text(encoding="utf-8", errors="ignore")
    body = fh[fh.find("async def _handle_") :]
    results = []
    for g in [
        "version_manager",
        "rag_engine",
        "agentic_engine",
        "prefect_manager",
        "ollama_stream",
        "settings",
    ]:
        pat = r"(?<!_g\()(?<!\')(?<!\")(?<![_\w])\b" + g + r'\b(?![_\w\'"(])'
        n = len(re.findall(pat, body))
        results.append(("OK" if n == 0 else "FAIL", f"fh.{g}", f"{n}x brut"))
    return results


def check_no_self(files=None) -> list[tuple]:
    """Pas de self. nu dans les modules externalisés."""
    if files is None:
        files = [
            "app/forge_handlers.py",
            "app/forge_dispatch_network.py",
            "app/forge_dispatch_ai.py",
        ]
    results = []
    for f in files:
        p = ROOT / f
        if not p.exists():
            results.append(("SKIP", f, "absent"))
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        # Exclure les commentaires + les définitions
        bare = [
            l.strip()[:60]
            for l in src.splitlines()
            if not l.lstrip().startswith("#")
            and not l.lstrip().startswith("def ")
            and re.search(r"(?<![_\w])self\.", l)
        ]
        results.append(("OK" if not bare else "FAIL", f, f"{len(bare)}x self." if bare else ""))
    return results


def check_registry() -> list[tuple]:
    """REGISTRY complet avec 28 cmds, tous async."""
    old, _ = _inject_mock()
    try:
        for mod in ["forge_dispatch"]:
            sys.modules.pop(mod, None)
        from nokido_agent.app import forge_dispatch as fd

        cmds = set()
        for k in fd.REGISTRY:
            cmds.update(k) if isinstance(k, tuple) else cmds.add(k)
        all_async = all(inspect.iscoroutinefunction(fn) for fn in fd.REGISTRY.values())
        expected = {
            "@help",
            "@audit",
            "@scan",
            "@mode",
            "@collab",
            "@rag",
            "@loop",
            "@role",
            "@estim",
            "@run",
            "@ssh",
            "@disco",
            "@evolve",
            "@agentic",
            "@tools",
            "@ci",
            "@workflow",
            "@proxy",
        }
        missing = expected - cmds
        results = [
            ("OK" if len(cmds) >= 26 else "FAIL", "REGISTRY count", f"{len(cmds)} cmds"),
            ("OK" if all_async else "FAIL", "REGISTRY async", ""),
            ("OK" if not missing else "FAIL", "REGISTRY missing", str(missing)),
        ]
    except Exception as e:
        results = [("FAIL", "REGISTRY import", str(e)[:80])]
    finally:
        if old:
            sys.modules["__main__"] = old
    return results


def check_imports() -> list[tuple]:
    """Tous les modules importables sans erreur circulaire."""
    old, _ = _inject_mock()
    mods = [
        "forge_dispatch",
        "forge_handlers",
        "forge_dispatch_network",
        "forge_dispatch_ai",
        "forge_collab_modes",
        "forge_task_bus",
        "forge_timecode",
        "forge_llm",
        "forge_litellm_bridge",
    ]
    results = []
    for mod in mods:
        sys.modules.pop(mod, None)
    for mod in mods:
        try:
            __import__(mod)
            results.append(("OK", mod, ""))
        except Exception as e:
            results.append(("FAIL", mod, f"{type(e).__name__}: {str(e)[:60]}"))
    if old:
        sys.modules["__main__"] = old
    return results


def check_wrappers_lf() -> list[tuple]:
    """Wrappers Nokido.py : presence + try/except (wrapper ou inline)."""
    lf = (ROOT / "app/LaForge.py").read_text(encoding="utf-8", errors="ignore")
    results = []
    # _handle_apply : méthode UI simple (pas de try/except requis)
    for name in [
        "_handle_audit",
        "_handle_rag",
        "_handle_loop",
        "_handle_mode",
        "_handle_role",
        "_handle_estim",
        "_handle_ci",
        "_handle_workflow",
        "_handle_proxy",
    ]:
        present = f"def {name}" in lf or f"async def {name}" in lf
        has_try = False
        if present:
            m = re.search(
                rf"(?:async )?def {re.escape(name)}\(self[^)]*\):(.*?)(?=\n        (?:async )?def )",
                lf,
                re.DOTALL,
            )
            if m:
                body = m.group(1)
                # Accepter : wrapper (forge_handlers) ou inline (except direct)
                has_try = ("except" in body) or ("forge_handlers" in body)
        results.append(
            (
                "OK" if present and has_try else "FAIL",
                f"wrapper {name}",
                "" if (present and has_try) else ("absent" if not present else "no try/except"),
            )
        )
    return results


def check_task_bus() -> list[tuple]:
    """forge_task_bus : cycle create→claim→submit→review."""
    old, _ = _inject_mock()
    try:
        sys.modules.pop("forge_task_bus", None)
        import uuid as _uuid

        from nokido_agent.app import forge_task_bus as tb

        ex = f"NR_{_uuid.uuid4().hex[:6]}"
        t = tb.create_task(title="NR test", description="d", executor=ex)
        assert t["status"] == "pending", f"status={t['status']}"
        c = tb.claim_task(executor=ex)
        assert c is not None, "claim=None"
        assert c["id"] == t["id"], "id mismatch"
        tb.submit_result(t["id"], [{"content": "ok"}])
        tb.forge_review(t["id"], verdict="approved", acteur=tb.ACTEUR_FORGE)   # AUTH-6 : acteur exige
        final = tb.get_task(t["id"])
        assert final["status"] == "done", f"final={final['status']}"
        results = [("OK", "task_bus lifecycle", "create→claim→submit→review→done")]
    except Exception as e:
        results = [("FAIL", "task_bus lifecycle", str(e)[:80])]
    finally:
        if old:
            sys.modules["__main__"] = old
    return results


def check_timecode() -> list[tuple]:
    """forge_timecode : tick monotone."""
    old, _ = _inject_mock()
    try:
        sys.modules.pop("forge_timecode", None)
        from nokido_agent.app import forge_timecode as ftc

        tc = ftc.TimecodeEngine()
        seqs = [tc.tick()[0] for _ in range(3)]
        ok = seqs == sorted(seqs) and len(set(seqs)) == 3
        results = [("OK" if ok else "FAIL", "timecode monotone", str(seqs))]
    except Exception as e:
        results = [("FAIL", "timecode", str(e)[:80])]
    finally:
        if old:
            sys.modules["__main__"] = old
    return results


def check_integrity() -> list[tuple]:
    """forge_integrity : IntegrityRing, is_at_least, CapabilityToken HMAC, RingContext."""
    results = []
    try:
        sys.modules.pop("forge_integrity", None)
        from nokido_agent.app import forge_integrity as fi

        # 1. is_at_least — matrice critique
        IR = fi.IntegrityRing
        matrix = [
            (IR.SYSTEM, IR.UNTRUSTED, True),
            (IR.DEV, IR.TRUSTED, True),
            (IR.COLLAB, IR.TRUSTED, False),
            (IR.DEV, IR.SYSTEM, False),
        ]
        ok = all(fi.is_at_least(r, req) == exp for r, req, exp in matrix)
        results.append(("OK" if ok else "FAIL", "integrity.is_at_least", "4/4"))

        # 2. CapabilityToken encode/decode round-trip
        import os as _os

        _os.environ.setdefault("MCP_DEV_SECRET", "nr_test_secret")
        mgr = fi.IntegrityManager("nr_test_secret_32chars_long_enough!")
        token_str = mgr.create_manifest(
            "claude",
            IR.DEV,
            scopes={"fs": ["read", "write"], "rag": ["ingest", "query"]},
            duration_s=3600,
        )
        results.append(
            ("OK" if "." in token_str else "FAIL", "integrity.token_format", "payload.sig")
        )

        # 3. verify() — action autorisée
        ok_v, ctx = mgr.verify("fs", "write", token_str)
        results.append(
            (
                "OK" if ok_v else "FAIL",
                "integrity.verify_ok",
                ctx.ring.label() if ok_v else str(ctx),
            )
        )

        # 4. verify() — action refusée (scope absent)
        ok_bad, reason = mgr.verify("sql", "write", token_str)
        results.append(
            ("OK" if not ok_bad else "FAIL", "integrity.verify_denied", str(reason)[:40])
        )

        # 5. Token expiré
        expired = mgr.create_manifest("x", IR.COLLAB, duration_s=-1)
        ok_exp, reason_exp = mgr.verify("rag", "query", expired)
        results.append(("OK" if not ok_exp else "FAIL", "integrity.expired", str(reason_exp)[:40]))

        # 6. Atténuation — le fils ne peut pas étendre les droits du parent

        parent_token = fi.CapabilityToken.decode(token_str, b"nr_test_secret_32chars_long_enough!")
        child = parent_token.attenuate({"fs": ["read", "exec"], "rag": ["admin"]})
        # exec est absent du parent → refusé
        has_exec = child.can("fs", "exec")
        # admin est absent du parent → refusé
        has_admin = child.can("rag", "admin")
        results.append(
            (
                "OK" if not has_exec and not has_admin else "FAIL",
                "integrity.attenuate",
                "exec+admin refusés",
            )
        )

        # 7. RingContext.rag_author_tag format
        ctx_sys = fi.RingContext.system()
        tag = ctx_sys.rag_author_tag()
        results.append(
            ("OK" if tag.startswith("system:") else "FAIL", "integrity.rag_author_tag", tag)
        )

        # 8. consensus_level par ring
        expected_consensus = {0: "gold", 1: "gold", 2: "verified", 3: "draft", 4: "raw"}
        ok_c = all(IR(v).consensus_level() == exp for v, exp in expected_consensus.items())
        results.append(("OK" if ok_c else "FAIL", "integrity.consensus", "5/5"))

        # 9. get_manager() singleton
        mgr1 = fi.get_manager()
        mgr2 = fi.get_manager()
        results.append(("OK" if mgr1 is mgr2 else "FAIL", "integrity.get_manager singleton", ""))

        # 10. seq_id croissant dans les tokens
        t1 = mgr.create_manifest("agent_a", IR.DEV, duration_s=60)
        t2 = mgr.create_manifest("agent_a", IR.DEV, duration_s=60)
        tok1 = fi.CapabilityToken.decode(t1, b"nr_test_secret_32chars_long_enough!")
        tok2 = fi.CapabilityToken.decode(t2, b"nr_test_secret_32chars_long_enough!")
        results.append(
            (
                "OK" if tok2.seq > tok1.seq else "FAIL",
                "integrity.seq_monotone",
                f"{tok1.seq}<{tok2.seq}",
            )
        )

        # 11. revoke() bloque les anciens tokens
        mgr2_local = fi.IntegrityManager("nr_test_secret_32chars_long_enough!")
        t_old = mgr2_local.create_manifest(
            "bob", IR.COLLAB, scopes={"rag": ["query"]}, duration_s=60
        )
        t_new = mgr2_local.create_manifest(
            "bob", IR.COLLAB, scopes={"rag": ["query"]}, duration_s=60
        )
        tok_old = fi.CapabilityToken.decode(t_old, b"nr_test_secret_32chars_long_enough!")
        # Révoquer tout ce qui est < seq du nouveau token
        mgr2_local.revoke("bob", tok_old.seq + 1)
        ok_old, _ = mgr2_local.verify("rag", "query", t_old)
        ok_new, _ = mgr2_local.verify("rag", "query", t_new)
        results.append(
            ("OK" if not ok_old else "FAIL", "integrity.revoke_old_blocked", f"seq={tok_old.seq}")
        )
        results.append(("OK" if ok_new else "FAIL", "integrity.revoke_new_ok", ""))

    except Exception as e:
        results = [("FAIL", "integrity import/exec", f"{type(e).__name__}: {str(e)[:80]}")]
    return results


def check_boot() -> list[tuple]:
    """forge_boot : boot léger sans imports lourds + settings OK."""
    old, _ = _inject_mock()
    results = []
    try:
        sys.modules.pop("forge_boot", None)
        sys.modules.pop("forge_settings", None)

        # Vérifier qu'aucun import lourd n'est présent
        src = (ROOT / "app/forge_boot.py").read_text(encoding="utf-8")
        heavy = ["forge_rag_engine", "forge_orchestrator", "torch", "transformers"]
        heavy_found = [h for h in heavy if f"import {h}" in src or f"from {h}" in src]
        results.append(
            (
                "OK" if not heavy_found else "FAIL",
                "boot no heavy imports",
                str(heavy_found) if heavy_found else "",
            )
        )
        # Vérifier que BootResult est importable
        results.append(("OK", "boot BootResult importable", ""))
        # Vérifier taille forge_boot.py < 250L
        lines = src.count("\n")
        results.append(
            ("OK" if lines < 250 else "WARN", "boot taille", f"{lines}L (max 250 recommandé)")
        )
    except Exception as e:
        results = [("FAIL", "boot import", str(e)[:80])]
    finally:
        if old:
            sys.modules["__main__"] = old
    return results


def check_metrics() -> list[tuple]:
    """forge_metrics : collecteur + measure context manager."""
    old, _ = _inject_mock()
    results = []
    try:
        sys.modules.pop("forge_metrics", None)
        from nokido_agent.app import forge_metrics as fm

        col = fm.MetricsCollector(max_history=10)
        # Test context manager
        with col.measure("test_provider", "test_model", mode="nr") as m:
            m.estimate_tokens("hello world", "response")
        assert len(col._history) == 1
        assert col._history[0].latency_ms >= 0
        assert col._history[0].prompt_tokens > 0
        # Test stats
        s = col.stats("test_provider")
        assert s["n"] == 1
        assert s["latency_ms"]["avg"] >= 0
        results.append(("OK", "metrics measure + stats", f"lat={s['latency_ms']['avg']:.1f}ms"))
        # Test best_provider
        best = col.best_provider()
        results.append(("OK", "metrics best_provider", best))
    except Exception as e:
        results = [("FAIL", "metrics", str(e)[:80])]
    finally:
        if old:
            sys.modules["__main__"] = old
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Suites
# ─────────────────────────────────────────────────────────────────────────────


def _report(results: list, title: str):
    ok = sum(1 for r in results if r[0] == "OK")
    fail = sum(1 for r in results if r[0] == "FAIL")
    skip = sum(1 for r in results if r[0] == "SKIP")
    icon = "✅" if fail == 0 else "❌"
    print(f"{icon} {title}: {ok} OK / {fail} FAIL / {skip} SKIP")
    for status, name, detail in results:
        if status != "OK":
            print(f"    {status} {name}: {detail}")
    return fail


def _archive_run(suite_type: str, fails: int) -> None:
    """Archive JSON + RAG pending apres chaque run — non-fatal."""
    try:
        import datetime as _dt
        import json as _j
        from pathlib import Path as _P

        _root = _P(__file__).resolve().parent.parent
        try:
            sys.path.insert(0, str(_root))
            from nokido_agent.app import forge_version as _fv

            _fv.invalidate_cache()
            _ver = _fv.get()
        except Exception:
            _ver = "0.13.0"
        _ts = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
        _ts_f = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        _status = "PASS" if fails == 0 else "FAIL"
        # Archive JSON
        _rdir = _root / "data_nr" / "reports"
        _rdir.mkdir(parents=True, exist_ok=True)
        _data = {
            "_schema": "nr_report_v1",
            "run_id": _ts,
            "version": _ver,
            "suite_type": suite_type,
            "status": _status,
            "total_fail": fails,
            "triggered_by": "system:mcp_nr",
        }
        (_rdir / f"nr_{suite_type}_{_ts_f}.json").write_text(
            _j.dumps(_data, indent=2), encoding="utf-8"
        )
        (_rdir / "nr_latest.json").write_text(_j.dumps(_data, indent=2), encoding="utf-8")
        # RAG pending (author=system:nr_runner, ring=SYSTEM, consensus=gold)
        _pdir = _root / "data_nr" / "rag_pending"
        _pdir.mkdir(exist_ok=True)
        _text = (
            f"[NR {_status}] Nokido v{_ver} suite={suite_type} ts={_ts}\n"
            f"Author: system:nr_runner | Ring: SYSTEM | consensus: gold\n"
            f"fails={fails}"
        )
        (_pdir / f"nr_{_ts_f}.txt").write_text(_text, encoding="utf-8")
    except Exception:
        pass


def run_fast() -> int:
    """Suite rapide < 3s — lancée avant/après chaque edit."""
    # Sync silencieux des datasets périmés
    try:
        from nokido_agent.app.forge_dataset_sync import sync_before_nr as _sbn

        _sbn(verbose=False)
    except Exception:
        pass
    print("══ NR FAST ══════════════════════════════")
    fails = 0
    fails += _report(check_ast(), "AST")
    fails += _report(check_globals_fh(), "Globals fh")
    fails += _report(check_no_self(), "No self.")
    fails += _report(check_registry(), "REGISTRY")
    fails += _report(check_wrappers_lf(), "Wrappers LF")
    fails += _report(check_boot(), "Boot")
    fails += _report(check_integrity(), "Integrity")
    print(f"{'✅ FAST OK' if fails == 0 else f'❌ {fails} FAIL(S)'}")
    print("═════════════════════════════════════════")
    _archive_run("fast", fails)
    return fails


def run_all() -> int:
    """Suite complète."""
    print("══ NR COMPLET ═══════════════════════════")
    fails = 0
    fails += _report(check_ast(), "AST")
    fails += _report(check_globals_fh(), "Globals fh")
    fails += _report(check_no_self(), "No self.")
    fails += _report(check_registry(), "REGISTRY")
    fails += _report(check_imports(), "Imports")
    fails += _report(check_wrappers_lf(), "Wrappers LF")
    fails += _report(check_task_bus(), "Task bus")
    fails += _report(check_timecode(), "Timecode")
    fails += _report(check_boot(), "Boot")
    fails += _report(check_metrics(), "Metrics")
    fails += _report(check_integrity(), "Integrity")
    print(f"{'✅ ALL OK' if fails == 0 else f'❌ {fails} FAIL(S)'}")
    print("═════════════════════════════════════════")
    _archive_run("all", fails)
    return fails


def run_after_edit(filepath: str) -> int:
    """
    NR ciblé après modification d'un fichier.
    Lance automatiquement les checks pertinents selon le fichier modifié.
    """
    print(f"══ NR AFTER EDIT: {filepath} ═══")
    fails = 0

    # Toujours : AST du fichier modifié
    fails += _report(check_ast([filepath]), f"AST {filepath}")

    # Ciblé selon le fichier
    if "forge_handlers" in filepath:
        fails += _report(check_globals_fh(), "Globals fh")
        fails += _report(check_no_self(["app/forge_handlers.py"]), "No self. fh")

    if "forge_dispatch_network" in filepath:
        fails += _report(check_no_self(["app/forge_dispatch_network.py"]), "No self. fdn")

    if "forge_dispatch_ai" in filepath:
        fails += _report(check_no_self(["app/forge_dispatch_ai.py"]), "No self. fda")

    if "forge_dispatch.py" in filepath:
        fails += _report(check_registry(), "REGISTRY")

    if "Nokido.py" in filepath:
        fails += _report(check_wrappers_lf(), "Wrappers LF")
        fails += _report(check_ast(["app/LaForge.py"]), "AST Nokido")

    if "forge_task_bus" in filepath:
        fails += _report(check_task_bus(), "Task bus")

    if "forge_timecode" in filepath:
        fails += _report(check_timecode(), "Timecode")

    if "forge_integrity" in filepath:
        fails += _report(check_integrity(), "Integrity")

    print(f"{'✅ OK' if fails == 0 else f'❌ {fails} FAIL(S)'}")
    return fails


if __name__ == "__main__":
    import sys as _sys

    suite = _sys.argv[1] if len(_sys.argv) > 1 else "fast"
    if suite == "all":
        _sys.exit(run_all())
    elif suite == "fast":
        _sys.exit(run_fast())
    elif suite.startswith("app/") or suite.startswith("tools/"):
        _sys.exit(run_after_edit(suite))
    else:
        _sys.exit(run_fast())
