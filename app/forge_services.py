"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_services
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_services.py — Registre de services réseau modulaire pour La Forge.

Architecture :
  Chaque composant (LLM, RAG, Audit, SSH, Sidecar) est un "service"
  qui peut tourner localement ou sur n'importe quelle machine du réseau.

  Le ServiceRegistry :
    - Charge la config depuis services.json
    - Vérifie la connectivité (healthcheck)
    - Route les appels vers le bon endpoint
    - Supporte le failover (service local → distant → fallback)

Services supportés :
  llm       → Ollama, oobabooga, LM Studio, Jan.ai, vLLM
  rag       → brain_worker local, ChromaDB distant, Qdrant, NAS
  audit     → local (ruff/mypy) ou distant via SSH
  sidecar   → brain_worker ZMQ (embeddings, tree-sitter)
  ssh       → connexions SSH multiples (StackDNS, NAS, etc.)

Protocoles : HTTP, ZMQ, SSH/SFTP, WebSocket (futur)
"""

import json
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# =============================================================================
# MODÈLE DE DONNÉES
# =============================================================================


class ServiceType(Enum):
    LLM = "llm"
    RAG = "rag"
    AUDIT = "audit"
    SIDECAR = "sidecar"
    SSH = "ssh"
    STORAGE = "storage"


class Protocol(Enum):
    HTTP = "http"
    ZMQ = "zmq"
    SSH = "ssh"
    SFTP = "sftp"


class ServiceStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


@dataclass
class ServiceEndpoint:
    """Un endpoint réseau pour un service."""

    name: str  # identifiant unique (ex: "ollama-local")
    type: ServiceType  # llm, rag, audit, sidecar, ssh
    protocol: Protocol  # http, zmq, ssh
    host: str = "127.0.0.1"
    port: int = 0
    path: str = ""  # chemin API (ex: "/v1/chat/completions")
    api_key: str = ""
    ssh_user: str = ""
    ssh_key: str = ""
    priority: int = 0  # 0 = préféré, 10 = fallback
    tags: List[str] = field(default_factory=list)  # ["local", "gpu", "arm64"]
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_check: float = 0.0
    latency_ms: float = 0.0
    metadata: Dict = field(default_factory=dict)  # données libres

    @property
    def base_url(self) -> str:
        """Base url."""
        scheme = "https" if self.port == 443 else "http"
        if self.protocol in (Protocol.HTTP,):
            return f"{scheme}://{self.host}:{self.port}"
        return f"{self.protocol.value}://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """Url."""
        return f"{self.base_url}{self.path}"

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "name": self.name,
            "type": self.type.value,
            "protocol": self.protocol.value,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "api_key": self.api_key,
            "ssh_user": self.ssh_user,
            "ssh_key": self.ssh_key,
            "priority": self.priority,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ServiceEndpoint":
        """From dict.

        Args:
            cls: Description.
            d: Description.
        """
        return cls(
            name=d["name"],
            type=ServiceType(d.get("type", "llm")),
            protocol=Protocol(d.get("protocol", "http")),
            host=d.get("host", "127.0.0.1"),
            port=d.get("port", 0),
            path=d.get("path", ""),
            api_key=d.get("api_key", ""),
            ssh_user=d.get("ssh_user", ""),
            ssh_key=d.get("ssh_key", ""),
            priority=d.get("priority", 0),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
        )


# =============================================================================
# REGISTRE DE SERVICES
# =============================================================================


class ServiceRegistry:
    """
    Registre central de tous les services réseau.
    Charge depuis services.json, healthcheck périodique, routage dynamique.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """Init.

        Args:
            config_path: Description.
        """
        self._endpoints: Dict[str, ServiceEndpoint] = {}
        self._config_path = config_path
        self._check_interval = 60.0  # secondes entre healthchecks
        self._initialized = False

    # ── Chargement / sauvegarde ───────────────────────────────────────────

    def load(self, config_path: Optional[Path] = None) -> int:
        """Charge les services depuis services.json. Retourne le nombre chargé."""
        path = config_path or self._config_path
        if not path or not path.exists():
            self._register_defaults()
            return len(self._endpoints)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("services", []):
                ep = ServiceEndpoint.from_dict(entry)
                self._endpoints[ep.name] = ep
            logger.info(f"[services] {len(self._endpoints)} services chargés depuis {path.name}")
        except Exception as e:
            logger.warning(f"[services] Erreur chargement {path}: {e}")
            self._register_defaults()
        self._initialized = True
        return len(self._endpoints)

    def save(self, config_path: Optional[Path] = None) -> None:
        """Sauvegarde le registre dans services.json."""
        path = config_path or self._config_path
        if not path:
            return
        data = {"services": [ep.to_dict() for ep in self._endpoints.values()]}
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[services] {len(self._endpoints)} services sauvegardés → {path.name}")
        except Exception as e:
            logger.warning(f"[services] save: {e}")

    def _register_defaults(self) -> None:
        """Enregistre les services par défaut (tout local)."""
        defaults = [
            ServiceEndpoint(
                name="ollama-local",
                type=ServiceType.LLM,
                protocol=Protocol.HTTP,
                host="127.0.0.1",
                port=11434,
                path="/api/chat",
                priority=0,
                tags=["local", "default"],
                metadata={"format": "ollama", "models_path": "/api/tags"},
            ),
            ServiceEndpoint(
                name="oobabooga-local",
                type=ServiceType.LLM,
                protocol=Protocol.HTTP,
                host="127.0.0.1",
                port=5000,
                path="/v1/chat/completions",
                priority=10,
                tags=["local", "openai-compatible"],
                metadata={"format": "openai", "models_path": "/v1/models"},
            ),
            ServiceEndpoint(
                name="lmstudio-local",
                type=ServiceType.LLM,
                protocol=Protocol.HTTP,
                host="127.0.0.1",
                port=1234,
                path="/v1/chat/completions",
                priority=10,
                tags=["local", "openai-compatible"],
                metadata={"format": "openai", "models_path": "/v1/models"},
            ),
            ServiceEndpoint(
                name="jan-local",
                type=ServiceType.LLM,
                protocol=Protocol.HTTP,
                host="127.0.0.1",
                port=1337,
                path="/v1/chat/completions",
                api_key="jan-local",
                priority=10,
                tags=["local", "openai-compatible"],
                metadata={"format": "openai", "models_path": "/v1/models"},
            ),
            ServiceEndpoint(
                name="sidecar-local",
                type=ServiceType.SIDECAR,
                protocol=Protocol.ZMQ,
                host="127.0.0.1",
                port=5557,
                priority=0,
                tags=["local", "embeddings", "tree-sitter"],
            ),
        ]
        for ep in defaults:
            self._endpoints[ep.name] = ep
        logger.info(f"[services] {len(defaults)} services par défaut enregistrés")

    # ── Enregistrement / suppression ──────────────────────────────────────

    def register(self, endpoint: ServiceEndpoint) -> None:
        """Enregistre ou met à jour un endpoint."""
        self._endpoints[endpoint.name] = endpoint
        logger.info(f"[services] +{endpoint.name} ({endpoint.type.value} {endpoint.host}:{endpoint.port})")

    def unregister(self, name: str) -> None:
        """Unregister.

        Args:
            name: Description.
        """
        self._endpoints.pop(name, None)

    # ── Requêtes ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ServiceEndpoint]:
        """Get.

        Args:
            name: Description.
        """
        return self._endpoints.get(name)

    def find(
        self, service_type: ServiceType, tags: List[str] = None, healthy_only: bool = True
    ) -> List[ServiceEndpoint]:
        """
        Trouve les endpoints pour un type de service donné.
        Triés par priorité (0 = meilleur).
        """
        results = [ep for ep in self._endpoints.values() if ep.type == service_type]
        if tags:
            results = [ep for ep in results if any(t in ep.tags for t in tags)]
        if healthy_only:
            results = [ep for ep in results if ep.status in (ServiceStatus.HEALTHY, ServiceStatus.UNKNOWN)]
        return sorted(results, key=lambda e: e.priority)

    def find_best(self, service_type: ServiceType, **kwargs) -> Optional[ServiceEndpoint]:
        """Retourne le meilleur endpoint disponible."""
        eps = self.find(service_type, **kwargs)
        return eps[0] if eps else None

    def all(self) -> List[ServiceEndpoint]:
        """All."""
        return sorted(self._endpoints.values(), key=lambda e: (e.type.value, e.priority))

    # ── Healthcheck ───────────────────────────────────────────────────────

    async def check_health(self, name: str) -> ServiceStatus:
        """Vérifie un endpoint spécifique."""
        ep = self._endpoints.get(name)
        if not ep:
            return ServiceStatus.UNREACHABLE

        t0 = time.perf_counter()
        try:
            if ep.protocol == Protocol.HTTP:
                status = await self._check_http(ep)
            elif ep.protocol == Protocol.ZMQ:
                status = await self._check_zmq(ep)
            elif ep.protocol == Protocol.SSH:
                status = await self._check_ssh(ep)
            else:
                status = ServiceStatus.UNKNOWN
        except Exception:
            status = ServiceStatus.UNREACHABLE

        ep.status = status
        ep.latency_ms = (time.perf_counter() - t0) * 1000
        ep.last_check = time.time()
        return status

    async def check_all(self) -> Dict[str, ServiceStatus]:
        """Vérifie tous les endpoints en parallèle (asyncio.gather)."""
        names = list(self._endpoints.keys())
        if not names:
            return {}
        tasks = [self.check_health(name) for name in names]
        statuses = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            name: (s if isinstance(s, ServiceStatus) else ServiceStatus.UNREACHABLE) for name, s in zip(names, statuses)
        }

    async def _check_http(self, ep: ServiceEndpoint) -> ServiceStatus:
        """Check http.

        Args:
            ep: Description.
        """
        import aiohttp

        # Construire l'URL de healthcheck
        base = f"http://{ep.host}:{ep.port}"
        models_path = ep.metadata.get("models_path", "")
        check_url = f"{base}{models_path}" if models_path else f"{base}/"
        headers = {"Authorization": f"Bearer {ep.api_key}"} if ep.api_key else {}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(check_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return ServiceStatus.HEALTHY
                    return ServiceStatus.DEGRADED
        except Exception:
            return ServiceStatus.UNREACHABLE

    async def _check_zmq(self, ep: ServiceEndpoint) -> ServiceStatus:
        """Check zmq.

        Args:
            ep: Description.
        """
        try:
            import zmq

            ctx = zmq.Context()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, 1000)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(f"tcp://{ep.host}:{ep.port}")
            sock.send(json.dumps({"cmd": "ping"}).encode())
            rep = json.loads(sock.recv().decode())
            sock.close()
            ctx.term()
            return ServiceStatus.HEALTHY if rep.get("data") == "pong" else ServiceStatus.DEGRADED
        except Exception:
            return ServiceStatus.UNREACHABLE

    async def _check_ssh(self, ep: ServiceEndpoint) -> ServiceStatus:
        """Check ssh.

        Args:
            ep: Description.
        """
        try:
            import asyncssh

            async with asyncssh.connect(
                ep.host,
                port=ep.port or 22,
                username=ep.ssh_user,
                client_keys=[ep.ssh_key] if ep.ssh_key else None,
                known_hosts=None,
                login_timeout=3,
            ) as conn:
                result = await conn.run("echo ok", timeout=2)
                return ServiceStatus.HEALTHY if result.exit_status == 0 else ServiceStatus.DEGRADED
        except Exception:
            return ServiceStatus.UNREACHABLE

    # ── Affichage ─────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Résumé lisible pour la TUI."""
        lines = []
        for st in ServiceType:
            eps = self.find(st, healthy_only=False)
            if not eps:
                continue
            lines.append(f"\n[bold]{st.value.upper()}[/]")
            for ep in eps:
                icon = {"healthy": "✅", "degraded": "⚠️", "unreachable": "❌", "unknown": "❓"}.get(
                    ep.status.value, "❓"
                )
                lat = f" {ep.latency_ms:.0f}ms" if ep.latency_ms > 0 else ""
                tags = f" [{', '.join(ep.tags)}]" if ep.tags else ""
                lines.append(f"  {icon} {ep.name} → {ep.host}:{ep.port}{lat}{tags}")
        return "\n".join(lines)


