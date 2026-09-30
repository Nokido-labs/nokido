import asyncio
import ast
import subprocess
import time
from collections import defaultdict
from typing import List


# -------------------- Agents & RAG --------------------
class Agent:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.context = None

    async def execute(self, task, rag):
        # Ici l'agent exécute une tâche. Mock simple
        await asyncio.sleep(0.1)  # simuler durée
        return f"{self.name} exécuté: {task}"


class Planner:
    def __init__(self, agents, rag, llm):
        self.agents = agents
        self.rag = rag
        self.llm = llm

    async def select_agents(self, scores, top_n=3):
        # Retourne les top_n agents selon scores
        sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [agent for agent, score in sorted_agents[:top_n]]


# -------------------- RAG --------------------
class RAG:
    def __init__(self):
        self.documents = []

    async def enrich(self, docs: List[str]):
        self.documents.extend(docs)

    def query(self, prompt: str, k=3):
        return self.documents[-k:]


# -------------------- LLM --------------------
class OllamaLocal:
    async def ask(self, prompt: str) -> str:
        # Simulation de génération code
        return f"# Code généré pour le prompt:\n# {prompt}\nprint('Hello World')"


# -------------------- Analyse statique --------------------
def analyze_code(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError as e:
        print(f"[AST ERROR] {e}")
        return False


# -------------------- Test sandbox --------------------
def run_test(code: str) -> bool:
    try:
        with open("temp_test.py", "w") as f:
            f.write(code)
        result = subprocess.run(["python3", "temp_test.py"], capture_output=True, timeout=3)
        if result.returncode == 0:
            print(result.stdout.decode())
            return True
        else:
            print(result.stderr.decode())
            return False
    except Exception as e:
        print(f"[TEST ERROR] {e}")
        return False


# -------------------- GameChanger 4.0 --------------------
class GameChanger4:
    def __init__(self, planner, rag, terminal_agent, web_agent, llm):
        self.planner = planner
        self.rag = rag
        self.terminal_agent = terminal_agent
        self.web_agent = web_agent
        self.llm = llm
        self.agent_history = defaultdict(list)  # {agent: [{'task', 'duration', 'success'}]}

    async def handle_prompt(self, prompt: str, mode="auto"):
        start = time.time()
        category = await self.classify_prompt(prompt)

        # Sandbox pour commandes risquées
        if any(cmd in prompt for cmd in ["rm ", "del ", "format"]):
            return "[Sandbox] Commande dangereuse détectée, simulation sans exécution"

        # Web → enrich RAG
        if category == "web":
            docs = await self.web_search(prompt)
            await self.rag.enrich(docs)
            return f"[RAG enrichi] {len(docs)} documents web ajoutés."

        # Python / chat → génération code
        if category in ["python", "chat"]:
            code = await self.generate_code(prompt)
            if not analyze_code(code):
                return "[FAIL] Code syntaxiquement invalide"
            success = run_test(code)
            return f"[{'PASS' if success else 'FAIL'}] Code généré et testé."

        # Terminal
        if category == "terminal":
            result = await self.terminal_agent.execute(prompt, self.rag)
            return result

        # Infra → Planner
        if category == "infra":
            return await self._execute_infra_task(prompt, mode)

        # Fallback
        return "\n".join(self.rag.query(prompt, k=3))

    # ---------------- Classification mock ----------------
    async def classify_prompt(self, prompt):
        prompt_lower = prompt.lower()
        if any(x in prompt_lower for x in ["ls", "cd", "mkdir"]):
            return "terminal"
        if any(x in prompt_lower for x in ["python", "fonction", "asyncio"]):
            return "python"
        if any(x in prompt_lower for x in ["bios", "update", "ad", "windows", "linux"]):
            return "infra"
        return "web"

    # ---------------- Génération code ----------------
    async def generate_code(self, prompt):
        context_docs = self.rag.query(prompt)
        prompt_with_context = prompt + "\n# Contexte:\n" + "\n".join(context_docs)
        code = await self.llm.ask(prompt_with_context)
        return code

    # ---------------- Recherche web mock ----------------
    async def web_search(self, prompt):
        await asyncio.sleep(0.1)  # simuler recherche
        return [f"Doc web simulée pour: {prompt}"]

    # ---------------- Infra execution ----------------
    async def _execute_infra_task(self, task, mode="collaboration"):
        # Score adaptatif avec prédiction performance (mock)
        scores = {agent: 0.5 for agent in self.planner.agents}
        selected_agents = await self.planner.select_agents(scores, top_n=3)
        tasks = [agent.execute(task, self.rag) for agent in selected_agents]
        results = await asyncio.gather(*tasks)
        return "\n".join(results)


# -------------------- Exemple d'utilisation --------------------
async def main():
    # Init agents & planner
    agents = [Agent(f"Agent{i}", f"Role{i}") for i in range(1, 6)]
    rag = RAG()
    llm = OllamaLocal()
    planner = Planner(agents, rag, llm)
    terminal_agent = Agent("Terminal Agent", "Execution")
    web_agent = Agent("Web Agent", "Web")
    game = GameChanger4(planner, rag, terminal_agent, web_agent, llm)

    # Enrichir RAG initial
    await rag.enrich(["Exemple fonction addition", "Doc asyncio gather"])

    prompts = [
        "Créer une fonction Python qui additionne deux nombres",
        "Mettre à jour BIOS HP et AD sur tous les postes",
        "ls -la dans mon dossier utilisateur",
        "Comment utiliser asyncio.gather en Python ?",
    ]

    for p in prompts:
        result = await game.handle_prompt(p)
        print(f"\nPrompt: {p}\nResult:\n{result}")


asyncio.run(main())
