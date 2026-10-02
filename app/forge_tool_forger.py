"""
forge_tool_forger.py — Phase I: Forge dynamique d outils manquants
Quand un outil MCP echoue ou n existe pas, genere le code via LLM local,
valide syntaxe AST, enregistre dans forge_tools_dynamic/.
#FORGE:[score:85|agent:claude-sonnet-4-6|temp:0.00|color:GREEN|attempt:1]
"""
from __future__ import annotations

__FORGE_COLOR__ = "GREEN"
FORGE_ORGAN = "cortex_prefrontal"

import ast
import asyncio
import hashlib
import importlib
import importlib.util  # sous-module : sans cet import explicite, importlib.util peut etre absent en process frais -> _load_tool cassait silencieusement
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("Nokido.ToolForger")

DYNAMIC_DIR = ROOT / "app" / "forge_tools_dynamic"
DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)

# Init package
_init = DYNAMIC_DIR / "__init__.py"
if not _init.exists():
    _init.write_text("# forge_tools_dynamic — outils generes dynamiquement\n")


# ─────────────────────────────────────────────────────────────────────────────
# LLM code generator (local only)
# ─────────────────────────────────────────────────────────────────────────────

_FORGE_SYSTEM = """You are an expert Python developer writing Nokido tool functions.
Rules:
- Write ONLY the Python function, no imports unless strictly necessary
- Function must be standalone, no external state
- Add brief docstring (1 line)
- Handle exceptions gracefully, return None on error
- No print statements — use return values only
Output: valid Python code only, no markdown fences."""


async def _llm_forge(description: str, signature: str, timeout: float = 30.0) -> str:
    prompt = (
        f"Write a Python function with this signature:\n{signature}\n\nDescription: {description}\n\nPython function:"
    )
    try:
        # `ollama_generate` n'a jamais existe (2026-10-01) : l'API est ollama_call.
        from nokido_agent.app.forge_ollama import ollama_call

        return await asyncio.wait_for(
            ollama_call("qwen2.5-coder:7b-instruct-q4_K_M",
                        [{"role": "user", "content": prompt + "\n" + _FORGE_SYSTEM}], max_tokens=400),
            timeout=timeout,
        )
    except Exception as e:
        logger.debug(f"ollama forge failed: {e}")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# AST validation + extraction
# ─────────────────────────────────────────────────────────────────────────────


def _extract_function(raw: str, func_name: str) -> str:
    """Extrait le corps de la fonction depuis la reponse LLM (nettoie markdown)."""
    # Strip markdown fences
    raw = raw.strip()
    if "```" in raw:
        blocks = raw.split("```")
        for b in blocks:
            if "def " in b:
                raw = b.strip()
                if raw.startswith("python"):
                    raw = raw[6:].strip()
                break

    # Si la reponse ne contient pas de def, ajouter signature
    if "def " not in raw:
        return ""
    return raw


def _validate_ast(code: str) -> tuple[bool, str]:
    """Valide syntaxe Python via AST."""
    try:
        tree = ast.parse(code)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if not funcs:
            return False, "no function definition found"
        return True, funcs[0]
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"


# Denylist AST (defense en profondeur). sanitize_python_code ne couvre QUE l'acces
# secrets ; ici on borne ce qu'un outil forge PEUT faire : exec de code, ops
# destructives FS, reseau brut. Pas un sandbox airtight (l'aliasing peut contourner)
# mais releve nettement le cout d'un outil forge malveillant.
_FORGE_DENY_CALLS = {
    "eval", "exec", "compile", "__import__",
    "system", "popen", "execv", "execve", "execvp", "execvpe", "spawnv", "spawnl",
    "remove", "unlink", "rmdir", "removedirs", "rmtree",
}
_FORGE_DENY_IMPORTS = {
    "subprocess", "socket", "ctypes", "marshal", "pty", "multiprocessing",
    "ftplib", "smtplib", "telnetlib",
}


