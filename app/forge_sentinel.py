"""Valide une instruction texte contre trois listes de regex (ring 0, 1, 2) et rend un
verdict pass, warn ou block selon le mode dev/strict lu dans l'environnement.

Entrées : validate_action (rend un SentinelResult), sentinel_guard (décorateur async
pour outils MCP), sentinel_status, is_dev_mode.
Variables lues : LAFORGE_ENV, LAFORGE_MCP_DEV, MCP_STRICT_MODE ; secret MCP_DEV_SECRET.
Utilisé par mcp_server_tools.py (outils validate/sentinel_status) et
forge_desktop/views/debate_view.py.
Effets : chaque violation est insérée dans event_log de sandbox/events.db et poussée
dans live_bridge (clés sentinel.*) ; erreurs silencieuses.
"""
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_sentinel
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_sentinel.py — Sentinelle Ring 2-3
=============================================
Circuit Breaker sur les actions PC critiques.
Valide chaque instruction avant envoi aux outils MCP ring 9.

Variables .env respectées :
  LAFORGE_ENV=dev          → mode dev : warn au lieu de block sur ring 1-2
  LAFORGE_MCP_DEV=true     → désactive le blocage dur sauf ring 0 absolu
  MCP_STRICT_MODE=false    → permissif par défaut (même en prod)
  MCP_DEV_SECRET=<hash>    → permet de bypass en mode dev signé

Ring 0 = TOUJOURS bloqué même en dev (lois absolues)
Ring 1 = bloqué en prod, warn en dev
Ring 2 = warn seulement