# =============================================================================
# SINGLETON
# =============================================================================

_registry: Optional[ServiceRegistry] = None


def get_registry() -> ServiceRegistry:
    """Get registry."""
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
        # Auto-enregistrer Nokido Hub v17 si disponible
        try:
            from nokido_agent.app.forge_hub_client import hub as _hub

            if _hub.alive():
                _hub_ep = ServiceEndpoint(
                    name="laforge-hub-v17",
                    type=ServiceType.SIDECAR,
                    protocol=Protocol.HTTP,
                    host="127.0.0.1",
                    port=8766,
                    path="/health",
                    priority=0,
                    tags=["local", "hub", "mcp", "github"],
                    metadata={"version": _hub.version(), "ring": 0},
                )
                _hub_ep.status = ServiceStatus.HEALTHY
                _registry.endpoints["laforge-hub-v17"] = _hub_ep
                logger.info("[services] Nokido Hub v17 auto-enregistré sur :8766")
        except Exception:
            pass
    return _registry


def init_registry(config_path: Path) -> ServiceRegistry:
    """Init registry.

    Args:
        config_path: Description.
    """
    global _registry
    _registry = ServiceRegistry(config_path)
    _registry.load()
    return _registry


# =============================================================================
# HELPERS POUR LA FORGE
# =============================================================================


def get_llm_endpoint(preferred: str = "") -> Optional[ServiceEndpoint]:
    """
    Retourne le meilleur endpoint LLM disponible.
    Si preferred est donné, tente de le trouver d'abord.
    """
    reg = get_registry()
    if preferred:
        ep = reg.get(preferred)
        if ep and ep.status != ServiceStatus.UNREACHABLE:
            return ep
    return reg.find_best(ServiceType.LLM)


def get_rag_endpoint() -> Optional[ServiceEndpoint]:
    """Get rag endpoint."""
    return get_registry().find_best(ServiceType.RAG)


def get_sidecar_endpoint() -> Optional[ServiceEndpoint]:
    """Get sidecar endpoint."""
    return get_registry().find_best(ServiceType.SIDECAR)


def get_ssh_endpoints() -> List[ServiceEndpoint]:
    """Get ssh endpoints."""
    return get_registry().find(ServiceType.SSH, healthy_only=False)


__all__ = [
    "ServiceType",
    "Protocol",
    "ServiceStatus",
    "ServiceEndpoint",
    "ServiceRegistry",
    "get_registry",
    "init_registry",
    "get_llm_endpoint",
    "get_rag_endpoint",
    "get_sidecar_endpoint",
    "get_ssh_endpoints",
]
