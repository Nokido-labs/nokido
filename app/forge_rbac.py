"""
forge_rbac.py Nokido v18.5 RBAC Middleware v2 Anti-Piege
4 parades contre le piege semantique de la Sentinelle:
  1. BREAK-GLASS: FORGE_MCP_TOKEN + LAFORGE_ADMIN_TOKEN AVANT la DB
  2. PAS DE SUPPRESSION SILENCIEUSE: outil bloque -> remplace par request_<tool>
  3. ZERO LLM DANS LES PERMISSIONS: capabilities = booleans stricts Python
  4. SHADOW MODE: action destructive + agent non-owner -> dry_run automatique
PIEGES EVITES:
  DB corrompue -> Break-Glass fonctionne independamment
  ring_level en DB modifie -> sans effet sur break-glass ni humain ring 0
  is_active=0 -> jamais applique aux humains ring 0
"""

from __future__ import annotations
import json, sqlite3, logging, hashlib, datetime, os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _load_breakglass_tokens() -> frozenset:
    # Le GUICHET seul (etape 2b-2 du correctif du coffre, 2026-09-28). Ces deux noms sont
    # reserves : lus par l'environnement puis par un parseur maison de `Nokido.env`, ils
    # contournaient le coffre reserve et le recensement. Le guichet lit deja `Nokido.env`
    # et l'environnement, en dernier recours.
    tokens = set()
    try:
        from nokido_agent.app.forge_secrets import get_secret
        for var in ("FORGE_MCP_TOKEN", "LAFORGE_ADMIN_TOKEN"):
            val = (get_secret(var) or "").strip()
            if val and len(val) >= 32:
                tokens.add(val)
    except Exception as exc:  # noqa: BLE001
        logger.critical("RBAC: guichet illisible (%s) -- aucun break-glass charge",
                        type(exc).__name__)
    if not tokens:
        logger.critical("RBAC: AUCUN break-glass token")
    else:
        logger.info(f"RBAC: {len(tokens)} break-glass token(s)")
    return frozenset(tokens)


BREAKGLASS_TOKENS: frozenset = _load_breakglass_tokens()


def is_breakglass(token: str) -> bool:
    if not token:
        return False
    import hmac

    return any(hmac.compare_digest(token.encode(), bg.encode()) for bg in BREAKGLASS_TOKENS)


CAPABILITY_REGISTRY = {
    "read_db": "Lecture rag_chunks",
    "write_db": "Ecriture generique DB",
    "write_chunk": "INSERT/UPDATE rag_chunks",
    "read_chunk": "SELECT rag_chunks",
    "run_python": "Executer code Python",
    "run_ps1": "Executer scripts PowerShell",
    "web_search": "Requetes SearXNG",
    "task_create": "Creer agent_tasks",
    "task_claim": "Clamer tache",
    "task_result": "Ecrire resultats",
    "task_approve": "Approuver/rejeter tasks",
    "tui_notify": "Ecrire notifications",
    "network_audit": "Acces netcfg",
    "vault_read": "Lire vault.db",
    "vault_access": "RW vault.db",
    "deploy": "Declencher deploy",
    "approve_rules": "Modifier system_rules",
    "admin": "Acces complet",
}

TOOL_CAPABILITY_MAP = {
    "write_chunk": "write_chunk",
    "ingest": "write_chunk",
    "run_python": "run_python",
    "run_ps1": "run_ps1",
    "execute_powershell": "run_ps1",
    "web_search": "web_search",
    "web_fetch": "web_search",
    "task_create": "task_create",
    "task_approve": "task_approve",
    "task_result": "task_result",
    "vault": "vault_access",
    "admin": "admin",
    "deploy": "deploy",
    "approve_rules": "approve_rules",
    "network_audit": "network_audit",
}

TOOL_FALLBACK_MAP = {
    "execute_powershell": {
        "name": "request_powershell_execution",
        "description": "Soumet une demande PS1 a la promotion_queue pour validation humaine.",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "reason": {"type": "string"},
                "is_dry_run": {"type": "boolean", "default": True},
            },
            "required": ["script", "reason"],
        },
    },
    "run_ps1": {
        "name": "request_powershell_execution",
        "description": "Soumet une demande PS1 a la promotion_queue pour validation humaine.",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "reason": {"type": "string"},
                "is_dry_run": {"type": "boolean", "default": True},
            },
            "required": ["script", "reason"],
        },
    },
    "write_chunk": {
        "name": "request_write_chunk",
        "description": "Soumet une proposition d ingestion a la promotion_queue.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source": {"type": "string"},
                "domain": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["text", "source"],
        },
    },
    "admin": {
        "name": "request_admin_action",
        "description": "Soumet une demande admin a la promotion_queue.",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["action", "reason"],
        },
    },
    "deploy": {
        "name": "request_deploy",
        "description": "Soumet une demande de deploiement a la validation humaine.",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["target", "reason"],
        },
    },
}


