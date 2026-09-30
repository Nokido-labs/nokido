#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_wasm_selftest.py — vérifie la voie wasm NATIVE de forge_wasm_cervelet.

Self-contained : génère un add.wat, appelle health_wasmtime() + run_wasm() et
imprime le verdict JSON. À lancer via `run action=trusted_script`."""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/tests : verifie la voie wasm native de forge_wasm_cervelet"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_wasm_cervelet as wc  # noqa: E402

WAT = """(module
  (func (export "add") (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add))
"""


def main() -> int:
    out: dict = {}
    out["exe"] = wc._wasmtime_exe()
    out["health"] = wc.health_wasmtime()
    d = Path(tempfile.gettempdir()) / "forge_wasm_selftest_add.wat"
    d.write_text(WAT, encoding="utf-8")
    out["run_add_3_4"] = wc.run_wasm(str(d), func="add", args=[3, 4])
    ok = (out["run_add_3_4"].get("result") == "7")
    out["VERDICT"] = "PASS" if ok else "FAIL"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
