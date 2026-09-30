"""
forge_meta_tools.py — Nokido v18.5
=====================================
8 méta-outils MCP pour réduire 88% des tokens payload LLM.
Remplace 33 handlers atomiques par des abstractions haut niveau.

PRINCIPE (Gemini doc) :
  Le LLM distant reçoit 8 outils simples (~150 tokens chacun = 1200 tokens total).
  Chaque méta-outil délègue à l'orchestration locale (Hub Python).
  Le LLM ne voit jamais la plomberie interne (SQLite, FAISS, FTS5...).

ANTI-YOLO intégré :
  - draft_plan() : génère un plan SANS exécuter (le seul outil créatif)
  - Toute action destructive → promotion_queue → validation humaine
  - SAFE_COMMANDS : liste blanche des appels autonomes permis

RÉDUCTION TOKENS :
  Avant : 33 handlers × 300 tokens = 9900 tokens
  Après : 8 méta-outils × 150 tokens = 1200 tokens (-88%)
  + Prompt Caching Anthropic sur le bloc statique → -90% coût supplémentaire

INTÉGRATION :
  from forge_meta_tools import META_TOOL_SCHEMAS, handle_meta_tool, is_safe_autonomous
  # Injecter META_TOOL_SCHEMAS dans le payload API au lieu des 33 handlers
  # Appeler handle_meta_tool(name, args, entity_id, token) pour dispatcher
"""

from __future__ import annotations
import json
import re
import sqlite3
import logging
import datetime
from pathlib import Path
from typing import Optional, Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
# ═══════════════════════════════════════════════════════════════════════════
# PATH SANITIZER — Pilier 2 anti-YOLO (Gemini security cage)
# ═══════════════════════════════════════════════════════════════════════════

_DANGEROUS_PATH_PATTERN = re.compile(
    r"(\.\.[/\\]|"  # ../  ..\ path traversal
    r"^[A-Za-z]:[/\\]|"  # C:\ D:// chemins absolus Windows
    r"^/etc/|^/root/|^/proc/|"  # chemins systeme Linux
    r"/shadow|/passwd|/sudoers)",  # fichiers critiques
    re.IGNORECASE,
)


def _sanitize_path(value: Any, context: str = "") -> tuple[bool, str]:
    """
    Vérifie qu un argument ne contient pas de path traversal ou chemin absolu dangereux.
    Returns (safe: bool, reason: str)
    """
    if not isinstance(value, str):
        return True, "non-string"
    if _DANGEROUS_PATH_PATTERN.search(value):
        reason = f"path dangereux detecte dans {context}: {value[:50]}"
        logger.warning(f"PATH_BLOCK: {reason}")
        return False, reason
    return True, "ok"


def _sanitize_args(args: dict) -> tuple[bool, str]:
    """Vérifie tous les args string d un tool call."""
    for k, v in args.items():
        safe, reason = _sanitize_path(v, context=k)
        if not safe:
            return False, reason
    return True, "ok"


# ═══════════════════════════════════════════════════════════════════════════
# SAFE_COMMANDS — Liste blanche autonomie sans confirmation
# ═══════════════════════════════════════════════════════════════════════════

# Patterns SQL sûrs (lecture seule)
_SAFE_SQL_PATTERN = re.compile(r"^\s*SELECT", re.IGNORECASE)
_DANGEROUS_SQL_PATTERN = re.compile(r"(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|REPLACE)", re.IGNORECASE)

# Patterns code Python sûrs
_SAFE_PYTHON_PATTERN = re.compile(
    r"^\s*(print|len|type|list|dict|str|int|float|sum|max|min|sorted|"
    r"json\.dumps|json\.loads|datetime|os\.path\.exists|os\.listdir)\(",
    re.IGNORECASE,
)
_DANGEROUS_PYTHON_PATTERN = re.compile(
    r"(open\s*\(.*[waxb]|subprocess|os\.system|os\.remove|shutil\.|"
    r"exec\s*\(|eval\s*\(|__import__|importlib)",
    re.IGNORECASE,
)


