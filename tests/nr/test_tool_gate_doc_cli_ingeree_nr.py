"""NR : un WebFetch sur la doc d'un CLI oriente vers le RAG, ou cette doc est ingeree.

Owner 5/11 : « tu as les docs de chaque cli ingere, pourquoi tu ne t'en sers pas ? ». Une page de doc lue en WebFetch a rendu
60 000 caracteres et creve le budget de volume ; le RAG (source claude_code_docs) rendait le passage utile en quelques lignes,
y compris le plafond de la liste de skills que le WebFetch avait manque.
"""
import importlib.util
import pathlib

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_tool_gate.py"
_spec = importlib.util.spec_from_file_location("forge_tool_gate_doc_nr", _CHEMIN)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _decision(url):
    return gate.decide("claude", "agt_claude", "WebFetch", {"url": url}, ring=1)


def test_doc_de_cli_oriente_vers_le_rag():
    d = _decision("https://code.claude.com/docs/en/costs")
    assert d["action"] == "deport"
    assert "rag" in d["reason"] and "ingér" in d["reason"]


def test_doc_codex_nomme_sa_source_et_ne_bloque_pas():
    d = _decision("https://www.developers.openai.com/codex/config-file/config-reference.md")
    assert d["action"] == "deport" and d["target"] == "hub:rag"
    assert "openai_docs" in d["reason"]


def test_autre_page_garde_la_raison_de_souverainete():
    d = _decision("https://exemple.org/page")
    assert d["action"] == "deport"
    assert "SearXNG" in d["reason"] and "ingér" not in d["reason"]


def test_url_absente_ne_plante_pas():
    assert "SearXNG" in gate.decide("claude", "agt_claude", "WebFetch", {}, ring=1)["reason"]
