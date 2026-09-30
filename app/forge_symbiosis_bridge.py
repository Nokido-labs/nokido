import requests
import json
from nokido_agent.app.forge_resource_manager import ResourceManager
from nokido_agent.app.forge_persona_engine import PersonaEngine

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


class SymbiosisBridge:
    def __init__(self):
        self.rm = ResourceManager()
        self.pe = PersonaEngine()
        self.ollama_url = "http://127.0.0.1:11434/api/chat"

    def local_preflight(self, prompt):
        """Utilise un modèle local (Gemma/Mistral) pour analyser l'intention."""
        if not self.rm.is_port_open(11434):
            return {"complexity": "unknown", "reason": "Ollama offline"}

        try:
            payload = {
                "model": "gemma",  # ou mistral
                "messages": [
                    {
                        "role": "system",
                        "content": "Analyse la complexité de la tâche. Réponds uniquement par LOW ou HIGH.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            }
            # Timeout court pour ne pas bloquer
            response = requests.post(self.ollama_url, json=payload, timeout=5)
            result = response.json()["message"]["content"].strip()
            return {"complexity": "high" if "HIGH" in result.upper() else "low"}
        except:
            return {"complexity": "low", "reason": "Error during preflight"}

    def cloud_execution(self, prompt, context=""):
        """Appel Gemini Pro (via API ou Proxy)."""
        # Ici on simulerait l'appel au modèle Pro
        print("☁️ Appel Gemini Pro avec contexte enrichi...")
        return "[Résultat Gemini Pro]"

    def symbiotic_call(self, prompt):
        print(f"🔍 Début du cycle symbiotique pour : {prompt[:50]}...")

        # 1. Évaluation locale
        preflight = self.local_preflight(prompt)
        print(f"⚖️ Pré-vol local : {preflight}")

        if preflight["complexity"] == "low":
            print("⚡ Exécution directe sur Flash-Lite (Économie).")
            # Appel Flash-Lite
        else:
            print("🧠 Escalade sur Gemini Pro (Qualité).")
            # Appel Gemini Pro

        return "Cycle terminé."


if __name__ == "__main__":
    bridge = SymbiosisBridge()
    # On ne lance pas d'appel réel sans Ollama actif, mais la structure est là.
    print(bridge.symbiotic_call("Comment refactoriser le coeur de Nokido ?"))