def is_safe_autonomous(tool_name: str, args: dict) -> tuple[bool, str]:
    """
    Vérifie si un appel peut être exécuté de manière autonome (sans confirmation humaine).

    Returns:
        (True, "raison") si sûr
        (False, "raison") si confirmation requise
    """
    # Outils always-safe (lecture pure)
    always_safe = {
        "query_knowledge",
        "system_status",
        "web_fetch",
        "agent_delegate",  # délégation LLM — pas d'action système
    }
    if tool_name in always_safe:
        return True, "outil lecture-seule"

    # draft_plan — sûr car aucune exécution
    if tool_name == "draft_plan":
        return True, "dry-run par définition"

    # notify_and_log — sûr (écriture TUI uniquement)
    if tool_name == "notify_and_log":
        return True, "notification TUI seulement"

    # manage_task — sûr pour status/claim, dangereux pour approve
    if tool_name == "manage_task":
        action = args.get("action", "")
        if action in ("status", "claim", "result"):
            return True, f"manage_task.{action} = lecture/résultat"
        if action == "approve":
            return False, "approve nécessite validation humaine ring=0"

    # execute_action — toujours confirmation
    if tool_name == "execute_action":
        action_type = args.get("type", "")
        safe_read_types = {"read", "search", "rag_search", "query_select"}
        if action_type in safe_read_types:
            return True, f"execute_action type={action_type} lecture seule"
        return False, f"execute_action type={action_type} nécessite confirmation"

    # SQL inline — analyser le contenu
    if "sql" in args or "query" in args:
        sql = args.get("sql", args.get("query", ""))
        if _DANGEROUS_SQL_PATTERN.search(sql):
            return False, f"SQL dangereux détecté: {sql[:50]}"
        if _SAFE_SQL_PATTERN.match(sql):
            return True, "SQL SELECT read-only"

    # Python inline — analyser le code
    if "code" in args:
        code = args.get("code", "")
        if _DANGEROUS_PYTHON_PATTERN.search(code):
            return False, f"Python dangereux détecté: {code[:50]}"

    # PATH CHECK final
    safe_p, reason_p = _sanitize_args(args)
    if not safe_p:
        return False, reason_p

    return False, "precaution par defaut"


# ═══════════════════════════════════════════════════════════════════════════
# META-TOOL SCHEMAS — Ce que le LLM distant voit (1200 tokens total)
# ═══════════════════════════════════════════════════════════════════════════

META_TOOL_SCHEMAS = [
    {
        "name": "query_knowledge",
        "description": (
            "Cherche dans la base de connaissances Nokido. "
            "Combine automatiquement recherche sémantique (vecteurs), "
            "FTS5 (texte) et SQL selon le besoin. "
            "SAFE: lecture seule, aucune confirmation requise."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question ou terme à chercher"},
                "domain": {
                    "type": "string",
                    "description": "Domaine optionnel: code|security|devops|ia|general|nokido_code",
                },
                "mode": {"type": "string", "enum": ["semantic", "fts", "sql", "auto"], "default": "auto"},
                "limit": {"type": "integer", "default": 5, "description": "Nombre de résultats"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "draft_plan",
        "description": (
            "ANTI-YOLO: Génère un plan d'exécution JSON SANS l'exécuter. "
            "Le plan sera soumis à validation humaine (ring=0) avant toute action. "
            "Utilise TOUJOURS cet outil en premier pour toute action système."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Titre de la tâche"},
                "description": {"type": "string", "description": "Description de l'intention"},
                "task_type": {
                    "type": "string",
                    "enum": ["devops", "code", "research", "maintenance", "security", "generic"],
                },
                "steps": {
                    "type": "array",
                    "description": "Liste des étapes planifiées",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "action": {"type": "string"},
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "risk": {"type": "string", "enum": ["safe", "medium", "destructive"]},
                        },
                        "required": ["step", "action", "tool", "risk"],
                    },
                },
                "estimated_tokens_saved": {
                    "type": "integer",
                    "description": "Tokens LLM économisés si Golden Path créé",
                },
            },
            "required": ["title", "description", "steps"],
        },
    },
    {
        "name": "execute_action",
        "description": (
            "Exécute une action validée. REQUIERT approbation humaine sauf pour "
            "les types lecture-seule (read, search, rag_search, query_select). "
            "Pour toute écriture: créer d'abord un draft_plan."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["python", "ps1", "read", "write", "rag_search", "query_select", "query_mutate"],
                    "description": "Type d'action",
                },
                "payload": {"type": "string", "description": "Code ou requête à exécuter"},
                "approved_plan_id": {"type": "string", "description": "ID du plan approuvé (requis pour mutations)"},
            },
            "required": ["type", "payload"],
        },
    },
    {
        "name": "manage_task",
        "description": "Gère le cycle de vie des tâches agent_tasks. status/claim sont autonomes. approve nécessite ring=0.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["assign", "claim", "result", "status", "approve", "reject"]},
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "task_type": {"type": "string"},
                "result": {"type": "string", "description": "JSON résultat pour action=result"},
                "plan": {"type": "string", "description": "JSON plan pour action=assign"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "notify_and_log",
        "description": "Envoie une notification TUI et/ou log un événement. SAFE: aucune confirmation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "level": {"type": "string", "enum": ["info", "success", "warning", "error"], "default": "info"},
                "target": {"type": "string", "enum": ["tui", "rag", "both"], "default": "tui"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "agent_delegate",
        "description": "Délègue une sous-tâche à un agent expert (Claude, Gemini, local Ollama). SAFE pour analyse. Résultat retourné directement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "enum": ["claude", "gemini", "ollama", "auto"], "default": "auto"},
                "prompt": {"type": "string", "description": "Tâche à déléguer"},
                "context": {"type": "string", "description": "Contexte additionnel optionnel"},
                "max_tokens": {"type": "integer", "default": 500},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Recherche sur le web via SearXNG local. SAFE: lecture seule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "domain": {"type": "string", "description": "Domaine de recherche optionnel"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "system_status",
        "description": "Retourne l'état du système Nokido: mode, services actifs, métriques DB, tâches en cours. SAFE: lecture seule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["all", "hub", "db", "tasks", "agents", "broker"],
                    "default": "all",
                },
            },
            "required": [],
        },
    },
]

