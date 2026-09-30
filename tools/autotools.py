"""
tools/autotools.py — Autotools Nokido v1.0
============================================
Package central de tous les outils du projet, exposés comme commandes @ natives.

USAGE depuis Nokido (TUI) :
    @tools list              — liste tous les outils disponibles
    @tools run <nom> [args]  — exécute un outil
    @tools check             — vérifie l'état de tous les outils (AST + import)
    @tools update            — régénère les stubs + rebuild atlas

USAGE depuis CLI :
    python tools/autotools.py check
    python tools/autotools.py run <nom> [args...]
    python tools/autotools.py list

AJOUT D'UN OUTIL :
    1. Créer une fonction run_xxx(args: list) -> str dans ce fichier
    2. L'enregistrer dans TOOLS_REGISTRY
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/bootstrap : package central des outils Nokido"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import importlib.util
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Chemins
# ─────────────────────────────────────────────────────────────────────────────
TOOLS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOLS_DIR.parent
APP_DIR = ROOT_DIR / "app"
TESTS_DIR = ROOT_DIR / "tests"
sys.path.insert(0, str(TOOLS_DIR / "research"))  # forge_distribution y vivait (retire)


def _load_distribution_manager():
    """forge_distribution a ete retire de tools/research/ (orphelin du move 20260416).
    Import DYNAMIQUE guarde : evite l'import statique d'un module fantome (scan AST) et
    remonte une erreur explicite si le module reste absent, sans casser autotools."""
    import importlib

    return importlib.import_module("forge_distribution").get_distribution_manager()


# ─────────────────────────────────────────────────────────────────────────────
# Registre des outils
# ─────────────────────────────────────────────────────────────────────────────


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable,
        path: Path | None = None,
        category: str = "général",
    ):
        self.name = name
        self.description = description
        self.fn = fn
        self.path = path
        self.category = category

    def run(self, args: list[str] | None = None) -> str:
        try:
            return self.fn(args or [])
        except Exception as e:
            import traceback

            return f"❌ {self.name}: {e}\n{traceback.format_exc()[-600:]}"


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : INDEXATION & NPU
# ─────────────────────────────────────────────────────────────────────────────


def run_index(args: list[str]) -> str:
    """Indexe le projet dans embeddings.db via IndexNokido.py"""
    script = ROOT_DIR / "IndexNokido.py"
    if not script.exists():
        return "❌ IndexNokido.py introuvable"
    result = _run_script(script, args)
    return result


def run_index_continue(args: list[str]) -> str:
    """Indexe pour Continue.dev via IndexpourContinue.py"""
    script = ROOT_DIR / "IndexpourContinue.py"
    if not script.exists():
        return "❌ IndexpourContinue.py introuvable"
    return _run_script(script, args)


def run_diag_npu(args: list[str]) -> str:
    """Diagnostic runtime NPU (VitisAI / ONNX)"""
    script = ROOT_DIR / "diagnostic_npu.py"
    return _run_script(script, args)


def run_calib_npu(args: list[str]) -> str:
    """Calibration quantification NPU"""
    script = ROOT_DIR / "calib_npu.py"
    return _run_script(script, args)


def run_quantize(args: list[str]) -> str:
    """Quantification modèle AMD/NPU via quantize_amd.py"""
    script = ROOT_DIR / "quantize_amd.py"
    return _run_script(script, args)


def run_export_base(args: list[str]) -> str:
    """Export modèle base en ONNX"""
    script = ROOT_DIR / "export_base.py"
    return _run_script(script, args)


def run_export_clean(args: list[str]) -> str:
    """Export modèle nettoyé ONNX"""
    script = ROOT_DIR / "export_clean.py"
    return _run_script(script, args)


def run_recherche_npu(args: list[str]) -> str:
    """Recherche vectorielle NPU (test/bench)"""
    script = ROOT_DIR / "recherche_NPU.py"
    return _run_script(script, args)


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : CODE & STUBS
# ─────────────────────────────────────────────────────────────────────────────


def run_stub(args: list[str]) -> str:
    """Génère un stub AST d'un fichier .py — usage: stub <fichier.py>"""
    if not args:
        return "Usage: @tools run stub <fichier.py>"
    target = Path(args[0])
    if not target.exists():
        target = APP_DIR / args[0]
    if not target.exists():
        return f"❌ Fichier introuvable: {args[0]}"
    sys.path.insert(0, str(TOOLS_DIR))
    from nokido_agent.tools.generate_stub import generate_stub

    return generate_stub(str(target))


