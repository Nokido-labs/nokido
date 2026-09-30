# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Criminologue.
    Branche : Droit, Administration & Sécurité Publique
    Discipline : Sécurité Publique, Défense & Renseignement
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent Criminologue spécialisé dans la discipline 'Sécurité Publique, Défense & Renseignement', "
            "faisant partie de la branche 'Droit, Administration & Sécurité Publique'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent Criminologue...")

    def get_tools(self):
        """
        Returns a list of methods that should be exposed as tools.
        """
        return {
            "ping": self.ping,
            "get_capabilities": self.get_capabilities,
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
            "specialty": "Agent Criminologue",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
