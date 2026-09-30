# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_ui_autocomplete
#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Unification AutocompleteEngine
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import logging
from typing import Dict, List

logger = logging.getLogger("Nokido.UI.Autocomplete")


class AutocompleteEngine:
    """Moteur d'autocomplétion unifié pour Chat et Terminal."""

    def __init__(self) -> None:
        self.commands = {
            "@help": "Aide complète",
            "@run": "SSH Run",
            "@rag": "Gère RAG",
            "@evolve": "Auto-évolution",
            "@agentic": "Analyse compétences",
            "@ci": "CI/CD",
            "@audit": "Audit Code",
            "@code": "Sandbox Python",
            "@loop": "Boucle d'amélioration",
            "@role": "Rôles IA",
            "@mode": "Multi-agents",
            "@status": "État IA",
        }
        self.sub_commands = {
            "@rag": ["info", "size", "list", "reindex", "build"],
            "@mode": ["autonome", "collaboration", "comite"],
            "@ci": ["run", "lint", "test", "env"],
        }
        self.chat_history: List[str] = []
        self._hist_idx: int = -1
        self._ai_terminal_queue: List[str] = []
        self._term_idx: int = -1

    def add_to_history(self, text: str) -> None:
        text = text.strip()
        if not text or text.startswith("@"):
            return
        if not self.chat_history or self.chat_history[-1] != text:
            self.chat_history.append(text)
            if len(self.chat_history) > 300:
                self.chat_history.pop(0)
        self._hist_idx = -1

    def history_up(self, current: str) -> str:
        if not self.chat_history:
            return current
        if self._hist_idx == -1:
            self._hist_idx = len(self.chat_history) - 1
        else:
            self._hist_idx = max(0, self._hist_idx - 1)
        return self.chat_history[self._hist_idx]

    def suggest_cmd(self, prefix: str) -> List[str]:
        if not prefix.startswith("@"):
            return []
        parts = prefix.split()

        # Cas 1 : Préfixe court (ex: "@r") -> Suggérer les commandes de base
        if len(parts) == 1 and not prefix.endswith(" "):
            matches = [c for c in self.commands if c.startswith(prefix)]
            # Si on a un match exact (ex: "@rag"), on ajoute aussi ses sous-commandes
            if prefix in self.sub_commands:
                for s in self.sub_commands[prefix]:
                    matches.append(f"{prefix} {s}")
            return matches

        # Cas 2 : Commande + espace (ex: "@rag ") -> Suggérer uniquement les sous-commandes
        base = parts[0]
        if base in self.sub_commands:
            sub_prefix = parts[1] if len(parts) > 1 else ""
            return [f"{base} {s}" for s in self.sub_commands[base] if s.startswith(sub_prefix)]

        return []