# Index pour lookup rapide
_SCHEMA_BY_NAME = {s["name"]: s for s in META_TOOL_SCHEMAS}


def get_tool_schema(name: str) -> Optional[dict]:
    return _SCHEMA_BY_NAME.get(name)


def get_filtered_schemas(intent_category: str) -> list[dict]:
    """
    Retourne uniquement les méta-outils pertinents pour une catégorie d'intention.
    Réduit encore plus les tokens selon le contexte.

    intent_category: analyse|execution|communication|all
    """
    if intent_category == "analyse":
        # Lecture pure → pas d'execute_action ni draft_plan avec steps destructifs
        return [
            s
            for s in META_TOOL_SCHEMAS
            if s["name"] in ("query_knowledge", "web_fetch", "system_status", "notify_and_log", "agent_delegate")
        ]
    if intent_category == "execution":
        # Action planifiée → draft_plan OBLIGATOIRE en premier
        return [
            s
            for s in META_TOOL_SCHEMAS
            if s["name"] in ("draft_plan", "execute_action", "manage_task", "query_knowledge", "notify_and_log")
        ]
    if intent_category == "communication":
        return [s for s in META_TOOL_SCHEMAS if s["name"] in ("notify_and_log", "agent_delegate", "manage_task")]
    return META_TOOL_SCHEMAS  # all


