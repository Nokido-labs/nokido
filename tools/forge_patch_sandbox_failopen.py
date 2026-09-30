#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0 SECURITE — fermer le fail-open du dispatch `sandbox` (mesure 2026-09-01).

CE QUE CE PATCH CORRIGE. La condition d'aiguillage de `handle_run` testait
`sandbox not in ("local", "")` : une valeur INCONNUE etait donc prise pour un
"type explicite", contournait le confinement par compte, puis ne matchait AUCUNE
branche de `_exec_sandboxed` et tombait sur la branche finale, qui execute `pwsh`
IN-PROCESS DU HUB.

Mesures qui l'etablissent, toutes en lecture seule :

    sandbox="local"                  -> desktop-xxxx\\laforgesbxoffline
    sandbox="online"                 -> NT AUTHORITY\\SYSTEM
    sandbox="trusted"                -> NT AUTHORITY\\SYSTEM  (SeTcb + SeDebug ACTIVES)
    sandbox="zzz_valeur_inexistante" -> NT AUTHORITY\\SYSTEM

Une entree INVALIDE obtenait donc PLUS de privileges qu'une entree valide. C'est un
fail-OPEN sur une frontiere de privilege, et la valeur inventee le prouve : le defaut
n'est pas propre a `online`/`trusted`, il est dans la SELECTION du confinement.

POURQUOI UN SCRIPT ET PAS `governed_edit`. `app/forge_mcp_registry.py` est un
CRITICAL_FILE : `governed_edit` refuse, et le forcer avec `allow_critical` a DEJA
coupe le hub sur un gros fichier (2026-08-27). Le remede documente est un patch
committe, lance en `trusted_script`. L'ecriture est ATOMIQUE (fichier temporaire
puis `os.replace`) : c'est la reecriture NON atomique qui expose un import concurrent
a un fichier tronque.

IDEMPOTENT : si la garde est deja posee, le script ne touche a rien et le DIT.
Usage :
    run action=trusted_script path=tools/forge_patch_sandbox_failopen.py
    LAFORGE_PYTHON tools/forge_patch_sandbox_failopen.py --dry-run
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/frontiere-de-privilege"

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"
MARQUEUR = "_SANDBOX_TYPES"

BLOC_GARDE = '''    # Types de bac RECONNUS. Toute autre valeur est REFUSEE avant l'aiguillage.
    #
    # POURQUOI (mesure 2026-09-01, P0 securite). La condition d'aiguillage testait
    # `sandbox not in ("local", "")` : une valeur INCONNUE etait donc prise pour un
    # "type explicite", contournait le confinement par compte, puis ne matchait
    # AUCUNE branche de `_exec_sandboxed` et tombait sur la branche finale, qui
    # execute `pwsh` IN-PROCESS DU HUB. Mesure : `sandbox="zzz_valeur_inexistante"`,
    # `"online"` et `"trusted"` rendaient tous NT AUTHORITY\\SYSTEM (SeTcbPrivilege et
    # SeDebugPrivilege ACTIVES), alors que `sandbox="local"` rendait bien
    # LaForgeSbxOffline. Une entree INVALIDE obtenait donc PLUS de privileges qu'une
    # entree valide -- fail-OPEN sur une frontiere de privilege.
    #
    # `""` et `"local"` restent acceptes : c'est le comportement historique quand
    # SANDBOX_EXEC est desactive. On ferme le chemin que PERSONNE n'a choisi, pas un
    # chemin voulu.
    _SANDBOX_TYPES = ("", "local", "console", "ps_clm", "docker", "windows", "wasm", "gvisor")

    def _sandbox_valide(self, sandbox: str) -> str:
        """'' si le type est reconnu, sinon le message de REFUS.

        Un parametre de securite inconnu doit echouer FERME, jamais choisir le chemin
        le plus puissant. Le message nomme la forme correcte, sinon l'appelant reessaie
        la meme erreur : l'egress se demande par `network=true`, et un script
        git-tracke privilegie par `action=trusted_script`.
        """
        if str(sandbox or "") in self._SANDBOX_TYPES:
            return ""
        return (
            "SECURITY: sandbox=%r inconnu -- REFUSE (fail-closed). Types valides : %s. "
            "Une valeur inconnue ne retombe JAMAIS sur un contexte plus privilegie. "
            "Egress : network=true. Script git-tracke privilegie : action=trusted_script."
            % (str(sandbox)[:40], ", ".join(t for t in self._SANDBOX_TYPES if t))
        )

    def _sandbox_decision(self, args: dict, agent: str) -> tuple:
'''

