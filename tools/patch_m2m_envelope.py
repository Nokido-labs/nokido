#!/usr/bin/env python
"""patch_m2m_envelope.py — patcheur one-shot CRITICAL_FILE (chemin owner-sanctionne via
`run action=trusted_script`). Injecte l'enveloppe M2M auto-surface dans
forge_mcp_registry.dispatch, juste avant le `return result` succes.

Garde-fous anti-brick (aucune ecriture si un seul echoue) :
  - idempotent : skip si deja patche (marqueur present),
  - ancre STRICTEMENT unique (count==1), sinon ABORT,
  - AST verifie sur le resultat AVANT d'ecrire le fichier cible,
  - backup .m2m.bak avant ecriture, re-compile apres.
"""
from __future__ import annotations

import os
import py_compile
import shutil
import sys
import tempfile

TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "app", "forge_mcp_registry.py")
MARKER = "ENVELOPPE M2M"

OLD = (
    "                            result = result[: int(_cap * 0.8)] + _ptr + result[-int(_cap * 0.15) :]\n"
    "                return result\n"
)
NEW = (
    "                            result = result[: int(_cap * 0.8)] + _ptr + result[-int(_cap * 0.15) :]\n"
    "                # -- ENVELOPPE M2M -- auto-surface postal, UNIVERSEL (ce dispatcher = toutes les\n"
    "                # surfaces MCP : HTTP CLI + desktop via bridge). Flag OFF par defaut + fail-open :\n"
    "                # ne casse JAMAIS un tool call. Anti-spoof (identite forte) : ring < 4 = token-\n"
    "                # prouve (resolve_identity planche tout header non authentifie a HEADER_FLOOR=4).\n"
    "                # On ne draine QUE l'agent resolu -> zero fuite cross-agent.\n"
    "                try:\n"
    "                    if (os.environ.get(\"LAFORGE_M2M_ENVELOPE\", \"0\") == \"1\"\n"
    "                            and isinstance(result, str) and int(ring) < 4\n"
    "                            and str(agent).upper() not in (\"HUB\", \"UNKNOWN\")):\n"
    "                        from forge_postal import envelope_for as _envf\n"
    "\n"
    "                        _env = _envf(agent)\n"
    "                        if _env:\n"
    "                            result = result + _env\n"
    "                except Exception:\n"
    "                    pass  # fail-open : l'enveloppe M2M ne casse jamais un tool call\n"
    "                return result\n"
)


def main() -> int:
    if not os.path.exists(TARGET):
        print("ABORT: cible introuvable:", TARGET)
        return 2
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()
    if MARKER in src:
        print("SKIP: deja patche (idempotent).")
        return 0
    n = src.count(OLD)
    if n != 1:
        print("ABORT: ancre non-unique (count=%d) -> AUCUNE ecriture." % n)
        return 3
    patched = src.replace(OLD, NEW, 1)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    try:
        tmp.write(patched)
        tmp.close()
        py_compile.compile(tmp.name, doraise=True)
    except Exception as e:  # noqa: BLE001
        print("ABORT: AST invalide apres patch ->", e)
        return 4
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
    shutil.copy2(TARGET, TARGET + ".m2m.bak")
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(patched)
    py_compile.compile(TARGET, doraise=True)
    print("OK: enveloppe M2M injectee dans dispatch. backup =", TARGET + ".m2m.bak")
    print("    Activation : LAFORGE_M2M_ENVELOPE=1 (env hub) + reboot hub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
