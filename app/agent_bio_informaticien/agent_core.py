# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Bio-informaticien.
    Branche : Sciences Fondamentales & Appliquées
    Discipline : Biologie & Sciences du Vivant
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent Bio-informaticien spécialisé dans la discipline 'Biologie & Sciences du Vivant', "
            "faisant partie de la branche 'Sciences Fondamentales & Appliquées'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent Bio-informaticien...")

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
            "specialty": "Agent Bio-informaticien",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
