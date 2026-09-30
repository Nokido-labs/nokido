"""
forge_p2p_protocol.py — Interface abstraite pour backend P2P RAG
=================================================================
Stub d'architecture pour le branchement futur libsql/cr-sqlite P2P.

Implémentations prévues :
  - LibSQLP2PBackend  : libsql (Turso fork) avec réplication CRDT
  - CRSQLiteBackend   : cr-sqlite (ATTENTION: FTS5 incompat confirmé — voir bench_v4)
  - NullP2PBackend    : no-op (défaut local-only actuel)

Wiring point : forge_rag_store.py → get_p2p_backend() optionnel.
Pour activer : set env LAFORGE_P2P_BACKEND=libsql|crsqlite

Décision architecturale (2026-05-04) :
  Implémentation différée — cr-sqlite FTS5 incompat bloquant (notre RAG
  repose sur FTS5 BM25). libsql nécessite migration turso-client + schema
  CRDT. À faire quand bench local ≥85% et Docker packagé.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class P2PBackend(ABC):
    """Contrat minimal pour un backend RAG distribué."""

    @abstractmethod
    async def push_chunk(self, chunk_id: str, text: str, meta: dict) -> bool:
        """Pousse un chunk vers les pairs. Retourne True si propagé."""

    @abstractmethod
    async def pull_chunks(self, since_ts: float) -> list[dict]:
        """Pull chunks modifiés depuis timestamp. Retourne liste de {id, text, meta, ts}."""

    @abstractmethod
    async def sync_chunks(self, chunk_ids: list[str]) -> dict[str, dict]:
        """Sync bidirectionnel sur une liste d'IDs. Retourne {id: chunk_dict}."""

    @abstractmethod
    async def list_peers(self) -> list[str]:
        """Retourne les URLs des pairs connus."""

    @abstractmethod
    async def health(self) -> bool:
        """True si le backend est accessible."""


class NullP2PBackend(P2PBackend):
    """No-op — comportement local-only actuel. Défaut jusqu'à implémentation réelle."""

    async def push_chunk(self, chunk_id: str, text: str, meta: dict) -> bool:
        return True  # local only, always "ok"

    async def pull_chunks(self, since_ts: float) -> list[dict]:
        return []

    async def sync_chunks(self, chunk_ids: list[str]) -> dict[str, dict]:
        return {}

    async def list_peers(self) -> list[str]:
        return []

    async def health(self) -> bool:
        return True


def get_p2p_backend() -> P2PBackend:
    """Factory — lit LAFORGE_P2P_BACKEND. Défaut = NullP2PBackend."""
    import os

    backend = os.environ.get("LAFORGE_P2P_BACKEND", "null").lower()
    if backend == "libsql":
        raise NotImplementedError(
            "LibSQL P2P backend not yet implemented. "
            "Requires turso-client + CRDT schema migration. "
            "Blocked on: FTS5 compatibility audit for cr-sqlite."
        )
    if backend == "crsqlite":
        raise NotImplementedError(
            "cr-sqlite backend blocked: FTS5 incompatibility confirmed (bench_v4). "
            "Use LAFORGE_P2P_BACKEND=libsql once libsql migration is complete."
        )
    return NullP2PBackend()
