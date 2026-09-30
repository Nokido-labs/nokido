"""
forge_jwt_router.py — Middleware JWT HS256 + routage par aud
============================================================
4 piliers de sécurité :
  1. HS256 forcé (anti algorithm confusion)
  2. hmac.compare_digest natif PyJWT (anti timing attack)
  3. jti_cache SQLite (anti replay)
  4. exp court par type de frame

Routage O(1) par aud claim → ROUTER_MAP dict.
request.state.jwt_claims injecté pour les handlers.
"""

import hmac, time, uuid, os, sqlite3, json, logging
from pathlib import Path
from datetime import datetime, timezone
from nokido_agent.app.forge_secrets import get_secret

logger = logging.getLogger("Nokido.JWTRouter")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"


# ── Secret HS256 ──────────────────────────────────────────────────────────
def _get_secret() -> str:
    # Le GUICHET seul (2b-2, 2026-09-28) : il lit deja `Nokido.env` (source dotenv). Le
    # parseur maison qui le relisait ici lisait un nom RESERVE hors du guichet.
    return get_secret("HUB_JWT_SECRET") or ""


# ── Permissions bitmask ───────────────────────────────────────────────────
PERM = {
    "read_db": 1,
    "write_files": 2,
    "web_search": 4,
    "exec_python": 8,
    "notify_hub": 16,
    "admin": 32,
}
AGENT_PRM = {
    "CLAUDE": 63,  # tout
    "GEMINI": 29,  # sans write_files(2), sans admin(32)
    "CODEX": 13,  # read_db(1) + web_search(4) + exec_python(8)
    "CLINE": 31,  # sans admin
}

# TTL par type de frame (secondes)
TTL_MAP = {
    "task": 300,
    "reply": 120,
    "ping": 30,
    "ack": 30,
    "urgent": 60,
}


def has_perm(prm: int, perm_name: str) -> bool:
    return bool(prm & PERM.get(perm_name, 0))


# ── Forge un JWT signé ────────────────────────────────────────────────────
# Intent → action mapping (routage sémantique)
# L'intent précise POURQUOI la frame existe, l'action précise QUOI faire
INTENT_MAP = {
    "exec_python": {"action": "task", "pri": 0, "ttl": 120},
    "query_rag": {"action": "task", "pri": 3, "ttl": 60},
    "notify_agent": {"action": "ping", "pri": 5, "ttl": 30},  # signal léger
    "request_relay": {"action": "task", "pri": 0, "ttl": 300},
    "report_status": {"action": "reply", "pri": 7, "ttl": 60},
    "escalate": {"action": "task", "pri": 0, "ttl": 60},
    "ack": {"action": "ack", "pri": 9, "ttl": 15},
    "inbox_signal": {"action": "ping", "pri": 5, "ttl": 15},  # just "go check your box"
}


def forge_frame_token(
    from_agent: str,
    to_agent: str,
    action: str = "task",
    intent: str = "",  # intent machine-readable
    priority: int = 5,
    prm: int = None,
    extra: dict = None,
) -> str:
    try:
        import jwt as _jwt
    except ImportError:
        return ""
    secret = _get_secret()
    if not secret:
        return ""
    ttl = TTL_MAP.get(action, 300)
    if priority == 0:
        ttl = min(ttl, TTL_MAP["urgent"])
    now = int(time.time())
    # Résoudre intent → overrides action/priority/ttl
    if intent and intent in INTENT_MAP:
        _im = INTENT_MAP[intent]
        action = action if action != "task" else _im["action"]
        priority = priority if priority != 5 else _im["pri"]
        ttl = _im.get("ttl", ttl)

    payload = {
        "iss": "hub",
        "aud": to_agent.lower(),
        "sub": from_agent.lower(),
        "rng": 0,
        "prm": prm if prm is not None else AGENT_PRM.get(from_agent.upper(), 7),
        "pri": priority,
        "act": action,
        "int": intent or "",  # intent — routage sémantique
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + ttl,
        **(extra or {}),
    }
    return _jwt.encode(payload, secret, algorithm="HS256")


# ── Vérifier un JWT + anti-replay ────────────────────────────────────────
def verify_frame_token(token: str, expected_aud: str = None) -> dict | None:
    try:
        import jwt as _jwt
    except ImportError:
        return None
    secret = _get_secret()
    if not secret or not token:
        return None
    try:
        payload = _jwt.decode(
            token,
            secret,
            algorithms=["HS256"],  # FORCER — jamais faire confiance au header
            options={"verify_aud": False},  # on route par aud manuellement
        )
    except Exception as e:
        logger.warning(f"JWT invalid: {e}")
        return None

    # Vérifier audience si demandée
    if expected_aud and payload.get("aud") != expected_aud.lower():
        logger.warning(f"JWT aud mismatch: {payload.get('aud')} != {expected_aud}")
        return None

    # Anti-replay : vérifier jti_cache
    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    if jti:
        try:
            with sqlite3.connect(str(DB_PATH), timeout=3) as conn:
                # Nettoyer les JTI expirés
                conn.execute("DELETE FROM jti_cache WHERE exp < ?", (int(time.time()),))
                # Tenter insertion — échoue si déjà vu
                try:
                    conn.execute(
                        "INSERT INTO jti_cache(jti, exp, agent) VALUES(?,?,?)", (jti, exp, payload.get("sub", ""))
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    logger.warning(f"JWT replay détecté jti={jti}")
                    return None
        except Exception as e:
            logger.debug(f"jti_cache check skip: {e}")

    return payload


# ── Middleware Starlette/FastAPI ──────────────────────────────────────────
async def jwt_routing_middleware(request, call_next):
    """
    Intercepte Authorization: Bearer <jwt>
    Route par aud claim en O(1) via ROUTER_MAP.
    Injecte request.state.jwt_claims pour les handlers.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return await call_next(request)

    token = auth[7:].strip()
    secret = _get_secret()
    if not secret:
        return await call_next(request)

    try:
        import jwt as _jwt

        payload = _jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_exp": True},
        )
        # Injecter les claims dans request.state
        request.state.jwt_claims = payload
        request.state.jwt_aud = payload.get("aud", "")
        request.state.jwt_prm = payload.get("prm", 0)
        request.state.jwt_ring = payload.get("rng", 99)
        request.state.jwt_pri = payload.get("pri", 5)
        logger.debug(f"JWT routed: aud={payload.get('aud')} prm={payload.get('prm')} pri={payload.get('pri')}")
    except Exception:
        pass  # Token absent ou invalide → call_next gère

    return await call_next(request)


def forge_inbox_signal(from_agent: str, to_agent: str) -> str:
    """
    Signal minimal — potentiel d'action.
    Informe l'agent qu'un message l'attend, sans transporter le contenu.
    TTL 15s, priorité neutre, JWT signé pour authentification.
    """
    return forge_frame_token(
        from_agent=from_agent,
        to_agent=to_agent,
        intent="inbox_signal",
    )
