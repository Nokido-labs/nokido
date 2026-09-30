"""Patcher one-shot : serialiser le batch shell par RESSOURCE EXCLUSIVE.

Probleme mesure (2026-07-22) : `run action=shell commands=[...]` fait un fan-out
nu (`asyncio.gather`) sans aucune file ni verrou de ressource. Deux `git commit`
dans le meme batch -> `fatal: Unable to create .git/index.lock: File exists`.
L'index git est un verrou FICHIER exclusif : aucun WAL SQLite ne le couvre, et
meme SQLite n'autoriserait pas deux ecrivains simultanes (WAL = 1 writer + N
readers). La seule reponse correcte est donc la SERIALISATION par cle, pas la
parallelisation.

Ce patch groupe les commandes par cle de ressource exclusive (`git:<repo>`),
execute chaque groupe SEQUENTIELLEMENT, et laisse les groupes tourner en
parallele entre eux. Meme principe que forge_lane_admission, applique au batch.

Cible : app/forge_mcp_registry.py (CRITICAL_FILE -> governed_edit refuse).
Idempotent, verifie l'AST avant ecriture, ecrit un backup horodate.
S'arme au prochain redemarrage du hub.

Usage : run action=trusted_script path=tools/patch_shell_batch_serialize.py
"""

from __future__ import annotations

import ast
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "app" / "forge_mcp_registry.py"
MARKER = "RESSOURCE EXCLUSIVE"

ANCHOR = (
    "                tasks = [loop.run_in_executor(None, _run_one, cmd) for cmd in commands]\n"
    "                results = await _aio.gather(*tasks, return_exceptions=True)\n"
)

REPLACEMENT = '''                # RESSOURCE EXCLUSIVE : deux commandes qui ecrivent le meme index
                # git ne peuvent PAS tourner en parallele (.git/index.lock est un
                # verrou FICHIER exclusif, aucun WAL ne le couvre). On SERIALISE
                # par cle de ressource ; les groupes restent paralleles entre eux.
                import re as _re_x

                _RE_REPO = _re_x.compile(r'-C\\s+"?([^"\\s]+)"?')

                def _excl_key(cmd):
                    s = str(cmd).lstrip().lower()
                    if not s.startswith("git "):
                        return None
                    m = _RE_REPO.search(str(cmd))
                    return "git:" + (m.group(1) if m else "cwd")

                _groups = {}
                _order = []
                for _i, _c in enumerate(commands):
                    _k = _excl_key(_c) or ("__par%d" % _i)
                    if _k not in _groups:
                        _groups[_k] = []
                        _order.append(_k)
                    _groups[_k].append((_i, _c))

                def _run_group(items):
                    outs = []
                    for _idx, _cmd in items:
                        try:
                            outs.append((_idx, _run_one(_cmd)))
                        except Exception as _e:  # noqa: BLE001 - remonte par item
                            outs.append((_idx, _e))
                    return outs

                tasks = [loop.run_in_executor(None, _run_group, _groups[k]) for k in _order]
                _gres = await _aio.gather(*tasks, return_exceptions=True)
                results = [None] * len(commands)
                for _k, _gr in zip(_order, _gres):
                    if isinstance(_gr, Exception):
                        for _idx, _c in _groups[_k]:
                            results[_idx] = _gr
                    else:
                        for _idx, _r in _gr:
                            results[_idx] = _r
'''


def main() -> int:
    if not TARGET.exists():
        print("ERR cible absente: %s" % TARGET)
        return 2

    src = TARGET.read_text(encoding="utf-8")

    if MARKER in src:
        print("DEJA APPLIQUE (marqueur present) - aucune modification")
        return 0

    if src.count(ANCHOR) != 1:
        print("ERR ancre introuvable ou ambigue (occurrences=%d) - abandon" % src.count(ANCHOR))
        return 3

    patched = src.replace(ANCHOR, REPLACEMENT)

    try:
        ast.parse(patched)
    except SyntaxError as exc:
        print("ERR AST invalide apres patch (L%s): %s - abandon" % (exc.lineno, exc.msg))
        return 4

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_suffix(".py.bak_%s" % stamp)
    shutil.copy2(TARGET, backup)
    TARGET.write_text(patched, encoding="utf-8")

    print("OK patch applique")
    print("  cible   : %s" % TARGET)
    print("  backup  : %s" % backup)
    print("  delta   : +%d lignes" % (len(patched.splitlines()) - len(src.splitlines())))
    print("  ARMEMENT: au prochain redemarrage du hub (owner)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