def run_ast_check(args: list[str]) -> str:
    """Vérifie la syntaxe AST de tous les .py du projet"""
    errors = []
    ok = 0
    targets = args if args else []
    if not targets:
        targets = [str(p) for p in APP_DIR.glob("*.py")]
        targets += [str(p) for p in ROOT_DIR.glob("*.py")]
        targets += [str(p) for p in TOOLS_DIR.glob("*.py")]

    for path in targets:
        try:
            ast.parse(Path(path).read_text(encoding="utf-8", errors="ignore"))
            ok += 1
        except SyntaxError as e:
            errors.append(f"  ❌ {path} L{e.lineno}: {e.msg}")

    lines = [f"AST check: {ok} OK, {len(errors)} erreurs"]
    lines += errors
    return "\n".join(lines)


def run_semantic_scan(args: list[str]) -> str:
    """Scan sémantique du projet (semantic_scanner.py)"""
    sys.path.insert(0, str(APP_DIR))
    try:
        from nokido_agent.app.semantic_scanner import extract_nodes

        target = Path(args[0]) if args else APP_DIR / "Nokido.py"
        nodes = extract_nodes(str(target))
        lines = [f"Scan sémantique : {target.name} — {len(nodes)} nœuds"]
        for n in nodes[:20]:
            lines.append(f"  {n}")
        if len(nodes) > 20:
            lines.append(f"  … (+{len(nodes) - 20} autres)")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ semantic_scanner: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : TESTS
# ─────────────────────────────────────────────────────────────────────────────


def run_tests(args: list[str]) -> str:
    """Lance pytest sur le dossier tests/ — usage: tests [fichier] [-v] [-k pattern]"""
    cmd = [sys.executable, "-m", "pytest", str(TESTS_DIR)]
    if args:
        # Si premier arg est un nom de fichier test
        if args[0].endswith(".py"):
            cmd = [sys.executable, "-m", "pytest", str(TESTS_DIR / args[0])]
            args = args[1:]
    cmd += args if args else ["-v", "--tb=short", "-q"]
    return _run_cmd(cmd, cwd=ROOT_DIR)


def run_test_dispatch(args: list[str]) -> str:
    """Lance uniquement les tests du dispatcher @"""
    return run_tests(["test_dispatch.py", "-v", "--tb=short"])


def run_test_all(args: list[str]) -> str:
    """Lance toute la suite de tests avec rapport"""
    return run_tests(["--tb=short", "-q"])


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : ATLAS & SITUATION
# ─────────────────────────────────────────────────────────────────────────────


def run_atlas(args: list[str]) -> str:
    """Rebuild l'atlas du projet (project_atlas.json + map.md)"""
    # Via MCP run atlas_build — ici on le fait directement
    atlas_path = ROOT_DIR / "project_atlas.json"
    import json

    files = sorted(
        [
            str(p.relative_to(ROOT_DIR))
            for p in ROOT_DIR.rglob("*.py")
            if ".git" not in str(p) and "__pycache__" not in str(p) and ".mypy_cache" not in str(p)
        ]
    )
    data = {"generated": time.strftime("%Y-%m-%d %H:%M"), "files": len(files), "paths": files}
    atlas_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"✅ Atlas rebuilt: {len(files)} fichiers → {atlas_path.name}"


