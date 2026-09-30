import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from nokido_agent.app.forge_persona_engine import PersonaEngine
from nokido_agent.app.forge_resource_manager import ResourceManager


class CapabilityBenchmarker:
    def __init__(self):
        self.engine = PersonaEngine()
        self.rm = ResourceManager()

    def run_benchmark(self, model_name, task="Réparer les permissions avec icacls"):
        print(f"\n--- BENCHMARK : {model_name} ---")
        probe = self.engine.generate_probe_query(task)
        print(f"Question de Sonde : {probe}")

        # Ici, dans un vrai run, on appellerait le modèle.
        # Pour le test, on définit la logique de ce que l'on attend.
        print("Note : En attente de la réponse réelle du modèle via le Router.")

    def preflight_report(self):
        res = self.rm.check_resources()
        print("\n--- RAPPORT PRÉ-VOL (PRÉ-REQUIS) ---")
        for k, v in res.items():
            icon = "✅" if v else "❌"
            print(f"{icon} {k.upper()} : {'Actif' if v else 'Inactif'}")

        if not res["ollama"]:
            print("💡 Suggestion : Lancez 'ollama serve' ou utilisez le PersonaEngine pour l'allumage auto.")


if __name__ == "__main__":
    bench = CapabilityBenchmarker()
    bench.preflight_report()
    bench.run_benchmark("Gemini-2.5-Flash-Lite")
