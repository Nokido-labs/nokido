"""forge_patch_wasm_routing.py — one-shot : un TYPE de sandbox explicite prime.

Bug mesure 2026-07-28 : quand SANDBOX_EXEC est actif, _sandbox_decision rend
_sbx=True, et handle_run route TOUT vers _run_sandboxed_shell (cmd.exe /c ...),
IGNORANT sandbox=wasm/docker/ps_clm/windows/console. Un .wasm passe alors a
cmd.exe -> « Acces refuse » (un module wasm n'est pas un executable). Le
_exec_sandboxed qui gere ces types n'etait atteint que si _sbx=False.

Fix : si un TYPE de sandbox explicite (non-local) est demande, router vers
_exec_sandboxed MEME quand _sbx=True. CRITICAL_FILE -> voie trusted_script.
Idempotent, AST-valide avant ecriture.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "app" / "forge_mcp_registry.py"

OLD1 = (
    "                def _run_one(cmd):\n"
    "                    if _sbx:\n"
    "                        return self._run_sandboxed_shell(cmd, _online, timeout)\n"
    "                    return self._exec_sandboxed(cmd, sandbox, container, timeout, agent, ring)"
)
NEW1 = (
    "                def _run_one(cmd):\n"
    "                    # Un TYPE de sandbox explicite (wasm/docker/ps_clm/windows/\n"
    "                    # console) PRIME sur le sandboxing par defaut : sinon\n"
    "                    # _run_sandboxed_shell passe le module a cmd.exe -> « Acces\n"
    "                    # refuse » (un .wasm n'est pas un exe). Mesure 2026-07-28.\n"
    "                    if sandbox and sandbox not in (\"local\", \"\"):\n"
    "                        return self._exec_sandboxed(cmd, sandbox, container, timeout, agent, ring)\n"
    "                    if _sbx:\n"
    "                        return self._run_sandboxed_shell(cmd, _online, timeout)\n"
    "                    return self._exec_sandboxed(cmd, sandbox, container, timeout, agent, ring)"
)

OLD2 = (
    "                _sbx, _online, _ = self._sandbox_decision(args, agent)\n"
    "                if _sbx:\n"
    "                    # OFFLOAD : idem action=python -> ne pas bloquer l'event-loop hub.\n"
    "                    import asyncio as _aio_sh"
)
NEW2 = (
    "                _sbx, _online, _ = self._sandbox_decision(args, agent)\n"
    "                if not (sandbox and sandbox not in (\"local\", \"\")) and _sbx:\n"
    "                    # OFFLOAD : idem action=python -> ne pas bloquer l'event-loop hub.\n"
    "                    # (sandbox explicite non-local -> _exec_sandboxed ci-dessous.)\n"
    "                    import asyncio as _aio_sh"
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "PRIME sur le sandboxing par defaut" in src:
        print("DEJA PATCHE — rien a faire")
        return 0
    changed = 0
    for old, new in ((OLD1, NEW1), (OLD2, NEW2)):
        if old not in src:
            print("ANCRE INTROUVABLE (bloc %d) — abstention" % changed)
            return 2
        src = src.replace(old, new, 1)
        changed += 1
    ast.parse(src)  # jamais ecrire du python casse dans un CRITICAL_FILE
    TARGET.write_text(src, encoding="utf-8")
    print("PATCH APPLIQUE (%d blocs) + AST_OK" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
