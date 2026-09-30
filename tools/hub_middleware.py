"""
tools/hub_middleware.py
========================
KNOWLEDGE_HARVESTER_V1 — Security Middleware
INPUT_VALIDATION + PATH_SANITIZATION
Scope : nokido_hub.py gateway — rings 0/1/2 non touches
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("forge.middleware")

# ── Patterns interdits ────────────────────────────────────────────────────────
_BLOCKED_PATH_PATTERNS = [
    re.compile(r"\.\.[\\/]"),  # path traversal ../
    re.compile(r"^[\\/]etc[\\/]"),  # /etc/
    re.compile(r"^[\\/]proc[\\/]"),  # /proc/
    re.compile(r"win(dows)?[\\/]system"),  # Windows system
    re.compile(r"\.\.(\\|/)"),  # ..\
    re.compile(r"%2e%2e", re.I),  # URL encoded ..
    re.compile(r"\x00"),  # null bytes
]

# Toujours bloqués — attaques d'injection réelles (XSS, SQLi, JS)
_INJECTION_PATTERNS = [
    re.compile(r"<script[^>]*>", re.I),  # XSS
    re.compile(r"javascript:", re.I),  # JS injection
    re.compile(r"union\s+select", re.I),  # SQLi union
    re.compile(r";\s*(drop|truncate)\s+", re.I),  # SQLi DDL destructif
]

# Heuristiques — bloquées partout SAUF pour les champs de recherche locale
# (orchestrate.task, run.code) où du code Python légitime est attendu
# Gestionnaires d'evenements HTML, NOMMES un par un (mesure 2026-07-31).
# Le motif precedent etait « frontiere + o-n + mot + egal », qui attrapait TOUT
# argument nomme Python dont le nom commence par ces deux lettres -- quatre formes
# courantes verifiees bloquees (drapeau reseau du job runner, compteur unique,
# selecteur, et le on-delete de Django), alors que `x = 1` passait. Consequence :
# governed_edit refusait des editions legitimes sans nommer le motif, donc sans que
# l'appelant puisse corriger -- et le refus se franchissait PAR ACCIDENT en decoupant
# l'edition en blocs plus petits. Un garde qu'on traverse sans le vouloir ne protege
# pas ; celui-ci est desormais precis. La couverture des vecteurs XSS reels est
# INTACTE : ce sont exactement ces noms-la, et aucun n'est un identifiant Python.
_HTML_EVENT_HANDLERS = (
    "onerror|onload|onclick|ondblclick|onmouseover|onmouseenter|onmouseleave|"
    "onmousedown|onmouseup|onmousemove|onfocus|onfocusin|onblur|onsubmit|onreset|"
    "onchange|oninput|onselect|onkeydown|onkeyup|onkeypress|onwheel|onscroll|"
    "onresize|ontoggle|onbeforeunload|onpageshow|onpagehide|onhashchange|onmessage|"
    "onpopstate|onstorage|onunload|onauxclick|oncontextmenu|ondrag|ondragstart|"
    "ondragover|ondrop|onplay|oncanplay|onplaying|onpause|onended|onloadstart|"
    "onloadeddata|onprogress|onanimationstart|onanimationend|onanimationiteration|"
    "ontransitionend|oncut|oncopy|onpaste|onpointerdown|onpointerover|onpointerenter|"
    "ontouchstart|ontouchmove|ontouchend|onshow|oninvalid|onsearch|onwaiting"
)

_HEURISTIC_PATTERNS = [
    re.compile(r"\b(" + _HTML_EVENT_HANDLERS + r")\s*=", re.I),  # XSS event handlers
    re.compile(r"exec\s*\(", re.I),  # exec() arbitraire (faux positif sur exec_run, -exec-mi)
    re.compile(r";\s*(delete|insert)\s+", re.I),  # SQLi DML (faux positif sur code Python)
]

# Champs exemptés des heuristiques — uniquement pour exécution locale ring ≤ 1
# Le contenu reste dans la machine, XSS/SQLi toujours vérifiés.
# ask.message = prompt LLM : porte légitimement du code / type hints
# (ex: `package: str | None = None`) — heuristiques code = faux positifs.
_RESEARCH_FIELDS: dict[str, set[str]] = {
    "orchestrate": {"task"},
    "run": {"code"},
    "ask": {"message"},
    "oracle_python_repl": {"code"},  # Oracle REPL : code = exécution locale sandbox (comme run.code)
    # governed_edit et blackboard_propose_fact ont ete AJOUTES ici le 2026-07-31 puis
    # RETIRES le meme jour, apres mesure. L'exemption reglait bien le faux positif,
    # mais elle ouvrait un trou verifie : un attribut de gestionnaire d'evenement
    # injecte dans une balise passait alors sans obstacle vers un fichier du depot,
    # que le web_hub sert ensuite a un navigateur. Le faux positif d'origine se
    # corrige entierement en RESSERRANT le motif (voir _HTML_EVENT_HANDLERS) ; il
    # n'exigeait aucune levee de garde. Corriger le diagnostic, jamais contourner
    # le garde. Consequence assumee et connue : un appel dynamique litteral dans
    # `blocks` reste refuse -> passer par un patcher committe + trusted_script,
    # chemin deja obligatoire pour les CRITICAL_FILES.
}

# Rétro-compatibilité : vue unifiée pour code existant hors validate_arguments
_BLOCKED_CONTENT_PATTERNS = _INJECTION_PATTERNS + _HEURISTIC_PATTERNS

_ALLOWED_TOOLS = {
    "read",
    "write",
    "query",
    "run",
    "get_mode",
    "set_mode",
    "notify",
    "poll",
    "index_result",
    "search_recent",
    "auto_test",
    "rag_search",
    "rag_ingest_text",
    "rag_stats",
    "swarm_status",
    "llm_generate",
    "code_py_compile",
    "code_run_python",
    "events_recent",
    "sentinel_check",
    "sentinel_status",
    "adr_list",
    "adr_create",
    "adr_check_drift",
    "services_status",
    "service_start",
    "service_stop",
    "task_assign",
    "task_claim",
    "task_result",
    "task_status",
    "trigger_autonomous_evolution",
    "web_search",
    "route_task",
    "research_agent",
    "ask",
    "hub",
    "task",
    "event",
    "rag",
    "web_search_rag",
    "ask_gemini",
    "ask_claude",
    "ask_agent",
    "agent_debate",
    "list_providers",
    "event_history",
    "restart_claude",
    "ps_run",
    "ps_agent",
    "memory",
    "agent_send",
    "agent_recv",
    "biblio",
    "orchestrate",
    # netcfg-agent-mcp tools (proxied to :8767)
    "netcfg_ping",
    "netcfg_vendors",
    "netcfg_list_equipments",
    "netcfg_get_dashboard",
    "netcfg_topology",
    "netcfg_audit",
    "netcfg_verify_chain",
    "netcfg_preview_deploy",
    "netcfg_open_terminal",
    "netcfg_export_topology",
    "netcfg_vendor_search",
    "netcfg_vendor_stats",
    "manage_forge_lifecycle",
    # netcfg unifie (verb-dispatcher)
    "netcfg",
    # Exegol MCP (verb-dispatcher : status / list_containers / list_tools / exec / start / stop)
    "exegol",
    # CTF Browser MCP :8771 (verb-dispatcher Playwright Firefox user-session + Root-Me)
    "ctf_browser",
    # Autonomous CTF solver silo (ReAct loop Ollama + ctf_browser via hub)
    "ctf_solver",
    # Verbes session 2026-05-31 : Oracle REPL (GOAP doute→test) + ForgeSwarm + ForgeAudit
    "oracle_python_repl",
    "forge_spawn_swarm",
    "forge_trigger_audit",
    # Capteurs code (pagination sémantique) + blackboard swarm — étaient
    # enregistrés au registre/rbac mais ABSENTS de cette allowlist /mcp -> 400
    # "not allowed" sur tout appel HTTP (planner orchestrate, clients MCP).
    "read_function_body",
    "get_file_skeleton",
    "get_function_dependencies",
    "blackboard_read_zone",
    "blackboard_propose_fact",
    "forge_stats",
    "skill",
    # Honeypot delegation : recon LOCALE souveraine (anti-fuite-tokens, 0 token cloud)
    "forge_deep_explore",
    # Bouton rouge declaratif : ensure service state (anti-bricolage infra client)
    "nokido_ensure_service",
    # Edition GOUVERNEE in-process (pont client : remplace le Write natif non-gouverne)
    "governed_edit",
    "tool_scope",
    # ── OMISSION D'ALLOWLIST, mesuree le 2026-07-31 ──────────────────────────
    # 25 tools sur 61 etaient DECLARES au registre (avec leur ring RBAC) et
    # absents d'ici : tout appel /mcp rendait « tool 'X' not allowed ». Les skills
    # qui en dependent etaient donc morts sans que rien ne l'explique — meme
    # defaut que les capteurs code (read_function_body, get_file_skeleton,
    # blackboard_*) repare en juillet, et deja diagnostique alors comme « absents
    # de cette allowlist -> 400 not allowed ».
    #
    # CE N'EST PAS UN AFFAIBLISSEMENT : le controle d'acces REEL est le ring RBAC
    # porte par le registre (crawl=1, docker_action=1, agy_run=owner-only...), et
    # il s'applique de toute facon. Cette liste est un filtre de SURFACE ; une
    # entree manquante ne protege rien, elle casse un chemin declare.
    "crawl",                    # forge_crawl_tool : PUR STDLIB (urllib + markdown
                                # + extraction PDF), aucune dependance Docker malgre
                                # ce que laisse croire son libelle « Crawl4AI »
    "md",
    "query_documentation",
    "query_local_json",
    "search_local_file",
    "absorb_rfc_knowledge",
    "auto_ingest",
    "github",
    "graph_ppr",
    "graph_edge_score",
    "graph_cve_propagate",
    "forge_list_dynamic_tools",
    "forge_call_dynamic",
    "delegate_to_local_scout",
    "plan",
    "bundle",
    "loop_orchestrate",
    "react_orchestrate",
    "route_dt",
    "docker_action",            # cycle de vie conteneurs : le RBAC ring tranche
    "agy_add_dir",
    "agy_config",
    "agy_run",                  # owner-only cote RBAC, inutile de le doubler ici
    "cross_platform_fs",
    # Allowlist STATIQUE du /mcp : sans elle un tool declare au catalogue ET
    # autorise cote RBAC ressort quand meme en 400 « not allowed » a l'execution.
    # Gotcha deja paye pour `forge_deep_explore` ; re-paye le 2026-08-31 sur
    # `introspect`, expose la veille et refuse au premier appel d'agent.
    "introspect",
    # DELIBEREMENT ABSENT : `secret`. Un tool de gestion de secrets est le seul de
    # la liste dont l'omission peut etre une defense en profondeur VOULUE plutot
    # qu'un oubli. On ne l'ajoute pas « tant qu'a faire » : il se decide a part,
    # avec l'owner, et son absence ne casse aucun skill mesure a ce jour.
}

MAX_PAYLOAD_BYTES = 512_000  # 512 KB max
MAX_STRING_LEN = 16_000  # 16 KB max par string


# ── Validateurs ───────────────────────────────────────────────────────────────


def sanitize_path(raw: str) -> tuple[bool, str]:
    """
    PATH_SANITIZATION — verifie qu'un chemin est safe.
    Retourne (ok, chemin_nettoye ou message_erreur).
    """
    if not isinstance(raw, str):
        return False, "path must be string"
    if len(raw) > 512:
        return False, "path too long"
    for pat in _BLOCKED_PATH_PATTERNS:
        if pat.search(raw):
            logger.warning("PATH_BLOCKED: %s", raw[:80])
            return False, f"path blocked: {pat.pattern[:30]}"
    # Normaliser
    cleaned = raw.replace("\\", "/").strip()
    return True, cleaned


def sanitize_string(value: str, field: str = "?", research_mode: bool = False) -> tuple[bool, str]:
    """
    Nettoie une valeur string.
    research_mode=True : uniquement les injections réelles (XSS/SQLi), pas les heuristiques code.
    Utilisé pour orchestrate.task et run.code (exécution locale uniquement).
    """
    if not isinstance(value, str):
        return True, str(value)
    if len(value) > MAX_STRING_LEN:
        logger.warning("STRING_TRUNCATED field=%s len=%d", field, len(value))
        value = value[:MAX_STRING_LEN]
    patterns = _INJECTION_PATTERNS if research_mode else (_INJECTION_PATTERNS + _HEURISTIC_PATTERNS)
    for pat in patterns:
        if pat.search(value):
            logger.warning(
                "CONTENT_BLOCKED field=%s pattern=%s research=%s",
                field,
                pat.pattern[:30],
                research_mode,
            )
            # NOMMER le motif : un refus opaque n'est pas corrigeable. Mesure
            # 2026-07-31 -- un simple « blocked content in field 'blocks' » a
            # envoye l'appelant redecouper ses blocs au hasard pendant plusieurs
            # essais, au lieu de lui montrer la forme fautive.
            return False, (f"blocked content in field '{field}': motif "
                           f"{pat.pattern[:60]!r} (research={research_mode})")
    return True, value


def validate_tool_name(name: Any) -> tuple[bool, str]:
    """Valide que le nom de tool est dans la liste autorisee."""
    if not isinstance(name, str):
        return False, "tool name must be string"
    name = name.strip().lower()
    if name not in _ALLOWED_TOOLS:
        logger.warning("TOOL_BLOCKED: %s", name)
        return False, f"tool '{name}' not allowed"
    return True, name


def validate_arguments(args: Any, tool: str = "") -> tuple[bool, dict, list]:
    """
    Valide et sanitize les arguments d'un appel MCP.
    Retourne (ok, args_clean, errors).
    """
    if args is None:
        return True, {}, []
    if not isinstance(args, dict):
        return False, {}, ["arguments must be object"]

    errors = []
    cleaned = {}

    for key, value in args.items():
        # Valider la cle
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", str(key)):
            errors.append(f"invalid key: {key}")
            continue

        # Valider les strings
        if isinstance(value, str):
            # Path fields
            if any(k in key.lower() for k in ["path", "file", "dir", "folder"]):
                ok, result = sanitize_path(value)
                if not ok:
                    errors.append(f"{key}: {result}")
                    continue
                cleaned[key] = result
            else:
                # research_mode : heuristiques désactivées pour champs de code local
                is_research = key in _RESEARCH_FIELDS.get(tool, set())
                ok, result = sanitize_string(value, key, research_mode=is_research)
                if not ok:
                    errors.append(result)
                    continue
                cleaned[key] = result
        elif isinstance(value, (int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, dict)):
            # Serialiser et valider la taille
            try:
                serialized = json.dumps(value, ensure_ascii=False)
                if len(serialized) > MAX_PAYLOAD_BYTES:
                    errors.append(f"{key}: payload too large")
                    continue
                cleaned[key] = value
            except Exception:
                errors.append(f"{key}: not serializable")
        else:
            cleaned[key] = value

    ok = len(errors) == 0
    return ok, cleaned, errors


def validate_mcp_body(body: Any) -> tuple[bool, dict, list]:
    """
    Valide un body JSON-RPC MCP complet.
    Retourne (ok, body_clean, errors).
    """
    errors = []

    if not isinstance(body, dict):
        return False, {}, ["body must be JSON object"]

    # Taille totale
    try:
        raw_size = len(json.dumps(body, ensure_ascii=False).encode())
        if raw_size > MAX_PAYLOAD_BYTES:
            return False, {}, [f"payload too large: {raw_size} bytes"]
    except Exception:
        pass

    cleaned = {}

    # method / jsonrpc
    for field in ["jsonrpc", "id", "method"]:
        if field in body:
            ok, val = sanitize_string(str(body[field]), field)
            if ok:
                cleaned[field] = body[field]

    # params.name = tool name (uniquement pour tools/call)
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "tools/call" and isinstance(params, dict):
        tool_name_raw = params.get("name", "")
        ok, tool_name = validate_tool_name(tool_name_raw)
        if not ok:
            errors.append(tool_name)
            return False, {}, errors

        # params.arguments
        args_raw = params.get("arguments", {})
        ok, args_clean, arg_errors = validate_arguments(args_raw, tool_name)
        errors.extend(arg_errors)

        cleaned["params"] = {"name": tool_name, "arguments": args_clean}
    elif isinstance(params, dict):
        # Autres methodes (initialize, tools/list, prompts/*) : passthrough sans validation de tool_name
        cleaned["params"] = params

    # Reponse JSON-RPC du CLIENT (aucune `method`) : `result` / `error` passent tels quels.
    # Sans cela une reponse d'elicitation arrivait VIDE au hub -- seuls jsonrpc/id/method/params
    # etaient recopies (mesure 2026-09-26). Taille deja bornee par MAX_PAYLOAD_BYTES.
    if "method" not in body:
        for field in ("result", "error"):
            if field in body:
                cleaned[field] = body[field]

    return len(errors) == 0, cleaned, errors


class ValidationError(Exception):
    """Erreur de validation middleware."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(errors))

    def to_json_rpc(self, req_id: Any = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32600,
                "message": "Invalid Request",
                "data": {"validation_errors": self.errors},
            },
        }
