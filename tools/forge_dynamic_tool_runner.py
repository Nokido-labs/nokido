#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_dynamic_tool_runner.py — Runner ISOLÉ pour outils forgés (sandbox-forced-default).

Idée Ironsmith : un artefact GÉNÉRÉ s'exécute sandboxé par défaut. Ce runner est lancé par
forge_call_dynamic via spawn_as_sandbox (process bas-privilège) ; il charge l'outil forgé,
l'appelle avec les kwargs (fichier JSON), et écrit le résultat dans un out-file JSON.
argv: <tool_path> <tool_name> <kwargs_json_path> <out_json_path>
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main() -> None:
    tool_path, tool_name, kwargs_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    res: dict = {}
    try:
        kwargs = {}
        if Path(kwargs_path).exists():
            kwargs = json.loads(Path(kwargs_path).read_text(encoding="utf-8") or "{}")
        spec = importlib.util.spec_from_file_location("forged_tool", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # exécution top-level DANS le sandbox
        import re
        safe = re.sub(r"[^a-z0-9_]", "_", tool_name.lower())
        func = getattr(mod, tool_name, None) or getattr(mod, safe, None)
        if not func:
            funcs = [v for k, v in vars(mod).items() if callable(v) and not k.startswith("_")]
            func = funcs[0] if funcs else None
        if not func:
            res = {"error": f"no callable in tool '{tool_name}'"}
        else:
            res = {"result": func(**kwargs)}
    except Exception as e:  # noqa: BLE001
        res = {"error": f"{type(e).__name__}: {e}"}
    try:
        Path(out_path).write_text(json.dumps(res, default=str), encoding="utf-8")
    except Exception:
        Path(out_path).write_text(json.dumps({"error": "résultat non sérialisable"}), encoding="utf-8")


if __name__ == "__main__":
    main()
