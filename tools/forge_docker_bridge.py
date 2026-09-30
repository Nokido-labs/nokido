"""
forge_docker_bridge.py — Bridge Docker natif pour Nokido MCP
==============================================================
Remplace tous les subprocess.run(['docker','exec',...]) par des appels
SDK Docker directs. Plus rapide, pas de sérialisation shell, pas de timeout.

Usage interne Nokido uniquement — pas exposé comme MCP externe.

Architecture:
  Nokido MCP server (Python)
    └→ forge_docker_bridge.DockerBridge
        └→ docker.from_env() (socket Unix/Named Pipe)
            └→ Docker daemon
                └→ exegol-nokido container
"""

import logging
import time

import docker

log = logging.getLogger("Nokido.docker")

CONTAINER_NAME = "exegol-laforge"
EXEC_TIMEOUT = 60  # secondes par défaut
BUFFER_LIMIT = 8000  # chars max retournés


class DockerBridge:
    """Bridge direct vers le container Exegol via Docker SDK."""

    _instance = None
    _client = None
    _container = None

    @classmethod
    def get(cls) -> "DockerBridge":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._client = None
        self._container = None

    @property
    def client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    @property
    def container(self):
        """Récupère le container, le redémarre si arrêté."""
        if self._container is None:
            try:
                self._container = self.client.containers.get(CONTAINER_NAME)
            except docker.errors.NotFound:
                raise RuntimeError(f"Container {CONTAINER_NAME} introuvable")

        if self._container.status != "running":
            log.info(f"Container {CONTAINER_NAME} arrêté, redémarrage...")
            self._container.start()
            time.sleep(2)
            self._container.reload()

        return self._container

    def exec_run(
        self,
        cmd: str,
        timeout: int = EXEC_TIMEOUT,
        workdir: str = None,
        env: dict = None,
    ) -> tuple[str, int]:
        """
        Exécute une commande dans le container.
        Retourne (stdout+stderr, exit_code).
        Plus rapide que subprocess docker exec.
        """
        t0 = time.time()
        try:
            env_list = [f"{k}={v}" for k, v in (env or {}).items()]
            env_list.append("TERM=xterm")

            result = self.container.exec_run(
                ["bash", "-c", cmd],
                workdir=workdir or "/workspace",
                environment=env_list,
                demux=False,
            )

            output = result.output.decode("utf-8", errors="replace")
            exit_code = result.exit_code
            dt = time.time() - t0

            # Tronquer si trop long
            if len(output) > BUFFER_LIMIT:
                output = output[:BUFFER_LIMIT] + f"\n... [tronqué à {BUFFER_LIMIT} chars]"

            log.debug(f"exec({cmd[:40]}...) → {exit_code} ({dt:.1f}s, {len(output)} chars)")
            return output, exit_code

        except Exception as e:
            dt = time.time() - t0
            log.error(f"exec failed after {dt:.1f}s: {e}")
            return str(e), -1

    def exec_async(self, cmd: str, workdir: str = None) -> str:
        """
        Lance une commande en background dans le container.
        Retourne le exec_id pour polling.
        """
        try:
            env_list = ["TERM=xterm"]
            exec_id = self.client.api.exec_create(
                self.container.id,
                ["bash", "-c", f"nohup {cmd} &"],
                workdir=workdir or "/workspace",
                environment=env_list,
            )
            self.client.api.exec_start(exec_id, detach=True)
            return exec_id["Id"]
        except Exception as e:
            return f"ERROR: {e}"

    def put_file(self, local_path: str, container_path: str):
        """Copie un fichier local dans le container."""
        import io
        import os
        import tarfile

        # Créer un tar en mémoire
        data = open(local_path, "rb").read()
        filename = os.path.basename(container_path)
        dest_dir = os.path.dirname(container_path)

        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        tar_stream.seek(0)

        self.container.put_archive(dest_dir, tar_stream)

    def get_file(self, container_path: str) -> bytes:
        """Récupère un fichier du container."""
        import io
        import tarfile

        bits, stat = self.container.get_archive(container_path)
        tar_stream = io.BytesIO(b"".join(bits))
        with tarfile.open(fileobj=tar_stream) as tar:
            member = tar.getmembers()[0]
            f = tar.extractfile(member)
            return f.read() if f else b""

    def is_alive(self) -> bool:
        """Vérifie si le container est vivant."""
        try:
            self.container.reload()
            return self.container.status == "running"
        except Exception:
            return False

    def ensure_running(self):
        """S'assure que le container tourne."""
        if not self.is_alive():
            try:
                c = self.client.containers.get(CONTAINER_NAME)
                c.start()
                time.sleep(2)
                self._container = c
            except Exception as e:
                raise RuntimeError(f"Impossible de démarrer {CONTAINER_NAME}: {e}")


# ── Fonctions raccourcies pour Nokido MCP ──


def exeg(cmd: str, timeout: int = 60, cwd: str = None) -> str:
    """Raccourci: exécute dans Exegol, retourne stdout."""
    bridge = DockerBridge.get()
    output, rc = bridge.exec_run(cmd, timeout=timeout, workdir=cwd)
    return output


def exeg_async(cmd: str, cwd: str = None) -> str:
    """Raccourci: lance en background dans Exegol."""
    bridge = DockerBridge.get()
    return bridge.exec_async(cmd, workdir=cwd)


def deploy_file(local_path: str, container_path: str):
    """Raccourci: copie un fichier dans Exegol."""
    bridge = DockerBridge.get()
    bridge.put_file(local_path, container_path)


def fetch_file(container_path: str) -> bytes:
    """Raccourci: récupère un fichier depuis Exegol."""
    bridge = DockerBridge.get()
    return bridge.get_file(container_path)
