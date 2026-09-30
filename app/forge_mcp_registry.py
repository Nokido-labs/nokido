# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-25 | VER:v_forge_mcp_registry_v3
#FORGE:[score:96|agent:claude-opus-4.7|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Unified Handler Registry with WebSearch & Agent RPC + SecretGuard

v3 (2026-04-25) :
  - Branchement de forge_secret_guard sur handle_read, handle_write,
    handle_run.python et handle_query
  - L'ancienne defense honeytoken (3 paths en dur, ring > 0) est retiree
    car contournee trivialement via run.python et SQL direct.
  - SecretGuard bloque MEME en RING 0 sauf attestation dev-mode armee
    est positionne explicitement.

v3.1 (2026-05-23) — Namespace structure + explanation field
  Pattern inspire de Cursor / Augment / Devin / Claude Code 2.0
  (cf. ai_prompts_landscape ingere dans RAG).

  Catégories namespace (forme canonique `forge.{cat}.{tool}`) :
    forge.code.*     : lecture/ecriture de fichiers (read, write, read_function_body, auto_test)
    forge.rag.*      : recherche RAG / SQL embeddings (rag, query, biblio)
    forge.hub.*      : etat hub et orchestration locale (hub, plan, execute, bundle, bundle_read, loop_orchestrate, orchestrate, react_orchestrate, route_dt, route_task, manage_forge_lifecycle, trigger_autonomous_evolution)
    forge.llm.*      : appels LLM (ask, ask_agent)
    forge.task.*     : cycle de vie taches + events (task, event, memory, agent_send, agent_recv, poll, index_result, search_recent)
    forge.run.*      : execution shell / python / sandbox (run, ps_run, ps_agent, secret)
    forge.graph.*    : graphe de code et CVE (graph_edge_score, graph_cve_propagate, graph_ppr)
    forge.net.*      : reseau et reconnaissance (netcfg, crawl, web_search, web_search_rag, research_agent, github, browser)
    forge.security.* : docker / skill marketplace (skill)
    forge.fs.*       : filesystem cross-platform (cross_platform_fs, auto_ingest)
    forge.meta.*     : meta-info agent (whoami, get_mode, set_mode, notify)

  Mapping complet -> voir `_NAMESPACE_ALIASES` plus bas.

  Backward-compat : les noms cours actuels (`read`, `run`, `rag`, ...) ET les
  variantes prefixees historiques (`forge_read`, `forge_rag`, ...) restent
  appelables sans changement. La fonction `resolve_tool_name()` normalise
  vers le nom interne court utilise par les handlers (`handle_<name>`).

  Champ `explanation` ajoute dans `inputSchema.properties` de tous les tools
  (string, optionnel pour 6 mois). Helper `enforce_explanation(args, mode=...)`
  permet de passer en mode "error" via env `LAFORGE_EXPLANATION_MODE=error`.
  Deadline mode=error : 2026-08-01.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:96|agent:claude-opus-4.7|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
)

import asyncio
import json
import logging
import os
import sqlite3
from nokido_agent.app.forge_spike_router import evaluate_intent
import time
import base64
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# On s'assure que le path est correct pour les imports internes
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in os.sys.path:
    os.path.sys.path.insert(0, str(ROOT / "app"))

from nokido_agent.app.forge_state_manager import get_state_manager

# v3 : import du SecretGuard
from nokido_agent.app.forge_secret_guard import (
    SecretGuardViolation,
    assert_can_read,
    assert_can_write,
    sanitize_python_code,
    sanitize_sql,
)
# JsonQueryTool importé en LAZY dans handle_query_json (rend solide : un module
# tool optionnel cassé ne doit JAMAIS faire tomber l'import du gate -> hub fail-closed)

from nokido_agent.app.forge_goap import GoalPlanner, execute_plan

from nokido_agent.app.forge_lifecycle_tool import handle_manage_forge_lifecycle
from nokido_agent.app.forge_extern_patterns import query_extern_pattern

logger = logging.getLogger("Nokido.MCP.Registry")


# ─── NAMESPACE STRUCTURE (v3.1) ──────────────────────────────────────────────
# Mapping : nom expose externe -> nom interne court (handler = handle_<short>).
# Trois familles de cles :
#   1. forme canonique         "forge.code.read"  -> "read"
#   2. alias historique prefix "forge_read"       -> "read"
#   3. identite (passthrough)  "read"             -> "read"  (couvre par defaut)
#
# Ajouter une entree ici suffit a exposer un nouvel alias ; les handlers
# (handle_<short>) ne bougent pas. Source de verite pour les clients :
# preferer la forme canonique forge.{cat}.{tool}.
_NAMESPACE_ALIASES: Dict[str, str] = {
    # ── forge.code.* ────────────────────────────────────────────────────────
    "forge.code.read": "read",
    "forge.code.read_function_body": "read_function_body",
    "forge.code.write": "write",
    "forge.code.auto_test": "auto_test",
    "forge.code.get_file_skeleton": "get_file_skeleton",
    "forge.code.get_function_dependencies": "get_function_dependencies",
    "forge_read": "read",
    "forge_read_function_body": "read_function_body",
    "forge_write": "write",
    "forge_auto_test": "auto_test",
    "forge_get_file_skeleton": "get_file_skeleton",
    "forge_get_function_dependencies": "get_function_dependencies",
    "forge.code.introspect": "introspect",
    "forge_introspect": "introspect",
    # ── forge.json.* ────────────────────────────────────────────────────────
    "forge.json.query": "query_json",
    "query_json": "query_json",
    # ── forge.swarm.* ───────────────────────────────────────────────────────
    "forge.swarm.blackboard_read_zone": "blackboard_read_zone",
    "forge.swarm.blackboard_propose_fact": "blackboard_propose_fact",
    "forge_blackboard_read_zone": "blackboard_read_zone",
    "forge_blackboard_propose_fact": "blackboard_propose_fact",
    # ── forge.meta.* (observabilité) ──
    "forge.meta.forge_stats": "forge_stats",
    "forge.meta.stats": "forge_stats",
    # ── forge.rag.* ─────────────────────────────────────────────────────────
    "forge.rag.rag": "rag",
    "forge.rag.query": "query",
    "forge.rag.biblio": "biblio",
    "forge.rag.search": "rag",
    "forge.rag.fts": "query",
    "forge_rag": "rag",
    "forge_rag_query": "rag",
    "forge_rag_search": "rag",
    "forge_rag_fts": "query",
    "forge_query": "query",
    "forge_biblio": "biblio",
    # ── forge.hub.* ─────────────────────────────────────────────────────────
    "forge.hub.hub": "hub",
    "forge.hub.plan": "plan",
    "forge.hub.execute": "execute",
    "forge.hub.bundle": "bundle",
    "forge.hub.bundle_read": "bundle_read",
    "forge.hub.orchestrate": "orchestrate",
    "forge.hub.react_orchestrate": "react_orchestrate",
    "forge.hub.loop_orchestrate": "loop_orchestrate",
    "forge.hub.route_dt": "route_dt",
    "forge.hub.route_task": "route_task",
    "forge.hub.manage_forge_lifecycle": "manage_forge_lifecycle",
    "forge.hub.trigger_autonomous_evolution": "trigger_autonomous_evolution",
    "forge_hub": "hub",
    "forge_plan": "plan",
    "forge_execute": "execute",
    "forge_bundle": "bundle",
    "forge_bundle_read": "bundle_read",
    "forge_orchestrate": "orchestrate",
    "forge_react_orchestrate": "react_orchestrate",
    "forge_loop_orchestrate": "loop_orchestrate",
    "forge_route_dt": "route_dt",
    "forge_route_task": "route_task",
    "forge_manage_forge_lifecycle": "manage_forge_lifecycle",
    "forge_trigger_autonomous_evolution": "trigger_autonomous_evolution",
    # ── forge.llm.* ─────────────────────────────────────────────────────────
    "forge.llm.ask": "ask",
    "forge.llm.ask_agent": "ask_agent",
    "forge_ask": "ask",
    "forge_ask_agent": "ask_agent",
    # ── forge.task.* ────────────────────────────────────────────────────────
    "forge.task.task": "task",
    "forge.task.event": "event",
    "forge.task.memory": "memory",
    "forge.task.agent_send": "agent_send",
    "forge.task.agent_recv": "agent_recv",
    "forge.task.poll": "poll",
    "forge.task.index_result": "index_result",
    "forge.task.search_recent": "search_recent",
    "forge_task": "task",
    "forge_event": "event",
    "forge_memory": "memory",
    "forge_agent_send": "agent_send",
    "forge_agent_recv": "agent_recv",
    "forge_poll": "poll",
    "forge_index_result": "index_result",
    "forge_search_recent": "search_recent",
    # ── forge.run.* ─────────────────────────────────────────────────────────
    "forge.run.run": "run",
    "forge.run.ps_run": "ps_run",
    "forge.run.ps_agent": "ps_agent",
    "forge.run.secret": "secret",
    "forge_run": "run",
    "forge_ps_run": "ps_run",
    "forge_ps_agent": "ps_agent",
    "forge_secret": "secret",
    # ── forge.graph.* ───────────────────────────────────────────────────────
    "forge.graph.edge_score": "graph_edge_score",
    "forge.graph.cve_propagate": "graph_cve_propagate",
    "forge.graph.ppr": "graph_ppr",
    "forge_graph_edge_score": "graph_edge_score",
    "forge_graph_cve_propagate": "graph_cve_propagate",
    "forge_graph_ppr": "graph_ppr",
    # ── forge.net.* ─────────────────────────────────────────────────────────
    "forge.net.netcfg": "netcfg",
    "forge.net.crawl": "crawl",
    "forge.net.web_search": "web_search",
    "forge.net.web_search_rag": "web_search_rag",
    "forge.net.research_agent": "research_agent",
    "forge.net.github": "github",
    "forge.net.browser": "browser",
    "forge_netcfg": "netcfg",
    "forge_crawl": "crawl",
    "forge_web_search": "web_search",
    "forge_web_search_rag": "web_search_rag",
    "forge_research_agent": "research_agent",
    "forge_github": "github",
    "forge_browser": "browser",
    "forge.security.skill": "skill",
    "forge_skill": "skill",
    # ── forge.fs.* ──────────────────────────────────────────────────────────
    "forge.fs.cross_platform_fs": "cross_platform_fs",
    "forge.fs.auto_ingest": "auto_ingest",
    "forge_cross_platform_fs": "cross_platform_fs",
    "forge_auto_ingest": "auto_ingest",
    # ── forge.meta.* ────────────────────────────────────────────────────────
    "forge.meta.whoami": "whoami",
    "forge.meta.get_mode": "get_mode",
    "forge.meta.set_mode": "set_mode",
    "forge.meta.notify": "notify",
    "forge_whoami": "whoami",
    "forge_get_mode": "get_mode",
    "forge_set_mode": "set_mode",
    "forge_notify": "notify",
    "forge.code.agy_run": "agy_run",
    "forge_agy_run": "agy_run",
    "forge.meta.agy_config": "agy_config",
    "forge_agy_config": "agy_config",
    "forge.fs.agy_add_dir": "agy_add_dir",
    "forge_agy_add_dir": "agy_add_dir",
}


def check_unicode_concealment(val: Any) -> tuple[bool, str]:
    """Scan récursif pour le bloc Unicode TAG (U+E0000 - U+E007F) et les invisibles.
    Retourne (détecté, raison).
    """
    if isinstance(val, str):
        for char in val:
            cp = ord(char)
            if 0xE0000 <= cp <= 0xE007F:
                return True, f"U+{cp:X} (Unicode TAG-block)"
            if cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF):
                return True, f"U+{cp:X} (Invisible)"
        return False, ""
    elif isinstance(val, dict):
        for k, v in val.items():
            ok, reason = check_unicode_concealment(k)
            if ok:
                return True, f"clé '{k}': {reason}"
            ok, reason = check_unicode_concealment(v)
            if ok:
                return True, f"valeur sous '{k}': {reason}"
    elif isinstance(val, list):
        for idx, item in enumerate(val):
            ok, reason = check_unicode_concealment(item)
            if ok:
                return True, f"élément [{idx}]: {reason}"
    return False, ""


def resolve_tool_name(name: str) -> str:
    """Normalise un nom de tool vers le nom interne court.

    >>> resolve_tool_name("forge.code.read")
    'read'
    >>> resolve_tool_name("forge_read")
    'read'
    >>> resolve_tool_name("read")
    'read'
    >>> resolve_tool_name("inconnu")
    'inconnu'
    """
    if not isinstance(name, str):
        return name
    return _NAMESPACE_ALIASES.get(name, name)


# Message rendu par `dispatch` pour un nom sans handler ni route. CONSTANTE partagee avec
# `classer_retour_intent` : si le libelle change, la classification suit au lieu de rouvrir
# le faux succes en silence (NR test_goap_outil_inconnu_failclosed_nr).
OUTIL_INCONNU = "Outil inconnu"
_PREFIXES_ECHEC_INTENT = ("ERR", "SECURITY", "SECRET GUARD", "FAIL", OUTIL_INCONNU)


def classer_retour_intent(res: Any, intent: Dict[str, Any]) -> Dict[str, Any]:
    """Retour de `dispatch` -> reponse JSON-RPC pour forge_goap.execute_plan.

    Seul classement des outils `plan` (execute=true) et `execute`. Un intent GOAP porte un nom
    de forge_trajectory.ALLOWED_METHODS ; 14 des 23 n'ont pas d'outil MCP homonyme (mesure du
    2026-09-27) et `dispatch` rend alors OUTIL_INCONNU, chaine sans prefixe d'erreur que
    l'ancien classement prenait pour un succes (pas `completed`). Fail-closed : c'est une erreur.
    """
    if str(res).startswith(_PREFIXES_ECHEC_INTENT):
        return {"jsonrpc": "2.0", "id": intent.get("id"),
                "error": {"code": -32003, "message": str(res)}}
    if isinstance(res, dict) and res.get("error"):
        return res
    return {"jsonrpc": "2.0", "id": intent.get("id"), "result": res}


def enforce_explanation(call: Dict[str, Any], mode: str = "warn") -> None:
    """Verifie la presence d'un champ `explanation` dans les arguments d'un
    appel de tool (pattern Cursor / Augment / Claude Code 2.0).

    Args:
        call: dict avec au moins `name` et `arguments` (ou les args directs).
        mode: "warn" (defaut) emet un log warning si absent ; "error" leve
              ValueError. Permet une transition douce.

    Variable d'env `LAFORGE_EXPLANATION_MODE` (warn|error) override `mode`.
    """
    env_mode = os.environ.get("LAFORGE_EXPLANATION_MODE", "").strip().lower()
    if env_mode in ("warn", "error"):
        mode = env_mode
    if not isinstance(call, dict):
        return
    # accepte les 2 formes : {"name":..., "arguments":{...}} OU args directs
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else call
    name = call.get("name", "?")
    has_expl = isinstance(args, dict) and bool(str(args.get("explanation", "") or "").strip())
    if has_expl:
        return
    msg = (
        f"[explanation-missing] tool '{name}' appele sans champ "
        f"`explanation` (pattern Cursor/Augment). Deadline mode=error : 2026-08-01."
    )
    if mode == "error":
        raise ValueError(msg)
    # log-once PAR TOOL (anti-firehose : ce warning par tool-call a contribué aux 47GB
    # de log -> fuite superviseur). Dédup sur le logger singleton.
    _seen = getattr(logger, "_no_expl_seen", None)
    if _seen is None:
        _seen = logger._no_expl_seen = set()
    if name not in _seen:
        _seen.add(name)
        logger.warning(msg)


_WHOAMI_HEALTHY_STATES = {"running", "sleeping", "starting", "disabled"}
_WHOAMI_HARD_STATES = ("crashed", "quarantine", "error", "failed")


def whoami_degraded_services(services: dict) -> list:
    """Services hors états sains, depuis le dict /supervisor/status. Pur (testable)."""
    out = []
    for name, sv in (services or {}).items():
        st = (sv.get("status") if isinstance(sv, dict) else None) or "?"
        if st not in _WHOAMI_HEALTHY_STATES:
            out.append(
                {
                    "service": name,
                    "status": st,
                    "restarts": (sv.get("restarts", 0) if isinstance(sv, dict) else 0),
                }
            )
    return out


def whoami_health_actions(degraded: list, limit: int = 4) -> list:
    """Actions restart pour services ayant ESSAYÉ et échoué (restarts>0) ou état dur.
    Ignore les essential=false cleanement idle (restarts=0). Pur (testable)."""
    return [
        {
            "cmd": f'run action=trusted_script path=tools/forge_supervisor_ctl.py script_args="restart {d["service"]}"',
            "why": f'{d["service"]} {d["status"]} (restarts={d["restarts"]}) — infra degradee',
        }
        for d in degraded
        if d.get("restarts", 0) > 0 or d.get("status") in _WHOAMI_HARD_STATES
    ][:limit]


def _profile_dispatch(fn):
    """Mesure le cout REEL d'un appel de tool au chokepoint (P2 item 2).

    Decorateur et non instrumentation du corps : `dispatch` a de multiples points
    de sortie et les envelopper un a un serait autant d'occasions de regresser.
    Le profilage ne doit jamais casser le dispatch : import paresseux, aucune
    exception propagee, resultat retourne tel quel meme si l'enregistrement echoue.
    """
    import functools
    import time as _t

    @functools.wraps(fn)
    async def _wrapper(self, name, args, agent, ring):
        _t0 = _t.perf_counter()
        _ok = True
        try:
            res = await fn(self, name, args, agent, ring)
            # Un dict porteur d'`error` est un echec METIER : le compter comme un
            # succes ferait mentir le taux d'erreur par tool.
            if isinstance(res, dict) and res.get("error"):
                _ok = False
            return res
        except Exception:
            _ok = False
            raise
        finally:
            try:
                from nokido_agent.app.forge_promcp_profiler import record as _rec

                _rec(name, (_t.perf_counter() - _t0) * 1000.0, ok=_ok,
                     payload_bytes=len(str(args)) if args else 0)
            except Exception:  # noqa: BLE001
                pass

    return _wrapper


class ToolRegistry:
    """Registre unifie des outils MCP pour Nokido (HTTP & STDIO)."""

    def __init__(self, root_dir: Path = ROOT):
        self.root = root_dir
        self.state_mgr = get_state_manager()
        self._unicode_meta_clean = set()
        self.db_path = root_dir / "RAG" / "embeddings.db"
        if not self.db_path.exists():
            try:
                self.db_path = next((root_dir / "data").glob("*.db"))
            except (StopIteration, Exception):
                pass

    def _archive_long_args(self, args: dict, agent: str, tool_name: str) -> dict:
        """
        Si une valeur d arg est une chaine > 500c, l archive dans agent_messages
        et retourne un preview avec un pointeur _archived_msg_id.

        Permet d eviter la perte de messages longs (probleme initial : preview 200c
        truncate destructif). Le message complet reste recuperable via le hub :
        SELECT payload FROM agent_messages WHERE id=?
        """
        import sqlite3, hashlib, json as _json, time as _time

        ARCHIVE_THRESHOLD = 500
        out = {}
        for k, v in args.items():
            if isinstance(v, (int, float, bool, list, dict)):
                out[k] = v
                continue
            sv = str(v)
            if len(sv) > ARCHIVE_THRESHOLD:
                # Archiver le message complet
                msg_id = "evtmsg_" + hashlib.sha256(f"{agent}{tool_name}{k}{_time.time()}".encode()).hexdigest()[:14]
                try:
                    from nokido_agent.app.forge_db_path import open_m2m as _open_m2m   # scission M2M : interrupteur sandbox/m2m.switch
                    conn = _open_m2m(timeout=3)
                    conn.execute(
                        "INSERT INTO agent_messages(id, from_agent, to_agent, correlation_id, method, payload, status) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (
                            msg_id,
                            agent,
                            "EVENTBUS_ARCHIVE",
                            msg_id,
                            f"tool.{tool_name}.arg.{k}",
                            _json.dumps({"text": sv, "tool": tool_name, "arg_key": k}),
                            "archived",
                        ),
                    )
                    conn.commit()
                    conn.close()
                    out[k] = {
                        "_archived_msg_id": msg_id,
                        "_preview": sv[:200],
                        "_full_chars": len(sv),
                    }
                except Exception as _e:
                    # En cas d echec d archivage, fallback ancien comportement (truncate)
                    out[k] = sv[:200]
            else:
                out[k] = sv[:200] if len(sv) > 200 else sv
        return out

    def _archive_blob(self, text: str, agent: str, label: str) -> "Optional[str]":
        """Stashe un blob TEXTE complet sous sandbox/ccr/<id>.txt, récupérable via
        read(action='archived', id=...). None si échec.

        Compression réversible (CCR, inspiré Headroom) côté SORTIE : le guard ne
        tronque plus en PERDANT le milieu. Store FICHIER (pas agent_messages) car le
        contexte qui exécute le guard est readonly sur embeddings.db (sandbox ACLs) ;
        sandbox/ccr est writable dans ce même contexte. Symétrique à _archive_long_args."""
        import hashlib, time as _time

        try:
            d = self.root / "sandbox" / "ccr"
            d.mkdir(parents=True, exist_ok=True)
            mid = "ccr_" + hashlib.sha256(f"{agent}{label}{len(text)}{_time.time()}".encode()).hexdigest()[:16]
            (d / f"{mid}.txt").write_text(text, encoding="utf-8")
            return mid
        except Exception as _e:
            logger.debug(f"CCR archive failed: {_e}")
            return None

    async def _handle_ensure_service(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:
        """Bouton rouge declaratif : {service, desired_state} -> orchestration SERVIE
        (LaForgeTrusted: forge_docker_agent/keeper/forge_supervisor_ctl). Le client
        DECLARE ; l'imperatif (privileges/daemons/conteneurs) reste cote hub."""
        import asyncio as _aio
        import json as _json
        import re as _re
        from pathlib import Path as _P
        # PLANCHER DE RING — ajoute le 2026-09-13.
        # Ce handler lance forge_ensure_service.py sous LaForgeTrusted
        # (start/stop/restart de services). Il est route AVANT le gate central
        # `_get_ring_needed` et ABSENT du barème RBAC : mesure du jour, un
        # client ring 4 (UNTRUSTED) l'atteignait (refus au FORMAT, pas au ring).
        # Un barème EN BASE le disait a min_ring 4 — declaration morte, jamais
        # appliquee puisque le tool court-circuite le gate qui la lit.
        # ring <= 2 (TRUSTED) : l'autoregulation documentee (le client DECLARE
        # son besoin) est faite a ring 1-2 ; les organes internes tournent dans
        # le hub, hors dispatch. SEUIL a confirmer par l'owner (le barème mort
        # disait 4) ; l'infra mutante hors d'atteinte d'UNTRUSTED, elle, ne se
        # negocie pas. Fige par tests/test_ensure_service_plancher_ring.py
        try:
            _ring_eff = int(ring)
        except (TypeError, ValueError):
            _ring_eff = 4  # ring illisible -> le moins privilegie, jamais l'inverse
        if _ring_eff > 2:
            return {"error": "forbidden",
                    "reason": ("SECURITY: nokido_ensure_service exige ring <= 2 "
                               "(TRUSTED) — pilotage de services via executeur "
                               "trusted refuse au ring %r" % (ring,)),
                    "ring": ring}
        svc = str(args.get("service") or "").strip()
        state = str(args.get("desired_state") or "running").strip()
        if not svc:
            return {"error": "service requis", "hint": "nokido_ensure_service{service, desired_state}"}
        if not _re.match(r"^[A-Za-z0-9_\-]{1,40}$", svc) or not _re.match(r"^[A-Za-z]{1,16}$", state):
            return {"error": "service/desired_state invalides (alphanum)"}
        script = str(_P(__file__).resolve().parent.parent / "tools" / "forge_ensure_service.py")
        try:
            from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON as _PY
        except Exception:
            _PY = os.path.expanduser("~/miniforge3/python.exe")
        cmd = f'"{_PY}" "{script}" --service {svc} --state {state}'
        try:
            from nokido_agent.app.forge_sandbox_exec import spawn_as_trusted
            r = await _aio.to_thread(lambda: spawn_as_trusted(cmd, timeout=200))
        except Exception as e:  # noqa: BLE001
            return {"error": f"ensure_service: {type(e).__name__}: {str(e)[:120]}"}
        out = (r.get("stdout") or "").strip() if isinstance(r, dict) else str(r)
        try:
            return _json.loads(out.splitlines()[-1])
        except Exception:
            return {"success": False, "detail": (out[-300:] or "no output"),
                    "exit": (r.get("exit_code") if isinstance(r, dict) else None)}

    async def _handle_deep_explore(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:
        """Honeypot de delegation : recon LOCALE souveraine (0 token cloud).

        Capte les intentions d'exploration que les clients enverraient sinon en
        Agent(Explore)/reads natifs (fuite tokens). Wrappe forge_local_explore :
        recherche DETERMINISTE (regex) sur globs, puis CLASSEMENT (forge_explore_rank)
        et coupe. Aucune synthese LLM ici : le digest est fait d'extraits BRUTS --
        la docstring promettait une synthese que le code ne faisait pas (2026-08-02)."""
        import asyncio as _aio
        intent = str(args.get("intent") or "").strip()
        if not intent:
            return {"error": "intent requis", "hint": "forge_deep_explore{intent, target?, globs?, breadth?}"}
        query = str(args.get("target") or intent)
        globs = str(args.get("globs") or "app/forge_*.py,tools/*.py")
        breadth = str(args.get("breadth") or "medium")
        # Budgets DISTINCTS (mesure 2026-08-02) : borner la COLLECTE revenait a ne
        # jamais voir le module cherche -- a 90 hits, 0 extrait des modules vises ;
        # a 2000, 47. Chercher large est local et gratuit ; c'est l'AFFICHAGE qui
        # coute des tokens, donc lui seul reste serre.
        collecte = {"narrow": 400, "medium": 1200, "wide": 3000}.get(breadth, 1200)
        affichage = {"narrow": 20, "medium": 30, "wide": 60}.get(breadth, 30)

        def _run():
            import sys as _s
            from pathlib import Path as _P
            _tp = str(_P(__file__).resolve().parent.parent / "tools")
            if _tp not in _s.path:
                _s.path.insert(0, _tp)
            from nokido_agent.tools import forge_local_explore as fle  # type: ignore
            _globs = [g.strip() for g in globs.split(",") if g.strip()]
            return fle.search(query, _globs, context=2, max_hits=collecte)

        try:
            res = await _aio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return {"error": f"deep_explore: {type(e).__name__}: {str(e)[:120]}"}
        hits = res.get("hits", [])
        try:
            from nokido_agent.app.forge_explore_rank import classer as _classer_explore
        except Exception:  # muet-ok : le classement est un confort, la recon reste utile
            def _classer_explore(_h, _q, **_k):
                return _h[:60]
        files = sorted({h.get("file", "") for h in hits})
        _parts = []
        montres = _classer_explore(hits, query, par_fichier=2, plafond=affichage)
        for h in montres:
            _parts.append(f"--- {h.get('file')}:{h.get('line')}")
            # 240 et non 400 : a 8000 chars de digest, des extraits longs ne laissent
            # passer que ~19 entrees et annulent la diversite gagnee plus haut.
            _parts.append(str(h.get("excerpt", ""))[:240])
        digest = "\n".join(_parts)[:8000]
        return {
            "ok": True,
            "intent": intent,
            "files_touched": files[:40],
            "n_hits": len(hits),
            # Un filtre qui ecarte des donnees le DIT (RULES_SHARED) : sinon la
            # couverture est surestimee en silence.
            "hits_montres": len(montres),
            "digest": digest,
            "note": "recon LOCALE déterministe (0 token cloud, file:line + extraits). Affine via {target, globs, breadth}.",
        }

    @_profile_dispatch
    async def dispatch(self, name: str, args: Dict[str, Any], agent: str, ring: int) -> Union[str, Dict[str, Any]]:
        """Dispatch avec vérification sécurité + filtre sémantique RAG (ITEM 12).

        v3.1 : resoud les alias namespace `forge.{cat}.{tool}` et les variantes
        prefixees `forge_*` vers le nom interne court avant tout traitement.
        Verifie aussi la presence du champ `explanation` (warn par defaut,
        cf. `enforce_explanation` + env `LAFORGE_EXPLANATION_MODE`).

        Couche SpikeRouter posee en tete de dispatch : elle suspend l'action et
        demande une negociation humaine quand l'intention du couple (outil,
        arguments) est jugee suspecte.
        """
        # -- SpikeRouter Semantic Security Layer --
        intent_check = evaluate_intent({"tools": [{"name": name, "arguments": args}]})
        if intent_check.get("status") == "requires_negotiation":
            import json
            return (
                "SECURITY: Action suspendue. Negociation requise "
                f"(Human-in-the-loop). Détails: {json.dumps(intent_check)}"
            )
        # -----------------------------------------
        # P0 SECURITE : scan Unicode TAG-block U+E0000-E007F + invisibles (name et args)
        ok, reason = check_unicode_concealment(name)
        if ok:
            import logging as _lg
            _lg.getLogger("Nokido.Security").warning(
                f"[SECURITY REJECT] Unicode concealment detected in tool name '{name}' from agent '{agent}': {reason}"
            )
            return {"error": "security_reject", "reason": f"Unicode concealment detected in tool name: {reason}"}

        ok, reason = check_unicode_concealment(args)
        if ok:
            import logging as _lg
            _lg.getLogger("Nokido.Security").warning(
                f"[SECURITY REJECT] Unicode concealment detected in tool arguments for '{name}' from agent '{agent}': {reason}"
            )
            return {"error": "security_reject", "reason": f"Unicode concealment detected in tool arguments: {reason}"}

        # v3.1 : alias namespace -> nom interne court (handle_<short>)
        resolved = resolve_tool_name(name)
        if resolved != name:
            logger.debug(f"[namespace] alias '{name}' -> '{resolved}'")
        name = resolved

        # P0 SECURITE : scan Unicode TAG-block U+E0000-E007F + invisibles dans la métadonnée du tool (name, description, schema)
        if not hasattr(self, "_unicode_meta_clean"):
            self._unicode_meta_clean = set()
        if resolved not in self._unicode_meta_clean:
            tool_meta = None
            for t in self._all_tools():
                if t.get("name") == resolved:
                    tool_meta = t
                    break
            if tool_meta:
                ok, reason = check_unicode_concealment(tool_meta.get("description", ""))
                if ok:
                    import logging as _lg
                    _lg.getLogger("Nokido.Security").warning(
                        f"[SECURITY REJECT] Unicode concealment detected in tool description of '{resolved}' called by '{agent}': {reason}"
                    )
                    return {"error": "security_reject", "reason": f"Unicode concealment detected in tool metadata: {reason}"}

                ok, reason = check_unicode_concealment(tool_meta.get("inputSchema", {}))
                if ok:
                    import logging as _lg
                    _lg.getLogger("Nokido.Security").warning(
                        f"[SECURITY REJECT] Unicode concealment detected in tool inputSchema of '{resolved}' called by '{agent}': {reason}"
                    )
                    return {"error": "security_reject", "reason": f"Unicode concealment detected in tool metadata: {reason}"}
                self._unicode_meta_clean.add(resolved)

        # v3.1 : champ `explanation` recommande (warn, configurable error)
        try:
            enforce_explanation({"name": name, "arguments": args}, mode="warn")
        except ValueError:
            # mode=error explicite (env LAFORGE_EXPLANATION_MODE=error) : propager
            raise

        # Phase 35 (2026-05-25) — RBAC scoped MCP tools. Check ring vs tool
        # required ring AVANT execution. Defense in depth complement JWT scope.
        try:
            from nokido_agent.app.forge_mcp_rbac import check_tool_capability

            # `permissive_unknown` etait laisse a son defaut True : un outil
            # absent de la table RBAC y etait AUTORISE
            # (`tool_unmapped_permissive_default`), et seul le plafond par
            # defaut de `_get_ring_needed` (2) le rattrapait en aval. Defense
            # en profondeur, pas declaration — mesure du 2026-09-12 : 14 des
            # 81 handlers natifs etaient dans ce cas.
            #
            # La table RBAC gouverne les outils NATIFS (`handle_<nom>`). Les
            # noms ROUTES — proxies `netcfg_*` / `docker_*`, outils forges
            # `dyn_*`, module redteam — n'y figurent pas et n'ont pas a y
            # figurer : leur route porte leur garde. Desarmer le defaut pour
            # TOUS les couperait. D'ou la distinction, et non un simple
            # `permissive_unknown=False`.
            # Verrouille par tests/test_outil_natif_non_declare.py, dont le
            # controle NEGATIF echoue si les noms routes se font couper.
            _est_natif = hasattr(self, f"handle_{name}")
            _rbac_ok, _rbac_reason = check_tool_capability(
                name, agent, ring, permissive_unknown=not _est_natif)
            if not _rbac_ok:
                import logging as _lg

                _lg.getLogger("Nokido.Security").warning(
                    f"[RBAC] DENY tool={name} agent={agent} ring={ring}: {_rbac_reason}"
                )
                return {"error": "forbidden", "reason": _rbac_reason, "tool": name, "agent": agent, "ring": ring}
        except ImportError as _e_rbac:
            # FAIL-CLOSED depuis le 2026-09-12 (chantier M0.1).
            #
            # AVANT : `pass` nu. Si `forge_mcp_rbac` devenait inimportable —
            # erreur de syntaxe introduite, dependance manquante, renommage de
            # namespace — l'autorisation disparaissait EN SILENCE et tous les
            # tools passaient. C'est `garde indisponible -> ALLOW`.
            #
            # Or cette table est celle qui protege les tools les plus puissants :
            # `ps_run` et `ps_agent` y sont declares a TRUSTED=2 et ne figurent
            # PAS dans `_TOOL_MIN_RING`. Sans elle, ils retombaient sur le defaut
            # permissif.
            #
            # « compat boot » ne s'applique pas ici : ce code est dans le chemin
            # d'APPEL d'un tool, pas dans l'initialisation. Un echec d'import y
            # bloque des appels, jamais le demarrage du hub.
            #
            # Sans risque mesure : le module s'importe aujourd'hui (_ENFORCE
            # True, mesure du meme jour), donc cette branche n'est pas empruntee
            # en fonctionnement normal.
            #
            # La capture reste ETROITE (`ImportError` seul) : une exception
            # levee par `check_tool_capability` continue de se propager, ce qui
            # est deja fail-closed. L'elargir a `Exception` recreerait le trou.
            # Fige par tests/nr/test_rbac_indisponible_failclosed_nr.py
            import logging as _lg_rbac

            _lg_rbac.getLogger("Nokido.Security").critical(
                "[RBAC] INDISPONIBLE (%s: %s) — refus fail-closed tool=%s agent=%s ring=%s",
                type(_e_rbac).__name__, _e_rbac, name, agent, ring,
            )
            return {
                "error": "forbidden",
                "reason": ("SECURITY: garde d'autorisation indisponible "
                           "(forge_mcp_rbac) — refus fail-closed"),
                "tool": name,
                "agent": agent,
                "ring": ring,
            }

        # CORRIGIBILITE (off-switch d'EXECUTION + seuils ASL, organe forge_corrigibility) :
        # le kill-switch humain (forge_opsec) doit bloquer les tools MUTANTS au niveau du
        # dispatch (pas seulement le restart de service via le watchdog), et les tools a
        # forte capacite sont gates par un niveau ASL. read-only reste permis pendant un
        # lock (l'humain inspecte).
        #
        # CORRIGE LE 2026-09-12 : cette branche etait `except Exception: pass`.
        # La panne — ou la disparition — de l'interrupteur d'arret humain etait
        # donc INDETECTABLE, et valait autorisation. Desormais : journal CRITICAL,
        # et refus BORNE aux tools mutants (le read-only reste permis, l'humain
        # doit garder le moyen d'inspecter pendant l'incident).
        try:
            from nokido_agent.app.forge_corrigibility import corrigibility_gate

            _cg_ok, _cg_reason = corrigibility_gate(name, agent, ring)
            if not _cg_ok:
                import logging as _lg
                _lg.getLogger("Nokido.Security").warning(
                    f"[CORRIGIBILITY] HALT tool={name} agent={agent}: {_cg_reason}")
                return {"error": "corrigibility_halt", "reason": _cg_reason,
                        "tool": name, "agent": agent}
        except Exception as _e_cg:  # noqa: BLE001
            _detail_cg = "%s: %s" % (type(_e_cg).__name__, str(_e_cg)[:140])
            import logging as _lg_cg
            _lg_cg.getLogger("Nokido.Security").critical(
                "[CORRIGIBILITY] garde INATTEIGNABLE (%s) tool=%s agent=%s ring=%s",
                _detail_cg, name, agent, ring)
            if name in self._CORRIGIBILITE_MUTANTS_REPLI:
                return {"error": "corrigibility_indisponible",
                        "reason": ("SECURITY: le garde de corrigibilite est "
                                   "inatteignable (%s) — l'interrupteur d'arret "
                                   "humain ne peut pas etre constate, tool mutant "
                                   "'%s' refuse. Les tools read-only restent "
                                   "disponibles pour le diagnostic."
                                   % (_detail_cg, name)),
                        "tool": name, "agent": agent, "ring": ring}

        # Gate d'intention (Agent Policier) : derive de scope declare. WARN-mode par
        # defaut (LAFORGE_INTENTION_GATE_MODE=warn|error|off) -> bloque seulement si error.
        # Fail-open : toute erreur -> pas de gate (le dispatch n'est JAMAIS casse).
        try:
            from nokido_agent.app.forge_intention_gate import gate_tool_call

            _ig_ok, _ig_reason = gate_tool_call(agent, name)
            if not _ig_ok:
                return {"error": "intention_drift", "reason": _ig_reason,
                        "tool": name, "agent": agent}
        except Exception:
            pass  # fail-open

        # Coupe-circuit COMPORTEMENTAL (anti-fuite-tokens) : throttle la recon FINE
        # (tool `read`) sur du code Nokido, pour TOUT client MCP (agy inclus, sans hook)
        # -> force forge_deep_explore. Compteur FS partage (cross-process). Log observable.
        if name == "read":
            try:
                import sys as _sys, time as _tm
                from pathlib import Path as _P
                _tp = str(_P(__file__).resolve().parent.parent / "tools")
                if _tp not in _sys.path:
                    _sys.path.insert(0, _tp)
                from nokido_agent.tools import forge_recon_breaker as _brk
                _islf = _brk.is_nokido_args(args)
                _v, _why, _n = _brk.verdict(str(agent or "HUB"), "read", _islf)
                try:
                    with open(r"C:/tmp/recon_breaker.log", "a", encoding="utf-8") as _lf:
                        _lf.write(f"{int(_tm.time())} read agent={agent} islf={_islf} v={_v} n={_n}\n")
                except Exception:
                    pass
                if _v == "deny":
                    return {"error": "recon_throttled", "reason": _why,
                            "tool": name, "delegate_to": "forge_deep_explore"}
            except Exception as _e:
                try:
                    with open(r"C:/tmp/recon_breaker.log", "a", encoding="utf-8") as _lf:
                        _lf.write(f"BRK_ERR {type(_e).__name__}: {str(_e)[:140]}\n")
                except Exception:
                    pass

        # ITEM SECURITY: Détection d'injection MCP Claude Desktop
        for k, v in args.items():
            if isinstance(v, str) and ("<system>" in v and "<functions>" in v and "<function>{" in v):
                import logging as _lg

                _lg.getLogger("Nokido.Security").warning(
                    f"[MCP INJECTION] Detected schema injection from {agent} in arg '{k}' of tool '{name}'"
                )

        # ITEM 12 — Filtre sémantique : consulter bugs connus avant dispatch
        if name in ("write", "run") and args:
            try:
                import sqlite3 as _sq

                _hits = (
                    _sq.connect(str(self.db_path), timeout=3)
                    .execute(
                        "SELECT text FROM rag_chunks WHERE domain='lessons' AND text LIKE ? LIMIT 1", (f"%{name}%",)
                    )
                    .fetchone()
                )
                if _hits:
                    import logging as _lg

                    _lg.getLogger("Nokido.Registry").debug(f"[RAG hint] {name}: {_hits[0][:80]}")
            except Exception:
                pass
        # Proxy netcfg-agent-mcp (:8767) — noms legacy netcfg_* (deprecated,
        # remplaces par le tool unifie `netcfg`). Ring check ajoute : cette
        # branche court-circuitait _TOOL_MIN_RING (bypass ring sur les
        # appels netcfg_* directs).
        if name.startswith("netcfg_"):
            _nr = self._TOOL_MIN_RING.get(name, 3)
            if ring > _nr:
                return f"SECURITY: Acces refuse (agent ring {ring} > max autorise {_nr})"
            return await self._handle_netcfg_proxy(name, args, agent, ring)

        # Proxy Docker MCP gateway (stdio, lazy-spawned) — sauf si handler natif handle_<name> existe
        if name.startswith("docker_") and not hasattr(self, f"handle_{name}"):
            return await self._handle_docker_proxy(name, args, agent, ring)

        # Module red-team OPTIONNEL (laforge-redteam) : exegol/ctf_* ne dispatch que si
        # rebranché (LAFORGE_REDTEAM=1 + service :8768). Sinon erreur propre, pas de crash.
        if name in self._REDTEAM_TOOLS or name.startswith(("exegol_", "ctf_")):
            if not self._redteam_enabled():
                return {"error": "module redteam optionnel desactive — activer via "
                                 "LAFORGE_REDTEAM=1 + service :8768 (depot laforge-redteam)"}

        # Essaim Map-Reduce local (ForgeSwarm) — DAG validé puis workers // bornés
        if name == "nokido_ensure_service":
            return await self._handle_ensure_service(args, agent, ring)

        if name == "forge_deep_explore":
            return await self._handle_deep_explore(args, agent, ring)

        if name == "forge_spawn_swarm":
            return await self._handle_spawn_swarm(name, args, agent, ring)

        # Ultra-Review locale (ForgeAudit) — essaim read-only multi-prismes
        if name == "forge_trigger_audit":
            return await self._handle_trigger_audit(name, args, agent, ring)

        # Oracle d'exécution déterministe (sandbox offline) — pont LLM↔vérité
        if name == "oracle_python_repl":
            return await self._handle_oracle_python_repl(name, args, agent, ring)

        # Outils FORGES (forge_tool_forger) exposes en MCP : 2 generiques + dyn_<nom>/outil.
        if name in ("forge_call_dynamic", "forge_list_dynamic_tools") or name.startswith("dyn_"):
            return await self._handle_forge_dynamic(name, args, agent, ring)

        method_name = f"handle_{name}"
        if hasattr(self, method_name):
            ring_needed = self._get_ring_needed(name, args)
            if ring > ring_needed:
                return f"SECURITY: Acces refuse (agent ring {ring} > max autorise {ring_needed})"

            # ── ACCESS SWITCHES — droits dynamiques ReBAC ────────────────────
            # Couche complémentaire au ring : switches DB configurables à chaud.
            # check_access() retourne (allowed|None, reason).
            # None = pas de règle → déléguer au ring check existant (déjà passé).
            # False = DENY explicite → bloquer même si ring OK.
            try:
                import sys as _sw_sys, os as _sw_os

                _sw_app = str(_sw_os.path.join(_sw_os.path.dirname(__file__)))
                if _sw_app not in _sw_sys.path:
                    _sw_sys.path.insert(0, _sw_app)
                from nokido_agent.app.forge_access_switches import check_access as _check_sw

                _resource = args.get("path", args.get("filepath", name))
                _sw_result, _sw_reason = _check_sw(agent, str(_resource), name, ring)
                if _sw_result is False:
                    return f"SECURITY: Switch DENY {agent}→{_resource}:{name} ({_sw_reason})"
                # True ou None → continuer (True = allow explicite, None = pas de règle)
            except ImportError:
                pass  # module pas encore dispo → fail-open
            except Exception as _swe:
                logger.debug(f"[access_switches] skip: {_swe}")
            # ─────────────────────────────────────────────────────────────────

            corr_id = None
            start_evt_id = None
            if name not in ("event_publish", "event_history"):
                try:
                    if not hasattr(self, "_event_bus"):
                        from nokido_agent.app.forge_state_manager import EventBus

                        self._event_bus = EventBus(self.state_mgr)
                    import uuid as _uuid

                    corr_id = f"tool_{name}_{_uuid.uuid4().hex[:8]}"
                    # Offload SQLite sync hors event-loop (wedge trigger #2, RCA 2026-07-02/03)
                    args_preview = await asyncio.to_thread(self._archive_long_args, args, agent, name)
                    start_evt_id = self._event_bus.publish(
                        topic=f"tool.{name}.start",
                        kind="tool_call",
                        data={"args": args_preview, "ring": ring, "caller": agent},
                        agent=agent,
                        corr_id=corr_id,
                        trusted=True,
                    )
                except Exception as _e:
                    logger.debug(f"EventBus start emit skipped: {_e}")

            handler = getattr(self, method_name)
            t0 = time.monotonic()
            try:
                result = await handler(args, agent, ring)
                elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

                if name not in ("event_publish", "event_history") and hasattr(self, "_event_bus"):
                    try:
                        result_str = str(result)
                        self._event_bus.publish(
                            topic=f"tool.{name}.end",
                            kind="tool_result",
                            data={
                                "ok": not result_str.startswith(("ERR", "SECURITY", "Erreur", "FAIL", "SECRET GUARD")),
                                "latency_ms": elapsed_ms,
                                "result_summary": result_str[:200],
                            },
                            agent="HUB",
                            corr_id=corr_id,
                            parent_id=start_evt_id if isinstance(start_evt_id, str) else None,
                            trusted=True,
                        )
                    except Exception as _e:
                        logger.debug(f"EventBus end emit skipped: {_e}")
                # GUARD DE SORTIE = SAFETY NET contre les DUMPS bruts volumineux
                # (stdout shell, HTML render, output pentest — re-ciblables via
                # grep/filtre), PAS un distillateur routinier. RÈGLE D'OR : la
                # frugalité ne doit JAMAIS réduire l'intelligence -> on n'agit QUE
                # sur une ALLOWLIST de tools à sortie BRUTE, JAMAIS sur les porteurs
                # de signal (ask/rag/research_agent/crawl/read/read_function_body/
                # orchestrate/bundle/skill/biblio/graph...). JSON laissé intact.
                # Seuil haut (12k) = ne mord que sur le pathologique. Opt-out
                # FORGE_TOOL_OUTPUT_CAP=0.
                _CAP_TOOLS = {"run", "browser", "netcfg"}
                if isinstance(result, str) and name in _CAP_TOOLS:
                    if result.lstrip()[:1] not in ("{", "["):  # JSON laissé intact
                        result = self._strip_output_noise(result)
                    _cap = int(os.environ.get("FORGE_TOOL_OUTPUT_CAP", "12000"))
                    if _cap and len(result) > _cap:
                        _is_json = result.lstrip()[:1] in ("{", "[")
                        if _is_json:
                            try:
                                json.loads(result)
                            except Exception:
                                _is_json = False
                        if not _is_json:
                            # CCR réversible : stashe le COMPLET (zéro perte du milieu),
                            # renvoie head+tail+pointeur de récupération. Fallback (échec
                            # archivage) = ancien comportement (re-grep/rag).
                            _full_n = len(result)
                            _ccr = self._archive_blob(result, agent, f"tool.{name}.output")
                            _ptr = (
                                f"\n\n[… SORTIE TRONQUÉE par le hub : {_full_n} chars ({name}). "
                                + (f"COMPLET récupérable : read(action='archived', id='{_ccr}'). …]\n\n"
                                   if _ccr else "Affine (grep/offset/limit) ou interroge via `rag`. …]\n\n")
                            )
                            result = result[: int(_cap * 0.8)] + _ptr + result[-int(_cap * 0.15) :]
                # -- ENVELOPPE M2M -- auto-surface postal, UNIVERSEL (ce dispatcher = toutes les
                # surfaces MCP : HTTP CLI + desktop via bridge). Flag OFF par defaut + fail-open :
                # ne casse JAMAIS un tool call. Anti-spoof (identite forte) : ring < 4 = token-
                # prouve (resolve_identity planche tout header non authentifie a HEADER_FLOOR=4).
                # On ne draine QUE l'agent resolu -> zero fuite cross-agent.
                try:
                    if (os.environ.get("LAFORGE_M2M_ENVELOPE", "0") == "1"
                            and isinstance(result, str) and int(ring) < 4
                            and str(agent).upper() not in ("HUB", "UNKNOWN")):
                        from nokido_agent.app.forge_postal import envelope_for as _envf

                        _env = _envf(agent)
                        if _env:
                            result = result + _env
                except Exception:
                    pass  # fail-open : l'enveloppe M2M ne casse jamais un tool call

                # -- L1 : FILTRAGE DES SECRETS EN SORTIE D'OUTIL (2026-09-12) --
                # Mesure AST du jour : `forge_mcp_registry`, `mcp_server_tools` et
                # `mcp_bridge` rendaient leurs resultats avec ZERO appel de
                # filtrage. Les cinq porteurs sont pourtant cables et `post_flight`
                # a six appelants — tous sur des chemins LLM, AUCUN ici.
                #
                # Un firewall sur le PROMPT protege ce qu'on ENVOIE. Une sortie
                # d'outil est l'AUTRE direction : elle entre dans le contexte du
                # modele sans passer par la porte d'entree. Un `cat` de fichier de
                # configuration, un `env`, un journal portant un jeton : le secret
                # revient par le RESULTAT.
                #
                # `redact_tool_output` applique les DEUX jeux de motifs du depot,
                # mesures DISJOINTS a 100 % (12 d'infrastructure, 10 de clefs
                # d'API), en ecartant l'heuristique `[A-Za-z0-9]{64}` qui matchait
                # tout hash sha256.
                if isinstance(result, str) and result:
                    try:
                        from nokido_agent.app.forge_semantic_firewall import (
                            redact_tool_output as _redact_outil,
                        )

                        result, _bilan = _redact_outil(result, outil=name)
                        if _bilan.get("secrets_rediges"):
                            logger.warning(
                                "[L1] %s : %d secret(s) rediges avant remise au "
                                "modele (%d infra + %d clefs)", name,
                                _bilan["secrets_rediges"],
                                _bilan.get("dont_infrastructure", 0),
                                _bilan.get("dont_clefs_api", 0))
                    except Exception as _fe:  # noqa: BLE001
                        # Fail-open ASSUME : un filtre casse ne doit pas briquer le
                        # dispatch. Mais JAMAIS muet — sans cette trace, une sortie
                        # non filtree serait indiscernable d'une sortie propre, ce
                        # qui est exactement le defaut que ce bloc repare.
                        logger.error(
                            "[L1] filtrage de la sortie de %s INDISPONIBLE (%s: %s) "
                            "— le resultat part au modele SANS avoir ete filtre",
                            name, type(_fe).__name__, str(_fe)[:100])
                return result
            except SecretGuardViolation as e:
                # v3 : violation SecretGuard = retour clair au caller, log deja fait par le guard
                elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                if name not in ("event_publish", "event_history") and hasattr(self, "_event_bus"):
                    try:
                        self._event_bus.publish(
                            topic=f"tool.{name}.end",
                            kind="tool_result",
                            data={"ok": False, "latency_ms": elapsed_ms, "error": f"SecretGuardViolation: {e}"[:200]},
                            agent="HUB",
                            corr_id=corr_id,
                            parent_id=start_evt_id if isinstance(start_evt_id, str) else None,
                            trusted=True,
                        )
                    except Exception:
                        pass
                return str(e)
            except Exception as e:
                elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
                logger.error(f"Erreur handler {name}: {e}")
                if name not in ("event_publish", "event_history") and hasattr(self, "_event_bus"):
                    try:
                        self._event_bus.publish(
                            topic=f"tool.{name}.end",
                            kind="tool_result",
                            data={"ok": False, "latency_ms": elapsed_ms, "error": f"{type(e).__name__}: {e}"[:200]},
                            agent="HUB",
                            corr_id=corr_id,
                            parent_id=start_evt_id if isinstance(start_evt_id, str) else None,
                            trusted=True,
                        )
                    except Exception:
                        pass
                return f"ERR: {type(e).__name__}: {e}"
        return f"{OUTIL_INCONNU}: {name}"

    # Ring minimum par tool (défense en profondeur côté registry)
    # REPLI de dernier recours du garde de corrigibilite. DUPLIQUE deliberement
    # `forge_corrigibility.MUTATING_TOOLS` : quand ce module est lui-meme
    # inatteignable, le dispatch n'a plus aucune autre source pour savoir quels
    # tools mutent le monde. Une duplication non testee derive ; celle-ci est
    # verrouillee par `tests/nr/test_corrigibilite_failclosed_nr.py`, qui echoue
    # des que les deux listes divergent.
    _CORRIGIBILITE_MUTANTS_REPLI: frozenset = frozenset((
        "agy_config", "agy_run", "apply_patch", "bundle", "docker_action",
        "dyn_orchestrate", "edit", "execute", "forge_call_dynamic",
        "forge_spawn_swarm", "governed_edit", "loop_orchestrate",
        "manage_forge_lifecycle", "nokido_ensure_service", "orchestrate",
        "plan", "run", "task", "trigger_autonomous_evolution", "write",
    ))

    _TOOL_MIN_RING: dict = {
        "nokido_ensure_service": 4,
        "tool_scope": 3,
        "forge_deep_explore": 4,
        "forge_call_dynamic": 2,
        "forge_list_dynamic_tools": 2,
        "write": 0,
        "set_mode": 0,
        "governed_edit": 3,
        "auto_test": 1,
        "trigger_autonomous_evolution": 1,
        "crawl": 1,
        "manage_forge_lifecycle": 3,
        "query": 2,
        "event": 2,
        # poll: 14 512 appels mesures, `handle_poll` present, mais ABSENT de ce dict
        # jusqu'au 2026-08-12. Consequence exacte : le dispatch le laissait passer
        # (defaut ring 3 via `.get(name, 3)`) tandis que `tools/list` ne le montrait
        # a personne — un outil massivement utilise et invisible au catalogue. Le
        # declarer a 3 n'accorde AUCUN privilege nouveau : il aligne la vitrine sur
        # ce qui etait deja permis.
        "poll": 3,
        # run/hub/task/rag: min_ring=3 (sync DB) → visible + exécutable par GEMINI (ring 3)
        "run": 3,
        "oracle_python_repl": 3,
        "hub": 3,
        "task": 3,
        "rag": 3,
        "read": 3,
        # github/memory : MEME DEFAUT QUE `poll` ci-dessus, re-paye le 2026-09-13.
        # Handlers presents, schemas complets, dispatch ouvert (`.get(name, 3)`) --
        # mais ABSENTS de ce dict, donc `tools/list` ne les montrait A PERSONNE.
        # CODEX a donc cherche un depot par `run action=github`, faute de voir le
        # tool `github` ; or `run` n'expose ni `repo` ni `sub`, l'URL devenait
        # `https://api.github.com/repos/` et GitHub rendait 404 -- lu des heures
        # durant comme « le hub n'a pas acces », alors que le jeton du coffre rend
        # HTTP 200 push=True sur ce meme depot. Declarer a 3 n'accorde AUCUN
        # privilege nouveau : on aligne la vitrine sur ce qui etait deja permis.
        "github": 3,
        "memory": 3,
        "query_json": 3,
        "web_search": 3,
        "ask": 3,
        "route_task": 3,
        "docker_action": 2,
        "research_agent": 3,
        "biblio": 3,
        "skill": 3,
        "read_function_body": 3,
        "get_file_skeleton": 4,
        "get_function_dependencies": 4,
        # Lecture seule, agrege des organes deja exposes : meme ring qu'eux.
        "introspect": 4,
        # netcfg : tool unifie verb-dispatcher (12 netcfg_* collapses en 1).
        # action=open_terminal gardee ring<=1 dans handle_netcfg.
        "netcfg": 3,
        # legacy : netcfg_open_terminal garde ring 1 pour la branche de
        # compat startswith (les autres netcfg_* -> defaut 3).
        "netcfg_open_terminal": 1,
        "forge_spawn_swarm": 2,
        "forge_trigger_audit": 2,
        # orchestrate : agentic loop Qwen → tool_calls → dispatch (ring 2 min)
        "orchestrate": 2,
        "loop_orchestrate": 2,
        "bundle": 2,
        "plan": 2,
        "execute": 2,
        "route_dt": 2,
        "cross_platform_fs": 2,
        "graph_edge_score": 3,
        "graph_cve_propagate": 2,
        "graph_ppr": 2,
        # ── forge.swarm.* : blackboard zoné (write-funnel mono-writer) ──
        "blackboard_read_zone": 4,
        "blackboard_propose_fact": 2,
        "forge_stats": 4,
        "agy_run": 2,
        "agy_config": 3,
        "agy_add_dir": 2,
    }
    # Tools exposés par défaut si agent non identifié (ring > 3)
    _TOOLS_PUBLIC: set = {"web_search", "ask", "hub", "forge_deep_explore", "nokido_ensure_service"}

    # Sous-actions valides du tool unifie `netcfg` (proxy netcfg-agent-mcp :8767)
    _NETCFG_ACTIONS: frozenset = frozenset(
        {
            "ping",
            "vendors",
            "list_equipments",
            "get_dashboard",
            "topology",
            "audit",
            "verify_chain",
            "preview_deploy",
            "open_terminal",
            "export_topology",
            "vendor_search",
            "vendor_stats",
        }
    )

    async def handle_plan(self, args: dict, agent: str, ring: int) -> str:
        """Handler GOAP Planner — décompose un goal en subgoals + exécution optionnelle."""
        goal = args.get("goal")
        if not goal:
            return "ERR: parametre 'goal' requis"

        ring_max = int(args.get("ring_max", 2))
        context = args.get("context", {})
        do_execute = bool(args.get("execute", False))

        import sys

        sys.path.insert(0, str(self.root))
        try:
            from nokido_agent.app.forge_goap import GoalPlanner, execute_plan

            async def _gated_dispatch(intent: dict) -> dict:
                res = await self.dispatch(intent.get("method"), intent.get("params", {}),
                                          agent=agent, ring=ring)
                return classer_retour_intent(res, intent)

            plan = await GoalPlanner.plan(goal, context=context, ring_max=ring_max)
            result = plan.to_dict()
            if do_execute:
                traj = await execute_plan(plan, dispatch_fn=_gated_dispatch)
                result["trajectory"] = {
                    "job_id": traj.job_id,
                    "steps": [{"intent": s.intent, "status": s.status, "result": s.result} for s in traj.steps],
                }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"ERR handle_plan: {type(e).__name__}: {e}"

    async def handle_execute(self, args: dict, agent: str, ring: int) -> str:
        """Exécute un PlanTree sérialisé (plan JSON issu de handle_plan)."""
        import sys, json as _j

        sys.path.insert(0, str(self.root))
        plan_dict = args.get("plan")
        if not plan_dict:
            return "ERR: parametre 'plan' requis (JSON PlanTree)"
        if isinstance(plan_dict, str):
            try:
                plan_dict = _j.loads(plan_dict)
            except Exception as e:
                return f"ERR: plan JSON invalide: {e}"
        try:
            from nokido_agent.app.forge_goap import execute_plan, PlanTree, SubGoal
            from dataclasses import fields as _fields

            async def _gated_dispatch(intent: dict) -> dict:
                res = await self.dispatch(intent.get("method"), intent.get("params", {}),
                                          agent=agent, ring=ring)
                return classer_retour_intent(res, intent)

            sgs = []
            for sg_data in plan_dict.get("subgoals", []):
                if isinstance(sg_data, dict):
                    sgs.append(SubGoal(name=sg_data.get("name", ""), actions=sg_data.get("actions", [])))
                else:
                    sgs.append(sg_data)

            clean_dict = {k: plan_dict[k] for k in plan_dict if k in {f.name for f in _fields(PlanTree)}}
            clean_dict["subgoals"] = sgs
            plan = PlanTree(**clean_dict)
            traj = await execute_plan(plan, dispatch_fn=_gated_dispatch)
            return _j.dumps(
                {
                    "ok": True,
                    "job_id": traj.job_id,
                    "steps": [{"intent": s.intent, "status": s.status, "result": s.result} for s in traj.steps],
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            return f"ERR handle_execute: {type(e).__name__}: {e}"

    async def handle_bundle_read(self, args: dict, agent: str, ring: int) -> str:
        """Lit fichiers + grep + RAG en un seul call. Économise N round-trips."""
        import re as _re, sqlite3 as _sq, json as _j

        files_out, grep_out, rag_out = {}, [], []

        for fp in args.get("files", []):
            p = self.root / fp if not Path(fp).is_absolute() else Path(fp)
            if p.exists():
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[:100]
                files_out[fp] = lines

        import shutil as _sh, subprocess as _sp, shlex as _sl # Added imports

        g = args.get("grep")
        if g:
            pat, gpath_str = g.get("pattern", ""), str(self.root / g.get("path", "app"))
            if pat and Path(gpath_str).exists():
                rg_path = _sh.which("rg")
                if rg_path:
                    # Use ripgrep
                    try:
                        command = [rg_path, "--json", "-P", pat, gpath_str]
                        proc = _sp.run(command, capture_output=True, text=True, check=False, encoding="utf-8", errors="replace")
                        if proc.returncode in (0, 1):  # 0 = matches, 1 = no matches
                            for line in proc.stdout.splitlines():
                                try:
                                    json_line = _j.loads(line)
                                    if json_line.get("type") == "match":
                                        file_path = json_line["data"]["path"]["text"]
                                        match_text = [json_line["data"]["lines"]["text"]]
                                        if match_text:
                                            grep_out.append({"file": file_path, "matches": match_text[:10]})
                                except _j.JSONDecodeError:
                                    continue
                    except Exception as _e:
                        grep_out.append({"error": f"ripgrep failed: {type(_e).__name__}: {_e}"})
                else:
                    # No ripgrep binary -> python re fallback
                    try:
                        rx = _re.compile(pat)
                        base = Path(gpath_str)
                        targets = list(base.rglob("*.py")) if base.is_dir() else [base]
                        for fpath in targets[:2000]:
                            try:
                                for ln in fpath.read_text(encoding="utf-8", errors="replace").splitlines():
                                    if rx.search(ln):
                                        grep_out.append({"file": str(fpath), "matches": [ln[:300]]})
                                        break
                            except Exception:
                                continue
                    except Exception as _e:
                        grep_out.append({"error": f"re fallback failed: {type(_e).__name__}: {_e}"})

        # --- RAG (best-effort FTS5, lecture seule) ---
        rag_q = args.get("rag")
        if rag_q:
            try:
                _db = self.root / "RAG" / "embeddings.db"
                if _db.exists():
                    _con = _sq.connect(f"file:{_db.as_posix()}?mode=ro", uri=True)
                    try:
                        _rows = _con.execute(
                            "SELECT source, substr(text,1,300) FROM rag_fts WHERE rag_fts MATCH ? "
                            "ORDER BY bm25(rag_fts) LIMIT 8",
                            (rag_q,),
                        ).fetchall()
                        rag_out = [{"source": _s, "preview": _t} for _s, _t in _rows]
                    finally:
                        _con.close()
            except Exception as _e:
                rag_out.append({"error": f"rag failed: {type(_e).__name__}: {_e}"})

        return _j.dumps({"files": files_out, "grep": grep_out, "rag": rag_out}, ensure_ascii=False)

    async def handle_query_json(self, args: dict, agent: str, ring: int) -> str:
        """Queries a JSON or JSONL file using JsonQueryTool."""
        file_path = args.get("file_path")
        query = args.get("query")

        if not file_path or not query:
            return "ERR: 'file_path' and 'query' arguments are required."

        # Security check: Ensure the file path is within the allowed root
        abs_file_path = (self.root / file_path).resolve()
        if not abs_file_path.is_relative_to(self.root):
            return f"ERR: File path '{file_path}' is outside the allowed project directory."

        try:
            from nokido_agent.app.forge_json_query import JsonQueryTool  # lazy: découple le gate du module
        except Exception as _e:
            return f"ERR: JsonQueryTool indisponible: {type(_e).__name__}: {_e}"
        json_query_tool = JsonQueryTool()
        result = json_query_tool.query_json(str(abs_file_path), query)
        return json.dumps(result, ensure_ascii=False)


    async def handle_bundle(self, args: dict, agent: str, ring: int) -> str:
        """
        Exécute une séquence de tool calls MCP en un seul round-trip.
        S'arrête à la première erreur pour éviter des corruptions en chaîne.
        """
        import json as _j

        calls = args.get("calls", [])
        if not isinstance(calls, list):
            return "ERR: 'calls' doit être une liste."

        results = []
        for i, call in enumerate(calls):
            tool = call.get("tool")
            t_args = call.get("args", {})
            if not tool:
                results.append({"index": i, "status": "ERR", "error": "tool name missing"})
                break

            try:
                res = await self.dispatch(tool, t_args, agent=agent, ring=ring)
                str_res = str(res)
                if str_res.startswith(("ERR", "SECURITY", "SECRET GUARD", "FAIL")):
                    results.append({"index": i, "tool": tool, "status": "ERR", "result": str_res})
                    break
                results.append({"index": i, "tool": tool, "status": "OK", "result": str_res})
            except Exception as e:
                results.append({"index": i, "tool": tool, "status": "ERR", "error": str(e)})
                break

        return _j.dumps(
            {"executed": len(results), "total": len(calls), "results": results}, ensure_ascii=False, indent=2
        )

    # ── Module red-team OPTIONNEL (laforge-redteam) — gate de visibilité ──────────
    # exegol/ctf_* = capacité offensive dans un dépôt séparé rebranchable. Par défaut
    # OFF : invisibles de tout tools/list (cœur propre). ON (LAFORGE_REDTEAM=1 + service
    # :8768) : réapparaissent pour ring<=2 — SAUF agents en denylist (Fable/BRIDGE).
    _REDTEAM_TOOLS = frozenset({"exegol", "ctf_solver", "ctf_browser"})
    _REDTEAM_DYN_PREFIXES = ("dyn_redteam_", "dyn_exegol", "dyn_ctf")
    # Denylist namespace par agent : BRIDGE (Claude/Fable) ne voit JAMAIS l'offensif,
    # même module branché — sa garantie durable est ici, pas dans le ring.
    _AGENT_TOOL_DENY = {"BRIDGE": frozenset(_REDTEAM_TOOLS | set(_REDTEAM_DYN_PREFIXES))}

    @staticmethod
    def _redteam_enabled() -> bool:
        """Module optionnel laforge-redteam rebranché ? Lu LIVE à chaque tools/list :
        env LAFORGE_REDTEAM=1 OU marqueur `sandbox/redteam.enabled` (posé/retiré par le
        service :8768 → rebranch sans restart hub)."""
        import os
        from pathlib import Path
        if os.environ.get("LAFORGE_REDTEAM", "0") == "1":
            return True
        try:
            return (Path(__file__).resolve().parent.parent / "sandbox" / "redteam.enabled").exists()
        except Exception:
            return False

    def get_tool_list(self, ring: int = 4, agent: str = "UNKNOWN") -> List[Dict[str, Any]]:
        """
        Retourne les tools filtrés selon le ring de l agent.
        Ring 0 (admin) : tous les tools.
        Ring 4+ (non identifié) : subset minimal public.
        Principe organique : la membrane expose ce qui est nécessaire,
        pas tout ce qui existe — couplage structurel minimal par défaut.
        """
        allowed = {n for n, r in self._TOOL_MIN_RING.items() if ring <= r} if ring <= 3 else self._TOOLS_PUBLIC
        rt_off = not self._redteam_enabled()
        deny = self._AGENT_TOOL_DENY.get(agent, ())

        def _blocked(n: str) -> bool:
            # module optionnel désactivé → offensif invisible (statique + dynamique)
            if rt_off and (n in self._REDTEAM_TOOLS or n.startswith(self._REDTEAM_DYN_PREFIXES)):
                return True
            # denylist par agent (BRIDGE/Fable) : offensif jamais exposé, même module ON
            return any(n == d or n.startswith(d) for d in deny)

        # Outils forges dynamiques (dyn_<nom>) : noms non-statiques -> autorises a ring<=2
        # (le ring est porte par forge_call_dynamic ; l'exec passe par SecretGuard).
        visible = [t for t in self._all_tools()
                   if (t["name"] in allowed or (ring <= 2 and t["name"].startswith("dyn_")))
                   and not _blocked(t["name"])]
        # Sprint 2 : scope dynamique par agent (tool_scope). VISIBILITE seule —
        # le dispatch reste ouvert (un outil hors scope demeure appelable).
        try:
            from nokido_agent.app import forge_tool_scope as _ts
            # Perimetre DECLARE par defaut. Avec LAFORGE_TOOLS_LIST_ROLESCOPE,
            # on prend `expected_scope_for` : declare d'abord, sinon DERIVE du
            # role (profil system-owned) -- ce qui ferme le bypass opt-out, un
            # agent ne pouvant plus elargir sa vue en ne declarant rien.
            # Desarme par defaut : le perimetre derive peut masquer un outil
            # dont l'agent a besoin (mesure : `code_recon` n'inclut pas
            # `governed_edit`). Le dispatch, lui, reste ouvert dans les deux cas.
            if os.environ.get("LAFORGE_TOOLS_LIST_ROLESCOPE", "").strip().lower() in (
                "1", "true", "on", "yes"
            ):
                _scope, _src = _ts.expected_scope_for(agent)
            else:
                _scope, _src = _ts.active_tools_for(agent), "declared"
            if _scope:
                visible = [t for t in visible if t["name"] in _scope]
        except Exception as _se:
            # fail-open volontaire (ne jamais casser tools/list), mais PAS muet :
            # un scope qui s'evapore sur une erreur d'import doit laisser une trace.
            logger.debug("[tool_scope] perimetre indisponible (fail-open) : %s", _se)
        # Sprint 1 anti context-bomb : vue telegraphique NEGOCIEE par client.
        ca = self._compact_agents()
        if ca and ("*" in ca or (agent or "").upper() in ca):
            return self._compact_tools(visible)
        return visible

    # v3.1 : description standard du champ `explanation` (pattern Cursor / Augment).
    _EXPLANATION_FIELD: Dict[str, str] = {
        "type": "string",
        "description": (
            "One sentence explanation as to why this tool is being used, "
            "and how it contributes to the goal. Optional during transition "
            "(warn-only), required after 2026-08-01 (set "
            "LAFORGE_EXPLANATION_MODE=error to enforce now)."
        ),
    }

    def _inject_explanation_field(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Injecte `explanation` (optionnel) dans inputSchema.properties de
        chaque tool. Idempotent : ne touche pas si deja present.
        """
        for t in tools:
            schema = t.get("inputSchema") or {}
            props = schema.setdefault("properties", {})
            if "explanation" not in props:
                props["explanation"] = dict(self._EXPLANATION_FIELD)
            # NOTE : volontairement PAS ajoute dans `required` (mode warn).
        return tools

    async def handle_tool_scope(self, args: Dict[str, Any], agent: str, ring: int):
        """Sprint 2 anti context-bomb : scope dynamique du catalogue par agent.
        Delegue a forge_tool_scope (classifieur semantique LOCAL + etat +
        push list_changed). Sync -> to_thread (embeddings = I/O, anti-wedge)."""
        try:
            import sys as _s, os as _o
            _app = _o.path.dirname(_o.path.abspath(__file__))
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_tool_scope import handle as _ts_handle
            return await asyncio.to_thread(_ts_handle, dict(args or {}), agent, ring)
        except Exception as e:  # noqa: BLE001 - jamais casser le dispatch
            return {"intent_code": "ERR_SCOPE_INTERNAL", "error": str(e)[:200]}

    # ── Mode compact negocie par client (Sprint 1 anti context-bomb) ────────
    # Vue TELEGRAPHIQUE du catalogue pour les surfaces sans deferral de schemas
    # (AGY, bridge stdio, cline). Opt-in par agent : env LAFORGE_TOOLS_COMPACT
    # ("*" ou CSV de noms) OU marqueur sandbox/tools_compact.txt (CSV, lu LIVE
    # a chaque tools/list -> toggle sans restart hub, miroir _redteam_enabled).
    # Le catalogue CANONIQUE n'est jamais modifie (copie par tool).
    _COMPACT_DESC_MAX = 200
    _COMPACT_PROP_DESC_MAX = 80
    _COMPACT_EXPLANATION_DESC = "Pourquoi cet appel (1 phrase)."

    def _compact_agents(self) -> set:
        """Agents ayant negocie la vue compacte. Lu LIVE a chaque tools/list."""
        raw = os.environ.get("LAFORGE_TOOLS_COMPACT", "") or ""
        try:
            marker = Path(__file__).resolve().parent.parent / "sandbox" / "tools_compact.txt"
            if marker.exists():
                raw = raw + "," + marker.read_text(encoding="utf-8")
        except Exception:
            pass  # marqueur best-effort : jamais bloquer tools/list
        return {a.strip().upper() for a in raw.replace(";", ",").split(",") if a.strip()}

    def _compact_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Vue telegraphique : 1re phrase + hint action= ; descriptions de
        proprietes tronquees ; enums/required/types INTACTS ; zero mutation
        du canonique (copie par tool)."""
        import re  # local : le `import re` module-level du fichier est tardif
        out: List[Dict[str, Any]] = []
        for t in tools:
            t2 = dict(t)
            desc = (t2.get("description") or "").strip()
            first = desc.split("\n", 1)[0].strip()
            cut = first.find(". ")
            if 0 < cut < self._COMPACT_DESC_MAX:
                first = first[: cut + 1]
            m = re.search(r"action=[\w|\-]+", desc)
            hint = m.group(0) if (m and m.group(0) not in first) else ""
            budget = self._COMPACT_DESC_MAX - (len(hint) + 1 if hint else 0)
            if len(first) > budget:
                first = first[: max(0, budget - 1)].rstrip() + "..."
            if hint:
                first = (first + " " + hint)[: self._COMPACT_DESC_MAX]
            t2["description"] = first
            schema = t2.get("inputSchema") or {}
            props: Dict[str, Any] = {}
            for k, p in (schema.get("properties") or {}).items():
                p2 = dict(p)
                if k == "explanation":
                    p2["description"] = self._COMPACT_EXPLANATION_DESC
                else:
                    pd = p2.get("description")
                    if isinstance(pd, str) and len(pd) > self._COMPACT_PROP_DESC_MAX:
                        p2["description"] = pd[: self._COMPACT_PROP_DESC_MAX - 3] + "..."
                props[k] = p2
            t2["inputSchema"] = dict(schema)
            t2["inputSchema"]["properties"] = props
            out.append(t2)
        return out

    def _forge_dynamic_catalog(self) -> List[Dict[str, Any]]:
        """Outils FORGES exposes en MCP. 2 generiques (forge_call_dynamic,
        forge_list_dynamic_tools) + 1 entree `dyn_<nom>` par outil forge (A2,
        decouverte nommee). Lu a chaque tools/list -> frais. SecretGuard sur l'exec."""
        tools = [
            {"name": "forge_call_dynamic",
             "description": "Invoque un outil forge par son nom (registre forge_tool_forger). SecretGuard sur l'exec.",
             "inputSchema": {"type": "object", "properties": {
                 "name": {"type": "string", "description": "nom de l'outil forge"},
                 "kwargs": {"type": "object", "description": "arguments de l'outil"}},
                 "required": ["name"]}},
            {"name": "forge_list_dynamic_tools",
             "description": "Liste les outils forges disponibles (nom, signature, description).",
             "inputSchema": {"type": "object", "properties": {}}},
        ]
        try:
            import sys as _s
            from pathlib import Path as _P

            _app = str(_P(__file__).resolve().parent)
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_tool_forger import forge_list_dynamic_tools

            for t in forge_list_dynamic_tools().get("tools", []):
                tools.append({
                    "name": f"dyn_{t['name']}",
                    "description": f"[forge] {t.get('description', '')} {t.get('signature', '')}".strip(),
                    "inputSchema": {"type": "object", "properties": {
                        "kwargs": {"type": "object", "description": "arguments de l'outil forge"}}},
                })
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[catalogue] outils forges NON ajoutes au catalogue dynamique (%s: %s) "
                "| consequence: un client verra un catalogue INCOMPLET et conclura que "
                "l'outil n'existe pas, alors qu'il est seulement invisible",
                type(e).__name__, str(e)[:100])
        return tools

    async def _handle_forge_dynamic(self, name: str, args: Dict[str, Any], agent: str, ring: int):
        """Route les outils forges (ring 2). dyn_<nom> -> forge_call_dynamic(<nom>).
        L'exec est gardee par SecretGuard cote forge_tool_forger."""
        if ring > 2:
            return f"SECURITY: Acces refuse (agent ring {ring} > max autorise 2)"
        try:
            import sys as _s
            from pathlib import Path as _P

            _app = str(_P(__file__).resolve().parent)
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_tool_forger import forge_call_dynamic, forge_list_dynamic_tools
        except Exception as e:
            return f"ERR: forge_tool_forger indisponible: {e}"
        if name == "forge_list_dynamic_tools":
            return forge_list_dynamic_tools()
        tool_name = args.get("name", "") if name == "forge_call_dynamic" else name[len("dyn_"):]
        if not tool_name:
            return "ERR: name requis"
        kwargs = args.get("kwargs", {}) or {}
        if not isinstance(kwargs, dict):
            return "ERR: kwargs doit etre un objet"
        return forge_call_dynamic(tool_name, **kwargs)

    def _all_tools(self) -> List[Dict[str, Any]]:
        """Catalogue complet — source de vérité interne.

        v3.1 : `explanation` est injecte dans tous les inputSchema via
        `_inject_explanation_field` (cf. _get_tool_catalog wrapper).
        """
        tools = self._inject_explanation_field(
            self._raw_tool_catalog() + self._forge_dynamic_catalog())
        return self._inject_annotations(tools)

    def _inject_annotations(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Injecte `annotations` (spec MCP 2026-07-28) depuis `forge_tool_annotations`.

        Le catalogue presentait `run` et `read` avec la meme neutralite : rien n'y
        disait lequel des deux peut detruire. Ces annotations le disent -- sans
        rien BLOQUER : ce qui bloque reste le videur, `forge_tool_gate` et les
        guards d'action. C'est une signaletique, pas une securite, et la spec
        elle-meme interdit d'y fonder une decision de securite.

        Un echec d'import ne passe PAS en silence : sans annotations, la spec
        presume chaque tool destructeur -- bon defaut, mais qui masquerait la
        disparition de la table. On le journalise une fois, puis on sert le
        catalogue : `tools/list` ne doit jamais casser pour un ornement.
        """
        try:
            from nokido_agent.app.forge_tool_annotations import annoter
        except Exception as _ae:  # table absente ou cassee : le DIRE, une fois
            if not getattr(self, "_annotations_signalees", False):
                self._annotations_signalees = True
                logger.warning(
                    "[annotations] table indisponible (%s) : le catalogue sort SANS "
                    "annotations -- chaque tool sera presume destructeur par defaut", _ae)
            return tools
        try:
            return annoter(tools)
        except Exception as _ae:
            if not getattr(self, "_annotations_signalees", False):
                self._annotations_signalees = True
                logger.warning(
                    "[annotations] injection echouee (%s) : catalogue brut servi", _ae)
            return tools

    def _raw_tool_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue brut (sans injection de `explanation`)."""
        return [
            {
                "name": "tool_scope",
                "description": "Scope dynamique du catalogue MCP (anti context-bomb). action=set|clear|status. set: intent -> classifieur semantique LOCAL -> tools/list reduit au groupe pertinent + CORE (push list_changed). Reponses M2M intent codes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["set", "clear", "status"]},
                        "intent": {"type": "string", "description": "But de la session (action=set)"},
                        "target_agent": {"type": "string", "description": "Agent vise (defaut: appelant ; autre = ring<=1)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "agy_run",
                "description": "Execute an agy task command safely.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to run"},
                        "timeout": {"type": "integer", "description": "Optional timeout in seconds"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "agy_config",
                "description": "Read or write settings.json settings.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["read", "write"], "description": "Read or write action"},
                        "key": {"type": "string", "description": "Settings key to read or write"},
                        "value": {"description": "Settings value to write (for write action)"},
                    },
                    "required": ["action", "key"],
                },
            },
            {
                "name": "agy_add_dir",
                "description": "Add a directory path to trusted workspaces.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the workspace directory to trust"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "nokido_ensure_service",
                "description": (
                    "USE THIS to guarantee a Nokido service is in a desired state "
                    "(docker, searxng, hub, ollama, netcfg, webhub, graph, embed, lmstudio). "
                    "Do NOT write keeper/diagnostic scripts, do NOT run docker commands, do "
                    "NOT diagnose manually. The Hub owns the privileges (SeTcbPrivilege), "
                    "daemons and containers. You are a CLIENT: declare the intent, the Hub "
                    "makes it true."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "docker | searxng | hub | ollama | netcfg | webhub | graph | embed | lmstudio (or a Nokido<Name>)."},
                        "desired_state": {"type": "string", "enum": ["running", "stopped", "restarted"], "description": "Desired state (default running)."},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "forge_deep_explore",
                "description": (
                    "USE THIS FIRST for ANY codebase exploration, deep read, multi-file "
                    "recon, or 'understand how X works' on Nokido. Do NOT use native "
                    "search/read or Agent(Explore) for this. Pass your GOAL; the LOCAL "
                    "Nokido network runs the heavy reconnaissance for FREE (0 cloud "
                    "token) and returns a condensed summary with file:line references."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "description": "What you want to understand (natural-language goal)."},
                        "target": {"type": "string", "description": "Optional regex/keywords (| = OR) to focus the search."},
                        "globs": {"type": "string", "description": "Optional comma globs (default app/forge_*.py,tools/*.py)."},
                        "breadth": {"type": "string", "enum": ["narrow", "medium", "wide"], "description": "Search breadth (default medium)."},
                    },
                    "required": ["intent"],
                },
            },
            {
                "name": "netcfg",
                "description": "netcfg-agent (:8767) — config reseau multi-vendor. Verb-dispatcher : action=ping|vendors|list_equipments|get_dashboard|topology|audit|verify_chain|preview_deploy|open_terminal|export_topology|vendor_search|vendor_stats. open_terminal=ring<=1.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "ping",
                                "vendors",
                                "list_equipments",
                                "get_dashboard",
                                "topology",
                                "audit",
                                "verify_chain",
                                "preview_deploy",
                                "open_terminal",
                                "export_topology",
                                "vendor_search",
                                "vendor_stats",
                            ],
                        },
                        "shape_id": {"type": "string", "description": "preview_deploy/open_terminal"},
                        "command": {"type": "string", "description": "open_terminal"},
                        "wait_ms": {"type": "integer", "description": "open_terminal"},
                        "format": {
                            "type": "string",
                            "enum": ["d2", "drawthe", "mermaid"],
                            "description": "export_topology",
                        },
                        "query": {"type": "string", "description": "vendor_search"},
                        "vendor": {"type": "string", "description": "vendor_search"},
                        "limit": {"type": "integer", "description": "vendor_search"},
                        "db_path": {"type": "string", "description": "verify_chain"},
                        "scale_m_per_px": {"type": "number", "description": "topology"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "run",
                "description": "Git/Python/Shell/TrustedScript/Atlas/Snapshot/GitHub. trusted_script: run a git-tracked tools/ or app/ script privileged (path, script_args). shell: code=single OR commands=[...] parallel, sandbox=local|docker|ps_clm|windows. run_job: lance un .py DETACHE (script, online) -> job_id survivant restart ; job_status (job_id) pour poll/reprise ; job_kill (job_id) arrete l'arbre du job + libere la lane (le hub est l'ancetre du job).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "github",
                                "python",
                                "shell",
                                "trusted_script",
                                "atlas_build",
                                "save_situation",
                                "atlas_get",
                                "make_snapshot",
                                "setup_check",
                                "restart_claude",
                                "audit_log",
                                "worker_status",
                                "run_job",
                                "job_status",
                                "job_kill",
                            ],
                        },
                        "code": {"type": "string"},
                        "path": {
                            "type": "string",
                            "description": "Script path under tools/ or app/ (trusted_script action)",
                        },
                        "script_args": {
                            "type": "string",
                            "description": "CLI args for trusted_script (chaine style shell, parsee via shlex)",
                        },
                        "script": {
                            "type": "string",
                            "description": "run_job: chemin .py (sous C:/tmp ou racine Nokido) a lancer DETACHE",
                        },
                        "online": {
                            "type": "boolean",
                            "description": "run_job: sandbox-online (reseau sortant) si true, sinon offline",
                        },
                        "job_id": {
                            "type": "string",
                            "description": "job_status/job_kill: id retourne par run_job (poll etat running|done|killed, rc, log_tail)",
                        },
                        "force": {
                            "type": "boolean",
                            "description": "job_kill: accepte un python dont la cmdline est illisible (identification via la fiche du job seulement)",
                        },
                        "notify_agent": {
                            "type": "string",
                            "description": "run_job: agent a notifier sur l'inbox a la fin du job (optionnel)",
                        },
                        "lane": {
                            "type": "string",
                            "description": "run_job: lane d'admission (ex 'gpu8091'). Si fournie et deja tenue -> refus REACTIF (anti-stacking/anti-wedge): 1 job lourd par lane, liberee a la fin. Cf forge_lane_admission.",
                        },
                        "rss_cap_mb": {
                            "type": "integer",
                            "description": "run_job: plafond memoire de l ARBRE du job, en Mo (defaut env LAFORGE_JOB_RSS_CAP_MB, sinon 6000). Depasse -> job TUE, rc=137, motif dans le .err. Borne la famine RAM (incident 2026-08-02).",
                        },
                        "commands": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Parallel shell commands (shell action only)",
                        },
                        "sandbox": {
                            "type": "string",
                            "enum": ["local", "docker", "ps_clm", "windows", "wasm", "console", "gvisor"],
                            "description": "TYPE de bac (default: local). N'EST PAS le levier d'egress -- pour le reseau sortant, utiliser `network`. Une valeur HORS de cet enum est REFUSEE (fail-closed) : elle ne retombe jamais sur un contexte plus privilegie. console=session user (ring-0, default-deny). gvisor=tier2 isolation kernel pour untrusted (via forge_exec_tier)",
                        },
                        "network": {
                            "type": "boolean",
                            "description": "Reseau SORTANT (actions shell et python). absent/false -> compte LaForgeSbxOffline (loopback seul, egress bloque) ; true -> LaForgeSbxOnline (egress autorise). C'est le SEUL levier d'egress : sandbox=\"online\" n'a jamais existe. Pour un script git-tracke privilegie (LaForgeTrusted) : action=trusted_script.",
                        },
                        "container": {"type": "string", "description": "Docker container name (sandbox=docker)"},
                        "timeout": {"type": "integer", "description": "Per-command timeout seconds (default 30)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "md",
                "description": "Markdown read-only: action=route|lazy|index|extract|outline|read. query (route/lazy) ou path .md (extract/outline/read). Lecture/interaction docs markdown via forge_md_router. Edit=Phase2.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["route", "lazy", "index", "extract", "outline", "read"]},
                        "query": {"type": "string", "description": "Question (action=route|lazy)"},
                        "path": {"type": "string", "description": "Chemin .md relatif ROOT (action=extract|outline|read)"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "read",
                "description": (
                    "Lit un fichier du depot ou la fin d'un journal. action=file rend le fichier ENTIER : "
                    "aucun fenetrage, `lines` et `pattern` y sont ignores -- pour une fonction, "
                    "read_function_body ; pour la structure, get_file_skeleton ; pour une plage, Read "
                    "offset/limit. action=tail_logs rend les `lines` dernieres lignes (defaut 100) d'un "
                    "journal : `path` explicite, ou `pattern` qui resout le .log de l'organe et filtre les "
                    "lignes contenant ce texte. action=archived rend une sortie mise de cote par le garde "
                    "(`id` = ccr_...)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["file", "tail_logs", "archived"]},
                        "path": {"type": "string", "description": "Fichier ; pour tail_logs, le .log vise."},
                        "pattern": {"type": "string",
                                    "description": "tail_logs seulement : resout le journal et filtre les lignes."},
                        "lines": {"type": "integer",
                                  "description": "tail_logs seulement : dernieres lignes (defaut 100). Ignore par action=file."},
                        "id": {"type": "string", "description": "CCR blob id (action=archived) — récupère une sortie stashée par le guard"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "write",
                "description": "Ecrire/editer fichier (Thread-safe, RING_0)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
            {
                "name": "governed_edit",
                "description": "Edition GOUVERNEE in-process (ecrit app/ la ou le sandbox est ACL-bloque). path + (content complet OU blocs SEARCH/REPLACE Aider-style: <<<<<<< SEARCH / ======= / >>>>>>> REPLACE). Gouvernance: AST .py + secret scan + tree_lock claim (anti-clobber). Mode blocs = edition chirurgicale (LLM renvoie des blocs cibles, >80% economie tokens). RING_0.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Chemin relatif au repo"},
                        "content": {"type": "string", "description": "Contenu complet (mode write)"},
                        "blocks": {"type": "string", "description": "Blocs SEARCH/REPLACE (mode edition chirurgicale)"},
                        "allow_critical": {"type": "boolean", "description": "Derogation owner pour un CRITICAL_FILE. Reservee au ring <= 1, tracee. Sans elle l autorisation owner n a aucun canal : la variable d env est celle du process hub."},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "query",
                "description": "SQL RAG/semantic search (sql=...) OU introspecteur schema SQLite read-only (action=schema[, table, db])",
                "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}, "action": {"type": "string", "enum": ["schema"]}, "table": {"type": "string"}, "db": {"type": "string"}}},
            },
            {
                "name": "web_search",
                "description": "Recherche web SearXNG",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                    "required": ["query"],
                },
            },
            {
                "name": "absorb_rfc_knowledge",
                "description": "Recherche une norme IETF/RFC dans le miroir local Air-gapped (Zero-Latency), la découpe et l'ingère dans le RAG. À utiliser OBLIGATOIREMENT en cas de doute sur une spécification protocolaire ou réseau.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "concept_query": {
                            "type": "string",
                            "description": "Le concept technique exact (ex: 'OAuth 2.0 Threat Model', 'IPv4 MTU')."
                        }
                    },
                    "required": ["concept_query"]
                }
            },
            {
                "name": "query_documentation",
                "description": "Interroge la documentation officielle hors-ligne (Python_3, Docker, ONNX) pour obtenir la syntaxe exacte d'une fonction ou API. ZERO-LATENCY.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "docset_name": {
                            "type": "string",
                            "description": "La technologie ciblée (ex: 'Python_3', 'Docker', 'ONNX')."
                        },
                        "search_query": {
                            "type": "string",
                            "description": "Le nom exact de la fonction, classe ou commande (ex: 'subprocess.run', 'docker run')."
                        }
                    },
                    "required": ["docset_name", "search_query"]
                }
            },
            {
                "name": "search_local_file",
                "description": "Exécute une recherche Regex (FTS) ultra-rapide dans un fichier local lourd (logs, textes). Évite de lire le fichier entier.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Chemin du fichier (ex: 'logs/mcp.log')"},
                        "pattern": {"type": "string", "description": "Regex de recherche (ex: 'ERROR.*OAuth')"},
                        "context_lines": {"type": "integer", "description": "Nombre de lignes autour du match", "default": 2}
                    },
                    "required": ["path", "pattern"]
                }
            },
            {
                "name": "query_local_json",
                "description": "Interroge un fichier JSON ou JSONL local et ne renvoie que les données filtrées. Idéal pour health.json ou reflexion.jsonl.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Chemin du fichier JSON/JSONL"},
                        "key_filter": {"type": "string", "description": "Clé ou chemin simple à extraire (ex: 'system.cpu')"},
                        "last_n": {"type": "integer", "description": "Pour les JSONL, ne lire que les N dernières lignes", "default": 10}
                    },
                    "required": ["path", "key_filter"]
                }
            },
            {
                "name": "delegate_to_local_scout",
                "description": "Envoie un fichier lourd à un petit modèle local (SLM) pour obtenir une synthèse ou une réponse précise. ZÉRO TOKENS CLOUD.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Fichier à analyser"},
                        "prompt": {"type": "string", "description": "Question ou consigne de synthèse pour le Scout local"}
                    },
                    "required": ["path", "prompt"]
                }
            },
            {
                "name": "research_agent",
                "description": "Agent recherche zero-token: SearXNG+Groq->RAG",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "objective": {"type": "string"},
                        "max_rounds": {"type": "integer"},
                        "max_urls": {"type": "integer"},
                        "domain": {"type": "string"},
                        "provider": {"type": "string"},
                    },
                    "required": ["objective"],
                },
            },
            {
                "name": "oracle_python_repl",
                "description": (
                    "Oracle d'EXÉCUTION déterministe (sandbox OFFLINE non-admin, ZÉRO réseau, "
                    "timeout court). UTILISE-LE quand tu DOUTES du comportement exact d'une "
                    "fonction / regex / librairie / format de retour — N'HALLUCINE PAS : écris un "
                    "micro-script et teste ton hypothèse ICI d'abord, puis utilise le résultat avéré "
                    "pour construire la suite. Renvoie la VÉRITÉ (stdout) ou l'ÉCHEC (stderr) à corriger."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string",
                                 "description": "Snippet Python AUTONOME (imports + print()) testant ton hypothèse."},
                        "timeout": {"type": "integer", "description": "secondes (défaut 10, max 60)"},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "forge_trigger_audit",
                "description": (
                    "Ultra-Review LOCALE (0 API) : essaim de reviewers READ-ONLY sous 4 prismes "
                    "(Security/Correctness/Architecture/Style). Findings ancrés sur symboles AST "
                    "(le reducer déterministe jette les symboles inexistants = anti-hallucination). "
                    "target_files=[...], lenses=[...] (défaut: les 4). Rend un rapport Markdown."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target_files": {"type": "array", "items": {"type": "string"},
                                         "description": "fichiers à auditer"},
                        "lenses": {"type": "array",
                                   "items": {"type": "string",
                                             "enum": ["security", "correctness", "architecture", "style"]}},
                        "root": {"type": "string", "description": "racine projet (défaut: repo)"},
                    },
                    "required": ["target_files"],
                },
            },
            {
                "name": "forge_spawn_swarm",
                "description": (
                    "Essaim de sous-agents LOCAUX (Map-Reduce) pour refacto/tests massifs, 0 API. "
                    "tasks=[{task_id, targets, prompt, deps, op}]. Valide le DAG (déterministe : "
                    "collision/FS/cycle/bipartite) puis exécute en parallèle borné (slots), overlay "
                    "atomique (commit all-or-nothing), self-heal. Visible live sur /forge/swarm."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tasks": {
                            "type": "array",
                            "description": "Sous-tâches du DAG (indépendantes ou liées par deps)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task_id": {"type": "string"},
                                    "targets": {"type": "array", "items": {"type": "string"},
                                                "description": "fichiers ÉDITABLES (alias context_files)"},
                                    "prompt": {"type": "string"},
                                    "deps": {"type": "array", "items": {"type": "string"}},
                                    "op": {"type": "string",
                                           "enum": ["edit_sr", "create", "delete", "rename", "noop"]},
                                },
                                "required": ["task_id", "prompt"],
                            },
                        },
                        "root": {"type": "string", "description": "racine projet (défaut: repo)"},
                        "dry_run": {"type": "boolean", "description": "valide+exécute sans écrire le disque"},
                    },
                    "required": ["tasks"],
                },
            },
            {
                "name": "route_dt",
                "description": "Routeur intelligent Decision Tree. Prédit le provider optimal.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Texte du prompt à router"},
                        "task_type": {"type": "string", "description": "Type de tâche (optionnel)"},
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "route_task",
                "description": "Route tache vers provider LLM gratuit (ollama/gemini/groq)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_type": {"type": "string"}, "payload": {"type": "object"}},
                    "required": ["task_type", "payload"],
                },
            },
            {
                "name": "docker_action",
                "description": "Actions Docker GOUVERNEES (broker souverain forge_docker_agent, exec contexte LaForgeTrusted). argv = liste sans le mot 'docker' (ex: [\"ps\",\"-a\"] / [\"start\",\"searxng-laforge\"] / [\"logs\",\"searxng-laforge\"]). DockerPolicy default-deny: read-only toujours, lifecycle sur conteneurs Nokido, run images-whitelist sans evasion hote.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "argv": {"type": "array", "items": {"type": "string"}},
                        "timeout": {"type": "integer"},
                    },
                    "required": ["argv"],
                },
            },
            {
                "name": "ask",
                "description": "RPC LLM: provider=claude|gemini|groq|ollama|gpt4o_github|gemini_cli|claude_agent_sdk|claude_cli|...",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "message": {"type": "string"},
                        "thread_id": {"type": "string"},
                        "max_tokens": {"type": "integer"},
                        "rag_context": {"type": "boolean"},
                    },
                    "required": ["provider", "message"],
                },
            },
            {
                "name": "hub",
                "description": (
                    "Etat hub: action=get_mode|set_mode|poll|notify|list_providers|search_recent|whoami|"
                    "quota_model|quota_report|emit_telemetry. notify: to=claude|gemini|cline|daemon (explicite) "
                    "+ message. whoami : identite et ring de l'appelant, taches non reclamees par agent. "
                    "quota_report : declare le % utilise (flash, flash_lite, pro, preview_pro). quota_model : "
                    "choisit un modele selon quality=high|medium|low|ultra (apply pour l'appliquer). "
                    "emit_telemetry : lire le handler avant usage. demander_ordre : ordre=<nom> "
                    "(tailscale-statut|funnel-ouvrir|funnel-fermer|pair-approuver|pair-repondre|restart), "
                    "question a l'owner par elicitation puis execution (hub) ou depot pour le tray ; "
                    "cible/texte/pointeur selon l'ordre."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "get_mode",
                                "set_mode",
                                "poll",
                                "notify",
                                "list_providers",
                                "search_recent",
                                "whoami",
                                "emit_telemetry",
                                "redemarrer_stack",
                                "ordre_bureau",
                                "demander_ordre",
                                "quota_model",
                                "quota_report",
                                "confirmer_owner",
                            ],
                        },
                        "mode": {"type": "string"},
                        "message": {"type": "string"},
                        "to": {
                            "type": "string",
                            "enum": ["claude", "gemini", "cline", "daemon", "hub"],
                            "description": "Destinataire explicite pour action=notify",
                        },
                        "topic": {"type": "string"},
                        "limit": {"type": "integer"},
                        "flash": {"type": "number", "description": "quota_report: % flash used"},
                        "flash_lite": {"type": "number", "description": "quota_report: % flash_lite used"},
                        "pro": {"type": "number", "description": "quota_report: % pro used"},
                        "preview_pro": {"type": "number", "description": "quota_report: % preview_pro used"},
                        "quality": {"type": "string", "description": "quota_model: high|medium|low|ultra"},
                        "apply": {"type": "boolean", "description": "quota_model: apply model selection"},
                        "ordre": {"type": "string", "description": "demander_ordre : nom de l'ordre"},
                        "cible": {"type": "string", "description": "demander_ordre : id du depot (pair-approuver) ou client du pair (pair-repondre)"},
                        "texte": {"type": "string", "description": "demander_ordre pair-repondre : compte rendu (1000 car. max)"},
                        "pointeur": {"type": "string", "description": "demander_ordre pair-repondre : pointer_ref M2M"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "task",
                "description": "Cycle tache: action=assign|claim|result|status",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["assign", "claim", "result", "status"]},
                        "task_id": {"type": "string"},
                        "job_id": {"type": "string"},
                        "description": {"type": "string"},
                        "agent": {"type": "string"},
                        "intent": {"type": "string"},
                        "priority": {"type": "integer"},
                        "result": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "event",
                "description": "EventBus: action=publish|history",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["publish", "history"]},
                        "topic": {"type": "string"},
                        "kind": {"type": "string"},
                        "data": {"type": "object"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "rag",
                "description": "RAG: action=index|search",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["index", "search"]},
                        "task_id": {"type": "string"},
                        "result": {"type": "string"},
                        "topic": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "auto_test",
                "description": "py_compile AST check fichier",
                "inputSchema": {
                    "type": "object",
                    "properties": {"filepath": {"type": "string"}},
                    "required": ["filepath"],
                },
            },
            {
                "name": "bundle",
                "description": "Execute a sequence of primitive MCP tool calls in a single round-trip. Useful to batch reads, queries, and writes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "calls": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
                                "required": ["tool"],
                            },
                            "description": "Liste des appels a executer",
                        }
                    },
                    "required": ["calls"],
                },
            },
            {
                "name": "manage_forge_lifecycle",
                "description": "Pilote le cycle de vie (START/STOP/RESTART) des organes Nokido via NSSM.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "organ_name": {"type": "string"},
                        "action": {"type": "string", "enum": ["START", "STOP", "RESTART", "STATUS"]},
                        "priority": {"type": "string", "enum": ["LOW", "NORMAL", "HIGH"]},
                    },
                    "required": ["organ_name", "action"],
                },
            },
            {
                "name": "plan",
                "description": "GOAP Planner: décompose un objectif complexe en étapes JSON-RPC.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "ring_max": {"type": "integer"},
                        "context": {"type": "object"},
                    },
                    "required": ["goal"],
                },
            },
            {
                "name": "trigger_autonomous_evolution",
                "description": "Decompose intention en silos et execute en background",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "intention": {"type": "string"},
                        "domains": {"type": "array", "items": {"type": "string"}},
                        "max_silos": {"type": "integer"},
                    },
                    "required": ["intention"],
                },
            },
            {
                "name": "biblio",
                "description": "Bibliography Worker: extract|search|list|promote|reject|pin",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["extract", "search", "list", "promote", "reject", "pin", "unpin", "get"],
                        },
                        "text": {"type": "string"},
                        "idea_id": {"type": "string"},
                        "entry_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "status_filter": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "crawl",
                "description": "Crawl URL (Crawl4AI/Markdown)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}, "timeout": {"type": "integer"}},
                    "required": ["url"],
                },
            },
            {
                "name": "secret",
                "description": "Phase 1.4 — Acces secret WCM/env securise (whitelist + audit). action=get_env_var|get_secret_from_wcm|list_keys",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_env_var", "get_secret_from_wcm", "list_keys"]},
                        "key": {"type": "string", "description": "Nom de la cle (whitelist obligatoire)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "github",
                "description": "GitHub API: info|files|read|commits|branches|prs|search sur un repo",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo ex: az0/linkgopher"},
                        "sub": {
                            "type": "string",
                            "enum": ["info", "files", "read", "commits", "branches", "prs", "search"],
                        },
                        "path": {"type": "string", "description": "Chemin fichier ou dossier"},
                        "query": {"type": "string", "description": "Pour search"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "memory",
                "description": "Memoire Nokido: context|rules|adr|search|tasks|providers|status",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "context",
                                "rules",
                                "adr",
                                "instructions",
                                "providers",
                                "tasks",
                                "search",
                                "status",
                            ],
                        },
                        "query": {"type": "string"},
                        "tag": {"type": "string"},
                        "status_filter": {"type": "string"},
                        "limit": {"type": "integer"},
                        "domain": {"type": "string"},
                        "agent_id": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "skill",
                "description": "Skills centralisés Nokido (DB+fichier): action=list|load|search|ingest. Claude+Gemini+Cline+Docker.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "load", "search", "ingest"]},
                        "name": {"type": "string", "description": "Nom du skill ex: forge-anatomy"},
                        "query": {"type": "string", "description": "Pour action=search"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "cross_platform_fs",
                "description": "Move/Copy files between Windows and Docker/WSL safely.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["copy_to_docker", "copy_from_docker", "copy_to_wsl"]},
                        "src": {"type": "string", "description": "Source path (host path or container:path)"},
                        "dest": {"type": "string", "description": "Destination path (host path or container:path)"},
                        "distro": {"type": "string", "description": "WSL distro name (default Debian)"},
                    },
                    "required": ["action", "src", "dest"],
                },
            },
            {
                "name": "auto_ingest",
                "description": "Surveille et ingère les fichiers du hot-folder (data/rag_files/).",
                "inputSchema": {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": ["scan", "status", "start", "stop"]}},
                    "required": ["action"],
                },
            },
            {
                "name": "react_orchestrate",
                "description": "Boucle ReAct autonome (Ollama qwen3:8b). Supporte le function calling natif.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Tâche à accomplir"},
                        "max_iter": {"type": "integer", "description": "Max itérations (défaut 10)"},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "orchestrate",
                "description": "Boucle agentique locale: Qwen2.5-Coder:7B (llama-server :8091) orchestre les outils MCP en autonomie. Loop tool_calls jusqu a finish_reason=stop.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Tâche à accomplir"},
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Noms des outils autorisés (vide = tous les outils du ring)",
                        },
                        "max_iter": {"type": "integer", "description": "Max itérations (défaut 10)"},
                        "model": {"type": "string", "description": "Modèle llama-server (défaut laforge-coder)"},
                        "temperature": {"type": "number", "description": "Température (défaut 0.2)"},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "loop_orchestrate",
                "description": "[T_TOKEN_LOOP] Boucle autonome via GOAP + autonomous_loop_state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Pattern à exécuter (ex: health_check, git_hygiene)",
                        },
                        "max_steps": {"type": "integer", "description": "Nombre max d'étapes"},
                    },
                },
            },
            {
                "name": "read_function_body",
                "description": "Outil chirurgical : extrait le code source exact et les numéros de ligne d'une fonction ou classe dans un fichier. À utiliser après avoir analysé le squelette via read.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Chemin absolu ou relatif au fichier cible (ex: 'django/core/auth.py')",
                        },
                        "function_name": {
                            "type": "string",
                            "description": "Nom exact de la fonction ou classe à extraire (ex: 'validate_token')",
                        },
                    },
                    "required": ["file_path", "function_name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_file_skeleton",
                "description": "Squelette AST d'un fichier Python : imports + signatures de classes/fonctions, corps remplacés par '...'. Pagination sémantique — lire l'architecture d'un fichier SANS charger tout le code (anti lost-in-the-middle). Enchaîner avec read_function_body pour zoomer sur une fonction.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Chemin du fichier .py (absolu ou relatif au repo)",
                        },
                    },
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_function_dependencies",
                "description": "Call-graph fonction-level JIT : callees (fonctions appelées DANS la cible) + callers (fonctions qui l'appellent, grep ripgrep → parse AST ciblé). Mesure l'impact AVANT de modifier une fonction. file_path requis pour calculer les callees.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "Nom exact de la fonction cible",
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Fichier de la fonction (pour les callees). Optionnel.",
                        },
                    },
                    "required": ["function_name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "introspect",
                "description": (
                    "Point d'entree d'introspection (21 organes). Pour une question en langage "
                    "naturel, rend les symboles qui existent vraiment, ou ils sont definis, si "
                    "l'attribution de leurs appelants est sure (RESOLU / AMBIGU / ILLISIBLE), et si "
                    "Nokido a deja enquete sur ce symptome ; declare ce qu'il n'a pas consulte. "
                    "Borne a 5 symboles et au budget demande. A utiliser avant un grep, une lecture "
                    "ou une ecriture sur un domaine pas encore connu : c'est le moyen le moins cher "
                    "de ne pas reinventer un module existant."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "La question, en langage naturel.",
                        },
                        "budget_tokens": {
                            "type": "integer",
                            "description": "Plafond de la reponse (defaut 2000).",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "blackboard_read_zone",
                "description": "Lit UNE zone du tableau noir SQLite WAL du swarm (mémoire de travail partagée). Lecture condensée par zone pour éviter le lost-in-the-middle. Zones: mission, architecture_rules, discovered_facts, active_bugs, scratch, tree_locks (verrous d'edition entre agents : cle = agent, fait = fichiers reclames ; lue par governed_edit et le gate git).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone_name": {
                            "type": "string",
                            "description": "Nom de la zone (ex: 'active_bugs', 'discovered_facts')",
                        },
                        "filter": {
                            "type": "object",
                            "description": "Optionnel: {category, min_trust, limit}",
                        },
                    },
                    "required": ["zone_name"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "blackboard_propose_fact",
                "description": "Propose un fait atomique dans une zone (fire-and-forget). Le hub est l'unique write-funnel (mono-writer sérialisé, zéro contention 'database is locked'). Clé déterministe = idempotent. ACL par ring: mission/architecture_rules ring<=1, discovered_facts/active_bugs ring<=2.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "zone_name": {"type": "string", "description": "Zone cible"},
                        "fact": {"type": "string", "description": "Contenu du fait (texte ou JSON)"},
                        "category": {"type": "string", "description": "Classification (ex: 'api', 'bug', 'rule')"},
                        "trust": {"type": "number", "description": "Confiance [0.0-1.0], défaut 0.5"},
                        "key": {"type": "string", "description": "Optionnel: clé explicite (sinon hash du fait)"},
                    },
                    "required": ["zone_name", "fact"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "forge_stats",
                "description": "Observabilité runtime : cache de plans GOAP (hit-rate), sentinelle lag event-loop (events/max_lag/log), ressources (ram/cpu/gpu). Lecture seule.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "graph_edge_score",
                "description": "Calcule le score [0.0-1.0] d'un edge dans le graphe de code (import/call/inherit/embed_sim).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Module source (chemin ou nom)"},
                        "dst": {"type": "string", "description": "Module destination"},
                        "edge_type": {
                            "type": "string",
                            "enum": ["import", "call", "inherit", "embed_sim"],
                            "description": "Type de relation",
                        },
                        "metadata": {"type": "object", "description": "Optionnel: sim (float), deprecated (bool)"},
                    },
                    "required": ["src", "dst"],
                },
            },
            {
                "name": "graph_cve_propagate",
                "description": "Propage une CVE dans le graphe de dépendances BFS depuis entry_module.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cve_id": {"type": "string", "description": "Identifiant CVE (ex: CVE-2025-1234)"},
                        "entry_module": {"type": "string", "description": "Module d'entrée (point d'injection)"},
                        "max_depth": {"type": "integer", "description": "Profondeur BFS max (défaut 3)"},
                    },
                    "required": ["cve_id", "entry_module"],
                },
            },
            {
                "name": "graph_ppr",
                "description": "Personalized PageRank — identifie les modules les plus reliés à un seed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "seed": {"type": "string", "description": "Module de départ (seed PPR)"},
                        "alpha": {"type": "number", "description": "Facteur de téléportation (défaut 0.85)"},
                        "depth": {"type": "integer", "description": "Profondeur de construction du graphe (défaut 3)"},
                    },
                    "required": ["seed"],
                },
            },
        ]

    # -- HANDLERS : File System & DB --

    async def handle_netcfg(self, args: dict, agent: str, ring: int) -> str:
        """Tool unifie netcfg — verb-dispatcher proxy vers netcfg-agent-mcp :8767.

        Remplace les 12 tools netcfg_* par un seul tool (action=...). Passe par
        le dispatch normal -> ring check + access_switches + event bus, ce que
        les anciens netcfg_* contournaient.
        """
        action = str(args.get("action", "")).strip()
        if action not in self._NETCFG_ACTIONS:
            return f"ERR: action netcfg invalide '{action}'. Valides: {', '.join(sorted(self._NETCFG_ACTIONS))}"
        # open_terminal = acces shell SSH -> ring<=1 (CLINE/BRIDGE), pas ring 3
        if action == "open_terminal" and ring > 1:
            return f"SECURITY: netcfg action=open_terminal reserve ring<=1 (agent ring {ring})"
        sub_args = {k: v for k, v in args.items() if k != "action"}
        return await self._handle_netcfg_proxy(f"netcfg_{action}", sub_args, agent, ring)

    async def _handle_netcfg_proxy(self, name: str, args: dict, agent: str, ring: int) -> str:
        """Proxy HTTP vers netcfg-agent-mcp sur le port 8767."""
        url = "http://127.0.0.1:8767/mcp"
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        try:
            headers = {"Content-Type": "application/json"}
            # NETCFG_MCP_TOKEN = bearer token direct :8767 (depuis ~/.netcfg-agent-mcp/token)
            # FORGE_TOKEN_NETCFG = token identité hub (différent — ne pas utiliser ici)
            token = os.environ.get("NETCFG_MCP_TOKEN", "")
            if not token:
                _tf = Path.home() / ".netcfg-agent-mcp" / "token"
                try:
                    token = _tf.read_text().strip()
                except Exception as e:
                    import logging as _lg

                    _lg.getLogger("Nokido.Registry").debug(
                        "[netcfg] jeton fichier illisible (%s) — repli sur Nokido.env",
                        type(e).__name__)
            if not token:
                _lf = Path(__file__).resolve().parent.parent / "Nokido.env"
                try:
                    for _l in _lf.read_text(errors="ignore").splitlines():
                        if _l.startswith("NETCFG_MCP_TOKEN="):
                            token = _l.split("=", 1)[1].strip()
                            break
                except Exception:
                    pass
            if token:
                headers["Authorization"] = f"Bearer {token}"

            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)

            # DEPORT — mesure 2026-09-21. `urlopen` est SYNCHRONE et cette
            # methode est `async def` : l'appel s'executait DANS la boucle
            # d'evenements, qu'il immobilisait jusqu'a 10 s. Le serveur entier
            # attendait, pas seulement l'appelant de `netcfg`.
            #
            # Portee plus faible que le cas `ui_generate` traite le meme jour :
            # la cible est netcfg (:8767), un AUTRE service. Il n'y a donc pas
            # de deadlock -- la boucle n'a pas besoin d'etre libre pour que la
            # reponse arrive -- seulement un gel. La distinction se mesure :
            # un appel a SOI-MEME ne peut pas aboutir depuis la boucle, un
            # appel a un tiers finit par revenir.
            #
            # Le cout demeure ; il cesse d'etre PARTAGE.
            def _appel_synchrone():
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())

            res_data = await asyncio.get_running_loop().run_in_executor(
                None, _appel_synchrone)
            if "result" in res_data and "content" in res_data["result"]:
                return res_data["result"]["content"][0].get("text", str(res_data["result"]))
            return str(res_data)
        except Exception as e:
            return f"ERR: netcfg-agent-mcp proxy error: {e}"

    async def _handle_trigger_audit(self, name: str, args: dict, agent: str, ring: int) -> str:
        """Verbe MCP ForgeAudit — Ultra-Review locale read-only. ring<=2."""
        if ring > 2:
            return "SECURITY: forge_trigger_audit réservé ring<=2"
        files = args.get("target_files") or []
        if not isinstance(files, list) or not files:
            return "ERR: forge_trigger_audit: 'target_files' (liste non vide) requis"

        import sys as _s
        from pathlib import Path as _P

        _app = str(_P(__file__).resolve().parent)
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_audit import run_forge_audit

        root = args.get("root") or str(getattr(self, "root", "."))

        def _emit(kind, data):  # events live -> bus topic=audit
            try:
                from nokido_agent.app.forge_swarm_bus import publish

                publish(kind, data, topic="audit")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                # Chemin CHAUD : deduplication par compteur porte par la fonction,
                # sinon le remede noierait le journal qu'il repare.
                _n = getattr(_emit, "_pertes", 0) + 1
                _emit._pertes = _n
                if _n == 1 or _n % 200 == 0:
                    _lg.getLogger("Nokido.Registry").warning(
                        "[bus] evenement d'AUDIT non publie (%s: %s) — %d perdu(s) | "
                        "consequence: la piste d'audit a des trous et ne peut pas "
                        "servir de preuve", type(e).__name__, str(e)[:80], _n)

        try:
            rep = await run_forge_audit(files, root, lenses=args.get("lenses"), emit=_emit)
        except Exception as e:  # noqa: BLE001
            return f"ERR: forge_trigger_audit: {type(e).__name__}: {e}"
        return rep.get("report_md", "") + (
            f"\n<!-- kept={len(rep.get('kept', []))} dropped={rep.get('dropped', 0)} -->"
        )

    async def _handle_spawn_swarm(self, name: str, args: dict, agent: str, ring: int) -> str:
        """Verbe MCP ForgeSwarm — branche run_forge_swarm (validator+workers+overlay) +
        pool inférence local + bus events live. ring<=2 (édition de code)."""
        if ring > 2:
            return "SECURITY: forge_spawn_swarm réservé ring<=2 (édition de code)"
        tasks = args.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return "ERR: forge_spawn_swarm: 'tasks' (liste non vide) requis"

        import json as _j
        import sys as _s
        from pathlib import Path as _P

        _app = str(_P(__file__).resolve().parent)
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_local_inference_pool import LocalInferencePool
        from nokido_agent.app.forge_swarm_orchestrator import run_forge_swarm

        root = args.get("root") or str(getattr(self, "root", "."))

        def _emit(kind, data):  # events live -> bus topic=swarm -> /forge/swarm
            try:
                from nokido_agent.app.forge_swarm_bus import publish

                publish(kind, data, topic="swarm")
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _n = getattr(_emit, "_pertes", 0) + 1
                _emit._pertes = _n
                if _n == 1 or _n % 200 == 0:
                    _lg.getLogger("Nokido.Registry").warning(
                        "[bus] evenement SWARM non publie (%s: %s) — %d perdu(s) | "
                        "consequence: /forge/swarm affiche un essaim plus calme qu'il "
                        "ne l'est", type(e).__name__, str(e)[:80], _n)

        pool = LocalInferencePool()  # llama-server slots préféré, ollama fallback
        try:
            res = await run_forge_swarm(
                tasks, root, pool.make_infer_fn(),
                import_graph=None,  # règle 4 (repo_map) : câblage ultérieur
                emit=_emit, dry_run=bool(args.get("dry_run", False)),
            )
        except Exception as e:  # noqa: BLE001
            return f"ERR: forge_spawn_swarm: {type(e).__name__}: {e}"
        return _j.dumps(res, ensure_ascii=False, default=str)[:4000]




    async def _handle_docker_proxy(self, name: str, args: dict, agent: str, ring: int) -> str:
        """
        Proxy stdio vers `docker mcp gateway run` (lazy-spawn singleton).
        Le prefix `docker_` est strippe avant l appel natif au gateway.
        """
        try:
            from nokido_agent.app.forge_docker_supervisor import get_supervisor, DockerSupervisorError
        except Exception as e:
            return f"ERR: docker supervisor import: {e}"

        sup = get_supervisor()
        native_name = name[len("docker_") :] if name.startswith("docker_") else name
        try:
            return await sup.call_tool(native_name, args or {}, timeout=15)
        except DockerSupervisorError as e:
            return f"ERR: docker gateway: {e}"
        except Exception as e:
            return f"ERR: docker proxy unexpected: {type(e).__name__}: {e}"

    async def list_docker_tools(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        Liste dynamique des tools Docker MCP (namespace docker_*).
        Cache au niveau supervisor. Tolerant : retourne [] si gateway down.
        """
        try:
            from nokido_agent.app.forge_docker_supervisor import get_supervisor
        except Exception:
            return []
        sup = get_supervisor()
        try:
            tools = await sup.list_tools(force=force)
        except Exception as e:
            logger.debug(f"list_docker_tools: gateway unavailable: {e}")
            return []
        out: List[Dict[str, Any]] = []
        for t in tools:
            try:
                native = t.get("name", "")
                if not native:
                    continue
                out.append(
                    {
                        "name": f"docker_{native}",
                        "description": t.get("description", f"Docker MCP gateway tool: {native}"),
                        "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}}),
                    }
                )
            except Exception:
                continue
        return out

    async def handle_agy_run(self, args: dict, agent: str, ring: int) -> dict:
        """Handle executing an agy command safely."""
        command = args.get("command", "")
        timeout = args.get("timeout")

        # 1. Enforce command length <= 500
        if len(command) > 500:
            return {"success": False, "error": "Command too long (invalid)"}

        # 2. Command injection check using regex [;&|`$<>\(\)\*!\[\]\{\}\n\r\^\%]
        import re
        injection_pattern = re.compile(r"[;&|`$<>\(\)\*!\[\]\{\}\n\r\^\%]")
        if injection_pattern.search(command):
            return {"success": False, "error": "Command rejected: forbidden characters (injection/invalid)"}

        # 3. Subprocess command parsing via shlex.split
        import shlex
        import subprocess
        import shutil

        try:
            cmd_args = shlex.split(command)
        except Exception as e:
            return {"success": False, "error": f"Failed to parse command: {str(e)} (invalid)"}

        # Resolve the absolute path of the agy CLI binary
        # `which` cherche dans le PATH du PROCESS HUB (compte de service) : le
        # PATH utilisateur de l'owner n'y est pas, donc `agy` est introuvable et
        # l'appel meurt en WinError 2 — ce qui se lit « AGY n'est pas installe ».
        # Mesure 2026-08-28 : le binaire EXISTE et est lisible. Ordre explicite :
        # override, PATH, emplacements connus, puis le nom nu en dernier recours.
        _agy_connus = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe"),
            r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe",
        ]
        agy_bin = (
            os.environ.get("LAFORGE_AGY_BIN")
            or shutil.which("agy")
            or next((p for p in _agy_connus if p and os.path.exists(p)), None)
            or "agy"
        )

        # Strip redundant agy token
        if cmd_args and cmd_args[0] == "agy":
            cmd_args = cmd_args[1:]

        full_cmd = [agy_bin] + cmd_args

        # Default timeout of 60 seconds
        if timeout is None:
            timeout = 60

        # 4. Execution with shell=False
        try:
            kwargs = {
                "capture_output": True,
                "text": True,
                "shell": False,
                "timeout": timeout,
            }

            proc = subprocess.run(full_cmd, **kwargs)

            if proc.returncode == 0:
                return {
                    "success": True,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr
                }
            else:
                return {
                    "success": False,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr
                }

        except subprocess.TimeoutExpired as e:
            return {
                "success": False,
                "exit_code": -1,
                "stderr": f"Command timed out: {str(e)}",
                "error": f"Timeout expired: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stderr": str(e),
                "error": f"Execution failed: {str(e)}"
            }

    async def handle_agy_config(self, args: dict, agent: str, ring: int) -> dict:
        """Handle reading or writing configuration in settings.json."""
        action = args.get("action")
        key = args.get("key")
        value = args.get("value")

        if not action or not key:
            return {"success": False, "error": "Missing 'action' or 'key' arguments."}

        from pathlib import Path
        import os
        import json
        import tempfile

        settings_dir = Path.home() / ".gemini" / "antigravity-cli"
        settings_file = settings_dir / "settings.json"

        # Symbolic link check
        if settings_file.exists():
            if settings_file.is_symlink() or any(p.is_symlink() for p in settings_file.parents):
                return {"success": False, "error": "Symbolic link detected (not allowed)"}

        if action == "read":
            if not settings_file.exists():
                return {"success": True, "key": key, "value": None}

            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    # TOCTOU: check size on open file descriptor
                    size = os.fstat(f.fileno()).st_size
                    if size > 1024 * 1024:
                        return {"success": False, "error": "settings.json size exceeds 1MB limit"}
                    config_data = json.load(f)
            except Exception as e:
                return {"success": False, "error": f"Failed to parse settings.json: {str(e)}"}

            if not isinstance(config_data, dict):
                return {"success": False, "error": "settings.json content is not a dictionary"}

            val = config_data.get(key)
            return {"success": True, "key": key, "value": val}

        elif action == "write":
            SETTINGS_SCHEMA = {
                "allowNonWorkspaceAccess": bool,
                "altScreenMode": str,
                "artifactReviewPolicy": str,
                "colorScheme": str,
                "editor": str,
                "enableTelemetry": bool,
                "enableTerminalSandbox": bool,
                "gcp": dict,
                "historySize": int,
                "model": str,
                "notifications": bool,
                "permissions": dict,
                "runningLightSpeed": str,
                "showFeedbackSurvey": bool,
                "showTips": bool,
                "statusLine": dict,
                "title": dict,
                "toolPermission": str,
                "trustedWorkspaces": list,
                "useG1Credits": bool,
                "verbosity": str,
            }

            expected_type = SETTINGS_SCHEMA.get(key)
            if expected_type is None:
                return {"success": False, "error": f"Unknown key '{key}'"}

            # Type checking
            if expected_type is bool:
                if not isinstance(value, bool):
                    return {"success": False, "error": f"Invalid type for key '{key}'. Expected bool."}
            elif isinstance(value, bool):
                return {"success": False, "error": f"Invalid type for key '{key}'. Expected {expected_type.__name__}."}
            elif not isinstance(value, expected_type):
                return {"success": False, "error": f"Invalid type for key '{key}'. Expected {expected_type.__name__}."}

            if key == "trustedWorkspaces":
                if not all(isinstance(x, str) for x in value):
                    return {"success": False, "error": "trustedWorkspaces must be a list of strings."}

            # Read existing config
            config_data = {}
            if settings_file.exists():
                try:
                    with open(settings_file, "r", encoding="utf-8") as f:
                        # TOCTOU: check size on open file descriptor
                        size = os.fstat(f.fileno()).st_size
                        if size > 1024 * 1024:
                            return {"success": False, "error": "settings.json size exceeds 1MB limit"}
                        config_data = json.load(f)
                except Exception as e:
                    return {"success": False, "error": f"Failed to parse settings.json: {str(e)}"}

                if not isinstance(config_data, dict):
                    return {"success": False, "error": "settings.json content is not a dictionary"}

            config_data[key] = value

            # Size check of new config
            try:
                json_str = json.dumps(config_data)
                if len(json_str.encode('utf-8')) > 1024 * 1024:
                    return {"success": False, "error": "New config size would exceed 1MB"}
            except Exception as e:
                return {"success": False, "error": f"Failed to serialize config: {str(e)}"}

            # Atomic write using temp file
            try:
                settings_dir.mkdir(parents=True, exist_ok=True)
                temp_fd, temp_path = tempfile.mkstemp(dir=str(settings_dir), prefix="settings_tmp_")
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                os.replace(temp_path, str(settings_file))
            except Exception as e:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                return {"success": False, "error": f"Failed to write settings.json: {str(e)}"}

            return {"success": True, "key": key, "value": value}

        else:
            return {"success": False, "error": f"Invalid action '{action}'"}

    async def handle_agy_add_dir(self, args: dict, agent: str, ring: int) -> dict:
        """Handle adding a directory path to trustedWorkspaces."""
        path = args.get("path", "").strip()

        # 1. Enforce path is non-empty and absolute
        if not path:
            return {"success": False, "error": "Path cannot be empty."}

        from pathlib import Path
        import os
        import json
        import tempfile

        # Enforce input path is absolute using Path(path).is_absolute()
        if not Path(path).is_absolute():
            return {"success": False, "error": f"Path '{path}' is not absolute."}

        # Reject path if it contains traversal tokens `..`
        path_obj = Path(path)
        if ".." in path_obj.parts or "../" in path or "..\\" in path:
            return {"success": False, "error": "Path contains directory traversal sequences."}

        settings_dir = Path.home() / ".gemini" / "antigravity-cli"
        settings_file = settings_dir / "settings.json"

        # Symbolic link check
        if settings_file.exists():
            if settings_file.is_symlink() or any(p.is_symlink() for p in settings_file.parents):
                return {"success": False, "error": "Symbolic link detected (not allowed)"}

        # Read existing config
        config_data = {}
        if settings_file.exists():
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    # TOCTOU: check size on open file descriptor
                    size = os.fstat(f.fileno()).st_size
                    if size > 1024 * 1024:
                        return {"success": False, "error": "settings.json size exceeds 1MB limit"}
                    config_data = json.load(f)
            except Exception as e:
                return {"success": False, "error": f"Failed to parse settings.json: {str(e)}"}

            if not isinstance(config_data, dict):
                return {"success": False, "error": "settings.json content is not a dictionary"}

        # Append path to trustedWorkspaces
        trusted = config_data.get("trustedWorkspaces")
        if not isinstance(trusted, list):
            trusted = []
        if path not in trusted:
            trusted.append(path)
        config_data["trustedWorkspaces"] = trusted

        # Size check of new config
        try:
            json_str = json.dumps(config_data)
            if len(json_str.encode('utf-8')) > 1024 * 1024:
                return {"success": False, "error": "New config size would exceed 1MB"}
        except Exception as e:
            return {"success": False, "error": f"Failed to serialize config: {str(e)}"}

        # Atomic write using temp file
        try:
            settings_dir.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(dir=str(settings_dir), prefix="settings_tmp_")
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                f.write(json_str)
            os.replace(temp_path, str(settings_file))
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return {"success": False, "error": f"Failed to write settings.json: {str(e)}"}

        return {"success": True, "path": path}

    async def handle_read(self, args: dict, agent: str, ring: int) -> str:
        """v3 : SecretGuard remplace l'ancien check honeytoken contournable."""
        # CCR retrieve : récupère un blob stashé par le guard de sortie (read sans path).
        if args.get("action") == "archived":
            import re as _re

            _mid = args.get("id", "")
            if not _re.fullmatch(r"ccr_[A-Za-z0-9]+", _mid or ""):  # anti path-traversal
                return "CCR: 'id' invalide (action=archived)."
            _p = self.root / "sandbox" / "ccr" / f"{_mid}.txt"
            if not _p.is_file():
                return f"CCR: aucun blob id={_mid} (expiré ou inexistant)."
            return _p.read_text(encoding="utf-8", errors="replace")

        path_str = args.get("path", "")
        path = self.root / path_str

        # v3 : SecretGuard bloque meme en RING 0
        # Verifier sur path_str (forme passee) ET sur path resolu
        assert_can_read(path_str, agent, ring)
        assert_can_read(str(path), agent, ring)

        if args.get("action") == "tail_logs":
            from pathlib import Path as _P

            _lines = int(args.get("lines", 100))
            _pattern = args.get("pattern", "")
            # `path` ABSENT -> self.root / "" == le DOSSIER racine : path.exists()
            # renvoie True et read_text() levait « PermissionError [Errno 13] ...
            # \LaForge ». Le reflexe FONDATEUR (« le LOG de l'organe AVANT toute
            # sonde ») etait donc casse et l'agent contournait par un shell (mesure
            # 2026-07-25). On RESOUT le log de l'organe depuis `pattern` : le plus
            # recemment ecrit parmi logs/ et logs/supervisor/ dont le nom matche.
            if (not path_str) or path.is_dir():
                _cands = []
                for _d in (self.root / "logs", self.root / "logs" / "supervisor"):
                    if not _d.is_dir():
                        continue
                    for _f in _d.glob("*.log"):
                        # Motif « docker_keeper » vs fichier « NokidoDockerKeeper.log » :
                        # on compare sans casse NI separateurs, sinon le match echoue
                        # toujours (mesure 2026-07-25, juste apres le 1er correctif).
                        _nf = _f.name.lower().replace("_", "").replace("-", "").replace(" ", "")
                        _np = _pattern.lower().replace("_", "").replace("-", "").replace(" ", "")
                        if not _pattern or _np in _nf:
                            try:
                                _cands.append((_f.stat().st_mtime, str(_f)))
                            except OSError:
                                continue
                if not _cands:
                    # « rien trouve » != « pas pu voir » : dire OU l'on a cherche.
                    return (f"tail_logs: aucun .log correspondant a pattern={_pattern!r} "
                            f"dans logs/ et logs/supervisor/ (racine {self.root})")
                path = _P(max(_cands)[1])
                assert_can_read(str(path), agent, ring)
            if not path.exists():
                return f"Log introuvable: {path}"
            # TAIL par la FIN (seek) au lieu de charger tout le fichier : un log de
            # 2,3 Mo saturait la sortie pour un simple tail (mesure du jour).
            _budget = min(max(1, _lines) * (4096 if _pattern else 512), 4 * 1024 * 1024)
            try:
                with open(path, "rb") as _fh:
                    _fh.seek(0, 2)
                    _size = _fh.tell()
                    _fh.seek(max(0, _size - _budget))
                    _raw = _fh.read()
            except OSError as _e:
                return f"tail_logs: illisible ({type(_e).__name__}: {_e}): {path}"
            lines = _raw.decode("utf-8", errors="replace").splitlines()
            if _size > _budget and lines:
                lines = lines[1:]   # 1re ligne tronquee au milieu par le seek
            if _pattern:
                lines = [l for l in lines if _pattern.lower() in l.lower()]
            try:
                _shown = _P(path).relative_to(self.root)
            except ValueError:
                _shown = path
            return (f"[tail_logs {_shown} — {len(lines)} lignes, tail {_budget // 1024} Ko]\n"
                    + "\n".join(lines[-_lines:]))
        return path.read_text(encoding="utf-8", errors="replace")

    async def handle_write(self, args: dict, agent: str, ring: int) -> str:
        """v3 : SecretGuard bloque l'ecriture sur fichiers proteges."""
        path_str = args.get("path", "")
        path = self.root / path_str
        content = args.get("content", "")

        # WorkspaceGuard — aucun write hors de l'arbre projet, meme ring 0.
        # path_str absolu hors ROOT -> self.root/path_str garde l'absolu -> rejet.
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return f"SECURITY: write hors projet refuse: {path_str}"

        # v3 : SecretGuard bloque meme en RING 0
        assert_can_write(path_str, agent, ring)
        assert_can_write(str(path), agent, ring)

        if path.suffix == ".py" and (path.name.startswith("forge_") or path.name == "Nokido.py"):
            try:
                compile(content, str(path), "exec")
            except Exception as e:
                return f"COMMIT GUARD FAIL: {e}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.state_mgr.add_notification(f"fichier ecrit: {path.name}", source=agent)
        # ── Qualité DB (avertissement Gemini inventaire) ─────────────────────
        _warnings = []
        if path.suffix == ".py":
            try:
                from nokido_agent.app.forge_mcp_security import check_db_quality as _cdbq

                _warnings = _cdbq(content, path_str, agent)
                for w in _warnings:
                    import logging as _wl

                    _wl.getLogger("Nokido.Registry").warning(w)
                    print(f"\033[33m[DB_QUALITY] {w}\033[0m", flush=True)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[db_quality] avertissements NON restitues (%s: %s) | consequence: "
                    "des defauts de qualite ont ete detectes puis perdus en chemin",
                    type(e).__name__, str(e)[:100])
        # ─────────────────────────────────────────────────────────────────────
        suffix = f" | WARN: {len(_warnings)} DB patterns" if _warnings else ""
        return f"SUCCESS: {path.name} mis a jour.{suffix}"

    async def handle_governed_edit(self, args: dict, agent: str, ring: int) -> str:
        """Edition GOUVERNEE in-process : content complet OU blocs SEARCH/REPLACE.

        Comble le gap : le sandbox est ACL-bloque sur app/ ; CE handler tourne DANS le process
        hub = peut ecrire app/. Gouvernance deleguee a forge_governed_edit.governed_write
        (AST .py + secret scan + tree_lock claim anti-clobber). Mode blocs = forge_search_replace
        (edition chirurgicale : le LLM renvoie des blocs cibles au lieu du fichier entier)."""
        # Un argument inconnu est une INTENTION NON EXECUTEE, jamais un detail.
        # Mesure 2026-08-20 : un appel a passe `mode="append"` -- parametre qui
        # n'existe pas ici. Il a ete jete en silence, `content` a ete traite
        # comme un fichier COMPLET, et `route_subtask` -- fonction de
        # production -- a disparu. Le retour annoncait pourtant
        # "relecture disque identique" : l'outil relit ce qu'il vient d'ecrire,
        # ce qui reste vrai quand il a ecrase autre chose.
        # Ce controle precede TOUT effet de bord (y compris sys.path) : un
        # refus ne doit rien avoir modifie.
        _CONNUS = {"path", "content", "blocks", "explanation", "allow_critical"}
        _inconnus = sorted(k for k in args if k not in _CONNUS and not k.startswith("_"))
        if _inconnus:
            return ("EDIT FAIL: argument(s) inconnu(s) %s -- refus. Modes reels : "
                    "'content' (fichier COMPLET, ecrase) ou 'blocks' "
                    "(SEARCH/REPLACE chirurgical). Il n'y a pas de mode append."
                    % ", ".join(_inconnus))

        import sys as _s

        _td = str(self.root / "tools")
        if _td not in _s.path:
            _s.path.insert(0, _td)
        path_str = args.get("path", "")
        path = self.root / path_str
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return f"SECURITY: edit hors projet refuse: {path_str}"

        # Separation of Powers: check if agent is trying to edit its own judge/scorer
        try:
            from nokido_agent.app.forge_separation import enforce_separation
            ok, reason = enforce_separation(agent, "governed_edit", path_str)
            if not ok:
                return f"SECURITY: Separation of powers violation: {reason}"
        except Exception as e:
            return f"SECURITY: Separation of powers check error: {e}"
        blocks_raw = args.get("blocks")
        if blocks_raw:
            from nokido_agent.tools.forge_search_replace import apply_to_text, parse_blocks

            cur = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            res = apply_to_text(cur, parse_blocks(blocks_raw))
            if not res["ok"]:
                return f"EDIT FAIL (blocs SEARCH/REPLACE): {res['failed']}"
            content = res["text"]
        else:
            content = args.get("content", "")
            if not content:
                return "EDIT FAIL: fournir 'content' (complet) ou 'blocks' (SEARCH/REPLACE)"
        from nokido_agent.tools.forge_governed_edit import governed_write

        # Derogation CRITICAL_FILE : parametre d outil, RESERVE au ring <= 1.
        # Mesure 2026-08-16 : l owner a autorise une ecriture critique et cette
        # autorisation n avait aucun canal — LAFORGE_ALLOW_CRITICAL_WRITE est lue
        # dans l environnement du process hub, qu aucun appel client ne modifie.
        # Le correctif d un incident a donc du etre applique hors gouvernance.
        # Un garde dont la seule derogation est inatteignable ne protege pas :
        # il deporte l ecriture la ou plus personne ne la verifie.
        _allow_crit = bool(args.get("allow_critical"))
        if _allow_crit and ring > 1:
            return f"SECURITY: allow_critical refuse pour ring {ring} (reserve au ring <= 1)"
        verdict = governed_write(str(path), content, agent=agent, allow_critical=_allow_crit)
        if not verdict.get("ok"):
            return f"GOVERNED EDIT BLOCKED ({verdict.get('blocked')}): {verdict.get('reason')}"
        self.state_mgr.add_notification(f"governed_edit: {path.name}", source=agent)
        import json as _j

        # GARDE ANTI-REINVENTION, en AVERTISSEMENT (2026-08-31). On MESURE avant
        # de refuser : un garde pose sans connaitre son taux de fausse alerte se
        # fait desarmer au premier cri a faux -- piege consigne sur CE site le
        # 2026-08-01. N'agit que sur une ecriture REUSSIE : avertir sur un refus
        # ajouterait du bruit a une erreur.
        try:
            from nokido_agent.app.forge_introspect import consultation_recente, noter_edition

            _c = consultation_recente(agent)
            noter_edition(agent, _c["vu"], str(path))
            if not _c["vu"]:
                verdict["avertissement_reflexe"] = (
                    "aucune consultation `introspect` %s avant cette ecriture. "
                    "Nokido a peut-etre deja une procedure pour ce probleme : "
                    "l'interroger AVANT d'ecrire evite de reinventer."
                    % ("recente (%s s)" % _c["age_s"] if _c["etat"] == "PERIMEE"
                       else "sur cette session"))
        except Exception as _e:  # noqa: BLE001 - la trace ne casse jamais l'edition
            verdict["avertissement_reflexe_indisponible"] = type(_e).__name__

        # INVARIANT HISTORIQUE. On SAIT que cette capacite marchait, et on sait
        # avec quel test le verifier. Ne pas le dire ici reviendrait a posseder
        # la preuve sans jamais s'en servir.
        try:
            from nokido_agent.tools.forge_success_oplog import capacites_touchees

            _cap = capacites_touchees([str(path)])
            if _cap:
                _tests = sorted({t for c in _cap for t in c["tests"]})
                _absents = sorted({t for c in _cap for t in c.get("tests_absents") or []})
                verdict["capacites_prouvees_touchees"] = _cap[:3]
                verdict["avertissement_invariant"] = (
                    "cette ecriture touche le perimetre de %d capacite(s) PROUVEE(s). "
                    "Ce n'est pas un changement ordinaire : rejouer %s avant de "
                    "committer." % (len(_cap), ", ".join(_tests) or "leurs tests"))
                if _absents:
                    # Cites par le commit qui a prouve la capacite, disparus depuis :
                    # les DIRE, sinon la liste ci-dessus semble complete.
                    verdict["avertissement_invariant"] += (
                        " Tests cites mais ABSENTS du depot (renommes ou retires) : %s."
                        % ", ".join(_absents))
        except Exception as _e:  # noqa: BLE001 - jamais bloquer une edition
            verdict["invariant_indisponible"] = type(_e).__name__

        return _j.dumps(verdict, ensure_ascii=False)

    async def handle_query(self, args: dict, agent: str, ring: int) -> str:
        """v3 : SecretGuard bloque les SELECT sur tables sensibles.

        action=schema : introspecteur SQLite read-only (proprioception/audit).
        - sans table -> liste {table: row_count} de la db.
        - avec table -> PRAGMA table_info + COUNT(*) + 3 lignes sample.
        - db (optionnel) : autre .db dans le repo (resolu sous root, mode=ro).
        """
        if (args.get("action") or "").strip().lower() == "schema":
            _tbl = (args.get("table") or "").strip()
            _dbarg = (args.get("db") or "").strip()
            db_path = self.db_path
            if _dbarg:
                cand = (self.root / _dbarg).resolve()
                if (not str(cand).startswith(str(self.root.resolve()))
                        or cand.suffix != ".db" or not cand.exists()):
                    return json.dumps({"error": f"db invalide/hors-root: {_dbarg}"}, ensure_ascii=False)
                db_path = cand
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
                # budget schema (porte non gardee du 2026-09-03) : `timeout=10` est
                # un delai d'attente de VERROU, pas une borne sur le travail du
                # moteur. Sans progress handler, un COUNT sur une table de 22 Go
                # gele l'event loop du hub — mesure : 19 760 ms, puis la chute.
                _budget_s = float(os.environ.get("LAFORGE_QUERY_BUDGET_S", "20"))
                _echeance = time.monotonic() + _budget_s
                conn.set_progress_handler(
                    lambda: 1 if time.monotonic() > _echeance else 0, 20000)
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
                if not _tbl:
                    tbls = {}
                    for _n in names:
                        # MAX(rowid) : instantane (index) la ou COUNT(*) BALAYE. La
                        # valeur change de sens — c'est une BORNE SUPERIEURE, les
                        # suppressions ne rendent pas leur rowid — donc la sortie le
                        # dit au lieu de laisser croire a un compte exact.
                        try:
                            _v = conn.execute(f'SELECT MAX(rowid) FROM "{_n}"').fetchone()[0]
                            tbls[_n] = int(_v) if _v is not None else 0
                        except Exception:
                            tbls[_n] = None   # illisible : PAS zero
                    conn.close()
                    return json.dumps({"db": str(db_path), "tables": tbls,
                                       "note": "valeurs = MAX(rowid), BORNE SUPERIEURE "
                                               "et non COUNT(*) : un balayage sur une "
                                               "grosse table gele le hub (2026-09-03). "
                                               "null = table non comptable ou illisible."},
                                      indent=2, ensure_ascii=False)
                if _tbl not in names:
                    conn.close()
                    return json.dumps({"error": f"table inconnue: {_tbl}", "tables": names}, ensure_ascii=False)
                cols = [{"cid": c[0], "name": c[1], "type": c[2], "notnull": c[3],
                         "default": c[4], "pk": c[5]}
                        for c in conn.execute(f'PRAGMA table_info("{_tbl}")').fetchall()]
                # idem : borne, pas compte — voir la note renvoyee au client.
                _mx = conn.execute(f'SELECT MAX(rowid) FROM "{_tbl}"').fetchone()[0]
                n_rows = int(_mx) if _mx is not None else 0
                colnames = [c["name"] for c in cols]
                sample = [dict(zip(colnames, r)) for r in
                          conn.execute(f'SELECT * FROM "{_tbl}" LIMIT 3').fetchall()]
                conn.close()
                return json.dumps({"db": str(db_path), "table": _tbl,
                                   "rows_max_rowid": n_rows,
                                   "note": "rows_max_rowid = BORNE SUPERIEURE "
                                           "(MAX(rowid)), pas un COUNT(*)",
                                   "columns": cols, "sample": sample},
                                  indent=2, ensure_ascii=False, default=str)
            except Exception as e:
                return f"Erreur schema: {e}"
        sql = args.get("sql", "")

        # v3 : SecretGuard
        violation = sanitize_sql(sql, agent, ring)
        if violation:
            return violation

        try:
            # Scission M2M : une requete qui NOMME agent_messages vise la base des
            # messages (interrupteur sandbox/m2m.switch). Sinon, apres la bascule,
            # les agents qui lisent leur boite par `query` (doctrine des daemons :
            # « SELECT * FROM agent_messages WHERE to_agent=... ») liraient la copie
            # figee restee dans la base du RAG. Une jointure avec une table du RAG
            # echoue alors en « no such table » : dit, jamais silencieux.
            import re as _re
            _db_q = str(self.db_path)
            if _re.search(r"\bagent_messages\b", sql, _re.I):
                from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
                _db_q = _m2m_path()
            # L'ECRITURE PAR CETTE ROUTE EST UNE CAPACITE ASSUMEE, pas un oubli :
            # la branche `else` plus bas fait `conn.commit()` et repond
            # « Mutation OK ». On ne la supprime donc pas — c'est `sanitize_sql`
            # qui a ete etendu aux verbes d'ecriture (audit 2026-09-18), parce
            # que le defaut PROUVE n'etait pas l'existence de l'ecriture mais son
            # INVERSION : `SELECT ... FROM system_rules` etait bloque quand
            # `UPDATE system_rules ...` passait, journal d'audit `event_log`
            # compris.
            #
            # Un `mode=ro` a ete essaye ici puis RETIRE : il fermait la capacite
            # au lieu de la gouverner, et rien ne mesurait qui en depend.
            conn = sqlite3.connect(_db_q, timeout=10)
            # GARDE DE COUT (mesure 2026-08-23) : une LECTURE cliente a fait tomber
            # le hub DEUX fois dans la meme heure — une sous-requete non bornee sur
            # rag_fts, puis un GROUP BY source sur rag_chunks (1,3 M lignes). Le port
            # mourait, emportant toutes les surfaces clientes et les jobs en vol.
            # `timeout=10` ci-dessus ne protege PAS de cela : c'est le delai d'attente
            # d'un VERROU, pas une borne sur le travail du moteur — confusion qui rend
            # la route lisible comme protegee alors qu'elle ne l'est pas. Le progress
            # handler, lui, est appele toutes les N instructions de la VM SQLite et
            # ABANDONNE la requete des que le budget est depasse, quel que soit le plan
            # choisi. Une afference trop forte doit declencher un retrait, pas un arret
            # cardiaque : la requete chere est REFUSEE, l'organe survit.
            _budget_s = float(os.environ.get("LAFORGE_QUERY_BUDGET_S", "20"))
            _echeance = time.monotonic() + _budget_s
            conn.set_progress_handler(
                lambda: 1 if time.monotonic() > _echeance else 0, 20000)
            try:
                cur = conn.execute(sql)
            except sqlite3.OperationalError as _e_budget:
                if "interrupt" not in str(_e_budget).lower():
                    raise
                conn.close()
                return (
                    "REQUETE REFUSEE : budget de %.0f s depasse — la requete balayait "
                    "la table au lieu d'utiliser un index, et ce balayage a deja fait "
                    "tomber le hub deux fois le 2026-08-23. Reformuler avec un filtre "
                    "indexe (id, cle exacte), un MATCH FTS qui borne l'ensemble "
                    "candidat, ou un LIMIT sur une table connue petite. Budget "
                    "ajustable via LAFORGE_QUERY_BUDGET_S." % _budget_s
                )
            if sql.strip().upper().startswith("SELECT"):
                # Cap lignes (frugalité) : fetchmany au lieu de fetchall — PLUS SÛR
                # qu'injecter LIMIT dans le SQL (ne casse ni subquery/UNION ni un
                # LIMIT déjà présent ni les agrégats). Le json.dumps n'est PAS
                # couvert par le guard global (qui laisse le JSON intact).
                _cap = int(os.environ.get("FORGE_QUERY_MAX_ROWS", "200"))
                rows = cur.fetchmany(_cap + 1)
                _over = len(rows) > _cap
                rows = rows[:_cap]
                res = json.dumps(rows, indent=2, ensure_ascii=False)
                if _over:
                    res += (
                        f"\n\n[… {_cap}+ lignes — tronqué (cap FORGE_QUERY_MAX_ROWS). "
                        "Ajoute LIMIT/WHERE ou agrège (COUNT/GROUP BY). …]"
                    )
            else:
                conn.commit()
                res = "Mutation OK"
            conn.close()
            return res
        except Exception as e:
            return f"Erreur SQL: {e}"

    # -- HANDLERS : Run (Sub-actions) --

    # -- Sandbox routing (docs/sandbox_user_plan.md) -----------------------
    # Types de bac RECONNUS. Toute autre valeur est REFUSEE avant l'aiguillage.
    #
    # POURQUOI (mesure 2026-09-01, P0 securite). La condition d'aiguillage testait
    # `sandbox not in ("local", "")` : une valeur INCONNUE etait donc prise pour un
    # "type explicite", contournait le confinement par compte, puis ne matchait
    # AUCUNE branche de `_exec_sandboxed` et tombait sur la branche finale, qui
    # execute `pwsh` IN-PROCESS DU HUB. Mesure : `sandbox="zzz_valeur_inexistante"`,
    # `"online"` et `"trusted"` rendaient tous NT AUTHORITY\SYSTEM (SeTcbPrivilege et
    # SeDebugPrivilege ACTIVES), alors que `sandbox="local"` rendait bien
    # LaForgeSbxOffline. Une entree INVALIDE obtenait donc PLUS de privileges qu'une
    # entree valide -- fail-OPEN sur une frontiere de privilege.
    #
    # `""` et `"local"` restent acceptes : c'est le comportement historique quand
    # SANDBOX_EXEC est desactive. On ferme le chemin que PERSONNE n'a choisi, pas un
    # chemin voulu.
    _SANDBOX_TYPES = ("", "local", "console", "ps_clm", "docker", "windows", "wasm", "gvisor")

    def _sandbox_valide(self, sandbox: str) -> str:
        """'' si le type est reconnu, sinon le message de REFUS.

        Un parametre de securite inconnu doit echouer FERME, jamais choisir le chemin
        le plus puissant. Le message nomme la forme correcte, sinon l'appelant reessaie
        la meme erreur : l'egress se demande par `network=true`, et un script
        git-tracke privilegie par `action=trusted_script`.
        """
        if str(sandbox or "") in self._SANDBOX_TYPES:
            return ""
        return (
            "SECURITY: sandbox=%r inconnu -- REFUSE (fail-closed). Types valides : %s. "
            "Une valeur inconnue ne retombe JAMAIS sur un contexte plus privilegie. "
            "Egress : network=true. Script git-tracke privilegie : action=trusted_script."
            % (str(sandbox)[:40], ", ".join(t for t in self._SANDBOX_TYPES if t))
        )

    def _sandbox_decision(self, args: dict, agent: str) -> tuple:
        """(use_sandbox, online, reason). Gated by env SANDBOX_EXEC; off by
        default so handle_run behaves exactly as before until enabled."""
        import os as _os

        if _os.environ.get("SANDBOX_EXEC", "").lower() not in ("1", "true", "on"):
            return False, False, "disabled"
        online = bool(args.get("network"))
        if args.get("privileged"):
            # Fix B: the caller must PRESENT the dev-mode token. That file
            # (sandbox/.dev_mode_token) is ACL'd SYSTEM+Administrators only,
            # so a sandboxed or non-admin process cannot read it and cannot
            # escalate. X-Agent-Name alone is NOT trusted -- it is spoofable
            # by anything holding the master token.
            try:
                import hmac as _hmac
                import sys as _s

                _s.path.insert(0, str(self.root / "tools"))
                from nokido_agent.tools.forge_dev_mode import TOKEN_FILE, is_armed

                armed, _rem = is_armed()
                presented = str(args.get("dev_token", ""))
                if armed and presented and TOKEN_FILE.exists():
                    actual = TOKEN_FILE.read_text(encoding="utf-8").strip()
                    if actual and _hmac.compare_digest(presented, actual):
                        return False, online, "privileged-granted"
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").debug(
                    "[privilege] octroi dev_token non evalue (%s) — repli fail-CLOSED "
                    "sur sandboxed", type(e).__name__)
        return True, online, "sandboxed"

    def _parite_sous_processus(self, args: dict, agent: str, ring: int) -> bool:
        """Un sous-processus lance depuis `action=python` est-il a PARITE avec `run shell` ?

        Oui SEULEMENT si le code tourne sous le compte bac a sable (`_sandbox_decision`),
        le meme que celui du shell (mesure 2026-09-27) : l'enfant n'y a aucun droit que
        `run shell` n'ait deja. Non pour gVisor (agent untrusted) ni pour le pool du hub
        (privileged-granted ou SANDBOX_EXEC coupe) : la, l'enfant heriterait d'un compte
        plus large. Decide ICI, cote hub -- jamais dans le code de l'agent."""
        if args.get("sandbox") == "gvisor" or (ring >= 4 and not args.get("sandbox")):
            return False
        return bool(self._sandbox_decision(args, agent)[0])

    def _run_sandboxed_python(self, code: str, online: bool, timeout: float) -> str:
        import sys as _s
        import uuid as _u

        _s.path.insert(0, str(self.root / "app"))
        from nokido_agent.app.forge_sandbox_exec import WORKSPACE, spawn_as_sandbox

        WORKSPACE.mkdir(parents=True, exist_ok=True)
        script = WORKSPACE / f"_run_{_u.uuid4().hex[:12]}.py"
        script.write_text(code, encoding="utf-8")
        try:
            r = spawn_as_sandbox(f'"{_s.executable}" "{script}"', online=online, timeout=max(5, int(timeout)))
            return (r.get("stdout") or "") + (r.get("stderr") or "")
        finally:
            try:
                script.unlink()
            except Exception:  # noqa: BLE001
                pass

    def _run_sandboxed_shell(self, cmd: str, online: bool, timeout: int,
                             agent: str | None = None) -> dict:
        """Shell sandboxe. `agent` = identite AUTHENTIFIEE par le hub, propagee a
        l'enfant : sans elle un `git commit` lance ici ne peut se reclamer que du
        compte sandbox, et la note de provenance sort `GIT:<user>|UNKNOWN`.

        Le canal est fixe a HUB_SHELL : c'est une propriete du CHEMIN, pas de
        l'agent -- le meme agent commit tantot par le pont stdio, tantot ici.

        PORTEE : ceci rend une provenance OPERATIONNELLE (le hub sait qui il a
        authentifie) sous forme de TRACE LOCALE. Ce n'est PAS une attestation
        infalsifiable : la commande executee peut reposer la variable elle-meme.
        Ne jamais presenter ces notes comme une preuve d'origine.
        """
        import sys as _s

        _s.path.insert(0, str(self.root / "app"))
        from nokido_agent.app.forge_sandbox_exec import spawn_as_sandbox

        _ag = (agent or "").strip().upper()
        _prov = {"LAFORGE_AGENT": _ag, "LAFORGE_AGENT_CHANNEL": "HUB_SHELL"} if _ag else None
        return spawn_as_sandbox(f"cmd.exe /c {cmd}", online=online,
                                timeout=max(5, int(timeout)), env_extra=_prov)

    async def _handle_oracle_python_repl(self, name: str, args: dict, agent: str, ring: int) -> str:
        """Oracle d'exécution déterministe : exécute un snippet en sandbox OFFLINE (non-admin,
        zéro réseau, timeout court) → renvoie la VÉRITÉ brute (stdout) ou l'ÉCHEC (stderr).
        Pont LLM↔réalité : l'agent TESTE son hypothèse au lieu d'halluciner. Réutilise
        spawn_as_sandbox (pas de docker brut) ; l'isolation vient du user non-admin + no-net + timeout."""
        if ring is not None and ring > 3:
            return f"SECURITY: oracle_python_repl exige ring<=3 (ring={ring})"
        code = (args.get("code") or "").strip()
        if not code:
            return "ERR: oracle_python_repl: 'code' requis (snippet Python autonome avec print())."
        timeout = max(2, min(int(args.get("timeout", 10) or 10), 60))
        import sys as _s
        import uuid as _u

        _s.path.insert(0, str(self.root / "app"))
        from nokido_agent.app.forge_sandbox_exec import WORKSPACE, spawn_as_sandbox

        WORKSPACE.mkdir(parents=True, exist_ok=True)
        script = WORKSPACE / f"_oracle_{_u.uuid4().hex[:12]}.py"
        # Préambule : CWD=ROOT + sys.path += app -> l'oracle peut importer les forge_* et
        # résoudre les chemins relatifs (RAG/*, logs/*, sandbox/*). Sinon ImportError
        # forge_metrics + 'db not found' (Gemini/tout agent bloqué). N'affecte PAS
        # l'isolation : le sandbox reste offline + non-admin + timeout.
        _root = str(self.root)
        _appdir = str(self.root / "app")
        _preamble = (
            "import sys as _S, os as _O\n"
            "try:\n    _O.chdir(r'" + _root + "')\nexcept Exception:\n    pass\n"
            "_appp = r'" + _appdir + "'\n"
            "if _appp not in _S.path:\n    _S.path.insert(0, _appp)\n"
        )
        script.write_text(_preamble + code, encoding="utf-8")
        try:
            # online=False : un ORACLE de vérité n'a JAMAIS de réseau (pas de fetch, pas d'exfil).
            r = spawn_as_sandbox(f'"{_s.executable}" "{script}"', online=False, timeout=timeout)
        finally:
            try:
                script.unlink()
            except Exception:  # noqa: BLE001
                pass
        try:
            from nokido_agent.app.forge_swarm_bus import publish

            publish(kind="ORACLE_INVOKED",
                    data={"agent": agent, "exit": r.get("exit_code"),
                          "timed_out": r.get("timed_out"), "out_len": len(r.get("stdout") or "")},
                    topic="oracle")
        except Exception:  # noqa: BLE001
            pass
        if r.get("timed_out"):
            return f"ÉCHEC DE L'ORACLE : timeout > {timeout}s (ton code boucle ou est trop lent — simplifie l'hypothèse)."
        out = (r.get("stdout") or "").strip()
        err = (r.get("stderr") or "").strip()
        if r.get("exit_code") == 0:
            tail = f"\n[stderr]\n{err[:500]}" if err else ""
            return f"VÉRITÉ DE L'ORACLE (stdout) :\n{out[:3500] or '(vide — ajoute des print())'}{tail}"
        return (f"ÉCHEC DE L'ORACLE (exit={r.get('exit_code')}) :\n{(err or out)[:3500]}\n"
                "Corrige ton code et re-soumets ton hypothèse.")

    async def _handle_trusted_script(self, args: dict, agent: str, ring: int) -> str:
        """Run a git-tracked, unmodified tools/ or app/ script under the
        dedicated LaForgeTrusted account (repo+DB write, subprocess OK, no
        audit hook). Trust gate = the file is committed AND clean vs HEAD,
        i.e. reviewed code only. Ad-hoc / agent code stays sandboxed via
        action=python. See docs/sandbox_user_plan.md."""
        import asyncio as _aio
        import os as _os
        import subprocess as _sp
        import sys as _s
        from pathlib import Path as _P

        if ring is not None and ring > 2:
            return f"ERR: trusted_script: reserve ring<=2 (ring={ring})"
        logger.info("[trusted_script] keys=%s script_args=%r", sorted(args.keys()), args.get("script_args"))

        rel = str(args.get("path", "")).strip()
        if not rel:
            return "ERR: trusted_script: 'path' requis (relatif au repo, sous tools/ ou app/)"

        root = _P(self.root).resolve()
        target = (root / rel).resolve()
        allowed = (root / "tools", root / "app")
        if not any(target == d or str(target).startswith(str(d) + _os.sep) for d in allowed):
            return f"ERR: trusted_script: chemin hors tools/ ou app/ : {rel}"
        if target.suffix != ".py" or not target.is_file():
            return f"ERR: trusted_script: script .py introuvable : {rel}"

        relg = str(target.relative_to(root)).replace("\\", "/")

        def _git(*cmd):
            # encoding + errors EXPLICITES. `text=True` seul décode avec l'encodage
            # préféré du process, et le hub tourne sous PYTHONUTF8=1 -> UTF-8 STRICT.
            # Or git écrit ses messages dans la locale du système (cp1252 en FR) : un
            # seul accent lève UnicodeDecodeError DANS LE THREAD LECTEUR de subprocess.
            # Le trusted_script réussit quand même (exit 0) — c'est ce qui rend le
            # défaut pernicieux : traceback parasite, et une sortie git pourrait être
            # PERDUE sans qu'on le voie. Mesuré 2026-07-29 : octet 0x82, position 13.
            return _sp.run(
                ["git", "-C", str(root), *cmd],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )

        if _git("ls-files", "--error-unmatch", relg).returncode != 0:
            return (
                f"ERR: trusted_script: '{relg}' non suivi par git -- commit d'abord (privilege = code revu uniquement)"
            )
        if _git("diff", "--quiet", "HEAD", "--", relg).returncode != 0:
            return (
                f"ERR: trusted_script: '{relg}' modifie vs HEAD -- commit "
                f"les changements (execute = exactement le code revu)"
            )

        _s.path.insert(0, str(root / "app"))
        from nokido_agent.app.forge_sandbox_exec import spawn_as_trusted, trusted_ready

        ok, why = trusted_ready()
        if not ok:
            return f"ERR: trusted_script: compte LaForgeTrusted indispo -- {why}"

        # script_args = chaine style shell (parsee shlex). Tolere aussi une
        # vraie liste, ou un array stringifie "[a, b]" (artefact de transport).
        raw = args.get("script_args")
        if raw is None:
            raw = args.get("args")
        extra: list = []
        if isinstance(raw, list):
            extra = [str(x) for x in raw]
        elif isinstance(raw, str) and raw.strip():
            import shlex as _shlex

            s = raw.strip()
            if s[0] == "[" and s[-1] == "]":
                inner = s[1:-1].strip()
                extra = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
            else:
                extra = _shlex.split(s)
        argstr = " ".join(f'"{a}"' for a in extra)
        cmd = f'"{_s.executable}" "{target}" {argstr}'.strip()
        timeout = max(5, min(int(args.get("timeout", 120)), 3600))

        loop = _aio.get_event_loop()
        try:
            r = await loop.run_in_executor(None, lambda: spawn_as_trusted(cmd, timeout=timeout))
        except Exception as exc:  # noqa: BLE001
            return f"ERR: trusted_script: {type(exc).__name__}: {exc}"
        logger.info(
            "[trusted_script] %s ran %s exit=%s timed_out=%s", agent, relg, r.get("exit_code"), r.get("timed_out")
        )
        return (
            f"[trusted_script {relg} exit={r.get('exit_code')} "
            f"timed_out={r.get('timed_out')} user={r.get('sandbox_user')}]\n"
            + (r.get("stdout") or "")
            + (r.get("stderr") or "")
        )

    async def handle_run(self, args: dict, agent: str, ring: int) -> str:
        """v3 : SecretGuard sur action 'python' pour empecher contournement."""
        from nokido_agent.app.forge_utils import safe_shell_run
        import sys

        act = args.get("action", "")
        # Journal d'intention UNIFIE (audit-trail SSoT) — chaque run = une intention tracee.
        try:
            from nokido_agent.app import forge_intention_journal as _ij
            _ij.record(agent=agent, intent_type=f"run:{act}",
                       target=str(args.get("script") or args.get("path") or args.get("code", "")[:60] or "")[:120],
                       payload={"ring": ring, "sandbox": args.get("sandbox")}, decision="executed")
        except Exception:
            pass
        if act == "trusted_script":
            return await self._handle_trusted_script(args, agent, ring)
        if act == "run_job":
            # Verbe MCP first-class du job détaché (avant : REST /admin/run_job
            # uniquement). Lance un .py détaché survivant déconnexion + restart,
            # rend un job_id immédiat -> le hub ne bloque JAMAIS sur une tâche
            # longue (pattern OS). Reprise = poll job_status (état sur disque).
            if ring > 2:
                return "ERR: run_job: reserve ring<=2 (lancement code detache)"
            from nokido_agent.app.forge_job_runner import launch_job

            # Admission control : 1 job lourd par lane (anti-stacking -> anti-wedge hub).
            # lane optionnel ; si fourni et deja tenu -> refus REACTIF (router ailleurs, pas empiler).
            _lane = args.get("lane")
            if not _lane:
                # LANE DEDUITE (2026-08-29). Sans lane, l'anti-stacking ne s'armait
                # PAS : cinq jobs lourds empiles le meme jour ont sature la RAM et
                # fait tomber le hub. Un garde optionnel n'est pas un garde.
                # On ne serialise pour autant RIEN de plus que necessaire : la lane
                # porte le NOM DU FICHIER lance, donc deux lancements du MEME travail
                # s'excluent, tandis que des fichiers DIFFERENTS restent paralleles
                # -- swarm et fan-out intacts. « Ne jamais serialiser par prudence ».
                _src = str(args.get("script") or args.get("path") or "").replace("\\", "/")
                _lane = "auto:%s" % (_src.rsplit("/", 1)[-1] or "job")
                if bool(args.get("online", False)):
                    # Meme fichier, AUTRE compte (egress) : pas le meme travail. Vecu le
                    # 2026-09-27 : une mesure lancee online puis offline etait refusee
                    # (« lane occupee ») alors que les deux jobs etaient distincts.
                    _lane += "@online"
            _lane_acq = None
            # CONTROLE D'EMBOLIE, avec lane OU SANS (2026-08-02) : sans lane ce chemin
            # ne verifiait RIEN, et avec lane il ne verifiait que l occupation. Un job
            # relance sur une machine a 96 % de RAM a gonfle jusqu a la famine memoire
            # (dwm.exe tue, bureau fige, redemarrage manuel de l owner). check_ressources
            # est FAIL-CLOSED (mesure impossible -> refus) et tente de LIBERER avant de
            # refuser ; il ne prend aucun bail, donc les jobs ne sont pas serialises.
            try:
                from nokido_agent.app.forge_lane_admission import check_ressources as _check_res

                _resv = _check_res(heavy=True)
                if not _resv.get("ok"):
                    return json.dumps({"ok": False, "admit": False, "lane": _lane or "",
                                       "reason": _resv.get("reason"),
                                       "reserve": _resv.get("reserve"),
                                       "freed_gb": _resv.get("freed_gb"),
                                       "alt_cloud": _resv.get("alt"),
                                       "react": "machine saturee : alleger, attendre, ou router cloud :free"},
                                      ensure_ascii=False)
            except ImportError:
                pass  # muet-ok: module du depot absent -> on ne bloque pas le hub pour autant
            if _lane:
                try:
                    from nokido_agent.app.forge_lane_admission import current as _lane_cur, acquire as _lane_acq, ALT_CLOUD as _ALTC

                    _busy = _lane_cur(_lane)
                    if _busy:
                        return json.dumps({"ok": False, "admit": False, "lane": _lane,
                                           "busy_by": _busy.get("holder"),
                                           "reason": f"lane '{_lane}' occupee (1 job lourd/lane)",
                                           "alt_cloud": _ALTC,
                                           "react": "ne pas empiler : router cloud :free / autre lane / attendre"},
                                          ensure_ascii=False)
                except ImportError:
                    _lane = None  # module absent -> pas d'admission, on laisse passer

            res = launch_job(
                args.get("script") or args.get("path") or "", bool(args.get("online", False)),
                _lane or "", args.get("rss_cap_mb"),
                # 2026-08-20 : `script_args` existait pour trusted_script mais run_job
                # le JETAIT en silence. Un `--once` perdu = daemon infini a la place
                # d'un drain one-shot, qu'il faut ensuite tuer a la main.
                args.get("script_args") or "",
            )
            if _lane and _lane_acq and res.get("ok"):
                try:
                    _lane_acq(_lane, res["job_id"])
                except Exception as e:
                    import logging as _lg

                    _lg.getLogger("Nokido.Registry").warning(
                        "[lane] bail NON pris sur %s (%s) | consequence: le job tourne "
                        "hors admission, un second job peut demarrer sur la meme lane",
                        _lane, type(e).__name__)
            notify = args.get("notify_agent")
            if res.get("ok") and (notify or _lane):
                # Watcher asyncio (MÊME event loop -> INBOX.push thread-safe) : poll le .rc,
                # libere la lane d'admission a la fin du job, notifie l'agent si demande.
                import asyncio as _aio

                async def _watch_job(jid: str, who: str, lane: str = ""):
                    # JOBS_DIR a bouge (C:/tmp/nokido_jobs -> sandbox/jobs,
                    # 2026-07-28) : ce poll du .rc pointait l'ANCIEN dossier ->
                    # lane jamais liberee avant le cap 2 h (garde branche sur
                    # un signal que rien n'emet).
                    from nokido_agent.app.forge_job_runner import JOBS_DIR as _jobs_dir
                    rcf = _jobs_dir / f"{jid}.rc"
                    for _ in range(2400):  # cap ~2h (2400 x 3s) = TTL lease
                        if rcf.exists():
                            break
                        await _aio.sleep(3)
                    if lane:  # libere la lane d'admission (job termine)
                        try:
                            from nokido_agent.app.forge_lane_admission import release as _lane_rel

                            _lane_rel(lane, jid)
                        except Exception as e:
                            import logging as _lg

                            _lg.getLogger("Nokido.Registry").warning(
                                "[lane] bail NON rendu sur %s (%s) | consequence: bail "
                                "ORPHELIN, toute reprise refusee jusqu'au TTL en "
                                "designant un detenteur mort", lane, type(e).__name__)
                    if who:
                        try:
                            from nokido_agent.app.forge_message_frame import INBOX as _IN
                            from nokido_agent.app.forge_message_frame import MessageFrame as _MF

                            _IN.push(
                                _MF(
                                    to_agent=who,
                                    from_agent="agt_laforge",
                                    action="status",
                                    intent="report_status",
                                    text=f"job {jid} termine",
                                    parameters={"job_id": jid},
                                )
                            )
                        except Exception:
                            pass

                _aio.ensure_future(_watch_job(res["job_id"], notify or "", _lane or ""))
            return json.dumps(res, ensure_ascii=False)
        if act == "job_status":
            jid = args.get("job_id", "")
            if not jid:
                return "ERR: job_status: 'job_id' requis"
            from nokido_agent.app.forge_job_runner import read_job

            return json.dumps(read_job(jid), ensure_ascii=False)
        if act == "job_kill":
            # Symetrique de run_job : le hub est l'ANCETRE du job, lui seul peut
            # l'arreter (AccessDenied mesure 4 formes cote clients). Offload
            # executor : terminate+wait peut tenir ~13 s, jamais dans l'event loop.
            jid = args.get("job_id", "")
            if not jid:
                return "ERR: job_kill: 'job_id' requis"
            if ring > 2:
                return "ERR: job_kill: reserve ring<=2 (arret code detache)"
            from nokido_agent.app.forge_job_runner import kill_job
            import asyncio as _aio_k

            res_k = await _aio_k.get_event_loop().run_in_executor(
                None, lambda: kill_job(jid, bool(args.get("force", False))))
            return json.dumps(res_k, ensure_ascii=False)
        if act == "python":
            if args.get("code_file"):
                import os as _os

                _f = args["code_file"]
                if not _os.path.exists(_f):
                    logger.warning(f"code_file disparu: {_f} -- retry lecture directe")
                    code = args.get("code", "")
                else:
                    code = open(_f, encoding="utf-8", errors="replace").read()
                try:
                    _os.unlink(_f)
                except:
                    pass
            else:
                code = args.get("code", "")

            # v3 : SecretGuard sur le code Python
            violation = sanitize_python_code(code, agent, ring)
            if violation:
                return violation

            # WorkspaceGuard — confine TOUT agent à une zone fs via audit hook
            # injecté en sous-processus. Superviseur -> arbre projet (ROOT) ;
            # agent zoné -> sous-dossiers AGENT_WRITE_PATHS. Ferme le trou :
            # `run` python = exec arbitraire = write/spawn partout sur le
            # disque, meme pour CLAUDE/BRIDGE ring 0. Header multiline -> force
            # _run_isolated (subprocess frais), pas de pollution du pool.
            try:
                from nokido_agent.app.forge_workspace_guard import run_guard_header_for

                _wg = run_guard_header_for(agent, ring, self.root,
                                           sous_processus=self._parite_sous_processus(args, agent, ring))
                if _wg:
                    code = _wg + "\n" + code
            except Exception as _wge:
                logger.warning(f"[run-guard] header non injecte: {_wge}")

            # Auto-route untrusted-ring (#5 part B) : code d'un agent UNTRUSTED
            # (ring >= 4, sans token) -> tier2 gVisor (isolation kernel), AVANT le
            # chemin user-restreint. Fail-closed si gVisor indispo. Skip si l'appelant
            # demande explicitement un autre sandbox.
            if args.get("sandbox") == "gvisor" or (ring >= 4 and not args.get("sandbox")):
                import asyncio as _aio_gv
                from nokido_agent.tools.forge_exec_tier import run_sandboxed as _rsb_py
                _t_gv = min(float(args.get("timeout", 30)), 300.0)
                _rgv = await _aio_gv.get_event_loop().run_in_executor(
                    None, lambda: _rsb_py(code, kind="python", trust="untrusted",
                                          network="none", timeout=int(_t_gv)))
                return str(_rgv.get("stdout", _rgv.get("result", ""))) + str(_rgv.get("stderr", _rgv.get("error", "")))

            # Sandbox routing (flag-gated, SANDBOX_EXEC) -- runs the code as a
            # low-privilege sandbox user instead of SYSTEM.
            _sbx, _online, _ = self._sandbox_decision(args, agent)
            if _sbx:
                # OFFLOAD obligatoire : spawn_as_sandbox bloque sur WaitForSingleObject
                # (jusqu'a 300s). En SYNC ici -> gele l'event-loop hub -> /health KO ->
                # WEDGE (root cause incidents 2026-06-03/04 : egress 5-URL action=python).
                # trusted_script + parallel-shell sont deja offloades ; on aligne.
                import asyncio as _aio_py
                _t_py = min(float(args.get("timeout", 30)), 300.0)
                return await _aio_py.get_event_loop().run_in_executor(
                    None, lambda: self._run_sandboxed_python(code, _online, _t_py))

            # v4 : Pool de workers Python pre-warmed
            try:
                import asyncio as _asyncio
                from nokido_agent.app.forge_python_runner import get_runner

                loop = _asyncio.get_event_loop()
                _t = min(float(args.get("timeout", 30)), 300.0)
                result = await loop.run_in_executor(None, get_runner().run_code, code, _t)
                return result.get("stdout", "") + result.get("stderr", "")
            except Exception as e:
                # Fallback via safe_shell_run (REMPART)
                res = safe_shell_run([sys.executable, "-c", code], cwd=str(self.root))
                return f"[runner-fallback: {e}]\n" + res["stdout"] + res["stderr"]

        if act == "shell":
            cmd_str = args.get("code", "")
            commands = args.get("commands")
            sandbox = args.get("sandbox", "local")
            timeout = int(args.get("timeout", 30))
            container = args.get("container", "")

            if not cmd_str and not commands:
                return "ERR: shell: code ou commands requis"

            # FAIL-CLOSED sur le type de bac, AVANT tout aiguillage (P0 2026-09-01).
            _refus_sbx = self._sandbox_valide(sandbox)
            if _refus_sbx:
                return _refus_sbx

            # gVisor tier2 (isolation kernel) AVANT _sandbox_decision : explicit
            # sandbox=gvisor OU auto-route agent UNTRUSTED (ring>=4). Doit precede le
            # chemin user-restreint (SANDBOX_EXEC) pour gagner. Fail-closed si indispo.
            if args.get("sandbox") == "gvisor" or (ring >= 4 and not args.get("sandbox")):
                import asyncio as _aio_gv

                _loop_gv = _aio_gv.get_event_loop()
                _cmds_gv = commands if (commands and isinstance(commands, list)) else [cmd_str]
                _res_gv = await _aio_gv.gather(*[
                    _loop_gv.run_in_executor(
                        None, lambda c=c: self._exec_sandboxed(c, "gvisor", container, timeout, agent, ring))
                    for c in _cmds_gv], return_exceptions=True)
                if commands and isinstance(commands, list):
                    _out_gv = []
                    for c, r in zip(_cmds_gv, _res_gv):
                        if isinstance(r, Exception):
                            _out_gv.append({"cmd": str(c)[:80], "ok": False, "error": str(r)[:200]})
                        else:
                            _out_gv.append({"cmd": str(c)[:80], **r})
                    return json.dumps(_out_gv, ensure_ascii=False)
                _rr_gv = _res_gv[0]
                if isinstance(_rr_gv, Exception):
                    return f"ERR gvisor: {_rr_gv}"
                return (_rr_gv.get("stdout", "") or "") + (_rr_gv.get("stderr", "") or "")

            if commands and isinstance(commands, list):
                # ── Parallel batch ───────────────────────────────────────────
                import asyncio as _aio

                loop = _aio.get_event_loop()
                _sbx, _online, _ = self._sandbox_decision(args, agent)

                def _run_one(cmd):
                    # Un TYPE de sandbox explicite (wasm/docker/ps_clm/windows/
                    # console) PRIME sur le sandboxing par defaut : sinon
                    # _run_sandboxed_shell passe le module a cmd.exe -> « Acces
                    # refuse » (un .wasm n'est pas un exe). Mesure 2026-07-28.
                    if sandbox and sandbox not in ("local", ""):
                        return self._exec_sandboxed(cmd, sandbox, container, timeout, agent, ring)
                    if _sbx:
                        return self._run_sandboxed_shell(cmd, _online, timeout, agent)
                    return self._exec_sandboxed(cmd, sandbox, container, timeout, agent, ring)

                # RESSOURCE EXCLUSIVE : deux commandes qui ecrivent le meme index
                # git ne peuvent PAS tourner en parallele (.git/index.lock est un
                # verrou FICHIER exclusif, aucun WAL ne le couvre). On SERIALISE
                # par cle de ressource ; les groupes restent paralleles entre eux.
                import re as _re_x

                _RE_REPO = _re_x.compile(r'-C\s+"?([^"\s]+)"?')

                def _excl_key(cmd):
                    s = str(cmd).lstrip().lower()
                    if not s.startswith("git "):
                        return None
                    m = _RE_REPO.search(str(cmd))
                    return "git:" + (m.group(1) if m else "cwd")

                _groups = {}
                _order = []
                for _i, _c in enumerate(commands):
                    _k = _excl_key(_c) or ("__par%d" % _i)
                    if _k not in _groups:
                        _groups[_k] = []
                        _order.append(_k)
                    _groups[_k].append((_i, _c))

                def _run_group(items):
                    outs = []
                    for _idx, _cmd in items:
                        try:
                            outs.append((_idx, _run_one(_cmd)))
                        except Exception as _e:  # noqa: BLE001 - remonte par item
                            outs.append((_idx, _e))
                    return outs

                tasks = [loop.run_in_executor(None, _run_group, _groups[k]) for k in _order]
                _gres = await _aio.gather(*tasks, return_exceptions=True)
                results = [None] * len(commands)
                for _k, _gr in zip(_order, _gres):
                    if isinstance(_gr, Exception):
                        for _idx, _c in _groups[_k]:
                            results[_idx] = _gr
                    else:
                        for _idx, _r in _gr:
                            results[_idx] = _r
                out = []
                for cmd, r in zip(commands, results):
                    if isinstance(r, Exception):
                        out.append({"cmd": cmd[:80], "ok": False, "error": str(r)[:200]})
                    else:
                        out.append({"cmd": cmd[:80], **r})
                return json.dumps(out, ensure_ascii=False)
            else:
                _sbx, _online, _ = self._sandbox_decision(args, agent)
                if not (sandbox and sandbox not in ("local", "")) and _sbx:
                    # OFFLOAD : idem action=python -> ne pas bloquer l'event-loop hub.
                    # (sandbox explicite non-local -> _exec_sandboxed ci-dessous.)
                    import asyncio as _aio_sh
                    rr = await _aio_sh.get_event_loop().run_in_executor(
                        None, lambda: self._run_sandboxed_shell(cmd_str, _online, timeout, agent))
                    return (rr.get("stdout", "") or "") + (rr.get("stderr", "") or "")
                # OFFLOAD (2026-08-17) : DERNIER chemin d'execution encore
                # synchrone sur l'event-loop. Les commandes multiples passent deja
                # par run_in_executor (_run_group), gvisor aussi (plus haut), et
                # _run_sandboxed_shell juste au-dessus ; ce cas — commande UNIQUE
                # avec sandbox EXPLICITE (ps_clm, docker, wasm, windows) — restait
                # bloquant. La stack coupable relevee par LoopSentinel s'arrete
                # exactement ici : _exec_sandboxed -> subprocess.communicate() ->
                # threading.join(), sous run_forever. N'importe quelle commande
                # longue gelait donc le hub ENTIER jusqu'a la coupure du watchdog
                # (deux morts le 2026-08-17). Le sandbox wasm est couvert par le
                # meme deport : run_wasm_deno lance Deno en subprocess.
                import asyncio as _aio_x

                r = await _aio_x.to_thread(
                    self._exec_sandboxed, cmd_str, sandbox, container, timeout, agent, ring
                )
                return r.get("stdout", "") + r.get("stderr", "")
        if act == "atlas_get":
            p = self.root / "project_atlas.json"
            return p.read_text("utf-8") if p.exists() else "Atlas non trouve."
        if act == "worker_status":
            from nokido_agent.app.forge_python_runner import get_runner
            import json as _j

            ws = get_runner().worker_status()
            return _j.dumps(ws, indent=2)
        if act == "setup_check":
            return f"System OK | Agent: {agent} | Ring: {ring} | Time: {datetime.now().strftime('%H:%M:%S')}"
        if act == "restart_claude":
            import subprocess as _sp

            _sp.Popen(["python", str(self.root / "tools" / "restart_claude.py"), "full"])
            return "Restart lance en arriere-plan"
        if act == "github":
            # Appel GitHub API : liste les repos, lis un fichier, cherche des commits
            import urllib.request as _ur, json as _j, base64 as _b64

            repo = args.get("repo", "")  # ex: "az0/linkgopher"
            action2 = args.get("sub", "info")  # info | files | read | commits | search
            path = args.get("path", "")
            _gh_headers = {"User-Agent": "LaForge/1.0", "Accept": "application/vnd.github.v3+json"}
            # Coffre d'abord (DPAPI -> WCM -> Nokido.env -> env). L'environnement
            # reste joignable en dernier recours, mais il n'est plus la PREMIERE
            # source : c'est la couche qu'aucune rotation ne met a jour.
            token = ""
            try:
                import sys as _sy

                _app = str(Path(__file__).resolve().parent)
                if _app not in _sy.path:
                    _sy.path.insert(0, _app)
                from nokido_agent.app.forge_secrets import get_secret as _gs_gh

                token = (_gs_gh("GITHUB_TOKEN") or "").strip()
            except Exception as _e_gh:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[github] jeton lu hors coffre (%s) : repli sur l'environnement, "
                    "couche qu'aucune rotation ne met a jour", type(_e_gh).__name__)
            if not token:
                token = __import__("os").environ.get("GITHUB_TOKEN", "")
            if token:
                _gh_headers["Authorization"] = f"token {token}"
            base_url = f"https://api.github.com/repos/{repo}"
            try:
                if action2 == "info" or not repo:
                    url = base_url
                elif action2 == "files":
                    url = f"{base_url}/contents/{path}"
                elif action2 == "read":
                    url = f"{base_url}/contents/{path}"
                elif action2 == "commits":
                    url = f"{base_url}/commits?per_page={args.get('limit', 10)}&path={path}"
                elif action2 == "search":
                    query = args.get("query", "")
                    url = f"https://api.github.com/search/code?q={_ur.parse.quote(query)}+repo:{repo}"
                elif action2 == "branches":
                    url = f"{base_url}/branches"
                elif action2 == "prs":
                    state = args.get("state", "all")
                    url = f"{base_url}/pulls?state={state}&per_page=20"
                else:
                    return f"github sub-action inconnue: {action2}"
                req = _ur.Request(url, headers=_gh_headers)
                with _ur.urlopen(req, timeout=10) as r:
                    d = _j.loads(r.read())
                    # Si read/files sur un fichier, décoder le contenu base64
                    if action2 == "read" and isinstance(d, dict) and d.get("encoding") == "base64":
                        content = _b64.b64decode(d["content"]).decode("utf-8", errors="replace")
                        size = d.get("size", 0)
                        return f"=== {path} ({size}b) ===\n" + content[:8000]
                    return _j.dumps(d, ensure_ascii=False, indent=2)[:6000]
            except Exception as e:
                return f"github ERR: {e}"
        if act in ("atlas_build", "save_situation", "make_snapshot", "audit_log"):
            return f"Action {act} : non disponible dans cette instance (registre standalone)."
        return f"Action {act} non implementee dans le Registry."

    # -- HANDLERS : Web & Agents --

    async def handle_web_search(self, args: dict, agent: str, ring: int) -> str:
        """Recherche web avec cascade SearXNG -> Groq fallback."""
        import sys as _sys, os as _os

        _sys.path.insert(0, str(self.root / "app"))
        from nokido_agent.app.forge_web_fallback import web_search_with_fallback, format_results

        query = args.get("query", "")
        max_res = int(args.get("max_results", 5))
        results = await web_search_with_fallback(query, max_results=max_res)
        if not results:
            return "Aucun resultat (SearXNG + Groq fallback vides)."
        return format_results(results)

    async def handle_absorb_rfc_knowledge(self, args: dict, agent: str, ring: int) -> str:
        import sys as _sys
        import json as _j
        _sys.path.insert(0, str(self.root / "tools"))
        from nokido_agent.tools.forge_rfc_ingest import LocalRFCIngestionTool
        
        query = args.get("concept_query", "")
        if not query:
            return "Erreur: concept_query est vide."
            
        tool = LocalRFCIngestionTool()
        res = tool.process_and_ingest(query)
        return _j.dumps(res, ensure_ascii=False, indent=2)

    async def handle_query_documentation(self, args: dict, agent: str, ring: int) -> str:
        import sys as _sys
        import json as _j
        _sys.path.insert(0, str(self.root / "tools"))
        from nokido_agent.tools.forge_docset_reader import DocsetReaderTool
        
        docset = args.get("docset_name", "")
        query = args.get("search_query", "")
        if not docset or not query:
            return "Erreur: docset_name et search_query sont requis."
            
        tool = DocsetReaderTool()
        res = tool.query_documentation(docset, query)
        return _j.dumps(res, ensure_ascii=False, indent=2)

    async def handle_search_local_file(self, args: dict, agent: str, ring: int) -> str:
        import re as _re, os as _os
        path = self.root / args.get("path", "")
        pattern = args.get("pattern", "")
        ctx = int(args.get("context_lines", 2))
        if not _os.path.exists(path): return f"Fichier introuvable: {path}"
        
        matches = []
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    if _re.search(pattern, line, _re.IGNORECASE):
                        start = max(0, i - ctx)
                        end = min(len(lines), i + ctx + 1)
                        matches.append(f"--- Ligne {i+1} ---\n" + "".join(lines[start:end]))
            if not matches: return "Aucun match trouvé."
            return "\n".join(matches[:10]) + (f"\n... ({len(matches)-10} de plus)" if len(matches) > 10 else "")
        except Exception as e: return f"Erreur: {e}"

    async def handle_query_local_json(self, args: dict, agent: str, ring: int) -> str:
        import json as _j, os as _os
        path = self.root / args.get("path", "")
        filter_str = args.get("key_filter", "").lower()
        last_n = int(args.get("last_n", 10))
        if not _os.path.exists(path): return "Fichier introuvable."
        
        results = []
        try:
            # Detect JSONL vs JSON
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                if str(path).endswith(".jsonl"):
                    lines = f.readlines()[-last_n:]
                    for line in lines:
                        if filter_str in line.lower(): results.append(_j.loads(line))
                else:
                    data = _j.load(f)
                    if isinstance(data, list):
                        results = [x for x in data if filter_str in str(x).lower()][:last_n]
                    else:
                        results = {k: v for k, v in data.items() if filter_str in k.lower()}
            return _j.dumps(results, indent=2, ensure_ascii=False)
        except Exception as e: return f"Erreur: {e}"

    async def handle_delegate_to_local_scout(self, args: dict, agent: str, ring: int) -> str:
        import requests as _req, os as _os
        path = self.root / args.get("path", "")
        prompt = args.get("prompt", "")
        if not _os.path.exists(path): return "Fichier introuvable."
        
        content = ""
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()[-10000:] # On limite au 10k derniers caractères pour le SLM
            
        try:
            # Appel à Ollama local (on suppose qu'il tourne sur 11434)
            # On utilise un modèle léger comme Qwen 2.5 1.5B/3B si dispo, sinon le défaut
            r = _req.post("http://127.0.0.1:11434/api/generate", json={
                "model": "qwen2.5-coder:1.5b", # On tente le scout ultra-rapide
                "prompt": f"FICHIER:\n{content}\n\nQUESTION: {prompt}\n\nSYNTHÈSE COURTE:",
                "stream": False
            }, timeout=30)
            if r.status_code != 200:
                # Fallback sur le modèle par défaut si Qwen n'est pas là
                r = _req.post("http://127.0.0.1:11434/api/generate", json={
                    "model": "llama3.1:8b", 
                    "prompt": f"FICHIER:\n{content}\n\nQUESTION: {prompt}\n\nSYNTHÈSE COURTE:",
                    "stream": False
                }, timeout=30)
            return r.json().get("response", "Erreur Scout local.")
        except Exception as e: return f"Erreur Scout: {e}"

    async def handle_web_search_rag(self, args, agent, ring):
        from nokido_agent.app.forge_web_search import aggregate_search
        import sqlite3
        from datetime import datetime, timezone

        query = args.get("query", "")
        max_res = int(args.get("max_results", 5))
        domain = args.get("domain", "web_search")
        results = await aggregate_search(query, max_res)
        if not results:
            return "Aucun resultat."
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        now = datetime.now(timezone.utc).isoformat()
        for r in results:
            uid = "ws_" + str(abs(hash(r["url"])) % 10**9)
            text = r["title"] + "\n" + r["content"][:2000] + "\n" + r["url"]
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks (id,text,source,domain,role_hint,author,ingested_at) VALUES (?,?,?,?,?,?,?)",
                (uid, text, r["url"], domain, query[:100], "SearXNG", now),
            )
        conn.commit()
        conn.close()
        lines = [r["title"][:70] + " | " + r["url"] for r in results]
        return f"Ingere {len(results)} (domain={domain}):\n" + "\n".join(lines)

    async def handle_ask_agent(self, args: dict, agent: str, ring: int) -> str:
        from nokido_agent.app.forge_agent_proxy import ask

        provider = args.get("provider", "gemini")
        # "prompt" est le champ canonical du tool schema — "message" = compat legacy
        message = args.get("prompt", args.get("message", ""))
        thread_id = args.get("thread_id")
        model = args.get("model")
        # Tâches code/generation OU raw=True : AUCUNE persona Nokido (le modèle exécute
        # la tâche brute, ne se présente pas comme "agent de l'écosystème"). rag_context=False
        # ne suffisait PAS (la persona base restait) -> on passe raw=True à ask().
        rag_ctx = args.get("rag_context", True)
        _raw = bool(args.get("raw")) or args.get("task_type") in ("code", "generation", "write")
        if _raw:
            rag_ctx = False
        kw = {"thread_id": thread_id, "rag_context": rag_ctx, "raw": _raw}
        if model:
            kw["model"] = model  # type: ignore[assignment]
        _mt = args.get("max_tokens")
        if _mt:
            kw["max_tokens"] = int(_mt)  # type: ignore[assignment]
        # Anti-wedge (2026-06-20) : timeout EXTERNE borne -> un provider qui hang
        # (OAuth-CLI) ne bloque jamais la requete indefiniment (le hub repond).
        import asyncio as _aio_ask
        _ask_to = int(args.get("max_wait", 0)) or 240
        try:
            result = await _aio_ask.wait_for(ask(provider, message, **kw), timeout=_ask_to)
        except _aio_ask.TimeoutError:
            return json.dumps({"ok": False,
                               "error": "ask timeout %ss provider=%s (borne, hub protege)" % (_ask_to, provider)},
                              ensure_ascii=False)
        return json.dumps(result, indent=2, ensure_ascii=False)

    # -- HANDLERS : Mode & Coordination --

    async def handle_get_mode(self, args: dict, agent: str, ring: int) -> str:
        s = self.state_mgr.read_state()
        lines = [f"mode={s.get('active_mode', 'AUTO')}  agent={agent}"]
        for ag, info in s.get("agents", {}).items():
            lines.append(f"  {ag}: {info.get('status', '?')} {info.get('progress', 0)}%")
        notifs = s.get("pending_notifications", [])
        if notifs:
            lines.append(f"Notifs en attente: {len(notifs)}")
        return "\n".join(lines)

    async def handle_set_mode(self, args: dict, agent: str, ring: int) -> str:
        if ring > 0:
            return "INTERDIT: set_mode reserve RING_0"
        mode = args.get("mode", "AUTO").upper()
        s = self.state_mgr.read_state()
        s["active_mode"] = mode
        s["permissions"] = "FULL" if mode == "CHEF" else "STANDARD"
        s["last_switch"] = datetime.now().isoformat()
        s["switch_reason"] = args.get("reason", f"set par {agent}")
        self.state_mgr.add_notification(f"-> mode {mode}", source=agent)
        self.state_mgr.write_state(s)
        return f"OK mode={mode}"

    async def handle_notify(self, args: dict, agent: str, ring: int) -> str:
        msg = args.get("message", "")
        if not msg:
            return "Erreur: parametre 'message' requis"

        # Sprint 3 M2M : validation du message inter-agents (config/m2m_intents.json).
        # warn (defaut) = annotation + event bus ; error = refus. Fail-open.
        _m2m_note = ""
        try:
            from nokido_agent.app.forge_m2m_protocol import check as _m2m_check
            _m2m_ok, _m2m_v = _m2m_check("notify", msg)
            if not _m2m_ok:
                return f"M2M_REFUSED {_m2m_v.get('code')}: {'; '.join(_m2m_v.get('violations') or [])}"
            if _m2m_v.get("code") not in ("M2M_OK", "M2M_OK_PROSE"):
                _m2m_note = f" [{_m2m_v.get('code')}]"
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Un VALIDATEUR qui tombe en silence laisse passer le message NON VALIDE :
            # la gouvernance parait active alors qu'elle est contournee.
            _lg.getLogger("Nokido.Registry").error(
                "[m2m] validation du protocole IMPOSSIBLE (%s: %s) — le message part "
                "SANS avoir ete valide | consequence: la conformite M2M annoncee n'est "
                "pas garantie pour ce message", type(e).__name__, str(e)[:100])

        # ── STEP 1 : Archive immuable (EVENTBUS_ARCHIVE) ─────────────────────
        # Identifier le destinataire depuis le préfixe [AGENT][...]
        import re as _re, time as _nt, json as _nj, hashlib as _nh
        import sqlite3 as _nsq, sys as _ns, os as _no
        from datetime import datetime as _ndt, timezone as _ntz

        _to_map = {
            "GEMINI": "agt_gemini",
            "CLAUDE": "agt_claude",
            "COPILOT": "agt_copilot",
            "CODEX": "agt_codex",
            "DAEMON": "agt_daemon",
            "HUB": "agt_hub",
            "CLINE": "agt_cline",
            "SYSTEM": "agt_hub",
            "NOKIDO": "agt_nokido",
            # alias directs (parametre `to`)
            "gemini": "agt_gemini",
            "claude": "agt_claude",
            "copilot": "agt_copilot",
            "codex": "agt_codex",
            "daemon": "agt_daemon",
            "cline": "agt_cline",
            "hub": "agt_hub",
            "nokido": "agt_nokido",
            # ANTIGRAVITY (alias AGY) : identite canonique ring1, inbox agt_antigravity
            "ANTIGRAVITY": "agt_antigravity",
            "AGY": "agt_antigravity",
            "antigravity": "agt_antigravity",
            "agy": "agt_antigravity",
        }
        # CLIENTS CLI connus = cible du broadcast (pas daemon/hub interne)
        _broadcast_all = ["agt_claude", "agt_gemini", "agt_copilot", "agt_codex", "agt_cline", "agt_nokido", "agt_antigravity"]
        # ── M2M DURABLE : complete les maps figees par les cli_agent du registre
        # LIVE (config/agent_identities.json, reload mtime). Le fige ci-dessus reste
        # un PLANCHER (fallback si registre illisible) ; la derivation ajoute
        # mammouth/zcode/roo/vibe/sixth/vscode + tout futur CLI sans redeploiement.
        # On n'itere QUE les cli_agent : les providers (mistral, cohere) sont exclus.
        try:
            _ns.path.insert(0, _no.path.join(_no.path.dirname(__file__)))
            from nokido_agent.app.forge_videur import cli_agents as _cli_ag, mailbox_de as _mb_de
            for _nm in _cli_ag():
                _bx = _mb_de(_nm)
                if not _bx:
                    continue
                _to_map[_nm] = _bx
                _to_map[_nm.lower()] = _bx
                if _bx not in _broadcast_all:
                    _broadcast_all.append(_bx)
        except Exception:  # noqa: BLE001
            pass  # registre illisible -> plancher fige conserve
        _explicit_to = args.get("to", "")
        _self_agt = f"agt_{agent.lower()}"

        # ── Postal souverain (forge_postal) : courrier RICHE + DÉDUP + cycle de vie/accusés.
        # Source de vérité anti-triplication (l'archive agent_messages reste le transport/
        # historique). Best-effort point-à-point, ne bloque JAMAIS notify.
        if _explicit_to and _explicit_to.lower() not in ("all", "broadcast", "*", "everyone"):
            try:
                from nokido_agent.app.forge_postal import facteur as _postal_facteur
                from nokido_agent.app.forge_postal import post as _postal_post

                _pm = _postal_post(agent, _explicit_to, msg, reply_to=agent)
                _postal_facteur(_pm.get("recipient_channel", ""))
                # LE COURRIER REVEILLE SON DRAIN (2026-07-31). NokidoGeminiAutonomous
                # est volontairement `disabled` (son tick concurrence les CLI
                # interactifs, decision owner du 18-06) et son commentaire prevoit
                # « reveil via nokido_ensure_service au besoin » — que personne
                # n'appelait. Un message livre a un drain endormi reste `delivered`
                # pour toujours, sans que rien ne le signale. Le message EST
                # l'intention : meme doctrine que les cerveaux a la demande.
                # On ne passe PAS le service en permanent : on le reveille.
                _dest_l = str(_explicit_to).strip().lower()
                if _dest_l in ("gemini", "agy", "antigravity"):
                    import threading as _th_w
                    import time as _t_w

                    _last = getattr(self, "_dernier_reveil_agy", 0.0)
                    if _t_w.time() - _last > 60.0:
                        self._dernier_reveil_agy = _t_w.time()

                        def _reveiller_drain():
                            # Thread daemon : ensure_service fait des appels HTTP au
                            # superviseur, jamais dans l'event loop du hub (wedge).
                            try:
                                import sys as _s_w
                                import urllib.request as _ur_w

                                _s_w.path.insert(0, str(self.root / "app"))
                                _tok_w = ""
                                try:
                                    from nokido_agent.app.forge_secrets import get_secret as _gs_w

                                    _tok_w = _gs_w("LAFORGE_SUPERVISOR_TOKEN") or ""
                                except Exception as e:  # noqa: BLE001
                                    import logging as _lg

                                    _lg.getLogger("Nokido.Registry").warning(
                                        "[superviseur] jeton illisible (%s) | consequence: "
                                        "appel NON authentifie, refus obscur en aval",
                                        type(e).__name__)
                                # Route HTTP du superviseur : stdlib pur, quelques ms.
                                # `ensure()` passe par un subprocess Python complet et
                                # echoue partout ou subprocess est interdit.
                                # Chemin EXACT verifie dans supervisor.ts (L1683) :
                                # /supervisor/service/start/<nom>. Le raccourci
                                # /supervisor/start/ n'existe pas et aurait rendu 404
                                # en silence — un reveil mort a la place d'un lent.
                                _req_w = _ur_w.Request(
                                    "http://127.0.0.1:8765/supervisor/service/start/"
                                    "NokidoGeminiAutonomous",
                                    data=b"", method="POST",
                                    headers={"Authorization": f"Bearer {_tok_w}"}
                                    if _tok_w else {})
                                try:
                                    with _ur_w.urlopen(_req_w, timeout=30) as _rp_w:
                                        logger.info(f"[postal] drain AGY reveille "
                                                    f"(HTTP {_rp_w.status})")
                                except Exception as _he_w:  # noqa: BLE001
                                    # REPLI sur le chemin historique : mieux vaut un
                                    # subprocess lent qu'un drain qui dort.
                                    logger.warning(f"[postal] reveil HTTP KO "
                                                   f"({type(_he_w).__name__}) -> repli ensure()")
                                    _s_w.path.insert(0, str(self.root / "tools"))
                                    from nokido_agent.tools.forge_ensure_service import ensure as _ens

                                    logger.info("[postal] drain AGY reveille (repli): "
                                                f"{_ens('NokidoGeminiAutonomous', 'running')}")
                            except Exception as _we:  # noqa: BLE001
                                # Journalise : un reveil muet qui echoue redonne
                                # exactement la panne qu'on corrige ici.
                                logger.warning(
                                    f"[postal] reveil du drain AGY impossible "
                                    f"({type(_we).__name__}: {str(_we)[:120]}) — "
                                    f"le courrier est depose mais peut dormir")

                        _th_w.Thread(target=_reveiller_drain, daemon=True).start()
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[postal] reveil du drain NON TENTE (%s: %s) | consequence: le "
                    "courrier est depose mais peut rester 'pending' sans que personne "
                    "ne le signale", type(e).__name__, str(e)[:100])

        # ── Destinataires : broadcast (to=ALL) | point-à-point | archive ─────
        if _explicit_to and _explicit_to.lower() in ("all", "broadcast", "*", "everyone"):
            # BROADCAST : fan-out vers tous les CLI sauf l'émetteur. Chaque CLI
            # le reçoit via [HOOK:INBOX] (hub_lifecycle_hooks) à son prochain call.
            _targets = [t for t in _broadcast_all if t != _self_agt]
            _is_broadcast = True
        elif _explicit_to and _explicit_to in _to_map:
            _targets = [_to_map[_explicit_to]]
            _is_broadcast = False
        else:
            # Destinataire deduit du prefixe du message (mesure 2026-08-10).
            # Fenetre portee de 40 a 80 caracteres : une forme dirigee
            # [ANTIGRAVITY->CLAUDE] depasse 40 et tombait donc en archive.
            _AGT = r"CLAUDE|GEMINI|ANTIGRAVITY|AGY|COPILOT|CODEX|DAEMON|HUB|CLINE|SYSTEM|NOKIDO"
            try:
                from nokido_agent.app.forge_videur import cli_agents as _cag2
                _AGT = "|".join(sorted(set(_AGT.split("|")) | _cag2()))
            except Exception:  # noqa: BLE001
                pass
            _head = msg[:80]
            # 1) forme DIRIGEE [EMETTEUR->DEST] : c'est DEST qui route, pas l'emetteur.
            #    Fleches acceptees : ASCII -> et =>, et U+2192 que AGY emet reellement.
            _m = _re.search(
                r"\[(?:" + _AGT + r")\s*(?:->|=>|→)\s*(" + _AGT + r")\]",
                _head, _re.I)
            # 2) forme SIMPLE [DEST].
            if _m is None:
                _m = _re.search(r"\[(" + _AGT + r")\]", _head, _re.I)
            _to_agent = "EVENTBUS_ARCHIVE"
            if _m:
                _to_agent = _to_map.get(_m.group(1).strip().upper(), "EVENTBUS_ARCHIVE")
            if _to_agent == "EVENTBUS_ARCHIVE":
                # Une disparition MUETTE est indiscernable d'un message jamais
                # envoye : on NOMME ce qu'on n'a pas su router. Logger importe
                # LOCALEMENT (_lg n'est lie que dans un bloc except plus haut).
                import logging as _lg_postal

                _lg_postal.getLogger("Nokido.Registry").warning(
                    "[postal] destinataire NON IDENTIFIE -> EVENTBUS_ARCHIVE | "
                    "from=%s | tete=%r | consequence: STEP 2 saute ce destinataire, "
                    "aucun push INBOX, personne ne lira ce message",
                    agent, _head[:80])
            _targets = [_to_agent]
            _is_broadcast = False

        # ── STEP 1 : Archive immuable agent_messages (1 ligne / destinataire) ─
        _first_frame = None
        # P0 (owner 2026-09-05) : cette archive s'ecrivait EN SYNCHRONE dans l'event
        # loop, dans RAG/embeddings.db (24,9 Go) avec busy_timeout=15000 — tout verrou
        # tenu par un autre ecrivain (backfill, ingestion, network_log) gelait le hub
        # 15 s ; c'etait la pile du loop a CHAQUE kill du watchdog (16 morts en 2 j).
        # Deux gestes, en deux temps. Ce soir : l'ecriture part dans un THREAD, le
        # loop reste libre (c'est ce qui tuait). Passe 2 : la table bascule vers la
        # base M2M dediee (forge_db_path.open_m2m) — mais TOUS les sites de ce
        # fichier (archive d'args, whoami, eventbus, handle_inbox : 13 autres SQL sur
        # agent_messages) et les lecteurs externes basculent ENSEMBLE, apres copie
        # delta (tools/forge_m2m_db_split) et restart ; un seul site bascule = un hub
        # qui ecrit d'un cote et lit de l'autre.
        _rows_archive = []
        for _i, _tgt in enumerate(_targets):
            _frame_id = "frm_" + _nh.md5(f"{agent}{_tgt}{_nt.time()}{_i}".encode()).hexdigest()[:12]
            if _first_frame is None:
                _first_frame = _frame_id
            _rows_archive.append((
                _frame_id, agent, _tgt, _frame_id, "tool.hub.arg.message",
                _nj.dumps({"text": msg}, ensure_ascii=False), "unread",
                _ndt.now(_ntz.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ))

        def _archiver_sync(_rows=_rows_archive):
            _ns.path.insert(0, _no.path.dirname(__file__))
            from nokido_agent.app.forge_db_path import open_m2m as _open_m2m
            _c = _open_m2m(timeout=15.0)   # scission M2M passe 2 : la table suit l'interrupteur sandbox/m2m.switch
            try:
                _c.executemany(
                    "INSERT OR IGNORE INTO agent_messages"
                    "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?)", _rows)
            finally:
                _c.close()

        try:
            import asyncio as _aio
            await _aio.to_thread(_archiver_sync)
        except Exception as _ae:
            import logging as _log

            _log.getLogger("Nokido.Hub").warning(f"handle_notify DB: {_ae}")

        # ── STEP 2 : Push INBOX volatile (CQRS) par destinataire ─────────────
        for _i, _tgt in enumerate(_targets):
            if _tgt == "EVENTBUS_ARCHIVE":
                continue
            try:
                _ns.path.insert(0, _no.path.dirname(__file__))
                from nokido_agent.app.forge_message_frame import INBOX as _INBOX, MessageFrame as _MF

                _frame = _MF(
                    frame_id=(_first_frame or "frm_inbox") + f"_{_i}",
                    from_agent=agent,
                    to_agent=_tgt,
                    action="notification",
                    text=msg,
                    parameters={"raw_message": msg},
                )
                _INBOX.push(_frame)
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                # fail-open ASSUME : la notification ne doit pas echouer parce que
                # l'inbox est indisponible. Mais l'assumer n'est pas le taire.
                _lg.getLogger("Nokido.Registry").warning(
                    "[inbox] message NON pousse (%s: %s) — notification maintenue "
                    "(fail-open) | consequence: ce message n'apparaitra pas dans "
                    "l'inbox du destinataire", type(e).__name__, str(e)[:100])

        # ── STEP 3 : Notification volatile (poll classique) ──────────────────
        _tagged_msg = f"[frame:{_first_frame or 'frm_x'}|hash:{_nh.md5(msg.encode()).hexdigest()[:16]}] {msg}"
        self.state_mgr.add_notification(_tagged_msg, source=agent)
        if _is_broadcast:
            return f"OK broadcast envoye a {len(_targets)} agents: {', '.join(_targets)}" + _m2m_note
        return "OK notification envoyee" + _m2m_note

    async def handle_whoami(self, args: dict, agent: str, ring: int) -> str:
        """
        Retourne l etat complet de l agent depuis la DB en temps reel.
        UNE seule requete au boot — remplace GEMINI.md statique.
        Format JSON compact optimise pour LLM (pas de prose, juste les faits).
        """
        import sqlite3 as _sq, json as _j, time as _t, os as _o, sys as _s

        _s.path.insert(0, _o.path.join(_o.path.dirname(__file__)))
        from pathlib import Path as _P

        _db = str(_P(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
        _now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            _conn = _sq.connect(_db, timeout=5)
            _conn.row_factory = _sq.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            # Scission M2M : agent_messages vit dans la base M2M (interrupteur
            # sandbox/m2m.switch) ; _conn reste la base du RAG pour les autres tables.
            from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
            _m2m = _sq.connect(_m2m_path(), timeout=5)
            _m2m.row_factory = _sq.Row

            # 1. Messages non lus pour cet agent
            _unread = _m2m.execute(
                "SELECT id, from_agent, created_at, payload FROM agent_messages "
                "WHERE to_agent=? AND status='unread' ORDER BY rowid DESC LIMIT 5",
                (f"agt_{agent.lower()}",),
            ).fetchall()

            # 2. Jobs interrompus (failed/running/pending)
            _jobs = _conn.execute(
                "SELECT id, theme, step, status FROM watch_jobs "
                "WHERE status IN ('pending','running','error') "
                "ORDER BY rowid DESC LIMIT 5"
            ).fetchall()

            # 3. Chain nodes bloqués pour cet agent
            _nodes = _conn.execute(
                "SELECT chain_id, step_name, status, error FROM agent_chain_nodes "
                "WHERE status IN ('failed','running') ORDER BY rowid DESC LIMIT 5"
            ).fetchall()

            # 4. Biblio unverified
            _biblio = _conn.execute("SELECT id, title FROM biblio_raw WHERE status='unverified' LIMIT 5").fetchall()

            # 5. Derniere action de cet agent
            _last = _m2m.execute(
                "SELECT created_at, payload FROM agent_messages WHERE from_agent IN (?,?) ORDER BY rowid DESC LIMIT 1",
                (agent, f"agt_{agent.lower()}"),
            ).fetchone()

            # 6. Resource Discovery — providers, tools, RAG domains
            _providers = _conn.execute(
                "SELECT provider, ttft_ms, grade FROM provider_scores WHERE status='ok' ORDER BY ttft_ms ASC LIMIT 5"
            ).fetchall()
            # `_conn` lit legitimement la base RAG (biblio, scores, chunks) ; seule
            # la table d'AUTORITE en sort. Connexion dediee, fermee aussitot.
            from nokido_agent.app.forge_db_path import (
                authority_path as _autorite,
                authority_switch_actif as _bascule,
            )

            _sql_tools = ("SELECT tool_name FROM forge_tools WHERE is_active=1 "
                          "AND min_ring<=? ORDER BY min_ring")
            if _bascule():
                _ac = sqlite3.connect(_autorite(), timeout=3)
                try:
                    _tools = _ac.execute(_sql_tools, (ring,)).fetchall()
                finally:
                    _ac.close()
            else:
                _tools = _conn.execute(_sql_tools, (ring,)).fetchall()
            _domains = _conn.execute(
                "SELECT domain, COUNT(*) as n FROM rag_chunks "
                "WHERE domain NOT LIKE 'beir%' GROUP BY domain ORDER BY n DESC LIMIT 8"
            ).fetchall()
            # 6.bis Présence — agents ayant émis un message < 15 min (proxy d'activité ;
            # Phase 1b = présence par-appel via post_dispatch pour du live exact).
            _online = _m2m.execute(
                "SELECT from_agent, MAX(created_at) as last, COUNT(*) as n FROM agent_messages "
                "WHERE created_at > datetime('now','-15 minutes') AND from_agent != '' "
                "GROUP BY from_agent ORDER BY last DESC LIMIT 12"
            ).fetchall()
            _m2m.close()
            _conn.close()

            # 6.ter Token usage pour cet agent (Forge Token Meter)
            _tok_usage = {}
            try:
                from nokido_agent.tools.forge_token_meter import get_agent_usage
                _tok_usage = get_agent_usage(agent, since_hours=720)
            except Exception:
                try:
                    import sys as _sys_tm
                    _sys_tm.path.insert(0, str(_P(__file__).resolve().parent.parent / "tools"))
                    from nokido_agent.tools.forge_token_meter import get_agent_usage
                    _tok_usage = get_agent_usage(agent, since_hours=720)
                except Exception:
                    pass

            # 7. Santé services (cross-ref superviseur :8765, GET non gaté) — sinon
            # whoami reste aveugle à une infra cassée tant qu'aucun job/chain n'est
            # en file. RCA 2026-05-29 : SearXNG down + veille KO non détectés car
            # les chains avaient expiré → "rien à reprendre" trompeur.
            _degraded = []
            try:
                import urllib.request as _u

                with _u.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=3) as _r:
                    _svcs = _j.loads(_r.read()).get("services", {})
                _degraded = whoami_degraded_services(_svcs)
            except Exception:
                _degraded = []
            _health_actions = whoami_health_actions(_degraded)

            # 8. Taches DEPOSEES mais jamais RECLAMEES (2026-07-26). Une tache
            # adressee a un CLI interactif lui est RESERVEE : l'executor autonome
            # l'exclut volontairement (_INTERACTIVE_CLIS) et elle attend une
            # reclamation. Si la surface visee ne tourne pas, la tache dort sans
            # que RIEN ne le signale -- mesure : 16 taches ANTIGRAVITY decouvertes
            # par l'owner, traitees a la main. Meme angle mort que le point 7
            # ci-dessus, applique a la FILE et non plus a l'infra.
            _unclaimed = []
            try:
                import sqlite3 as _sq3

                _tdb = _P(__file__).resolve().parent.parent / "sandbox" / "tasks.db"
                _c8 = _sq3.connect("file:%s?mode=ro" % _tdb.as_posix(), uri=True, timeout=2.0)
                try:
                    _unclaimed = [
                        {"agent": _a, "n": _n, "plus_ancienne": _old}
                        for _a, _n, _old in _c8.execute(
                            "SELECT agent, COUNT(*), MIN(created_at) FROM tasks "
                            "WHERE status='pending' GROUP BY agent ORDER BY COUNT(*) DESC"
                        )
                    ]
                finally:
                    _c8.close()
            except Exception:
                _unclaimed = []
            for _u8 in _unclaimed:
                _health_actions = [{
                    "cmd": "task action=claim agent=%s  (ou reveiller sa surface)" % _u8["agent"],
                    "why": "%s tache(s) pending pour %s, la plus ancienne %s -- personne ne draine"
                           % (_u8["n"], _u8["agent"], _u8["plus_ancienne"]),
                }] + _health_actions

            out = {
                "agent": agent,
                "ts": _now,
                "token_usage": _tok_usage,
                "agents_online": [
                    {"agent": o["from_agent"], "last": (o["last"] or "")[-8:], "msgs": o["n"]}
                    for o in _online
                ],
                "unread": [
                    {
                        "id": r["id"][:16],
                        "from": r["from_agent"],
                        "ts": r["created_at"][-8:],
                        "text": _j.loads(r["payload"]).get("text", "")[:120] if r["payload"] else "",
                    }
                    for r in _unread
                ],
                "jobs_interrupted": [
                    {"id": j["id"][:12], "step": j["step"], "status": j["status"], "theme": j["theme"][:60]}
                    for j in _jobs
                ],
                "chain_nodes_blocked": [
                    {
                        "chain": n["chain_id"][:16],
                        "step": n["step_name"],
                        "status": n["status"],
                        "error": (n["error"] or "")[:80],
                    }
                    for n in _nodes
                ],
                "biblio_unverified": [{"id": b["id"][:12], "title": b["title"][:60]} for b in _biblio],
                "tasks_unclaimed": _unclaimed,
                "services_degraded": _degraded,
                "last_action": _last["created_at"] if _last else None,
                # Resource Discovery — ce que Gemini Ultra appellait check_privileges()
                "resources": {
                    "providers_available": [
                        {"model": p["provider"], "ttft_ms": p["ttft_ms"], "grade": p["grade"]} for p in _providers
                    ],
                    "tools_available": [t["tool_name"] for t in _tools],
                    "rag_domains": [{"domain": d["domain"], "chunks": d["n"]} for d in _domains],
                    "ring": ring,
                },
                "next_actions": _health_actions
                + ([{"cmd": "hub action=poll", "why": "messages non lus"}] if _unread else [])
                + (
                    [
                        {
                            "cmd": f"query sql=\"UPDATE agent_chain_nodes SET status='pending' WHERE chain_id='{n['chain_id']}' AND status IN ('failed','running')\"",
                            "why": f"debloquer {n['step_name']}",
                        }
                        for n in _nodes[:2]
                    ]
                    if _nodes
                    else []
                )
                + (
                    [
                        {
                            "cmd": "run action=python code=\"import sys,asyncio; sys.path.insert(0,'app'); from forge_chain_executor import ChainExecutor; asyncio.run(ChainExecutor().execute_pending())\"",
                            "why": f"reprendre job: {j['theme'][:40]}",
                        }
                        for j in _jobs[:1]
                    ]
                    if _jobs
                    else [{"cmd": "hub action=poll", "why": "rien a reprendre"}]
                ),
            }
            return _j.dumps(out, ensure_ascii=False, indent=2)

        except Exception as e:
            return _j.dumps({"agent": agent, "ts": _now, "error": str(e)})

    async def handle_manage_forge_lifecycle(self, args: dict, agent: str, ring: int) -> str:
        """Pilote le cycle de vie (START/STOP/RESTART) des organes Nokido via NSSM."""
        organ = args.get("organ_name", args.get("organ", ""))
        action = args.get("action", "")
        priority = args.get("priority", "NORMAL")
        if not organ or not action:
            return "ERR: manage_forge_lifecycle requiert organ_name + action"
        res = handle_manage_forge_lifecycle(organ_name=organ, action=action, priority=priority)
        return json.dumps(res, ensure_ascii=False, indent=2)

    async def handle_emit_telemetry(self, args: dict, agent: str, ring: int) -> str:
        """
        Nourrit routing_telemetry — l agent signale sa propre performance.
        Usage : hub action=emit_telemetry task_type=crawl chosen_model=groq/llama-3.3-70b
                ttft_ms=344 success_score=0.9
        Implémente le "Bilan de Compétences" de Gemini Ultra Web.
        """
        import sqlite3 as _sq, json as _j, hashlib as _h, time as _t
        from pathlib import Path as _P
        from datetime import datetime as _dt, timezone as _tz

        _db = str(_P(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
        prompt = args.get("prompt_sample", "")[:200]
        phash = _h.md5((prompt or str(_t.time())).encode()).hexdigest()[:16]
        row = {
            "ts": _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_hash": phash,
            "prompt_sample": prompt,
            "chosen_model": args.get("chosen_model", "unknown"),
            "chosen_provider": args.get("chosen_provider", agent),
            "ttft_ms": float(args.get("ttft_ms", 0)),
            "success_score": float(args.get("success_score", 0.5)),
            "task_type": args.get("task_type", "generic"),
            "ring": ring,
        }
        try:
            conn = _sq.connect(_db, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO routing_telemetry(ts,prompt_hash,prompt_sample,"
                "chosen_model,chosen_provider,ttft_ms,success_score,task_type,ring)"
                " VALUES(:ts,:prompt_hash,:prompt_sample,:chosen_model,:chosen_provider,"
                ":ttft_ms,:success_score,:task_type,:ring)",
                row,
            )
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM routing_telemetry").fetchone()[0]
            conn.close()
            return _j.dumps({"ok": True, "routing_telemetry_total": count, "row": row})
        except Exception as e:
            return _j.dumps({"ok": False, "error": str(e)})

    async def handle_poll(self, args: dict, agent: str, ring: int) -> str:
        s = self.state_mgr.read_state()
        notifs = s.pop("pending_notifications", [])
        if notifs:
            self.state_mgr.write_state(s)
        # ── Postal souverain : relève le courrier DELIVERED non-acké de l'agent (SECRÉTAIRE,
        # non-consommant, ack=True à la lecture => ACCUSÉ DE RÉCEPTION). C'est ce qui réconcilie
        # notify(->postal) et poll : avant, poll lisait pending_notifications, un AUTRE store que
        # notify -> "Aucune notification" alors que le message etait livré (bug du test). Best-effort.
        _mail = []
        try:
            from nokido_agent.app.forge_postal import secretaire as _postal_secretaire

            # ack OPTIONNEL (2026-07-29) : lire n'est pas toujours traiter. Un lecteur
            # PASSIF (daemon d'affichage) doit pouvoir relever SANS accuser réception,
            # sinon il vide la boîte de l'agent qui, lui, répond. Défaut inchangé =
            # True : aucun appelant existant ne voit son comportement modifié.
            _ack = str(args.get("ack", True)).strip().lower() not in ("false", "0", "no")
            for _m in _postal_secretaire(agent, ack=_ack):
                _mail.append(
                    f"[POSTAL #{_m['id']} from {_m['from']}/{_m.get('from_channel', '')} "
                    f"reply->{_m.get('reply_to')}] {_m['body']}"
                )
        except Exception:
            pass
        out = list(notifs) + _mail
        return "\n".join(out) if out else "Aucune notification."

    # -- HANDLERS : RAG & Resultats --

    async def handle_index_result(self, args: dict, agent: str, ring: int) -> str:
        task_id = args.get("task_id", "?")
        result = args.get("result", "")
        src = f"mcp_result:{agent}:{task_id}:{int(time.time())}"
        text = f"[AGENT:{agent}] [TASK:{task_id}]\n{result}"[:4000]
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks(id, source, text, domain, author, ingested_at) VALUES(?, ?, ?, ?, ?, datetime('now'))",
                (f"idx_{agent}_{task_id}_{int(time.time())}", src, text, "mcp_result", agent),
            )
            conn.commit()
            conn.close()
            self.state_mgr.add_notification(f"tache '{task_id}' indexee RAG", source=agent)
            return f"OK indexe: {src}"
        except Exception as e:
            return f"Erreur index: {e}"

    async def handle_search_recent(self, args: dict, agent: str, ring: int) -> str:
        topic = args.get("topic", "")
        limit = int(args.get("limit", 10))
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            sql = "SELECT source, text FROM rag_chunks WHERE domain='mcp_result' ORDER BY rowid DESC LIMIT ?"
            params = (limit,)
            if topic:
                sql = "SELECT source, text FROM rag_chunks WHERE domain='mcp_result' AND text LIKE ? ORDER BY rowid DESC LIMIT ?"
                params = (f"%{topic}%", limit)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            if not rows:
                return "Aucun resultat."
            return "\n\n".join(f"[{r['source']}]\n{r['text'][:400]}" for r in rows)
        except Exception as e:
            return f"Erreur search: {e}"

    async def handle_trigger_autonomous_evolution(self, args: dict, agent: str, ring: int) -> str:
        # Accept intent | intention | task (catalog schema uses "intention",
        # historical handlers used "intent").
        intent = args.get("intent") or args.get("intention") or args.get("task") or "evolve"
        try:
            from nokido_agent.app.forge_runner import spawn
            import json as _json

            # AutonomousOrchestrator.run_sync(intent) construit le DAG +
            # exécute via OneMCPMultiplexer (PARSE → DAG → execute) en bloquant.
            # On le détache via forge_runner.spawn() — fire-and-forget, le
            # tid retourné permet de poll les résultats RAG / event_log.
            job_code = (
                "import sys, json\n"
                f"sys.path.insert(0, r'{str(self.root / 'app').replace(chr(92), '/')}')\n"
                "from forge_autonomous_orchestrator import AutonomousOrchestrator\n"
                f"intent = {_json.dumps(intent)}\n"
                "r = AutonomousOrchestrator().run_sync(intent)\n"
                "print(json.dumps(r, ensure_ascii=False, default=str))\n"
            )
            tid = spawn(job_code, prefix="orch", timeout_s=900)
            return _json.dumps({"ok": True, "task_id": tid, "intent": intent[:200]}, ensure_ascii=False)
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"

    async def handle_task_status(self, args: dict, agent: str, ring: int) -> str:
        import json as _j
        from nokido_agent.app.forge_jobid import load_job

        tid = args.get("task_id", "")
        job_id = args.get("job_id", "") or tid

        # Priorité : jobs_state (riche)
        ctx = load_job(job_id) if job_id else None
        if not ctx and tid and tid != job_id:
            ctx = load_job(tid)
        if ctx:
            return _j.dumps(
                {
                    "job_id": ctx.job_id,
                    "task_id": tid,
                    "status": ctx.status,
                    "agent": ctx.agent,
                    "intent_type": ctx.intent_type,
                    "result_summary": ctx.result_summary,
                    "error": ctx.error,
                },
                ensure_ascii=False,
            )

        # Fallback : tasks.db
        conn = self._task_db()
        row = conn.execute(
            "SELECT id,description,agent,status,result,job_id,from_agent FROM tasks WHERE id=? OR job_id=?",
            (tid, job_id),
        ).fetchone()
        conn.close()
        if not row:
            return _j.dumps({"ok": False, "reason": "not_found"})
        return _j.dumps(
            {
                "task_id": row[0],
                "description": row[1],
                "agent": row[2],
                "status": row[3],
                "result": row[4],
                "job_id": row[5],
                "from_agent": row[6],
            },
            ensure_ascii=False,
        )

    # -- HANDLER : Bibliography Worker (Sprint Alpha) --
    async def handle_biblio(self, args: dict, agent: str, ring: int) -> str:
        """
        Tool MCP `Nokido:biblio`.
        Actions : extract | search | list | promote | reject | pin | unpin | get.
        Delegue a app/forge_biblio_core.py et app/forge_biblio_worker.py.
        """
        import json as _json
        import sys as _sys
        from pathlib import Path as _Path

        _app = _Path(__file__).resolve().parent
        if str(_app) not in _sys.path:
            _sys.path.insert(0, str(_app))

        action = (args.get("action") or "").lower()

        try:
            if action == "extract":
                # Extraction depuis un texte colle. Ne fait QUE l extraction
                # (pas l insert auto, car on veut que utilisateur valide).
                from nokido_agent.app.forge_biblio_core import extract_from_text, insert_biblio_raw

                text = args.get("text", "")
                idea_id = args.get("idea_id", "")
                if not text or not idea_id:
                    return "ERR: extract requiert text + idea_id"
                sources = extract_from_text(text, idea_id, agent=agent)
                # Insert chaque source en biblio_raw (status unverified ou rejected)
                results = []
                for s in sources:
                    r = insert_biblio_raw(s)
                    results.append(
                        {
                            "id": r.get("id"),
                            "status": r.get("status"),
                            "title": s.get("title"),
                            "rejection_reason": r.get("rejection_reason"),
                        }
                    )
                return _json.dumps(
                    {"ok": True, "extracted": len(sources), "entries": results}, ensure_ascii=False, indent=2
                )

            elif action == "list":
                from nokido_agent.app.forge_biblio_core import list_entries

                entries = list_entries(
                    status_filter=args.get("status_filter"),
                    limit=int(args.get("limit", 20)),
                )
                return _json.dumps({"ok": True, "n": len(entries), "entries": entries}, ensure_ascii=False, indent=2)

            elif action == "get":
                from nokido_agent.app.forge_biblio_core import get_entry

                entry_id = args.get("entry_id", "")
                if not entry_id:
                    return "ERR: get requiert entry_id"
                e = get_entry(entry_id)
                if not e:
                    return _json.dumps({"ok": False, "reason": "not_found"})
                return _json.dumps({"ok": True, "entry": e}, ensure_ascii=False, indent=2)

            elif action == "promote":
                if ring > 1:
                    return f"SECURITY: promote requiert ring<=1 (votre ring={ring})"
                from nokido_agent.app.forge_biblio_core import promote_entry

                entry_id = args.get("entry_id", "")
                if not entry_id:
                    return "ERR: promote requiert entry_id"
                r = promote_entry(entry_id, promoted_by=agent)
                return _json.dumps(r, ensure_ascii=False, indent=2)

            elif action == "reject":
                from nokido_agent.app.forge_biblio_core import reject_entry

                entry_id = args.get("entry_id", "")
                reason = args.get("reason", "manual_reject")
                if not entry_id:
                    return "ERR: reject requiert entry_id"
                r = reject_entry(entry_id, reason)
                return _json.dumps(r, ensure_ascii=False, indent=2)

            elif action in ("pin", "unpin"):
                # Pin pas encore en schema alpha. Reporte beta.
                return "NOTE: pin/unpin reporte en beta (pas de colonne pinned dans schema alpha)"

            elif action == "search":
                # Forcer search sur 1 entry queued (utile pour test). Cycle worker.
                from nokido_agent.app.forge_biblio_worker import process_one_entry
                from nokido_agent.app.forge_biblio_core import get_entry
                import sqlite3 as _sq
                from nokido_agent.app.forge_biblio_core import DEFAULT_DB_PATH

                entry_id = args.get("entry_id")
                if not entry_id:
                    return "ERR: search requiert entry_id"
                entry = get_entry(entry_id)
                if not entry:
                    return _json.dumps({"ok": False, "reason": "not_found"})
                # Mettre a jour status -> queued si pas deja
                conn = _sq.connect(DEFAULT_DB_PATH)
                try:
                    conn.execute("UPDATE biblio_raw SET status='queued' WHERE id=?", (entry_id,))
                    conn.commit()
                    entry["status"] = "queued"
                    res = process_one_entry(conn, entry)
                finally:
                    conn.close()
                return _json.dumps(res, ensure_ascii=False, indent=2)

            else:
                return f"ERR: action inconnue '{action}'. Valides: extract|list|get|promote|reject|search|pin|unpin"

        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"

    #: L'echelle DECLAREE des rings (forge_integrity). Une valeur hors de
    #: cette echelle n'est pas une autorite, c'est du bruit.
    _RINGS_LEGAUX = (-1, 0, 1, 2, 3, 4)
    _RING_LE_MOINS_PRIVILEGIE = 4

    @staticmethod
    def _ring_delegant(valeur) -> int:
        """Convertit l'autorite STOCKEE d'un delegant en ring exploitable.

        UNE SEULE regle, a un seul endroit : sans elle chaque lecteur inventera
        la sienne, et c'est la plus permissive qui gagnera.

        `from_ring` est NULL sur toute ligne anterieure au 2026-09-12, et le
        restera pour tout producteur qui ne le renseigne pas. Lire ce NULL
        comme `0` donnerait MASTER a ces lignes — la conversion la plus
        naturelle en Python (`int(x or 0)`) est justement celle-la. D'ou cette
        fonction, et non un `or 0` disperse.

        Absent, illisible, ou hors de l'echelle declaree => le ring le MOINS
        privilegie. « UNKNOWN n'est pas NO », applique dans le seul sens qui ne
        fabrique pas de privilege.
        Fige par tests/test_delegation_porte_l_autorite.py
        """
        # `int(valeur)` seul ne suffit PAS — mesure du 2026-09-12, sur cette
        # fonction meme, dix minutes apres son ecriture :
        #   int(3.7)  -> 3   : une valeur fractionnaire devient un ring legal
        #   int(-0.5) -> 0   : et celle-la devient SYSTEM
        #   int(inf)  -> OverflowError : la conversion n'est plus TOTALE, donc
        #                chaque lecteur ajoutera son propre except et son
        #                propre defaut, et le plus permissif gagnera.
        # La troncature INVENTE une autorite a partir de quelque chose qui n'en
        # est pas une. On n'accepte donc qu'un ENTIER EXACT, ou une chaine qui
        # en est un — jamais un flottant, jamais un booleen.
        if isinstance(valeur, bool):
            return ToolRegistry._RING_LE_MOINS_PRIVILEGIE
        if isinstance(valeur, int):
            r = valeur
        elif isinstance(valeur, str):
            try:
                r = int(valeur.strip())
            except ValueError:
                return ToolRegistry._RING_LE_MOINS_PRIVILEGIE
        else:
            return ToolRegistry._RING_LE_MOINS_PRIVILEGIE
        if r not in ToolRegistry._RINGS_LEGAUX:
            return ToolRegistry._RING_LE_MOINS_PRIVILEGIE
        return r

    def _task_db(self):
        import sqlite3 as _sq

        db_path = self.root / "sandbox" / "tasks.db"
        conn = _sq.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks "
            "(id TEXT PRIMARY KEY, description TEXT, agent TEXT, "
            "status TEXT DEFAULT 'pending', result TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        existing = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "job_id" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN job_id TEXT")
        if "from_agent" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN from_agent TEXT")
        if "from_ring" not in existing:
            # `from_agent` porte le NOM du delegant ; un nom est une
            # DECLARATION, pas une autorite (c'est la raison du plancher
            # anti-spoof a ring 4 sur les identites d'en-tete). Sans cette
            # colonne, l'autorite du parent n'existe nulle part au moment ou
            # l'enfant agit : `C ⊆ P` n'est pas seulement non verifie, il est
            # INVERIFIABLE. Migration additive, au meme patron que les deux
            # precedentes. Lecture par `_ring_delegant` UNIQUEMENT.
            conn.execute("ALTER TABLE tasks ADD COLUMN from_ring INTEGER")
        conn.commit()
        return conn

    async def handle_task_assign(self, args: dict, agent: str, ring: int) -> str:
        import json as _j, sqlite3 as _sq
        from datetime import datetime as _dt
        from nokido_agent.app.forge_jobid import generate_job_id, JobContext, persist_job
        from nokido_agent.app.forge_message_frame import make_task_frame, INBOX

        ag_raw = (args.get("agent") or "WORKER").upper()
        # Alias identite : AGY == ANTIGRAVITY (inbox canonique drainee agt_antigravity)
        if ag_raw in ("AGY", "ANTIGRAVITY"):
            ag_raw = "ANTIGRAVITY"
        to_agt = f"agt_{ag_raw.lower()}"
        from_agt = f"agt_{agent.lower()}" if not agent.startswith("agt_") else agent
        # Le schema du tool expose `task` ; ce handler ne lisait QUE `description`.
        # Un appel CONFORME au schema creait donc une tache au corps VIDE, en
        # silence (mesure 24-07 : job_d168f5c8, description len=0 -> AGY repond
        # « le message est vide ou absent dans la transmission », et la tache
        # revient quand meme OK_DONE). On accepte les trois noms rencontres, en
        # commencant par celui que le schema annonce.
        desc = (args.get("task") or args.get("description") or args.get("message") or "").strip()
        intent = args.get("intent", "task_assign")
        priority = int(args.get("priority", 5))

        # Inject file context: detect py file paths in description, prepend content
        if intent == "code" and desc:
            import re as _re

            # Matches: LaForge/app/foo.py  LaForge/tools/foo.py  app/foo.py  tools/foo.py
            _file_pat = _re.compile(r'(?:LaForge/)?((?:app|tools)/[^\s,\'"]+\.py)')
            _seen, _injected = set(), []
            for m in _file_pat.finditer(desc):
                rel = m.group(1)  # e.g. "app/forge_graph_linker.py"
                if rel in _seen:
                    continue
                _seen.add(rel)
                fp = self.root / rel
                if fp.exists():
                    try:
                        content = fp.read_text(encoding="utf-8", errors="replace")[:3500]
                        _injected.append(f"# FILE: {rel}\n```python\n{content}\n```")
                    except Exception:
                        pass
            if _injected:
                desc = "\n\n".join(_injected) + "\n\n---\n\n# TASK\n" + desc

        job_id = args.get("job_id") or generate_job_id(agent, intent)
        tid = args.get("task_id") or job_id
        now = _dt.now().isoformat()

        # 1. Persist task
        conn = self._task_db()
        conn.execute(
            # `from_ring` : l'AUTORITE du delegant, a cote de son NOM. Ecrite
            # ici parce qu'un champ sans producteur ne se distingue pas d'un
            # champ absent — le consommateur est `handle_task_claim`, qui la
            # restitue a l'agent qui prend la tache.
            # Normalisee par `_ring_delegant` DES l'ecriture : stocker une
            # valeur hors echelle reviendrait a deporter la decision sur
            # chaque lecteur.
            "INSERT OR REPLACE INTO tasks"
            "(id,description,agent,status,result,created_at,updated_at,job_id,"
            "from_agent,from_ring)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, desc, ag_raw, "pending", None, now, now, job_id, from_agt,
             self._ring_delegant(ring)),
        )
        conn.commit()
        conn.close()

        # 2. Persist JobContext (jobs_state — riche, queryable)
        ctx = JobContext(
            job_id=job_id,
            agent=ag_raw,
            intent_type=intent,
            payload={"task_id": tid, "description": desc, "from": from_agt},
            status="pending",
        )
        persist_job(ctx)

        # 3. Build MessageFrame (JWT-signé auto via __post_init__)
        frame = make_task_frame(
            to_agent=to_agt,
            action="task",
            parameters={"task_id": tid, "description": desc, "intent": intent},
            from_agent=from_agt,
            job_id=job_id,
            text=desc[:120],
            priority=priority,
            ring=ring,
        )

        # 4. Archive dans agent_messages (CQRS — immuable) — base M2M (interrupteur
        # sandbox/m2m.switch), plus la base du RAG.
        from nokido_agent.app.forge_db_path import open_m2m as _open_m2m
        conn2 = _open_m2m()
        conn2.execute(
            "INSERT OR IGNORE INTO agent_messages"
            "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (frame.frame_id, from_agt, to_agt, job_id, "task.assign", frame.to_json(), "unread", now),
        )
        conn2.commit()
        conn2.close()

        # 5. Push queue volatile (SSE wake-up immédiat)
        INBOX.push(frame)

        return _j.dumps(
            {
                "ok": True,
                "task_id": tid,
                "job_id": job_id,
                "agent": ag_raw,
                "frame_id": frame.frame_id,
            },
            ensure_ascii=False,
        )

    async def handle_task_claim(self, args: dict, agent: str, ring: int) -> str:
        import json as _j
        from datetime import datetime as _dt
        from nokido_agent.app.forge_jobid import load_job, persist_job

        ag_filter = (args.get("agent") or agent or "").upper().replace("AGT_", "")
        conn = self._task_db()
        if ag_filter:
            row = conn.execute(
                "SELECT id,description,agent,job_id,from_agent,from_ring FROM tasks"
                " WHERE status='pending' AND upper(agent)=?"
                " ORDER BY created_at LIMIT 1",
                (ag_filter,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id,description,agent,job_id,from_agent,from_ring FROM tasks"
                " WHERE status='pending' ORDER BY created_at LIMIT 1"
            ).fetchone()

        if not row:
            conn.close()
            return _j.dumps({"ok": False, "reason": "no_pending_task", "agent": ag_filter})

        tid, desc, ag, job_id, from_ag, from_rg = row
        # Toute ligne anterieure au 2026-09-12 a `from_ring` NULL. La lire par
        # `_ring_delegant` la ramene au ring le MOINS privilegie — jamais 0,
        # qui serait MASTER.
        from_rg = self._ring_delegant(from_rg)
        now = _dt.now().isoformat()
        conn.execute("UPDATE tasks SET status='claimed',updated_at=? WHERE id=?", (now, tid))
        conn.commit()
        conn.close()

        if job_id:
            ctx = load_job(job_id)
            if ctx:
                ctx.mark_running()
                persist_job(ctx)

        return _j.dumps(
            {
                "ok": True,
                "task_id": tid,
                "job_id": job_id or tid,
                "description": desc,
                "agent": ag,
                "from_agent": from_ag,
                # L'autorite du delegant est RESTITUEE au preneur. Elle ne le
                # CONTRAINT pas : l'enfant agit toujours avec son propre ring.
                # Transporter n'est pas attenuer, et le nom du champ le dit.
                "from_ring": from_rg,
                "attenuation": ("NON_APPLIQUEE — l'autorite du delegant est "
                                "transportee, pas imposee ; le preneur agit "
                                "avec son propre ring"),
            },
            ensure_ascii=False,
        )

    async def handle_task_result(self, args: dict, agent: str, ring: int) -> str:
        import json as _j, sqlite3 as _sq, hashlib as _hl
        from datetime import datetime as _dt
        from nokido_agent.app.forge_jobid import load_job, persist_job

        tid = args.get("task_id", "")
        result_text = (args.get("result", "") or "")[:2000]
        now = _dt.now().isoformat()

        # Sprint 3 M2M : validation du result (warn par defaut ; error = refus).
        try:
            from nokido_agent.app.forge_m2m_protocol import check as _m2m_check
            _m2m_ok, _m2m_v = _m2m_check("task_result", result_text)
            if not _m2m_ok:
                return _j.dumps({"ok": False, "error": "M2M_REFUSED", "code": _m2m_v.get("code"),
                                 "violations": _m2m_v.get("violations")}, ensure_ascii=False)
        except Exception:
            pass

        # Separation of Powers: check that the validator/creator is not the task worker
        try:
            from nokido_agent.app.forge_separation import enforce_separation
            ok, reason = enforce_separation(agent, "task.result", tid)
            if not ok:
                return f"SECURITY: Separation of powers violation: {reason}"
        except Exception as e:
            return f"SECURITY: Separation of powers check error: {e}"

        # Quality gate on Python code blocks in result (non-blocking, warn only)
        _qg_errs: list = []
        try:
            from nokido_agent.app.forge_quality_gate import gate_check_result as _gqr

            _qg_errs = _gqr(tid, result_text) or []
            if _qg_errs:
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning("[quality_gate] task=%s errors=%s", tid, _qg_errs[:3])
        except Exception:
            pass

        # Scorecard : enrobe le quality_gate dans le contrat unifie
        # (forge_scorecard.Scorecard). Persiste dans tasks.scorecard_json via
        # ALTER TABLE soft. Le LLM-judge n'est PAS lance ici (couteux) - le
        # grade reflete UNIQUEMENT la passe deterministe ; l'agent suivant
        # ou un job batch peut le re-evaluer plus tard avec contexte complet.
        try:
            from nokido_agent.app.forge_scorecard import scorecard_de_resultat, store_for_task

            # 2026-09-24 (veille lot_B_33) : le scorecard etait FABRIQUE ici en dur,
            # toujours COMPLETED, et OPTIMAL 1.0 des que le gate ne rendait rien — or le
            # gate n'inspecte que les blocs de code : une tache ECHOUEE (ERR_INTERNAL,
            # refus de verrou) sortait OPTIMAL. Le verdict vient desormais du module
            # juge (patch pose par l'owner, separation des pouvoirs) : le registre
            # n'invente plus de note.
            _sc = scorecard_de_resultat(result_text, _qg_errs)
            # store_for_task gere ALTER TABLE + UPDATE scorecard_json
            # Path explicite : tasks.db sous sandbox/, pas RAG/embeddings.db.
            store_for_task(_sc, tid, db_path=str(self.root / "sandbox" / "tasks.db"))
        except Exception as _e:
            import logging as _lg

            _lg.getLogger("Nokido.Registry").debug("[scorecard] task=%s skipped: %s", tid, _e)

        # Dep manager: extract Python blocks, check + install missing imports
        try:
            import re as _re, tempfile as _tf, os as _os
            from nokido_agent.app.forge_dep_manager import manage as _dep_manage

            _py_blocks = _re.findall(r"```python\n(.*?)```", result_text, _re.DOTALL)
            if _py_blocks:
                with _tf.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as _tmp:
                    _tmp.write("\n".join(_py_blocks))
                    _tmp_path = _tmp.name
                try:
                    _dep_result = _dep_manage(_tmp_path, dry_run=False)
                    if _dep_result.get("installed"):
                        import logging as _lg

                        _lg.getLogger("Nokido.Registry").info(
                            "[dep_manager] task=%s installed=%s", tid, _dep_result["installed"]
                        )
                finally:
                    _os.unlink(_tmp_path)
        except Exception:
            pass

        conn = self._task_db()
        row = conn.execute(
            "SELECT job_id,from_agent,description,result FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        # NE PAS ECRASER UN RESULTAT PLUS RICHE PAR L'ENVELOPPE M2M.
        # Mesure 2026-07-26 : l'executor ecrit d'abord la reponse complete de
        # l'agent (jusqu'a 8000 chars), PUIS emet son accuse M2M -- dont le champ
        # `detail` est volontairement court (180 chars). Cet UPDATE ecrasait la
        # reponse par l'accuse : 1555 caracteres d'avis reduits a 313, coupes en
        # pleine phrase, recuperables seulement dans le postal.
        # L'enveloppe est un ACCUSE DE RECEPTION, pas le livrable : elle part de
        # toute facon a l'emetteur (notification plus bas) et dans agent_messages.
        _prev = (row[3] if row and len(row) > 3 else "") or ""
        _keep = result_text if len(result_text or "") >= len(_prev) else _prev
        # UN REFUS DU MODELE N'EST PAS UN TRAVAIL FAIT.
        # Mesure 2026-09-18 : une revue de code deleguee est revenue en « Sorry, I
        # cannot fulfill your request » (377 caracteres) et a ete enregistree
        # `done`. Le garde-fou du MODELE servi comme LIVRABLE, et un faux vert au
        # bout de la chaine de delegation — celui qui lit `done` croit la tache
        # faite. On reutilise `failed`, un statut que les lecteurs traitent deja,
        # plutot que d'en inventer un qu'aucun d'eux ne connait.
        _statut = "done"
        try:
            from nokido_agent.tools.forge_task_executor import est_refus_du_modele as _erm

            _motif_refus = _erm(_keep)
        except Exception as _e_refus:  # noqa: BLE001
            _motif_refus = None
            logger.debug("[task] detection de refus indisponible: %s", type(_e_refus).__name__)
        if _motif_refus:
            _statut = "failed"
            _keep = (f"[REFUS DU MODELE — formule reconnue : {_motif_refus!r}. La tache n'a "
                     f"PAS ete faite ; c'est la formulation qu'il faut reprendre, pas un bug "
                     f"a chercher.] {_keep}")
            logger.warning("[task] %s REFUSEE par le modele (%r) — statut failed, pas done",
                           str(tid)[:24], _motif_refus)

        # UN ACCUSE DE RECEPTION N'EST PAS UN LIVRABLE.
        # Mesure 2026-09-19 : un audit delegue est revenu en "I am running the
        # AST scanner in the background... I will write the requested report once
        # the scan is complete" et a ete enregistre `done` / SUCCESS. Le
        # detecteur `_est_accuse_reception` EXISTE et reconnait correctement
        # cette formulation -- il n'avait qu'UN consommateur,
        # `forge_task_executor`, dont le chemin ecrit `completed` et que ces
        # taches-ci n'empruntent pas. Le garde tenait une porte, pas l'autre :
        # quatrieme occurrence du meme motif dans la journee.
        #
        # `failed` plutot qu'un statut neuf, pour la meme raison qu'au-dessus :
        # les lecteurs le traitent deja. Et c'est AUTO-CORRIGEANT -- si l'agent
        # livre vraiment ensuite, la mise a jour suivante repassera a `done`.
        if _statut == "done":
            try:
                from nokido_agent.tools.forge_task_executor import (
                    _est_accuse_reception as _eac,
                )

                _est_accuse = bool(_eac(_keep))
            except Exception as _e_acc:  # noqa: BLE001
                _est_accuse = False
                logger.debug("[task] detection d'accuse indisponible: %s", type(_e_acc).__name__)
            if _est_accuse:
                _statut = "failed"
                _keep = ("[ACCUSE DE RECEPTION, PAS UN LIVRABLE -- l'agent annonce "
                         "qu'il va faire le travail. La tache n'est PAS faite : "
                         "attendre le rapport, ou la relancer.] " + str(_keep))
                logger.warning("[task] %s a rendu un ACCUSE et non un livrable "
                               "-- statut failed, pas done", str(tid)[:24])

        conn.execute("UPDATE tasks SET status=?,result=?,updated_at=? WHERE id=?",
                     (_statut, _keep, now, tid))
        conn.commit()
        conn.close()

        job_id = row[0] if row else tid
        from_ag = row[1] if row else ""
        desc = row[2] if row else ""

        # Update JobContext
        ctx = load_job(job_id) if job_id else None
        if ctx:
            ctx.mark_completed(result_text[:200])
            persist_job(ctx)

        # Notifier l'émetteur
        if from_ag:
            from nokido_agent.app.forge_db_path import open_m2m as _open_m2m   # scission M2M : la reponse part dans la base M2M
            reply_id = "frm_" + _hl.md5(f"reply_{tid}{now}".encode()).hexdigest()[:12]
            from_self = f"agt_{agent.lower()}" if not agent.startswith("agt_") else agent
            conn2 = _open_m2m()
            conn2.execute(
                "INSERT OR IGNORE INTO agent_messages"
                "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    reply_id,
                    from_self,
                    from_ag,
                    job_id,
                    "task.result",
                    _j.dumps(
                        {"task_id": tid, "job_id": job_id, "result": result_text, "description": desc},
                        ensure_ascii=False,
                    ),
                    "unread",
                    now,
                ),
            )
            conn2.commit()
            conn2.close()

        # Index vectoriel dans rag_chunks (cherchable sémantiquement)
        try:
            rag_db = self.root / "RAG" / "embeddings.db"
            conn3 = _sq.connect(str(rag_db))
            chunk_id = f"task_result_{tid}"
            chunk_text = f"[TASK RESULT] job={job_id} task={tid}\ndesc: {desc}\nresult: {result_text}"
            conn3.execute(
                "INSERT OR REPLACE INTO rag_chunks(id,text,source,domain,role_hint,ingested_at) VALUES(?,?,?,?,?,?)",
                (chunk_id, chunk_text, f"tasks/{tid}", "collab", "task_result", now),
            )
            conn3.execute(
                # `chunk_id` et `domain` manquaient : la ligne arrivait avec une cle
                # NULL, donc introuvable par jointure et invisible aux purges ciblees.
                "INSERT OR REPLACE INTO rag_fts(rowid,chunk_id,text,source,domain) "
                "SELECT rowid,id,text,source,domain FROM rag_chunks WHERE id=?",
                (chunk_id,),
            )
            conn3.commit()
            conn3.close()
        except Exception:
            pass

        return _j.dumps(
            {
                "ok": True,
                "task_id": tid,
                "job_id": job_id or tid,
                "status": "done",
            },
            ensure_ascii=False,
        )

    # -- HANDLERS : EventBus (docs/EVENT_SPEC.md) --

    async def handle_event_publish(self, args: dict, agent: str, ring: int) -> str:
        if not hasattr(self, "_event_bus"):
            from nokido_agent.app.forge_state_manager import EventBus

            self._event_bus = EventBus(self.state_mgr)
        res = self._event_bus.publish(
            topic=args.get("topic", ""),
            kind=args.get("kind", "msg"),
            data=args.get("data", {}),
            agent=agent,
            trusted=True,
        )
        return f"OK published {res}"

    async def handle_event_history(self, args: dict, agent: str, ring: int) -> str:
        if not hasattr(self, "_event_bus"):
            from nokido_agent.app.forge_state_manager import EventBus

            self._event_bus = EventBus(self.state_mgr)
        events = self._event_bus.history(topics=args.get("topics", ["*"]), limit=int(args.get("limit", 50)))
        return json.dumps(events, indent=2, ensure_ascii=False)

    async def handle_memory(self, args: dict, agent: str, ring: int) -> str:
        """
        Accès lecture à la mémoire et l intelligence de Nokido.

        Point d entrée unique pour onboarder un agent collaborateur.
        Droits :
          Ring 0 : toutes les actions
          Ring 1 : context, rules, adr, search, tasks, providers
          Ring 2 : context, search uniquement

        Actions :
          context      : briefing projet (ADR + rules + sprint + agents actifs)
          rules        : system_rules (filtre par tag optionnel)
          adr          : adr_records (filtre par status optionnel)
          instructions : system prompts agents dans instruction_library
          providers    : état des providers LLM + scores qualité
          tasks        : tâches agents récentes
          search       : recherche sémantique dans rag_chunks (FTS)
          status       : état système (inspector + network_log récent)
        """
        import sqlite3, json as _json

        action = args.get("action", "context")

        # Contrôle d accès par action
        ring1_allowed = {"context", "rules", "adr", "search", "tasks", "providers"}
        ring2_allowed = {"context", "search"}

        if ring >= 2 and action not in ring2_allowed:
            return _json.dumps({"error": f"Ring {ring} : action '{action}' réservée Ring <= 1"})
        if ring >= 1 and action not in ring1_allowed:
            return _json.dumps({"error": f"Ring {ring} : action '{action}' réservée Ring 0"})

        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row

        try:
            # ACTION : context (briefing agent - 1 appel pour tout comprendre)
            if action == "context":
                # Sprint actif depuis system_rules tag=sprint
                sprint_rows = conn.execute(
                    "SELECT content FROM system_rules WHERE tag LIKE '%sprint%' OR tag LIKE '%biblio%' LIMIT 3"
                ).fetchall()
                sprint = sprint_rows[0]["content"][:200] if sprint_rows else "Aucun sprint actif trouvé"

                # ADR récents
                adr_rows = conn.execute(
                    "SELECT adr_id, title, status FROM adr_records ORDER BY id DESC LIMIT 5"
                ).fetchall()

                # Providers UP
                prov_rows = conn.execute(
                    "SELECT provider_id, quality_tier, last_status FROM provider_scores WHERE last_status='ok' ORDER BY calls_total DESC"
                ).fetchall()

                # Agents actifs (heartbeats récents)
                fleet = conn.execute(
                    "SELECT agent_id, status FROM fleet_heartbeats ORDER BY last_seen DESC LIMIT 5"
                ).fetchall()

                # Stats mémoire
                n_rag = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
                n_adr = conn.execute("SELECT COUNT(*) FROM adr_records").fetchone()[0]
                n_rules = conn.execute("SELECT COUNT(*) FROM system_rules").fetchone()[0]
                n_tasks = conn.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0]

                # Rules critiques (top 3)
                rules = conn.execute("SELECT content FROM system_rules ORDER BY id DESC LIMIT 3").fetchall()

                context = {
                    "project": "Nokido Sovereign Hub v18.5",
                    "owner": "user",
                    "hub_url": "http://127.0.0.1:8766/mcp",
                    "active_sprint": sprint[:200],
                    "recent_adr": [{"id": r["adr_id"], "title": r["title"], "status": r["status"]} for r in adr_rows],
                    "key_rules": [r["content"][:150] for r in rules],
                    "providers_up": [r["provider_id"] for r in prov_rows],
                    "active_agents": [{"id": r["agent_id"], "status": r["status"]} for r in fleet],
                    "memory_stats": {
                        "rag_chunks": n_rag,
                        "adr_records": n_adr,
                        "system_rules": n_rules,
                        "agent_tasks": n_tasks,
                    },
                    "tools_available": [
                        "memory(context|rules|adr|search|tasks|providers)",
                        "rag(search|index)",
                        "query(sql)",
                        "read(file|tail_logs)",
                        "hub(notify|poll|get_mode)",
                        "task(assign|claim|result|status)",
                        "event(publish|history)",
                    ],
                }
                return _json.dumps(context, ensure_ascii=False, indent=2)

            # ACTION : rules
            elif action == "rules":
                tag = args.get("tag")
                limit = min(int(args.get("limit", 20)), 50)
                if tag:
                    rows = conn.execute(
                        "SELECT id, tag, content FROM system_rules WHERE tag=? LIMIT ?", (tag, limit)
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT id, tag, content FROM system_rules LIMIT ?", (limit,)).fetchall()
                return _json.dumps(
                    [{"id": r["id"], "tag": r["tag"], "content": r["content"]} for r in rows],
                    ensure_ascii=False,
                    indent=2,
                )

            # ACTION : adr
            elif action == "adr":
                status_filter = args.get("status")
                limit = min(int(args.get("limit", 20)), 50)
                if status_filter:
                    rows = conn.execute(
                        "SELECT adr_id, title, status, decision, consequences_pos, consequences_neg, tags "
                        "FROM adr_records WHERE status=? ORDER BY id DESC LIMIT ?",
                        (status_filter, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT adr_id, title, status, decision, consequences_pos, tags "
                        "FROM adr_records ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)

            # ACTION : instructions (system prompts agents)
            elif action == "instructions":
                agent_id = args.get("agent_id")
                if agent_id:
                    row = conn.execute("SELECT * FROM instruction_library WHERE id=?", (agent_id,)).fetchone()
                    return _json.dumps(dict(row) if row else {}, ensure_ascii=False, indent=2)
                else:
                    rows = conn.execute("SELECT id, name, version FROM instruction_library").fetchall()
                    return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)

            # ACTION : providers
            elif action == "providers":
                prov = conn.execute(
                    "SELECT provider_id, agent_id, calls_total, quality_tier, last_status "
                    "FROM provider_scores ORDER BY calls_total DESC"
                ).fetchall()
                fleet = conn.execute("SELECT agent_id, role, status, last_seen FROM fleet_heartbeats").fetchall()
                return _json.dumps(
                    {
                        "providers": [dict(r) for r in prov],
                        "fleet": [dict(r) for r in fleet],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            # ACTION : tasks
            elif action == "tasks":
                limit = min(int(args.get("limit", 10)), 30)
                status = args.get("status")
                if status:
                    rows = conn.execute(
                        "SELECT task_id, agent_id, description, status, created_at FROM agent_tasks "
                        "WHERE status=? ORDER BY created_at DESC LIMIT ?",
                        (status, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT task_id, agent_id, description, status, created_at FROM agent_tasks "
                        "ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)

            # ACTION : search (FTS dans rag_chunks)
            elif action == "search":
                query = args.get("query", "")
                limit = min(int(args.get("limit", 10)), 30)
                domain = args.get("domain")
                if not query:
                    return _json.dumps({"error": "query obligatoire"})
                # FTS search
                try:
                    if domain:
                        rows = conn.execute(
                            """SELECT rc.id, rc.source, rc.domain, rc.content
                               FROM rag_chunks rc
                               JOIN rag_chunks_fts fts ON rc.id = fts.rowid
                               WHERE rag_chunks_fts MATCH ? AND rc.domain=?
                               ORDER BY rank LIMIT ?""",
                            (query, domain, limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """SELECT rc.id, rc.source, rc.domain, rc.content
                               FROM rag_chunks rc
                               JOIN rag_chunks_fts fts ON rc.id = fts.rowid
                               WHERE rag_chunks_fts MATCH ?
                               ORDER BY rank LIMIT ?""",
                            (query, limit),
                        ).fetchall()
                    results = [
                        {"id": r["id"], "source": r["source"], "domain": r["domain"], "content": r["content"][:500]}
                        for r in rows
                    ]
                except Exception as e:
                    # Fallback LIKE
                    rows = conn.execute(
                        "SELECT id, source, domain, content FROM rag_chunks WHERE content LIKE ? LIMIT ?",
                        (f"%{query}%", limit),
                    ).fetchall()
                    results = [
                        {"id": r["id"], "source": r["source"], "domain": r["domain"], "content": r["content"][:500]}
                        for r in rows
                    ]
                return _json.dumps(
                    {"query": query, "results": results, "count": len(results)}, ensure_ascii=False, indent=2
                )

            # ACTION : status (Ring 0 only)
            elif action == "status":
                # `inspector_log` suit `sandbox/journaux.switch` ; `network_log`
                # ci-dessous reste dans la base du RAG. Sans ce helper, la meme
                # connexion servirait aux deux et cette route rendrait, apres
                # bascule, un journal FIGE presente comme l'etat courant.
                # Ecriture MINIMALE : ce fichier est un CRITICAL_FILE de 9 241
                # lignes dont l'edition gouvernee a fait tomber le hub le
                # 2026-09-22 ; la logique vit dans `forge_db_path`.
                # Autorisation owner explicite (`allow_critical`), tracee.
                from nokido_agent.app.forge_db_path import lecteur_journal as _lj
                with _lj("inspector_log", conn, str(self.db_path)) as _ci:
                    inspector = _ci.execute(
                        "SELECT created_at, level, payload FROM inspector_log "
                        "ORDER BY id DESC LIMIT 5"
                    ).fetchall()
                network = conn.execute(
                    "SELECT ts, channel, agent, tool, status FROM network_log ORDER BY id DESC LIMIT 10"
                ).fetchall()
                return _json.dumps(
                    {
                        "inspector_recent": [dict(r) for r in inspector],
                        "network_recent": [dict(r) for r in network],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            else:
                return _json.dumps({"error": f"action inconnue: {action}"})

        finally:
            conn.close()

    async def handle_event_fetch_archived(self, args: dict, agent: str, ring: int) -> str:
        """
        Recupere le contenu COMPLET d un message archive par _archive_long_args.

        Args attendus :
            msg_id (str) : id retourne dans args_preview._archived_msg_id

        Returns:
            JSON {"id": ..., "tool": ..., "arg_key": ..., "text": "<full content>", "from_agent": ..., "created_at": ...}
            OU {"ok": false, "error": "not_found"}
        """
        import sqlite3, json as _json

        msg_id = args.get("msg_id", "").strip()
        if not msg_id:
            return _json.dumps({"ok": False, "error": "msg_id obligatoire"})
        if not msg_id.startswith("evtmsg_"):
            return _json.dumps({"ok": False, "error": "format msg_id invalide (doit commencer par evtmsg_)"})
        try:
            from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M
            conn = sqlite3.connect(_m2m_path(), timeout=3)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, from_agent, method, payload, created_at "
                "FROM agent_messages WHERE id=? AND to_agent='EVENTBUS_ARCHIVE'",
                (msg_id,),
            ).fetchone()
            conn.close()
            if not row:
                return _json.dumps({"ok": False, "error": "not_found", "msg_id": msg_id})
            payload = _json.loads(row["payload"])
            return _json.dumps(
                {
                    "ok": True,
                    "id": row["id"],
                    "from_agent": row["from_agent"],
                    "method": row["method"],
                    "tool": payload.get("tool"),
                    "arg_key": payload.get("arg_key"),
                    "text": payload.get("text"),
                    "created_at": row["created_at"],
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return _json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})

    async def handle_read_function_body(self, args: dict, agent: str, ring: int) -> str:
        """Extrait le corps complet d'une fonction/classe via AST. Single Source of Truth pour zoom SWE."""
        import ast as _ast, os as _os

        file_path = args.get("file_path", "")
        func_name = args.get("function_name", "")
        if not file_path or not func_name:
            return "ERR: file_path et function_name requis"
        root = _os.path.dirname(_os.path.dirname(__file__))
        abs_path = file_path if _os.path.isabs(file_path) else _os.path.join(root, file_path)
        if not _os.path.exists(abs_path):
            return f"ERR: fichier introuvable: {file_path}"
        try:
            source = open(abs_path, encoding="utf-8", errors="replace").read()
            tree = _ast.parse(source)
        except SyntaxError as e:
            return f"ERR: SyntaxError dans {file_path}: {e}"
        src_lines = source.splitlines(keepends=True)
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                if node.name == func_name:
                    start = node.lineno - 1
                    end = getattr(node, "end_lineno", node.lineno)
                    body = "".join(src_lines[start:end])
                    return f"### {file_path} — {func_name} (L{node.lineno}–L{end})\n```python\n{body.rstrip()}\n```"
        return f"ERR: '{func_name}' non trouvé dans {file_path}"

    async def handle_forge_stats(self, args: dict, agent: str, ring: int) -> str:
        """Observabilité : cache de plans GOAP + sentinelle lag event-loop + ressources."""
        import json as _j

        out: dict = {}
        try:
            from nokido_agent.app.forge_goap import plan_cache_stats

            out["plan_cache"] = plan_cache_stats()
        except Exception as e:
            out["plan_cache"] = f"err: {type(e).__name__}: {e}"
        try:
            from nokido_agent.app.forge_loop_sentinel import stats as _ls

            out["loop_sentinel"] = _ls()
        except Exception as e:
            out["loop_sentinel"] = f"err: {type(e).__name__}: {e}"
        try:
            from nokido_agent.app.forge_resource_manager import get_snapshot

            s = get_snapshot()
            out["resources"] = {k: s.get(k) for k in ("ram_pct", "cpu_pct", "gpu_pct")}
        except Exception as e:
            out["resources"] = f"err: {type(e).__name__}: {e}"
        return _j.dumps(out, ensure_ascii=False)

    async def handle_get_file_skeleton(self, args: dict, agent: str, ring: int) -> str:
        """Squelette AST d'un fichier (imports+signatures, corps='...') via forge_repo_map."""
        import os as _os, asyncio as _aio
        try:
            from nokido_agent.app.forge_repo_map import file_skeleton as _fs
        except Exception:
            from app.forge_repo_map import file_skeleton as _fs
        path = args.get("file_path") or args.get("path") or ""
        if not path:
            return "ERR: file_path requis"
        root = _os.path.dirname(_os.path.dirname(__file__))
        try:
            sk = await _aio.to_thread(_fs, path, root)
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"
        if not sk:
            return f"ERR: skeleton vide (fichier introuvable ou SyntaxError): {path}"
        return f"### SKELETON {path}\n```python\n{sk}\n```"

    async def handle_get_function_dependencies(self, args: dict, agent: str, ring: int) -> str:
        """Callers+callees fonction-level (impact d'une modif) via forge_callgraph_jit."""
        import json as _json, asyncio as _aio
        try:
            from nokido_agent.app.forge_callgraph_jit import get_function_dependencies as _gfd
        except Exception:
            from app.forge_callgraph_jit import get_function_dependencies as _gfd
        func = args.get("function_name") or args.get("func") or ""
        fpath = args.get("file_path") or ""
        if not func:
            return "ERR: function_name requis"
        try:
            res = await _aio.to_thread(_gfd, func, fpath)
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"
        return _json.dumps(res, ensure_ascii=False)

    async def handle_introspect(self, args: dict, agent: str, ring: int) -> str:
        """Point d'entree unique vers les organes d'introspection.

        POURQUOI (mesure 2026-08-31). Nokido porte 21 organes d'introspection et
        17 ont un consommateur : ils sont cables. Mais aucun point d'entree
        commun n'existait, et les verbes d'introspection pesaient 70 appels sur
        16 447 resultats d'outils - 0,4 %. Une capacite qu'il faut savoir NOMMER
        pour l'atteindre n'est pas atteinte.
        """
        import asyncio as _aio
        import json as _json
        try:
            from nokido_agent.app.forge_introspect import introspect as _intro
        except Exception:  # noqa: BLE001
            from app.forge_introspect import introspect as _intro
        q = args.get("query") or args.get("question") or ""
        if not q:
            return "ERR: query requis"
        budget = int(args.get("budget_tokens") or 2000)
        try:
            res = await _aio.to_thread(_intro, q, budget)
        except Exception as e:  # noqa: BLE001
            return f"ERR: {type(e).__name__}: {e}"
        try:
            from nokido_agent.app.forge_introspect import noter_consultation as _noter

            _noter(agent, q, res)
        except Exception:  # noqa: BLE001 - muet-ok : la trace ne casse jamais l'appel
            pass
        return _json.dumps(res, ensure_ascii=False)

    async def handle_blackboard_read_zone(self, args: dict, agent: str, ring: int) -> str:
        """Lit une zone du tableau noir swarm (forge_swarm_blackboard)."""
        import json as _json
        try:
            from nokido_agent.app.forge_swarm_blackboard import read_zone as _rz
        except Exception:
            from app.forge_swarm_blackboard import read_zone as _rz
        zone = args.get("zone_name") or args.get("zone") or ""
        if not zone:
            return "ERR: zone_name requis"
        flt = args.get("filter") or {}
        try:
            rows = _rz(
                zone,
                category=flt.get("category"),
                min_trust=flt.get("min_trust"),
                limit=int(flt.get("limit", 200)),
            )
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"
        return _json.dumps({"zone": zone, "count": len(rows), "facts": rows}, ensure_ascii=False)

    async def handle_blackboard_propose_fact(self, args: dict, agent: str, ring: int) -> str:
        """Propose un fait dans le tableau noir swarm (write-funnel mono-writer + ACL ring)."""
        import json as _json
        try:
            from nokido_agent.app.forge_swarm_blackboard import apply_fact as _af
        except Exception:
            from app.forge_swarm_blackboard import apply_fact as _af
        zone = args.get("zone_name") or args.get("zone") or ""
        fact = args.get("fact") or ""
        if not zone or not fact:
            return "ERR: zone_name et fact requis"
        try:
            res = await _af(
                zone,
                fact,
                category=args.get("category", ""),
                trust=float(args.get("trust", 0.5)),
                key=args.get("key"),
                source=args.get("source") or agent,
                ring=ring,
            )
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"
        if res.get("error"):
            return "ERR: " + res["error"]
        return _json.dumps(res, ensure_ascii=False)

    async def handle_auto_test(self, args: dict, agent: str, ring: int) -> str:
        """AST py_compile uniquement. Vectorisation = forge_post_commit.py au git commit."""
        import py_compile, os as _os, time as _t

        filepath = args.get("filepath", "")
        if not filepath:
            return "ERR: parametre filepath requis"
        root = _os.path.dirname(_os.path.dirname(__file__))
        abs_path = filepath if _os.path.isabs(filepath) else _os.path.join(root, filepath)
        if not _os.path.exists(abs_path):
            return f"ERR: fichier introuvable: {filepath}"
        if not abs_path.endswith(".py"):
            return f"OK auto_test (non-Python): {filepath}"
        t0 = _t.monotonic()
        try:
            py_compile.compile(abs_path, doraise=True)
        except py_compile.PyCompileError as e:
            return f"AST FAIL: {e}"
        ms = round((_t.monotonic() - t0) * 1000, 1)
        return f"OK auto_test {ms}ms | ast=OK | {filepath}"

    async def handle_ask(self, args: dict, agent: str, ring: int) -> str:
        message = args.get("message", args.get("prompt", ""))
        try:
            from nokido_agent.app.forge_clarification import clarify_or_proceed as _clarify

            _r = _clarify(message)
            if _r["needs_clarif"]:
                return _r["clarification_q"]
        except Exception:
            pass
        provider = args.get("provider", "gemini")
        if provider in ("claude",):
            return await self.handle_ask_claude(args, agent, ring)
        if provider in ("gemini",):
            return await self.handle_ask_gemini(args, agent, ring)
        return await self.handle_ask_agent(args, agent, ring)

    async def handle_list_providers(self, args: dict, agent: str, ring: int) -> str:
        """Liste les providers LLM disponibles avec leur statut."""
        import json as _j

        try:
            from nokido_agent.app.forge_llm_router import router_status

            # deporte hors event-loop : router_status interroge le coffre pour chaque
            # slot (RCA hub mort 2026-08-16 -- 60 s de gel puis os._exit). Le cache de
            # forge_key_rotation rend le cas normal quasi gratuit ; ce to_thread borne
            # le cas ANORMAL, celui ou le coffre traine.
            return _j.dumps(await asyncio.to_thread(router_status), ensure_ascii=False, indent=2)
        except Exception as e:
            # Fallback manuel
            providers = [
                "groq",
                "mistral",
                "gpt4o_github",
                "gemini",
                "ollama",
                "cohere",
                "claude",
                "sambanova",
                "deepseek",
            ]
            return _j.dumps({"providers": providers, "note": str(e)}, ensure_ascii=False)

    async def handle_hub(self, args: dict, agent: str, ring: int) -> str:
        action = args.get("action", "get_mode")
        if action == "get_mode":
            return await self.handle_get_mode(args, agent, ring)
        if action == "set_mode":
            return await self.handle_set_mode(args, agent, ring)
        if action == "poll":
            return await self.handle_poll(args, agent, ring)
        if action == "notify":
            return await self.handle_notify(args, agent, ring)
        if action == "list_providers":
            return await self.handle_list_providers(args, agent, ring)
        if action == "search_recent":
            return await self.handle_search_recent(args, agent, ring)
        if action == "whoami":
            return await self.handle_whoami(args, agent, ring)
        if action == "confirmer_owner":
            # Elicitation MCP : le dialogue s'affiche chez l'owner, le modele ne le remplit
            # pas. Seul etat qui autorise : ACCEPTE (app/forge_mcp_elicitation.py).
            import json as _json
            from nokido_agent.app.forge_mcp_elicitation import confirmer_owner

            r = await confirmer_owner(str(args.get("message") or ""), str(args.get("detail") or ""))
            return _json.dumps(r, ensure_ascii=False)
        if action in ("redemarrer_stack", "ordre_bureau", "demander_ordre"):
            # Ordres confies a la session de l'owner (app/forge_ordres_bureau.py, 2026-09-26) :
            # redemarrer_stack questionne l'owner par elicitation et ne depose l'ordre que
            # sur ACCEPTE ; ordre_bureau le rend au tray, une seule fois. demander_ordre
            # (2026-09-29, derogation owner UNIQUE sur ce fichier) est la porte generique :
            # les ordres suivants s'ajoutent dans forge_ordres_bureau, plus ici.
            import json as _json
            from nokido_agent.app import forge_ordres_bureau as _ob

            if action == "redemarrer_stack":
                r = await _ob.redemarrer_stack(agent, str(args.get("message") or ""))
            elif action == "demander_ordre":
                r = await _ob.demander_ordre(agent, str(args.get("ordre") or ""), str(args.get("message") or ""),
                                             cible=str(args.get("cible") or ""), texte=str(args.get("texte") or ""),
                                             pointeur=str(args.get("pointeur") or ""))
            else:
                r = _ob.prendre(agent)
            return _json.dumps(r, ensure_ascii=False)
        if action == "emit_telemetry":
            return await self.handle_emit_telemetry(args, agent, ring)
        if action == "manage_forge_lifecycle":
            return await self.handle_manage_forge_lifecycle(args, agent, ring)
        if action == "send":
            return await self.handle_agent_send(args, agent, ring)
        if action == "recv":
            return await self.handle_agent_recv(args, agent, ring)
        if action == "quota_status":
            return await self.handle_quota_status(args, agent, ring)
        if action == "quota_model":
            return await self.handle_quota_model(args, agent, ring)
        if action == "quota_report":
            return await self.handle_quota_report(args, agent, ring)
        return f"hub: action inconnue {action}"

    async def handle_quota_model(self, args: dict, agent: str, ring: int) -> str:
        """hub action=quota_model quality=high|medium|low|ultra [apply=true]
        Sélectionne le meilleur modèle Gemini selon quota disponible.
        Si apply=true → met à jour ~/.gemini/settings.json"""
        import sys as _qs, os as _qo

        _qapp = str(__import__("pathlib").Path(__file__).resolve().parent)
        if _qapp not in _qs.path:
            _qs.path.insert(0, _qapp)
        try:
            from nokido_agent.app.forge_quota_manager import auto_select, get_best_model, status_report

            quality = args.get("quality", "medium")
            apply = str(args.get("apply", "false")).lower() in ("true", "1")
            if apply:
                model = auto_select(quality)
                return f"Modèle appliqué: {model}\n\n" + status_report()
            else:
                model = get_best_model(quality)
                return f"Recommandé ({quality}): {model}\n\n" + status_report()
        except Exception as e:
            return f"ERR quota_model: {e}"

    async def handle_quota_report(self, args: dict, agent: str, ring: int) -> str:
        """hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W
        Gemini reporte son état quota réel (vu dans /model).
        Stocke dans RAG/quota_state.json."""
        import json as _j
        from pathlib import Path as _P

        state = {
            "flash": args.get("flash"),
            "flash_lite": args.get("flash_lite"),
            "pro": args.get("pro"),
            "preview_pro": args.get("preview_pro"),
            "ts": __import__("datetime").datetime.now().isoformat(),
            "reported_by": agent,
        }
        for k in ["flash", "flash_lite", "pro", "preview_pro"]:
            try:
                state[k] = float(state[k])
            except:
                pass
        db = _P(__file__).resolve().parent.parent / "RAG" / "quota_state.json"
        db.write_text(_j.dumps(state, indent=2), encoding="utf-8")
        return f"Quota state sauvegardé: flash={state['flash']}% flash_lite={state['flash_lite']}% pro={state['pro']}% preview_pro={state['preview_pro']}%"

    async def handle_quota_status(self, args: dict, agent: str, ring: int) -> str:
        """Snapshot quota tous providers via forge_quota_tracker.

        args.fetch_live : True -> appelle endpoints HTTP (ex: OpenRouter /v1/key).
        args.provider   : si specifie, retourne uniquement ce provider en detail.
        """
        try:
            from nokido_agent.app.forge_quota_tracker import get_quota, get_all_quotas, quota_summary_text

            fetch_live = bool(args.get("fetch_live", False))
            prov = args.get("provider")
            if prov:
                return json.dumps(get_quota(prov, fetch_live=fetch_live), indent=2, default=str, ensure_ascii=False)
            # Mode par defaut : resume texte (econome en tokens)
            if args.get("format") == "json":
                return json.dumps(get_all_quotas(fetch_live=fetch_live), indent=2, default=str, ensure_ascii=False)
            return quota_summary_text(fetch_live=fetch_live)
        except Exception as e:
            return f"ERR quota_status: {type(e).__name__}: {e}"

    async def handle_agent_send(self, args: dict, agent: str, ring: int) -> str:
        import sqlite3, hashlib, time, json as _json

        to_agent = args.get("to", "")
        method = args.get("method", "agent.message")
        payload = str(args.get("payload", ""))
        if not to_agent:
            return "ERR: to requis"
        msg_id = hashlib.sha256(f"{agent}{to_agent}{time.time()}".encode()).hexdigest()[:16]
        try:
            from nokido_agent.app.forge_db_path import open_m2m as _open_m2m   # scission M2M
            conn = _open_m2m(timeout=3)
            conn.execute(
                "INSERT INTO agent_messages(id,from_agent,to_agent,correlation_id,method,payload,status) VALUES(?,?,?,?,?,?,?)",
                (msg_id, agent, to_agent, args.get("correlation_id", msg_id), method, payload, "pending"),
            )
            conn.commit()
            conn.close()
            return _json.dumps({"id": msg_id, "status": "sent", "to": to_agent})
        except Exception as e:
            return f"ERR:{e}"

    async def handle_agent_recv(self, args: dict, agent: str, ring: int) -> str:
        import sqlite3, json as _json

        limit = int(args.get("limit", 5))
        try:
            from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M
            conn = sqlite3.connect(_m2m_path(), timeout=3)
            rows = conn.execute(
                "SELECT id,from_agent,method,payload,created_at FROM agent_messages WHERE to_agent=? AND status='pending' ORDER BY rowid ASC LIMIT ?",
                (agent, limit),
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                conn.execute(
                    f"UPDATE agent_messages SET status='read',read_at=datetime('now') WHERE id IN ({chr(44).join([chr(63)] * len(ids))})",
                    ids,
                )
            conn.commit()
            conn.close()
            return _json.dumps(
                {
                    "messages": [{"id": r[0], "from": r[1], "method": r[2], "payload": r[3], "at": r[4]} for r in rows],
                    "count": len(rows),
                }
            )
        except Exception as e:
            return f"ERR:{e}"

    async def handle_task(self, args: dict, agent: str, ring: int) -> str:
        action = args.get("action", "status")
        if action == "assign":
            return await self.handle_task_assign(args, agent, ring)
        if action == "claim":
            return await self.handle_task_claim(args, agent, ring)
        if action == "result":
            return await self.handle_task_result(args, agent, ring)
        if action == "status":
            return await self.handle_task_status(args, agent, ring)
        return f"task: action inconnue {action}"

    async def handle_event(self, args: dict, agent: str, ring: int) -> str:
        action = args.get("action", "history")
        if action == "publish":
            return await self.handle_event_publish(args, agent, ring)
        if action == "history":
            return await self.handle_event_history(args, agent, ring)
        if action == "fetch_archived":
            return await self.handle_event_fetch_archived(args, agent, ring)
        return f"event: action inconnue {action}"

    async def handle_rag(self, args: dict, agent: str, ring: int) -> str:
        action = args.get("action", "search")
        if action == "index":
            return await self.handle_index_result(args, agent, ring)
        if action == "search":
            # Recherche RAG : dense (bge-m3 :8099 + cosine + rerank :8100),
            # fallback BM25 FTS5 si :8099 indisponible.
            topic = args.get("topic", "") or args.get("query", "")
            limit = int(args.get("limit", 10))
            if not topic:
                return "rag search: parametre topic requis"
            # #8 audit DB au grain TOOL : 1 ligne par rag_search (lit embeddings.db),
            # attribuée à l'acteur (#7). Léger (pas par connexion -> évite le wedge du
            # routage _db_connect, reverté). Best-effort, ne casse jamais la recherche.
            try:
                from nokido_agent.app.forge_db_conn import _audit_db_access

                _audit_db_access(str(self.root / "RAG" / "embeddings.db"), "read", "sqlite")
            except Exception:
                pass
            import asyncio as _aio
            try:
                # OFFLOAD : _rag_dense_search charge la matrice embeddings (_load_dense_cache,
                # TTL 300s) + cosine = CPU/IO lourd -> JAMAIS sur l'event loop (sinon gel,
                # constaté live par forge_loop_sentinel: _load_dense_cache mid-block).
                _res = await _aio.to_thread(self._rag_dense_search, topic, limit, bool(args.get("multi")))
                # observation shadow du routeur de recherche (2026-09-03).
                # Le cablage vivait dans RAGEngine.search(), que CE chemin
                # n'emprunte pas : le journal restait vide et le replay rendait
                # `lues: 0`. SHADOW = on note ce que le routeur AURAIT decide,
                # on n'applique rien. WARNING et non debug : un echec doit
                # s'entendre, sinon on remesure ce silence dans six mois.
                try:
                    import time as _rt_time
                    from nokido_agent.app.forge_retrieval_router import decider as _rt_decider
                    from nokido_agent.app.forge_retrieval_router import observer as _rt_observer

                    _rt_dec = _rt_decider(topic, {})
                    _rt_observer(
                        "%d" % int(_rt_time.time() * 1000), topic, _rt_dec, [],
                        contexte={"k": limit, "chemin": "handle_rag/_rag_dense_search",
                                  "multi": bool(args.get("multi"))})
                except Exception as _rt_e:  # noqa: BLE001
                    import logging as _rt_log
                    _rt_log.getLogger(__name__).warning(
                        "[router] observation shadow impossible (%r)", _rt_e)
                return _res
            except Exception as e_dense:
                try:
                    _res_bm25 = await _aio.to_thread(self._rag_bm25_search, topic, limit)
                except Exception as e:
                    return f"rag search error: dense={e_dense} bm25={e}"
                # C0 (2026-09-12) — OBSERVER LE CHEMIN REELLEMENT EMPRUNTE.
                # L'observation ne vivait que dans la branche dense ci-dessus. Or
                # les embedders sont eteints : toute recherche reelle tombe ICI.
                # Mesure : journal shadow fige a 899 o / 1 ligne depuis le
                # 2026-09-03, alors qu'une recherche emise le 2026-09-12 rendait
                # bien des resultats scores bm25. Un observateur cable sur le seul
                # chemin qui ne s'execute jamais accumule du volume, pas de la
                # preuve — meme famille qu'un garde branche sur un signal que
                # personne n'emet. `motif_repli` porte la RAISON du repli : sans
                # elle, un embedder eteint ne se distingue pas d'une panne.
                try:
                    import time as _rt_time
                    from nokido_agent.app.forge_retrieval_router import decider as _rt_decider
                    from nokido_agent.app.forge_retrieval_router import observer as _rt_observer

                    _rt_dec = _rt_decider(topic, {})
                    _rt_observer(
                        "%d" % int(_rt_time.time() * 1000), topic, _rt_dec, [],
                        contexte={"k": limit, "chemin": "handle_rag/_rag_bm25_search",
                                  "multi": bool(args.get("multi")),
                                  "motif_repli": type(e_dense).__name__})
                except Exception as _rt_e:  # noqa: BLE001
                    import logging as _rt_log
                    _rt_log.getLogger(__name__).warning(
                        "[router] observation shadow impossible (%r)", _rt_e)
                return _res_bm25
        if action == "distill":
            try:
                from nokido_agent.app.forge_distiller import RAGDistiller

                domain = args.get("domain", "general")
                threshold = float(args.get("threshold", 0.92))
                import sqlite3

                db_path = str(self.root / "RAG" / "embeddings.db")
                conn = sqlite3.connect(db_path)
                rows = conn.execute(
                    "SELECT id,text,embedding,domain FROM rag_chunks "
                    "WHERE domain=? AND embedding IS NOT NULL LIMIT 2000",
                    (domain,),
                ).fetchall()
                conn.close()
                if not rows:
                    return f"distill: 0 chunks vectorises dans {domain}"
                results = [{"id": r[0], "text": r[1], "embedding": r[2], "domain": r[3]} for r in rows]
                d = RAGDistiller(ring=ring)
                kept = d.distill(results, mode="hybrid", top_k=args.get("top_k", 50))
                removed = len(results) - len(kept)
                return f"distill {domain}: {len(results)} -> {len(kept)} chunks ({removed} doublons retires)"
            except Exception as e:
                return f"distill error: {e}"
        if action == "stats":
            try:
                import sqlite3

                conn = sqlite3.connect(str(self.root / "RAG" / "embeddings.db"))
                total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
                no_emb = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[0]
                domains = conn.execute(
                    "SELECT domain,COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 10"
                ).fetchall()
                conn.close()
                d_str = " | ".join(f"{d}:{n}" for d, n in domains)
                return f"RAG total={total} no_emb={no_emb} | {d_str}"
            except Exception as e:
                return f"stats error: {e}"
        if action == "ingest":
            # Ingestion raffinee L1-L3 : text -> chunks -> store
            try:
                from nokido_agent.app.forge_ingest_pipeline import process_document, store_chunks
                from nokido_agent.app.forge_npu_embedder import embed_via_probe

                text = args.get("text", "")
                source = args.get("source", "unknown")
                chunks = process_document(
                    text=text,
                    source=source,
                    domain_hint=args.get("domain", ""),
                    role_hint=args.get("role", ""),
                    author=args.get("author", ""),
                    doc_summary=args.get("summary", ""),
                )
                if not chunks:
                    return "ingest: 0 chunks (texte trop court ou vide)"
                # Vectoriser via NPU probe
                texts_only = [c.text for c in chunks]
                vecs = embed_via_probe(texts_only)
                if vecs:
                    for c, v in zip(chunks, vecs):
                        c.embedding = v
                inserted = store_chunks(chunks)
                domain = chunks[0].domain if chunks else "?"
                role = chunks[0].role_hint if chunks else "?"
                vectorized = len(vecs) if vecs else 0
                return (
                    f"ingest OK: {len(chunks)} chunks -> {inserted} inseres "
                    f"domain={domain} role={role} vectorized={vectorized}"
                )
            except Exception as e:
                return f"ingest error: {e}"
        return f"rag: action inconnue {action} (index|search|distill|stats|ingest)"

    def _rag_bm25_search(self, topic: str, limit: int) -> str:
        """Recherche BM25 FTS5 sur rag_chunks_fts, scope tier chaud. Fallback."""
        import re as _re
        import sqlite3
        import time as _t_bm25

        _t0_bm25 = _t_bm25.time()

        _stop = {
            "quelle",
            "quel",
            "quels",
            "quelles",
            "est",
            "les",
            "des",
            "une",
            "uns",
            "dans",
            "pour",
            "par",
            "sur",
            "avec",
            "que",
            "qui",
            "quoi",
            "comment",
            "elle",
            "ils",
            "son",
            "sas",
            "ses",
            "aux",
            "leur",
            "etre",
            "fait",
            "the",
            "and",
            "what",
            "how",
            "are",
            "this",
            "that",
            "from",
            "with",
            "ont",
            "cette",
        }
        terms = [w for w in _re.findall(r"\w+", topic.lower()) if len(w) > 2 and w not in _stop]
        if not terms:
            return "Aucun resultat (requete sans terme significatif)."
        match = " OR ".join(f'"{w}"' for w in terms[:24])
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            # DEUX index lexicaux coexistaient, et le corps n'en remplissait QU'UN.
            # Mesure 2026-08-23 : `rag_fts MATCH 'Nengo'` = 55 (dont 48 chunks d'un
            # article ingere le jour meme), `rag_chunks_fts MATCH 'Nengo'` = 2.
            # `rag_chunks_fts` est un index external-content (content='rag_chunks')
            # que rien ne synchronise ; les 26 modules qui ecrivent du lexical
            # alimentent tous `rag_fts`. La lecture interrogeait donc l'index que
            # PERSONNE ne nourrit : toute ingestion recente etait introuvable en
            # recherche syntaxique alors qu'elle etait correctement indexee, et le
            # symptome se lisait comme "le RAG ne contient rien sur ce sujet".
            # LE LEXICAL SERT D'ABORD CE QUE LE DENSE NE PEUT PAS VOIR (2026-08-23).
            # L'ancienne clause `AND c.embedding IS NOT NULL` excluait du lexical
            # exactement les chunks INVISIBLES a la recherche vectorielle — soit
            # 176 431 chunks, dont la tete de file est la plus fraiche : sur les
            # 4 000 non vectorises les plus recents, 3 970 sont du domaine `conv`,
            # le reste `knowledge_papers` / `episodic_memory` / `autonomous`.
            # La vectorisation a un cout, donc elle aura TOUJOURS du retard : le
            # corps se retrouvait aveugle a ce qui venait de lui arriver, par les
            # deux voies a la fois. Deux voies, comme une fibre rapide qui porte le
            # reflexe pendant que la voie lente interprete : le lexical DOIT couvrir
            # la fenetre que le dense n'a pas encore atteinte.
            # Le bonus compense une absence structurelle, pas une qualite : un chunk
            # non vectorise ne peut RIEN marquer par le canal dense, il partirait
            # donc perdant a fusion egale. Reglable, et neutralisable a 0.
            # UN RETRAIT DOIT S'APPLIQUER, PAS SEULEMENT SE DECLARER (2026-09-23).
            # Le raffinage a passe 655 216 chunks a `active=0` (retires, jamais
            # supprimes) ; ce repli, qui sert la majorite des recherches reelles, les
            # rendait quand meme. `COALESCE(...,1)` : un chunk ancien SANS valeur n'a
            # jamais ete retire (UNKNOWN != NO) — seul `active=0` explicite l'exclut.
            # NR : tests/nr/test_rag_lexical_exclut_inactifs_nr.py
            "SELECT c.id AS id, c.source AS source, c.domain AS domain, c.text AS text, "
            "bm25(rag_fts) - (CASE WHEN c.embedding IS NULL THEN ? ELSE 0 END) AS rank "
            "FROM rag_fts JOIN rag_chunks c "
            "ON c.id = rag_fts.chunk_id "
            "WHERE rag_fts MATCH ? AND COALESCE(c.active, 1) = 1 "
            "ORDER BY rank LIMIT ?",
            (float(os.environ.get("LAFORGE_LEXICAL_BONUS_NON_VECTORISE", "2.0")),
             match, limit),
        ).fetchall()
        try:
            _ids = [r["id"] for r in rows if r["id"]]
            if _ids:
                conn.execute(
                    "UPDATE rag_chunks SET access_count=COALESCE(access_count,0)+1 "
                    "WHERE id IN (%s)" % ",".join("?" * len(_ids)), _ids)
                conn.commit()
        except Exception:
            pass  # signal d'usage best-effort : jamais casser la lecture
        conn.close()
        if not rows:
            return "Aucun resultat."
        # LA SOIF EPISTEMIQUE MOURAIT DE FAIM ICI (mesure 2026-08-20).
        # `_log_query` n'etait appele QUE depuis `_rag_dense_search`. Or ce chemin
        # BM25 est le FALLBACK, et il sert des que le dense echoue — c'est-a-dire
        # la majorite des recherches reelles. Consequence : `query_log` fige au
        # 2026-08-14 (118 lignes), et `forge_epistemic_daemon`, qui ne lit QUE
        # `query_log`, tournait avec `examinees: 0` — vivant mais sans matiere.
        # Un organe qui se nourrit d'une trace doit etre nourri par TOUS les
        # chemins qui produisent cette trace, pas seulement par le chemin noble.
        self._log_query(topic, {"mode": "bm25"}, [r["id"] for r in rows if r["id"]],
                        int((_t_bm25.time() - _t0_bm25) * 1000))
        return "\n\n".join(
            f"[{r['source']}] ({r['domain']}, bm25={r['rank']:.1f})\n{(r['text'] or '')[:400]}" for r in rows
        )

    @staticmethod
    def _rag_query_filter(topic: str) -> dict:
        """Self-Query leger (sans LLM) : detecte un langage mentionne dans la
        requete -> filtre ext. Tue l'homonymie cross-langage (validate() Deno
        vs PowerShell)."""
        t = " " + (topic or "").lower() + " "
        for kw, ext in (
            ("python", "py"),
            (".py", "py"),
            ("typescript", "ts"),
            (".ts", "ts"),
            ("deno", "ts"),
            ("javascript", "js"),
            (".js", "js"),
            ("rust", "rs"),
            ("powershell", "ps1"),
        ):
            if kw in t:
                return {"ext": ext}
        return {}

    @staticmethod
    def _strip_output_noise(text: str) -> str:
        """Compaction rtk-style AVANT cap : strip séquences ANSI + collapse
        lignes vides (3+ → 1) + dédup lignes consécutives identiques. N'enlève
        QUE du bruit répétitif (logs, progress bars) — zéro perte de signal,
        gros gain tokens sur stdout verbeux. JSON jamais passé ici (cf. appelant)."""
        import re as _re

        text = _re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)  # séquences ANSI
        text = _re.sub(r"[ \t]+(\r?\n)", r"\1", text)            # trailing whitespace
        out: list = []
        prev = None
        dup = 0
        blanks = 0
        for line in text.split("\n"):
            if line.strip() == "":
                blanks += 1
                if blanks <= 1:
                    out.append(line)
                continue
            blanks = 0
            if line == prev:
                dup += 1
                continue
            if dup:
                out.append(f"    … [{dup + 1}× la ligne ci-dessus]")
                dup = 0
            out.append(line)
            prev = line
        if dup:
            out.append(f"    … [{dup + 1}× la ligne ci-dessus]")
        return "\n".join(out)

    @staticmethod
    def _reorder_mid(items: list) -> list:
        """Lost-in-the-middle : meilleurs aux extremites du prompt, moins bons
        au centre (le LLM final attend moins le milieu d'un long contexte)."""
        head, tail = [], []
        for k, it in enumerate(items):
            (head if k % 2 == 0 else tail).append(it)
        return head + tail[::-1]

    def _sidecar_dense_actif(self) -> tuple:
        """Le sidecar vectoriel est-il configure ET vivant ? (2026-08-25)

        TROIS ETATS, JAMAIS DEUX : delegue / non configure / configure mais MUET.
        Confondre les deux derniers ferait passer une PANNE pour un CHOIX — et c'est
        exactement ainsi qu'on batit 4,7 Go de matrice en croyant l'avoir deleguee.

        Rend (bool, raison) : la raison est journalisee, parce qu'un mode de
        fonctionnement qu'on ne peut pas lire dans les logs se diagnostique a l'aveugle.
        """
        import json as _js
        import os as _os
        import urllib.request as _ur

        port = _os.environ.get("LAFORGE_VEC_SIDECAR_PORT")
        if not port:
            return False, "matrice locale (LAFORGE_VEC_SIDECAR_PORT absent)"
        try:
            with _ur.urlopen("http://127.0.0.1:%s/health" % port, timeout=2.0) as r:
                _d = _js.loads(r.read().decode("utf-8", "replace"))
        except Exception as _e:  # noqa: BLE001
            return False, ("sidecar :%s CONFIGURE MAIS INJOIGNABLE (%s) -> repli sur la "
                           "matrice locale, ce n'est pas le mode voulu"
                           % (port, type(_e).__name__))
        # `forge_faiss_sidecar.sidecar_alive` teste `.get("ok")`, or le sidecar Qdrant
        # rend `{"status": "ok"}` : ce client-la le declarerait mort a tort. On accepte
        # les deux formes plutot que de propager l'incompatibilite.
        if _d.get("ok") or _d.get("status") == "ok":
            return True, "delegue au sidecar :%s (collection %s)" % (
                port, _d.get("collection") or "?")
        return False, "sidecar :%s repond sans ok -> matrice locale" % port

    def _load_dense_cache(self) -> dict:
        """Charge les embeddings du tier chaud en RAM (cache, TTL 300s).

        DELEGATION (2026-08-25). Mesure tracemalloc : la ligne `np.empty` plus bas
        allouait 4 720 Mo — 1 152 197 vecteurs x 1024 float32 — dans le process du hub,
        alors que Qdrant en detenait deja 1 150 543 sur disque et que le hub portait
        `LAFORGE_VEC_SIDECAR_PORT=8098`. Le cutover etait DECLARE et pas EFFECTIF : le
        drapeau n'etait lu que par `forge_rag_engine`, qui n'est meme pas importe ici.
        Quand le sidecar repond, on ne demande donc plus la colonne `embedding` et on
        n'alloue plus de matrice. On garde `ids`, `meta`, `exts`, `folders` : le rerank
        et l'affichage en dependent, et ils pesent 264 Mo, pas 4,7 Go.
        """
        import sqlite3
        import struct as _st
        import json as _j
        import time as _t
        import numpy as _np

        _delegue, _pourquoi = self._sidecar_dense_actif()
        if (not _delegue and "INJOIGNABLE" in _pourquoi
                and not getattr(self, "_sidecar_attente_faite", False)):
            # ORDRE DES VAGUES (mesure 2026-08-25). Le hub est en vague 1, le sidecar
            # en vague 4 : il demarre +23 s APRES lui. Le prewarm dense tombait donc
            # systematiquement sur un sidecar muet et batissait les 4,7 Go, alors que
            # le drapeau demandait exactement l'inverse — la delegation ne pouvait
            # JAMAIS s'engager au boot, et le repli, pourtant correct, la rendait
            # invisible. Un drapeau pose par l'operateur exprime une INTENTION : une
            # indisponibilite de quelques secondes au demarrage ne doit pas la
            # retourner pour toute la session. On attend donc, borne, UNE SEULE FOIS
            # par process — les rafraichissements suivants ne repaient pas l'attente.
            # Pendant ce temps les recherches tombent en BM25, ce qui est deja le
            # comportement normal d'un cache en cours de warm.
            _budget = float(os.environ.get("LAFORGE_VEC_SIDECAR_WAIT_S", "90"))
            _fin = _t.time() + _budget
            logging.getLogger(__name__).info(
                "[rag:index] sidecar configure mais pas encore la — attente bornee "
                "%.0f s avant de batir la matrice locale", _budget)
            while _t.time() < _fin and not _delegue:
                _t.sleep(5.0)
                _delegue, _pourquoi = self._sidecar_dense_actif()
            self._sidecar_attente_faite = True
            if not _delegue:
                logging.getLogger(__name__).warning(
                    "[rag:index] sidecar TOUJOURS muet apres %.0f s -> matrice locale "
                    "(~4,7 Go). Ce n'est PAS le mode voulu : verifier le port %s.",
                    _budget, os.environ.get("LAFORGE_VEC_SIDECAR_PORT"))
        logging.getLogger(__name__).info("[rag:index] mode dense = %s", _pourquoi)
        if _delegue:
            _conn = sqlite3.connect(str(self.db_path), timeout=20)
            _ids, _meta, _exts, _folders = [], {}, [], []
            # Meme filtre `embedding IS NOT NULL` que le mode local : le jeu d'ids doit
            # rester celui que Qdrant indexe, sinon `idpos` ne remappe plus rien.
            for _cid, _src, _dom, _txt, _ext, _fold in _conn.execute(
                "SELECT id, source, domain, text, ext, folder FROM rag_chunks "
                "WHERE embedding IS NOT NULL"
            ):
                if not _cid:
                    continue
                _ids.append(_cid)
                _meta[_cid] = {"source": _src, "domain": _dom, "text": (_txt or "")[:512]}
                _exts.append(_ext or "")
                _folders.append(_fold or "")
            _conn.close()
            logging.getLogger(__name__).info(
                "[rag:index] %d chunks indexables, AUCUNE matrice en RAM (dense servi "
                "par le sidecar)", len(_ids))
            return {
                "ids": _ids,
                # Matrice VIDE = sentinelle deja comprise par `_rag_dense_search`, qui
                # bascule alors sur le sidecar. On ne cree pas un second drapeau la ou
                # la forme porte deja l'information.
                "mat": _np.zeros((0, 1024), dtype=_np.float32),
                "meta": _meta,
                "exts": _np.array(_exts),
                "folders": _np.array(_folders),
                "ts": _t.time(),
            }

        conn = sqlite3.connect(str(self.db_path), timeout=20)
        # PIC MESURE 2026-08-20 : 15,50 Go de pic pour 5,91 Go de plateau, sur une
        # machine de 23,67 Go — soit 65 % prise par un seul process, ce qui declenche
        # une `evict_detresse` a CHAQUE redemarrage. Cause : `np.vstack(vecs)` alloue
        # la matrice ENTIERE pendant que la liste `vecs` existe encore -> la memoire
        # est DOUBLEE a l'instant du pic. Le commentaire ci-dessous se felicite
        # d'avoir tue les tuples Python (14 Go -> 4 Go), mais le doublement du vstack
        # avait survecu. On pre-alloue donc la matrice et on la remplit EN PLACE :
        # le pic retombe au niveau du plateau. `count` d'abord (index partiel, rapide).
        try:
            _n_att = conn.execute(
                "SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
        except Exception:  # noqa: BLE001 - si le compte echoue on repart en mode liste
            _n_att = 0
        _mat_pre = None
        if _n_att:
            try:
                _mat_pre = _np.empty((_n_att, 1024), dtype=_np.float32)
            except Exception as _e_ram:  # noqa: BLE001
                # REPLI BORNE, PLUS JAMAIS `vstack` (2026-08-20). L'ancien repli
                # reconstruisait la liste complete puis la concatenait : il
                # REPRODUISAIT exactement le pic de 15,5 Go qu'on venait de
                # supprimer, et precisement dans le seul cas ou il se declenche --
                # celui ou la RAM manque deja. Un repli qui ramene le defaut n'est
                # pas un repli. On bascule sur un memmap DISQUE : le pic devient
                # nul, au prix d'I/O.
                import os as _os_mm

                _chemin_mm = str(self.db_path) + ".dense.%d.mmap" % _os_mm.getpid()
                try:
                    _mat_pre = _np.memmap(_chemin_mm, dtype=_np.float32,
                                          mode="w+", shape=(_n_att, 1024))
                    logger.warning(
                        "[rag:index] pre-allocation RAM %d x 1024 impossible (%s) : "
                        "bascule sur memmap disque %s", _n_att,
                        type(_e_ram).__name__, _chemin_mm)
                except Exception as _e_mm:  # noqa: BLE001
                    # Ni RAM ni disque. Refabriquer le pic tuerait le process ;
                    # rendre un index vide EN SILENCE serait un faux-vert. Le log
                    # est le contrat : la recherche dense est degradee, on le dit.
                    logger.error(
                        "[rag:index] ni RAM (%s) ni memmap (%s) pour %d x 1024 : "
                        "index dense VIDE ce cycle -- recherche dense DEGRADEE, "
                        "le lexical reste seul", type(_e_ram).__name__,
                        type(_e_mm).__name__, _n_att)
                    _mat_pre = None
        _k_pre = 0
        _ignores = 0
        ids, meta, exts, folders = [], {}, [], []
        for cid, src, dom, txt, ext, folder, emb in conn.execute(
            "SELECT id, source, domain, text, ext, folder, embedding FROM rag_chunks WHERE embedding IS NOT NULL"
        ):
            # RAM (2026-07-07, hub a 13.9GB) : ex-unpack en TUPLES de floats
            # Python = pic ~14GB sur 544k vecteurs (28B/float, heap jamais
            # rendu a l'OS). np.frombuffer = zero-copy 4KB/vecteur -> ~4GB.
            v = None
            if isinstance(emb, bytes) and len(emb) == 4096:
                v = _np.frombuffer(emb, dtype=_np.float32)
            elif isinstance(emb, (bytes, str)):
                try:
                    jv = _j.loads(emb)
                    if isinstance(jv, list) and len(jv) == 1024:
                        v = _np.asarray(jv, dtype=_np.float32)
                except Exception:
                    pass
            if v is None or not cid:
                continue
            # Remplissage EN PLACE : la copie va directement dans la matrice
            # finale, `v` est relachee au tour suivant. Plus de place (table
            # agrandie pendant la lecture) ou aucune matrice : on COMPTE et on
            # passe -- on ne bascule pas sur une liste qui rejouerait le pic.
            # Le test precede `ids.append` pour que `ids` et les lignes de la
            # matrice restent alignes : un decalage ici rendrait des voisins
            # attribues au mauvais chunk, ce qui est pire qu'un vecteur manquant.
            if _mat_pre is None or _k_pre >= _n_att:
                _ignores += 1
                continue
            _mat_pre[_k_pre] = v
            _k_pre += 1
            ids.append(cid)
            # RAM (2026-07-07, 93% post-prewarm) : les consommateurs ne lisent
            # que text[:512] (rerank) / [:400] (sortie) -> stocker 512 chars
            # au lieu du texte complet = plusieurs GB rendus, zero perte.
            meta[cid] = {"source": src, "domain": dom, "text": (txt or "")[:512]}
            exts.append(ext or "")
            folders.append(folder or "")
        conn.close()
        if _ignores:
            logger.warning(
                "[rag:index] %d vecteur(s) hors index ce cycle (matrice "
                "indisponible, ou table agrandie pendant la lecture) -- compte "
                "DIT, jamais taise", _ignores)
        # Tronque si la table a maigri entre le compte et la lecture (concurrence).
        mat = (_mat_pre[:_k_pre] if _mat_pre is not None
               else _np.zeros((0, 1024), dtype=_np.float32))
        nrm = _np.linalg.norm(mat, axis=1, keepdims=True)
        nrm[nrm == 0] = 1.0
        mat /= nrm
        return {
            "ids": ids,
            "mat": mat,
            "meta": meta,
            "exts": _np.array(exts),
            "folders": _np.array(folders),
            "ts": _t.time(),
        }

    def _dense_refresh_bg(self) -> None:
        """Pre-warm/refresh du cache dense en thread daemon, race-garde.

        Cold-wedge RCA 2026-07-07 : _load_dense_cache decode ~691k
        embeddings (GIL-bound) -> jamais inline. Lock non-bloquant = un
        seul loader ; les searches pendant le warm servent le stale ou
        tombent en BM25. Ne touche PAS _save_embeddings (piege wipe).
        """
        import threading as _th

        lk = getattr(self, "_dense_lock", None)
        if lk is None:
            lk = self._dense_lock = _th.Lock()
        if not lk.acquire(blocking=False):
            return  # warm deja en cours

        def _work():
            try:
                # SATIETE (avis AGY 2026-07-30) : ne pas batir ~2,2 Go de matrice
                # dense quand le corps manque de place. Le seuil vient du corps
                # lui-meme (_SUPERVISOR_SLEEP_RAM_THRESHOLD : le point ou il endort
                # des services), pas d'un chiffre choisi ici. Fail-open : mesure
                # indisponible -> on construit, car un cache absent degrade en BM25
                # alors qu'un frein aveugle bloquerait le RAG sans raison.
                try:
                    import psutil as _ps

                    from nokido_agent.app.forge_resource_manager import (
                        _SUPERVISOR_SLEEP_RAM_THRESHOLD as _SEUIL,
                    )

                    _vm = _ps.virtual_memory()
                    _libre = _vm.available / (1024 ** 3)
                    if _vm.percent >= _SEUIL or _libre < 3.5:
                        # EXCEPTION MESUREE (2026-08-25). Ce frein suppose qu'un warm
                        # COUTE de la memoire — vrai pour la matrice de 4,7 Go, FAUX en
                        # mode delegue ou le warm ne charge que ~0,3 Go de metadonnees
                        # et FAIT TOMBER la matrice existante. Sans cette exception, le
                        # garde interdisait precisement la bascule qui rend la RAM :
                        # sous pression le corps restait sur le mode cher, et plus il
                        # manquait de place, moins il pouvait s'en sortir. Un frein qui
                        # empeche la guerison protege le symptome.
                        _peut_deleguer, _r = self._sidecar_dense_actif()
                        if not _peut_deleguer:
                            logging.getLogger(__name__).warning(
                                "[rag] warm dense REFUSE (satiete) : RAM %.1f%% >= "
                                "%.1f%% ou libre %.2f Go < 3.5 — recherche en BM25, "
                                "reconstruction au prochain cycle",
                                _vm.percent, _SEUIL, _libre,
                            )
                            return
                        logging.getLogger(__name__).warning(
                            "[rag] satiete atteinte (RAM %.1f%%, libre %.2f Go) mais "
                            "warm AUTORISE : %s — ce cycle LIBERE la matrice au lieu "
                            "de la batir", _vm.percent, _libre, _r)
                except Exception as _e:
                    logging.getLogger(__name__).debug(
                        "[rag] satiete non mesurable (%s) — on construit",
                        type(_e).__name__,
                    )
                c = self._load_dense_cache()
                # Jamais ecraser un cache sain par un load vide (DB en vrac).
                if c.get("ids") or getattr(self, "_dense_cache", None) is None:
                    self._dense_cache = c
                    self._declarer_cache_reclamable()
                logging.getLogger(__name__).info(
                    "[rag] dense cache warm OK: %d vecteurs", len(c.get("ids") or [])
                )
            except Exception as e:
                logging.getLogger(__name__).warning("[rag] dense warm failed: %s", e)
            finally:
                lk.release()

        _th.Thread(target=_work, name="rag-dense-prewarm", daemon=True).start()

    def _declarer_cache_reclamable(self) -> None:
        """Declare la matrice dense comme RAM RECLAMABLE (mesure 2026-07-30).

        ~2.3 Go de float32 dont Qdrant detient la copie sur disque : le plus gros
        bloc reclamable du corps, et il n'existait aucun levier pour le rendre. A
        86-90 % de RAM l'echelle rendait `noop` en manquant 1.07 Go, tous les gros
        porteurs etant legitimement proteges (piliers du RAG, porteurs d'etat).

        Un cache se rend, un organe ne s'ampute pas : la perte est un cout de
        RECONSTRUCTION, pas de capacite. `_rag_dense_search` leve alors
        « dense cache warming » et `handle_rag` bascule sur BM25 le temps du warm.
        """
        try:
            from nokido_agent.app.forge_resource_manager import register_reclaimer
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "[rag] cache dense NON declare reclamable (%s) — le corps reste "
                "sans levier RAM", type(e).__name__)
            return

        def _rendre_cache_dense() -> float:
            cache = getattr(self, "_dense_cache", None)
            if not cache:
                return 0.0
            try:
                go = float(getattr(cache.get("mat"), "nbytes", 0)) / (1024 ** 3)
            except Exception:  # noqa: BLE001
                go = 0.0
            # Un search en cours garde SA reference locale : le GC ne libere
            # qu'apres son retour, aucune requete n'est cassee en vol.
            self._dense_cache = None
            if go <= 0.0:
                # MODE DELEGUE (2026-08-25) : il n'y a plus de matrice a rendre, Qdrant
                # la tient. Ce recuperateur n'est donc plus le gros levier du corps — et
                # il vaut mieux qu'il le DISE en rendant 0,00 que d'annoncer un gain
                # imaginaire : un regulateur qui croit disposer de 4,7 Go recuperables
                # attend un soulagement qui ne viendra pas, et n'essaie rien d'autre.
                logging.getLogger(__name__).warning(
                    "[rag] cache dense rendu, mais AUCUNE matrice en RAM (dense "
                    "delegue au sidecar) : seules les metadonnees sont liberees, non "
                    "mesurees ici. Ce levier ne rend plus de RAM significative.")
                return 0.0
            logging.getLogger(__name__).warning(
                "[rag] cache dense RENDU sous pression RAM (~%.2f Go) — recherche "
                "en BM25 jusqu'au prochain warm", go)
            return go

        register_reclaimer("rag_dense_cache", _rendre_cache_dense)

    def _rag_dense_search(self, topic: str, limit: int, multi: bool = False) -> str:
        """Recherche hybride : dense (bge-m3 :8099, cosine) + BM25 FTS5 code-tune
        (k1=1.2 b=0.5), union des candidats, rerank cross-encoder (:8100),
        Self-Query pre-filtre langage, context-reorder. Cache embeddings TTL 300s.
        """
        import json as _j
        import re as _re
        import sqlite3 as _sq
        import time as _t
        import urllib.request as _u
        import numpy as _np

        _t0 = _t.time()
        _stop = {
            "quelle",
            "quel",
            "quels",
            "est",
            "les",
            "des",
            "une",
            "dans",
            "pour",
            "par",
            "sur",
            "avec",
            "que",
            "qui",
            "quoi",
            "comment",
            "the",
            "and",
            "what",
            "how",
            "are",
            "this",
            "from",
            "with",
        }
        # Cold-wedge RCA 2026-07-07 : le load ~691k embeddings (GIL-bound,
        # minutes) ne tourne plus JAMAIS inline sur un search. Pas de cache
        # -> refresh background + raise (handle_rag bascule BM25). Cache
        # stale -> stale-while-revalidate (sert le stale, refresh en fond).
        cache = getattr(self, "_dense_cache", None)
        _ttl = float(os.environ.get("LAFORGE_DENSE_CACHE_TTL", "1800"))
        if not cache:
            self._dense_refresh_bg()
            raise RuntimeError("dense cache warming -> fallback BM25")
        if _t.time() - cache["ts"] > _ttl:
            self._dense_refresh_bg()
        ids, mat, meta = cache["ids"], cache["mat"], cache["meta"]
        if not ids:
            raise RuntimeError("cache dense vide")
        idpos = cache.get("idpos")
        if idpos is None:
            idpos = {c: i for i, c in enumerate(ids)}
            cache["idpos"] = idpos
        # Multi-Query : si demande, reformule la requete en variantes (LLM).
        queries = self._rag_multi_query(topic) if multi else [topic]
        body = _j.dumps({"input": queries}).encode()
        req = _u.Request(
            "http://127.0.0.1:8099/v1/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _u.urlopen(req, timeout=20) as r:
            qd = _j.loads(r.read())["data"]
        qm = _np.asarray([it["embedding"] for it in sorted(qd, key=lambda x: x.get("index", 0))], dtype=_np.float32)
        qm /= _np.linalg.norm(qm, axis=1, keepdims=True) + 1e-9
        flt = self._rag_query_filter(topic)
        mode = "hybride"
        _exts = cache.get("exts")
        if getattr(mat, "shape", (0,))[0] == 0:
            # DENSE DELEGUE (2026-08-25). Aucune matrice en RAM : Qdrant tient les
            # 1,15 M vecteurs et rend directement les voisins. On remappe par `idpos`
            # pour rester sur les indices positionnels que tout l'aval attend — un
            # decalage ici attribuerait des voisins au mauvais chunk.
            import os as _os

            _port = int(_os.environ.get("LAFORGE_VEC_SIDECAR_PORT") or 8098)
            try:
                from nokido_agent.tools.forge_faiss_sidecar import search_remote as _sc_search
            except Exception as _e:  # noqa: BLE001
                self._dense_refresh_bg()
                raise RuntimeError(
                    "dense delegue mais client sidecar introuvable (%s) -> BM25"
                    % type(_e).__name__)
            _scores, _erreurs = {}, 0
            for _qv in qm:
                try:
                    # `.tolist()` OBLIGATOIRE : le client serialise en JSON et
                    # `np.float32` n'est pas serialisable — l'oubli se manifesterait
                    # comme une panne du sidecar, pas comme un bug de type.
                    # timeout 6 s et non 1,5 : le banc du 06/07 mesurait p50 61 ms sur
                    # cette collection, mais la queue est plus longue, et un timeout
                    # se lirait ici comme « aucun voisin » alors que le moteur va bien.
                    for _cid, _sc in _sc_search(_qv.tolist(), 50, port=_port, timeout=6.0):
                        _i = idpos.get(_cid)
                        if _i is not None:
                            _scores[_i] = max(_scores.get(_i, -2.0), float(_sc))
                except Exception:  # noqa: BLE001
                    _erreurs += 1
            if _erreurs and not _scores:
                # Erreurs ET aucun resultat : rendre un dense vide le ferait passer
                # pour « rien de pertinent ». On le DIT et on tombe en BM25.
                self._dense_refresh_bg()
                raise RuntimeError(
                    "sidecar dense injoignable sur %d requete(s) -> repli BM25"
                    % _erreurs)
            if _erreurs:
                logging.getLogger(__name__).warning(
                    "[rag] dense delegue : %d reformulation(s) sur %d en echec cote "
                    "sidecar — resultats PARTIELS, dits plutot que tus",
                    _erreurs, len(qm))
            _ordre = sorted(_scores, key=lambda i: -_scores[i])
            if flt.get("ext") and _exts is not None:
                _filtres = [i for i in _ordre if _exts[i] == flt["ext"]]
                if len(_filtres) >= max(limit, 12):
                    _ordre = _filtres
                    mode = f"hybride.ext={flt['ext']}"
            dense_cand = _ordre[:50]
            mode += ".qdrant"
        else:
            sims = (mat @ qm.T).max(axis=1)  # score = meilleure reformulation
            if flt.get("ext"):
                fmask = _exts == flt["ext"]
                if int(fmask.sum()) >= max(limit, 12):
                    sims = _np.where(fmask, sims, -2.0)
                    mode = f"hybride.ext={flt['ext']}"
            dense_cand = [int(i) for i in _np.argsort(-sims)[:50]]
        # BM25 FTS5 code-tune -> candidats lexicaux
        bm_cand = []
        try:
            terms = [w for w in _re.findall(r"\w+", topic.lower()) if len(w) > 2 and w not in _stop]
            if terms:
                mq = " OR ".join(f'"{w}"' for w in terms[:24])
                cx = _sq.connect(str(self.db_path), timeout=8)
                rows = cx.execute(
                    "SELECT c.id FROM rag_chunks_fts JOIN rag_chunks c "
                    "ON c.rowid = rag_chunks_fts.rowid "
                    "WHERE rag_chunks_fts MATCH ? AND c.embedding IS NOT NULL "
                    "ORDER BY bm25(rag_chunks_fts, 1.2, 0.5) LIMIT 50",
                    (mq,),
                ).fetchall()
                cx.close()
                bm_cand = [idpos[r[0]] for r in rows if r[0] in idpos]
        except Exception:
            pass
        # union dense + BM25 (le reranker tranche), plafonne a 80
        seen, cand = set(), []
        for i in dense_cand + bm_cand:
            if i not in seen:
                seen.add(i)
                cand.append(i)
        # TRACE BRUTE hors du canal de connaissance. `session:auto_*` indexe les
        # tool_calls VERBATIM, requete comprise : la recherche retrouvait en tete
        # l'appel d'outil ou la question figurait mot pour mot — le RAG rendait son
        # propre echo. Sa pertinence lexicale est maximale par construction, donc
        # aucun prior d'autorite ne la renverse ; il faut l'ecarter des candidats.
        # Filtre AVANT le rerank : autant ne pas payer le cross-encoder pour ca.
        cand = [i for i in cand if not str(meta[ids[i]].get("source") or "").startswith("session:auto_")]
        cand = cand[:80]
        try:
            docs = [(meta[ids[i]]["text"] or "")[:512] for i in cand]
            # DECLARANT MANQUANT DE `rerank.wanted` (mesure 2026-08-25).
            # `forge_signal_coupling` rendait ce signal DECOY_LECTEUR_PASSIF avec ZERO
            # emetteur : la regulation lisait une intention que personne ne posait, donc
            # la lire ne changeait RIEN. Un emetteur existait pourtant — dans
            # `forge_rag_engine`, qui n'est PAS importe dans le hub. Bon code, mauvais
            # module : le meme defaut que le cutover Qdrant du matin.
            # Et on le pose A L'USAGE, pas a la panne. L'emetteur d'origine ne le posait
            # qu'une fois :8100 injoignable — un signal de DETRESSE a posteriori. Ici
            # c'est une declaration de DEPENDANCE : « ce reranker me sert MAINTENANT »,
            # ce qui est la seule forme sur laquelle une regulation peut decider avant
            # de couper.
            try:
                from nokido_agent.app.forge_embed_router import declare_wanted as _dw

                _dw("rerank.wanted", motif="rerank cross-encoder en usage par le RAG")
            except Exception as _ie:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[rag] intention rerank.wanted NON posee (%s) — le reranker reste "
                    "evincable pendant qu'on s'en sert", type(_ie).__name__)
            rb = _j.dumps({"model": "x", "query": topic, "documents": docs}).encode()
            rq = _u.Request(
                "http://127.0.0.1:8100/v1/rerank", data=rb, headers={"Content-Type": "application/json"}, method="POST"
            )
            with _u.urlopen(rq, timeout=20) as r:
                res = _j.loads(r.read()).get("results", [])
            if res and len(res) == len(cand):
                # AUTORITE DE LA SOURCE. Le cross-encoder ne repond qu'a « est-ce
                # pertinent ? », jamais a « qui parle ? » : 504k chunks de docsets
                # tiers contre 99 de doctrine souveraine, il n'a aucun moyen de
                # savoir lesquels font foi sur Nokido. Ponderation DELIBEREMENT
                # moderee (x1.0 doctrine, x0.78 docset) : elle departage a
                # pertinence comparable, elle n'ecrase pas un tiers tres pertinent.
                try:
                    from nokido_agent.app.forge_rag_qualify import trust_weight as _tw
                except Exception:  # noqa: BLE001 - jamais degrader la recherche
                    def _tw(_s):
                        return 0.5

                def _autorite(x):
                    src = meta[ids[cand[x["index"]]]].get("source") or ""
                    return x.get("relevance_score", 0.0) * (0.6 + 0.4 * _tw(src))

                res = sorted(res, key=lambda x: -_autorite(x))
                cand = [cand[x["index"]] for x in res]
                mode += "+rerank+autorite"
        except Exception:
            pass
        final = cand[:limit]
        out = []
        for i in final:
            m = meta[ids[i]]
            out.append(f"[{m['source']}] ({m['domain']}, {mode})\n{(m['text'] or '')[:400]}")
        out = self._reorder_mid(out)
        self._log_query(topic, flt, [ids[i] for i in final], int((_t.time() - _t0) * 1000))
        return "\n\n".join(out) if out else "Aucun resultat."

    def _log_query(self, topic: str, flt: dict, retrieved: list = None, latency_ms: int = 0) -> None:
        """Journalise la requete RAG (schema riche : query, filtres, ids
        retournes, latence) -> fondation du predictif (Self-Query appris, cache
        predictif, calibration RRF). Best-effort, ne casse jamais la recherche.
        """
        try:
            import json as _j
            import sqlite3 as _sq

            cx = _sq.connect(str(self.db_path), timeout=5)
            cx.execute(
                "CREATE TABLE IF NOT EXISTS query_log ("
                "id INTEGER PRIMARY KEY, query_text TEXT NOT NULL, "
                "filters_json TEXT, retrieved_chunks_ids TEXT, "
                "selected_chunk_id INTEGER, latency_ms INTEGER, "
                "timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')))"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log(timestamp)")
            cx.execute("CREATE INDEX IF NOT EXISTS idx_query_log_query ON query_log(query_text)")
            cx.execute(
                "INSERT INTO query_log (query_text, filters_json, "
                "retrieved_chunks_ids, latency_ms) VALUES (?, ?, ?, ?)",
                ((topic or "")[:500], _j.dumps(flt or {}), _j.dumps(retrieved or []), int(latency_ms)),
            )
            # T1 ADAPT (memory_decay AGY 2026-07-05) : signal d'usage — un chunk LU
            # vieillit moins vite (forge_auto_compact purge access_count<3).
            if retrieved:
                cx.execute(
                    "UPDATE rag_chunks SET access_count=COALESCE(access_count,0)+1 "
                    "WHERE id IN (%s)" % ",".join("?" * len(retrieved)),
                    [str(c) for c in retrieved],
                )
            cx.commit()
            cx.close()
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # BOMBE TROUVEE 2026-08-20 (pyflakes) : `_log_query` est une METHODE,
            # la nommer en global levait un NameError — et ce NameError naissait
            # DANS le `except`, donc rien ne le rattrapait : il remontait a
            # l'appelant. Un compteur de pertes qui transforme une perte benigne
            # en exception propagee. Compteur porte par la CLASSE (un setattr sur
            # une methode liee echouerait, lui aussi silencieusement au pire).
            _n = getattr(type(self), "_log_query_pertes", 0) + 1
            type(self)._log_query_pertes = _n
            if _n == 1 or _n % 200 == 0:
                _lg.getLogger("Nokido.Registry").warning(
                    "[query_log] journalisation de requete PERDUE (%s: %s) — %d au "
                    "total | consequence: les statistiques d'usage sous-estiment le "
                    "trafic reel", type(e).__name__, str(e)[:80], _n)

    def _rag_multi_query(self, topic: str) -> list:
        """Multi-Query : reformule la requete en variantes via LLM (:8091).
        Retourne [topic, ...variantes]. Best-effort -> [topic] si echec.
        """
        try:
            import json as _j
            import urllib.request as _u

            prompt = (
                "Reformule cette requete de recherche technique en 3 "
                "variantes courtes et distinctes, une par ligne, sans "
                "numerotation ni preambule. Requete : " + topic
            )
            body = _j.dumps(
                {"messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0.4}
            ).encode()
            rq = _u.Request(
                "http://127.0.0.1:8091/v1/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _u.urlopen(rq, timeout=25) as r:
                txt = _j.loads(r.read())["choices"][0]["message"]["content"]
            variants = [ln.strip(" -*0123456789.").strip() for ln in txt.splitlines() if len(ln.strip()) > 8]
            return [topic] + variants[:3]
        except Exception:
            return [topic]

    async def handle_md(self, args: dict, agent: str, ring: int) -> str:
        """forge.md / md (read-only Phase 1) : lecture & interaction markdown via
        forge_md_router (route/extract/lazy/index, BAML) + outline/read BAML-free.
        AUCUNE écriture (edit = Phase 2 avec gardes anti-injection, cf
        roadmap_console_exec). read/outline path-confinés ROOT + .md uniquement."""
        import json as _j
        action = args.get("action", "route")
        root = self.root
        try:
            import sys as _s
            _app = str(root / "app")
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app import forge_md_router as _mdr
        except Exception as e:  # noqa: BLE001
            return f"md: forge_md_router indispo: {e}"

        def _confine(rel: str):
            try:
                p = (root / rel).resolve()
            except Exception:  # noqa: BLE001
                return None
            r = root.resolve()
            if r != p and r not in p.parents:
                return None
            if p.suffix.lower() != ".md":
                return None
            return p

        try:
            if action == "route":
                q = args.get("query", "")
                return _j.dumps(_mdr.route_query(q, root), ensure_ascii=False, indent=2) if q else "md route: 'query' requis"
            if action == "lazy":
                q = args.get("query", "")
                return _j.dumps(_mdr.lazy_load(q, root), ensure_ascii=False, indent=2) if q else "md lazy: 'query' requis"
            if action == "index":
                return _j.dumps(_mdr.build_index(root), ensure_ascii=False, indent=2)[:8000]
            if action in ("extract", "adr"):
                p = _confine(args.get("path", ""))
                if not p or not p.exists():
                    return f"md extract: path .md invalide/hors-ROOT: {args.get('path', '')}"
                return _j.dumps(_mdr.extract_adr(str(p), root), ensure_ascii=False, indent=2)
            if action == "outline":
                p = _confine(args.get("path", ""))
                if not p or not p.exists():
                    return f"md outline: path .md invalide/hors-ROOT: {args.get('path', '')}"
                txt = p.read_text("utf-8", "replace")
                heads = [ln.rstrip() for ln in txt.splitlines() if ln.lstrip().startswith("#")]
                fm = ""
                if txt.startswith("---"):
                    _end = txt.find("\n---", 3)
                    if _end > 0:
                        fm = txt[3:_end].strip()
                return _j.dumps({"path": args.get("path", ""), "frontmatter": fm[:1000],
                                 "headings": heads[:200], "lines": txt.count("\n") + 1},
                                ensure_ascii=False, indent=2)
            if action == "read":
                p = _confine(args.get("path", ""))
                if not p or not p.exists():
                    return f"md read: path .md invalide/hors-ROOT: {args.get('path', '')}"
                return p.read_text("utf-8", "replace")[:12000]
            return f"md: action inconnue '{action}' (route|lazy|index|extract|outline|read). edit=Phase 2."
        except Exception as e:  # noqa: BLE001
            return f"md {action}: erreur: {e}"

    def _exec_console(self, cmd: str, timeout: int, agent: str, ring: int) -> dict:
        """sandbox=console (Phase 1b) : exécute une commande dans la session
        console user (user) via forge_sandbox_exec.console_exec. Gated ring-0 +
        ConsolePolicy default-deny + audit JSONL. Cf. roadmap_console_exec v4.
        Durcissement (ledger signé, park out-of-band, TPM) = Phase 1 full / 2."""
        import shlex
        import time as _tm
        import json as _cj
        import hashlib as _ch
        t0 = _tm.monotonic()

        def _el():
            return round((_tm.monotonic() - t0) * 1000)

        if int(ring) != 0:
            return {"ok": False, "stdout": "", "stderr": "SECURITY: sandbox=console requiert ring=0",
                    "elapsed_ms": _el(), "sandbox": "console"}
        try:
            argv = shlex.split(cmd, posix=True)
        except ValueError as e:
            return {"ok": False, "stdout": "", "stderr": f"console: parse error: {e}",
                    "elapsed_ms": _el(), "sandbox": "console"}
        try:
            from nokido_agent.app.forge_sandbox_exec import ConsolePolicy, console_exec
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "stdout": "", "stderr": f"console: module indispo: {e}",
                    "elapsed_ms": _el(), "sandbox": "console"}
        decision, reason = ConsolePolicy.decide(argv)
        try:  # audit JSONL (Phase 1b non signé ; ledger Ed25519 SYSTEM-only = Ph1 full)
            rec = {"ts": _tm.time(), "agent": agent, "ring": ring,
                   "exe": (argv[0] if argv else ""),
                   "args_sha256": _ch.sha256((" ".join(argv[1:])).encode()).hexdigest()[:16],
                   "decision": decision, "reason": reason}
            ap = self.root / "sandbox" / "console_exec_audit.jsonl"
            ap.parent.mkdir(parents=True, exist_ok=True)
            with open(ap, "a", encoding="utf-8") as f:
                f.write(_cj.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        if decision != "ALLOW":
            return {"ok": False, "stdout": "", "stderr": f"[console:{decision}] {reason}",
                    "elapsed_ms": _el(), "sandbox": "console", "decision": decision}
        try:
            r = console_exec(argv, timeout=min(int(timeout), 120))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "stdout": "", "stderr": f"console_exec: {e}",
                    "elapsed_ms": _el(), "sandbox": "console"}
        return {"ok": bool(r.get("ok")), "stdout": r.get("stdout", ""),
                "stderr": "" if r.get("ok") else f"rc={r.get('rc')} timed_out={r.get('timed_out')}",
                "elapsed_ms": _el(), "sandbox": "console", "rc": r.get("rc")}

    def _exec_sandboxed(self, cmd: str, sandbox: str, container: str, timeout: int, agent: str, ring: int) -> dict:
        """Execute cmd in the requested sandbox, return {ok, stdout, stderr, elapsed_ms}.

        sandbox=local    — PowerShell (win) / bash (linux), existing forge_secret_guard
        sandbox=ps_clm   — PowerShell Constrained Language Mode via forge_ps_sandbox
        sandbox=docker   — docker exec <container> sh -c "<cmd>"
        sandbox=windows  — Windows Sandbox (Hyper-V): writes .wsb, waits for output file
        """
        import sys, time as _t
        from nokido_agent.app.forge_utils import safe_shell_run

        t0 = _t.monotonic()

        def _elapsed():
            return round((_t.monotonic() - t0) * 1000)

        # ── Sanitize (all sandboxes) ───────────────────────────────────────
        try:
            from nokido_agent.app.forge_secret_guard import sanitize_shell_command

            violation = sanitize_shell_command(cmd, agent, ring)
            if violation:
                return {"ok": False, "stdout": "", "stderr": violation, "elapsed_ms": _elapsed()}
        except ImportError:
            pass

        # ── Route by sandbox type ─────────────────────────────────────────
        # Garde en PROFONDEUR : meme si un appelant contourne la validation
        # d'entree, une valeur inconnue ne doit pas glisser jusqu'a la branche
        # finale (`pwsh` in-process). Les deux gardes disent la meme chose ;
        # c'est voulu -- une frontiere de privilege ne tient pas sur un seul
        # point de controle.
        _refus_sbx = self._sandbox_valide(sandbox)
        if _refus_sbx:
            return {"ok": False, "stdout": "", "stderr": _refus_sbx,
                    "elapsed_ms": _elapsed(), "sandbox": "refuse"}

        if sandbox == "console":
            return self._exec_console(cmd, timeout, agent, ring)

        if sandbox == "ps_clm":
            # ATTESTATION DEV EXIGEE — chantier M0.1, 2026-09-12.
            #
            # Mesure : ce chemin ecrit le code FOURNI PAR LE CLIENT dans
            # `.run_tmp/ps_nokido_*.ps1` (`f.write(code)`, ligne 5 du script)
            # puis l'execute sous `NT AUTHORITY\Systeme`. Ce n'est pas « un
            # shell un peu plus puissant » : c'est un TRANSFERT DE CODE du
            # domaine client vers un executeur privilegie.
            #
            # Asymetrie qui l'a rendu visible : `console`, qui ne donne que la
            # session UTILISATEUR, est garde ring-0 default-deny ; `ps_clm`, qui
            # donne SYSTEM, ne l'etait par rien. Le garde etait inverse par
            # rapport au privilege.
            #
            # Le mecanisme d'attestation EXISTE DEJA et n'est pas duplique ici :
            # `forge_dev_mode` porte un token signe `sandbox/.dev_mode_token`,
            # bail 30 min (TTL_S=1800), verifie par SIGNATURE (CapabilityToken).
            #
            # ⚠️ CORRECTION DU 2026-09-13 — une version anterieure de ce
            # commentaire, ecrite le 2026-09-12, affirmait que l'attestation
            # etait « INARMABLE PAR LE CLIENT » et « une autorite exterieure ».
            # C'ETAIT FAUX, et mesure a l'appui : le secret de signature
            # (MCP_DEV_SECRET, IntegrityManager.from_env) est SERVI PAR LE
            # COFFRE au compte sandbox lui-meme (get_secret rend 64 car., stable
            # sur deux appels donc non ephemere), et le dossier du token est
            # inscriptible par ce compte. Un client peut donc FRAPPER un
            # CapabilityToken ring DEV valide sans l'owner. L'ACL SYSTEM+Admin
            # de `_restrict_acl` ne protege que la CONFIDENTIALITE d'un token
            # cree par arm() ; elle n'empeche pas de MINTER, puisque la
            # verification est par signature et que la cle est lisible.
            # Ce chemin reste garde par : (1) le PLANCHER DE RING ci-dessus
            # (ring <= 1), independant de l'attestation ; (2) le refus quand
            # l'attestation est absente (mesure runtime : ps_clm sans token ->
            # refus). Ce qui n'est PAS garanti, c'est l'exclusivite OWNER de
            # l'armement. Suivi : PS_CLM_DEV_BOUND dans forge_trust_domains,
            # correctif = ACL-split du coffre (action OWNER), non code.
            #
            # Aucun usage runtime n'est casse : mesure du meme jour, `ps_clm`
            # n'a AUCUN appelant fonctionnel dans le depot (les occurrences sont
            # des patches declarant l'enum, un rang d'isolation, un commentaire
            # et des tests). Seuls des clients interactifs l'employaient.
            #
            # FAIL-CLOSED : une attestation ILLISIBLE refuse. Un garde
            # indisponible ne doit jamais valoir une autorisation.
            # Fige par tests/nr/test_ps_clm_exige_attestation_dev_nr.py
            #
            # PLANCHER DE RING — ajoute le 2026-09-12, second volet du meme
            # chantier. L'attestation ci-dessous est un interrupteur GLOBAL :
            # elle dit QUE le transfert de code est permis, jamais A QUI. Une
            # fois armee par l'owner pour un motif legitime, tout appelant
            # capable d'atteindre ce handler obtenait SYSTEM — et `run` est
            # plafonne a 2 par la table RBAC, donc ring 2 (TRUSTED) suffisait.
            # L'autorite OBTENUE n'etait liee par rien a l'autorite du
            # DEMANDEUR. C'est l'asymetrie decrite plus haut, dans sa seconde
            # moitie : elle restait ouverte apres la pose de l'attestation.
            #
            # Plancher a 1 (DEV), pas 0 : l'attestation s'appelle « DEV » et le
            # canal documente de lecture du profil owner est `ps_clm` depuis un
            # client de ring 1. Un plancher a 0 le couperait meme owner-arme.
            # La comparaison avec `console` (ring 0) reste un ARBITRAGE OWNER,
            # pas une evidence : les deux n'exposent pas la meme chose.
            #
            # ORDRE VOULU : le plancher passe AVANT l'attestation. C'est le
            # controle le moins cher, et c'est ce qui rend la borne verifiable
            # sans armer quoi que ce soit — un test qui devrait armer
            # l'attestation pour verifier le ring executerait du code SYSTEM
            # pour prouver une limite.
            # Fige par tests/test_ps_clm_plancher_de_ring.py
            _PLANCHER_PS_CLM = 1
            try:
                _ring_eff = int(ring)
            except (TypeError, ValueError):
                # « ring non transmis » existe sur d'autres chemins de ce
                # module : un ring illisible vaut le MOINS privilegie, jamais
                # le plus.
                _ring_eff = 4
            if _ring_eff > _PLANCHER_PS_CLM:
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": (
                        "SECURITY: sandbox=ps_clm exige ring <= %d (ring %r "
                        "presente) — l'attestation DEV dit QUE le transfert de "
                        "code vers un executeur SYSTEM est permis, jamais A QUI."
                        % (_PLANCHER_PS_CLM, ring)
                    ),
                    "elapsed_ms": _elapsed(),
                }
            try:
                from nokido_agent.tools.forge_dev_mode import is_armed as _dev_arme

                _arme, _detail_dev = _dev_arme()
            except Exception as _e_dev:  # noqa: BLE001
                _arme = False
                _detail_dev = "attestation illisible (%s)" % type(_e_dev).__name__
            if not _arme:
                return {
                    "ok": False,
                    "stdout": "",
                    "stderr": (
                        "SECURITY: sandbox=ps_clm exige l'attestation DEV "
                        "(forge_dev_mode) — transfert de code vers un executeur "
                        "SYSTEM refuse. Etat: %s" % (_detail_dev,)
                    ),
                    "elapsed_ms": _elapsed(),
                }
            try:
                from nokido_agent.app.forge_ps_sandbox import PowerShellSandbox

                sb = PowerShellSandbox(mode="CLM", timeout=timeout)
                r = sb.run(cmd)
                return {
                    "ok": r.ok,
                    "stdout": r.stdout or "",
                    "stderr": r.stderr or "",
                    "elapsed_ms": _elapsed(),
                    "sandbox": "ps_clm",
                }
            except Exception as e:
                return {"ok": False, "stdout": "", "stderr": str(e), "elapsed_ms": _elapsed()}

        if sandbox == "docker":
            ct = container or "laforge-searxng"
            res = safe_shell_run(
                ["docker", "exec", ct, "sh", "-c", cmd],
                cwd=str(self.root),
                timeout=timeout,
            )
            return {
                "ok": res.get("code", 1) == 0,
                "stdout": res["stdout"],
                "stderr": res["stderr"],
                "elapsed_ms": _elapsed(),
                "sandbox": "docker",
            }

        if sandbox == "windows":
            return self._exec_windows_sandbox(cmd, timeout)

        if sandbox == "wasm":
            # cmd = path/to/module.wasm [func] [arg1 arg2...]  OR  wasm_url|wasm_b64
            # PARSING ROBUSTE (fix 2026-07-28) : un split() naif cassait sur les
            # ESPACES du chemin — Nokido vit dans "Script python IA", donc parts[0]
            # devenait "C:\\...\\Script" et l'open() rendait « Acces refuse ». On
            # capture le chemin ENTIER jusqu'a .wasm (ou l'URL http), puis func+args.
            import re as _re_wasm

            _c = cmd.strip()
            _m = _re_wasm.match(r"^\s*(https?://\S+|.+?\.wasm)\s*(.*)$", _c, _re_wasm.I)
            if _m:
                wasm_file = _m.group(1).strip().strip('"')
                _rest = _m.group(2).split()
            else:
                wasm_file, _rest = _c, []
            # Defaut "_start" : la fonction d'une COMMANDE WASI. "run" n'est le nom
            # d'aucune convention -- ce defaut faisait echouer TOUT module passe sans
            # fonction, sur les trois backends a la fois, donc l'echec ressemblait a une
            # chaine morte. Mesure 2026-09-06 : _selftest_add.wasm KO sans nom de
            # fonction, "7" des qu'on ecrit "add 3 4". Un module wasm32-wasip1 (le cas
            # SWE-bench) n'expose QUE _start : sans ce defaut il etait inatteignable.
            func_name = _rest[0] if _rest else "_start"
            wasm_args = [int(x) for x in _rest[1:] if x.lstrip("-").isdigit()]
            try:
                from nokido_agent.app.forge_wasm_cervelet import run_wasm_deno, run_wasm

                # Priorité 1 : Deno natif (µs, sandbox strict)
                if wasm_file.startswith("http"):
                    r = run_wasm_deno(wasm_url=wasm_file, func=func_name, args=wasm_args or None, timeout=timeout)
                elif wasm_file.endswith(".wasm"):
                    import base64 as _b64

                    b64 = _b64.b64encode(open(wasm_file, "rb").read()).decode()
                    r = run_wasm_deno(wasm_b64=b64, func=func_name, args=wasm_args or None, timeout=timeout)
                    if not r.get("ok"):
                        # Fallback : wasmtime natif puis pont WasmEdge (run_wasm).
                        # Le motif du PREMIER essai est CONSERVE : trois backends qui
                        # echouent sans dire lequel a refuse rendent le diagnostic
                        # impossible -- c'est ce qui a fait lire "chaine wasm morte"
                        # la ou seul le nom de fonction etait faux (2026-09-06).
                        _deno_err = str(r.get("error") or "").strip() or "echec sans motif"
                        r = run_wasm(wasm_file, func=func_name, args=wasm_args or None)
                        if not r.get("ok"):
                            r = dict(r)
                            r["error"] = f"{str(r.get('error') or 'sans motif')} | deno: {_deno_err}"
                else:
                    r = {"ok": False, "error": f"wasm: chemin .wasm ou URL requis (got: {wasm_file[:60]})"}
                return {
                    "ok": r.get("ok", False),
                    "stdout": str(r.get("return_value", r.get("result", ""))),
                    "stderr": r.get("error", ""),
                    "elapsed_ms": r.get("duration_ms", _elapsed()),
                    "sandbox": "wasm",
                }
            except Exception as e:
                return {"ok": False, "stdout": "", "stderr": str(e), "elapsed_ms": _elapsed(), "sandbox": "wasm"}

        if sandbox == "gvisor":
            # Tier2 : isolation kernel (gVisor, network deny) pour code untrusted.
            # Delegue a la politique TRUST->TIER (forge_exec_tier.run_sandboxed) ->
            # bridge gvisor_run. Fail-closed si gVisor indispo (untrusted ne tourne pas).
            try:
                from nokido_agent.tools.forge_exec_tier import run_sandboxed as _rsb

                r = _rsb(cmd, kind="sh", trust="untrusted", network="none", timeout=timeout)
                return {
                    "ok": bool(r.get("ok")),
                    "stdout": str(r.get("stdout", r.get("result", ""))),
                    "stderr": str(r.get("stderr", r.get("error", ""))),
                    "elapsed_ms": _elapsed(),
                    "sandbox": "gvisor",
                    "tier": r.get("tier"),
                }
            except Exception as _e_gv:
                return {"ok": False, "stdout": "", "stderr": str(_e_gv), "elapsed_ms": _elapsed(), "sandbox": "gvisor"}

        # ── local (default) ───────────────────────────────────────────────
        shell_cmd = (
            ["pwsh", "-NonInteractive", "-Command", cmd] if sys.platform == "win32" else ["/bin/bash", "-c", cmd]
        )
        res = safe_shell_run(shell_cmd, cwd=str(self.root), timeout=timeout)
        return {
            "ok": res.get("code", 1) == 0,
            "stdout": res["stdout"],
            "stderr": res["stderr"],
            "elapsed_ms": _elapsed(),
            "sandbox": "local",
        }

    def _exec_windows_sandbox(self, cmd: str, timeout: int = 60) -> dict:
        """Run cmd inside Windows Sandbox (Hyper-V lightweight VM).

        Flow: write cmd.bat + read_output.bat to shared temp folder →
        generate .wsb XML with MappedFolder → launch WindowsSandbox.exe →
        poll for output.txt → return content.
        Windows Sandbox must be enabled (Containers-DisposableClientVM).
        Boot ~3-8s; total overhead ~10-15s per call.
        """
        import subprocess, tempfile, time as _t, os
        from pathlib import Path as _P

        tmp = _P(tempfile.mkdtemp(prefix="lf_wsb_"))
        cmd_bat = tmp / "run.bat"
        out_file = tmp / "output.txt"

        # Write the command — capture stdout+stderr to shared output.txt
        cmd_bat.write_text(
            f"@echo off\r\n({cmd}) > C:\\output.txt 2>&1\r\n",
            encoding="utf-8",
        )

        wsb_xml = f"""<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{tmp}</HostFolder>
      <SandboxFolder>C:\\shared</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>cmd /c C:\\shared\\run.bat &amp;&amp; copy C:\\output.txt C:\\shared\\output.txt</Command>
  </LogonCommand>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <Networking>Disable</Networking>
</Configuration>"""
        wsb_path = tmp / "nokido.wsb"
        wsb_path.write_text(wsb_xml, encoding="utf-8")

        try:
            proc = subprocess.Popen(
                ["C:\\Windows\\System32\\WindowsSandbox.exe", str(wsb_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = _t.monotonic() + timeout
            while _t.monotonic() < deadline:
                if out_file.exists():
                    result = out_file.read_text(encoding="utf-8", errors="replace").strip()
                    proc.terminate()
                    return {
                        "ok": True,
                        "stdout": result,
                        "stderr": "",
                        "elapsed_ms": round((_t.monotonic()) * 1000),
                        "sandbox": "windows",
                    }
                _t.sleep(0.5)
            proc.terminate()
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Windows Sandbox timeout {timeout}s",
                "elapsed_ms": timeout * 1000,
                "sandbox": "windows",
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "WindowsSandbox.exe introuvable — activer Containers-DisposableClientVM",
                "elapsed_ms": 0,
                "sandbox": "windows",
            }
        finally:
            try:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

    async def handle_ps_run(self, args: dict, agent: str, ring: int) -> str:
        """
        Exécution PowerShell sandboxée 3 niveaux.
        Niveau 1: Pre-Flight liste noire (toujours actif)
        Niveau 2: Constrained Language Mode (actif si mode=CLM)
        ring=0 requis (CLAUDE/GEMINI uniquement).
        args: {code, mode=CLM|preflight|JEA, timeout=15}
        """
        code = args.get("code", "").strip()
        mode = args.get("mode", "CLM").upper()
        timeout = int(args.get("timeout", 15))
        if not code:
            return "ps_run: code vide"
        if ring > 0:
            return "SECURITY: ps_run necessite ring=0"
        try:
            from nokido_agent.app.forge_ps_sandbox import PowerShellSandbox

            sb = PowerShellSandbox(mode=mode, timeout=timeout)
            result = sb.run(code)
            sb.audit_log(code, result)
            if result.blocked_by:
                return f"[SANDBOX BLOCKED] {result.stderr}"
            if result.ok:
                return result.stdout or "(pas de sortie)"
            return f"[PS ERROR] {result.stderr[:300]}"
        except Exception as e:
            return f"ps_run error: {e}"

    async def handle_ps_agent(self, args: dict, agent: str, ring: int) -> str:
        """
        Génère ET exécute un micro-agent PowerShell avec déport cognitif.
        Méthodes : edge (M1 Ollama), rag (M2 local), goal (M3 intent), diagnostic
        args: {type=edge|rag|goal|diagnostic, intent, context, service, port...}
        """
        agent_type = args.get("type", "diagnostic")
        mode = args.get("mode", "CLM")
        timeout = int(args.get("timeout", 30))
        if ring > 0:
            return "SECURITY: ps_agent necessite ring=0"
        try:
            from nokido_agent.app.forge_ps_agent import build_agent_for_mcp

            script = build_agent_for_mcp(agent_type, args)
            from nokido_agent.app.forge_ps_sandbox import PowerShellSandbox

            sb = PowerShellSandbox(mode=mode, timeout=timeout)
            result = sb.run(script)
            sb.audit_log(f"ps_agent:{agent_type}", result)
            if result.blocked_by:
                return f"[AGENT BLOCKED] {result.stderr}"
            return result.stdout or "(agent: pas de sortie)"
        except Exception as e:
            return f"ps_agent error: {e}"

    async def handle_route_dt(self, args: dict, agent: str, ring: int) -> str:
        """Handler pour le routeur intelligent Decision Tree (job_160f1c98)."""
        prompt = args.get("prompt", "").strip()
        if not prompt:
            return "ERR: parametre 'prompt' requis"
        task_type = args.get("task_type", "")

        import sys

        sys.path.insert(0, str(self.root))
        try:
            from nokido_agent.app.forge_llm_router_dt import route_with_dt

            provider, confidence, source = route_with_dt(task_type, prompt)
            return json.dumps(
                {"provider": provider, "confidence": confidence, "source": source}, ensure_ascii=False, indent=2
            )
        except Exception as e:
            return f"ERR handle_route_dt: {type(e).__name__}: {e}"

    async def handle_route_task(self, args: dict, agent: str, ring: int) -> str:
        task_type = args.get("task_type", "code")
        payload = args.get("payload", {})
        prompt = payload.get("prompt", payload.get("task", ""))
        token = args.get("_token", "")
        entity_id = f"agt_{agent.lower()}" if agent != "HUB" else "wrk_laforge"

        # ETAPE 0 : SSoT - "point sur <domain>" -> reponse STRUCTUREE uniforme cross-CLI
        # (0 LLM si SSoT structure). Court-circuite avant tout routage : la source unique
        # prime sur la re-derivation. None si la requete ne cible aucun domaine SSoT.
        try:
            from nokido_agent.app.forge_ssot import point as _ssot_point

            _sp = _ssot_point(prompt)
            if _sp is not None:
                return json.dumps(
                    {"status": "ssot", "domain": _sp["domain"], "kind": _sp.get("kind"),
                     "source": _sp.get("source"), "answer": _sp["answer"]},
                    ensure_ascii=False,
                )
        except Exception as _se:
            logger.debug(f"[ssot] skip: {_se}")

        # ETAPE 1 : Intent-Based Routing � bypass LLM si intention connue
        try:
            from app.services.intent_router import get_intent_router

            _ir = get_intent_router()
            decision = await _ir.route(prompt, task_type=task_type, entity_id=entity_id, token=token)
            if decision["action"] == "bypass" and decision.get("plan"):
                logger.info(
                    f"[intent-router] BYPASS LLM task={decision['source_task']} conf={decision['confidence']:.2f}"
                )
                return json.dumps(
                    {
                        "status": "bypassed",
                        "plan": decision["plan"],
                        "confidence": decision["confidence"],
                        "source_task": decision["source_task"],
                    }
                )
            if decision["action"] == "suggest" and decision.get("plan"):
                payload["_intent_hint"] = decision.get("context_hint", "")
                payload["_suggested_plan"] = decision["plan"]
            elif decision.get("context_hint"):
                payload["_intent_hint"] = decision["context_hint"]
        except Exception as _ie:
            logger.debug(f"[intent-router] skip: {_ie}")

        # ETAPE 2 : Routing cognitif classique
        try:
            from nokido_agent.app.forge_cognitive_router import _estimate_complexity, _select_model

            complexity = _estimate_complexity(prompt)
            model = _select_model(complexity, ring)
            payload["_cognitive"] = {"complexity": complexity, "model": model}
        except Exception:
            pass

        # ETAPE 3 : RBAC filter tools avant envoi LLM
        try:
            from nokido_agent.app.forge_rbac import get_rbac

            if "tools" in payload:
                payload = get_rbac().filter_tools_payload(payload, entity_id, token=token)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[rbac] filtrage des outils NON applique (%s: %s) | consequence: le "
                "payload part COMPLET, l'agent voit des outils que son role devrait "
                "masquer — fail-OPEN sur le controle d'acces",
                type(e).__name__, str(e)[:100])

        # FIX wedge (2026-06-18) : route() est DÉJÀ une coroutine async bornée (timeouts
        # internes wait_for 45s/provider + cascade jamais-hang). L'ancien
        # `run_in_executor(None, lambda: asyncio.run(route(...)))` = anti-pattern triple :
        # (P0) pas de timeout EXTERNE, (P1) asyncio.run -> nouvelle event-loop par appel,
        # (P1) ThreadPoolExecutor DÉFAUT partagé -> famine de threads sous charge,
        # (P2) get_event_loop() déprécié. = LE wedge observé. On await DIRECTEMENT
        # (non bloquant, loop principale) borné par un timeout total < cap hub.
        from nokido_agent.app.forge_task_router import route

        _route_timeout = int(payload.get("timeout_total", 100))
        try:
            res = await asyncio.wait_for(route(task_type, payload), timeout=_route_timeout)
        except asyncio.TimeoutError:
            return json.dumps(
                {"status": "error", "error": f"route_task timeout total ({_route_timeout}s)"},
                ensure_ascii=False,
            )
        return str(res)

    async def handle_docker_action(self, args: dict, agent: str, ring: int) -> str:
        """docker_action : actions Docker GOUVERNEES via le broker souverain
        forge_docker_agent. Le pipe docker (npipe docker_engine) n'est accessible
        qu'a un membre du groupe docker-users -> on execute en spawn_as_trusted
        (LaForgeTrusted, a ajouter au groupe). DockerPolicy valide 2x : ici
        (fail-closed avant le spawn) + dans le process trusted. argv passe en
        base64 (anti-quoting shell). Cf. l'agent docker / forge_docker_agent."""
        import base64 as _b64
        import json as _j

        argv = args.get("argv")
        if isinstance(argv, str):
            try:
                argv = _j.loads(argv) if argv.strip().startswith("[") else argv.split()
            except Exception:  # noqa: BLE001
                argv = argv.split()
        if not isinstance(argv, list) or not argv:
            return _j.dumps({"ok": False, "error": 'argv (list) requis, ex: ["ps","-a"]'})
        argv = [str(x) for x in argv]
        # Action de CONTROLE "up"/"ensure" : demander le launch Docker au keeper
        # souverain (pose docker.wanted) -- pas une commande docker. Permet a un agent
        # de lancer Docker normalement (le keeper LocalSystem fait le launch WTS).
        if argv[0].lower() in ("up", "ensure", "daemon", "ensure_daemon", "start_daemon"):
            try:
                from nokido_agent.app.forge_sandbox_exec import spawn_as_trusted
                from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON

                _script = str(self.root / "app" / "forge_docker_agent.py")
                _r = spawn_as_trusted(f'"{LAFORGE_PYTHON}" "{_script}" --ensure-daemon', timeout=30)
                return (_r.get("stdout") or "").strip() or _j.dumps(
                    {"ok": False, "error": "ensure: no output", "stderr": (_r.get("stderr") or "")[:300]})
            except Exception as e:  # noqa: BLE001
                return _j.dumps({"ok": False, "error": f"ensure_daemon: {e}"})
        try:
            from nokido_agent.app.forge_docker_agent import decide as _decide
        except Exception as e:  # noqa: BLE001
            return _j.dumps({"ok": False, "error": f"forge_docker_agent indispo: {e}"})
        decision, reason = _decide(argv)
        if decision != "ALLOW":
            return _j.dumps({"ok": False, "decision": decision, "reason": reason, "argv": argv})
        try:
            from nokido_agent.app.forge_sandbox_exec import spawn_as_trusted
            from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON
        except Exception as e:  # noqa: BLE001
            return _j.dumps({"ok": False, "error": f"import exec: {e}"})
        timeout = int(args.get("timeout", 120))
        b64 = _b64.b64encode(_j.dumps(argv).encode()).decode()
        script = str(self.root / "app" / "forge_docker_agent.py")
        cmd = f'"{LAFORGE_PYTHON}" "{script}" --argv-b64 {b64} --timeout {timeout}'
        try:
            r = spawn_as_trusted(cmd, timeout=timeout + 15)
        except Exception as e:  # noqa: BLE001
            return _j.dumps({"ok": False, "error": f"spawn trusted: {e}"})
        out = (r.get("stdout") or "").strip()
        if not out:
            return _j.dumps({"ok": False, "error": "broker: pas de sortie",
                             "stderr": (r.get("stderr") or "")[:400]})
        return out

    async def handle_research_agent(self, args: dict, agent: str, ring: int) -> str:
        from nokido_agent.app.forge_research_agent import research_agent

        # Fix 3 RCA wedge : SearXNG+ollama sync x rounds -> JAMAIS sur l'event-loop.
        return str(
            await asyncio.to_thread(
                research_agent,
                args["objective"],
                args.get("max_rounds", 2),
                args.get("max_urls", 5),
                args.get("domain", "research"),
                args.get("provider", "auto"),
            )
        )

    async def handle_crawl(self, args: dict, agent: str, ring: int) -> str:
        """Crawl une URL -> markdown épuré + firewallé (injection indirecte).
        Seuil auto-RAG : page volumineuse -> indexée en local (NPU BGE-M3,
        0 token cloud) + pointer, au lieu de saturer le contexte du LLM."""
        from nokido_agent.app.forge_crawl_tool import crawl_url

        url = args.get("url", "")
        if not url:
            return "ERR: url requise"
        timeout = int(args.get("timeout", 15))
        # deporte hors event-loop : I/O reseau bloquante (RCA hub mort 2026-08-15)
        md = await asyncio.to_thread(crawl_url, url, timeout)
        # ~10k chars ≈ 2500 tokens : au-delà, on indexe au lieu de dumper.
        if md and not md.startswith("ERR") and len(md) > 10000:
            try:
                from nokido_agent.app.forge_web_fetch import fetch_and_ingest

                res = await asyncio.to_thread(fetch_and_ingest, url)
                if res.get("ok"):
                    return (
                        f"[Page volumineuse ({len(md)} chars) indexée en RAG local "
                        f"(domain={res.get('domain')}, {res.get('chunks')} chunks, 0 token cloud). "
                        f"Interroge-la via l'outil `rag`/`query` au lieu de tout charger.]"
                    )
            except Exception as _e:
                self.logger.debug(f"auto-RAG ingest failed: {_e}") if hasattr(self, "logger") else None
        return md

    async def handle_secret(self, args: dict, agent: str, ring: int) -> str:
        """Phase 1.4 — Acces secret WCM/env securise.

        Whitelist : seules les cles non-sensibles (TOKEN/KEY/SECRET) ou explicitement
        autorisees passent. Audit log automatique. Deblocage : attestation
        dev-mode ('tools/forge_dev_mode.py arm', console ADMIN -- action NUE,
        sans tirets).
        """
        action = args.get("action", "")
        key = args.get("key", "").strip()

        # Whitelist explicite (extensible) — patterns NON sensibles
        WHITELIST_KEYS = {
            "FORGE_HUB_URL",
            "FORGE_HUB_PORT",
            "GEMINI_POLL_MODE",
            "GEMINI_POLL_INTERVAL_S",
            "GEMINI_MODEL",
            "OLLAMA_MODEL",
            "OLLAMA_HOST",
            "SEARXNG_URL",
            "LAFORGE_ENV",
            "LAFORGE_VERSION",
            "INSTANCE_NAME",
            "BASE_URL",
        }
        # Patterns toujours sensibles (deny-list dure)
        DENY_PATTERNS = ["TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "CREDENTIAL", "PRIVATE"]

        if action == "list_keys":
            from nokido_agent.app.forge_secret_guard import log_breach_attempt as _lba

            _lba("secret_list_keys", agent, ring, None, blocked=False, extra={"action": "list_keys"})
            return json.dumps(
                {
                    "whitelist": sorted(WHITELIST_KEYS),
                    "deny_patterns": DENY_PATTERNS,
                    "note": "Seules les cles dans whitelist OU absentes des deny_patterns sont accessibles. Deblocage : attestation dev-mode ('tools/forge_dev_mode.py arm').",
                },
                indent=2,
            )

        if action not in ("get_env_var", "get_secret_from_wcm"):
            return "ERR: action invalide. Utiliser get_env_var|get_secret_from_wcm|list_keys"
        if not key:
            return "ERR: parametre 'key' requis"

        # Check deny-list (sauf si explicitement whitelist OU breakglass)
        from nokido_agent.app.forge_secret_guard import is_breakglass_active, log_breach_attempt

        is_sensitive = any(p in key.upper() for p in DENY_PATTERNS)
        is_whitelisted = key.upper() in {k.upper() for k in WHITELIST_KEYS}

        if is_sensitive and not is_whitelisted and not is_breakglass_active():
            log_breach_attempt(
                "secret_access_denied", agent, ring, None, blocked=True, extra={"key": key, "action": action}
            )
            return f"SECRET GUARD: cle '{key}' contient pattern sensible (TOKEN/KEY/SECRET/...). Whitelist requise, ou attestation dev-mode ('tools/forge_dev_mode.py arm')."

        # Audit accept
        log_breach_attempt(
            f"secret_{action}_ok",
            agent,
            ring,
            None,
            blocked=False,
            extra={"key": key, "whitelisted": is_whitelisted, "breakglass": is_breakglass_active()},
        )

        try:
            from nokido_agent.app.forge_secrets import get_secret

            if action == "get_env_var":
                # Source : os.environ d'abord, fallback get_secret
                val = os.environ.get(key) or get_secret(key)
            else:  # get_secret_from_wcm — force WCM via keyring
                try:
                    import keyring

                    val = keyring.get_password("Nokido", key) or get_secret(key)
                except Exception:
                    val = get_secret(key)

            if val is None:
                return json.dumps({"key": key, "value": None, "found": False})
            # Masquer si sensible (sauf breakglass)
            if is_sensitive and not is_breakglass_active():
                val_masked = val[:4] + "***" + val[-4:] if len(val) > 12 else "***"
                return json.dumps({"key": key, "value": val_masked, "found": True, "masked": True})
            return json.dumps({"key": key, "value": val, "found": True})
        except Exception as e:
            return f"ERR: {type(e).__name__}: {e}"

    async def handle_browser(self, args: dict, agent: str, ring: int) -> str:
        """
        Bridge vers browser-control-mcp (Firefox extension).
        Actions : get_tabs | read_page | ingest | history | status
        Prerequis : npx @eyalzh/browser-control-mcp --port 3001
        """
        import sys as _s, os as _o

        _s.path.insert(0, str(self.root / "app"))
        from nokido_agent.app.forge_browser_tool import get_tabs, read_webpage, browser_ingest_to_rag, get_history, is_available

        action = args.get("action", "status")

        if action == "status":
            ok = is_available()
            return f"browser_mcp: {'OK port 3001' if ok else 'OFFLINE (lance: npx @eyalzh/browser-control-mcp --port 3001)'}"
        if action == "get_tabs":
            return await get_tabs()
        if action == "read_page":
            return await read_webpage(tab_id=args.get("tab_id"), url=args.get("url"))
        if action == "ingest":
            return await browser_ingest_to_rag(
                url=args.get("url"), tab_id=args.get("tab_id"), domain=args.get("domain", "browser")
            )
        if action == "history":
            return await get_history(query=args.get("query", ""), max_results=int(args.get("max_results", 10)))
        return f"browser: action inconnue {action} (get_tabs|read_page|ingest|history|status)"

    async def handle_github(self, args: dict, agent: str, ring: int) -> str:
        """GitHub API tool — info|files|read|commits|branches|prs|search."""
        import urllib.request as _ur, json as _j, base64 as _b64, os as _os, urllib.parse as _up

        repo = args.get("repo", "")
        sub = args.get("sub", "info")
        path = args.get("path", "")
        _h = {"User-Agent": "LaForge/1.0", "Accept": "application/vnd.github.v3+json"}
        # Coffre d'abord (DPAPI -> WCM -> Nokido.env -> env), COMME le chemin jumeau
        # `run action=github` -- corrige lui le 2026-09-03 (4c3ff5c363b6) et laissant
        # celui-ci en arriere : deux chemins pour la meme capacite, un seul lisant la
        # politique du corps. L'environnement du process du hub est VIDE (mesure du
        # 2026-09-13), donc l'appel partait ANONYME. Sur un depot PRIVE, GitHub rend
        # alors 404 et non 403 : le meme code pour un appel MAL FORME et pour un ACCES
        # REFUSE -- c'est ce 404 qui a fait verifier des jetons, des scopes, un SSO et
        # une appartenance d'organisation pendant des heures. Le meme jeton lu au
        # coffre rend 200 (private=True, push=True), en schema `token` comme `Bearer`.
        tok = ""
        try:
            import sys as _sy

            _app = str(Path(__file__).resolve().parent)
            if _app not in _sy.path:
                _sy.path.insert(0, _app)
            from nokido_agent.app.forge_secrets import get_secret as _gs_gh

            tok = (_gs_gh("GITHUB_TOKEN") or "").strip()
        except Exception as _e_gh:  # noqa: BLE001
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[github] jeton lu hors coffre (%s) : repli sur l'environnement, "
                "couche qu'aucune rotation ne met a jour", type(_e_gh).__name__)
        if not tok:
            tok = _os.environ.get("GITHUB_TOKEN", "")
        if tok:
            _h["Authorization"] = f"token {tok}"
        base = f"https://api.github.com/repos/{repo}"
        try:
            if sub == "info":
                url = base
            elif sub == "files":
                url = f"{base}/contents/{path}"
            elif sub == "read":
                url = f"{base}/contents/{path}"
            elif sub == "commits":
                url = f"{base}/commits?per_page={args.get('limit', 15)}&path={path}"
            elif sub == "branches":
                url = f"{base}/branches"
            elif sub == "prs":
                url = f"{base}/pulls?state={args.get('state', 'all')}&per_page=20"
            elif sub == "search":
                q = args.get("query", "")
                url = f"https://api.github.com/search/code?q={_up.quote(q)}+repo:{repo}"
            else:
                return f"github sub inconnu: {sub}"
            req = _ur.Request(url, headers=_h)
            with _ur.urlopen(req, timeout=10) as r:
                d = _j.loads(r.read())
            if sub == "read" and isinstance(d, dict) and d.get("encoding") == "base64":
                content = _b64.b64decode(d["content"]).decode("utf-8", errors="replace")
                size = d.get("size", 0)
                return f"=== {path} ({size}b) ===\n" + content[:8000]
            return _j.dumps(d, ensure_ascii=False, indent=2)[:6000]
        except Exception as e:
            if not tok:
                # Un capteur ne rend pas la meme chose pour deux causes : sans jeton,
                # le 404 de GitHub ne DIT PAS si l'appel est mal forme ou l'acces
                # refuse. On nomme l'anonymat plutot que de laisser deviner.
                return (f"github ERR: {e} -- requete ANONYME : aucun jeton, ni au "
                        f"coffre ni dans l'environnement. Sur un depot PRIVE GitHub "
                        f"repond 404 et non 403, donc ce code ne distingue pas un "
                        f"appel mal forme d'un acces refuse.")
            return f"github ERR: {e}"

    async def handle_ask_claude(self, args: dict, agent: str, ring: int) -> str:
        from nokido_agent.app.forge_agent_proxy import ask_claude

        res = await ask_claude(args.get("message", ""))
        return json.dumps(res, indent=2)

    async def handle_ask_gemini(self, args: dict, agent: str, ring: int) -> str:
        from nokido_agent.app.forge_agent_proxy import ask_gemini

        res = await ask_gemini(args.get("message", ""))
        return json.dumps(res, indent=2)

    async def handle_agent_debate(self, args: dict, agent: str, ring: int) -> str:
        from nokido_agent.app.forge_agent_proxy import agent_debate

        res = await agent_debate(args.get("topic", ""), rounds=int(args.get("rounds", 3)), agents=args.get("agents"))
        return json.dumps(res, indent=2)

    async def handle_skill(self, args: dict, agent: str, ring: int) -> str:
        """
        Skills centralisés — callable par tous agents (Claude, Gemini, Cline, Docker).
        actions: list | load | search | ingest
        Source de vérité : DB rag_chunks domain='skill' + fallback fichier docs/skills/.
        """
        import hashlib as _hs

        action = args.get("action", "list")
        skills_root = self.root / "docs" / "skills"
        # P2 — grille déterministe ring (règle d'or : gate/filtre APRÈS le routage sémantique).
        try:
            from nokido_agent.app.forge_skill_policy import skill_allowed_for_ring as _ring_ok, skill_min_ring as _min_ring
        except Exception:
            def _ring_ok(_slug, _r, fm=None):
                return True

            def _min_ring(_slug, fm=None):
                return 3

        if action == "list":
            # DB d'abord
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=3)
                rows = conn.execute(
                    "SELECT DISTINCT source FROM rag_chunks WHERE domain='skill' ORDER BY source"
                ).fetchall()
                conn.close()
                if rows:
                    names = sorted({r[0].split("/")[-2] for r in rows if "/" in r[0]})
                    names = [n for n in names if _ring_ok(n, ring)]  # grille ring (post-sémantique)
                    if names:
                        return json.dumps(names)
            except Exception:
                pass
            # Fallback filesystem
            if not skills_root.exists():
                return "[]"
            return json.dumps(sorted([d.name for d in skills_root.iterdir() if d.is_dir() and _ring_ok(d.name, ring)]))

        if action == "load":
            name = args.get("name", "").strip()
            if not name:
                return "ERROR: name requis pour action=load"
            if not _ring_ok(name, ring):
                return f"ERROR: skill '{name}' requiert ring <= {_min_ring(name)} (appelant: ring {ring}) — accès refusé (moindre-privilège)"
            # DB d'abord
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=3)
                rows = conn.execute(
                    "SELECT text FROM rag_chunks WHERE domain='skill' AND source LIKE ? ORDER BY rowid",
                    (f"%/{name}/%",),
                ).fetchall()
                conn.close()
                if rows:
                    return "\n\n".join(r[0] for r in rows)
            except Exception:
                pass
            # Fallback filesystem
            skill_path = skills_root / name / "SKILL.md"
            if not skill_path.exists():
                available = (
                    sorted([d.name for d in skills_root.iterdir() if d.is_dir()]) if skills_root.exists() else []
                )
                return f"ERROR: skill '{name}' introuvable. Disponibles: {available}"
            return skill_path.read_text(encoding="utf-8", errors="replace")

        if action == "search":
            query = args.get("query", args.get("name", "")).strip()
            limit = int(args.get("limit", 5))
            if not query:
                return "ERROR: query requis pour action=search"
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=3)
                rows = conn.execute(
                    "SELECT source, substr(text,1,300) FROM rag_fts "
                    "WHERE rag_fts MATCH ? AND source LIKE '%/skills/%' "
                    "ORDER BY bm25(rag_fts) LIMIT ?",
                    (query, limit),
                ).fetchall()
                conn.close()
                if not rows:
                    return json.dumps([])
                rows = [r for r in rows if _ring_ok(r[0].split("/skills/")[-1].split("/")[0], ring)]
                return json.dumps([{"source": r[0], "preview": r[1]} for r in rows])
            except Exception as e:
                return f"ERROR search: {e}"

        if action == "ingest":
            # Ingère tous les SKILL.md de docs/skills/ + ~/.gemini/skills/ dans rag_chunks.
            # DÉPORTÉ hors event-loop (asyncio.to_thread) : le corps sync (DB loop + FTS rebuild)
            # sérialisait TOUT le hub >120s = wedge mesuré 2026-06-16. list/load lisent rag_chunks
            # (pas la FTS) → rebuild_fts_index() rendu OPT-IN (args['rebuild']=true) au lieu d'un
            # full-rebuild 531k chunks inline à chaque ingest.
            import time as _t

            do_rebuild = bool(args.get("rebuild"))

            def _do_ingest():
                ingested, skipped = [], []
                skill_dirs = []
                if skills_root.exists():
                    skill_dirs += list(skills_root.iterdir())
                gemini_skills = Path.home() / ".gemini" / "skills"
                if gemini_skills.exists():
                    skill_dirs += list(gemini_skills.iterdir())

                conn = sqlite3.connect(str(self.db_path), timeout=10)
                conn.execute("PRAGMA journal_mode=WAL")
                for d in skill_dirs:
                    if not d.is_dir():
                        continue
                    md = d / "SKILL.md"
                    if not md.exists():
                        continue
                    text = md.read_text(encoding="utf-8", errors="replace")
                    source = str(md).replace("\\", "/")
                    chunk_id = "skill_" + _hs.sha256(source.encode()).hexdigest()[:16]
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO rag_chunks(id, source, text, domain, ingested_at) VALUES(?,?,?,?,?)",
                            (chunk_id, source, text, "skill", _t.strftime("%Y-%m-%dT%H:%M:%SZ")),
                        )
                        ingested.append(d.name)
                    except Exception as e:
                        skipped.append(f"{d.name}: {e}")
                conn.commit()
                conn.close()
                # Rebuild FTS OPT-IN seulement (full rebuild = lourd ; wedge si inline).
                if do_rebuild:
                    try:
                        import sys as _s

                        _s.path.insert(0, str(self.root / "app"))
                        from nokido_agent.app.forge_self_correction import rebuild_fts_index

                        rebuild_fts_index()
                    except Exception as e:  # noqa: BLE001
                        import logging as _lg

                        # LE PLUS GRAVE DE CE FICHIER. Le lexical PRIME dans la
                        # recherche : un index FTS non reconstruit sert l'ANCIEN texte
                        # sans jamais lever d'erreur. Mesure du 2026-07-29 : le lexical
                        # etait mort sur 99,5 % du corpus et personne ne l'a vu.
                        _lg.getLogger("Nokido.Registry").error(
                            "[ingest] reconstruction de l'index FTS ECHOUEE (%s: %s) | "
                            "consequence: la recherche lexicale sert un index PERIME "
                            "sur ce qui vient d'etre ingere, sans erreur visible",
                            type(e).__name__, str(e)[:100])
                return {"ingested": ingested, "skipped": skipped,
                        "total": len(ingested), "fts_rebuilt": do_rebuild}

            # Hors event-loop : le hub reste réactif pendant l'ingest.
            result = await asyncio.to_thread(_do_ingest)
            return json.dumps(result)

        return f"ERROR: action inconnue '{action}'. Utiliser list|load|search|ingest"

    async def handle_cross_platform_fs(self, args: dict, agent: str, ring: int) -> str:
        """Handler pour le skill cross_platform_fs."""
        import sys

        sys.path.insert(0, str(self.root))
        try:
            from nokido_agent.tools.forge_cross_fs import copy_to_docker, copy_from_docker, copy_to_wsl

            action = args.get("action")
            src = args.get("src")
            dest = args.get("dest")
            distro = args.get("distro", "Debian")

            if action == "copy_to_docker":
                return copy_to_docker(src, dest)
            elif action == "copy_from_docker":
                return copy_from_docker(src, dest)
            elif action == "copy_to_wsl":
                return copy_to_wsl(src, dest, distro)
            else:
                return f"ERR: cross_platform_fs action inconnue: {action}"
        except Exception as e:
            return f"ERR handle_cross_platform_fs: {e}"

    async def handle_auto_ingest(self, args: dict, agent: str, ring: int) -> str:
        """Handler pour le skill auto_ingest (hot-folder watcher)."""
        import sys

        sys.path.insert(0, str(self.root))
        try:
            from nokido_agent.app.forge_hot_ingest import get_watcher

            action = args.get("action", "status")
            watcher = get_watcher()

            if action == "status":
                return f"auto_ingest: {'RUNNING' if watcher._running else 'STOPPED'} | seen: {len(watcher._seen)} files"
            elif action == "scan":
                watcher._scan()
                return f"auto_ingest: scan manuel effectué. files seen: {len(watcher._seen)}"
            elif action == "start":
                watcher.start()
                return "auto_ingest: watcher démarré."
            elif action == "stop":
                watcher.stop()
                return "auto_ingest: watcher arrêté."
            else:
                return f"ERR: auto_ingest action inconnue: {action}"
        except Exception as e:
            return f"ERR handle_auto_ingest: {e}"

    async def handle_react_orchestrate(self, args: dict, agent: str, ring: int) -> str:
        """Handler pour la boucle ReAct autonome (job_160f1c98)."""
        task = args.get("task", "").strip()
        if not task:
            return "ERR: parametre 'task' requis"

        import sys

        sys.path.insert(0, str(self.root))
        try:
            from nokido_agent.tools.forge_orchestrate_react import run_react
            import json as _j

            res = run_react(task, ring=ring, max_steps=args.get("max_iter", 12))
            return _j.dumps(res, ensure_ascii=False, indent=2)
        except ImportError:
            return "ERR: forge_orchestrate_react.py introuvable dans tools/"
        except Exception as e:
            return f"ERR handle_react_orchestrate: {type(e).__name__}: {e}"

    async def handle_orchestrate(self, args: dict, agent: str, ring: int) -> str:  # noqa: C901
        """
        Moteur d'orchestration (forge_orchestrate_loop, Ollama).
        - detach=True    : lance en tâche de fond, retourne un run_id IMMÉDIAT (ne bloque
                           plus l'appel MCP au-delà du cap 120s ; "déporter le long").
        - status_id=<id> : état/résultat d'un run détaché.
        In-process : un run détaché NE survit PAS à un restart du hub. Pour de la
        durabilité event-sourced (resume-from-step) -> forge_durable_workflow.
        """
        import json as _j
        import sys

        sys.path.insert(0, str(self.root))
        if not hasattr(self, "_orch_runs"):
            self._orch_runs = {}

        sid = args.get("status_id")
        if sid:
            st = self._orch_runs.get(sid)
            if st is None:  # pas en mémoire -> peut-être un run DURABLE (survit au restart)
                try:
                    from nokido_agent.tools.forge_orchestrate_loop import durable_run_status

                    st = durable_run_status(sid)
                except Exception:
                    st = None
            return _j.dumps(st or {"error": f"run_id inconnu: {sid}"}, ensure_ascii=False)

        task = args.get("task", args.get("prompt", "")).strip()
        if not task:
            return "ERR: paramètre 'task' requis"

        if args.get("detach"):
            import uuid as _uuid

            rid = "orch_" + _uuid.uuid4().hex[:10]
            self._orch_runs[rid] = {"status": "running", "task": task[:120]}
            if len(self._orch_runs) > 64:  # purge grossière des plus anciens
                for _k in list(self._orch_runs)[:-32]:
                    self._orch_runs.pop(_k, None)
            _runs = self._orch_runs
            _mi = int(args.get("max_iter", 12))
            _durable = bool(args.get("durable"))

            async def _bg():
                try:
                    from nokido_agent.tools.forge_orchestrate_loop import _run_loop_async as _rl, _run_loop_durable as _rd

                    if _durable:  # event-sourced : survit au restart, replay-on-resume
                        r = await asyncio.to_thread(_rd, task, rid, _mi)
                    else:
                        r = await _rl(task, max_steps=_mi)
                    _runs[rid] = {"status": "done", "result": r}
                except Exception as _e:
                    _runs[rid] = {"status": "error", "error": str(_e)}

            asyncio.ensure_future(_bg())
            return _j.dumps({"run_id": rid, "status": "running", "durable": _durable,
                             "poll": f"orchestrate(status_id='{rid}')"}, ensure_ascii=False)

        try:
            from nokido_agent.tools.forge_orchestrate_loop import _run_loop_async

            res = await _run_loop_async(task, max_steps=args.get("max_iter", 12))
            return _j.dumps(res, ensure_ascii=False, indent=2)
        except ImportError:
            return await self._handle_orchestrate_legacy(args, agent, ring)
        except Exception as e:
            return f"ERR handle_orchestrate: {e}"

    async def handle_loop_orchestrate(self, args: dict, agent: str, ring: int) -> str:
        """
        [T_TOKEN_LOOP] Boucle autonome via GOAP + autonomous_loop_state.
        Analyse les patterns récurrents et lance des micro-agents.
        """
        import time as _t, json as _j
        from nokido_agent.tools.forge_orchestrate_loop import _hub_dispatch

        pattern = args.get("pattern", "health_check")
        max_steps = int(args.get("max_steps", 10))

        # 1. Update state
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.execute("INSERT OR IGNORE INTO autonomous_loop_state (pattern, enabled) VALUES (?, 1)", (pattern,))
            conn.commit()
            conn.close()
        except Exception:
            pass

        # 2. Plan & Execute
        goal = f"Exécuter la boucle autonome pour le pattern: {pattern}. Vérifier l'état, diagnostiquer les écarts et corriger via MCP."
        try:
            plan = await GoalPlanner.plan(goal, ring_max=ring)
            if not plan.subgoals:
                return f"OK: No actions needed for {pattern}"

            traj = await execute_plan(plan, dispatch_fn=_hub_dispatch)

            # 3. Log result
            status = "ok" if traj.ok else "error"
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=5)
                conn.execute(
                    "UPDATE autonomous_loop_state SET last_run=?, last_status=? WHERE pattern=?",
                    (_t.time(), status, pattern),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

            return _j.dumps(
                {
                    "ok": traj.ok,
                    "pattern": pattern,
                    "steps": len(traj.steps),
                    "summary": [s.intent for s in traj.steps],
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return f"ERR loop_orchestrate: {e}"

    async def _handle_orchestrate_legacy(self, args: dict, agent: str, ring: int) -> str:
        """Ancien moteur d'orchestration via llama-server :8091."""
        task = args.get("task", args.get("prompt", "")).strip()
        max_iter = int(args.get("max_iter", 10))
        model = args.get("model", "laforge-coder")
        temperature = float(args.get("temperature", 0.2))
        requested = args.get("tools", [])  # [] → all tools of the ring

        # --- Build tool schemas ---
        available = self.get_tool_list(ring=ring, agent=agent)
        available = [t for t in available if t["name"] != "orchestrate"]  # no recursion
        if requested:
            available = [t for t in available if t["name"] in requested]

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            for t in available
        ]

        server_url = os.environ.get("LLAMACPP_URL", "http://127.0.0.1:8091")
        if server_url.endswith(":8090") or server_url.endswith(":8080"):
            server_url = "http://127.0.0.1:8091"

        messages: List[Dict] = [
            {
                "role": "system",
                "content": (
                    "Tu es Nokido, un orchestrateur IA autonome. "
                    "Utilise les outils MCP disponibles pour accomplir la tâche. "
                    "Appelle les outils dans l'ordre logique, synthétise le résultat final en français."
                ),
            },
            {"role": "user", "content": task},
        ]

        trace: List[Dict] = []

        def _call_llm(msgs: list) -> dict:
            import urllib.request as _ur

            payload = json.dumps(
                {
                    "model": model,
                    "messages": msgs,
                    "tools": openai_tools,
                    "tool_choice": "auto",
                    "max_tokens": 2048,
                    "temperature": temperature,
                }
            ).encode()
            req = _ur.Request(
                f"{server_url}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with _ur.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())

        loop = asyncio.get_event_loop()

        for i in range(max_iter):
            try:
                resp = await loop.run_in_executor(None, lambda m=list(messages): _call_llm(m))
            except Exception as exc:
                return json.dumps({"error": f"llm_call iter={i}: {exc}", "trace": trace})

            choice = resp.get("choices", [{}])[0]
            finish_reason = choice.get("finish_reason", "stop")
            msg = choice.get("message", {})

            # Append assistant turn
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []

            if finish_reason != "tool_calls" or not tool_calls:
                # Fallback: Qwen/local models emit markdown ```json{"name":..,"arguments":..}```
                # instead of structured tool_calls. Parse and continue loop.
                content = msg.get("content", "") or ""
                parsed_tc = _parse_markdown_tool_call(content)
                if parsed_tc:
                    tool_calls = parsed_tc
                    # patch message so "tool" reply has a valid tool_call_id
                    msg["tool_calls"] = tool_calls
                elif finish_reason != "tool_calls":
                    return json.dumps(
                        {
                            "result": content,
                            "iterations": i + 1,
                            "model": resp.get("model", model),
                            "trace": trace,
                        }
                    )
                else:
                    # finish_reason said tool_calls but list is empty — treat as done
                    return json.dumps({"result": content, "iterations": i + 1, "trace": trace})

            # Dispatch each tool call
            for tc in tool_calls:
                tc_id = tc.get("id", f"call_{i}_{tc.get('function', {}).get('name', '?')}")
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tc_args = json.loads(fn.get("arguments", "{}") or "{}")
                except (json.JSONDecodeError, TypeError):
                    tc_args = {}

                trace.append({"iter": i, "tool": tool_name, "args": str(tc_args)[:200]})
                logger.info(f"[orchestrate] i={i} tool={tool_name} args={str(tc_args)[:120]}")

                try:
                    tool_result = await self.dispatch(
                        tool_name,
                        tc_args,
                        agent=f"orchestrate/{agent}",
                        ring=ring,
                    )
                except Exception as exc:
                    tool_result = f"ERR {type(exc).__name__}: {exc}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": str(tool_result)[:4000],
                    }
                )

        # max_iter reached
        last = messages[-1].get("content", "") if messages else ""
        return json.dumps(
            {
                "result": "max_iter atteint",
                "iterations": max_iter,
                "trace": trace,
                "last_content": last[:500],
            }
        )

    def _get_ring_needed(self, name: str, args: Dict[str, Any]) -> int:
        # Règle d'Or : vérifier forge_tools.min_ring en DB (source de vérité)
        try:
            # Le bareme d'autorisation ne se lit plus dans la base que le compte
            # client ECRIT (mesure 2026-09-13 : `LaForgeSandboxUsers` y avait
            # l'ecriture). `authority_path()` est resolu A CHAQUE APPEL ; tant que
            # l'interrupteur `etat_protege/authority.switch` est absent, il rend la
            # base RAG et le comportement est strictement inchange.
            from nokido_agent.app.forge_db_path import (
                authority_path as _autorite,
                authority_switch_actif as _bascule,
            )

            # Tant que l'interrupteur n'est pas pose, on lit la base du registre
            # (`self.db_path`) : c'est le comportement historique, et surtout c'est
            # la base que les tests INJECTENT. Emprunter `authority_path()` sans
            # condition l'ignorait -- 33 echecs a la CI du 2026-09-13, dont
            # `test_bareme_ring_is_active` : un outil DESACTIVE redevenait autorise
            # parce que la table lue n'etait plus celle du test. Une redirection
            # qui court-circuite le point d'injection casse la testabilite avant
            # de casser la production.
            _src = _autorite() if _bascule() else str(self.db_path)
            conn = sqlite3.connect(_src, timeout=3)
            row = conn.execute("SELECT min_ring, is_active FROM forge_tools WHERE tool_name=?", (name,)).fetchone()
            conn.close()
            if row:
                if not row[1]:  # is_active=0 (ou NULL) -> outil COUPE
                    # Le site appelant refuse si `ring > ring_needed`. Dans ce
                    # comparateur, GRAND = PERMISSIF : l'ancien `return 99`,
                    # commente « bloque », ne refusait AUCUN ring (0..4), donc
                    # couper un outil le rendait plus permissif que le laisser
                    # actif. Inversion de sens mesuree le 2026-09-12.
                    #
                    # La sentinelle doit etre STRICTEMENT INFERIEURE au plus
                    # petit ring legal — MASTER vaut -1, donc -1 ne suffit pas
                    # (`-1 > -1` est faux et MASTER passait encore ; trou
                    # residuel attrape par le NR, que le premier correctif
                    # laissait ouvert). Couper un outil est une decision de
                    # configuration, pas une question de privilege : elle vaut
                    # pour tous les rings, MASTER compris. Reactiver la ligne
                    # est le geste prevu pour revenir en arriere.
                    # Verrouille par tests/test_bareme_ring_is_active.py (TDD)
                    # et tests/nr/test_sentinelle_de_blocage_nr.py (invariant).
                    return -99
                return row[0]  # min_ring depuis DB
        except Exception as e:
            import logging as _lg

            _lg.getLogger("Nokido.Registry").warning(
                "[ring] barreme lu en base INDISPONIBLE (%s) | consequence: repli sur "
                "les valeurs codees en dur, la politique appliquee n'est plus celle "
                "de la base", type(e).__name__)
        # Fallback hardcodé si DB indisponible
        if name == "agy_config":
            return 1 if args.get("action") == "write" else 3
        if name in ("agy_run", "agy_add_dir"):
            return 2
        if name in ("write", "set_mode"):
            return 0
        if name == "run":
            if args.get("action") in ("python", "github", "hub_restart"):
                return 0
            return 1
        if name in ("trigger_autonomous_evolution", "auto_test", "index_result", "ask_agent", "web_search", "governed_edit"):
            return 1
        return 2

    # ── GRAPH TOOLS (CVE propagation, PPR, edge scoring) ─────────────────────
    # Remis DANS la classe le 2026-09-27. Depuis f40e0dc7f (2026-05-20) ces trois
    # handlers etaient colles en fin de fichier, APRES le `return` de la fonction
    # module `_parse_markdown_tool_call` : code mort. Les outils etaient annonces au
    # catalogue MCP et servis « Outil inconnu » (sonde vivante graph_ppr, meme jour).
    # Verrouille par tests/test_forge_mcp_registry_namespace.py (cible d'alias morte).

    async def handle_graph_edge_score(self, args: dict, agent: str, ring: int) -> str:
        try:
            import sys as _s, os as _o

            _ap = str(_o.path.join(_o.path.dirname(__file__)))
            if _ap not in _s.path:
                _s.path.insert(0, _ap)
            from nokido_agent.app.forge_graph_edge_scorer import score_edge

            result = score_edge(
                src=args.get("src", ""),
                dst=args.get("dst", ""),
                edge_type=args.get("edge_type", "call"),
                metadata=args.get("metadata", {}),
            )
            return json.dumps({"score": result, "src": args.get("src"), "dst": args.get("dst")})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def handle_graph_cve_propagate(self, args: dict, agent: str, ring: int) -> str:
        try:
            import sys as _s, os as _o

            _ap = str(_o.path.join(_o.path.dirname(__file__)))
            if _ap not in _s.path:
                _s.path.insert(0, _ap)
            from nokido_agent.app.forge_graph_cve_propagation import propagate_cve
            from nokido_agent.app.forge_graph_linker import GraphLinker

            gl = GraphLinker(db_path=str(self.db_path))
            # Build adjacency dict from linker
            all_nodes: set = set()
            raw_edges: dict = {}
            entry = args.get("entry_module", "")
            frontier = [entry] if entry else []
            visited_build: set = set()
            depth_limit = int(args.get("max_depth", 3)) + 1
            for _ in range(depth_limit):
                next_f = []
                for node in frontier:
                    if node in visited_build:
                        continue
                    visited_build.add(node)
                    all_nodes.add(node)
                    neighbors = gl.get_neighbors(node)
                    raw_edges[node] = [dst for dst, _, _ in neighbors]
                    next_f.extend(dst for dst, _, _ in neighbors if dst not in visited_build)
                frontier = next_f
                if not frontier:
                    break
            result = propagate_cve(
                cve_id=args.get("cve_id", "CVE-UNKNOWN"),
                entry_module=entry,
                graph=raw_edges,
                max_depth=int(args.get("max_depth", 3)),
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def handle_graph_ppr(self, args: dict, agent: str, ring: int) -> str:
        try:
            import sys as _s, os as _o

            _ap = str(_o.path.join(_o.path.dirname(__file__)))
            if _ap not in _s.path:
                _s.path.insert(0, _ap)
            from nokido_agent.app.forge_graph_ppr import ppr
            from nokido_agent.app.forge_graph_linker import GraphLinker

            gl = GraphLinker(db_path=str(self.db_path))
            seed = args.get("seed", "")
            alpha = float(args.get("alpha", 0.85))
            max_iter = int(args.get("max_iter", 50))
            frontier = [seed]
            visited_build: set = set()
            raw_edges: dict = {}
            for _ in range(int(args.get("depth", 3)) + 1):
                next_f = []
                for node in frontier:
                    if node in visited_build:
                        continue
                    visited_build.add(node)
                    neighbors = gl.get_neighbors(node)
                    raw_edges[node] = [dst for dst, _, _ in neighbors]
                    next_f.extend(dst for dst, _, _ in neighbors if dst not in visited_build)
                frontier = next_f
                if not frontier:
                    break
            scores = ppr(graph=raw_edges, seed=seed, alpha=alpha, max_iter=max_iter)
            top = sorted(scores.items(), key=lambda x: -x[1])[:20]
            return json.dumps({"seed": seed, "top_nodes": [{"node": n, "score": s} for n, s in top]})
        except Exception as e:
            return json.dumps({"error": str(e)})


import re as _re


def _parse_markdown_tool_call(content: str) -> list:
    """Extract tool_calls from Qwen/local model markdown output.

    Supports:
      ```json\n{"name": "X", "arguments": {...}}\n```
      {"name": "X", "arguments": {...}}   (bare JSON anywhere in content)
    Returns list of OpenAI-style tool_call dicts, or [] if none found.
    """
    if not content:
        return []
    # Strip markdown fences
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, _re.DOTALL)
    raw = m.group(1) if m else content.strip()
    # Try to find outermost JSON object
    if not m:
        start = raw.find("{")
        if start == -1:
            return []
        raw = raw[start:]
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Try extracting first {...} block
        m2 = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m2:
            return []
        try:
            obj = json.loads(m2.group(0))
        except (json.JSONDecodeError, ValueError):
            return []
    name = obj.get("name") or obj.get("function", {}).get("name", "")
    args = obj.get("arguments") or obj.get("parameters") or {}
    if not name:
        return []
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            pass
    tc_id = f"md_{name}_{int(time.time())}"
    return [
        {
            "id": tc_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }
    ]


_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        # Cold-wedge RCA 2026-07-07 : pre-warm dense au boot du singleton
        # hub (thread daemon race-garde) -> le 1er rag search ne gele plus
        # le hub. Opt-out : LAFORGE_RAG_PREWARM=0.
        if os.environ.get("LAFORGE_RAG_PREWARM", "1") != "0":
            try:
                _registry._dense_refresh_bg()
            except Exception:
                pass
    return _registry
