"""
app/core/payload_validator.py - Validation des payloads LLM/MCP.

PATTERN : Chain of Responsibility.
Injete dans la facade pour valider AVANT l'envoi au modele.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


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
        for t in tools:
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

    def validate_payload(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Valide un payload complet (messages + tools).
        """
        # 1. Verifier les messages
        messages = payload.get("messages", [])
        if not messages:
            return False, "Payload invalide: 'messages' est vide ou absent"

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or "content" not in msg or "role" not in msg:
                return False, f"Message #{i} invalide (role/content manquants)"

        # 2. Verifier les outils si presents
        if "tools" in payload:
            ok, err = self.validate_tools(payload["tools"])
            if not ok:
                return False, err

        return True, ""