ADR-008 : Sentinelle positionnée Ring 2-3.
"""

import json
import os
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


# ── Lecture config depuis .env (déjà chargé dans os.environ) ─────────────────


def _is_dev() -> bool:
    """True si LAFORGE_ENV=dev OU LAFORGE_MCP_DEV=true."""
    return (
        os.environ.get("LAFORGE_ENV", "prod").lower() == "dev"
        or os.environ.get("LAFORGE_MCP_DEV", "false").lower() == "true"
    )


def _is_strict() -> bool:
    """Is strict."""
    return os.environ.get("MCP_STRICT_MODE", "false").lower() == "true"


def _dev_secret() -> str:
    """Dev secret."""
    return get_secret("MCP_DEV_SECRET") or ""


# ── Patterns d'actions critiques par ring ────────────────────────────────────

# Ring 0 — ABSOLU — bloqué même en dev
_RING0_PATTERNS = [
    r"DROP\s+TABLE\s+system_rules",
    r"DELETE\s+FROM\s+system_rules",
    r"UPDATE\s+system_rules\s+SET\s+ring\s*=\s*0",
    r"rm\s+-rf\s+[\"']?/",
    r"format\s+[Cc]:",
    r"del\s+/[Ff]\s+/[Ss]\s+",
    r"SENTINEL\s+BLOQUE",  # auto-protection
    r"disable.*sentinel",
    r"bypass.*ring.?0",
]

# Ring 1 — bloqué en prod, warn en dev
_RING1_PATTERNS = [
    r"reg\s+(add|delete|export)\s+HKEY",
    r"taskkill.*\/F.*watchdog",
    r"del.*LaForge\.env",
    r"DELETE\s+FROM\s+adr_records",
    r"truncate.*event_log",
    r"nssm\s+remove\s+Nokido",
    r"sc\s+delete\s+Nokido",
]

# Ring 2 — warn seulement (même en prod si MCP_STRICT_MODE=false)
_RING2_PATTERNS = [
    r"DELETE\s+FROM\s+rag_chunks\s+WHERE\s+domain\s*=\s*[\"']adr[\"']",
    r"os\.system\s*\(",
    r"subprocess.*shell\s*=\s*True",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__.*os.*system",
]


# ── Validation ────────────────────────────────────────────────────────────────


class SentinelResult:
    __slots__ = ("allowed", "ring_violated", "pattern", "action", "message", "dev_mode")

    def __init__(
        self, allowed: bool, ring_violated: int, pattern: str, action: str, message: str, dev_mode: bool
    ) -> None:
        """Init.

        Args:
            allowed: Description.
            ring_violated: Description.
            pattern: Description.
            action: Description.
            message: Description.
            dev_mode: Description.
        """
        self.allowed = allowed
        self.ring_violated = ring_violated
        self.pattern = pattern
        self.action = action  # "pass" | "warn" | "block"
        self.message = message
        self.dev_mode = dev_mode

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "allowed": self.allowed,
            "ring_violated": self.ring_violated,
            "pattern": self.pattern,
            "action": self.action,
            "message": self.message,
            "dev_mode": self.dev_mode,
        }


def validate_action(
    instruction: str,
    tool_name: str = "",
    agent_id: str = "unknown",
    dev_override: str = "",  # hash MCP_DEV_SECRET pour bypass ring 1-2
) -> SentinelResult:
    """
    Valide une instruction avant exécution.

    Règles :
      Ring 0 → block TOUJOURS (même dev, même override)
      Ring 1 → block en prod | warn en dev
      Ring 2 → warn toujours (sauf MCP_STRICT_MODE=true → block)

    dev_override : si == MCP_DEV_SECRET, ring 1-2 → pass en mode dev
    """
    dev = _is_dev()
    text = instruction + " " + tool_name

    # ── Ring 0 — ABSOLU ────────────────────────────────────────────────
    for pat in _RING0_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            msg = f"[SENTINEL RING 0] BLOQUÉ — Pattern interdit: '{pat}' | agent={agent_id}"
            _log_violation(0, agent_id, tool_name, instruction, "block", pat)
            _broadcast_mmap("SENTINEL_BLOCK", 0, agent_id, pat)
            return SentinelResult(False, 0, pat, "block", msg, dev)

    # ── Ring 1 — Bloqué prod, warn dev ────────────────────────────────
    for pat in _RING1_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            # Dev override avec secret ?
            if dev and dev_override and dev_override == _dev_secret():
                msg = f"[SENTINEL RING 1] AUTORISÉ (dev+secret) — {pat}"
                _log_violation(1, agent_id, tool_name, instruction, "dev_pass", pat)
                return SentinelResult(True, 1, pat, "dev_pass", msg, dev)
            if dev:
                msg = f"[SENTINEL RING 1] WARN (dev mode) — Pattern risqué: '{pat}'"
                _log_violation(1, agent_id, tool_name, instruction, "warn", pat)
                _broadcast_mmap("SENTINEL_WARN", 1, agent_id, pat)
                return SentinelResult(True, 1, pat, "warn", msg, dev)
            else:
                msg = f"[SENTINEL RING 1] BLOQUÉ (prod) — '{pat}' | agent={agent_id}"
                _log_violation(1, agent_id, tool_name, instruction, "block", pat)
                _broadcast_mmap("SENTINEL_BLOCK", 1, agent_id, pat)
                return SentinelResult(False, 1, pat, "block", msg, dev)

    # ── Ring 2 — Warn toujours, block si strict ────────────────────────
    for pat in _RING2_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            if _is_strict():
                msg = f"[SENTINEL RING 2] BLOQUÉ (strict) — '{pat}'"
                _log_violation(2, agent_id, tool_name, instruction, "block", pat)
                return SentinelResult(False, 2, pat, "block", msg, dev)
            msg = f"[SENTINEL RING 2] WARN — Pattern risqué détecté: '{pat}'"
            _log_violation(2, agent_id, tool_name, instruction, "warn", pat)
            return SentinelResult(True, 2, pat, "warn", msg, dev)

    # ── Pass ────────────────────────────────────────────────────────────
    return SentinelResult(True, -1, "", "pass", "OK", dev)


# ── Logging + MMap ────────────────────────────────────────────────────────────


def _log_violation(ring: int, agent: str, tool: str, instruction: str, action: str, pattern: str) -> None:
    """Log violation.

    Args:
        ring: Description.
        agent: Description.
        tool: Description.
        instruction: Description.
        action: Description.
        pattern: Description.
    """
    try:
        db_events = ROOT / "sandbox" / "events.db"
        conn = sqlite3.connect(str(db_events), timeout=5)
        last_seq = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
        conn.execute(
            "INSERT INTO event_log"
            "(timecode,sequence_id,agent_id,event_type,target,payload,status)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                last_seq + 1,
                agent,
                "sentinel_" + action,
                tool,
                json.dumps(
                    {
                        "ring": ring,
                        "pattern": pattern,
                        "instruction": instruction[:200],
                        "dev_mode": _is_dev(),
                    }
                ),
                action,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _broadcast_mmap(event_type: str, ring: int, agent: str, pattern: str) -> None:
    """Écrit dans live_bridge.map pour alerter la GUI."""
    try:
        from nokido_agent.app.live_bridge import bridge

        bridge.json_set("sentinel.last_event", event_type)
        bridge.json_set("sentinel.ring", ring)
        bridge.json_set("sentinel.agent", agent)
        bridge.json_set("sentinel.pattern", pattern[:60])
        bridge.json_set("sentinel.ts", time.time())
        bridge.json_set("sentinel.dev_mode", _is_dev())
    except Exception:
        pass


# ── Décorateur pour les tools MCP ─────────────────────────────────────────────


def sentinel_guard(tool_fn) -> object:
    """
    Décorateur pour les tools MCP ring 9.
    Usage :
        @sentinel_guard
        async def dangerous_tool(cmd: str) -> str: ...
    """
    import functools

    @functools.wraps(tool_fn)
    async def wrapper(*args, **kwargs) -> object:
        # Construire l'instruction à valider
        """Wrapper."""
        instruction = " ".join(str(a) for a in args) + " " + str(kwargs)
        result = validate_action(
            instruction,
            tool_name=tool_fn.__name__,
            agent_id=kwargs.get("agent_id", "mcp_tool"),
        )
        if not result.allowed:
            return json.dumps(
                {
                    "ok": False,
                    "blocked": True,
                    "ring": result.ring_violated,
                    "message": result.message,
                }
            )
        if result.action == "warn":
            # Injecter le warning dans le résultat
            raw = await tool_fn(*args, **kwargs)
            try:
                data = json.loads(raw)
                data["sentinel_warn"] = result.message
                return json.dumps(data)
            except Exception:
                return raw
        return await tool_fn(*args, **kwargs)

    return wrapper


# ── API publique ──────────────────────────────────────────────────────────────


def is_dev_mode() -> bool:
    """Is dev mode."""
    return _is_dev()


def sentinel_status() -> dict:
    """Sentinel status."""
    return {
        "dev_mode": _is_dev(),
        "strict_mode": _is_strict(),
        "ring0_patterns": len(_RING0_PATTERNS),
        "ring1_patterns": len(_RING1_PATTERNS),
        "ring2_patterns": len(_RING2_PATTERNS),
        "env": os.environ.get("LAFORGE_ENV", "prod"),
        "mcp_dev": os.environ.get("LAFORGE_MCP_DEV", "false"),
    }
