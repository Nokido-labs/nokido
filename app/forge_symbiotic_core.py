import os
import json
import time
import subprocess
import psutil
from pathlib import Path
from nokido_agent.app.forge_resource_manager import ResourceManager
from nokido_agent.app.forge_persona_engine import PersonaEngine
from nokido_agent.app.forge_hippocampus import Hippocampus

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


class SymbioticCore:
    # workspace_root = racine du DEPOT, pas son parent : Hippocampus attend deja cette
    # racine-la (son defaut vaut ROOT), et le segment "Nokido" retire ci-dessous visait
    # un dossier absent depuis le cutover du 2026-07-09 — le registre de pids etait
    # donc cherche a cote.
    def __init__(self, workspace_root=str(__import__("pathlib").Path(__file__).resolve().parents[1])):
        self.root = Path(workspace_root)
        self.pid_file = self.root / "sandbox" / "pids" / "registry.json"
        self.rm = ResourceManager()
        self.pe = PersonaEngine()
        self.hippo = Hippocampus(workspace_root)
        self.pids = self._load_pids()

    def end_of_thought_cycle(self, session_dialogue):
        """Phase de 'Sommeil' : consolidation de la mémoire."""
        print("🛌 Cycle de Sommeil : Consolidation de la mémoire...")
        summary = self.hippo.distill_session(session_dialogue)
        self.hippo.consolidate(summary)
        print("✅ Mémoire consolidée dans lessons_learned.md")

    def _load_pids(self):
        if self.pid_file.exists():
            try:
                return json.loads(self.pid_file.read_text())
            except:
                return {}
        return {}

    def _save_pids(self):
        self.pid_file.write_text(json.dumps(self.pids, indent=2))

    def register_pid(self, name, pid):
        self.pids[name] = {"pid": pid, "started_at": time.time(), "status": "running"}
        self._save_pids()

    def cleanup_orphans(self):
        """Vérifie si les processus enregistrés sont toujours vivants."""
        to_remove = []
        for name, info in self.pids.items():
            pid = info["pid"]
            if not psutil.pid_exists(pid):
                to_remove.append(name)
            else:
                try:
                    p = psutil.Process(pid)
                    if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                        to_remove.append(name)
                except:
                    to_remove.append(name)

        for name in to_remove:
            print(f"🧹 Nettoyage du processus orphelin : {name} (PID {self.pids[name]['pid']})")
            del self.pids[name]
        self._save_pids()

    def jit_load(self, resource_name):
        """Charge une ressource Just-In-Time si nécessaire."""
        if resource_name == "ollama":
            if not self.rm.is_port_open(11434):
                print("⚡ JIT: Démarrage d'Ollama...")
                proc = subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
                self.register_pid("ollama", proc.pid)
                # Attente asynchrone simplifiée
                return True
        elif resource_name == "docker":
            if not self.rm.is_docker_running():
                print("🐳 JIT: Docker requis mais non lancé.")
                return False
        return True

    def start_worker(self, worker_script, args=None):
        """Lance un worker en tâche de fond et l'enregistre."""
        args = list(args or [])
        script_path = self.root / "Nokido" / worker_script
        print(f"👷 Lancement du worker : {worker_script}...")
        proc = subprocess.Popen(
            [os.path.expanduser(r"~\miniforge3\python.exe"), str(script_path)] + args,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.register_pid(worker_script, proc.pid)
        return proc.pid

    def execute_symbiotic(self, task, persona_name="Rescue_Admin"):
        """
        Symbiose Gemma + Gemini :
        1. Gemma (Local) : Analyse l'intention et pré-traite le contexte.
        2. Gemini (Cloud) : Exécute si la complexité > Seuil ou si Gemma demande de l'aide.
        """
        # Simulation du chaînage cognitif
        complexity_score = self.pe.route_intent(task)  # Retourne le modèle idéal

        print(f"🧠 Symbiose : Tâche '{task}'")
        if complexity_score == "gemini-2.5-flash-lite":
            print("🟢 Gemma (Local/Lite) est suffisant. Exécution locale.")
            self.jit_load("ollama")
            return {"engine": "local_gemma_lite", "action": "direct_execution"}
        else:
            print("🔴 Complexité détectée. Passage en mode Symbiose (Gemma brief Gemini).")
            # Gemma prépare le terrain (Worker)
            self.start_worker("scripts/nokido_rescue.py")
            return {"engine": "hybrid_symbiosis", "action": "cloud_escalation"}


if __name__ == "__main__":
    core = SymbioticCore()
    core.cleanup_orphans()

    print("\n--- TEST SYMBIOSE Gemma + Gemini ---")
    # Tâche simple
    print("\nTâche Simple :")
    print(core.execute_symbiotic("Lister les fichiers du dossier logs"))

    # Tâche complexe
    print("\nTâche Complexe :")
    print(core.execute_symbiotic("Analyser l'architecture de sécurité et proposer une refactorisation"))

    print(f"\nRegistre des PIDs : {core.pids}")
