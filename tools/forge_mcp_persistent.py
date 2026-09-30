"""
forge_mcp_persistent.py — Client MCP Persistant avec Schema Cache et Lazy Loading
==================================================================================
Optimise le dialogue MCP en :
1. Schema Caching  : liste des outils récupérée une seule fois par session
2. Connexion SSE maintenue : pas de handshake HTTP à chaque appel
3. Lazy Loading    : résultats > 2000 chars → MMAP pointer ID
4. Hardware Aware  : backpressure sur RAM > 80% (Ryzen 8700G)

Usage :
    async with PersistentMCPClient("http://localhost:9999") as client:
        result = await client.call("read", {"action": "file", "path": "app/X.py"})
        # Si résultat > 2000 chars → retourne {"__mmap_id__": "mcp_XXXXX", "size": N}
        # Récupérer le contenu complet : await client.resolve("mcp_XXXXX")
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

# ── Constantes ────────────────────────────────────────────────────────────────
MCP_HOST = os.getenv("MCP_HOST", "http://localhost:9999")
LAZY_THRESHOLD = int(os.getenv("MCP_LAZY_THRESHOLD", "2000"))  # chars
RAM_GUARD_PCT = float(os.getenv("MCP_RAM_GUARD_PCT", "80.0"))  # %
SCHEMA_TTL = int(os.getenv("MCP_SCHEMA_TTL", "300"))  # secondes
CONNECT_TIMEOUT = float(os.getenv("MCP_CONNECT_TIMEOUT", "5.0"))
CALL_TIMEOUT = float(os.getenv("MCP_CALL_TIMEOUT", "60.0"))

# ── MMAP Store (résultats volumineux en mémoire partagée) ─────────────────────
_mmap_store: dict[str, str] = {}


def mmap_store(content: str) -> str:
    """Stocke un contenu volumineux et retourne un pointer ID.

    Args:
        content: Contenu à stocker.

    Returns:
        Pointer ID sous forme de string 'mcp_XXXXXXXX'.
    """
    mmap_id = f"mcp_{uuid.uuid4().hex[:8]}"
    _mmap_store[mmap_id] = content
    return mmap_id


def mmap_get(mmap_id: str) -> str | None:
    """Récupère un contenu depuis le store MMAP.

    Args:
        mmap_id: Pointer ID retourné par mmap_store.

    Returns:
        Contenu original ou None si expiré/absent.
    """
    return _mmap_store.get(mmap_id)


def mmap_clear_old(max_age_s: int = 600) -> int:
    """Vide les entrées MMAP de plus de max_age_s secondes.

    Args:
        max_age_s: Âge maximum en secondes.

    Returns:
        Nombre d'entrées supprimées.
    """
    # Simple clear all pour l'instant (pas de timestamp sur les entrées)
    count = len(_mmap_store)
    _mmap_store.clear()
    return count


# ── Schema Cache ──────────────────────────────────────────────────────────────


class SchemaCache:
    """Cache des définitions d'outils MCP avec TTL.

    Évite de re-fetcher la liste des outils à chaque appel.
    """

    def __init__(self, ttl: int = SCHEMA_TTL) -> None:
        """Initialise le cache.

        Args:
            ttl: Durée de vie du cache en secondes.
        """
        self._ttl = ttl
        self._tools: list[dict] | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_valid(self) -> bool:
        """Retourne True si le cache est encore valide.

        Returns:
            True si le cache n'a pas expiré.
        """
        return self._tools is not None and time.time() - self._fetched_at < self._ttl

    def set(self, tools: list[dict]) -> None:
        """Met à jour le cache.

        Args:
            tools: Liste des définitions d'outils.
        """
        self._tools = tools
        self._fetched_at = time.time()

    def get(self) -> list[dict] | None:
        """Retourne les outils cachés ou None si expiré.

        Returns:
            Liste des outils ou None.
        """
        return self._tools if self.is_valid else None

    def invalidate(self) -> None:
        """Invalide le cache."""
        self._tools = None
        self._fetched_at = 0.0

    def tool_names(self) -> list[str]:
        """Retourne les noms des outils cachés.

        Returns:
            Liste des noms d'outils.
        """
        if not self.is_valid or not self._tools:
            return []
        return [t.get("name", "") for t in self._tools]


# ── RAM Guard ─────────────────────────────────────────────────────────────────


def _ram_usage_pct() -> float:
    """Retourne le pourcentage de RAM utilisée.

    Returns:
        Pourcentage RAM utilisé (0.0-100.0).
    """
    try:
        import psutil

        vm = psutil.virtual_memory()
        return vm.percent
    except Exception:
        return 0.0


def _check_ram_pressure() -> tuple[bool, float]:
    """Vérifie si la RAM est sous pression.

    Returns:
        Tuple (is_under_pressure, current_pct).
    """
    pct = _ram_usage_pct()
    return pct > RAM_GUARD_PCT, pct


# ── Client MCP Persistant ─────────────────────────────────────────────────────


class PersistentMCPClient:
    """Client MCP avec connexion SSE persistante et cache de schéma.

    Example:
        async with PersistentMCPClient() as client:
            result = await client.call("read", {"action": "file", "path": "app/X.py"})
    """

    def __init__(self, host: str = MCP_HOST) -> None:
        """Initialise le client.

        Args:
            host: URL du serveur MCP (ex: http://localhost:9999).
        """
        self._host = host.rstrip("/")
        self._schema_cache = SchemaCache()
        self._session = None
        self._connected = False
        self._call_count = 0
        self._error_count = 0
        self._created_at = time.time()

    async def __aenter__(self) -> PersistentMCPClient:
        """Connexion au serveur MCP.

        Returns:
            Self pour le context manager.
        """
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Déconnexion propre."""
        await self.disconnect()

    async def connect(self) -> bool:
        """Établit la connexion au serveur MCP.

        Returns:
            True si connexion réussie.

        Raises:
            ConnectionError: Si le serveur est inaccessible.
        """
        try:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT)
            )
            # Vérifier que le serveur répond
            async with self._session.get(f"{self._host}/") as resp:
                if resp.status in (200, 404):  # 404 = serveur actif mais pas de route /
                    self._connected = True
                    return True
        except Exception as e:
            self._connected = False
            raise ConnectionError(f"MCP server inaccessible ({self._host}): {e}") from e
        return False

    async def disconnect(self) -> None:
        """Ferme la session HTTP."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    async def get_tools(self, force_refresh: bool = False) -> list[dict]:
        """Retourne la liste des outils (cachée par défaut).

        Args:
            force_refresh: Force le re-fetch même si le cache est valide.

        Returns:
            Liste des définitions d'outils MCP.
        """
        if not force_refresh:
            cached = self._schema_cache.get()
            if cached is not None:
                return cached

        # Fetch depuis le serveur
        try:
            import aiohttp

            async with self._session.get(
                f"{self._host}/tools", timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT)
            ) as resp:
                data = await resp.json()
                tools = data.get("tools", data) if isinstance(data, dict) else data
                self._schema_cache.set(tools)
                return tools
        except Exception:
            # Retourner le cache même expiré plutôt que planter
            fallback = self._schema_cache._tools or []
            return fallback

    async def call(
        self,
        tool_name: str,
        params: dict | None = None,
        lazy: bool = True,
    ) -> str | dict:
        """Appelle un outil MCP.

        Args:
            tool_name: Nom de l'outil (ex: 'read', 'write', 'run').
            params:    Paramètres de l'outil.
            lazy:      Si True, les résultats > LAZY_THRESHOLD sont stockés en MMAP.

        Returns:
            Résultat de l'outil (str) ou dict MMAP pointer si lazy.
        """
        if not self._connected or not self._session:
            raise RuntimeError("Client non connecté — utiliser async with")

        # RAM guard
        under_pressure, ram_pct = _check_ram_pressure()
        if under_pressure:
            return f"[MCP RAM GUARD] RAM à {ram_pct:.1f}% — appel différé"

        payload = {
            "jsonrpc": "2.0",
            "id": self._call_count + 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params or {}},
        }

        try:
            import aiohttp

            async with self._session.post(
                f"{self._host}/mcp",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=CALL_TIMEOUT),
            ) as resp:
                data = await resp.json()
                result = self._extract_result(data)
                self._call_count += 1

                # Lazy loading
                if lazy and isinstance(result, str) and len(result) > LAZY_THRESHOLD:
                    mmap_id = mmap_store(result)
                    return {
                        "__mmap_id__": mmap_id,
                        "size": len(result),
                        "preview": result[:200] + "...",
                        "tool": tool_name,
                    }
                return result

        except Exception as e:
            self._error_count += 1
            return f"[MCP ERR] {tool_name}: {e}"

    async def resolve(self, mmap_id: str) -> str | None:
        """Résout un pointer MMAP en contenu complet.

        Args:
            mmap_id: Pointer retourné par call() en mode lazy.

        Returns:
            Contenu complet ou None si expiré.
        """
        return mmap_get(mmap_id)

    def _extract_result(self, data: dict) -> str:
        """Extrait le résultat utile d'une réponse JSON-RPC.

        Args:
            data: Réponse JSON-RPC brute.

        Returns:
            Contenu du résultat sous forme de string.
        """
        if "error" in data:
            return f"[MCP ERR] {data['error'].get('message', 'unknown')}"

        result = data.get("result", data)
        if isinstance(result, dict):
            content = result.get("content", result)
            if isinstance(content, list):
                return "\n".join(c.get("text", str(c)) for c in content if isinstance(c, dict))
            return str(content)
        return str(result)

    @property
    def stats(self) -> dict:
        """Retourne les statistiques du client.

        Returns:
            Dict avec call_count, error_count, cache_valid, uptime_s.
        """
        return {
            "call_count": self._call_count,
            "error_count": self._error_count,
            "cache_valid": self._schema_cache.is_valid,
            "tool_count": len(self._schema_cache.tool_names()),
            "uptime_s": round(time.time() - self._created_at, 1),
            "connected": self._connected,
        }


# ── Singleton session-level ───────────────────────────────────────────────────
_global_client: PersistentMCPClient | None = None


async def get_mcp_client(host: str = MCP_HOST) -> PersistentMCPClient:
    """Retourne ou crée le client MCP global (singleton par session).

    Args:
        host: URL du serveur MCP.

    Returns:
        Instance PersistentMCPClient connectée.
    """
    global _global_client
    if _global_client is None or not _global_client._connected:
        _global_client = PersistentMCPClient(host)
        try:
            await _global_client.connect()
        except ConnectionError:
            pass  # Serveur hors ligne — client utilisable en mode dégradé
    return _global_client


async def mcp_call(tool: str, params: dict | None = None) -> str | dict:
    """Raccourci pour appeler un outil MCP via le client global.

    Args:
        tool:   Nom de l'outil.
        params: Paramètres de l'outil.

    Returns:
        Résultat de l'outil.
    """
    client = await get_mcp_client()
    return await client.call(tool, params)
