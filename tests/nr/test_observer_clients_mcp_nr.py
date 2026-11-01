"""NR 31/10 (accord owner : « mesurer ce que le CLI declare a sa connexion », etape 1 de l'elicitation dans le CLI).

Mesure du jour : `hub confirmer_owner` -> INDISPONIBLE « requete sans Mcp-Session-Id » ; ce CLI n'apparait PAS au
registre des sessions (aucun `initialize` enregistre). Le hub gere deja la revision 2026-07-28 (forge_mcp_protocole), ou
le client declare version et capacites A CHAQUE requete dans `_meta`. L'observateur ecrit, par (agent, client,
protocole, methode, capacites), UNE ligne : noms seulement, jamais une valeur d'en-tete d'authentification.
"""
from __future__ import annotations

import json

from nokido_agent.app import forge_mcp_elicitation as E

NS = "io.modelcontextprotocol/"


def _corps(proto="2026-07-28", caps=None, methode="tools/call"):
    meta = {NS + "protocolVersion": proto, NS + "clientInfo": {"name": "claude-code", "version": "2.1.314"}}
    if caps is not None:
        meta[NS + "clientCapabilities"] = caps
    return {"jsonrpc": "2.0", "id": 1, "method": methode, "params": {"_meta": meta}}


def test_une_ligne_par_signature_noms_seulement(tmp_path, monkeypatch):
    j = tmp_path / "mcp_clients.jsonl"
    monkeypatch.setattr(E, "JOURNAL_CLIENTS", j)
    monkeypatch.setattr(E, "_SIGNATURES_VUES", set())
    entetes = {"MCP-Protocol-Version": "2026-07-28", "Authorization": "Bearer SECRET-NE-PAS-ECRIRE"}
    E.observer_requete("CLAUDE", entetes, _corps(caps={"elicitation": {"form": {}}}))
    E.observer_requete("CLAUDE", entetes, _corps(caps={"elicitation": {"form": {}}}))  # meme signature : ignoree
    lignes = [json.loads(l) for l in j.read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 1
    l = lignes[0]
    assert l["agent"] == "CLAUDE" and l["client"] == "claude-code" and l["protocole_meta"] == "2026-07-28"
    assert l["protocole_entete"] == "2026-07-28" and l["session_id"] is False and l["capacites"] == ["elicitation"]
    assert "SECRET" not in j.read_text(encoding="utf-8")


def test_client_2025_sans_meta(tmp_path, monkeypatch):
    j = tmp_path / "mcp_clients.jsonl"
    monkeypatch.setattr(E, "JOURNAL_CLIENTS", j)
    monkeypatch.setattr(E, "_SIGNATURES_VUES", set())
    E.observer_requete("CODEX", {"Mcp-Session-Id": "abc"}, {"jsonrpc": "2.0", "method": "tools/call", "params": {}})
    l = json.loads(j.read_text(encoding="utf-8").splitlines()[0])
    assert l["session_id"] is True and l["protocole_meta"] is None and l["capacites"] == []


def test_le_hub_observe_chaque_requete_avant_validation():
    """Le chemin REEL : mcp_post appelle observer_requete AVANT la validation 2026 (un refus doit etre observe aussi)."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "mcp_post")
    corps = ast.unparse(fn)
    assert "observer_requete" in corps
    assert corps.index("observer_requete") < corps.index("_valider26(")


def test_ne_leve_jamais(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "JOURNAL_CLIENTS", tmp_path / "x" / "y.jsonl")
    monkeypatch.setattr(E, "_SIGNATURES_VUES", set())
    E.observer_requete("A", None, None)  # entrees absurdes : aucune exception
