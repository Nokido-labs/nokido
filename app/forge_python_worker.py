"""
forge_python_worker.py — Worker subprocess pour PythonRunner
============================================================
Process long-lived qui execute du code Python via JSON-RPC sur stdin/stdout.

Protocole :
  Au demarrage, ecrit sur stdout :
    {"ready": true}\n

  Pour chaque requete sur stdin (1 JSON par ligne) :
    {"id": "...", "code": "..."}

  Repond sur stdout (1 JSON par ligne) :
    {"id": "...", "ok": true|false, "stdout": "...", "stderr": "...", "elapsed_ms": float}

Le worker est manage par forge_python_runner.PythonRunner. A ne pas lancer
directement.

Note importante : chaque exec() utilise un dict globals() frais pour eviter
la pollution entre calls. Mais sys.modules est partage = imports caches
sont reutilises (gain principal sur les calls suivants).
"""

from __future__ import annotations

import io
import json
import sys
import time
import traceback

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def _ready_signal() -> None:
    """Signale au pool manager que le worker est pret."""
    sys.__stdout__.write('{"ready":true}\n')
    sys.__stdout__.flush()


def _exec_one(code: str, timeout: int = 30) -> tuple[str, str, bool]:
    """
    Execute le code dans un namespace frais, capture stdout/stderr.
    Retourne (stdout, stderr, ok).
    """
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    old_out = sys.stdout
    old_err = sys.stderr
    sys.stdout = buf_out
    sys.stderr = buf_err

    namespace: dict = {"__name__": "__user__", "__builtins__": __builtins__}
    err_text = ""
    ok = True
    try:
        from nokido_agent.app.forge_mcp_safe import safe_exec as _safe

        result = _safe(code, timeout=timeout)
        buf_out.write(result if isinstance(result, str) else "")
    except SystemExit as e:
        # Empeche le worker de mourir si user code fait sys.exit()
        err_text = f"SystemExit interceptee (code utilisateur): {e}\n"
        ok = False
    except BaseException:
        err_text = traceback.format_exc()
        ok = False
    finally:
        sys.stdout = old_out
        sys.stderr = old_err

    return buf_out.getvalue(), buf_err.getvalue() + err_text, ok


def main() -> None:
    """Boucle principale : lit stdin, execute, ecrit reponse sur stdout."""
    _ready_signal()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.__stdout__.write(
                json.dumps(
                    {
                        "id": None,
                        "ok": False,
                        "stdout": "",
                        "stderr": f"Bad JSON: {e}",
                        "elapsed_ms": 0.0,
                    }
                )
                + "\n"
            )
            sys.__stdout__.flush()
            continue

        req_id = req.get("id", "?")
        code = req.get("code", "")
        if not isinstance(code, str):
            sys.__stdout__.write(
                json.dumps(
                    {
                        "id": req_id,
                        "ok": False,
                        "stdout": "",
                        "stderr": "code must be string",
                        "elapsed_ms": 0.0,
                    }
                )
                + "\n"
            )
            sys.__stdout__.flush()
            continue

        t0 = time.perf_counter()
        out, err, ok = _exec_one(code, timeout=req.get("timeout", 30))
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)

        # Truncate outputs si trop gros (eviter de saturer le pipe)
        MAX = 64 * 1024
        if len(out) > MAX:
            out = out[:MAX] + f"\n... [stdout tronque a {MAX} chars] ...\n"
        if len(err) > MAX:
            err = err[:MAX] + f"\n... [stderr tronque a {MAX} chars] ...\n"

        sys.__stdout__.write(
            json.dumps(
                {
                    "id": req_id,
                    "ok": ok,
                    "stdout": out,
                    "stderr": err,
                    "elapsed_ms": elapsed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.__stdout__.flush()


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
