#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_patch_crawl_offload.py - deporte les appels bloquants de handle_crawl.

forge_mcp_registry.py est CRITICAL_FILE : governed_edit le refuse sans la fenetre
owner. Ce patch git-tracke, lance en trusted_script avec accord owner (2026-08-15),
applique la correction ; le gate AST du pre-commit revalide au commit.

RCA 2026-08-15 : handle_crawl (async) appelait crawl_url() (I/O reseau, timeout
<=15s) puis fetch_and_ingest() (vectorisation locale) EN SYNCHRONE, donc sur
l'event-loop. Mesure -> loop-lag 3390 ms puis 6010 ms sur deux crawls ; le
LoopKillWatchdog (60s) a tue le hub, sans respawn -> 13 min de mort.
research_agent etait deja deporte (asyncio.to_thread) ; handle_crawl etait le
dernier appelant bloquant reste sur la boucle.

Correction MINIMALE et sure : les deux appels bloquants passent en
asyncio.to_thread. La methode est deja async, l'await est legal, et le loop est
libere pendant que le thread travaille -- ce qui suffit a empecher le wedge.

Idempotent : NOOP si deja patche. Verifie AST + octet apres ecriture.
"""
from __future__ import annotations

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIBLE = os.path.join(ROOT, "app", "forge_mcp_registry.py")

# Deux remplacements de ligne EXACTS, sans guillemets imbriques : robustes.
REMPLACEMENTS = [
    (
        "        md = crawl_url(url, timeout=timeout)",
        "        # deporte hors event-loop : I/O reseau bloquante (RCA hub mort 2026-08-15)\n"
        "        md = await asyncio.to_thread(crawl_url, url, timeout)",
    ),
    (
        "                res = fetch_and_ingest(url)",
        "                res = await asyncio.to_thread(fetch_and_ingest, url)",
    ),
]

SENTINELLE = "await asyncio.to_thread(crawl_url"


def main() -> int:
    src = open(CIBLE, encoding="utf-8").read()

    if SENTINELLE in src:
        print("[patch] NOOP : handle_crawl deja deporte")
        return 0

    neuf = src
    for avant, apres in REMPLACEMENTS:
        if avant not in neuf:
            print(f"ABORT: ligne attendue introuvable, le fichier a change :\n  {avant}")
            return 2
        if neuf.count(avant) != 1:
            print(f"ABORT: ligne ambigue ({neuf.count(avant)} occurrences), ne PAS patcher a l'aveugle :\n  {avant}")
            return 2
        neuf = neuf.replace(avant, apres, 1)

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as exc:
        print(f"ABORT: le resultat ne parse pas ({exc}) - rien ecrit")
        return 3
    imports = {n.name for node in ast.walk(arbre) if isinstance(node, ast.Import)
               for n in node.names}
    if "asyncio" not in imports:
        print("ABORT: `import asyncio` absent du module - le patch l'utilise")
        return 3

    open(CIBLE, "w", encoding="utf-8").write(neuf)
    if open(CIBLE, encoding="utf-8").read() != neuf:
        print("CRITIQUE: relecture != ecrit")
        return 4
    print(f"[patch] handle_crawl deporte - {len(neuf)} octets, AST OK, relecture identique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
