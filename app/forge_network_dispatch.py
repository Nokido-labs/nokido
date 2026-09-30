"""
forge_network_dispatch.py — Registre dynamique 5 topologies × 3 modes
======================================================================
Topologies:
  UNI  Unicast   1→1        direct, adressé
  MUL  Multicast 1→N groupe abonnés d'un groupe/tag
  BRD  Broadcast 1→tous    segment complet
  ANY  Anycast   1→1/N     nœud le plus proche/disponible (edge, tulip)
  GEO  Geocast   1→zone    alertes par organe/périmètre Nokido

Modes de retour:
  SNC  Synchrone  attend résultat complet
  ASY  Asynchrone fire-and-forget + job_id SQLite
  STR  Streaming  SSE token par token

Header LF1: LF1.<ring>.<from>.<to>.<pri>.<topo>.<mode>
"""

import asyncio, time, uuid, json, sqlite3, logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("Nokido.NetworkDispatch")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"

# ── Groupes Multicast prédéfinis ─────────────────────────────────────────
MULTICAST_GROUPS = {
    "workers": ["agt_gemini", "agt_codex"],
    "all_llm": ["agt_gemini", "agt_codex", "agt_claude"],
    "local_only": ["agt_codex"],
    "remote": ["agt_gemini"],
    "analysts": ["agt_gemini", "agt_codex"],
    "security": ["agt_claude"],  # organe immunitaire
}

# ── Zones Geocast (organes Nokido) ──────────────────────────────────────
GEO_ZONES = {
    "brain": ["agt_claude", "agt_gemini"],  # cortex + mains
    "immune": ["agt_claude"],  # forge_inspector zone
    "workers": ["agt_gemini", "agt_codex"],
    "ctf": ["agt_gemini"],  # ctf/ agents
    "all": ["agt_gemini", "agt_codex", "agt_claude", "agt_cline"],
}


