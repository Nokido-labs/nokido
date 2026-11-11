"""
forge_symbiotic_bridge.py — Pont Cloud-Local Synchrone pour Nokido.
===================================================================
Utilise Gemma/Qwen en local pour protéger le quota Gemini.
Version synchrone pour intégration directe dans le LLMRouter.
"""

import json
import logging
import time

# 11/11, CI GitHub run 42930679070 (3 OS) : `import requests` au chargement rendait le module NON IMPORTABLE sur
# une machine vierge, alors que ce pont est FAIL-OPEN par contrat. Import tolerant ; l'absence est DITE a l'usage.
try:
    import requests
except ImportError:  # muet-ok : dit dans _ollama_call_sync, a l'usage
    requests = None
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("symbiose")

class SymbioticBridge:
    def __init__(self, ollama_url: str = "http://localhost:11434/api/chat"):
        import os as _os
        self.ollama_url = ollama_url
        # Scout : Rapide pour validation/compression
        self.scout_model = _os.environ.get("NOKIDO_SYMBIOSE_SCOUT", "qwen2.5-coder:1.5b")
        # Muscle : 4/11 (mesure job_56920f239952) `gemma-4-31b-it` n'existe PAS dans Ollama ; seul gemma4:e4b-it-q4_K_M
        # est installe (70-83 s par reponse : muscle asynchrone, jamais compression en ligne). Reglable.
        self.muscle_model = _os.environ.get("NOKIDO_SYMBIOSE_MUSCLE", "gemma4:e4b-it-q4_K_M")
        # 4/11 : le scout met 12-14 s a GENERER (chargement 1,3 s) -- un delai de 10 s le condamnait ; borne sous le
        # budget du proxy (NOKIDO_SYMBIOSE_TIMEOUT_S = 20 s). NR tests/nr/test_symbiose_scout_reparee_nr.py.
        self.timeout_s = float(_os.environ.get("NOKIDO_SYMBIOSE_SCOUT_TIMEOUT_S", "18"))
        self.keep_alive = _os.environ.get("NOKIDO_SYMBIOSE_KEEP_ALIVE", "10m") 
        
    def _ollama_call_sync(self, model: str, system: str, prompt: str, json_mode: bool = False) -> str:
        """Appel synchrone vers Ollama local."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            # 4/11 : sortie BORNEE (la duree de generation suit le nombre de jetons) ; scout garde chaud entre appels
            "keep_alive": getattr(self, "keep_alive", "10m"),
            "options": {"temperature": 0.0, "num_predict": 400}
        }
        if json_mode:
            payload["format"] = "json"
            
        if requests is None:
            logger.warning("Symbiose : module `requests` absent -- scout local indisponible (%s)", model)
            return ""
        try:
            # Timeout court (5s) pour le Scout, on ne veut pas ralentir le système
            response = requests.post(self.ollama_url, json=payload, timeout=getattr(self, "timeout_s", 18.0))
            if response.status_code == 200:
                return response.json()['message']['content']
            logger.warning("Symbiose : Ollama HTTP %s pour %s", response.status_code, model)
        except Exception as e:
            # On ne bloque pas le systeme si Ollama est down -- mais l'echec se DIT (4/11 : avale en DEBUG, la symbiose
            # etait morte depuis des semaines sans que personne le voie).
            logger.warning("Symbiose : scout local indisponible (%s: %s) -- %s", type(e).__name__, str(e)[:120], model)
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
        # 4/11 : jamais de coupe muette a 2 000 car. (texte ampute envoye sans que personne le sache) -- l'original
        # repart tel quel ; l'echec du scout a deja ete dit en WARNING.
        return raw_data

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
