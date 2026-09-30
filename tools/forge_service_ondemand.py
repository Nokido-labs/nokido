#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_service_ondemand.py — bascule des services en ON-DEMAND.

Pose `disabled = true` dans le bloc `[[service]]` des services nommés au sein
de proxy_deno/core/services.toml. Effet : ils ne sont PLUS spawnés au boot
(allège la pression boot, évite les daemons lourds/rares en veille) mais
restent lançables À LA DEMANDE via :

    tools/forge_supervisor_ctl.py ensure <NomService>

(POST :8765/supervisor/service/start/<name> — réveille un disabled).

Idempotent : un bloc qui contient déjà une clé `disabled` est laissé tel quel.
Édition textuelle ancrée sur la ligne `name = "..."` (préserve commentaires et
formatage ; pas de réécriture TOML). Backup .bak avant écriture.

Usage :
    forge_service_ondemand.py                 # set par défaut (incident veille)
    forge_service_ondemand.py NokidoFoo ...  # liste explicite
    forge_service_ondemand.py --dry-run       # montre le diff sans écrire
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOML = os.path.join(ROOT, "proxy_deno", "core", "services.toml")

# Set on-demand validé (incident cascade 2026-06-03) :
DEFAULT_TARGETS = [
    "NokidoSearxng",          # conteneur Docker (search)
    "NokidoWatchAgent",       # veille web, dep Searxng:8080
    "NokidoOfflineTrainer",   # batch training
    "NokidoNightTrainer",     # batch training nocturne
    "NokidoSelfPatcher",      # auto-patch, déclenché par event
    "NokidoMemoryConsolidator",  # consolidation mémoire périodique
    "NokidoGeminiDaemon",     # polling Gemini CLI
    "NokidoMultiLLMDaemon",   # polling multi-LLM
    "NokidoEmbedTrigger",     # embed (dep :5557 disabled) — formalise on-demand
    "NokidoIngestDaemon",     # ingestion RAG à la demande
]

COMMENT = ("  # on-demand 2026-06-03 : wake via "
           "tools/forge_supervisor_ctl.py ensure {name}")


def _block_bounds(lines: list[str], name_idx: int) -> int:
    """Retourne l'index de fin (exclu) du bloc commençant à name_idx."""
    i = name_idx + 1
    while i < len(lines):
        s = lines[i].lstrip()
        if s.startswith("[[") or s.startswith("name ="):
            break
        i += 1
    return i


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    targets = argv or DEFAULT_TARGETS

    with open(TOML, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = text.split("\n")

    patched, skipped, missing = [], [], []
    for name in targets:
        needle = f'name = "{name}"'
        name_idx = next(
            (i for i, ln in enumerate(lines) if ln.strip() == needle), None
        )
        if name_idx is None:
            missing.append(name)
            continue
        end = _block_bounds(lines, name_idx)
        block = lines[name_idx:end]
        if any(ln.lstrip().startswith("disabled") for ln in block):
            skipped.append(name)
            continue
        indent = lines[name_idx][: len(lines[name_idx]) - len(lines[name_idx].lstrip())]
        insert = f"{indent}disabled = true{COMMENT.format(name=name)}"
        lines.insert(name_idx + 1, insert)
        patched.append(name)

    new_text = "\n".join(lines)
    print(f"[ondemand] patched={patched}")
    print(f"[ondemand] skipped(already)={skipped}")
    print(f"[ondemand] missing={missing}")

    if dry:
        print("[ondemand] --dry-run : aucune écriture")
        return 0
    if not patched:
        print("[ondemand] rien à faire")
        return 0

    with open(TOML + ".bak", "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(TOML, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    print(f"[ondemand] écrit {TOML} (backup {TOML}.bak)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