def run_check(args: list[str]) -> str:
    """Vérifie l'état de tous les outils enregistrés"""
    lines = [
        "╔══════════════════════════════════════════════════════╗",
        "║          AUTOTOOLS CHECK — Nokido                  ║",
        "╚══════════════════════════════════════════════════════╝",
    ]

    by_cat: dict[str, list[Tool]] = {}
    for t in TOOLS_REGISTRY.values():
        by_cat.setdefault(t.category, []).append(t)

    total_ok = 0
    total_err = 0
    for cat, tools in sorted(by_cat.items()):
        lines.append(f"\n  ── {cat.upper()} ──")
        for t in sorted(tools, key=lambda x: x.name):
            # Vérif : le callable existe
            fn_ok = callable(t.fn)
            # Vérif : le script source existe (si défini)
            path_ok = t.path is None or t.path.exists()
            status = "✅" if fn_ok and path_ok else "❌"
            suffix = "" if path_ok else f" (manquant: {t.path})"
            lines.append(f"  {status} {t.name:<20} {t.description[:45]}{suffix}")
            if fn_ok and path_ok:
                total_ok += 1
            else:
                total_err += 1

    lines.append(f"\n  Total: {total_ok} OK, {total_err} erreurs")

    # Vérif AST des fichiers critiques
    lines.append("\n  ── SANTÉ FICHIERS CRITIQUES ──")
    critical = [
        APP_DIR / "Nokido.py",
        APP_DIR / "forge_dispatch.py",
        TOOLS_DIR / "nokido_mcp_server.py",
        TOOLS_DIR / "autotools.py",
    ]
    for f in critical:
        try:
            ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            lines.append(f"  ✅ {f.relative_to(ROOT_DIR)}")
        except SyntaxError as e:
            lines.append(f"  ❌ {f.relative_to(ROOT_DIR)} L{e.lineno}: {e.msg}")

    return "\n".join(lines)


def run_list(args: list[str]) -> str:
    """Liste tous les outils disponibles"""
    lines = ["Autotools Nokido — outils disponibles:\n"]
    by_cat: dict[str, list[Tool]] = {}
    for t in TOOLS_REGISTRY.values():
        by_cat.setdefault(t.category, []).append(t)
    for cat, tools in sorted(by_cat.items()):
        lines.append(f"  {cat.upper()}")
        for t in sorted(tools, key=lambda x: x.name):
            lines.append(f"    @tools run {t.name:<18} — {t.description}")
        lines.append("")
    return "\n".join(lines)


def run_update(args: list[str]) -> str:
    """Met à jour stubs + atlas + vérifie AST"""
    results = []
    results.append(run_atlas([]))
    results.append(run_ast_check([]))
    return "\n".join(results)


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : GIT
# ─────────────────────────────────────────────────────────────────────────────


def run_gc_collect(args: list[str]) -> str:
    """Force un GC complet et retourne le rapport mémoire."""
    try:
        sys.path.insert(0, str(APP_DIR))
        from nokido_agent.app.forge_health import force_gc

        return force_gc()
    except Exception as e:
        import gc

        collected = gc.collect()
        return f"GC : {collected} objets collectés\nforge_health non disponible: {e}"


def run_memory_report(args: list[str]) -> str:
    """Rapport mémoire détaillé."""
    try:
        sys.path.insert(0, str(APP_DIR))
        from nokido_agent.app.forge_health import memory_report

        return memory_report()
    except Exception as e:
        return f"memory_report indisponible: {e}"


def run_health_check(args: list[str]) -> str:
    """Lance les startup checks complets (sync)."""
    try:
        sys.path.insert(0, str(APP_DIR))
        from nokido_agent.app.forge_health import (
            check_database,
            check_imports,
            check_modules_externalized,
            check_no_bare_globals,
            check_registry,
            check_wrappers,
        )

        all_results = []
        for fn in [
            check_imports,
            check_registry,
            check_database,
            check_modules_externalized,
            check_no_bare_globals,
            check_wrappers,
        ]:
            try:
                all_results.extend(fn())
            except Exception:
                pass
        ok = sum(1 for r in all_results if r.ok)
        fail = sum(1 for r in all_results if not r.ok)
        lines = [f"Health check: {ok} OK / {fail} FAIL"]
        for r in all_results:
            if not r.ok:
                lines.append(f"  FAIL {r.name}: {r.detail}")
        if fail == 0:
            lines.append("  Tout est OK ✅")
        return "\n".join(lines)
    except Exception as e:
        return f"health-check erreur: {e}"


def run_llm_metrics(args: list[str]) -> str:
    """Rapport métriques LLM collectées."""
    try:
        sys.path.insert(0, str(APP_DIR))
        from nokido_agent.app.forge_metrics import get_collector

        return get_collector().report()
    except Exception as e:
        return f"llm-metrics: {e}"


