# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Géomaticien / Cartographe (SIG).
    Branche : Sciences Humaines, Sociales & Éducation
    Discipline : Histoire & Géographie
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent Géomaticien / Cartographe (SIG) spécialisé dans la discipline 'Histoire & Géographie', "
            "faisant partie de la branche 'Sciences Humaines, Sociales & Éducation'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent Géomaticien / Cartographe (SIG)...")

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
            "specialty": "Agent Géomaticien / Cartographe (SIG)",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
