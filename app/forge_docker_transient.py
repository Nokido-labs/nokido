"""
forge_docker_transient.py — Transient Daemon Sandbox (Architecture V16)
=======================================================================
Implémente le pattern "Daemon + Exec" pour les boucles darwiniennes MCTS.
- Zéro cold start : Le conteneur est "warm" (sleep infinity).
- Zéro zombie : Utilisation de --init (tini) au boot.
- Zéro fuite de sous-processus : Utilisation de `setsid` + `timeout` dans le conteneur.
- I/O natif : Utilisation exclusive de Named Volumes (bypass gRPC-FUSE sur Windows).

Design validé par le Swarm Nokido (Claude Opus + Gemini) le 2026-06-15.
"""
import logging
import subprocess
import time
import os
from typing import Tuple, Dict, Any

logger = logging.getLogger("Nokido.Transient")

class TransientEnv:
    def __init__(self, name: str, workspace_vol: str, image: str = "python:3.11-slim"):
        self.name = name
        self.workspace_vol = workspace_vol
        self.image = image

    def _ensure_docker_running(self) -> bool:
        """Vérifie si Docker tourne, sinon tente de démarrer Docker Desktop sous Windows."""
        if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
            return True
            
        logger.info("Docker API injoignable. Tentative de démarrage de Docker Desktop...")
        docker_path = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if not os.path.exists(docker_path):
            logger.error(f"Docker Desktop introuvable à {docker_path}")
            return False
            
        # Lancement en arrière-plan (non-bloquant)
        subprocess.Popen([docker_path])
        
        # Polling : on attend que l'API réponde (max ~60s)
        logger.info("Attente de l'initialisation du moteur Docker...")
        for _ in range(30):
            time.sleep(2)
            if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
                logger.info("Moteur Docker prêt !")
                return True
                
        logger.error("Délai d'attente dépassé pour le démarrage de Docker.")
        return False

    def boot(self) -> bool:
        """Démarre le daemon transient. Crée le volume s'il n'existe pas."""
        if not self._ensure_docker_running():
            return False

        logger.info(f"Booting transient daemon: {self.name}")
        # Création du named volume (best-effort, permet une isolation stricte des I/O)
        subprocess.run(["docker", "volume", "create", self.workspace_vol], capture_output=True)

        cmd = [
            "docker", "run", "-d", "--rm", "--init",
            "--name", self.name,
            "-v", f"{self.workspace_vol}:/workspace",
            "-w", "/workspace",
            self.image,
            "sleep", "infinity"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        
        if res.returncode != 0:
            # Si le conteneur existe déjà (ex: crash précédent sans kill), on vérifie son statut
            check = subprocess.run(["docker", "ps", "-q", "-f", f"name={self.name}"], capture_output=True, text=True, errors="replace")
            if not check.stdout.strip():
                logger.error(f"Failed to boot transient: {res.stderr}")
                return False
        
        # Attente warm-up
        time.sleep(0.5)
        # Injection des outils de base dans l'image alpine/slim si manquants (ex: procps pour les tests)
        subprocess.run(["docker", "exec", self.name, "apt-get", "update"], capture_output=True)
        subprocess.run(["docker", "exec", self.name, "apt-get", "install", "-y", "procps"], capture_output=True)

        return True

    def fast_exec(self, command: str, timeout_s: int = 10) -> Dict[str, Any]:
        """Exécute une commande dans le transient via docker exec.
        Utilise un wrapper Python pour créer un Process Group (setsid) et tuer
        atomiquement toute l'arborescence (os.killpg) en cas de timeout."""
        host_timeout = timeout_s + 2
        
        # Wrapper Python injecté inline : la seule façon robuste d'éradiquer
        # un sous-processus et ses enfants (fork-bombs) de l'intérieur.
        py_wrapper = f"""import subprocess, sys, os, signal
try:
    p = subprocess.Popen({repr(command)}, shell=True, start_new_session=True)
    p.wait(timeout={timeout_s})
    sys.exit(p.returncode)
except subprocess.TimeoutExpired:
    os.killpg(p.pid, signal.SIGKILL)
    sys.exit(124)
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(1)
"""
        cmd = [
            "docker", "exec", self.name,
            "python", "-c", py_wrapper
        ]
        
        t0 = time.monotonic()
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=host_timeout, encoding='utf-8', errors='replace')
            latency = time.monotonic() - t0
            
            # Code 124 = process arrêté par le timeout interne
            timed_out = (res.returncode == 124)
                
            return {
                "ok": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "timed_out": timed_out,
                "latency_s": latency
            }
        except subprocess.TimeoutExpired:
            # La commande `docker exec` côté hôte a figé
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Host docker exec timeout after {host_timeout}s",
                "exit_code": -1,
                "timed_out": True,
                "latency_s": time.monotonic() - t0
            }
        except Exception as e:
            return {
                "ok": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "timed_out": False,
                "latency_s": time.monotonic() - t0
            }

    def put_file(self, content: str, dest_filename: str) -> bool:
        """Injecte un fichier dans le workspace du transient en bypassant le bind mount."""
        cmd = ["docker", "exec", "-i", self.name, "sh", "-c", f"cat > /workspace/{dest_filename}"]
        res = subprocess.run(cmd, input=content, text=True, capture_output=True, encoding='utf-8', errors="replace")
        return res.returncode == 0
        
    def get_file(self, filename: str) -> str:
        """Récupère le contenu d'un fichier généré dans le named volume."""
        cmd = ["docker", "exec", self.name, "cat", f"/workspace/{filename}"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors="replace")
        return res.stdout

    def terminate(self, force: bool = False) -> None:
        """Détruit le transient proprement ou de force."""
        action = "kill" if force else "stop"
        subprocess.run(["docker", action, self.name], capture_output=True)

    @staticmethod
    def panic_purge() -> None:
        """Bouton rouge : détruit tous les conteneurs transients.
        À câbler dans le forge_service_watchdog ou en cas d'OOM."""
        try:
            res = subprocess.run(["docker", "ps", "-a", "-q", "-f", "name=transient-"], capture_output=True, text=True, errors="replace")
            pids = res.stdout.strip().split()
            if pids:
                subprocess.run(["docker", "rm", "-f"] + pids, capture_output=True)
                logger.info(f"Panic purge completed: {len(pids)} transients destroyed.")
        except Exception as e:
            logger.error(f"Panic purge fallback failed: {e}")

