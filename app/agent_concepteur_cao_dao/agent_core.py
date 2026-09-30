# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Concepteur CAO/DAO.
    Branche : Ingénierie Industrielle, Production & Logistique
    Discipline : Conception & Mécanique
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent Concepteur CAO/DAO spécialisé dans la discipline 'Conception & Mécanique', "
            "faisant partie de la branche 'Ingénierie Industrielle, Production & Logistique'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent Concepteur CAO/DAO...")

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
            "specialty": "Agent Concepteur CAO/DAO",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