def run_benchmark_llm(args: list[str]) -> str:
    """
    Benchmark comparatif providers : envoie le même prompt à Ollama + Gemini.
    Mesure latence et tokens/s pour chaque provider.
    """
    import asyncio
    import time

    sys.path.insert(0, str(APP_DIR))
    prompt = " ".join(args) if args else "Dis juste 'ok' en une réponse très courte."
    results = []

    async def _bench():
        # Ollama
        try:
            from nokido_agent.app.forge_ollama_bridge import OllamaBridge

            b = OllamaBridge()
            t0 = time.perf_counter()
            r = await b.propose(prompt, max_tokens=50)
            lat = (time.perf_counter() - t0) * 1000
            results.append(("ollama", lat, len(r), bool(r)))
        except Exception:
            results.append(("ollama", 0, 0, False))

        # Gemini
        try:
            from nokido_agent.app.forge_gemini_bridge import get_gemini_bridge

            b = get_gemini_bridge()
            if b.api_key:
                t0 = time.perf_counter()
                r = await b.ask(prompt, mode="READ_ONLY")
                lat = (time.perf_counter() - t0) * 1000
                results.append(("gemini", lat, len(r), bool(r)))
            else:
                results.append(("gemini", 0, 0, None))  # non configuré
        except Exception:
            results.append(("gemini", 0, 0, False))

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_bench())
    finally:
        loop.close()

    lines = [f"Benchmark LLM — prompt: '{prompt[:40]}'"]
    for provider, lat, chars, ok in results:
        if ok is None:
            lines.append(f"  {provider:<12} non configuré (clé API manquante)")
        elif ok:
            tps = round((chars / 4) / max(lat / 1000, 0.001), 1)
            lines.append(f"  {provider:<12} {lat:>7.0f}ms  ~{chars // 4:>4} tok  {tps:>6.1f} tok/s")
        else:
            lines.append(f"  {provider:<12} ERREUR")
    return "\n".join(lines)