class EntityNotFound(Exception):
    pass


class CapabilityDenied(Exception):
    pass


class RBACMiddleware:
    def __init__(self, db_path=None):
        self._db = Path(db_path) if db_path else Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
        self._cache: dict = {}

    def _conn(self):
        c = sqlite3.connect(str(self._db), timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def get_entity(self, entity_id: str, refresh: bool = False) -> dict:
        if entity_id in self._cache and not refresh:
            return self._cache[entity_id]
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT entity_id,entity_type,display_name,ring_level,"
                "capabilities,is_active,meta FROM forge_entities WHERE entity_id=?",
                (entity_id,),
            ).fetchone()
            conn.close()
        except Exception as e:
            raise EntityNotFound(f"DB inaccessible: {e}")
        if not row:
            raise EntityNotFound(f"Entite inconnue: {entity_id}")
        p = {
            "entity_id": row[0],
            "entity_type": row[1],
            "display_name": row[2],
            "ring_level": row[3],
            "capabilities": json.loads(row[4] or "[]"),
            "is_active": bool(row[5]),
            "meta": json.loads(row[6] or "{}"),
        }
        self._cache[entity_id] = p
        return p

    def check(self, entity_id: str, capability: str, token: str = "") -> bool:
        # ORDRE STRICT — jamais inverse
        # 1. Break-glass
        if token and is_breakglass(token):
            logger.info(f"RBAC BREAK-GLASS: {entity_id} -> ACCEPT_ALL")
            return True
        try:
            p = self.get_entity(entity_id)
        except EntityNotFound:
            logger.warning(f"RBAC: entite inconnue {entity_id} -> refus")
            return False
        # 2. Humain ring 0 = toujours autorise (impossible de se bloquer)
        if p["entity_type"] == "human" and p["ring_level"] == 0:
            return True
        # Entite inactive (ne s applique PAS aux humains ring 0)
        if not p["is_active"]:
            return False
        # 3. Capabilities booleennes strictes, zero LLM
        caps = p["capabilities"]
        if "admin" in caps:
            return True
        return capability in caps

    def require(self, entity_id: str, capability: str, token: str = "") -> dict:
        if not self.check(entity_id, capability, token=token):
            try:
                p = self.get_entity(entity_id)
                ring, caps = p["ring_level"], p["capabilities"]
            except EntityNotFound:
                ring, caps = "?", []
            raise CapabilityDenied(f"[{entity_id}] ring={ring} manque '{capability}'. caps={caps}")
        return self.get_entity(entity_id)

    def filter_tools_payload(self, payload: dict, entity_id: str, token: str = "") -> dict:
        # Break-glass -> payload passe sans filtrage
        if token and is_breakglass(token):
            return payload
        tools = payload.get("tools", [])
        if not tools:
            return payload
        allowed, replaced_names, log_blocked = [], set(), []
        for tool in tools:
            tool_name = (tool.get("name") or tool.get("function", {}).get("name") or "").lower()
            required_cap, matched_key = None, None
            for key, cap in TOOL_CAPABILITY_MAP.items():
                if key in tool_name:
                    required_cap, matched_key = cap, key
                    break
            if required_cap is None or self.check(entity_id, required_cap, token=token):
                allowed.append(tool)
            else:
                log_blocked.append(tool_name)
                fb = TOOL_FALLBACK_MAP.get(matched_key)
                if fb and fb["name"] not in replaced_names:
                    allowed.append(fb)
                    replaced_names.add(fb["name"])
                    logger.info(f"RBAC REPLACE: '{tool_name}' -> '{fb['name']}' pour {entity_id}")
        if log_blocked:
            logger.warning(f"RBAC: {entity_id} {len(log_blocked)} outils traites: {log_blocked}")
        result = dict(payload)
        result["tools"] = allowed
        return result

    def shadow_check(self, entity_id: str, capability: str, action_description: str = "", token: str = "") -> dict:
        if token and is_breakglass(token):
            return {"allowed": True, "shadow": False, "reason": "break-glass", "entity": {}}
        try:
            profile = self.get_entity(entity_id)
        except EntityNotFound:
            return {"allowed": False, "shadow": False, "reason": "entity_not_found", "entity": {}}
        if profile["entity_type"] == "human" and profile["ring_level"] == 0:
            return {"allowed": True, "shadow": False, "reason": "human_owner", "entity": profile}
        has_cap = self.check(entity_id, capability, token=token)
        if has_cap:
            destructive = {"delete", "drop", "truncate", "rm", "remove", "format", "wipe", "purge", "reset"}
            is_destr = any(kw in action_description.lower() for kw in destructive)
            if is_destr and profile["ring_level"] > 1:
                return {"allowed": True, "shadow": True, "reason": "destructive_shadow", "entity": profile}
            return {"allowed": True, "shadow": False, "reason": "capability_ok", "entity": profile}
        return {"allowed": False, "shadow": False, "reason": f"missing_capability:{capability}", "entity": profile}

    def open_session(self, session_id: str, entity_id: str, mode: str = "solo", ip: str = "") -> None:
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else ""
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO entity_sessions(session_id,entity_id,mode,ip_hash) VALUES(?,?,?,?)",
            (session_id, entity_id, mode, ip_hash),
        )
        conn.execute(
            "UPDATE forge_entities SET last_seen=? WHERE entity_id=?", (datetime.datetime.now().isoformat(), entity_id)
        )
        conn.commit()
        conn.close()

    def close_session(self, session_id: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE entity_sessions SET ended_at=? WHERE session_id=?",
            (datetime.datetime.now().isoformat(), session_id),
        )
        conn.commit()
        conn.close()

    def list_entities(self, ring_max: int = 10, entity_type=None) -> list:
        conn = self._conn()
        q = "SELECT entity_id,entity_type,display_name,ring_level,capabilities,is_active FROM forge_entities"
        params = []
        filters = [f"ring_level <= {ring_max}"]
        if entity_type:
            filters.append("entity_type=?")
            params.append(entity_type)
        q += " WHERE " + " AND ".join(filters) + " ORDER BY ring_level,entity_type"
        rows = conn.execute(q, params).fetchall()
        conn.close()
        return [
            {
                "entity_id": r[0],
                "entity_type": r[1],
                "display_name": r[2],
                "ring_level": r[3],
                "capabilities": json.loads(r[4] or "[]"),
                "is_active": bool(r[5]),
            }
            for r in rows
        ]

    def audit_entity(self, entity_id: str) -> dict:
        profile = self.get_entity(entity_id, refresh=True)
        conn = self._conn()
        sessions = conn.execute(
            "SELECT session_id,started_at,ended_at,mode FROM entity_sessions "
            "WHERE entity_id=? ORDER BY started_at DESC LIMIT 10",
            (entity_id,),
        ).fetchall()
        conn.close()
        profile["recent_sessions"] = [
            {"session_id": s[0], "started_at": s[1], "ended_at": s[2], "mode": s[3]} for s in sessions
        ]
        return profile


