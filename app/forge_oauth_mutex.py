#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_oauth_mutex.py — Mutex=1 STRICT pour les appels OAuth-CLI (anti-collision entonnoir Hub).

GO Gemini V14 (split anti-dup) : "Claude verrouille l'entonnoir". Le routage reste 100% via le
Hub (seul Identity Provider) ; ce module SÉRIALISE les appels OAuth-CLI lourds qui se télescopent
(claude_cli / gemini_cli / codex_cli). Conflit signalé par user : "codex bugge gemini" → ils
PARTAGENT une lane (sérialisés ensemble). claude sur une lane séparée (parallèle OK).

Mutex BLOQUANT (attend que la lane se libère) — contraste avec forge_lane_admission.admit qui
REFUSE. Couche DISTINCTE de l'admission biométrique (occupancy pure, PAS de gate RAM/CPU : un appel
juge n'est pas un job lourd). SQLite WAL cross-process. Anti-dup : ne touche pas forge_lane_admission
(édité en parallèle par Gemini = admission biométrique v2).

Usage (entonnoir Hub, forge_agent_proxy.ask_tracked) :
    from forge_oauth_mutex import oauth_mutex, OAUTH_CLIS
    if self.name in OAUTH_CLIS:
        async with oauth_mutex(self.name):
            return await self._do_ask(...)
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : mutex strict des appels OAuth-CLI (entonnoir hub)"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import contextlib
import os
import random
import sqlite3
import time
import uuid
from pathlib import Path

_DB = Path(os.environ.get("LAFORGE_RUNTIME_DB", os.environ.get("LAFORGE_LANES_DB", "C:/tmp/laforge_lanes.db")))
_TTL = float(os.environ.get("LAFORGE_OAUTH_MUTEX_TTL", "300"))

# Providers conflictuels -> lane PARTAGÉE (sérialisés ensemble). Surchargeable par env JSON.
_GROUPS = {
    "gemini_cli": "oauth_gem_codex", "codex_cli": "oauth_gem_codex",
    "claude_cli": "oauth_claude", "claude_agent_sdk": "oauth_claude",
    "copilot_cli": "oauth_copilot",
}
try:
    import json as _json
    _GROUPS.update(_json.loads(os.environ.get("LAFORGE_OAUTH_MUTEX_GROUPS", "{}")) or {})
except Exception:
    pass

OAUTH_CLIS = set(_GROUPS)


def lane_of(provider: str) -> str:
    return _GROUPS.get(provider, "oauth_" + provider)


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB), timeout=2.0, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA busy_timeout=4000;")
    c.execute("CREATE TABLE IF NOT EXISTS oauth_mutex "
              "(lane TEXT PRIMARY KEY, holder TEXT NOT NULL, expiry REAL NOT NULL)")
    return c


def _try(lane: str, holder: str, ttl: float):
    """Acquisition atomique PURE (occupancy, SANS gate biométrique).
    Tri-état (audit 2026-06-15) : True=acquis, False=lane occupée, None=DB indispo
    (-> l'appelant fail-open au lieu de boucler 180s ou de crasher l'acquire)."""
    try:
        c = _conn()
    except sqlite3.Error:
        return None
    try:
        now = time.time()
        c.execute("DELETE FROM oauth_mutex WHERE lane=? AND expiry<=?", (lane, now))
        try:
            c.execute("INSERT INTO oauth_mutex(lane, holder, expiry) VALUES(?,?,?)", (lane, holder, now + ttl))
            return True
        except sqlite3.IntegrityError:
            return False
    except sqlite3.Error:
        return None  # erreur DB (lock/busy) -> fail-open, ne pas crasher l'acquire
    finally:
        with contextlib.suppress(Exception):
            c.close()


def _free(lane: str, holder: str) -> None:
    """Libération idempotente, JAMAIS levante (audit : un crash sur la libération
    masquait l'exception du body)."""
    with contextlib.suppress(sqlite3.Error):
        c = _conn()
        try:
            c.execute("DELETE FROM oauth_mutex WHERE lane=? AND holder=?", (lane, holder))
        finally:
            with contextlib.suppress(Exception):
                c.close()


