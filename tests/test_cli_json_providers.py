"""Upgrade CLI providers : sortie JSON parsée + fallback brut + non-régression registre."""
import importlib

ap = importlib.import_module("forge_agent_proxy")


def test_parse_claude_json():
    assert ap._parse_claude_json('{"result":"hello","usage":{}}') == "hello"
    assert ap._parse_claude_json('{"text":"hi"}') == "hi"
    assert ap._parse_claude_json("plain text not json") == "plain text not json"  # fallback brut
    assert ap._parse_claude_json("") == ""


def test_parse_gemini_json():
    assert ap._parse_gemini_json('{"response":"bonjour"}') == "bonjour"
    assert ap._parse_gemini_json('{"result":"r"}') == "r"
    assert ap._parse_gemini_json("raw output") == "raw output"  # fallback brut


def test_cli_providers_still_register():
    # non-régression : les edits ask() n'ont pas cassé l'import/instanciation
    for n in ("claude_cli", "gemini_cli", "codex_cli"):
        assert n in ap._PROVIDERS, n
