# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent UX/UI Designer.
    Branche : Arts, Création & Communication
    Discipline : Design Visuel & UX
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent UX/UI Designer spécialisé dans la discipline 'Design Visuel & UX', "
            "faisant partie de la branche 'Arts, Création & Communication'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent UX/UI Designer...")

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
            "specialty": "Agent UX/UI Designer",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
