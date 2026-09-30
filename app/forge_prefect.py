"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_prefect.py — extrait automatiquement depuis Nokido.py
Généré par shredder.py
"""

from typing import Dict
from typing import List
from typing import Optional
import asyncio
import json
import logging
import sys as _sys

logger = logging.getLogger(__name__)

# Prefect optionnel
try:
    from prefect.task_runners import ConcurrentTaskRunner
    from prefect.client.orchestration import get_client

    HAS_PREFECT = True
except ImportError:
    ConcurrentTaskRunner = None  # type: ignore
    get_client = None  # type: ignore
    HAS_PREFECT = False


def _main() -> object | None:
    """
    Retourne le module __main__ (Nokido.py) pour accder  settings/run_ssh.

    Returns:
        object | None: Le module __main__ s'il est charg, sinon None.
    """
    return _sys.modules.get("__main__")


def _get_settings() -> object:
    """
    Get settings.

    Returns:
        object: Les paramètres.
    """
    m = _main()
    return getattr(m, "settings", None)


def _get_run_ssh() -> object:
    """
    Get run ssh.

    Returns:
        object: La fonction run_ssh.
    """
    m = _main()
    return getattr(m, "run_ssh", None)


def _failure_stats() -> object:
    """
    Failure stats.

    Returns:
        object: Les statistiques d'échec.
    """
    m = _main()
    fs = getattr(m, "failure_stats", None)
    if fs is None:
        fs = {"total_commands": 0, "failed_commands": 0}
        if m:
            m.failure_stats = fs
    return fs


class PrefectManager:
    """
    Orchestrateur de workflows et pipelines CI/CD via SSH.
    Prefect v2 optionnel — fonctionne aussi en mode SSH pur.
    """

    def __init__(self) -> None:
        """
        Init.

        Raises:
            Exception: Si les paramètres ne sont pas configurés correctement.
        """
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        HAS_PREFECT = _ac.HAS_PREFECT
        _s = _get_settings()
        if HAS_PREFECT and ConcurrentTaskRunner is not None and _s:
            self.task_runner = ConcurrentTaskRunner(max_workers=_s.max_concurrent_tasks)
        else:
            self.task_runner = None
        self.logger = logging.getLogger("PrefectManager")
        self.client = None
        self.slack_webhook = _s.slack_webhook_url if _s else None
        # ── Registre des pipelines en cours ──────────────────────────────────
        self._running_pipelines: Dict[str, asyncio.Task] = {}
        self._pipeline_history: List[Dict] = []  # max 50 entrées
        # ── Registre des workflows définis localement ─────────────────────────
        self._custom_workflows: Dict[str, List[str]] = {}  # nom → liste de commandes

    async def start(self) -> None:
        """
        Démarre le gestionnaire Prefect.

        Raises:
            Exception: Si le client Prefect ne peut pas être initialisé.
        """
        if not HAS_PREFECT:
            self.logger.debug("Prefect non disponible — mode SSH pur")
            return
        # Silencer les logs Prefect (serveur éphémère bruyant)
        import logging as _lgg

        for _noisy in ("prefect", "prefect.engine", "prefect.client", "prefect.runner", "httpx", "httpcore"):
            _lgg.getLogger(_noisy).setLevel(_lgg.WARNING)
        try:
            self.client = get_client()
            self.logger.debug("Prefect client initialisé")
        except Exception as e:
            self.logger.debug(f"Prefect client non disponible: {e}")
            self.client = None

    async def stop(self) -> None:
        """
        Arrête le gestionnaire Prefect.

        Raises:
            Exception: Si une erreur se produit lors de l'arrêt.
        """
        # Annuler les tâches en cours
        for name, task in list(self._running_pipelines.items()):
            if not task.done():
                task.cancel()
        self._running_pipelines.clear()
        if self.client:
            try:
                if hasattr(self.client, "close"):
                    await self.client.close()
                elif hasattr(self.client, "__aexit__"):
                    await self.client.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"PrefectManager.stop: {e}")
            finally:
                self.client = None

    async def run_ssh_command(self, command: str, sudo: bool = False) -> str:
        """
        Exécute une commande SSH.

        Args:
            command (str): La commande à exécuter.
            sudo (bool, optional): Utiliser sudo ou non. Defaults to False.

        Returns:
            str: La sortie de la commande.

        Raises:
            RuntimeError: Si la commande échoue.
        """
        _fs = _failure_stats()
        _fs["total_commands"] += 1
        _run_ssh = _get_run_ssh()
        if _run_ssh is None:
            raise RuntimeError("run_ssh non disponible (Nokido.py non chargé)")
        out, err, status = await _run_ssh(command, sudo)
        if status != 0:
            _fs["failed_commands"] += 1
            self._send_notification(f"Commande échouée: {command}\nErreur: {err}")
            raise RuntimeError(f"Commande échouée (exit {status}): {err}")
        return out

    def _send_notification(self, message: str) -> None:
        """
        Envoie une notification.

        Args:
            message (str): Le message à envoyer.
        """
        if not self.slack_webhook:
            return
        try:
            import urllib.request

            payload = json.dumps({"text": message}).encode()
            req = urllib.request.Request(
                self.slack_webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            self.logger.warning(f"Notification Slack échouée: {e}")

    def _record(self, name: str, status: str, detail: str = "") -> None:
        """
        Enregistre dans l'historique des pipelines.

        Args:
            name (str): Le nom du pipeline.
            status (str): Le statut du pipeline.
            detail (str, optional): Les détails du pipeline. Defaults to "".
        """
        import datetime

        entry = {
            "name": name,
            "status": status,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "detail": detail[:200],
        }
        self._pipeline_history.append(entry)
        if len(self._pipeline_history) > 50:
            self._pipeline_history.pop(0)

    # ── CI/CD ─────────────────────────────────────────────────────────────────

    async def run_ci_pipeline(
        self,
        repo_url: str,
        branch: str = "main",
        workdir: str = "/tmp/ci-repo",
        on_step: Optional[callable] = None,
    ) -> str:
        """
        Pipeline CI complet :
        1. clone/pull  2. checkout  3. détection auto (Makefile/pytest/npm/docker)
        4. test         5. build     6. optionnel: docker build + deploy
        on_step(icon, msg) appelé à chaque étape pour l'UI.

        Args:
            repo_url (str): L'URL du dépôt.
            branch (str, optional): La branche à utiliser. Defaults to "main".
            workdir (str, optional): Le répertoire de travail. Defaults to "/tmp/ci-repo".
            on_step (Optional[callable], optional): La fonction à appeler à chaque étape. Defaults to None.

        Returns:
            str: Le résultat du pipeline.

        Raises:
            RuntimeError: Si une erreur se produit lors du pipeline.
        """
        results = []

        def _ok(msg):
            """ok."""
            return results.append(f"✅ {msg}")

        def _ko(msg):
            """ko."""
            return results.append(f"❌ {msg}")

        def _info(msg):
            """info."""
            return results.append(f"  ℹ {msg}")

        def _step(icon: str, msg: str) -> None:
            """
            Étape du pipeline.

            Args:
                icon (str): L'icône de l'étape.
                msg (str): Le message de l'étape.
            """
            results.append(f"{icon} {msg}")
            if on_step:
                try:
                    on_step(icon, msg)
                except Exception:
                    pass

        # 1. Clone ou pull
        _step("🔄", f"Sync {repo_url} ({branch})")
        try:
            clone_cmd = (
                f"[ -d {workdir}/.git ] && "
                f"(cd {workdir} && git fetch origin && git reset --hard origin/{branch}) || "
                f"git clone --depth=1 -b {branch} {repo_url} {workdir}"
            )
            out = await self.run_ssh_command(clone_cmd)
            _ok(f"Dépôt prêt dans {workdir}")
        except RuntimeError as e:
            _ko(f"Clone/pull échoué : {e}")
            self._record(repo_url, "FAILED", str(e))
            return "\n".join(results)

        # 2. Détection de l'outillage
        _step("🔍", "Détection de l'outillage…")
        try:
            ls_out = await self.run_ssh_command(f"ls {workdir}/")
            has_make = "Makefile" in ls_out or "makefile" in ls_out
            has_pytest = "pytest.ini" in ls_out or "setup.cfg" in ls_out or "pyproject.toml" in ls_out
            has_npm = "package.json" in ls_out
            has_docker = "Dockerfile" in ls_out
            has_compose = "docker-compose" in ls_out or "compose.yml" in ls_out
            tools = []
            if has_make:
                tools.append("Makefile")
            if has_pytest:
                tools.append("pytest")
            if has_npm:
                tools.append("npm")
            if has_docker:
                tools.append("Docker")
            if has_compose:
                tools.append("Compose")
            _info(f"Outillage détecté : {', '.join(tools) or 'générique'}")
        except RuntimeError:
            has_make = has_pytest = has_npm = has_docker = has_compose = False

        # 3. Tests
        _step("🧪", "Exécution des tests…")
        test_ok = False
        if has_make:
            try:
                out = await self.run_ssh_command(f"cd {workdir} && make test 2>&1 | tail -20")
                _ok(f"make test OK\n{out[:300]}")
                test_ok = True
            except RuntimeError as e:
                _ko(f"make test : {str(e)[:200]}")
        elif has_pytest:
            try:
                out = await self.run_ssh_command(f"cd {workdir} && python -m pytest -x --tb=short 2>&1 | tail -30")
                _ok(f"pytest OK\n{out[:300]}")
                test_ok = True
            except RuntimeError as e:
                _ko(f"pytest : {str(e)[:200]}")
        elif has_npm:
            try:
                out = await self.run_ssh_command(f"cd {workdir} && npm test 2>&1 | tail -20")
                _ok(f"npm test OK\n{out[:200]}")
                test_ok = True
            except RuntimeError as e:
                _ko(f"npm test : {str(e)[:200]}")
        else:
            _info("Aucun système de test détecté — étape sautée")
            test_ok = True

        # 4. Build
        _step("🔨", "Build…")
        if has_make:
            try:
                out = await self.run_ssh_command(f"cd {workdir} && make build 2>&1 | tail -20")
                _ok(f"make build OK\n{out[:200]}")
            except RuntimeError as e:
                _ko(f"make build : {str(e)[:200]}")
        elif has_npm:
            try:
                out = await self.run_ssh_command(f"cd {workdir} && npm run build 2>&1 | tail -20")
                _ok(f"npm build OK\n{out[:200]}")
            except RuntimeError as e:
                _ko(f"npm build : {str(e)[:200]}")
        else:
            _info("Pas de build configuré")

        # 5. Docker build (si Dockerfile présent)
        if has_docker:
            _step("🐳", "Docker build…")
            img_name = repo_url.rstrip("/").split("/")[-1].lower() or "app"
            try:
                out = await self.run_ssh_command(
                    f"cd {workdir} && docker build -t {img_name}:{branch} . 2>&1 | tail -10"
                )
                _ok(f"Image {img_name}:{branch} construite\n{out[:200]}")
            except RuntimeError as e:
                _ko(f"docker build : {str(e)[:200]}")

        # 6. Docker Compose up (si compose présent)
        if has_compose:
            _step("🚢", "Docker Compose up…")
            try:
                out = await self.run_ssh_command(f"cd {workdir} && docker compose up -d --build 2>&1 | tail -10")
                _ok(f"Compose déployé\n{out[:200]}")
            except RuntimeError as e:
                _ko(f"docker compose : {str(e)[:200]}")

        final_status = "SUCCESS" if test_ok else "FAILED"
        self._record(repo_url, final_status, results[-1] if results else "")
        if final_status == "SUCCESS":
            self._send_notification(f"✅ CI {repo_url}@{branch} réussi")
        else:
            self._send_notification(f"❌ CI {repo_url}@{branch} échoué")
        return "\n".join(results)

    async def deploy(
        self,
        service: str,
        strategy: str = "restart",
        on_step: Optional[callable] = None,
    ) -> str:
        """
        Déploiement sur le serveur distant.
        strategy : restart | compose | systemd | docker | rollback

        Args:
            service (str): Le service à déployer.
            strategy (str, optional): La stratégie de déploiement. Defaults to "restart".
            on_step (Optional[callable], optional): La fonction à appeler à chaque étape. Defaults to None.

        Returns:
            str: Le résultat du déploiement.

        Raises:
            RuntimeError: Si une erreur se produit lors du déploiement.
        """
        results = []

        def _step(icon, msg):
            """step."""
            return results.append(f"{icon} {msg}") or (on_step and on_step(icon, msg))

        _step("🚀", f"Déploiement [{strategy}] de {service}…")

        if strategy == "restart":
            try:
                out = await self.run_ssh_command(f"systemctl restart {service}", sudo=True)
                _step("✅", f"{service} redémarré")
                status = await self.run_ssh_command(f"systemctl status {service} --no-pager -l | head -8")
                results.append(status[:400])
            except RuntimeError as e:
                _step("❌", str(e))

        elif strategy == "compose":
            try:
                out = await self.run_ssh_command(
                    f"cd /opt/{service} && docker compose pull && docker compose up -d --remove-orphans 2>&1 | tail -15",
                    sudo=True,
                )
                _step("✅", "Compose mis à jour")
                results.append(out[:400])
            except RuntimeError as e:
                _step("❌", str(e))

        elif strategy == "systemd":
            try:
                await self.run_ssh_command(f"systemctl daemon-reload && systemctl restart {service}", sudo=True)
                _step("✅", f"Systemd {service} rechargé")
            except RuntimeError as e:
                _step("❌", str(e))

        elif strategy == "docker":
            try:
                out = await self.run_ssh_command(
                    f"docker pull {service} && docker stop {service.split(':')[0]} 2>/dev/null; "
                    f"docker run -d --name {service.split(':')[0]} {service} 2>&1 | tail -5",
                    sudo=True,
                )
                _step("✅", f"Container {service} déployé")
                results.append(out[:300])
            except RuntimeError as e:
                _step("❌", str(e))

        elif strategy == "rollback":
            try:
                bak = await self.run_ssh_command(f"ls /opt/{service}_bak* 2>/dev/null | sort | tail -1")
                if bak.strip():
                    await self.run_ssh_command(
                        f"cp -r {bak.strip()} /opt/{service} && systemctl restart {service}", sudo=True
                    )
                    _step("✅", f"Rollback → {bak.strip()}")
                else:
                    _step("⚠", "Aucune sauvegarde trouvée")
            except RuntimeError as e:
                _step("❌", str(e))

        self._record(service, "DEPLOYED", strategy)
        return "\n".join(results)

    # run_workflow — voir forge_core_models.py

    def workflow_list(self) -> List[str]:
        """
        Liste les workflows définis.

        Returns:
            List[str]: La liste des workflows.
        """
        return list(self._custom_workflows.keys())

    def pipeline_history(self, limit: int = 10) -> List[Dict]:
        """
        Pipeline history.

        Args:
            limit (int, optional): La limite de résultats. Defaults to 10.

        Returns:
            List[Dict]: L'historique des pipelines.
        """
        return self._pipeline_history[-limit:]
