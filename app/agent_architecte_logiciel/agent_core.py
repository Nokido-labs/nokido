# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Architecte Logiciel.
    Branche : Ingénierie & Technologies de l'Information (IT)
    Discipline : Ingénierie Logicielle & Développement
    """
    def __init__(self):
        self.system_prompt = (
            "Tu es un Agent Architecte Logiciel spécialisé dans la discipline 'Ingénierie Logicielle & Développement', "
            "faisant partie de la branche 'Ingénierie & Technologies de l'Information (IT)'. "
            "Ton rôle est d'apporter ton expertise métier précise à l'écosystème Nokido."
        )
        print(f"[{self.__class__.__name__}] Initialisation de l'Agent Architecte Logiciel...")

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
            "specialty": "Agent Architecte Logiciel",
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
