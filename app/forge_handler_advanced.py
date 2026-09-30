"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_handler_advanced
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_handler_advanced.py
Handlers avances Nokido v17
"""

import asyncio, os, sqlite3, subprocess, sys, time
from pathlib import Path


from nokido_agent.app.forge_utils import _safe_llm_text


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def _team_run(task: str, agents: list[str]) -> dict:
    """Execute a task using a team of agents.

    Creates a default team, activates specified agents (with duplication handling),
    and runs the task through a LeadOrchestrator.

    Args:
        task: The task description to execute.
        agents: List of agent IDs to activate for the team.

    Returns:
        Dictionary containing the team execution results.

    Raises:
        Exception: If team execution fails (propagated from orchestrator).
    """
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

    team = _default_team()
    seen = {}
    for pid in agents:
        if pid not in seen:
            team.activate(pid)
            seen[pid] = 1
        else:
            base = next((pp for pp in team.participants if pp.id == pid), None)
            if base:
                import copy as _cp

                cl = _cp.deepcopy(base)
                cl.id = f"{pid}_{seen[pid] + 1}"
                cl.config = dict(base.config)
                cl.active = True
                team.participants.append(cl)
            seen[pid] += 1
    orc = LeadOrchestrator()
    loop = asyncio.new_event_loop()
    res = loop.run_until_complete(orc.run(task, team))
    loop.close()
    return res


def handle_optimize_core(args: str = "", **kw: object) -> str:
    """@optimize_core - AST + dispatch deps + LLM consensus.

    Performs comprehensive codebase health check:
    1. AST syntax validation across Python files (excluding sensitive paths)
    2. Dispatch dependency verification
    3. LLM-based architectural consensus

    Args:
        args: Unused command arguments (maintains interface consistency).
        **kw: Additional keyword arguments (ignored).

    Returns:
        Multi-line string report with validation results and recommendations.
    """
    import ast as _ast

    out = []
    errors = []
    ok = 0
    # IO_STABILITY_V1 — exclure shadow_mutation, history Windows, cache NPU
    _EXCLUDE = [
        "__pycache__",
        "backups",
        "legacy",
        ".git",
        "shadow_mutation",
        "failed_mutation",
        "AppData",
        "History",
        "WindowsApps",
        ".cache",
        "sandbox",
        ".mypy_cache",
    ]
    for py in Path(str(ROOT)).rglob("*.py"):
        if any(x in str(py) for x in _EXCLUDE):
            continue
        try:
            _ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            ok += 1
        except SyntaxError as e:
            errors.append(f"{py.relative_to(ROOT)}: {e}")
    out.append(f"AST: {ok} OK, {len(errors)} erreurs")
    out.extend(errors[:10])
    dp = ROOT / "app" / "forge_dispatch.py"
    if dp.exists():
        src = dp.read_text(encoding="utf-8", errors="ignore")
        missing = []
        for line in src.splitlines():
            if "_lazy(" in line or "_lazy_at(" in line:
                parts = line.split('"')
                mod = parts[1] if len(parts) > 1 else ""
                if mod and not (ROOT / "app" / f"{mod}.py").exists():
                    missing.append(mod)
        out.append(f"Dispatch manquants: {missing}" if missing else "Dispatch: OK")
    try:
        res = _team_run(f"Architecture check - {len(errors)} AST errors. 3 recommandations.", ["laforge", "llamacpp"])
        for t in res.get("results", []):
            out.append(f"[{t.get('participant_id')}] {str(t.get('response', ''))[:200]}")
    except Exception as e:
        out.append(f"LLM: {e}")
    return "\n".join(out)


def handle_sprint_refactor(args: str = "", **kw: object) -> str:
    """@sprint_refactor [module] - Refactor + commit guard.

    Analyzes and refactors a specified module using LLM assistance,
    then validates syntax and commits changes via git.

    Args:
        args: Target module path (relative to ROOT or app/).
        **kw: Additional keyword arguments (ignored).

    Returns:
        Multi-line string with analysis, fix status, and git operation results.
    """
    if not args.strip():
        return "Usage: @sprint_refactor <module.py>"
    pp = ROOT / args.strip()
    if not pp.exists():
        pp = ROOT / "app" / args.strip()
    if not pp.exists():
        return f"Introuvable: {args.strip()}"
    out = []
    src = pp.read_text(encoding="utf-8", errors="ignore")
    try:
        agent = "gemini" if _gs("GEMINI_API_KEY") else "laforge"
        res = _team_run(f"Dette technique:\n```python\n{src[:2000]}\n```", [agent])
        out.append(_safe_llm_text(res)[:300])
    except Exception as e:
        out.append(f"Analyse: {e}")
    try:
        res2 = _team_run(f"Corrige ce module, code seulement:\n```python\n{src[:3000]}\n```", ["laforge"])
        corrected = str(res2.get("results", [{}])[0].get("response", ""))
        if "```python" in corrected:
            corrected = corrected.split("```python")[1].split("```")[0]
        if len(corrected) > 100:
            import ast as _a

            try:
                _a.parse(corrected)
                pp.write_text(corrected, encoding="utf-8")
                out.append(f"[Fix] {len(corrected)} chars")
            except SyntaxError as e:
                out.append(f"[Fix] SyntaxError: {e}")
    except Exception as e:
        out.append(f"Fix: {e}")
    from nokido_agent.app.forge_python_bin import run_python

    r = run_python(["-m", "py_compile", str(pp)], cwd=str(ROOT), capture_output=True, encoding="utf-8")
    if r.returncode == 0:
        rel = str(pp.relative_to(ROOT))
        subprocess.run(["git", "add", rel], cwd=str(ROOT), capture_output=True)
        msg = f"refactor: {pp.name} via @sprint_refactor"
        subprocess.run(["git", "commit", "-m", msg], cwd=str(ROOT), capture_output=True)
        out.append(f"[Git] {msg}")
    else:
        out.append(f"[Git] bloque: {r.stderr[:60]}")
    return "\n".join(out)


def handle_app_factory(args: str = "", **kw: object) -> str:
    """@app_factory [nom] - Projet PySide6 isole + RAG dedie.

    Creates an isolated PySide6 project structure with:
    - Standard src/data/tests directories
    - SQLite RAG database with event logging schema
    - Auto-generated main.py scaffold (optionally LLM-enhanced)
    - Project README

    Args:
        args: Project name (spaces converted to underscores).
        **kw: Additional keyword arguments (ignored).

    Returns:
        Multi-line string with creation status and paths.
    """
    name = args.strip().replace(" ", "_") or "NewProject"
    proj = ROOT / "projects" / name
    out = []
    for sub in ["src", "data", "tests"]:
        (proj / sub).mkdir(parents=True, exist_ok=True)
    out.append(f"[FS] {proj}")
    db = proj / "data" / "embeddings.db"
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS event_log "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timecode TEXT, sequence_id INTEGER, session_id TEXT, "
            "agent_id TEXT, event_type TEXT, target TEXT, "
            "payload TEXT, status TEXT)"
        )
        conn.commit()
        conn.close()
        out.append(f"[RAG] {db.name}")
    except Exception as e:
        out.append(f"[RAG] {e}")
    scaffold = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication, QMainWindow\n\n"
        f"class MainWindow(QMainWindow):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        f"        self.setWindowTitle('{name}')\n"
        "        self.setMinimumSize(800, 600)\n\n"
        "if __name__ == '__main__':\n"
        "    app = QApplication(sys.argv)\n"
        "    w = MainWindow(); w.show()\n"
        "    sys.exit(app.exec())\n"
    )
    try:
        res = _team_run(f"Code PySide6 QMainWindow complet pour '{name}'. Code seulement.", ["laforge"])
        code = _safe_llm_text(res)
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        if len(code) > 100:
            scaffold = code
    except Exception:
        pass
    (proj / "src" / "main.py").write_text(scaffold, encoding="utf-8")
    out.append(f"[Scaffold] {len(scaffold)} chars")
    (proj / "README.md").write_text(f"# {name}\nGenere par LaForge\n")
    out.append(f"[Done] {proj}")
    return "\n".join(out)


def handle_multi_llm(args: str = "", **kw: object) -> str:
    """@multi_llm [question] - Debat 3 agents Sequential_Consensus.

    Orchestrates a multi-agent debate on the given question using
    sequentially activated agents (nokido, llamacpp, and optionally
    deepseek_direct or gemini based on API key availability).

    Args:
        args: The question/topic for multi-agent debate.
        **kw: Additional keyword arguments (ignored).

    Returns:
        Formatted string with each agent's response truncated to 400 chars.
    """
    if not args.strip():
        return "Usage: @multi_llm <question>"
    agents = ["laforge", "llamacpp"]
    if _gs("DEEPSEEK_API_KEY"):
        agents.append("deepseek_direct")
    elif _gs("GEMINI_API_KEY"):
        agents.append("gemini")
    try:
        res = _team_run(args.strip(), agents)
        out = [f"=== Multi-LLM ({len(res.get('results', []))} agents) ==="]
        for t in res.get("results", []):
            out.append(f"[{t.get('participant_id')}]\n{str(t.get('response', ''))[:400]}")
        return "\n\n".join(out)
    except Exception as e:
        return f"Erreur: {e}"


def handle_deep_search(args: str = "", **kw: object) -> str:
    """@deep_search [query] - Web + RAG + ADR Ring2.

    Performs multi-source deep search:
    1. Web search via forge_at_dispatch
    2. RAG indexing of query
    3. ADR (Architecture Decision Record) generation in Ring2 format

    Args:
        args: Search query string.
        **kw: Additional keyword arguments (ignored).

    Returns:
        Multi-line string with web results, RAG status, and ADR file path.
    """
    if not args.strip():
        return "Usage: @deep_search <query>"
    out = []
    try:
        from nokido_agent.app.forge_at_dispatch import handle_at_web

        out.append(f"[Web] {str(handle_at_web('search ' + args.strip()))[:300]}")
    except Exception as e:
        out.append(f"[Web] {e}")
    try:
        from nokido_agent.app.forge_rag_engine import get_rag

        get_rag().ingest_text(args.strip(), source="@deep_search")
        out.append("[RAG] Indexe")
    except Exception as e:
        out.append(f"[RAG] {e}")
    try:
        adr = _team_run(
            f"ADR Ring2 concise pour: {args.strip()}\nFormat: Titre/Contexte/Decision/Consequences.", ["laforge"]
        )
        txt = str(adr.get("results", [{}])[0].get("response", ""))[:600]
        adr_dir = ROOT / "docs" / "adr"
        adr_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        (adr_dir / f"adr_{ts}.md").write_text(f"# ADR\n\n{txt}", encoding="utf-8")
        out.append(f"[ADR] adr_{ts}.md")
    except Exception as e:
        out.append(f"[ADR] {e}")
    return "\n".join(out)


def handle_safety_audit(args: str = "", **kw: object) -> str:
    """@safety_audit - Scan leaks + gitignore avant push.

    Security pre-commit audit:
    1. Scans staged files for credential patterns
    2. Verifies .gitignore contains essential exclusions
    3. Checks Nokido.env for exposed long secrets

    Args:
        args: Unused command arguments (maintains interface consistency).
        **kw: Additional keyword arguments (ignored).

    Returns:
        Multi-line audit report with leak findings and .gitignore status.
    """
    out = []
    patterns = ["api_key", "password", "secret", "sk-", "gsk_"]
    r = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(ROOT), capture_output=True, encoding="utf-8", errors="replace")
    staged = [f.strip() for f in r.stdout.splitlines() if f.strip()]
    leaks = []
    for fname in staged:
        fp = ROOT / fname
        if not fp.exists():
            continue
        try:
            c = fp.read_text(encoding="utf-8", errors="ignore").lower()
            for pat in patterns:
                idx = c.find(pat)
                if idx >= 0:
                    ctx = c[max(0, idx - 5) : idx + 30].replace("\n", " ")
                    leaks.append(f"{fname}: {ctx}")
                    break
        except Exception:
            pass
    out.append(f"[Scan] {len(leaks)} leaks / {len(staged)} stagés")
    out.extend(leaks[:5])
    gi = ROOT / ".gitignore"
    must = [".env", "Nokido.env", "*.db", "__pycache__"]
    if gi.exists():
        gi_src = gi.read_text(encoding="utf-8", errors="ignore")
        missing = [m for m in must if m not in gi_src]
        out.append(f"[.gitignore] manque: {missing}" if missing else "[.gitignore] OK")
    env = ROOT / "Nokido.env"
    if env.exists():
        exposed = [
            ln.split("=")[0].strip()
            for ln in env.read_text(encoding="utf-8", errors="ignore").splitlines()
            if "=" in ln and not ln.startswith("#") and len(ln.split("=", 1)[1].strip()) > 8
        ]
        out.append(f"[.env] clair: {exposed[:5]}" if exposed else "[.env] vide OK")
    return "\n".join(out)
