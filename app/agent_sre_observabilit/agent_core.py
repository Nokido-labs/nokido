# agent_core.py

import urllib.request
import json

class AgentCore:
    """
    Cœur logique de l'Agent SRE & Observabilité.
    Branche : 01. Ingénierie & Technologies de l'Information (IT)
    Discipline : Supervision & Orchestration de l'Essaim
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent SRE & Observabilité spécialisé dans la discipline 'Supervision & Orchestration de l'Essaim', "
            "faisant partie de la branche '01. Ingénierie & Technologies de l'Information (IT)'. "
            "Ton rôle est de centraliser l'information, de surveiller la santé des ressources système (CPU, RAM), "
            "l'état des agents, et d'assurer la synchronisation globale des tâches au sein de l'architecture Nokido. "
            "Tu es invoqué directement par l'orchestrateur pour débloquer des situations ou fournir une analyse systémique."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent SRE & Observabilité...")

    def get_tools(self):
        """
        Returns a list of methods that should be exposed as tools.
        """
        return {
            "ping": self.ping,
            "get_capabilities": self.get_capabilities,
            "get_system_health": self.get_system_health,
            "get_active_services": self.get_active_services,
            "analyze_bottlenecks": self.analyze_bottlenecks
        }

    def ping(self, value: str = "pong") -> str:
        """
        A simple tool that returns a value.
        Useful for checking if the agent is alive.
        """
        return value

    def get_capabilities(self):
        """
        Returns the list of available tools.
        """
        return {
            "protocol": "mcp",
            "specialty": "Agent SRE & Observabilité",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }

    def _fetch_hub_api(self, path: str) -> dict:
        """Utilitaire pour appeler l'API du Hub Nokido localement."""
        try:
            # 2026-09-24 : la topologie exige une identite d'organe prouvee (jamais le maitre).
            try:
                from nokido_agent.app.forge_hub_client import entetes_organe

                entetes = entetes_organe("SRE")
            except Exception:  # noqa: BLE001 -- sans porteur, le hub rend 401 : visible
                entetes = {}
            req = urllib.request.Request(f"http://127.0.0.1:8766{path}", headers=entetes)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"error": str(e)}

    def get_system_health(self) -> dict:
        """
        Récupère l'état global des ressources (RAM, CPU, GPU) via le Hub Nokido.
        Utilise l'endpoint /api/resource/state.
        """
        return self._fetch_hub_api("/api/resource/state")

    def get_active_services(self) -> dict:
        """
        Récupère la liste des services (agents) et leur statut (running, sleeping).
        Utilise l'endpoint /api/services/list.
        """
        return self._fetch_hub_api("/api/services/list")

    def analyze_bottlenecks(self) -> dict:
        """
        Outil d'analyse heuristique pour le LLM. 
        Combine la santé du swarm et les tâches en cours pour identifier d'éventuels blocages.
        """
        health = self._fetch_hub_api("/api/swarm/health")
        loops = self._fetch_hub_api("/api/loops/status")
        return {
            "swarm_health": health,
            "autonomous_loops": loops,
            "analysis_hint": "Utilise ces données pour identifier si un agent sature (CPU/RAM) ou si une boucle autonome tourne à vide."
        }
