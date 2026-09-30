"""forge_trace_context.py — Trace/Correlation ID propagé via contextvars.

Source unique du trace_id Nokido pour le debug relationnel + l'idempotence des
sinks. Posé 1× au point d'entrée (hub mcp_post, tick daemon), lu par TOUS les
sinks DANS le même contexte (audit, execution_traces, anchor_error/solution,
critical_events). contextvars propage automatiquement aux sous-appels sync ET
aux tasks asyncio créées dans le contexte -> PAS besoin de threader le param
dans chaque signature de fonction.

Frontières de PROCESS (ZMQ :5557, subprocess sandbox, HTTP Deno/superviseur,
LLM cloud) NE propagent PAS contextvars -> sérialiser explicitement via
inject_*/extract_* (header W3C `traceparent` ou `X-Trace-Id`, env
LAFORGE_TRACE_ID, champ `trace_id` du payload msgpack/json).

Format = W3C trace_id (32 hex) via forge_audit_log.gen_trace_id pour cohérence
avec la table audit_log (RAG/audit.db) et parse_traceparent(). Ne DUPLIQUE pas
forge_jobid (dataclass JobContext.trace_id, passage explicite) : ce module est
le wrapper ContextVar end-to-end qui manquait. Cf. forge_jobid pour le lien
job<->trace persistant.
"""

from __future__ import annotations

import contextlib
import logging
import os
from contextvars import ContextVar, Token
from typing import Optional

HEADER_W3C = "traceparent"  # standard W3C
HEADER_SIMPLE = "X-Trace-Id"  # fallback simple
ENV = "LAFORGE_TRACE_ID"  # subprocess / sandbox
FIELD = "trace_id"  # payload msgpack / json

_trace_id: ContextVar[str] = ContextVar("forge_trace_id", default="")


def _gen() -> str:
    try:
        from nokido_agent.app.forge_audit_log import gen_trace_id

        return gen_trace_id()
    except Exception:
        import secrets

        return secrets.token_hex(16)


def new_trace_id() -> str:
    return _gen()


def get_trace_id() -> str:
    """Trace courant. ContextVar -> env (héritage subprocess) -> 'system'."""
    tid = _trace_id.get()
    if tid:
        return tid
    env = os.environ.get(ENV)
    return env if env else "system"


def set_trace_id(tid: Optional[str]) -> Token:
    return _trace_id.set(tid or _gen())


def reset_trace_id(token: Token) -> None:
    try:
        _trace_id.reset(token)
    except Exception:
        pass


@contextlib.contextmanager
def bind_trace_id(tid: Optional[str] = None):
    """Scope de trace. tid=None -> nouveau. Reset propre en sortie."""
    token = _trace_id.set(tid or _gen())
    try:
        yield _trace_id.get()
    finally:
        reset_trace_id(token)


# ── ActorContext : identité PRÉCISE de l'acteur (agent × canal × transport) ──
# Miroir de trace_id mais pour l'IDENTITÉ. Posé 1× au point d'entrée hub (après
# _resolve_ring + détection canal), lu SANS param par tous les sinks (audit DB
# read/write #8, network_log, lessons). contextvars propage aux sous-appels sync +
# tasks asyncio. Frontières process : sérialisé via les champs payload/headers
# (X-Agent/X-Channel/X-Transport) ci-dessous. Objectif : claude-desktop-stdio ≠
# cowork-http ≠ groq-cloud ≠ gemini-cli ≠ copilot-cli sur CHAQUE read/write DB.
# Defaut `None` et NON `{}` : un defaut MUTABLE est partage par tous les contextes,
# donc une mutation par reference fuiterait d'un acteur a l'autre -- exactement le
# genre de contamination que cet organe existe pour empecher (un acteur = un canal).
# Strictement equivalent ici : tous les lecteurs font `_actor.get() or {}`, et
# `None or {}` rend `{}`. Verifie 2026-09-19 : `_actor` n'est reference dans AUCUN
# autre module, et aucun usage ne mute la valeur par reference.
_actor: ContextVar[dict | None] = ContextVar("forge_actor", default=None)


def get_actor() -> dict:
    """Acteur courant {agent, ring, channel, transport, machine}. {} si non posé."""
    return dict(_actor.get() or {})


def set_actor(agent: str = "", *, ring=None, channel: str = "", transport: str = "",
              machine: str = "local") -> Token:
    return _actor.set({
        "agent": (agent or "").upper() or "UNKNOWN",
        "ring": ring,
        "channel": channel or "",
        "transport": transport or "",
        "machine": machine or "local",
    })


def reset_actor(token: Token) -> None:
    try:
        _actor.reset(token)
    except Exception:
        pass


@contextlib.contextmanager
def bind_actor(agent: str = "", *, ring=None, channel: str = "", transport: str = "",
               machine: str = "local"):
    """Scope acteur. Reset propre en sortie."""
    token = set_actor(agent, ring=ring, channel=channel, transport=transport, machine=machine)
    try:
        yield get_actor()
    finally:
        reset_actor(token)


def actor_tag() -> str:
    """Identité compacte 'AGENT/channel/transport' pour logs/audit (1 string)."""
    a = _actor.get() or {}
    return f"{a.get('agent', 'UNKNOWN')}/{a.get('channel', '-')}/{a.get('transport', '-')}"


