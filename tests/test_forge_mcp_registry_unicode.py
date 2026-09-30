# -*- coding: utf-8 -*-
"""
tests/test_forge_mcp_registry_unicode.py — Tests de sécurité pour le scan Unicode invisible / TAG-block.
"""
from __future__ import annotations

import asyncio
import pytest
from forge_mcp_registry import ToolRegistry, check_unicode_concealment


def test_check_unicode_concealment_clean():
    # Chaîne propre
    ok, reason = check_unicode_concealment("clean_tool_name")
    assert not ok

    # Dictionnaire propre
    ok, reason = check_unicode_concealment(
        {"path": "/tmp/test", "explanation": "This is a clean explanation"}
    )
    assert not ok


def test_check_unicode_concealment_invisibles():
    # Zero-width space (ZWSP) dans une chaîne
    ok, reason = check_unicode_concealment("tool\u200Bname")
    assert ok
    assert "U+200B" in reason

    # Zero-width joiner (ZWJ) dans une valeur de dictionnaire
    ok, reason = check_unicode_concealment({"explanation": "Hello\u200DWorld"})
    assert ok
    assert "U+200D" in reason


def test_check_unicode_concealment_tag_block():
    # TAG character dans une chaîne
    ok, reason = check_unicode_concealment("tool\U000E0020name")
    assert ok
    assert "U+E0020" in reason

    # TAG character dans une clé de dictionnaire
    ok, reason = check_unicode_concealment({"key\U000E0030": "value"})
    assert ok
    assert "U+E0030" in reason


@pytest.mark.asyncio
async def test_dispatch_rejects_malicious_name():
    reg = ToolRegistry()
    # Nom de tool avec un ZWSP à la fin
    res = await reg.dispatch(
        "read\u200B", {"path": "/tmp/test", "explanation": "test"}, agent="TEST", ring=0
    )
    assert isinstance(res, dict)
    assert res.get("error") == "security_reject"
    assert "Unicode concealment detected in tool name" in res.get("reason", "")


@pytest.mark.asyncio
async def test_dispatch_rejects_malicious_args():
    reg = ToolRegistry()
    # Arguments contenant un caractère TAG-block
    res = await reg.dispatch(
        "read",
        {"path": "/tmp/test\U000E0025", "explanation": "test"},
        agent="TEST",
        ring=0,
    )
    assert isinstance(res, dict)
    assert res.get("error") == "security_reject"
    assert "Unicode concealment detected in tool arguments" in res.get("reason", "")


@pytest.mark.asyncio
async def test_dispatch_rejects_malicious_metadata():
    class CustomRegistry(ToolRegistry):
        def _all_tools(self):
            # Retourne un catalogue mocké avec un outil contenant un caractère caché U+E0050 dans la description
            return [
                {
                    "name": "malicious_tool",
                    "description": "This is a malicious tool description \U000E0050",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]

    reg = CustomRegistry()
    res = await reg.dispatch(
        "malicious_tool", {"explanation": "test"}, agent="TEST", ring=0
    )
    assert isinstance(res, dict)
    assert res.get("error") == "security_reject"
    assert "Unicode concealment detected in tool metadata" in res.get("reason", "")


@pytest.mark.asyncio
async def test_dispatch_memoization():
    class SpyingRegistry(ToolRegistry):
        def __init__(self):
            super().__init__()
            self.all_tools_calls = 0

        def _all_tools(self):
            self.all_tools_calls += 1
            return super()._all_tools()

    reg = SpyingRegistry()
    # Premier appel - doit appeler _all_tools()
    await reg.dispatch(
        "read", {"path": "/tmp/test", "explanation": "test"}, agent="TEST", ring=0
    )
    assert reg.all_tools_calls == 1

    # Deuxième appel - ne doit PAS ré-appeler _all_tools() car resolved est dans _unicode_meta_clean
    await reg.dispatch(
        "read", {"path": "/tmp/test", "explanation": "test"}, agent="TEST", ring=0
    )
    assert reg.all_tools_calls == 1

