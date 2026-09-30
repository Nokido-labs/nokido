#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Contrat d'appel du tool `run` : declarer `network`, et dire ce que `sandbox` N'EST PAS.

POURQUOI (suite du P0 du 2026-09-01, chantier SEPARE). Le fail-open est ferme : une
valeur de `sandbox` inconnue est desormais REFUSEE. Mais le refus renvoie vers
`network=true`, et ce parametre n'etait PAS declare dans le schema du tool -- il est lu
par `_sandbox_decision` sans figurer nulle part dans le contrat. On remplacerait donc
une mauvaise porte DANGEREUSE par une bonne porte que certains clients ne savent pas
ouvrir.

VERITE RUNTIME, mesuree apres le redemarrage du hub :

    (defaut) / sandbox="local"  -> desktop-xxxx\\laforgesbxoffline
    network=true                -> desktop-xxxx\\laforgesbxonline
    action=trusted_script       -> LaForgeTrusted
    sandbox="online"/"trusted"  -> REFUSE (fail-closed)

Les trois comptes existaient et fonctionnaient depuis le debut : seule la SYNTAXE
documentee etait fausse. `sandbox="online"` n'a jamais ete un levier d'egress -- il
n'existait pas, et tombait sur une execution SYSTEM par accident de dispatch.

Ce patch ne touche AUCUNE mecanique de securite : il ne change que deux descriptions et
ajoute une propriete au schema. Meme protocole que le P0 : `forge_mcp_registry.py` est un
CRITICAL_FILE, donc script committe + `trusted_script` + ecriture ATOMIQUE.

Usage :
    run action=trusted_script path=tools/forge_patch_run_network_contract.py
    LAFORGE_PYTHON tools/forge_patch_run_network_contract.py --dry-run
"""

from __future__ import annotations

__FORGE_COLOR__ = "SNC/contrat-outils"

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"
MARQUEUR = '"network": {'

ANCIEN = (
    '                        "sandbox": {\n'
    '                            "type": "string",\n'
    '                            "enum": ["local", "docker", "ps_clm", "windows", "wasm", "console", "gvisor"],\n'
    '                            "description": "Execution sandbox (default: local). console=session user'
    ' (ring-0, default-deny). gvisor=tier2 isolation kernel pour untrusted (network=none, via'
    ' forge_exec_tier)",\n'
    '                        },\n'
)

NOUVEAU = (
    '                        "sandbox": {\n'
    '                            "type": "string",\n'
    '                            "enum": ["local", "docker", "ps_clm", "windows", "wasm", "console", "gvisor"],\n'
    '                            "description": "TYPE de bac (default: local). N\'EST PAS le levier'
    " d'egress -- pour le reseau sortant, utiliser `network`. Une valeur HORS de cet enum est"
    ' REFUSEE (fail-closed) : elle ne retombe jamais sur un contexte plus privilegie.'
    ' console=session user (ring-0, default-deny). gvisor=tier2 isolation kernel pour untrusted'
    ' (via forge_exec_tier)",\n'
    '                        },\n'
    '                        "network": {\n'
    '                            "type": "boolean",\n'
    '                            "description": "Reseau SORTANT (actions shell et python).'
    ' absent/false -> compte LaForgeSbxOffline (loopback seul, egress bloque) ; true ->'
    ' LaForgeSbxOnline (egress autorise). C\'est le SEUL levier d\'egress :'
    ' sandbox=\\"online\\" n\'a jamais existe. Pour un script git-tracke privilegie'
    ' (LaForgeTrusted) : action=trusted_script.",\n'
    '                        },\n'
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Declare `network` au contrat du tool run.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = CIBLE.read_text(encoding="utf-8")
    if MARQUEUR in src:
        print(json.dumps({"ok": True, "etat": "DEJA DECLARE", "fichier": str(CIBLE),
                          "note": "idempotent : aucune ecriture"}, ensure_ascii=False))
        return 0

    n = src.count(ANCIEN)
    if n != 1:
        print(json.dumps({"ok": False, "refus": "ancre non unique", "occurrences": n,
                          "pourquoi": "un patch qui s'applique au mauvais endroit est pire "
                                      "que pas de patch"}, ensure_ascii=False))
        return 2
    src = src.replace(ANCIEN, NOUVEAU, 1)

    try:
        ast.parse(src)
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "refus": "AST invalide apres patch",
                          "detail": f"{exc.lineno}: {exc.msg}"}, ensure_ascii=False))
        return 3

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "taille_apres": len(src)},
                         ensure_ascii=False))
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(src)
        os.replace(tmp, CIBLE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError as _cleanup:  # noqa: BLE001
            print(f"[patch] temporaire NON supprime ({_cleanup}) : {tmp}", file=sys.stderr)
        raise
    print(json.dumps({"ok": True, "etat": "DECLARE", "fichier": str(CIBLE),
                      "taille": len(src),
                      "note": "visible par les clients au PROCHAIN redemarrage du hub : le "
                              "catalogue d'outils est construit a l'import"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
