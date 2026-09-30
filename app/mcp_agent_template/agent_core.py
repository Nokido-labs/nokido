# agent_core.py

class AgentCore:
    """
    The core logic of the specialized agent.
    This class will be instantiated and its methods will be exposed as tools
    by the MCP server.
    """
    def __init__(self):
        # Here you can initialize any resources the agent needs,
        # like database connections, models, etc.
        print("Initializing AgentCore...")

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
            "version": "0.1.0",
            "tools": list(self.get_tools().keys())
        }
