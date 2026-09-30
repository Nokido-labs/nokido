#!/usr/bin/env python3
"""Patch : deplacer `# muet-ok` du `pass` vers la ligne du HANDLER.

`forge_git_gate._recidive_warn` cherche la marque sur la ligne du handler (voir
son propre idiome, `except Exception:  # noqa: BLE001 — muet-ok : ...`). Les
patchs precedents l'avaient posee sur le `pass` : le silence etait motive dans le
code mais le detecteur continuait a crier. Un garde qui crie a faux se fait
desarmer -- donc on aligne la marque sur ce que le garde LIT, pas sur ce qui nous
semblait lisible.

IDEMPOTENT. Ne touche qu'aux couples (`except ...:` / `pass  # muet-ok : ...`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_sandbox_exec.py"
PASS_MARQUE = re.compile(r"^(\s*)pass\s+#\s*muet-ok\s*:\s*(.+?)\s*$")


def main() -> int:
    if not CIBLE.is_file():
        print("ABSENT : %s" % CIBLE)
        return 2
    lignes = CIBLE.read_text(encoding="utf-8").splitlines(keepends=True)
    deplaces = 0

    for i, brute in enumerate(lignes):
        m = PASS_MARQUE.match(brute.rstrip("\r\n"))
        if not m or i == 0:
            continue
        indent, motif = m.group(1), m.group(2)
        handler = lignes[i - 1].rstrip("\r\n")
        if not handler.lstrip().startswith("except"):
            continue
        if "muet-ok" in handler:
            continue
        lignes[i - 1] = "%s — muet-ok : %s\n" % (handler, motif) if "#" in handler \
            else "%s  # muet-ok : %s\n" % (handler, motif)
        lignes[i] = "%spass\n" % indent
        deplaces += 1

    if not deplaces:
        print("RIEN A DEPLACER (deja aligne sur le handler).")
        return 0

    neuf = "".join(lignes)
    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("STOP : le resultat ne compile pas (%s ligne %s) — rien ecrit." % (e.msg, e.lineno))
        return 4
    CIBLE.write_text(neuf, encoding="utf-8")
    print("MARQUE DEPLACEE sur %d handler(s)." % deplaces)
    return 0


if __name__ == "__main__":
    sys.exit(main())