def token_estimate() -> dict:
    """Estime les tokens économisés vs catalogue complet."""
    full_33 = 33 * 300
    meta_8 = sum(len(json.dumps(s)) // 4 for s in META_TOOL_SCHEMAS)
    return {
        "full_catalog_tokens": full_33,
        "meta_tools_tokens": meta_8,
        "reduction_pct": round((1 - meta_8 / full_33) * 100),
        "schemas_count": len(META_TOOL_SCHEMAS),
    }


# ═══════════════════════════════════════════════════════════════════════════
# HANDLER — Dispatcher méta-outil → Hub MCP existant
# ═══════════════════════════════════════════════════════════════════════════


async def handle_meta_tool(
    name: str,
    args: dict,
    entity_id: str = "laforge",
    token: str = "",
) -> str:
    """
    Dispatch un appel méta-outil vers les handlers Hub existants.
    Vérifie RBAC + SAFE_COMMANDS avant tout appel.
    """
    # 1. RBAC check
    try:
        from nokido_agent.app.forge_rbac import get_rbac, is_breakglass

        rbac = get_rbac()
        if not is_breakglass(token):
            # Mapper méta-outil → capability RBAC
            cap_map = {
                "query_knowledge": "read_db",
                "draft_plan": "task_create",
                "execute_action": "run_python",
                "manage_task": "task_result",
                "notify_and_log": "tui_notify",
                "agent_delegate": "web_search",
                "web_fetch": "web_search",
                "system_status": "read_db",
            }
            cap = cap_map.get(name, "read_db")
            if not rbac.check(entity_id, cap, token=token):
                return f"RBAC_DENIED: {entity_id} n'a pas [{cap}] pour [{name}]"
    except Exception as e:
        logger.debug(f"RBAC skip: {e}")

    # 2. SAFE_COMMANDS check
    safe, reason = is_safe_autonomous(name, args)
    if not safe:
        # Envoyer vers promotion_queue pour validation humaine
        return await _queue_for_approval(name, args, entity_id, reason)

    # 2b. PATH SANITIZER — bloquer path traversal avant tout dispatch
    safe_path, path_reason = _sanitize_args(args)
    if not safe_path:
        # Logger la tentative
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=3)
            conn.execute(
                "INSERT INTO event_log(timecode,agent_id,event_type,target,payload,status,sequence_id,session_id,prev_hash,new_hash)"
                " VALUES(datetime('now'),?,'path_traversal_block',?,?,'blocked',0,'','','')",
                (entity_id, name, str(args)[:200]),
            )
            conn.commit()
            conn.close()
        except:
            pass
        return f"SECURITY_BLOCK: {path_reason}"

    # ═══════════════════════════════════════════════════════════════════════════

    # 2b-bis. SANDBOX GUARD — pré-validation + quota avant execute_action
    if name == "execute_action":
        try:
            import sys as _sys

            _sys.path.insert(0, str(DB_PATH.parent.parent / "app"))
            from nokido_agent.app.forge_sandbox_guard import prevalidate_code, get_quota

            # Quota check
            _q = get_quota()
            _qcheck = _q.check(entity_id)
            if not _qcheck["allowed"]:
                return f"QUOTA_EXCEEDED: {entity_id} — {_qcheck['reason']} (iter={_qcheck['iter']}, calls={_qcheck['calls']})"
            # Pré-validation code
            _payload = args.get("payload", "")
            if args.get("type", "") == "python" and _payload:
                _validation = prevalidate_code(_payload, "python")
                if not _validation["valid"]:
                    return f"PREVALIDATION_FAIL: {'; '.join(_validation['errors'])}"
                if _validation["warnings"]:
                    logger.warning(f"Code warnings: {_validation['warnings']}")
            # Incrémenter quota
            _q.increment(entity_id, sandbox=True)
        except Exception as _sge:
            logger.debug(f"SandboxGuard skip: {_sge}")

    # 2c. CERBERUSGUARD — scoring RF (cerberus_predictor.pkl, threshold=0.45)
    if name == "execute_action":
        try:
            import pickle as _pk

            _pkl = str(DB_PATH.parent.parent / "shadow_mutation" / "ml_models" / "cerberus_predictor.pkl")
            with open(_pkl, "rb") as _f:
                _c = _pk.load(_f)
            _at = args.get("type", "")
            _pl = args.get("payload", "")
            _vec = [
                [
                    1.0 if _at in ("python", "ps1", "query_mutate") else 0.3,
                    _pl.count("def "),
                    _pl.count("class "),
                    0.7,
                    1,
                    1 if "local" in entity_id else 0,
                    1 if "groq" in entity_id else 0,
                ]
            ]
            _score = _c["model"].predict_proba(_vec)[0][1]
            if _score > _c.get("threshold", 0.45):
                logger.warning(f"CerberusGuard BLOCK score={_score:.3f} entity={entity_id}")
                return await _queue_for_approval(
                    name, args, entity_id, f"CerberusGuard RF score={_score:.3f} > {_c.get('threshold', 0.45)}"
                )
        except Exception as _ce:
            logger.debug(f"CerberusGuard skip: {_ce}")

    # 3. Dispatcher vers les handlers Hub existants
    try:
        import asyncio

        if name == "query_knowledge":
            return await _handle_query_knowledge(args)
        elif name == "draft_plan":
            return await _handle_draft_plan(args, entity_id)
        elif name == "execute_action":
            return await _handle_execute_action(args, entity_id, token)
        elif name == "manage_task":
            return await _handle_manage_task(args, entity_id)
        elif name == "notify_and_log":
            return await _handle_notify(args)
        elif name == "agent_delegate":
            return await _handle_delegate(args, entity_id)
        elif name == "web_fetch":
            return await _handle_web_fetch(args)
        elif name == "system_status":
            return await _handle_system_status(args)
        elif name == "run_pipeline":
            try:
                import sys as _s2

                _s2.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
                from nokido_agent.app.forge_sandbox_guard import run_analysis_pipeline

                return __import__("json").dumps(run_analysis_pipeline(args.get("pipeline", "agent_status"), entity_id))
            except Exception as e:
                return f"ERR pipeline: {e}"
        else:
            return f"ERR: méta-outil inconnu: {name}"
    except Exception as e:
        logger.error(f"handle_meta_tool {name} err: {e}")
        return f"ERR: {e}"