def _validate_safe(code: str) -> Optional[str]:
    """None si OK ; message si un pattern dangereux est present (denylist AST)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax: {e}"
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad = [a.name.split(".")[0] for a in n.names if a.name.split(".")[0] in _FORGE_DENY_IMPORTS]
            if bad:
                return f"import interdit: {bad}"
        elif isinstance(n, ast.ImportFrom):
            m = (n.module or "").split(".")[0]
            if m in _FORGE_DENY_IMPORTS:
                return f"import interdit: {m}"
        elif isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nm in _FORGE_DENY_CALLS:
                return f"appel interdit: {nm}()"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrement + chargement dynamique
# ─────────────────────────────────────────────────────────────────────────────


def _tool_path(name: str) -> Path:
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
    return DYNAMIC_DIR / f"tool_{safe}.py"


def _save_tool(name: str, code: str, description: str, signature: str) -> Path:
    path = _tool_path(name)
    header = (
        f'"""forge_tool_dynamic: {name}\n'
        f"Description: {description}\n"
        f"Signature: {signature}\n"
        f'Generated: auto via forge_tool_forger\n"""\n'
        f"from __future__ import annotations\n\n"
    )
    # Ecriture PROPRIOCEPTIVE : valide-en-RAM + atomique (tmp->os.replace). refresh=False
    # car les outils forges vivent dans DYNAMIC_DIR (hors census app/tools).
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from nokido_agent.tools.forge_module_cards import proprioceptive_write

    res = proprioceptive_write(str(path), header + code + "\n", refresh=False)
    if not res.get("ok"):
        raise ValueError(f"forge write rejected: {res.get('error')}")
    logger.info(f"Tool saved (atomic): {path}")
    return path


