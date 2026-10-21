"""
app/core/payload_validator.py - Validation des payloads LLM/MCP.

PATTERN : Chain of Responsibility.
Injete dans la facade pour valider AVANT l'envoi au modele.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _forme_mcp(t: Dict[str, Any]) -> Dict[str, Any]:
    """Format OpenAI des fournisseurs tiers ({"type":"function","function":{name, description?, parameters}}) ramene a
    la forme MCP controlee ici. Mesure 17/10 : un outil OpenAI valide etait REFUSE (cles MCP exigees)."""
    if isinstance(t, dict) and t.get("type") == "function" and isinstance(t.get("function"), dict):
        f = t["function"]
        return {"name": f.get("name"), "description": f.get("description", ""), "inputSchema": f.get("parameters") or {}}
    return t


class PayloadValidator:
    """
    Validateur de payloads pour Nokido.
    Verifie la structure des messages et la validite des outils MCP.
    """

    REQUIRED_TOOL_KEYS = {"name", "description", "inputSchema"}

    def validate_tools(self, tools: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Valide une liste d'outils MCP.
        """
        for brut in tools:
            t = _forme_mcp(brut)
            # 1. Verifier les cles obligatoires
            missing = self.REQUIRED_TOOL_KEYS - t.keys()
            if missing:
                return False, f"Tool '{t.get('name', '?')}' manque les cles: {missing}"

            # 2. Verifier le schema (inputSchema.properties doit etre un dict)
            schema = t.get("inputSchema", {})
            if schema.get("type") != "object":
                # Note: certains outils utilisent 'parameters' (format ancien)
                if "parameters" in t:
                    if t.get("parameters", {}).get("type") != "object":
                        return False, f"Tool '{t['name']}': type doit etre 'object'"
                else:
                    return False, f"Tool '{t['name']}': inputSchema.type doit etre 'object'"

            if not isinstance(schema.get("properties"), dict) and "parameters" not in t:
                # Note: certains anciens formats utilisent 'parameters' au lieu d'inputSchema
                if not isinstance(t.get("parameters", {}).get("properties"), dict):
                    return False, f"Tool '{t['name']}': inputSchema.properties (ou parameters) absent ou invalide"

        return True, ""

    def validate_payload(self, payload: Dict[str, Any], agentique: bool = False) -> Tuple[bool, str]:
        """
        Valide un payload complet (messages + tools).

        `agentique=True` : appel qui doit AGIR (orchestrate, executeurs, A2A) -> `tools` present et NON VIDE exige, sinon
        l'agent devient inerte en silence (regle d'or owner, memoire feedback_validate_tools_payload). Defaut inchange
        pour les appels de texte (juge, resume, embeddings).
        """
        # 1. Verifier les messages
        messages = payload.get("messages", [])
        if not messages:
            return False, "Payload invalide: 'messages' est vide ou absent"

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or "content" not in msg or "role" not in msg:
                return False, f"Message #{i} invalide (role/content manquants)"

        if agentique and not payload.get("tools"):
            return False, "agent inerte : payload d'agent sans definitions d'outils (regle d'or tools)"

        # 2. Verifier les outils si presents
        if "tools" in payload:
            ok, err = self.validate_tools(payload["tools"])
            if not ok:
                return False, err

        return True, ""
