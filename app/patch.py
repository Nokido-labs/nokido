"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "infra/util : application de patchs (legacy)"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
nokido_mcp_server.py -- Serveur MCP unifie Nokido v13.5
7 outils intelligents + cache TTL + gc.collect + .mcpignore + NPU.

Outils :
  python_interpreter  Execute Python (namespace persistant, .mcpignore)
  file_read           Lit fichiers (modes: full/compressed/smart/stub/multi)
  file_write          Ecrit/edite/supprime/deplace/mkdir (.mcpignore)
  file_explore        Cherche/liste/arbre/info fichiers (cache)
  sql                 Query/execute/status sur embeddings.db WAL
  semantic_search     Recherche cosine NPU sur le code indexe
  system              Cache clear + mcpignore check

Config claude_desktop_config.json :
  {"mcpServers":{"Nokido":{
    "command":__import__("os").path.expanduser("~/miniforge3/python.exe"),
    "args":[__import__("os").path.expanduser("~/Script python IA/LaForge/tools/nokido_mcp_server.py")]}}}
"""

import ast, contextlib, difflib, fnmatch, gc, hashlib, io, json
import logging, os, re, shutil, sqlite3, sys, time, traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP
from datetime import datetime as _dt

# ── Config ──
PROJECT_ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
SANDBOX_DIR = PROJECT_ROOT / "sandbox"
LIVE_LOG = SANDBOX_DIR / "mcp_live.log"
TRACE_LOG = SANDBOX_DIR / "trace.log"
SITUATION_MD = PROJECT_ROOT / "SITUATION.md"
PID_FILE = SANDBOX_DIR / "server.pid"


# Context:


def _live_log(tool: str, msg: str, status: str = "OK") -> None:
    """crit un message de log en direct dans le fichier LIVE_LOG.

    Args:
        tool: Nom de l'outil ou module gnrant le log.
        msg: Message  enregistrer.
        status: Statut associ au message (dfaut: "OK").

    Note:
        Le message est tronqu  200 caractres. Toute exception lors de l'criture est silencieuse.
    """
    try:
        line = f"[{_dt.now().strftime('%H:%M:%S')}] [{status:4}] [{tool:18}] {msg[:200]}\n"
        with open(LIVE_LOG, "a", encoding="utf-8") as _f:
            _f.write(line)
    except Exception:
        pass


def _cleanup_old_instances() -> None:
    """Tue les instances fantomes du serveur."""
    current = __import__("os").getpid()
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        import psutil as _ps

        for proc in _ps.process_iter(["pid", "cmdline"]):
            try:
                if proc.info["pid"] == current:
                    continue
                cmd = " ".join(proc.info["cmdline"] or [])
                if "nokido_mcp_server.py" in cmd:
                    proc.terminate()
                    proc.wait(timeout=3)
                    _live_log("SYSTEM", f"Fantome PID={proc.info['pid']}", "WARN")
            except Exception:
                pass
    except ImportError:
        pass
    PID_FILE.write_text(str(current))


def _setup_logs() -> None:
    """Initialise sandbox propre + logs monitoring."""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    header = f"--- SESSION START: {_dt.now():%Y-%m-%d %H:%M:%S} ---\n"
    LIVE_LOG.write_text(header, encoding="utf-8")
    TRACE_LOG.write_text(header + "Monitoring actif (Get-Content -Wait)...\n", encoding="utf-8")
    for stale in ["watcher_output.log", "nokido_stdout.log", "nokido_stderr.log"]:
        p = SANDBOX_DIR / stale
        if p.exists():
            p.write_text("", encoding="utf-8")


APP_DIR = PROJECT_ROOT / "app"
DB_PATH = PROJECT_ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(APP_DIR))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("laforge-mcp")
try:
    for _l in (APP_DIR / "Nokido.py").read_text("utf-8", errors="ignore").splitlines()[:10]:
        if _l.startswith("__version__"):
            _VERSION = _l.split('"')[1]
            break
    else:
        _VERSION = "?"
except Exception:
    _VERSION = "?"

mcp = FastMCP("Nokido")

# ── Cache TTL ──
_CACHE: dict = {}
_CACHE_TTL = 600
_CACHE_MAX = 200


def _ck(tool, **kw) -> object:
    """Ck.

    Args:
        tool: Description.
    """
    return hashlib.md5(f"{tool}|{json.dumps(kw, sort_keys=True, default=str)}".encode()).hexdigest()


def _cg(k) -> str:
    """Cg.

    Args:
        k: Description.
    """
    if k in _CACHE:
        ts, r = _CACHE[k]
        age = time.time() - ts
        if age < _CACHE_TTL:
            return f"[CACHE:0tok {int(age)}s] {r}"
        del _CACHE[k]
    return None


def _cs(k, r) -> None:
    """Cs.

    Args:
        k: Description.
        r: Description.
    """
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda x: _CACHE[x][0])
        del _CACHE[oldest]
    _CACHE[k] = (time.time(), r)


"""Cj.

