"""Patcher one-shot : retirer le token en dur de tools/forge_skill_indexer.py.

Detecte par le gate egress souverain (2026-07-22) : `git_secrets: generic_secret`
-> PUSH BLOQUE. Le fichier etait untracked depuis toujours ; c'est le commit
bc647f7a (versionnement des outils untracked) qui l'a fait entrer dans git.
Rien n'ayant ete pousse, il n'y a pas eu de divulgation externe.

Remplace le litteral `self.token = "<64 chars>"` par une resolution vault/env
(forge_secrets puis variables d'environnement), sans jamais afficher la valeur.
Idempotent, verifie l'AST, backup horodate.

Usage : run action=trusted_script path=tools/patch_skill_indexer_secret.py
"""

from __future__ import annotations

import ast
import datetime
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tools" / "forge_skill_indexer.py"

LITERAL = re.compile(r'self\.token\s*=\s*"[^"]{16,}"[^\n]*')

REPLACEMENT = (
    'self.token = _resolve_token()  # vault DPAPI puis env - jamais de litteral'
)

HELPER = '''

def _resolve_token() -> str:
    """Token du hub : coffre DPAPI d'abord, variables d'environnement ensuite.

    Un litteral en dur ici a ete bloque par le gate egress le 2026-07-22 ;
    ne jamais le reintroduire.
    """
    try:
        from forge_secrets import get_secret  # type: ignore

        val = get_secret("FORGE_MCP_TOKEN")
        if val:
            return str(val)
    except Exception:  # noqa: BLE001 - le coffre est optionnel hors hub
        pass
    import os as _os

    return _os.environ.get("FORGE_MCP_TOKEN") or _os.environ.get("LAFORGE_MCP_TOKEN") or ""
'''


def main() -> int:
    if not TARGET.exists():
        print("ERR cible absente: %s" % TARGET)
        return 2

    src = TARGET.read_text(encoding="utf-8")

    if "_resolve_token()" in src and not LITERAL.search(src):
        print("DEJA APPLIQUE - aucun litteral restant")
        return 0

    hits = LITERAL.findall(src)
    if len(hits) != 1:
        print("ERR litteral introuvable ou multiple (occurrences=%d) - abandon" % len(hits))
        return 3

    patched = LITERAL.sub(REPLACEMENT, src, count=1)

    # Insere l'aide juste apres le bloc d'imports de tete.
    lines = patched.split("\n")
    anchor = 0
    for idx, line in enumerate(lines[:40]):
        if line.startswith("import ") or line.startswith("from "):
            anchor = idx
    lines.insert(anchor + 1, HELPER)
    patched = "\n".join(lines)

    try:
        ast.parse(patched)
    except SyntaxError as exc:
        print("ERR AST invalide apres patch (L%s): %s - abandon" % (exc.lineno, exc.msg))
        return 4

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(TARGET, TARGET.with_suffix(".py.bak_%s" % stamp))
    TARGET.write_text(patched, encoding="utf-8")

    reste = len(LITERAL.findall(patched))
    print("OK litteral retire (litteraux restants: %d)" % reste)
    print("  ATTENTION: le commit bc647f7a contient encore la valeur ->")
    print("  reecriture d'historique requise AVANT tout push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
