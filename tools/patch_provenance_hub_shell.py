#!/usr/bin/env python3
"""Patch : propager l'identite authentifiee jusqu'au shell sandboxe.

`app/forge_mcp_registry.py` est un CRITICAL_FILE : `governed_edit` le refuse, et
`allow_critical` sur un fichier de cette taille a deja coupe le hub (memoire
2026-08-27). Chemin prevu par la doctrine : un patch git-tracke, execute en
`trusted_script`.

IDEMPOTENT : si la marque est deja presente, ne touche a rien et sort 0. Chaque
motif recherche doit apparaitre EXACTEMENT une fois, sinon on s'arrete sans rien
ecrire -- un patch qui frappe a cote sur un fichier critique est pire que pas de
patch.
"""

from __future__ import annotations

import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"
MARQUE = "LAFORGE_AGENT_CHANNEL"

REMPLACEMENTS: list[tuple[str, str]] = [
    (
        '    def _run_sandboxed_shell(self, cmd: str, online: bool, timeout: int) -> dict:\n'
        '        import sys as _s\n'
        '\n'
        '        _s.path.insert(0, str(self.root / "app"))\n'
        '        from forge_sandbox_exec import spawn_as_sandbox\n'
        '\n'
        '        return spawn_as_sandbox(f"cmd.exe /c {cmd}", online=online, timeout=max(5, int(timeout)))\n',

        '    def _run_sandboxed_shell(self, cmd: str, online: bool, timeout: int,\n'
        '                             agent: str | None = None) -> dict:\n'
        '        """Shell sandboxe. `agent` = identite AUTHENTIFIEE par le hub, propagee a\n'
        "        l'enfant : sans elle un `git commit` lance ici ne peut se reclamer que du\n"
        '        compte sandbox, et la note de provenance sort `GIT:<user>|UNKNOWN`.\n'
        '\n'
        "        Le canal est fixe a HUB_SHELL : c'est une propriete du CHEMIN, pas de\n"
        "        l'agent -- le meme agent commit tantot par le pont stdio, tantot ici.\n"
        '\n'
        '        PORTEE : ceci rend une provenance OPERATIONNELLE (le hub sait qui il a\n'
        '        authentifie) sous forme de TRACE LOCALE. Ce n\'est PAS une attestation\n'
        '        infalsifiable : la commande executee peut reposer la variable elle-meme.\n'
        '        Ne jamais presenter ces notes comme une preuve d\'origine.\n'
        '        """\n'
        '        import sys as _s\n'
        '\n'
        '        _s.path.insert(0, str(self.root / "app"))\n'
        '        from forge_sandbox_exec import spawn_as_sandbox\n'
        '\n'
        '        _ag = (agent or "").strip().upper()\n'
        '        _prov = {"LAFORGE_AGENT": _ag, "LAFORGE_AGENT_CHANNEL": "HUB_SHELL"} if _ag else None\n'
        '        return spawn_as_sandbox(f"cmd.exe /c {cmd}", online=online,\n'
        '                                timeout=max(5, int(timeout)), env_extra=_prov)\n',
    ),
    (
        '                        return self._run_sandboxed_shell(cmd, _online, timeout)\n',
        '                        return self._run_sandboxed_shell(cmd, _online, timeout, agent)\n',
    ),
    (
        '                        None, lambda: self._run_sandboxed_shell(cmd_str, _online, timeout))\n',
        '                        None, lambda: self._run_sandboxed_shell(cmd_str, _online, timeout, agent))\n',
    ),
]


def main() -> int:
    if not CIBLE.is_file():
        print("ABSENT : %s" % CIBLE)
        return 2
    txt = CIBLE.read_text(encoding="utf-8")
    if MARQUE in txt:
        print("DEJA APPLIQUE (marque %s presente) — aucune ecriture." % MARQUE)
        return 0

    for i, (vieux, _neuf) in enumerate(REMPLACEMENTS, 1):
        n = txt.count(vieux)
        if n != 1:
            print("STOP bloc %d : %d occurrence(s) au lieu de 1 — rien ecrit." % (i, n))
            return 3

    neuf_txt = txt
    for vieux, neuf in REMPLACEMENTS:
        neuf_txt = neuf_txt.replace(vieux, neuf, 1)

    try:
        compile(neuf_txt, str(CIBLE), "exec")
    except SyntaxError as e:
        print("STOP : le resultat ne compile pas (%s ligne %s) — rien ecrit." % (e.msg, e.lineno))
        return 4

    CIBLE.write_text(neuf_txt, encoding="utf-8")
    print("PATCH APPLIQUE : %d bloc(s), %d -> %d octets" % (
        len(REMPLACEMENTS), len(txt.encode("utf-8")), len(neuf_txt.encode("utf-8"))))
    print("Le hub doit etre REDEMARRE pour charger le nouveau code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
