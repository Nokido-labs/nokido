import asyncio
from random import choice, sample


# ----- RAG Simulé -----
class RAG:
    async def query(self, prompt):
        # Simule une recherche de documents
        await asyncio.sleep(0.3)
        return [f"Doc about '{prompt}' #{i}" for i in range(1, 4)]


# ----- Agent -----
class Agent:
    def __init__(self, name, role):
        self.name = name
        self.role = role

    async def handle_task(self, task, rag, context=None):
        docs = await rag.query(task)
        # Synthèse simple avec contexte éventuel
        summary = docs[0]
        if context:
            summary += f" | Context: {context}"
        return f"{self.name} ({self.role}) proposes: {summary}"


# ----- Orchestrator -----
class Orchestrator:
    def __init__(self, agents, rag):
        self.agents = agents
        self.rag = rag

    async def run_task(self, task, mode="autonome"):
        if mode == "autonome":
            agent = choice(self.agents)
            result = await agent.handle_task(task, self.rag)
            return result

        elif mode == "collaboration":
            # Tous les agents collaborent
            tasks = [agent.handle_task(task, self.rag) for agent in self.agents]
            results = await asyncio.gather(*tasks)
            # Fusion simple des résultats
            return "\n".join(results)

        elif mode == "comite":
            # Chaque agent propose
            tasks = [agent.handle_task(task, self.rag) for agent in self.agents]
            results = await asyncio.gather(*tasks)
            # Vote pondéré : on simule par longueur de doc ou mot-clé
            votes = {r: r.count("Doc") for r in results}
            best = max(votes, key=votes.get)
            return f"Comité selected: {best}"

        else:
            raise ValueError("Mode inconnu")


# ----- Définition des agents -----
agent_definitions = [
    ("Planner Agent", "Planning"),
    ("Discovery Agent", "Discovery"),
    ("DevOps Agent", "DevOps"),
    ("Network Agent", "Network"),
    ("Security Agent", "Security"),
    ("Log Analysis Agent", "Logs"),
    ("RAG / Knowledge Agent", "Knowledge"),
    ("Action / Execution Agent", "Execution"),
    ("Memory Agent", "Memory"),
    ("Monitoring Agent", "Monitoring"),
    ("Patch Management Agent", "Patch"),
    ("Compliance / Audit Agent", "Compliance"),
    ("Incident Response Agent", "Incident"),
    ("Configuration Backup Agent", "Backup"),
    ("Threat Intelligence Agent", "ThreatIntel"),
    ("Active Directory Agent", "AD"),
    ("Windows Management Agent", "Windows"),
    ("Linux Management Agent", "Linux"),
    ("Switch / Network Device Agent", "NetworkDevice"),
    ("DNS / Pi-hole Agent", "DNS"),
    ("IDS / Zeek Agent", "IDS"),
]

agents = [Agent(name, role) for name, role in agent_definitions]


# ----- Exemple d'utilisation -----
async def main():
    rag = RAG()
    orchestrator = Orchestrator(agents, rag)

    task = "Automate HP BIOS configuration and AD integration"

    print("--- Autonome ---")
    print(await orchestrator.run_task(task, mode="autonome"))

    print("\n--- Collaboration ---")
    print(await orchestrator.run_task(task, mode="collaboration"))

    print("\n--- Comité ---")
    print(await orchestrator.run_task(task, mode="comite"))


asyncio.run(main())