if __name__ == "__main__":
    print("=== Test Transient Daemon (Nokido V16) ===")
    env = TransientEnv("transient-test-01", "vol_test_mcts")
    env.panic_purge()  # Nettoyage initial
    
    if env.boot():
        print("[+] 1. Booted (warm state achieved)")
        
        env.put_file("print('Hello from transient! I/O isolated.')", "test.py")
        
        print("[+] 2. Testing fast execution (< 100ms)...")
        res = env.fast_exec("python test.py")
        print(f"    Exit: {res['exit_code']} | Latency: {res['latency_s']:.2f}s | Out: {res['stdout'].strip()}")
        
        print("[+] 3. Testing fork-bomb / infinite loop isolation...")
        # Ce code spawn un worker CPU infini en arrière-plan puis boucle
        bad_code = """
import subprocess, sys
# Processus petit-enfant malveillant
subprocess.Popen([sys.executable, '-c', 'while True: pass'])
# Processus enfant malveillant
while True: pass
"""
        env.put_file(bad_code, "bad.py")
        
        print("    Running bad.py (expected timeout 3s)...")
        res = env.fast_exec("python bad.py", timeout_s=3)
        print(f"    Exit: {res['exit_code']} (Timeout={res['timed_out']})")
        
        # Preuve par l'image : vérifions la table des processus du conteneur
        print("[+] 4. Verifying PID reaping (Zero Zombies/Orphans)...")
        res_ps = env.fast_exec("ps aux")
        lines = res_ps['stdout'].strip().split('\\n')
        for line in lines:
            if "python" in line or "sleep" in line:
                print(f"    {line}")
        if "bad.py" not in res_ps['stdout']:
            print("    => SUCCESS: The fork-bomb was completely eradicated by setsid+tini.")
        else:
            print("    => FAILURE: Orphans detected in the process table!")
        
        env.terminate(force=True)
        print("[+] 5. Terminated. System clean.")