Args:
    data: Description.
"""


def _cj(data) -> object:
    """cj."""
    return json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)


# ── .mcpignore ──
_IGN_PATH = PROJECT_ROOT / ".mcpignore"
_IGN_MT: float = 0.0
_IGN_PAT: list[str] = [".mcpignore", "**/.mcpignore"]


def _load_ign() -> None:
    """Load ign."""
    global _IGN_MT, _IGN_PAT
    try:
        mt = _IGN_PATH.stat().st_mtime
    except FileNotFoundError:
        return
    if mt == _IGN_MT:
        return
    pats = [".mcpignore", "**/.mcpignore"]
    for l in _IGN_PATH.read_text("utf-8", errors="ignore").splitlines():
        l = l.strip()
        if l and not l.startswith("#"):
            pats.append(l)
    _IGN_PAT = pats
    _IGN_MT = mt


def _is_prot(p) -> object:
    """Is prot.

    Args:
        p: Description.
    """
    _load_ign()
    ap = os.path.realpath(p).replace("\\", "/")
    rp = os.path.relpath(ap, str(PROJECT_ROOT)).replace("\\", "/")
    bn = os.path.basename(ap)
    for pat in _IGN_PAT:
        pn = pat.rstrip("/")
        for c in (ap, rp, bn):
            if fnmatch.fnmatch(c, pn):
                return True, pat
            if pat.endswith("/") or "/" not in pat:
                if fnmatch.fnmatch(c, pn + "/*"):
                    return True, pat
                np_ = os.path.realpath(os.path.join(str(PROJECT_ROOT), pn)).replace("\\", "/")
                if ap.startswith(np_ + "/") or ap == np_:
                    return True, pat
    return False, ""


def _chkw(p) -> None:
    """Chkw.

    Args:
        p: Description.
    """
    ok, pat = _is_prot(p)
    if ok:
        raise PermissionError(f"[mcpignore] Bloque: '{p}' ('{pat}')")


def _res(p) -> object:
    """Res.

    Args:
        p: Description.
    """
    r = Path(p).resolve()
    root = PROJECT_ROOT.resolve()
    if not str(r).startswith(str(root)):
        raise PermissionError(f"Hors projet: {r}")
    return r


# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# 1. PYTHON INTERPRETER (v13.6 Robust)
# ══════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# PG + _PO namespace
# ════════════════════════════════════════════════════════════
class _PO:
    """po."""

    _ro = staticmethod(open)

    def __call__(self, f, m="r", *a, **kw) -> object:
        """Call.

        Args:
            f: Description.
            m: Description.
        """
        if any(x in m for x in "wax"):
            _chkw(str(f))
        return self._ro(f, m, *a, **kw)


_PG: dict = {"__builtins__": __builtins__}
_PG["open"] = _PO()
_SH_RE = re.compile(
    r'(?:shutil\.(?:move|copy2?|copytree)|os\.rename|os\.replace)\s*\([^,)]*,\s*["\']([^"\']+)["\']' "", re.M
)


# ════════════════════════════════════════════════════════════
# 1. PYTHON INTERPRETER (v13.6.1 GOLD)
# ════════════════════════════════════════════════════════════
@mcp.tool()
def python_interpreter(code: str) -> str:
    """Execute Python avec sandbox CWD et telemetry trace.log."""
    _live_log("python_interpreter", f"EXEC: {code[:100].strip()}...")

    # Anti-suicide
    if any(x in code for x in ["nokido_mcp_server.py", "mcp_server"]) and any(
        x in code for x in ["open", "write", "Path"]
    ):
        _live_log("python_interpreter", "AUTO-EDIT BLOCKED", "DENY")
        return "SECURITE: Modification du serveur interdite. Utilise file_write."

    os.chdir(PROJECT_ROOT)
    _PG.setdefault("__builtins__", __builtins__)
    _PG["datetime"] = datetime

    def mcp_trace(msg) -> None:
        """Mcp trace.

        Args:
            msg: Description.
        """
        try:
            with open(TRACE_LOG, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"[{datetime.now():%H:%M:%S}] [IA_LOG] {msg}\n")
        except Exception:
            pass

    _PG["log"] = mcp_trace

    so, se = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            exec(compile(code, "<mcp_sandbox>", "exec"), _PG)
    except PermissionError as e:
        _live_log("python_interpreter", f"PERM: {e}", "DENY")
        gc.collect()
        return f"Erreur:\n{e}"
    except Exception:
        err = traceback.format_exc()
        out = so.getvalue()
        _live_log("python_interpreter", f"CRASH: {err[:200]}", "FAIL")
        gc.collect()
        return "\n".join(([f"Sortie:\n{out}"] if out else []) + [f"Erreur:\n{err}"])
    finally:
        os.chdir(PROJECT_ROOT)

    out, err = so.getvalue(), se.getvalue()
    if out or err:
        with open(TRACE_LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"--- EXEC {datetime.now():%H:%M:%S} ---\n")
            if out:
                f.write(f"STDOUT: {out.strip()}\n")
            if err:
                f.write(f"STDERR: {err.strip()}\n")
            f.write("---\n")

    if len(out) > 8000:
        out = out[:8000] + f"\n...[tronque {len(out) - 8000}]"
    gc.collect()
    _live_log("python_interpreter", f"DONE {len(out)}c")
    res = []
    if out:
        res.append(out)
    if err:
        res.append(f"Stderr:\n{err[:2000]}")
    return "\n".join(res) if res else "[OK] pas de sortie (voir trace.log)"


# ════════════════════════════════════════════════════════════
# 2. FILE READ
# ════════════════════════════════════════════════════════════
@mcp.tool()
def file_read(
    path: str = "",
    mode: str = "full",
    head: Optional[int] = None,
    tail: Optional[int] = None,
    paths: Optional[list[str]] = None,
) -> str:
    """Lit des fichiers. Modes:
    - full: texte brut (defaut). head/tail pour limiter.
    - compressed: supprime commentaires et lignes vides (~40% tokens).
    - smart: garde la structure, compresse les fonctions longues (~60% tokens).
    - stub: signatures uniquement (~95% tokens).
    - multi: lit plusieurs fichiers (passer paths=[...]).
    """
    if mode == "multi" and paths:
        parts = []
        for ps in paths:
            try:
                parts.append(f"=== {ps} ===\n{_res(ps).read_text('utf-8', errors='replace')}")
            except Exception as e:
                parts.append(f"=== {ps} ===\nERROR: {e}")
        return "\n\n".join(parts)

    p = _res(path)
    # FULL
    if mode == "full":
        text = p.read_text("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        if head is not None:
            lines = lines[:head]
        elif tail is not None:
            lines = lines[-tail:]
        return "".join(lines)

    # COMPRESSED
    if mode == "compressed":
        key = _ck("compressed", path=path)
        cached = _cg(key)
        if cached:
            return cached
        raw = p.read_text("utf-8", errors="replace").splitlines()
        comp = [l for l in raw if l.strip() and not l.strip().startswith("#")]
        max_l = 200
        if len(comp) > max_l:
            try:
                tree = ast.parse(p.read_text("utf-8", errors="replace"))
                stubs = []
                for n in tree.body:
                    if isinstance(n, ast.ClassDef):
                        stubs.append(f"class {n.name}:")
                        for s in n.body:
                            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                stubs.append(f"    def {s.name}(...): ...")
                    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        stubs.append(f"def {n.name}(...): ...")
                stub = "\n".join(stubs)
            except Exception:
                stub = "(parse error)"
            result = f"PARTIEL ({len(comp)}L):\n" + "\n".join(comp[:20]) + f"\n\nSTRUCTURE:\n{stub}"
        else:
            result = "\n".join(comp)
        _cs(key, result)
        return result

    # SMART
    if mode == "smart":
        key = _ck("smart", path=path)
        cached = _cg(key)
        if cached:
            return cached
        source = p.read_text("utf-8", errors="replace")
        try:
            tree = ast.parse(source)

            class _C(ast.NodeTransformer):
                """c."""

                def _c(self, node) -> object:
                    """C.

                    Args:
                        node: Description.
                    """
                    if len(node.body) > 5:
                        first = node.body[0]
                        if (
                            isinstance(first, ast.Expr)
                            and isinstance(getattr(first, "value", None), ast.Constant)
                            and isinstance(first.value.value, str)
                        ):
                            node.body = [first, ast.Expr(value=ast.Constant(value="..."))]
                        else:
                            node.body = [ast.Expr(value=ast.Constant(value="..."))]
                    return node

                """Visit functiondef.

                Args:
                    n: Description.
                """

                def visit_FunctionDef(self, n) -> object:
                    """Visit functiondef."""
                    self.generic_visit(n)
                    return self._c(n)

                """Visit asyncfunctiondef.

                Args:
                    n: Description.
                """

                def visit_AsyncFunctionDef(self, n) -> object:
                    """Visit asyncfunctiondef."""
                    self.generic_visit(n)
                    return self._c(n)

            ast.fix_missing_locations(_C().visit(tree))
            result = ast.unparse(tree)
        except SyntaxError:
            lines = source.splitlines()
            result = "\n".join(l for l in lines if l.strip() and not l.strip().startswith("#"))
        _cs(key, result)
        return result

    # STUB
    if mode == "stub":
        key = _ck("stub", path=path)
        cached = _cg(key)
        if cached:
            return cached
        source = p.read_text("utf-8", errors="replace")
        tree = ast.parse(source)
        lines = []
        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in n.bases) if n.bases else ""
                lines.append(f"class {n.name}({bases}):" if bases else f"class {n.name}:")
                has = False
                for s in n.body:
                    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        pfx = "async " if isinstance(s, ast.AsyncFunctionDef) else ""
                        lines.append(f"    {pfx}def {s.name}({ast.unparse(s.args)}): ...")
                        has = True
                if not has:
                    lines.append("    ...")
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pfx = "async " if isinstance(n, ast.AsyncFunctionDef) else ""
                lines.append(f"{pfx}def {n.name}({ast.unparse(n.args)}): ...")
        result = "\n".join(lines) or "(vide)"
        _cs(key, result)
        return result

    return f"Mode inconnu: {mode}. Modes: full/compressed/smart/stub/multi"


# ══════════════════════════════════════════════════════════════
# 3. FILE WRITE (5 actions en 1)
# ══════════════════════════════════════════════════════════════
# ── Sentinelle : validation avant ecriture ──
_DANGER_PATTERNS = [
    (re.compile(r"\bos\.system\s*\(", re.I), "os.system() interdit"),
    (re.compile(r"\bsubprocess\.(?:call|run|Popen)\s*\(.*shell\s*=\s*True", re.I), "subprocess shell=True"),
    (re.compile(r"\beval\s*\(", re.I), "eval() interdit"),
    (re.compile(r"\bexec\s*\(", re.I), "exec() interdit (hors MCP interpreter)"),
    (re.compile(r'\b__import__\s*\(\s*[\'"](?:os|subprocess|shutil|ctypes)', re.I), "import dynamique dangereux"),
    (re.compile(r"\brm\s+-rf\s+/", re.I), "rm -rf / detecte"),
    (re.compile(r"\bformat\s*\(.*\bHARD\s*DISK", re.I), "formatage disque detecte"),
]


def _sentinel_check(code: str, filepath: str) -> tuple[bool, str]:
    """Valide du code Python AVANT ecriture. Retourne (ok, rapport)."""
    issues = []
    # 1. Validation syntaxe AST
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SYNTAX L{e.lineno}:{e.offset} {e.msg}"
    # 2. Patterns dangereux
    for pat, desc in _DANGER_PATTERNS:
        if pat.search(code):
            issues.append(desc)
    # 3. DangerGuard (si dispo)
    try:
        from nokido_agent.app.forge_code import get_guard

        guard = get_guard()
        if guard:
            check = guard.check(code)
            if check.level >= 3:  # CRITICAL
                issues.append(f"DangerGuard level={check.level}: {getattr(check, 'rule_name', '?')}")
    except Exception:
        pass
    if issues:
        return False, " | ".join(issues)
    return True, "OK"


def _sentinel_check(code: str, filepath: str) -> tuple[bool, str]:
    """Valide du code Python AVANT ecriture. Retourne (ok, rapport)."""
    issues = []
    # 1. Validation syntaxe AST
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SYNTAX L{e.lineno}:{e.offset} {e.msg}"
    # 2. Patterns dangereux
    for pat, desc in _DANGER_PATTERNS:
        if pat.search(code):
            issues.append(desc)
    # 3. DangerGuard (si dispo)
    try:
        from nokido_agent.app.forge_code import get_guard

        guard = get_guard()
        if guard:
            check = guard.check(code)
            if check.level >= 3:  # CRITICAL
                issues.append(f"DangerGuard level={check.level}: {getattr(check, 'rule_name', '?')}")
    except Exception:
        pass
    if issues:
        return False, " | ".join(issues)
    return True, "OK"


# ════════════════════════════════════════════════════════════
# 3. FILE WRITE
# ════════════════════════════════════════════════════════════
@mcp.tool()
def file_write(
    action: str,
    path: str,
    content: str = "",
    edits: Optional[list[dict]] = None,
    destination: str = "",
    dry_run: bool = False,
) -> str:
    """Ecrit/modifie des fichiers. Actions:
    - write: cree ou ecrase (content requis).
    - edit: applique des edits [{oldText,newText},...]. dry_run=true pour preview.
    - delete: supprime le fichier.
    - move: deplace/renomme (destination requis).
    - mkdir: cree un repertoire (et parents).
    Tous proteges par .mcpignore.
    """
    p = _res(path)
    _live_log("file_write", f"{action} {p.name} dry={dry_run}")
    if action == "write":
        _chkw(str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        # Sentinelle : valider les .py avant ecriture
        if p.suffix == ".py":
            ok, report = _sentinel_check(content, str(p))
            if not ok:
                _live_log("file_write", f"SENTINEL {p.name}: {report}", "DENY")
                return f"SENTINEL BLOQUE: {report}"
        p.write_text(content, "utf-8")
        _CACHE.clear()
        _live_log("file_write", f"WRITE OK {p.name} {len(content)}c")
        return f"OK: {p} ({len(content)} chars)"
    if action == "edit":
        if not dry_run:
            _chkw(str(p))
        orig = p.read_text("utf-8", errors="replace")
        mod = orig
        for e in edits or []:
            old, new = e.get("oldText", ""), e.get("newText", "")
            if old not in mod:
                return f"ERROR: oldText not found:\n{old[:200]}"
            mod = mod.replace(old, new, 1)
        diff = "".join(
            difflib.unified_diff(
                orig.splitlines(keepends=True), mod.splitlines(keepends=True), fromfile="original", tofile="modified"
            )
        )
        if not dry_run:
            # Sentinelle : valider le resultat final pour les .py
            if p.suffix == ".py":
                ok, report = _sentinel_check(mod, str(p))
                if not ok:
                    return f"SENTINEL BLOQUE: {report}\n\nDiff prevu:\n{diff[:500]}"
            p.write_text(mod, "utf-8")
            _CACHE.clear()
        if not dry_run:
            _live_log("file_write", f"EDIT OK {p.name} {len(diff)}c diff")
        return diff or "(no changes)"
    if action == "delete":
        _chkw(str(p))
        p.unlink(missing_ok=True)
        _CACHE.clear()
        _live_log("file_write", f"DELETE {p.name}")
        return f"OK: supprime {p}"
    if action == "move":
        d = _res(destination)
        _chkw(str(p))
        _chkw(str(d))
        shutil.move(str(p), str(d))
        _CACHE.clear()
        return f"OK: {p} -> {d}"
    if action == "mkdir":
        p.mkdir(parents=True, exist_ok=True)
        return f"OK: {p}"
    return f"Action inconnue: {action}. Actions: write/edit/delete/move/mkdir"


# ══════════════════════════════════════════════════════════════
# 4. FILE EXPLORE (4 actions en 1)
# ══════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# 4. FILE EXPLORE
# ════════════════════════════════════════════════════════════
@mcp.tool()
def file_explore(action: str, path: str, pattern: str = "*", max_depth: int = 3) -> str:
    """Explore le projet. Actions:
    - search: glob recursif (pattern requis). Ex: pattern='*.py'
    - list: contenu d'un repertoire.
    - tree: arborescence recursive (max_depth).
    - info: metadata d'un fichier (taille, date, type).
    Tous les resultats sont caches 10min.
    """
    key = _ck(f"explore_{action}", path=path, pattern=pattern, depth=max_depth)
    cached = _cg(key)
    if cached:
        return cached
    root = _res(path)

    if action == "search":
        matches = [str(p) for p in root.rglob(pattern) if "__pycache__" not in str(p) and ".git" not in str(p)]
        result = "\n".join(matches) if matches else "(no matches)"

    elif action == "list":
        entries = []
        for item in sorted(root.iterdir()):
            if item.name.startswith(".") and item.name != "RAG":
                continue
            k = "DIR " if item.is_dir() else "FILE"
            sz = f" ({item.stat().st_size:,}b)" if item.is_file() else ""
            entries.append(f"  {k}  {item.name}{sz}")
        result = f"{root}\n" + "\n".join(entries)

    elif action == "tree":
        lines = [str(root)]
        skip = {".git", "__pycache__", "node_modules", ".cache", ".venv", "venv"}

        def _w(d, pre, dep) -> None:
            """W.

            Args:
                d: Description.
                pre: Description.
                dep: Description.
            """
            if dep > max_depth:
                return
            try:
                items = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                return
            vis = [e for e in items if e.name not in skip and not (e.is_dir() and e.name.startswith("."))]
            for i, item in enumerate(vis):
                last = i == len(vis) - 1
                lines.append(f"{pre}{'  ' if last else '| '}{item.name}")
                if item.is_dir():
                    _w(item, pre + ("    " if last else "|   "), dep + 1)

        _w(root, "", 1)
        result = "\n".join(lines)

    elif action == "info":
        s = root.stat()
        result = _cj(
            {
                "path": str(root),
                "type": "dir" if root.is_dir() else "file",
                "size": s.st_size,
                "modified": datetime.fromtimestamp(s.st_mtime).isoformat(),
                "ext": root.suffix,
            }
        )
    else:
        return f"Action inconnue: {action}. Actions: search/list/tree/info"

    _cs(key, result)
    return result


# ══════════════════════════════════════════════════════════════
# 5. SQL (WAL)
# ══════════════════════════════════════════════════════════════
def _dbc(db_path=None) -> object:
    """Dbc.

    Args:
        db_path: Description.
    """
    p = Path(db_path) if db_path else DB_PATH
    c = sqlite3.connect(str(p))
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    return c


# ════════════════════════════════════════════════════════════
# 5. SQL
# ════════════════════════════════════════════════════════════
@mcp.tool()
def sql(action: str, query: str = "", db_path: Optional[str] = None) -> str:
    """Base SQLite WAL. Actions:
    - query: SELECT/PRAGMA (lecture seule, cache).
    - execute: INSERT/UPDATE/DELETE (invalide le cache).
    - status: version, WAL, vecteurs, integrite, cache.
    """

    # ── RAG QUERY AUDIT (non-bloquant) ──────────────────────────────────────
    try:
        import os as _os, threading as _th

        _agent = _os.environ.get("X_AGENT_NAME", "unknown")
        _sess = _os.environ.get("X_SESSION_ID", "")
        _res = (query or action)[:120]

        def _audit_log():
            import sqlite3 as _sq, datetime as _dt

            _db = _dbc(db_path)
            _db.execute(
                "INSERT INTO user_audit_log(ts,user_id,session_id,action,resource,ring_used,status,detail)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (_dt.datetime.now().isoformat(), _agent, _sess, f"rag.{action}", _res, 0, "ok", f"sql={bool(query)}"),
            )
            _db.commit()

        _th.Thread(target=_audit_log, daemon=True).start()
    except Exception:
        pass
    # ────────────────────────────────────────────────────────────────────────
    if action == "status":
        conn = _dbc(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            cnt = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            intg = conn.execute("PRAGMA integrity_check;").fetchone()[0]
            tbls = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            rc = 0
            if "rag_chunks" in tbls:
                rc = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            return _cj(
                {
                    "v": _VERSION,
                    "wal": mode,
                    "code_vecs": cnt,
                    "rag_chunks": rc,
                    "tables": tbls,
                    "integrity": intg,
                    "cache": len(_CACHE),
                }
            )
        except Exception as e:
            return f"ERROR: {e}"
        finally:
            conn.close()

    if action == "query":
        q = query.strip()
        if not q.upper().startswith(("SELECT", "PRAGMA")):
            return "ERROR: SELECT/PRAGMA only"
        key = _ck("sql_q", query=q, db=db_path)
        cached = _cg(key)
        if cached:
            return cached
        conn = _dbc(db_path)
        try:
            cur = conn.execute(q)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            trunc = len(rows) > 100
            if trunc:
                rows = rows[:100]
            result = _cj([dict(zip(cols, r)) for r in rows])
            if trunc:
                result += "\n(tronque 100)"
            _cs(key, result)
            return result
        except Exception as e:
            return f"ERROR: {e}"
        finally:
            conn.close()

    if action == "execute":
        s = query.strip()
        if s.upper().startswith(("DROP DATABASE", "DROP TABLE embeddings")):
            return "ERROR: operation destructive bloquee"
        conn = _dbc(db_path)
        try:
            conn.execute(s)
            conn.commit()
            _CACHE.clear()
            return f"OK: {conn.total_changes} row(s)"
        except Exception as e:
            return f"ERROR: {e}"
        finally:
            conn.close()

    return f"Action inconnue: {action}. Actions: query/execute/status"


# ══════════════════════════════════════════════════════════════
# 6. SEMANTIC SEARCH (NPU)
# ══════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# 6. SEMANTIC SEARCH
# ════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
@mcp.tool()
def semantic_search(query: str, top_k: int = 5) -> str:
    """Recherche semantique cosine sur le code indexe (NPU/DML/CPU)."""
    key = _ck("sem", query=query, k=top_k)
    cached = _cg(key)
    if cached:
        return cached
    try:
        import numpy as np
    except ImportError as e:
        return f"ERROR: {e}"
    if not DB_PATH.exists():
        return "ERROR: embeddings.db absent"
    npu = _get_npu()
    if not npu or not npu.available:
        return "ERROR: NPU non dispo"
    qv = np.array(npu.embed_one(query))
    qn = np.linalg.norm(qv)
    if qn < 1e-9:
        return "ERROR: zero vector"
    conn = _dbc()
    rows = conn.execute("SELECT file_path, embedding FROM embeddings").fetchall()
    conn.close()
    results = []
    for fp, ej in rows:
        emb = np.array(json.loads(ej))
        score = float(np.dot(qv, emb) / (qn * np.linalg.norm(emb) + 1e-9))
        results.append({"f": fp, "s": round(score, 4)})
    results.sort(key=lambda x: x["s"], reverse=True)
    result = _cj(results[:top_k])
    _cs(key, result)
    return result


# ══════════════════════════════════════════════════════════════
# 7. SYSTEM
# ══════════════════════════════════════════════════════════════
_ATLAS_PATH = PROJECT_ROOT / "project_atlas.json"


# ════════════════════════════════════════════════════════════
# 7. SYSTEM
# ════════════════════════════════════════════════════════════
@mcp.tool()
def system(action: str, path: str = "") -> str:
    """Utilitaires systeme. Actions:
    - cache_clear: vide le cache de resultats.
    - mcpignore: verifie si un chemin est protege (path requis).
    - atlas_build: genere le constat d'analyse du projet (arbre + stubs + hashes). ~3000 tokens.
    - atlas_get: consulte le constat deja genere (instantane). Pour la recherche semantique, utiliser semantic_search.
    """
    if action == "cache_clear":
        n = len(_CACHE)
        _CACHE.clear()
        return f"Cache vide ({n} entrees)"

    if action == "mcpignore":
        ok, pat = _is_prot(path)
        if ok:
            return f"PROTEGE '{path}' -- pattern: '{pat}'"
        return f"libre '{path}'"

    if action == "atlas_build":
        import hashlib as _h

        atlas = {
            "generated": datetime.now().isoformat(),
            "version": _VERSION,
            "structure": "",
            "files": {},
            "stubs": {},
            "stats": {},
        }
        # Arborescence
        skip = {".git", "__pycache__", "node_modules", ".cache", ".venv", "venv", "backups"}
        tree_lines = ["LaForge/"]

        def _walk(d, pre, dep) -> None:
            """Walk.

            Args:
                d: Description.
                pre: Description.
                dep: Description.
            """
            if dep > 2:
                return
            try:
                items = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                return
            vis = [e for e in items if e.name not in skip and not (e.is_dir() and e.name.startswith("."))]
            for i, item in enumerate(vis):
                last = i == len(vis) - 1
                tree_lines.append(f"{pre}{'  ' if last else '| '}{item.name}")
                if item.is_dir():
                    _walk(item, pre + ("    " if last else "|   "), dep + 1)

        _walk(PROJECT_ROOT, "", 1)
        atlas["structure"] = "\n".join(tree_lines)
        # Fichiers Python avec hash + taille
        py_files = list(APP_DIR.rglob("*.py"))
        py_files = [
            f for f in py_files if "backups" not in str(f) and "legacy" not in str(f) and "__pycache__" not in str(f)
        ]
        for pf in py_files:
            rel = str(pf.relative_to(PROJECT_ROOT))
            content_bytes = pf.read_bytes()
            atlas["files"][rel] = {
                "size": len(content_bytes),
                "hash": _h.md5(content_bytes).hexdigest()[:12],
                "lines": content_bytes.count(b"\n") + 1,
            }
        # Stubs ultra-compacts : noms de classes + fonctions publiques
        critical = [f for f in py_files if f.stem.startswith("forge_") or f.stem == "Nokido"]
        for pf in critical:
            rel = str(pf.relative_to(PROJECT_ROOT))
            try:
                tree = ast.parse(pf.read_text("utf-8", errors="replace"))
                classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
                funcs = [
                    n.name
                    for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
                ]
                atlas["stubs"][rel] = {"C": classes, "F": funcs}
            except Exception:
                atlas["stubs"][rel] = {"err": True}
        # Stats
        atlas["stats"] = {
            "py_files": len(py_files),
            "total_lines": sum(v["lines"] for v in atlas["files"].values()),
            "total_size_kb": sum(v["size"] for v in atlas["files"].values()) // 1024,
        }
        _ATLAS_PATH.write_text(_cj(atlas), "utf-8")
        return f"Atlas genere: {len(py_files)} fichiers, {atlas['stats']['total_lines']}L, {atlas['stats']['total_size_kb']}KB -> {_ATLAS_PATH.name}"

    if action == "atlas_get":
        if not _ATLAS_PATH.exists():
            return "Atlas inexistant. Lance system(action='atlas_build') d'abord."
        return _ATLAS_PATH.read_text("utf-8")

    if action == "save_situation":
        ts = _dt.now().strftime("%Y-%m-%d %H:%M")
        if not SITUATION_MD.exists():
            SITUATION_MD.write_text(f"# SITUATION {ts}\n\n", encoding="utf-8")
        return f"SITUATION.md pret ({ts}). Utilise file_write pour y ecrire."
    if action == "get_situation":
        if SITUATION_MD.exists():
            return SITUATION_MD.read_text("utf-8", errors="replace")
        return "Pas de SITUATION.md - premiere session."
    return (
        f"Action inconnue: {action}. Actions: cache_clear/mcpignore/atlas_build/atlas_get/save_situation/get_situation"
    )


# ══════════════════════════════════════════════════════════════
# PRE-CHARGEMENT NPU (singleton)
# ══════════════════════════════════════════════════════════════
_NPU_SINGLETON = None


def _get_npu() -> object:
    """Get npu."""
    global _NPU_SINGLETON
    if _NPU_SINGLETON is None:
        try:
            from nokido_agent.app.forge_npu_embedder import NPUEmbedder

            _NPU_SINGLETON = NPUEmbedder()
            if _NPU_SINGLETON.available:
                logger.info(f"NPU pre-loaded: {_NPU_SINGLETON.provider}")
        except Exception as e:
            logger.warning(f"NPU pre-load: {e}")
    return _NPU_SINGLETON


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _cleanup_old_instances()
    _setup_logs()
    logger.info(f"Nokido MCP v{_VERSION} (7 outils)")
    logger.info(f"DB: {DB_PATH} (WAL)")
    # NPU chargé en lazy (1er appel semantic_search) — démarrage instantané
    tools = list(mcp._tool_manager._tools.keys())
    logger.info(f"Outils: {', '.join(tools)}")
    _live_log("MCP_SERVER", f"Démarré v{_VERSION} — {len(tools)} outils")
    mcp.run(transport="stdio")
