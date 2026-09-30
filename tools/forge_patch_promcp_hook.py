"""forge_patch_promcp_hook.py — greffe le profileur ProMCP sur ToolRegistry.dispatch.

Patch de MAINTENANCE sur un CRITICAL_FILE (app/forge_mcp_registry.py), autorise
explicitement par l'owner le 2026-07-24. `governed_edit` refuse ce fichier par
design ; ce script est le chemin prevu (compte privilegie, code revu et commite).

On touche le coeur du dispatch : si le fichier devient invalide, le hub meurt au
prochain chargement. D'ou, dans cet ordre :
  1. IDEMPOTENT  — ne fait rien si la greffe est deja la (relancable sans risque).
  2. SAUVEGARDE  — copie horodatee avant toute ecriture.
  3. AST         — le resultat est compile en memoire ; si ca ne compile pas,
                   ROLLBACK immediat depuis la sauvegarde et rc=2.

Le corps de `dispatch` n'est PAS touche : on ajoute un decorateur. La fonction a de
multiples points de sortie (rejets securite, alias, erreurs) et les instrumenter un
a un serait autant d'occasions de regresser.

Usage :
    run action=trusted_script path=tools/forge_patch_promcp_hook.py
    run action=trusted_script path=tools/forge_patch_promcp_hook.py script_args="--revert"
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "app" / "forge_mcp_registry.py"
MARK = "_profile_dispatch"

DECORATOR = '''def _profile_dispatch(fn):
    """Mesure le cout REEL d'un appel de tool au chokepoint (P2 item 2).

    Decorateur et non instrumentation du corps : `dispatch` a de multiples points
    de sortie et les envelopper un a un serait autant d'occasions de regresser.
    Le profilage ne doit jamais casser le dispatch : import paresseux, aucune
    exception propagee, resultat retourne tel quel meme si l'enregistrement echoue.
    """
    import functools
    import time as _t

    @functools.wraps(fn)
    async def _wrapper(self, name, args, agent, ring):
        _t0 = _t.perf_counter()
        _ok = True
        try:
            res = await fn(self, name, args, agent, ring)
            # Un dict porteur d'`error` est un echec METIER : le compter comme un
            # succes ferait mentir le taux d'erreur par tool.
            if isinstance(res, dict) and res.get("error"):
                _ok = False
            return res
        except Exception:
            _ok = False
            raise
        finally:
            try:
                from forge_promcp_profiler import record as _rec

                _rec(name, (_t.perf_counter() - _t0) * 1000.0, ok=_ok,
                     payload_bytes=len(str(args)) if args else 0)
            except Exception:  # noqa: BLE001
                pass

    return _wrapper


class ToolRegistry:'''


def _say(t: str = "") -> None:
    sys.stdout.buffer.write((t + "\n").encode("ascii", "replace"))
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()

    src = TARGET.read_text(encoding="utf-8", errors="strict")
    present = MARK in src

    if a.revert:
        if not present:
            _say("greffe absente — rien a retirer")
            return 0
        new = src.replace(DECORATOR, "class ToolRegistry:")
        new = new.replace("    @_profile_dispatch\n    async def dispatch(", "    async def dispatch(")
    else:
        if present:
            _say("greffe DEJA presente — idempotent, rien a faire")
            return 0
        if "class ToolRegistry:" not in src or "    async def dispatch(" not in src:
            _say("ERREUR: points d'ancrage introuvables — fichier modifie ? abandon")
            return 2
        new = src.replace("class ToolRegistry:", DECORATOR, 1)
        new = new.replace("    async def dispatch(",
                          "    @_profile_dispatch\n    async def dispatch(", 1)

    backup = TARGET.with_suffix(f".py.bak_{int(time.time())}")
    shutil.copy2(TARGET, backup)
    _say(f"sauvegarde : {backup.name}")

    TARGET.write_text(new, encoding="utf-8")
    try:
        compile(new, str(TARGET), "exec")
    except SyntaxError as e:
        shutil.copy2(backup, TARGET)
        _say(f"AST INVALIDE ({e}) -> ROLLBACK effectue, fichier restaure")
        return 2

    _say("AST valide. Greffe " + ("retiree" if a.revert else "posee") + " sur ToolRegistry.dispatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
