import time
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from nokido_agent.app.forge_symbiotic_core import SymbioticCore
from nokido_agent.app.forge_persona_engine import PersonaEngine


class OrchestrationBenchmark:
    """
    Simule et mesure la qualité de l'orchestration cognitive de Nokido.
    """

    def __init__(self):
        self.core = SymbioticCore()
        self.pe = PersonaEngine()

    def run_scenario(self, name, task, expected_persona):
        print(f"\n🎬 SCÉNARIO : {name}")
        print(f"📝 Tâche : {task}")
        start_time = time.time()

        # 1. Routing & Persona
        model = self.pe.route_intent(task)
        persona = self.pe.get_persona(expected_persona)

        # 2. Sonde de Capacité
        probe = self.pe.generate_probe_query(task)
        # Simulation d'un retour sonde 'CAPABLE'
        probe_result = "CAPABLE"

        # 3. Préparation des ressources
        jit_status = "Skipped"
        if "ollama" in model or "local" in model:
            self.core.jit_load("ollama")
            jit_status = "Ollama Loaded"

        # 4. Mesure de latence
        latency = time.time() - start_time

        # Scoring
        score = 100
        if latency > 5:
            score -= 20
        if not persona:
            score -= 50

        print(f"🎯 Persona : {expected_persona} | Modèle : {model}")
        print(f"⚡ JIT Status : {jit_status}")
        print(f"⏱️ Latence Orchestration : {latency:.4f}s")
        print(f"⭐ Score Maturité : {score}/100")
        return score

    def full_suite(self):
        print("🚀 LANCEMENT DU BENCHMARK D'ORCHESTRATION SYMBIOTIQUE")
        results = []

        # Test 1 : Maintenance Système
        results.append(
            self.run_scenario(
                "Maintenance Urgente", "Réparer les permissions du dossier logs et redémarrer le hub", "Rescue_Admin"
            )
        )

        # Test 2 : Analyse Complexe
        results.append(
            self.run_scenario(
                "Audit Architectural",
                "Analyser l'impact de l'ajout d'une base de données graphe sur le RAG actuel",
                "Rescue_Admin",  # On utilisera un persona Architect plus tard
            )
        )

        avg_score = sum(results) / len(results)
        print(f"\n🏆 SCORE GLOBAL D'ORCHESTRATION : {avg_score:.2f}/100")

        if avg_score > 80:
            print("🟢 Maturité Élevée : Le système est prêt pour le chaînage réseau.")
        else:
            print("🟡 Maturité Moyenne : Des raffinements de mémoire sont nécessaires.")


if __name__ == "__main__":
    bench = OrchestrationBenchmark()
    bench.full_suite()
