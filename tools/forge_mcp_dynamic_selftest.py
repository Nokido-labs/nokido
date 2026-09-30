#!/usr/bin/env python3
"""forge_mcp_dynamic_selftest.py — e2e : outils forges exposes en MCP (A1+A2).

Forge un outil benin -> verifie qu'il apparait dans le catalogue MCP
(_forge_dynamic_catalog), dans get_tool_list(ring=2) (2 generiques + dyn_<nom>),
et que dispatch (_handle_forge_dynamic) l'execute sous SecretGuard. Cleanup.

Run : `LAFORGE_PYTHON tools/forge_mcp_dynamic_selftest.py` (contexte trusted).
"""
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_tool_forger as tf  # noqa: E402
from nokido_agent.app import forge_mcp_registry as mcp  # noqa: E402


def main() -> int:
    code = "def hello_dyn(x: int = 1) -> dict:\n    return {'doubled': x * 2}\n"
    p = tf._save_tool("hello_dyn", code, "double la valeur x", "def hello_dyn(x: int) -> dict")
    tf._registry_add("hello_dyn", "double la valeur x", "def hello_dyn(x: int) -> dict", str(p))
    try:
        reg = mcp.get_registry()

        # A1 : 2 generiques presents
        cat = {t["name"] for t in reg._forge_dynamic_catalog()}
        assert "forge_call_dynamic" in cat and "forge_list_dynamic_tools" in cat, cat
        # A2 : 1 entree par outil forge
        assert "dyn_hello_dyn" in cat, cat

        # tools/list (ring 2) expose les 3
        tl = {t["name"] for t in reg.get_tool_list(ring=2)}
        assert {"forge_call_dynamic", "forge_list_dynamic_tools", "dyn_hello_dyn"} <= tl, sorted(tl)[:20]
        # ring 4 (public) ne doit PAS les exposer
        tl4 = {t["name"] for t in reg.get_tool_list(ring=4)}
        assert "dyn_hello_dyn" not in tl4 and "forge_call_dynamic" not in tl4, "leak ring4"

        # dispatch : forge_list_dynamic_tools
        r_list = asyncio.run(reg._handle_forge_dynamic("forge_list_dynamic_tools", {}, "TEST", 2))
        assert any(t["name"] == "hello_dyn" for t in r_list.get("tools", [])), r_list
        # dispatch : forge_call_dynamic (generique)
        r_gen = asyncio.run(reg._handle_forge_dynamic("forge_call_dynamic", {"name": "hello_dyn", "kwargs": {"x": 21}}, "TEST", 2))
        assert r_gen.get("result", {}).get("doubled") == 42, r_gen
        # dispatch : dyn_<nom> (nomme, A2)
        r_dyn = asyncio.run(reg._handle_forge_dynamic("dyn_hello_dyn", {"kwargs": {"x": 5}}, "TEST", 2))
        assert r_dyn.get("result", {}).get("doubled") == 10, r_dyn
        # ring gate
        r_deny = asyncio.run(reg._handle_forge_dynamic("dyn_hello_dyn", {"kwargs": {"x": 5}}, "TEST", 3))
        assert "SECURITY" in str(r_deny), r_deny

        print("MCP-DYN OK | A1(2 generiques) + A2(dyn_hello_dyn) listes ring2, masques ring4, "
              "dispatch generique=42 dyn=10, ring3 deny")
        return 0
    finally:
        try:
            p.unlink()
        except Exception:
            pass
        rr = tf._registry_load()
        rr.pop("hello_dyn", None)
        tf._registry_save(rr)


if __name__ == "__main__":
    raise SystemExit(main())