def _renew(lane: str, holder: str, ttl: float) -> None:
    """Heartbeat DB : prolonge l'expiry tant que CE holder tient la lane (audit : un
    appel > TTL perdait son verrou -> exclusion mutuelle violée pendant le chevauchement)."""
    with contextlib.suppress(sqlite3.Error):
        c = _conn()
        try:
            c.execute("UPDATE oauth_mutex SET expiry=? WHERE lane=? AND holder=?",
                      (time.time() + ttl, lane, holder))
        finally:
            with contextlib.suppress(Exception):
                c.close()


async def _heartbeat(lane: str, holder: str, ttl: float) -> None:
    """Renouvelle l'expiry périodiquement pendant le body (via to_thread, ne gèle pas
    l'event-loop). Annulé à la sortie du contexte."""
    try:
        while True:
            await asyncio.sleep(max(1.0, ttl / 3))
            await asyncio.to_thread(_renew, lane, holder, ttl)
    except asyncio.CancelledError:
        pass


async def mutex_acquire(lane: str, holder: str, *, wait_timeout: float = 180.0,
                        ttl: float = _TTL, poll: float = 0.35) -> bool:
    """Mutex BLOQUANT borné : attend que la lane se libère. False si wait_timeout dépassé."""
    t0 = time.monotonic()
    while True:
        # to_thread : le sqlite bloquant (busy_timeout 4s) ne GÈLE PAS l'event-loop
        # (audit 2026-06-15 — sinon le mutex sérialisait tout le proxy async).
        got = await asyncio.to_thread(_try, lane, holder, ttl)
        if got is True:
            return True
        if got is None:
            return False  # DB indispo -> fail-open immédiat (pas de boucle 180s)
        if time.monotonic() - t0 > wait_timeout:
            return False
        await asyncio.sleep(poll + random.random() * poll * 0.3)  # jitter anti-thundering-herd


@contextlib.asynccontextmanager
async def oauth_mutex(provider: str, *, wait_timeout: float = 180.0, ttl: float = _TTL):
    """Sérialise les appels OAuth-CLI par groupe (1 à la fois). yield True si acquis, False si timeout
    (l'appelant procède quand même, fail-open : mieux vaut un appel non-sérialisé qu'un blocage)."""
    lane = lane_of(provider)
    # holder unique cross-process (audit : monotonic_ns a une époque par-process ->
    # collision possible -> le _free d'un process supprimait le verrou d'un autre).
    holder = f"{provider}:{os.getpid()}:{uuid.uuid4().hex}"
    got = await mutex_acquire(lane, holder, wait_timeout=wait_timeout, ttl=ttl)
    hb = asyncio.create_task(_heartbeat(lane, holder, ttl)) if got else None
    try:
        yield got
    finally:
        if hb is not None:
            hb.cancel()
            with contextlib.suppress(Exception):
                await hb
        if got:
            await asyncio.to_thread(_free, lane, holder)


def _selftest() -> bool:
    async def run():
        order = []

        async def worker(n):
            async with oauth_mutex("gemini_cli", wait_timeout=10) as ok:
                assert ok, "acquisition échouée"
                order.append(("in", n))
                await asyncio.sleep(0.15)
                order.append(("out", n))

        await asyncio.gather(worker(1), worker(2))  # même groupe -> doivent être sérialisés
        depth = maxd = 0
        for ev, _ in order:
            depth += 1 if ev == "in" else -1
            maxd = max(maxd, depth)
        assert maxd == 1, f"MUTEX KO : chevauchement (maxd={maxd}) {order}"
        # lanes distinctes -> parallèle autorisé
        assert lane_of("claude_cli") != lane_of("gemini_cli")
        assert lane_of("codex_cli") == lane_of("gemini_cli")  # conflit -> même lane
        print("forge_oauth_mutex selftest OK (sérialisation stricte) :", order)

    asyncio.run(run())
    return True


if __name__ == "__main__":
    _selftest()
