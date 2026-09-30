#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_service_import_check.py — diagnostic NON-LEAK des services quarantinés : importe
chaque module d'entrée (sans lancer le daemon) -> capture les bugs d'IMPORT (cffi, deps
manquantes, syntaxe). Les bugs en main() (ex. Starlette) sont trouvés autrement. Jetable."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MODS = [
    "forge_chain_executor", "forge_task_executor", "forge_web_egress", "nokido_web_hub",
    "forge_rss_watcher", "forge_skill_curator", "forge_trace_collector_rich", "forge_cowork",
    "forge_log_retention", "nokido_graph_server", "forge_graph_explorer", "forge_hebbian_linker",
    "forge_autonomous_loops", "forge_memory_consolidator", "forge_offline_trainer",
    "forge_anthropic_ingress", "forge_gemini_ingress", "forge_openai_proxy",
]


def main() -> int:
    ok = ko = 0
    for m in MODS:
        try:
            importlib.import_module(m)
            print("OK   " + m)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"KO   {m} :: {type(e).__name__}: {str(e)[:100]}")
            ko += 1
    print(f"--- import: {ok} OK / {ko} KO ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
