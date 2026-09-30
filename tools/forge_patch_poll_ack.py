#!/usr/bin/env python
"""tools/forge_patch_poll_ack.py — rend l'accusé de réception OPTIONNEL sur `poll`.

__FORGE_COLOR__ = "infra/bootstrap"

POURQUOI UN SCRIPT
------------------
`app/forge_mcp_registry.py` est un CRITICAL_FILE : `governed_edit` le refuse et
l'écriture native est bloquée par `forge_tool_gate`. Les deux gardes sont bons — c'est
le chokepoint MCP. Le chemin gouverné est un script COMMITÉ lancé en `trusted_script`,
où le privilège vient du code revu. Même pattern que forge_patch_git_encoding.

LE DÉFAUT (mesuré 2026-07-29)
-----------------------------
`handle_poll` relève le postal avec `secretaire(agent, ack=True)` : lire = accuser
réception. C'est juste pour un agent qui TRAITE son courrier. Ça ne l'est pas pour un
lecteur PASSIF — et `gemini_poll_daemon` polle en tant que GEMINI toutes les 30 s pour
AFFICHER. Il faisait donc passer les mails de `delivered` à `acked`, tandis que
`forge_gemini_autonomous_agent` — qui, lui, répond — lit via `secretaire(ack=False)`,
lequel ne rend QUE les `delivered`.

Une file, deux lecteurs, dont le passif vidait la boîte de l'actif. Reproduit : un mail
actionnable posté à GEMINI est acké en 1450 ms, aucune réponse produite, journal de
l'auto-répondeur inchangé. La demande de diagnostic du jour avait été ackée en 106 ms,
avant même que l'auto-répondeur démarre.

LE CORRECTIF
------------
`ack` devient un argument : `poll` continue d'acker PAR DÉFAUT (aucun appelant existant
ne change de comportement), et un lecteur passif passe `ack=false`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

AVANT = (
    "            for _m in _postal_secretaire(agent, ack=True):\n"
)

APRES = (
    "            # ack OPTIONNEL (2026-07-29) : lire n'est pas toujours traiter. Un lecteur\n"
    "            # PASSIF (daemon d'affichage) doit pouvoir relever SANS accuser réception,\n"
    "            # sinon il vide la boîte de l'agent qui, lui, répond. Défaut inchangé =\n"
    "            # True : aucun appelant existant ne voit son comportement modifié.\n"
    "            _ack = str(args.get(\"ack\", True)).strip().lower() not in (\"false\", \"0\", \"no\")\n"
    "            for _m in _postal_secretaire(agent, ack=_ack):\n"
)

MARQUE = '_postal_secretaire(agent, ack=_ack)'


def main() -> int:
    if not CIBLE.is_file():
        print(f"ECHEC: cible introuvable : {CIBLE}")
        return 2

    src = CIBLE.read_text(encoding="utf-8")

    if MARQUE in src and AVANT not in src:
        print("[patch] deja applique — rien a faire (idempotent).")
        return 0
    if AVANT not in src:
        print("ECHEC: motif attendu ABSENT — le code a change. On n'ecrit RIEN.")
        return 3
    if src.count(AVANT) != 1:
        print(f"ECHEC: motif trouve {src.count(AVANT)} fois, attendu 1. On n'ecrit RIEN.")
        return 4

    neuf = src.replace(AVANT, APRES, 1)
    try:
        ast.parse(neuf, filename=str(CIBLE))
    except SyntaxError as e:
        print(f"ECHEC: AST casse apres patch ({e.lineno}: {e.msg}). RIEN ecrit.")
        return 5

    CIBLE.write_text(neuf, encoding="utf-8")
    print(f"[patch] applique : {CIBLE.relative_to(ROOT)} ({len(src)} -> {len(neuf)} chars)")
    print("[patch] AST valide. Effectif au prochain rechargement du hub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