def _load_tool(name: str) -> Optional[object]:
    """Charge dynamiquement un outil forge."""
    path = _tool_path(name)
    if not path.exists():
        return None
    try:
        import re

        safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
        spec = importlib.util.spec_from_file_location(f"forge_tools_dynamic.tool_{safe}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        logger.debug(f"load_tool {name}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

import json

_REGISTRY_PATH = DYNAMIC_DIR / "registry.json"


def _registry_load() -> dict:
    if _REGISTRY_PATH.exists():
        try:
            return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _registry_save(registry: dict) -> None:
    _REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def _registry_add(name: str, description: str, signature: str, path: str) -> None:
    r = _registry_load()
    r[name] = {
        "description": description,
        "signature": signature,
        "path": path,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hash": hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8],
    }
    _registry_save(r)


# ─────────────────────────────────────────────────────────────────────────────
# MCP entry points
# ─────────────────────────────────────────────────────────────────────────────


def forge_forge_tool(name: str, description: str, signature: str) -> dict:
    """
    MCP-callable. Genere + sauvegarde + enregistre un outil manquant.
    name: nom de la fonction (ex: 'parse_elf_headers')
    description: ce que fait la fonction
    signature: def parse_elf_headers(path: str) -> dict:
    """
    t0 = time.monotonic()

    # Evite regeneration si deja forge
    existing = _registry_load().get(name)
    if existing:
        return {"status": "exists", "name": name, "path": existing["path"], "elapsed_s": 0.0}

    # Generation LLM
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    raw = loop.run_until_complete(_llm_forge(description, signature, timeout=30.0))

    if not raw:
        return {
            "status": "error",
            "name": name,
            "error": "LLM generation failed",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

    code = _extract_function(raw, name)
    if not code:
        return {
            "status": "error",
            "name": name,
            "error": "no function body extracted",
            "raw": raw[:200],
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

    ok, info = _validate_ast(code)
    _repaired = False
    if not ok:
        # Boucle build-repair (idées Ironsmith) : au lieu d'échouer one-shot, on tente
        # déterministe + réécriture. Modèle local 7b = capability FAIBLE -> deterministic + 1
        # rewrite (pas de diff fin). Le générateur faible redevient utile.
        try:
            from nokido_agent.app.forge_build_repair import build_repair

            def _repair_infer(prompt: str) -> str:
                try:
                    from nokido_agent.app.forge_ollama import ollama_call

                    raw2 = loop.run_until_complete(asyncio.wait_for(
                        ollama_call("qwen2.5-coder:7b-instruct-q4_K_M",
                                    [{"role": "user", "content": prompt}], max_tokens=400),
                        timeout=30.0))
                    return _extract_function(raw2, name) or (raw2 or "")
                except Exception:
                    return ""

            rr = build_repair(code, _repair_infer, capability="weak")
            if rr.get("ok"):
                code, _repaired = rr["code"], True
                ok, info = _validate_ast(code)
        except Exception as _bre:  # noqa: BLE001
            logger.debug(f"build_repair indispo: {_bre}")
    if not ok:
        return {
            "status": "error",
            "name": name,
            "error": info,
            "raw": raw[:200],
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

    # Defense en profondeur : refuse de forger un outil au code dangereux
    # (exec/destructif/reseau brut) en plus du SecretGuard a l'exec.
    _danger = _validate_safe(code)
    if _danger:
        return {
            "status": "rejected_unsafe",
            "name": name,
            "error": f"denylist: {_danger}",
            "raw": raw[:200],
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

    path = _save_tool(name, code, description, signature)
    _registry_add(name, description, signature, str(path))

    # Capacite changee : invalide le cache GOAP -> les goals recurrents re-planifient
    # avec le nouvel outil (sinon invisible jusqu'au TTL du cache de plans).
    try:
        from nokido_agent.app.forge_goap import invalidate_plan_cache

        invalidate_plan_cache()
    except Exception:
        pass

    # Signal capability-changed sur le bus (observable : SSE /api/swarm/stream).
    # NB : ce n'est PAS notifications/tools/list_changed MCP (le bridge ne push pas
    # dynamiquement + les outils forges ne sont pas des outils MCP) — c'est le canal
    # Nokido-natif de changement de capacite.
    try:
        from nokido_agent.app.forge_swarm_bus import publish as _bus_publish

        _bus_publish("capability.forged",
                     {"name": name, "signature": signature, "description": description},
                     topic="capabilities")
    except Exception:
        pass

    # Anchor dans RAG
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem=f"outil manquant: {name}",
            solution=f"forge_tool_forger genere {path.name}: {description}",
            example=signature,
            domain="systeme",
        )
    except Exception:
        pass

    return {
        "status": "forged",
        "name": name,
        "path": str(path),
        "func_name": info,
        "code_lines": len(code.splitlines()),
        "repaired": _repaired,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def _call_sandboxed(name: str, kwargs: dict):
    """Exécute l'outil forgé dans un sous-process SANDBOX (isolation forte, idée Ironsmith).
    None -> l'appelant retombe in-process (kwargs non-JSON, sandbox KO, etc. -> jamais bloquer)."""
    import json as _json
    import tempfile
    import uuid

    try:
        _kj = _json.dumps(kwargs)
    except Exception:
        return None
    try:
        from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON
        from nokido_agent.app.forge_sandbox_exec import spawn_as_sandbox
    except Exception:
        return None
    tp = _tool_path(name)
    if not tp.exists():
        return None
    runner = Path(__file__).resolve().parent.parent / "tools" / "forge_dynamic_tool_runner.py"
    base = Path(tempfile.gettempdir())
    kp = base / f"forgekw_{uuid.uuid4().hex[:8]}.json"
    op = base / f"forgeout_{uuid.uuid4().hex[:8]}.json"
    try:
        kp.write_text(_kj, encoding="utf-8")
        spawn_as_sandbox([str(LAFORGE_PYTHON), str(runner), str(tp), name, str(kp), str(op)],
                         online=False, timeout=30)
        if op.exists():
            r = _json.loads(op.read_text(encoding="utf-8") or "{}")
            r["tool"] = name
            r["sandboxed"] = True
            return r
    except Exception:
        return None
    finally:
        for _f in (kp, op):
            try:
                _f.unlink()
            except Exception:
                pass
    return None


def forge_call_dynamic(name: str, *, sandboxed: bool = True, **kwargs) -> dict:
    """MCP-callable. Appelle un outil forge dynamiquement.

    SECURITE (en couches) : ring 2 (QUI appelle) + denylist AST (exec/destructif/
    reseau brut) + SecretGuard (fuite de secrets). PAS un sandbox airtight (l'aliasing
    peut contourner la denylist) — le ring reste le confinement principal. Tourne AVANT
    _load_tool (importer le module execute son code top-level).
    """
    try:
        _p = _tool_path(name)
        if _p.exists():
            _src = _p.read_text(encoding="utf-8", errors="replace")
            _danger = _validate_safe(_src)
            if _danger:
                return {"error": f"denylist: {_danger}", "tool": name}
            from nokido_agent.app.forge_secret_guard import sanitize_python_code

            _viol = sanitize_python_code(_src, "FORGE_DYNAMIC", 2)
            if _viol:
                return {"error": f"SecretGuard: {_viol}", "tool": name}
    except ImportError:
        pass

    # SANDBOX-FORCED-DEFAULT (idée Ironsmith) : un outil GÉNÉRÉ s'exécute ISOLÉ par défaut.
    # Opt-out explicite (sandboxed=False). Fallback in-process si sandbox indispo -> jamais bloquer.
    if sandboxed:
        try:
            from nokido_agent.app.forge_sandbox_exec import sandbox_ready

            if sandbox_ready():
                _r = _call_sandboxed(name, kwargs)
                if _r is not None:
                    return _r
        except Exception as _se:  # noqa: BLE001
            logger.debug(f"sandbox forgé indispo, fallback in-process: {_se}")

    mod = _load_tool(name)
    if not mod:
        return {"error": f"tool '{name}' not found — use forge_forge_tool first"}
    registry = _registry_load()
    entry = registry.get(name, {})
    # Cherche la fonction dans le module
    import re

    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())
    func = getattr(mod, name, None) or getattr(mod, safe, None)
    if not func:
        # Essaie la premiere fonction du module
        funcs = [v for k, v in vars(mod).items() if callable(v) and not k.startswith("_")]
        if funcs:
            func = funcs[0]
    if not func:
        return {"error": f"no callable found in tool '{name}'"}
    try:
        result = func(**kwargs)
        return {"result": result, "tool": name}
    except Exception as e:
        return {"error": str(e), "tool": name}


def forge_list_dynamic_tools() -> dict:
    """MCP-callable. Liste tous les outils dynamiques enregistres."""
    registry = _registry_load()
    return {
        "count": len(registry),
        "tools": [
            {"name": n, "description": v["description"][:80], "signature": v.get("signature", ""),
             "created": v["created"]}
            for n, v in registry.items()
        ],
    }


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        # E2E bridge : place un outil benin -> SecretGuard+exec -> dispatch GOAP -> cleanup.
        import asyncio

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app import forge_trajectory
        from nokido_agent.app import forge_dispatchers  # noqa: F401 (side-effect : enregistre forge_call_dynamic)

        _code = "def hello_dyn(x: int = 1) -> dict:\n    return {'doubled': x * 2}\n"
        _path = _save_tool("hello_dyn", _code, "double la valeur x", "def hello_dyn(x: int) -> dict")
        _registry_add("hello_dyn", "double la valeur x", "def hello_dyn(x: int) -> dict", str(_path))
        try:
            print(f"diag: path_exists={_path.exists()} loaded={_load_tool('hello_dyn') is not None}")
            direct = forge_call_dynamic("hello_dyn", x=21)
            assert direct.get("result", {}).get("doubled") == 42, f"direct: {direct}"
            lst = forge_list_dynamic_tools()
            assert any(t["name"] == "hello_dyn" and t["signature"] for t in lst["tools"]), f"list: {lst}"
            disp = asyncio.run(forge_trajectory.dispatch_intent({
                "jsonrpc": "2.0", "method": "forge_call_dynamic",
                "params": {"name": "hello_dyn", "kwargs": {"x": 5}}, "id": "t1"}))
            assert disp.get("result", {}).get("result", {}).get("doubled") == 10, f"dispatch: {disp}"
            print("SELFTEST OK | direct=42 dispatch=10 | SecretGuard+exec+route verifies")
        finally:
            try:
                _path.unlink()
            except Exception:
                pass
            _r = _registry_load()
            _r.pop("hello_dyn", None)
            _registry_save(_r)
        sys.exit(0)

    # Smoke test — validation AST uniquement (pas de LLM)
    from nokido_agent.app.forge_self_refinement import thought_interceptor

    sample_code = '''
def add_numbers(a: int, b: int) -> int:
    """Return sum of a and b."""
    try:
        return a + b
    except Exception:
        return 0
'''
    ok, name = _validate_ast(sample_code.strip())
    print(f"AST validate: ok={ok} name={name}")
    assert ok
    assert name == "add_numbers"

    # Test registry
    r = _registry_load()
    print(f"Registry: {len(r)} tools")

    # Test list
    lst = forge_list_dynamic_tools()
    print(f"List: {lst}")

    print("forge_tool_forger smoke test PASS")