REMPLACEMENTS = [
    (
        "    def _sandbox_decision(self, args: dict, agent: str) -> tuple:\n",
        BLOC_GARDE,
    ),
    (
        '            if not cmd_str and not commands:\n'
        '                return "ERR: shell: code ou commands requis"\n',
        '            if not cmd_str and not commands:\n'
        '                return "ERR: shell: code ou commands requis"\n'
        '\n'
        '            # FAIL-CLOSED sur le type de bac, AVANT tout aiguillage (P0 2026-09-01).\n'
        '            _refus_sbx = self._sandbox_valide(sandbox)\n'
        '            if _refus_sbx:\n'
        '                return _refus_sbx\n',
    ),
    (
        '        if sandbox == "console":\n'
        "            return self._exec_console(cmd, timeout, agent, ring)\n",
        '        # Garde en PROFONDEUR : meme si un appelant contourne la validation\n'
        "        # d'entree, une valeur inconnue ne doit pas glisser jusqu'a la branche\n"
        '        # finale (`pwsh` in-process). Les deux gardes disent la meme chose ;\n'
        "        # c'est voulu -- une frontiere de privilege ne tient pas sur un seul\n"
        '        # point de controle.\n'
        '        _refus_sbx = self._sandbox_valide(sandbox)\n'
        '        if _refus_sbx:\n'
        '            return {"ok": False, "stdout": "", "stderr": _refus_sbx,\n'
        '                    "elapsed_ms": _elapsed(), "sandbox": "refuse"}\n'
        '\n'
        '        if sandbox == "console":\n'
        "            return self._exec_console(cmd, timeout, agent, ring)\n",
    ),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ferme le fail-open du dispatch sandbox.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = CIBLE.read_text(encoding="utf-8")
    if MARQUEUR in src:
        print(json.dumps({"ok": True, "etat": "DEJA POSEE", "fichier": str(CIBLE),
                          "note": "idempotent : aucune ecriture"}, ensure_ascii=False))
        return 0

    faits = []
    for cherche, remplace in REMPLACEMENTS:
        n = src.count(cherche)
        if n != 1:
            print(json.dumps({"ok": False, "refus": "ancre non unique", "occurrences": n,
                              "ancre": cherche.strip()[:70],
                              "pourquoi": "un patch qui s'applique au mauvais endroit est "
                                          "pire que pas de patch"}, ensure_ascii=False))
            return 2
        src = src.replace(cherche, remplace, 1)
        faits.append(cherche.strip()[:60])

    try:
        ast.parse(src)
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "refus": "AST invalide apres patch",
                          "detail": f"{exc.lineno}: {exc.msg}"}, ensure_ascii=False))
        return 3

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "ancres": faits,
                          "taille_apres": len(src)}, ensure_ascii=False, indent=1))
        return 0

    # ECRITURE ATOMIQUE : le hub importe ce module ; une reecriture en place l'expose
    # a un fichier tronque, ce qui l'a deja coupe (2026-08-27).
    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        os.replace(tmp, CIBLE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError as _cleanup:  # noqa: BLE001
            # Le temporaire qui SURVIT a un echec doit se voir : sinon il reste a cote
            # du CRITICAL_FILE sans que personne ne sache d'ou il vient.
            print(f"[patch] temporaire NON supprime ({_cleanup}) : {tmp}", file=sys.stderr)
        raise
    print(json.dumps({"ok": True, "etat": "POSEE", "ancres": faits,
                      "fichier": str(CIBLE), "taille": len(src),
                      "note": "actif au PROCHAIN redemarrage du hub : le module est "
                              "charge in-process"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