def run_nr_fast(args: list[str]) -> str:
    """NR rapide via mcp_nr."""
    try:
        tools_dir = str(ROOT_DIR / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        sys.path.insert(0, str(APP_DIR))
        import contextlib
        import io

        from nokido_agent.app.mcp_nr import run_fast

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fails = run_fast()
        return buf.getvalue()
    except Exception as e:
        return f"nr-fast erreur: {e}"


def run_litellm_status(args: list[str]) -> str:
    """Statut LiteLLM bridge + test connexion Ollama"""
    lines = ["LiteLLM Bridge Status\n"]
    # Charger Nokido.env
    env_path = ROOT_DIR / "Nokido.env"
    env = {}
    if env_path.exists():
        for l in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if l.strip() and not l.startswith("#") and "=" in l:
                k, _, v = l.partition("=")
                env[k.strip()] = v.strip()
    model = env.get("LITELLM_MODEL", "ollama/qwen2.5")
    api_base = env.get("LITELLM_API_BASE", "http://localhost:11434")
    lines.append(f"  LITELLM_MODEL    : {model}")
    lines.append(f"  LITELLM_API_BASE : {api_base}")
    # Vérifier litellm installé
    import importlib.util

    has_ll = importlib.util.find_spec("litellm") is not None
    lines.append(
        f"  litellm installé : {'✅' if has_ll else '❌ pip install litellm --break-system-packages'}"
    )
    # Vérifier Ollama joignable
    try:
        import urllib.request

        urllib.request.urlopen(api_base, timeout=3)
        lines.append(f"  Ollama joignable : ✅ {api_base}")
    except Exception as e:
        lines.append(f"  Ollama joignable : ❌ {e}")
    # forge_litellm_bridge.py
    bridge_path = APP_DIR / "forge_litellm_bridge.py"
    lines.append(f"  forge_litellm_bridge.py : {'✅' if bridge_path.exists() else '❌'}")
    return "\n".join(lines)


def run_collab_history(args: list[str]) -> str:
    """Historique sessions collab depuis shared_prompt_log"""
    db_path = ROOT_DIR / "RAG" / "embeddings.db"
    if not db_path.exists():
        return "❌ embeddings.db introuvable"
    try:
        import sqlite3

        con = sqlite3.connect(str(db_path))
        # Vérifier que la table existe
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "shared_prompt_log" not in tables:
            return "Aucune session collab (table shared_prompt_log absente)"
        rows = con.execute(
            "SELECT session_id, mode, COUNT(*) as turns, "
            "MIN(timecode) as started, MAX(timecode) as last_msg, "
            "GROUP_CONCAT(DISTINCT agent_id) as agents "
            "FROM shared_prompt_log "
            "GROUP BY session_id ORDER BY last_msg DESC LIMIT 20"
        ).fetchall()
        con.close()
        if not rows:
            return "Aucune session collab enregistrée."
        out = [f"Sessions collab ({len(rows)}) :\n"]
        for r in rows:
            out.append(
                f"  {r[0]:<32}  mode={r[1] or '?':<14}  "
                f"{r[2]} tours  agents={r[5] or '?'}  "
                f"last={r[4][11:19] if r[4] else '?'}"
            )
        if args:
            # args[0] = session_id à détailler
            sid = args[0]
            con2 = sqlite3.connect(str(db_path))
            msgs = con2.execute(
                "SELECT * FROM shared_prompt_log WHERE session_id=? ORDER BY sequence_id", (sid,)
            ).fetchall()
            con2.close()
            if msgs:
                out.append(f"\nDétail session {sid} ({len(msgs)} messages) :")
                for m in msgs:
                    out.append(f"  [{m[3]:3d}] {m[2][11:19]}  {m[4]:<15} [{m[5]:<9}]  {m[7][:80]}")
        return "\n".join(out)
    except Exception as e:
        return f"❌ collab-history: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# ── OUTILS : DISTRIBUTION SQLite
# ─────────────────────────────────────────────────────────────────────────────


def run_dist_status(args: list[str]) -> str:
    """Statut complet de l'arbre de distribution (Hub / Replica / Cache INT8)."""
    sys.path.insert(0, str(APP_DIR))
    try:
        dm = _load_distribution_manager()
        st = dm.status()
        hub = st["hub"]
        rep = st["replica"]
        cac = st["semantic_cache"]
        lines = [
            "Distribution SQLite — Arbre v16.6",
            f"  Hub     : {hub['db_size_mb']}MB  WAL={hub['journal_mode']}  vecteurs={hub['vectors_mb']}MB",
            f"  Tables  : { {t: n for t, n in hub['tables'].items()} }",
            f"  Replica : {rep.get('status', '?')}  tables={list(rep.get('tables', {}).keys())}",
            f"  Cache   : {'OK ' + str(cac['size_mb']) + 'MB' if cac['exists'] else 'absent'}  (INT8 quantisé)",
        ]
        n_new = rep.get("total_new", 0)
        if n_new:
            lines.append(f"  \u26a0  Désynchro: {n_new} lignes nouvelles — lancer dist-sync")
        else:
            lines.append("  \u2705 Replica synchronisée")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ dist-status: {e}"


def run_dist_sync(args: list[str]) -> str:
    """Synchronise incrémentalement la réplique depuis le Hub."""
    sys.path.insert(0, str(APP_DIR))
    try:
        import json

        dm = _load_distribution_manager()
        res = dm.incremental_sync()
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"❌ dist-sync: {e}"


def run_dist_cache(args: list[str]) -> str:
    """Génère/régénère le cache sémantique INT8 pour IA distante."""
    sys.path.insert(0, str(APP_DIR))
    try:
        import json

        dm = _load_distribution_manager()
        tbl = args[0] if args else "rag_chunks"
        nmax = int(args[1]) if len(args) > 1 else 5000
        res = dm.export_semantic_cache(source_table=tbl, max_rows=nmax)
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"❌ dist-cache: {e}"


def run_dist_replica(args: list[str]) -> str:
    """Exporte une réplique complète float32 pour les nœuds Grid."""
    sys.path.insert(0, str(APP_DIR))
    try:
        import json

        dm = _load_distribution_manager()
        res = dm.export_replica()
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"❌ dist-replica: {e}"


def run_git_status(args: list[str]) -> str:
    """git status --short"""
    return _run_cmd(["git", "status", "--short"], cwd=ROOT_DIR)


def run_git_diff(args: list[str]) -> str:
    """git diff --stat"""
    return _run_cmd(["git", "diff", "--stat"], cwd=ROOT_DIR)


def run_git_log(args: list[str]) -> str:
    """git log --oneline -10"""
    n = args[0] if args else "10"
    return _run_cmd(["git", "log", "--oneline", f"-{n}"], cwd=ROOT_DIR)


# ─────────────────────────────────────────────────────────────────────────────
# ── HELPERS INTERNES
# ─────────────────────────────────────────────────────────────────────────────


def _run_script(script: Path, args: list[str], timeout: int = 30) -> str:
    """Exécute un script Python et retourne stdout+stderr."""
    if not script.exists():
        return f"❌ Script introuvable: {script}"
    return _run_cmd([sys.executable, str(script)] + args, cwd=ROOT_DIR, timeout=timeout)


def _run_cmd(cmd: list[str], cwd: Path = ROOT_DIR, timeout: int = 30) -> str:
    """Exécute une commande et retourne stdout+stderr tronqués."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
            timeout=timeout,
        )
        out = (result.stdout or "") + (result.stderr or "")
        out = out.strip()
        if len(out) > 4000:
            out = out[:2000] + "\n…[tronqué]…\n" + out[-1000:]
        return out or "(pas de sortie)"
    except subprocess.TimeoutExpired:
        return f"❌ Timeout ({timeout}s)"
    except FileNotFoundError as e:
        return f"❌ Commande introuvable: {e}"
    except Exception as e:
        return f"❌ {e}"


def _load_module(path: Path):
    """Charge dynamiquement un module depuis son chemin."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRE FINAL
# ─────────────────────────────────────────────────────────────────────────────

TOOLS_REGISTRY: dict[str, Tool] = {
    # Indexation / NPU
    "index": Tool(
        "index",
        "Indexe le projet (embeddings.db)",
        run_index,
        ROOT_DIR / "IndexNokido.py",
        "indexation",
    ),
    "index-continue": Tool(
        "index-continue",
        "Indexe pour Continue.dev",
        run_index_continue,
        ROOT_DIR / "IndexpourContinue.py",
        "indexation",
    ),
    "diag-npu": Tool(
        "diag-npu",
        "Diagnostic runtime NPU/ONNX",
        run_diag_npu,
        ROOT_DIR / "diagnostic_npu.py",
        "npu",
    ),
    "calib-npu": Tool(
        "calib-npu",
        "Calibration quantification NPU",
        run_calib_npu,
        ROOT_DIR / "calib_npu.py",
        "npu",
    ),
    "quantize": Tool(
        "quantize",
        "Quantification modèle AMD/NPU",
        run_quantize,
        ROOT_DIR / "quantize_amd.py",
        "npu",
    ),
    "export-base": Tool(
        "export-base",
        "Export modèle base ONNX",
        run_export_base,
        ROOT_DIR / "export_base.py",
        "npu",
    ),
    "export-clean": Tool(
        "export-clean",
        "Export modèle nettoyé ONNX",
        run_export_clean,
        ROOT_DIR / "export_clean.py",
        "npu",
    ),
    "recherche-npu": Tool(
        "recherche-npu",
        "Recherche vectorielle NPU",
        run_recherche_npu,
        ROOT_DIR / "recherche_NPU.py",
        "npu",
    ),
    # Code / analyse
    "stub": Tool(
        "stub", "Génère stub AST d'un .py", run_stub, TOOLS_DIR / "generate_stub.py", "code"
    ),
    "ast-check": Tool(
        "ast-check", "Vérifie syntaxe AST de tous les .py", run_ast_check, None, "code"
    ),
    "semantic-scan": Tool(
        "semantic-scan",
        "Scan sémantique AST du projet",
        run_semantic_scan,
        APP_DIR / "semantic_scanner.py",
        "code",
    ),
    # Tests
    "tests": Tool("tests", "Lance pytest tests/", run_tests, TESTS_DIR, "tests"),
    "test-dispatch": Tool(
        "test-dispatch",
        "Tests non-régression dispatcher @",
        run_test_dispatch,
        TESTS_DIR / "test_dispatch.py",
        "tests",
    ),
    "test-all": Tool("test-all", "Suite complète de tests", run_test_all, TESTS_DIR, "tests"),
    # Atlas / projet
    "atlas": Tool(
        "atlas", "Rebuild atlas projet", run_atlas, ROOT_DIR / "project_atlas.json", "projet"
    ),
    "check": Tool("check", "Vérifie état de tous les outils", run_check, None, "projet"),
    "list": Tool("list", "Liste tous les outils disponibles", run_list, None, "projet"),
    "update": Tool("update", "Stubs + atlas + AST check", run_update, None, "projet"),
    # Git
    "git-status": Tool("git-status", "git status --short", run_git_status, None, "git"),
    "git-diff": Tool("git-diff", "git diff --stat", run_git_diff, None, "git"),
    "git-log": Tool("git-log", "git log --oneline -N", run_git_log, None, "git"),
    "litellm-status": Tool(
        "litellm-status", "Statut LiteLLM + test Ollama bridge", run_litellm_status, None, "collab"
    ),
    "collab-history": Tool(
        "collab-history", "Historique sessions collab", run_collab_history, None, "collab"
    ),
    "gc-collect": Tool("gc-collect", "Force GC + rapport mémoire", run_gc_collect, None, "system"),
    "memory": Tool("memory", "Rapport mémoire détaillé", run_memory_report, None, "system"),
    "health-check": Tool(
        "health-check",
        "Startup checks complets (NR + DB + imports)",
        run_health_check,
        None,
        "system",
    ),
    "nr-fast": Tool("nr-fast", "NR rapide (AST + globals + registry)", run_nr_fast, None, "system"),
    "llm-metrics": Tool(
        "llm-metrics", "Rapport métriques LLM (latence, tokens/s)", run_llm_metrics, None, "system"
    ),
    "benchmark-llm": Tool(
        "benchmark-llm", "Benchmark comparatif providers LLM", run_benchmark_llm, None, "system"
    ),
    # Distribution SQLite
    "dist-status": Tool(
        "dist-status",
        "Statut arbre distribution (Hub/Replica/Cache)",
        run_dist_status,
        None,
        "distribution",
    ),
    "dist-sync": Tool(
        "dist-sync", "Sync incrémentale Hub → Replica", run_dist_sync, None, "distribution"
    ),
    "dist-cache": Tool(
        "dist-cache", "Génère/régénère cache sémantique INT8", run_dist_cache, None, "distribution"
    ),
    "dist-replica": Tool(
        "dist-replica", "Export réplique complète float32", run_dist_replica, None, "distribution"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER Nokido — appelé par forge_dispatch via @tools
# ─────────────────────────────────────────────────────────────────────────────


async def handle_tools(app, cmd_line: str) -> None:
    """
    Handler @tools pour forge_dispatch.REGISTRY.
    Délègue vers TOOLS_REGISTRY.
    """
    import asyncio as _asyncio

    chat = app._chat_log()
    args = cmd_line[6:].strip().split()  # retire "@tools"
    sub = args[0].lower() if args else "list"

    if sub == "list":
        chat.write(run_list([]))
        return

    if sub == "check":
        chat.write("[dim]⏳ Vérification outils…[/]")

        async def _do():
            chat.write(run_check([]))

        _asyncio.create_task(_do())
        return

    if sub == "update":
        chat.write("[dim]⏳ Mise à jour…[/]")

        async def _do():
            chat.write(run_update([]))

        _asyncio.create_task(_do())
        return

    if sub == "run" and len(args) >= 2:
        tool_name = args[1]
        tool_args = args[2:]
        tool = TOOLS_REGISTRY.get(tool_name)
        if not tool:
            chat.write(f"[red]❌ Outil inconnu: {tool_name}[/]\n@tools list pour la liste")
            return
        chat.write(f"[dim]⏳ {tool_name}…[/]")

        async def _do(_t=tool, _a=tool_args):
            result = await _asyncio.get_event_loop().run_in_executor(None, _t.run, _a)
            chat.write(f"[bold]{_t.name}[/]\n{result}")

        _asyncio.create_task(_do())
        return

    # usage
    chat.write(
        "[bold]@tools[/] list              — liste les outils\n"
        "  @tools check             — vérifie l'état de tous les outils\n"
        "  @tools update            — stubs + atlas + AST check\n"
        "  @tools run <nom> [args]  — exécute un outil\n"
        "[dim]Exemple : @tools run test-dispatch[/]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(run_list([]))
        return

    sub = args[0]

    if sub == "check":
        print(run_check([]))
    elif sub == "list":
        print(run_list([]))
    elif sub == "update":
        print(run_update([]))
    elif sub == "run" and len(args) >= 2:
        tool_name = args[1]
        tool = TOOLS_REGISTRY.get(tool_name)
        if not tool:
            print(f"❌ Outil inconnu: {tool_name}")
            print(run_list([]))
            sys.exit(1)
        print(tool.run(args[2:]))
    else:
        # Essayer comme nom direct
        tool = TOOLS_REGISTRY.get(sub)
        if tool:
            print(tool.run(args[1:]))
        else:
            print(f"❌ Commande inconnue: {sub}")
            print(run_list([]))
            sys.exit(1)


if __name__ == "__main__":
    main()
