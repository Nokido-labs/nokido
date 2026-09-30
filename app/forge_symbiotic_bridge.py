"""
forge_symbiotic_bridge.py — Pont Cloud-Local Synchrone pour Nokido.
===================================================================
Utilise Gemma/Qwen en local pour protéger le quota Gemini.
Version synchrone pour intégration directe dans le LLMRouter.
"""

import json
import logging
import requests
import time
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("symbiose")

class SymbioticBridge:
    def __init__(self, ollama_url: str = "http://localhost:11434/api/chat"):
        self.ollama_url = ollama_url
        # Scout : Rapide pour validation/compression
        self.scout_model = "qwen2.5-coder:1.5b" 
        # Muscle : Gemma 4 31B pour la génération de code haute fidélité
        self.muscle_model = "gemma-4-31b-it" 
        
    def _ollama_call_sync(self, model: str, system: str, prompt: str, json_mode: bool = False) -> str:
        """Appel synchrone vers Ollama local."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": 0.0}
        }
        if json_mode:
            payload["format"] = "json"
            
        try:
            # Timeout court (5s) pour le Scout, on ne veut pas ralentir le système
            response = requests.post(self.ollama_url, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()['message']['content']
        except Exception as e:
            # On ne bloque pas tout le système si Ollama est down, on logge et on skip
            logger.debug(f"Symbiose local skip (Ollama offline/busy): {e}")
        return ""

    def compress_context(self, raw_data: str, target_tokens: int = 250) -> str:
        """
        [STRATÉGIE 2] Compresse les logs massifs en local.
        """
        if len(raw_data) < 2000: return raw_data
        
        system = "Tu es un Scout Nokido. Résume ce log d'erreur/code pour un expert. Garde l'essentiel technique."
        prompt = f"Résume en max {target_tokens} mots :\n\n{raw_data[:12000]}"
        
        compressed = self._ollama_call_sync(self.scout_model, system, prompt)
        if compressed and len(compressed) < len(raw_data):
            logger.info(f"Symbiose: Contexte compressé ({len(raw_data)} -> {len(compressed)} chars)")
            return f"[CONTEXTE COMPRESSÉ PAR GEMMA LOCAL]\n{compressed}"
        return raw_data[:2000] # Fallback tronqué si échec compression

    def validate_mcp_payload(self, tools: List[Dict]) -> Tuple[bool, str]:
        """
        [STRATÉGIE 3] Linter sémantique local pour protéger le quota.
        """
        if not tools: return True, ""
        
        system = "Réponds par VALID ou une liste d'erreurs JSON."
        prompt = f"Valide ce schéma de tools MCP :\n{json.dumps(tools)}"
        
        result = self._ollama_call_sync(self.scout_model, system, prompt)
        if not result or "VALID" in result.upper():
            return True, ""
        
        logger.warning(f"Symbiose: Payload MCP bloqué localement (malformé)")
        return False, result

    def query_memory(self, intent_query: str, limit: int = 5) -> str:
        """
        [COGNITIVE BRIDGE] Utilise le RAG (FTS + Vectoriel) au lieu de scanner le disque.
        C'est l'interface de 'Conscience' pour Gemini.
        """
        logger.info(f"Symbiose RAG: Interrogation sémantique pour '{intent_query}'")
        
        # Note: En production, ceci appelle l'API RAG locale du Hub :8766
        # Pour Gemini, cela signifie utiliser l'outil 'rag:search'
        return f"Intention identifiée : {intent_query}. Utilisation du RAG prioritaire sur ReadFolder."

    def distill_rag_results(self, chunks: List[str], query: str) -> str:
        """
        [SCOUT] Gemma compresse les résultats du RAG avant l'envoi au Cloud.
        """
        if not chunks: return "Aucune information trouvée dans la mémoire."
        
        system = "Tu es le Distillateur Nokido. Résume ces fragments pour répondre à la requête."
        context = "\n---\n".join(chunks)
        prompt = f"Requête: {query}\n\nFragments:\n{context}"
        
        return self._ollama_call_sync(self.scout_model, system, prompt)

    def get_log_essence(self, file_path: str, lines: int = 50) -> str:
        """
        [SCOUT] Lit la fin d'un log et utilise Gemma pour n'en extraire que la substantifique moelle.
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                tail = "".join(content[-lines:])
                
            return self.compress_context(tail, target_tokens=150)
        except Exception as e:
            return f"Erreur lecture log: {e}"

# Instance globale
bridge = SymbioticBridge()