# ── Anycast : score de disponibilité ──────────────────────────────────────
def _anycast_score(agent: str) -> float:
    """Retourne le score de disponibilité d'un agent (latence inverse)."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=3) as conn:
            row = conn.execute(
                "SELECT latency_ms FROM routing_telemetry WHERE chosen_model LIKE ? ORDER BY ts DESC LIMIT 1",
                (f"%{agent.replace('agt_', '')}%",),
            ).fetchone()
            if row and row[0]:
                return 1.0 / max(row[0], 1)
    except Exception:
        pass
    return 0.5  # score neutre si inconnu


# ── Registre dynamique — source de vérité unique ─────────────────────────
# La clé = code court (3 lettres) → description + handler
TOPOLOGY_REGISTRY = {
    "UNI": {
        "description": "Unicast 1→1 : message direct à un seul agent ciblé",
        "required": ["to", "message"],
        "example": "to=agt_gemini",
    },
    "MUL": {
        "description": "Multicast 1→N : groupe nommé ou liste explicite",
        "required": ["targets", "message"],
        "example": "targets=workers ou targets=gemini,codex",
    },
    "BRD": {
        "description": "Broadcast 1→tous : diffuse à tous les agents actifs",
        "required": ["message"],
        "example": "message=arrêt d'urgence",
    },
    "ANY": {
        "description": "Anycast 1→1/N : nœud le plus disponible (edge/test)",
        "required": ["candidates", "message"],
        "example": "candidates=gemini,codex",
    },
    "GEO": {
        "description": "Geocast 1→zone : alerte par organe/périmètre Nokido",
        "required": ["zone", "message"],
        "example": "zone=immune ou zone=brain",
    },
}

MODE_REGISTRY = {
    "SNC": "Synchrone — attend résultat complet (gather)",
    "ASY": "Asynchrone — fire-and-forget + job_id SQLite",
    "STR": "Streaming — SSE token par token",
}


def get_schema() -> dict:
    """Génère le schéma MCP dynamiquement — jamais hardcodé."""
    topo_enum = list(TOPOLOGY_REGISTRY.keys())
    mode_enum = list(MODE_REGISTRY.keys())
    topo_desc = " | ".join(f"{k}={v['description']}" for k, v in TOPOLOGY_REGISTRY.items())
    mode_desc = " | ".join(f"{k}={v}" for k, v in MODE_REGISTRY.items())
    return {
        "name": "dispatch",
        "description": f"Routage réseau Nokido. Topologies: {topo_desc}. Modes: {mode_desc}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topo": {"type": "string", "enum": topo_enum, "description": "Topologie réseau"},
                "mode": {"type": "string", "enum": mode_enum, "default": "SNC"},
                "to": {"type": "string", "description": "UNI: agent cible"},
                "targets": {"type": "string", "description": "MUL: groupe ou liste"},
                "zone": {"type": "string", "description": "GEO: zone/organe"},
                "candidates": {"type": "string", "description": "ANY: liste candidats"},
                "message": {"type": "string"},
                "intent": {"type": "string", "description": "intent machine-readable"},
                "payload": {"type": "object", "description": "données structurées"},
                "tool_defs": {"type": "array", "description": "tools injectés aux agents"},
            },
            "required": ["topo", "message"],
        },
    }


# ── Résolution des cibles ─────────────────────────────────────────────────
def _resolve_targets(topo: str, args: dict) -> list[str]:
    ALIAS = {"gemini": "agt_gemini", "codex": "agt_codex", "claude": "agt_claude", "cline": "agt_cline"}
    ALL = ["agt_gemini", "agt_codex", "agt_claude", "agt_cline"]

    if topo == "UNI":
        to = args.get("to", "").strip()
        return [ALIAS.get(to, to)] if to else []

    if topo == "MUL":
        raw = args.get("targets", "").strip()
        targets = set()
        for t in raw.split(","):
            t = t.strip().lower()
            if t in MULTICAST_GROUPS:
                targets.update(MULTICAST_GROUPS[t])
            elif t in ALIAS:
                targets.add(ALIAS[t])
            elif t.startswith("agt_"):
                targets.add(t)
        return sorted(targets)

    if topo == "BRD":
        return ALL

    if topo == "ANY":
        raw = args.get("candidates", "").strip()
        cands = [ALIAS.get(c.strip(), c.strip()) for c in raw.split(",") if c.strip()]
        if not cands:
            cands = ALL
        # Choisir le plus disponible
        return [max(cands, key=_anycast_score)]

    if topo == "GEO":
        zone = args.get("zone", "all").strip().lower()
        return GEO_ZONES.get(zone, GEO_ZONES["all"])

    return []


# ── Envoi vers un agent ───────────────────────────────────────────────────
def _send_to_agent(from_agent: str, to_agent: str, msg: str, intent: str, tool_defs: list, job_id: str) -> bool:
    """Insère dans agent_messages avec validation tool_defs."""
    try:
        # Validation : si tool_defs requis, vérifier présence
        if tool_defs and not isinstance(tool_defs, list):
            logger.warning(f"tool_defs invalide pour {to_agent} — ignoré")
            tool_defs = []

        from nokido_agent.app.forge_jwt_router import forge_frame_token

        jwt_tok = forge_frame_token(from_agent=from_agent, to_agent=to_agent, intent=intent or "notify_agent")
    except Exception:
        jwt_tok = ""

    payload = json.dumps(
        {
            "text": msg[:120],
            "aud": to_agent,
            "from": from_agent,
            "intent": intent or "notify_agent",
            "job_id": job_id,
            "jwt_token": jwt_tok,
            "tool_defs": tool_defs,  # injectés pour éviter les "outils fantômes"
        },
        ensure_ascii=False,
    )

    import hashlib, time as _t

    frame_id = "frm_" + hashlib.md5(f"{from_agent}{to_agent}{_t.time()}".encode()).hexdigest()[:12]
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M : la table suit l'interrupteur ; DB_PATH reste pour routing_telemetry
    with sqlite3.connect(_m2m_path(), timeout=5) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO agent_messages"
            "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (frame_id, from_agent, to_agent, job_id, "tool.hub.frame.task", payload, "unread", now),
        )
        conn.commit()
    return True


# ── Dispatcher principal ──────────────────────────────────────────────────
async def dispatch(args: dict, agent: str, ring: int) -> dict:
    """
    Point d'entrée unique. Retourne toujours:
    {ok, topo, mode, targets, job_id, results (SNC) ou job_id (ASY)}
    """
    topo = args.get("topo", "UNI").upper()
    mode = args.get("mode", "SNC").upper()
    msg = args.get("message", "")
    intent = args.get("intent", "notify_agent")
    payload = args.get("payload", {})
    tool_defs = args.get("tool_defs", [])

    if topo not in TOPOLOGY_REGISTRY:
        return {"ok": False, "error": f"Topologie inconnue: {topo}. Dispo: {list(TOPOLOGY_REGISTRY)}"}
    if mode not in MODE_REGISTRY:
        mode = "SNC"

    targets = _resolve_targets(topo, args)
    if not targets:
        return {"ok": False, "error": f"Aucune cible résolue pour {topo}"}

    job_id = f"job_{topo}_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ── MODE ASY : fire-and-forget ────────────────────────────────────────
    if mode == "ASY":

        async def _bg():
            for t in targets:
                _send_to_agent(agent, t, msg, intent, tool_defs, job_id)
                await asyncio.sleep(0.05)

        asyncio.create_task(_bg())
        return {
            "ok": True,
            "topo": topo,
            "mode": "ASY",
            "targets": targets,
            "job_id": job_id,
            "status": "accepted — résultat dans agent_messages",
        }

    # ── MODE SNC : gather synchrone ───────────────────────────────────────
    results = {}
    for t in targets:
        ok = _send_to_agent(agent, t, msg, intent, tool_defs, job_id)
        results[t] = "ok" if ok else "err"

    summary = f"{topo}({mode}) → {len(targets)} cibles | job={job_id} | " + " ".join(
        f"{t.replace('agt_', '')}:{s}" for t, s in results.items()
    )

    return {
        "ok": True,
        "topo": topo,
        "mode": mode,
        "targets": targets,
        "job_id": job_id,
        "results": results,
        "summary": summary,
    }
