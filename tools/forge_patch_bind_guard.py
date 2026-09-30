#!/usr/bin/env python
"""forge_patch_bind_guard.py -- branche le garde d'exposition dans le hub.

`tools/nokido_hub.py` est un CRITICAL_FILE : `governed_edit` le refuse, et
`allow_critical` a DEJA coupe le hub une fois (memoire 2026-08-27). Le chemin
documente est donc un patch COMMITE, execute en `trusted_script` -- le privilege
tient a la revue du code, pas a une derogation.

IDEMPOTENT : si le garde est deja branche, le script ne fait rien et le DIT.
Ecriture ATOMIQUE : un hub tronque ne redemarre pas.

Usage :
    run action=trusted_script path=tools/forge_patch_bind_guard.py                 # dry-run
    run action=trusted_script path=tools/forge_patch_bind_guard.py script_args=--appliquer
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/cablage-garde-exposition"

import argparse
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "tools" / "nokido_hub.py"

ANCRE = '    logger.info(f"  Network Monitor : http://{HUB_HOST}:{HUB_PORT}/forge/network")'

BLOC = '''    # GARDE D'EXPOSITION (2026-09-02). Le controle de HUB_HOST plus haut porte sur
    # l'INTENTION. Trois chemins exposent un port sans jamais y toucher : un
    # mapping de conteneur, un proxy place devant, un socket herite d'un parent.
    # On constate donc l'EFFET, en differe pour laisser uvicorn bind d'abord.
    # Il CRIE, il n'arrete pas : un garde qui tue le control-plane transforme une
    # exposition possible en indisponibilite certaine.
    def _controle_exposition():
        try:
            import time as _t

            _t.sleep(8)
            from forge_bind_guard import controler as _ctrl

            _ctrl(HUB_PORT, logger)
        except Exception as _e:  # noqa: BLE001  # muet-ok : jamais bloquant au boot
            logger.debug(f"[bind_guard] non execute: {_e}")

    threading.Thread(target=_controle_exposition, daemon=True).start()
'''

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  # muet-ok : confort console
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--appliquer", action="store_true")
    a = ap.parse_args(argv)

    src = CIBLE.read_text(encoding="utf-8", errors="replace")
    if "_controle_exposition" in src:
        print("DEJA BRANCHE : rien a faire.")
        return 0
    if ANCRE not in src:
        print("REFUS : ancre introuvable. Le hub a change ; ne pas patcher a l'aveugle.")
        print("   ancre attendue : %s" % ANCRE.strip()[:90])
        return 2
    if src.count(ANCRE) != 1:
        print("REFUS : ancre presente %d fois, insertion ambigue." % src.count(ANCRE))
        return 2

    nouveau = src.replace(ANCRE, ANCRE + "\n" + BLOC, 1)

    # Un patch qui casse la syntaxe rend le hub INDEMARRABLE : on verifie AVANT
    # d'ecrire, pas apres. Le preflight du script de demarrage ne verifie la
    # syntaxe qu'au prochain lancement -- trop tard.
    try:
        ast.parse(nouveau)
    except SyntaxError as e:
        print("REFUS : le patch casserait la syntaxe (ligne %s : %s)" % (e.lineno, e.msg))
        return 2

    print("ancre trouvee | %d -> %d octets (+%d)"
          % (len(src), len(nouveau), len(nouveau) - len(src)))
    if not a.appliquer:
        print("DRY-RUN : relancer avec --appliquer.")
        return 0

    tmp = CIBLE.with_suffix(".py.tmp")
    tmp.write_text(nouveau, encoding="utf-8", newline="")
    os.replace(tmp, CIBLE)            # atomique : pas de hub a moitie ecrit
    relu = CIBLE.read_text(encoding="utf-8", errors="replace")
    ok = "_controle_exposition" in relu
    try:
        ast.parse(relu)
        syntaxe = True
    except SyntaxError:
        syntaxe = False
    print("ECRIT. branche=%s syntaxe_ok=%s (%d octets)" % (ok, syntaxe, len(relu)))
    return 0 if (ok and syntaxe) else 1


if __name__ == "__main__":
    raise SystemExit(main())
