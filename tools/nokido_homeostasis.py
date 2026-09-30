import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from nokido_agent.app.forge_renal_clearance import RenalClearance
from nokido_agent.app.forge_symbiotic_core import SymbioticCore


def main():
    print("🧬 Nokido Homeostasis Daemon starting...")
    core = SymbioticCore()
    renal = RenalClearance()

    last_clearance = 0

    while True:
        try:
            # 1. Nettoyage des processus morts
            core.cleanup_orphans()

            # 2. Cycle de Clairance Rénale (toutes les 12 heures)
            now = time.time()
            if now - last_clearance > 12 * 3600:
                print("🧬 Cycle de Clairance Rénale en cours...")
                renal.purge_obsolete_bak()
                renal.deduplicate_rag()
                last_clearance = now

            # 2. Gestion de l'inactivité (Idle timeout pour Ollama par exemple)
            # Si Ollama tourne mais n'a pas été utilisé depuis 30 min, on pourrait le couper
            # Pour l'instant on se concentre sur la santé des processus

            # 3. Vérification des ressources critiques
            status = core.rm.check_resources()
            if not status["ollama"]:
                # On ne relance pas auto si pas besoin (JIT), mais on log
                pass

            time.sleep(60)  # Vérification chaque minute
        except KeyboardInterrupt:
            print("Stopping Homeostasis...")
            break
        except Exception as e:
            print(f"Error in Homeostasis loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
