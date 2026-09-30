import asyncio
from ollama import Ollama  # Hypothétique interface Ollama local
from typing import List


# ----- RAG Simulé -----
class RAG:
    async def query(self, prompt: str) -> List[str]:
        await asyncio.sleep(0.2)  # simulate retrieval
        return [f"Doc about '{prompt}' #{i}" for i in range(1, 4)]


# ----- Agent -----
class Agent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.context = ""

    async def execute(self, task: str, rag: RAG) -> str:
        # Ajouter contexte
        docs = await rag.query(task)
        context = " | ".join(docs + ([self.context] if self.context else []))
        result = f"{self.name} ({self.role}) executes: {context}"
        return result


# ----- Planner / Orchestrator -----
class Planner:
    def __init__(self, agents: List[Agent], rag: RAG, ollama: Ollama):
        self.agents = agents
        self.rag = rag
        self.ollama = ollama

    async def score_agents(self, task: str) -> dict:
        """Scoring dynamique avec Ollama local pour pertinence"""
        scores = {}
        for agent in self.agents:
            prompt = f"Score this agent for the task: {task}\nAgent role: {agent.role}"
            score_response = await self.ollama.ask(prompt)  # retourne un float 0-1
            try:
                score = float(score_response)
            except:
                score = 0.0
            scores[agent] = score
        return scores

    async def select_agents(self, scores: dict, top_n: int = 5) -> List[Agent]:
        sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [agent for agent, score in sorted_agents[:top_n]]

    async def run_task(self, task: str, mode: str = "autonome") -> str:
        # 1️⃣ Récupérer contexte initial via RAG
        context_docs = await self.rag.query(task)
        context = context_docs[0]

        # 2️⃣ Scoring Ollama pour sélectionner agents pertinents
        scores = await self.score_agents(task)
        selected_agents = await self.select_agents(scores, top_n=5)

        # 3️⃣ Propagation du contexte
        for agent in selected_agents:
            agent.context = context

        # 4️⃣ Exécution selon mode
        if mode == "autonome":
            agent = selected_agents[0]
            return await agent.execute(task, self.rag)

        elif mode == "collaboration":
            tasks = [agent.execute(task, self.rag) for agent in selected_agents]
            results = await asyncio.gather(*tasks)
            return "\n".join(results)

        elif mode == "comite":
            tasks = [agent.execute(task, self.rag) for agent in selected_agents]
            results = await asyncio.gather(*tasks)
            # Vote pondéré : utiliser le score Ollama pour chaque agent
            votes = {r: scores[agent] for agent, r in zip(selected_agents, results)}
            best = max(votes, key=votes.get)
            return f"Comité selected: {best}"

        else:
            raise ValueError("Mode inconnu")


# ----- Définition agents (12 principaux) -----
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
]

agents = [Agent(name, role) for name, role in agent_definitions]


# ----- Exemple d'utilisation -----
async def main():
    rag = RAG()
    ollama = Ollama()  # Connexion au modèle local Ollama
    planner = Planner(agents, rag, ollama)

    task = "Automate HP BIOS update, integrate AD and ensure compliance"

    print("--- Autonome ---")
    print(await planner.run_task(task, mode="autonome"))

    print("\n--- Collaboration ---")
    print(await planner.run_task(task, mode="collaboration"))

    print("\n--- Comité ---")
    print(await planner.run_task(task, mode="comite"))


asyncio.run(main())