async def _queue_for_approval(name: str, args: dict, entity_id: str, reason: str) -> str:
    """Route vers promotion_queue + notifie TUI pour validation humaine."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        import hashlib, time

        plan_id = hashlib.sha256(f"{name}{json.dumps(args)}{time.time()}".encode()).hexdigest()[:16]
        conn.execute(
            "INSERT OR IGNORE INTO promotion_queue "
            "(chunk_id, priority, author_id, status, source_type, tool_name, enqueued_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (plan_id, 3, entity_id, "pending", "meta_tool_approval", name, datetime.datetime.now().isoformat()),
        )
        conn.commit()
        # Notification TUI
        msg = (
            "ACTION EN ATTENTE [" + name + "] par " + entity_id + "\n"
            "Raison: " + reason + "\n"
            "Args: " + json.dumps(args, ensure_ascii=False)[:200] + "\n"
            "Plan ID: " + plan_id + "\n"
            "Approuver: manage_task(action=approve, task_id=" + plan_id + ")"
        )
        conn.execute(
            "INSERT INTO tui_notifications(source,type,message,status) VALUES(?,?,?,?)",
            ("hub", "action", msg, "unread"),
        )
        conn.commit()
        conn.close()
        return f"PENDING_APPROVAL: action [{name}] mise en queue (id={plan_id}). Validation humaine requise."
    except Exception as e:
        return f"ERR queue_approval: {e}"


async def _handle_query_knowledge(args: dict) -> str:
    """query_knowledge → forge_rag_engine + FTS5 + SQL."""
    try:
        from app.api_facade import get_async_facade

        facade = get_async_facade()
        result = await facade.rag_query(args["query"], domain=args.get("domain"), topk=args.get("limit", 5))
        return json.dumps(result, ensure_ascii=False)[:2000]
    except Exception:
        # Fallback FTS5 direct
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        q = args["query"].replace('"', "").replace("'", "")
        try:
            rows = conn.execute(
                "SELECT text, domain, source FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ? LIMIT ?",
                (q, args.get("limit", 5)),
            ).fetchall()
            conn.close()
            return json.dumps([{"text": r[0][:300], "domain": r[1], "source": r[2]} for r in rows])
        except:
            conn.close()
            return "ERR: RAG indisponible"


async def _handle_draft_plan(args: dict, entity_id: str) -> str:
    """draft_plan → INSERT agent_tasks status=review, verdict vide."""
    import hashlib, time

    task_id = hashlib.sha256(f"{args['title']}{time.time()}".encode()).hexdigest()[:16]
    plan = json.dumps(args.get("steps", []), ensure_ascii=False)
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT OR IGNORE INTO agent_tasks "
        "(id, title, description, task_type, plan, status, executor, orchestrator, meta) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            args["title"],
            args["description"],
            args.get("task_type", "generic"),
            plan,
            "review",
            entity_id,
            "laforge",
            json.dumps({"draft": True, "estimated_tokens_saved": args.get("estimated_tokens_saved", 0)}),
        ),
    )
    # Notification TUI
    conn.execute(
        "INSERT INTO tui_notifications(source,type,message,status) VALUES(?,?,?,?)",
        (
            "hub",
            "action",
            (
                "PLAN EN ATTENTE: " + args["title"] + "\n"
                "Etapes: " + str(len(args.get("steps", []))) + "\n"
                "Task ID: " + task_id + "\n"
                "Approuver: manage_task(action=approve, task_id=" + task_id + ")"
            ),
            "unread",
        ),
    )
    conn.commit()
    conn.close()
    return json.dumps(
        {"status": "draft_created", "task_id": task_id, "message": "Plan créé, en attente validation humaine"}
    )


async def _handle_execute_action(args: dict, entity_id: str, token: str) -> str:
    """execute_action → dispatch vers handlers Hub selon type."""
    from nokido_agent.app.forge_mcp_registry import get_registry

    action_type = args.get("type", "")
    payload = args.get("payload", "")
    if action_type == "python":
        return await get_registry().handle_run({"action": "python", "code": payload}, entity_id, 0)
    elif action_type in ("read", "query_select", "rag_search"):
        return await get_registry().handle_read({"action": "file", "path": payload}, entity_id, 0)
    return f"PENDING_APPROVAL: execute_action type={action_type} requires human approval"


async def _handle_manage_task(args: dict, entity_id: str) -> str:
    from nokido_agent.app.forge_mcp_registry import get_registry

    return await get_registry().handle_task(args, entity_id, 0)


async def _handle_notify(args: dict) -> str:
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute(
        "INSERT INTO tui_notifications(source,type,message,status) VALUES(?,?,?,?)",
        ("meta_tool", args.get("level", "info"), args["message"], "unread"),
    )
    conn.commit()
    conn.close()
    return "OK notifié"


async def _handle_delegate(args: dict, entity_id: str) -> str:
    from nokido_agent.app.forge_mcp_registry import get_registry

    provider = args.get("provider", "auto")
    prompt = args.get("prompt", "")
    if provider in ("claude", "auto"):
        return await get_registry().handle_ask_claude({"message": prompt}, entity_id, 0)
    return await get_registry().handle_ask_gemini({"message": prompt}, entity_id, 0)


async def _handle_web_fetch(args: dict) -> str:
    from nokido_agent.app.forge_mcp_registry import get_registry

    return await get_registry().handle_web_search({"query": args["query"]}, "meta", 0)


async def _handle_system_status(args: dict) -> str:
    scope = args.get("scope", "all")
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    status = {}
    if scope in ("all", "tasks"):
        status["tasks"] = {
            "approved": conn.execute(
                "SELECT COUNT(*) FROM agent_tasks WHERE forge_verdict='approved' AND status='done'"
            ).fetchone()[0],
            "pending": conn.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='pending'").fetchone()[0],
            "review": conn.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='review'").fetchone()[0],
        }
    if scope in ("all", "db"):
        status["db"] = {
            "chunks": conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0],
            "vectorized": conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0],
        }
    if scope in ("all", "broker"):
        import os

        hb = Path(__file__).parent.parent / "sandbox" / "forge_collab_broker.log"
        status["broker"] = {"active": hb.exists(), "log_size": hb.stat().st_size if hb.exists() else 0}
    conn.close()
    return json.dumps(status, ensure_ascii=False)


# Self-test
if __name__ == "__main__":
    import asyncio

    print("=== forge_meta_tools self-test ===\n")

    # Token count
    est = token_estimate()
    print(f"Tokens: {est['full_catalog_tokens']} → {est['meta_tools_tokens']} (-{est['reduction_pct']}%)")
    print(f"Schémas: {est['schemas_count']} méta-outils")

    # SAFE_COMMANDS
    tests = [
        ("query_knowledge", {"query": "nginx"}, True),
        ("execute_action", {"type": "python", "payload": "print(1)"}, False),
        ("execute_action", {"type": "read", "payload": "/tmp/x"}, True),
        ("draft_plan", {"title": "t", "description": "d", "steps": []}, True),
        ("manage_task", {"action": "approve"}, False),
        ("manage_task", {"action": "status"}, True),
    ]
    print("\nSAFE_COMMANDS checks:")
    all_ok = True
    for name, args, expected_safe in tests:
        safe, reason = is_safe_autonomous(name, args)
        icon = "✓" if safe == expected_safe else "✗"
        if safe != expected_safe:
            all_ok = False
        print(f"  {icon} {name}({list(args.keys())}) → safe={safe} [{reason[:40]}]")

    # Filtered schemas
    for cat in ["analyse", "execution", "communication"]:
        schemas = get_filtered_schemas(cat)
        names = [s["name"] for s in schemas]
        print(f"\nFiltered [{cat}]: {names}")

    print(f"\nSelf-test: {'PASS' if all_ok else 'FAIL'}")