_default_rbac: Optional[RBACMiddleware] = None


def get_rbac(db_path=None) -> RBACMiddleware:
    global _default_rbac
    if _default_rbac is None:
        _default_rbac = RBACMiddleware(db_path)
    return _default_rbac


def check_capability(entity_id: str, capability: str, token: str = "", db_path=None) -> bool:
    return get_rbac(db_path).check(entity_id, capability, token=token)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
    rbac = RBACMiddleware(DB)
    print("=== forge_rbac v2 self-test ===")
    bg = list(BREAKGLASS_TOKENS)[0] if BREAKGLASS_TOKENS else ""
    if bg:
        assert rbac.check("agt_gemini", "run_ps1", token=bg)
        print("  [1] Break-glass: OK")
    assert rbac.check("usr_naarob", "run_ps1")
    assert rbac.check("usr_naarob", "admin")
    print("  [2] Humain ring 0: OK")
    assert not rbac.check("agt_gemini", "write_chunk")
    assert rbac.check("agt_gemini", "read_chunk")
    assert rbac.check("agt_claude", "write_chunk")
    print("  [3] Capabilities: OK")
    p = {"model": "gemini", "tools": [{"name": "web_search"}, {"name": "execute_powershell"}, {"name": "write_chunk"}]}
    f = rbac.filter_tools_payload(p, "agt_gemini")
    names = {t["name"] for t in f["tools"]}
    assert "web_search" in names and "request_powershell_execution" in names and "request_write_chunk" in names
    print(f"  [4] Remplacement outils: OK -> {names}")
    d1 = rbac.shadow_check("agt_cline", "run_python", "delete files")
    assert d1["allowed"] and d1["shadow"]
    d2 = rbac.shadow_check("usr_naarob", "admin", "drop table")
    assert d2["allowed"] and not d2["shadow"]
    print("  [5] Shadow mode: OK")
    bad = RBACMiddleware("/dev/null/bad.db")
    if bg:
        assert bad.check("x", "admin", token=bg)
    print("  [6] DB inaccessible + break-glass: OK")
    print("Self-test PASS")