# ── Corrélation multi-appels : session/agent -> trace_id (flows) ─────────────
# Sans propagation explicite (header traceparent), chaque requête aurait un
# trace_id frais -> 1 action/flow, pas de séquence. Ici on CHAÎNE les appels
# d'une même clé (session_id sinon agent) tant qu'ils sont rapprochés
# (< _SESSION_GAP_S) : un burst d'appels liés = un flow. Idle > gap = nouvelle
# tâche = nouveau trace. -> policy_net/world_model apprennent des SÉQUENCES.
_SESSION_TRACES: dict = {}
_SESSION_GAP_S = 120.0  # 2 min sans appel = frontière de tâche
_SESSION_MAX = 500


def session_trace_id(key: str) -> str:
    """trace_id chaîné pour une clé (session_id ou agent), reset sur idle-gap."""
    if not key:
        return _gen()
    import time as _t

    now = _t.time()
    prev = _SESSION_TRACES.get(key)
    tid = prev[0] if (prev and (now - prev[1]) < _SESSION_GAP_S) else _gen()
    _SESSION_TRACES[key] = (tid, now)
    if len(_SESSION_TRACES) > _SESSION_MAX:  # GC léger
        cutoff = now - 3600
        for k in [k for k, v in list(_SESSION_TRACES.items()) if v[1] < cutoff]:
            _SESSION_TRACES.pop(k, None)
    return tid


# ── Frontières de process : sérialisation explicite ──────────────────────────
def from_traceparent(hdr: Optional[str]) -> str:
    """trace_id depuis un header W3C `traceparent` (en génère un si absent/KO)."""
    try:
        from nokido_agent.app.forge_audit_log import parse_traceparent

        tid, _span = parse_traceparent(hdr)
        return tid
    except Exception:
        if hdr and hdr.count("-") >= 3:
            return hdr.split("-")[1]
        return _gen()


def inject_headers(headers: Optional[dict] = None) -> dict:
    h = dict(headers or {})
    tid = get_trace_id()
    h[HEADER_SIMPLE] = tid
    try:
        from nokido_agent.app.forge_audit_log import build_traceparent

        h[HEADER_W3C] = build_traceparent(tid)
    except Exception:
        pass
    # Acteur cross-process : préserve l'identité PRÉCISE aux frontières (#9).
    a = _actor.get() or {}
    if a.get("agent"):
        h["X-Agent-Name"] = a["agent"]
        if a.get("channel"):
            h["X-Channel"] = a["channel"]
        if a.get("transport"):
            h["X-Transport"] = a["transport"]
    return h


def extract_headers(headers: Optional[dict]) -> str:
    if not headers:
        return ""
    low = {str(k).lower(): v for k, v in headers.items()}
    if HEADER_W3C in low:
        return from_traceparent(str(low[HEADER_W3C]))
    if HEADER_SIMPLE.lower() in low:
        return str(low[HEADER_SIMPLE.lower()])
    return ""


def inject_env(env: Optional[dict] = None) -> dict:
    e = dict(env if env is not None else os.environ)
    e[ENV] = get_trace_id()
    # Acteur cross-process (#9) : propage l'identité PRÉCISE aux subprocess/sandbox via
    # env, symétrique de inject_headers (HTTP) + inject_payload (msgpack). extract_env relit.
    a = _actor.get() or {}
    if a.get("agent"):
        e["LAFORGE_AGENT"] = str(a["agent"])
        if a.get("channel"):
            e["LAFORGE_CHANNEL"] = str(a["channel"])
        if a.get("transport"):
            e["LAFORGE_TRANSPORT"] = str(a["transport"])
        if a.get("ring") is not None:
            e["LAFORGE_RING"] = str(a["ring"])
    return e


def extract_env(env: Optional[dict] = None) -> dict:
    """Relit l'acteur injecté dans l'env d'un subprocess (#9) -> dict {agent,channel,
    transport,ring}. À appeler en tête d'un process enfant pour restaurer l'identité
    d'origine via set_actor(**extract_env()). {} si pas d'acteur injecté."""
    e = env if env is not None else os.environ
    agent = e.get("LAFORGE_AGENT", "")
    if not agent:
        return {}
    ring = e.get("LAFORGE_RING")
    try:
        ring = int(ring) if ring not in (None, "") else None
    except Exception:
        ring = None
    return {"agent": agent, "channel": e.get("LAFORGE_CHANNEL", ""),
            "transport": e.get("LAFORGE_TRANSPORT", ""), "ring": ring}


def inject_payload(payload: dict) -> dict:
    if isinstance(payload, dict):
        payload.setdefault(FIELD, get_trace_id())
        a = _actor.get() or {}
        if a.get("agent"):
            payload.setdefault("actor", {k: a.get(k) for k in
                                         ("agent", "channel", "transport", "machine")})
    return payload


def extract_payload(payload: Optional[dict]) -> str:
    if isinstance(payload, dict) and payload.get(FIELD):
        return str(payload[FIELD])
    return ""


# ── Logging filter : ajoute trace_id à chaque LogRecord ──────────────────────
class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def install_log_filter(logger: Optional[logging.Logger] = None) -> None:
    (logger or logging.getLogger()).addFilter(TraceIdFilter())
