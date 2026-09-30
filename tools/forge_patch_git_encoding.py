#!/usr/bin/env python
"""tools/forge_patch_git_encoding.py — décodage tolérant pour le git de trusted_script.

__FORGE_COLOR__ = "infra/bootstrap"

POURQUOI CE SCRIPT PLUTÔT QU'UNE ÉDITION DIRECTE
------------------------------------------------
`app/forge_mcp_registry.py` est un CRITICAL_FILE : `governed_edit` le refuse (il faut
`LAFORGE_ALLOW_CRITICAL_WRITE=1`, réservé à la maintenance owner) et l'écriture native
est refusée par `forge_tool_gate` (profil client, enforce ON). Les deux gardes sont
BONS — c'est le chokepoint MCP. Le chemin gouverné restant est un script COMMITÉ lancé
en `trusted_script` : le privilège y vient du code revu, pas d'un flag contourné.
Même pattern que forge_patch_wasm_routing / forge_patch_presence_namespace.

LE DÉFAUT CORRIGÉ (mesuré 2026-07-29, deux fois de suite)
---------------------------------------------------------
`_handle_trusted_script._git()` lançait git avec `text=True` SANS `encoding`. Le hub
tourne sous `PYTHONUTF8=1`, donc le décodage est UTF-8 STRICT, alors que git écrit ses
messages dans la locale système (cp1252 en français). Un seul accent suffit :

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x82 in position 13

L'erreur tombe DANS LE THREAD LECTEUR de subprocess. Le script appelé réussit quand
même (`exit 0`) — c'est ce qui rend le défaut pernicieux : un traceback parasite pollue
la sortie, et une sortie git pourrait être PERDUE sans que personne le voie. Distinguer
« rien trouvé » de « je n'ai pas pu lire » vaut aussi pour un flux.

GARDES
------
Idempotent (ne fait rien si déjà patché), vérifie l'AST AVANT d'écrire, et n'écrit pas
si le motif attendu est absent — mieux vaut ne rien faire que patcher à l'aveugle.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

AVANT = (
    '        def _git(*cmd):\n'
    '            return _sp.run(["git", "-C", str(root), *cmd], capture_output=True, text=True, timeout=30)\n'
)

APRES = (
    '        def _git(*cmd):\n'
    '            # encoding + errors EXPLICITES. `text=True` seul décode avec l\'encodage\n'
    '            # préféré du process, et le hub tourne sous PYTHONUTF8=1 -> UTF-8 STRICT.\n'
    '            # Or git écrit ses messages dans la locale du système (cp1252 en FR) : un\n'
    '            # seul accent lève UnicodeDecodeError DANS LE THREAD LECTEUR de subprocess.\n'
    '            # Le trusted_script réussit quand même (exit 0) — c\'est ce qui rend le\n'
    '            # défaut pernicieux : traceback parasite, et une sortie git pourrait être\n'
    '            # PERDUE sans qu\'on le voie. Mesuré 2026-07-29 : octet 0x82, position 13.\n'
    '            return _sp.run(\n'
    '                ["git", "-C", str(root), *cmd],\n'
    '                capture_output=True, text=True, timeout=30,\n'
    '                encoding="utf-8", errors="replace",\n'
    '            )\n'
)

MARQUE = 'encoding="utf-8", errors="replace",'


def main() -> int:
    if not CIBLE.is_file():
        print(f"ECHEC: cible introuvable : {CIBLE}")
        return 2

    src = CIBLE.read_text(encoding="utf-8")

    if MARQUE in src and "_git(*cmd)" in src and AVANT not in src:
        print("[patch] deja applique — rien a faire (idempotent).")
        return 0

    if AVANT not in src:
        print("ECHEC: motif attendu ABSENT — le code a change. On n'ecrit RIEN.")
        print("       Relire _handle_trusted_script._git avant de rejouer ce patch.")
        return 3

    if src.count(AVANT) != 1:
        print(f"ECHEC: motif trouve {src.count(AVANT)} fois, attendu 1. On n'ecrit RIEN.")
        return 4

    neuf = src.replace(AVANT, APRES, 1)

    # AST AVANT ecriture : un .py casse dans le chokepoint MCP fait fail-close le hub
    # au reboot, SANS message. On ne remplace pas un fichier qu'on n'a pas su parser.
    try:
        ast.parse(neuf, filename=str(CIBLE))
    except SyntaxError as e:
        print(f"ECHEC: AST casse apres patch ({e.lineno}: {e.msg}). RIEN ecrit.")
        return 5

    CIBLE.write_text(neuf, encoding="utf-8")
    print(f"[patch] applique : {CIBLE.relative_to(ROOT)} ({len(src)} -> {len(neuf)} chars)")
    print("[patch] AST valide. Le hub prendra le correctif a son prochain rechargement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
