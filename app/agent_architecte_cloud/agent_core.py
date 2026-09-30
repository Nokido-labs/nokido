# agent_core.py

class AgentCore:
    """
    Cœur logique de l'Agent Architecte Cloud.
    Expert en AWS, Azure, GCP, et infrastructure as code (Terraform, Pulumi).
    """
    def __init__(self):
        # Spécialisation du system prompt et de la base de connaissances
        self.system_prompt = (
            "Tu es un Agent Architecte Cloud de la branche 'Ingénierie & Technologies de l'Information (IT)'. "
            "Ton rôle est de concevoir des architectures résilientes, scalables et sécurisées "
            "(AWS, GCP, Azure, Kubernetes, Terraform)."
        )
        print(f"[{self.__class__.__name__}] Initialisation avec spécialité Cloud Architecture...")

    def get_tools(self):
        """
        Retourne la liste des méthodes exposées en tant qu'outils MCP.
        """
        return {
            "ping": self.ping,
            "get_capabilities": self.get_capabilities,
            "analyze_infrastructure": self.analyze_infrastructure,
            "generate_iac_stub": self.generate_iac_stub,
        }

    def ping(self, value: str = "pong") -> str:
        """Outil de test de vie de l'agent."""
        return f"Architecte Cloud répond : {value}"

    def get_capabilities(self):
        """Retourne les capacités et la spécialité de cet agent."""
        return {
            "protocol": "mcp",
            "version": "0.1.0",
            "specialty": "Cloud Architecture & Infrastructure as Code",
            "tools": list(self.get_tools().keys())
        }

    def analyze_infrastructure(self, provider: str, requirements: str) -> dict:
        """
        Analyse des prérequis et proposition d'une architecture cloud adaptée.
        """
        # Dans un agent complet, ici on appellerait le LLM local (via le hub Nokido)
        # pour raisonner sur l'architecture avec le system_prompt de l'architecte.
        return {
            "status": "success",
            "provider": provider,
            "recommendation": f"Ébauche d'architecture pour {provider} basée sur : {requirements}. "
                              f"Utilisation de clusters managés et réseaux privés virtuels recommandée."
        }

    def generate_iac_stub(self, resource_type: str, provider: str = "aws") -> dict:
        """
        Génère un squelette de code Terraform pour une ressource donnée.
        """
        code_stub = ""
        if provider.lower() == "aws" and resource_type.lower() == "vpc":
            code_stub = '''
resource "aws_vpc" "main" {
  cidr_block       = "localhost/16"
  instance_tenancy = "default"

  tags = {
    Name = "main-vpc"
  }
}'''
        else:
            code_stub = f"# Squelette Terraform non défini pour {resource_type} sur {provider}."

        return {
            "status": "success",
            "tool": "terraform",
            "code": code_stub.strip()
        }
