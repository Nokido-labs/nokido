"""
forge_goap.py — Goal-Oriented Action Planning (GOAP)
=====================================================
DATE:2026-05-03 | VER:v1_goap_cortex_prefrontal
#FORGE:[score:95|agent:agt_gemini|temp:0.00|risk:0.10|ast:OK|test:OK|color:GREEN|attempt:2]

Organe      : Cortex prefrontal (planification hiérarchique)
Vascularisation :
  - Input   : goal (str, langage naturel) + context (dict) + ring (int 0-4)
  - LLM     : forge_cognitive_router.route_task (sélection modèle auto)
  - Whitelist: forge_trajectory.ALLOWED_METHODS (intents JSON-RPC)
  - Tracking: forge_trajectory.Trajectory + persist_trajectory
  - Output  : PlanTree → List[Intent] JSON-RPC dispatchables
Hémorragie  : crash GOAP → ForgeOrchestrator fallback SiloDomain direct (non-fatal)

Pattern Ruflo GOAP adapté Python-natif Nokido. Différence clé vs Ruflo :
- JSON-RPC strict (ALLOWED_METHODS whitelist, pas d'actions arbitraires)
- Ring-aware (ring 3/4 = exegol bloqué si ring contexte < requis)
- Persistence SQLite (plans dans embeddings.db table goap_plans)
- Intégration forge_trajectory pour tracking cross-session

STATUT: GREEN — implémentation LLM-backed + parallel execution OK.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from nokido_agent.app.forge_trajectory import (
    ALLOWED_METHODS,
    Trajectory,
    TrajectoryStep,
    parse_intent,
    persist_trajectory,
    IntentValidationError,
    SYSTEM_PROMPT_JSON_MODE,
)

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:goap|organ:cortex_prefrontal|phase:skeleton]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# ============================================================
# System prompt GOAP — LLM decompose goal → plan JSON
# ============================================================
GOAP_SYSTEM_PROMPT = """\
Tu es le planificateur GOAP (Goal-Oriented Action Planning) de Nokido.
Reçois un goal en langage naturel. Décompose-le en plan JSON strict.

FORMAT DE SORTIE OBLIGATOIRE (un seul objet JSON, aucun texte hors JSON) :
{{
  "goal": "<goal reçu>",
  "plan_id": "<uuid court>",
  "parallel": false,
  "subgoals": [
    {{
      "name": "<sous-objectif>",
      "actions": [
        {{"jsonrpc":"2.0","method":"<méthode>","params":{{}},"id":"<uuid>"}}
      ]
    }}
  ]
}}

CONTRAINTES RING — tu ne peux inclure une méthode que si son ring <= ring_max :
  ring 0 : result, error, set_opsec_level
  ring 1 : run_python, run_shell, rag_ingest, sanitize_text, detect_lab, opsec_status
  ring 2 : embed, rag_search, swarm_vectorize, web_search, crawl, llm_call, llm_route, notify, event_publish, get_file_skeleton, get_function_dependencies, blackboard_read_zone, blackboard_propose_fact
  ring 3 : nmap, exegol_scan
  ring 4 : bruteforce_ssh

ring_max actuel : {ring_max}

MÉTHODES DISPONIBLES : {methods}

HEURISTIQUES CODE (économie de contexte, anti lost-in-the-middle) :
- AVANT d'éditer/écrire du code : d'abord get_file_skeleton(file_path) pour
  l'architecture, puis get_function_dependencies(function_name, file_path) pour
  l'impact (callers/callees). Ne jamais charger un fichier entier si squelette +
  corps ciblé suffisent. IMPÉRATIF : passe le chemin de fichier EXACT cité dans le
  goal (copie-le caractère pour caractère ; ne devine pas, ne substitue JAMAIS un
  autre fichier issu du contexte RAG).
- APRÈS une découverte réutilisable (fait, bug, contrainte) : blackboard_propose_fact
  (zone_name, fact). Consulter l'état partagé via blackboard_read_zone(zone_name).

Si le goal est impossible avec les méthodes disponibles : retourne
{{"goal":"...","plan_id":"...","parallel":false,"subgoals":[],"error":"raison"}}
"""


# ============================================================
# Structures de données
# ============================================================
@dataclass
class SubGoal:
    name: str
    actions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PlanTree:
    goal: str
    plan_id: str = field(default_factory=lambda: f"goap_{uuid.uuid4().hex[:10]}")
    subgoals: List[SubGoal] = field(default_factory=list)
    parallel: bool = False
    ring_max: int = 2
    created_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "plan_id": self.plan_id,
            "parallel": self.parallel,
            "ring_max": self.ring_max,
            "created_at": self.created_at,
            "error": self.error,
            "subgoals": [{"name": sg.name, "actions": sg.actions} for sg in self.subgoals],
        }

    def flat_actions(self) -> List[Dict[str, Any]]:
        """Aplatir toutes les actions en séquence."""
        return [a for sg in self.subgoals for a in sg.actions]

    def action_count(self) -> int:
        return sum(len(sg.actions) for sg in self.subgoals)


class GOAPError(Exception):
    pass


class GoalPlanner:
    """Cortex préfrontal : Planification d'objectifs (tool=plan)."""

    @staticmethod
    async def plan(goal: str, context: Optional[Dict[str, Any]] = None, ring_max: int = 2) -> PlanTree:
        """Point d'entrée unique pour la décomposition d'un goal."""
        return await decompose_goal(goal, context=context, ring_max=ring_max)


def warm() -> bool:
    """Charge laforge-qwen en RAM (keep_alive) pour tuer le cold-start du 1er
    plan (>120s à froid sur APU -> fast_path). Best-effort. À lancer dans un
    thread au boot du hub (non bloquant). Modèle = celui de decompose_goal."""
    try:
        import requests as _req

        _req.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": _planner_model(),
                "messages": [{"role": "user", "content": "ok"}],
                "stream": False,
                "options": {"num_predict": 1},
                "keep_alive": "10m",
            },
            timeout=120,
        )
        return True
    except Exception:
        return False


# ============================================================
# Persistence SQLite
# ============================================================
def persist_plan(plan: PlanTree, db_path: Optional[Path] = None) -> bool:
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goap_plans (
                plan_id TEXT PRIMARY KEY,
                goal TEXT,
                plan_json TEXT,
                ring_max INTEGER,
                created_at REAL
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO goap_plans VALUES (?,?,?,?,?)",
            (plan.plan_id, plan.goal, json.dumps(plan.to_dict(), ensure_ascii=False), plan.ring_max, plan.created_at),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ============================================================
# Cache de plans en-process (latence : skip l'appel LLM ~40-50s si un goal +
# context identique a été planifié récemment — gros gain sur les goals récurrents
# de la boucle autonome type health_check). Borné, TTL court, perdu au restart.
# ============================================================
_PLAN_CACHE: dict = {}
_PLAN_CACHE_TTL = 600.0  # 10 min
_PLAN_CACHE_HITS = 0
_PLAN_CACHE_MISSES = 0


def _planner_model() -> str:
    """Modèle du planner GOAP (goals OUVERTS uniquement — les goals CODE bypassent
    le LLM via le template-planner). Configurable via LAFORGE_PLANNER_MODEL pour
    pointer un modèle plus fort (ex: deepseek-r1:14b, qwen2.5-coder:32b, ou un
    provider cloud) sans toucher au code. Défaut = laforge-qwen:latest."""
    import os

    return os.environ.get("LAFORGE_PLANNER_MODEL", "laforge-qwen:latest")


def _plan_cache_key(goal: str, context: Optional[Dict[str, Any]], ring_max: int) -> str:
    """Clé = goal + ring SEULEMENT (context EXCLU). Sur le chemin orchestrate le
    `context` contient le preflight RAG (résultats variables par run : rerank,
    access_count) → l'inclure donnait une clé différente à chaque appel → cache
    JAMAIS touché (constaté : 2 runs identiques re-planifiés ~170s). Goal+ring
    → les goals récurrents (boucle autonome) hit enfin le cache (TTL 10min borne
    le risque d'un plan obsolète sur context changé)."""
    import hashlib

    return hashlib.sha256(f"{ring_max}\x00{goal}".encode("utf-8")).hexdigest()[:16]


def plan_cache_stats() -> dict:
    """Observabilité du cache de plans (hit-rate sur les goals récurrents)."""
    tot = _PLAN_CACHE_HITS + _PLAN_CACHE_MISSES
    return {
        "hits": _PLAN_CACHE_HITS,
        "misses": _PLAN_CACHE_MISSES,
        "hit_rate": round(_PLAN_CACHE_HITS / tot, 3) if tot else 0.0,
        "size": len(_PLAN_CACHE),
    }


def invalidate_plan_cache() -> int:
    """Vide le cache de plans — a appeler quand les capacites changent (nouvel outil
    forge) : sinon les goals recurrents servent un plan obsolete jusqu'au TTL."""
    n = len(_PLAN_CACHE)
    _PLAN_CACHE.clear()
    return n


def _sanitize_plan(plan, goal: str):
    """Grille corrige Réseau : le petit LLM planner substitue le fichier (depuis
    le RAG context) et met parfois un CHEMIN en zone_name. On IMPOSE de façon
    déterministe le chemin .py EXACT du goal aux tools code, et on rejette un
    zone_name qui est un chemin de fichier. Le LLM ne décide plus de ces champs."""
    import re

    m = re.search(r"[\w./\\-]+\.py", goal or "")
    goal_path = m.group(0).replace("\\", "/") if m else None
    _CODE = {"get_file_skeleton", "get_function_dependencies", "read_function_body"}
    try:
        for sg in plan.subgoals:
            for a in sg.actions:
                if not isinstance(a, dict):
                    continue
                method = a.get("method")
                params = a.get("params")
                if not isinstance(params, dict):
                    continue
                # override déterministe du fichier ciblé par le chemin EXACT du goal
                if goal_path and method in _CODE and params.get("file_path") not in (None, goal_path):
                    params["file_path"] = goal_path
                # zone_name ne doit JAMAIS être un chemin de fichier
                if method in ("blackboard_read_zone", "blackboard_propose_fact"):
                    zn = str(params.get("zone_name", ""))
                    if zn.endswith(".py") or "/" in zn or "\\" in zn:
                        params["zone_name"] = "discovered_facts"
    except Exception:
        pass
    return plan


def _template_plan(goal: str, ring_max: int):
    """Planner DÉTERMINISTE pour goals code à forme reconnaissable. Bypass le LLM
    (petit modèle instable : hallucine le fichier/les tools) → plan FIXE fiable,
    zéro latence Ollama, 100% reproductible. None si aucun template ne matche
    (-> fallback planner LLM)."""
    import re

    g = goal or ""
    gl = g.lower()
    pm = re.search(r"[\w./\\-]+\.py", g)
    path = pm.group(0).replace("\\", "/") if pm else None
    if not path:
        return None
    fm = re.search(r"fonction\s+`?([A-Za-z_]\w*)`?", g) or re.search(r"`([A-Za-z_]\w*)`", g)
    func = fm.group(1) if fm else None
    if func and any(k in gl for k in ("caller", "callee", "dépendance", "dependance",
                                       "impact", "appelle", "appelé", "appelée")):
        actions = [
            {"jsonrpc": "2.0", "method": "get_file_skeleton", "params": {"file_path": path}, "id": "t1"},
            {"jsonrpc": "2.0", "method": "get_function_dependencies",
             "params": {"function_name": func, "file_path": path}, "id": "t2"},
        ]
    elif func and any(k in gl for k in ("test", "teste", "pytest", "unittest", "couvre", "couverture")):
        # test-gen : prélude-inspection (corps + dépendances pour savoir quoi mocker).
        # La génération du test (créatif) reste à l'agent/LLM, mais grounded.
        actions = [
            {"jsonrpc": "2.0", "method": "read_function_body",
             "params": {"file_path": path, "function_name": func}, "id": "t1"},
            {"jsonrpc": "2.0", "method": "get_function_dependencies",
             "params": {"function_name": func, "file_path": path}, "id": "t2"},
        ]
    elif func and any(k in gl for k in ("refactor", "refactore", "réécris", "reecris",
                                        "optimise", "améliore", "amélior")):
        # refactor : prélude-inspection complète (squelette + impact + corps) AVANT
        # toute édition. NE modifie PAS (déterministe = sûr) ; l'edit reste décidé après.
        actions = [
            {"jsonrpc": "2.0", "method": "get_file_skeleton", "params": {"file_path": path}, "id": "t1"},
            {"jsonrpc": "2.0", "method": "get_function_dependencies",
             "params": {"function_name": func, "file_path": path}, "id": "t2"},
            {"jsonrpc": "2.0", "method": "read_function_body",
             "params": {"file_path": path, "function_name": func}, "id": "t3"},
        ]
    elif func and any(k in gl for k in ("corps", "implémentation", "implementation",
                                         "montre la fonction", "affiche la fonction",
                                         "lis la fonction", "source de la fonction", "body")):
        actions = [{"jsonrpc": "2.0", "method": "read_function_body",
                    "params": {"file_path": path, "function_name": func}, "id": "t1"}]
    elif any(k in gl for k in ("squelette", "structure", "skeleton", "architecture", "signatures")):
        actions = [{"jsonrpc": "2.0", "method": "get_file_skeleton", "params": {"file_path": path}, "id": "t1"}]
    else:
        return None
    raw = json.dumps({"goal": goal, "plan_id": "tmpl", "parallel": False,
                      "subgoals": [{"name": "code_analysis", "actions": actions}]}, ensure_ascii=False)
    try:
        return _parse_plan_response(raw, goal, ring_max)
    except Exception:
        return None


def load_plan(plan_id: str, db_path: Optional[Path] = None) -> Optional[PlanTree]:
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT plan_json FROM goap_plans WHERE plan_id=?", (plan_id,)).fetchone()
        conn.close()
        if not row:
            return None
        d = json.loads(row[0])
        plan = PlanTree(
            goal=d["goal"],
            plan_id=d["plan_id"],
            parallel=d.get("parallel", False),
            ring_max=d.get("ring_max", 2),
            created_at=d.get("created_at", 0),
            error=d.get("error"),
        )
        plan.subgoals = [SubGoal(name=sg["name"], actions=sg["actions"]) for sg in d.get("subgoals", [])]
        return plan
    except Exception:
        return None


def list_plans(limit: int = 20, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT plan_id, goal, ring_max, created_at FROM goap_plans ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [{"plan_id": r[0], "goal": r[1], "ring_max": r[2], "created_at": r[3]} for r in rows]
    except Exception:
        return []


# ============================================================
# Core GOAP — decompose_goal (TODO Gemini: implémenter _goap_llm_call)
# ============================================================
def _parse_plan_response(raw: str, goal: str, ring_max: int) -> PlanTree:
    """Parse la réponse LLM en PlanTree validé."""
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        s = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise GOAPError(f"LLM not valid JSON: {e}")

    plan = PlanTree(
        goal=d.get("goal", goal),
        plan_id=d.get("plan_id", f"goap_{uuid.uuid4().hex[:10]}"),
        parallel=d.get("parallel", False),
        ring_max=ring_max,
        error=d.get("error"),
    )

    for sg_raw in d.get("subgoals", []):
        sg = SubGoal(name=sg_raw.get("name", ""))
        for action_raw in sg_raw.get("actions", []):
            try:
                validated = parse_intent(json.dumps(action_raw))
                # Ring check
                m = validated.get("method", "")
                required_ring = ALLOWED_METHODS.get(m, {}).get("ring", 0)
                if required_ring > ring_max:
                    continue  # skip action dépassant le ring
                sg.actions.append(validated)
            except IntentValidationError:
                pass  # action invalide ignorée
        plan.subgoals.append(sg)

    return plan


async def decompose_goal(
    goal: str,
    context: Optional[Dict[str, Any]] = None,
    ring_max: int = 2,
    max_retries: int = 2,
    llm_call_fn=None,
) -> PlanTree:
    """Décompose un goal en PlanTree via LLM.

    Args:
        goal: objectif en langage naturel ("analyse le repo X pour CVEs")
        context: contexte additionnel (dict libre)
        ring_max: ring maximum autorisé (0-4)
        max_retries: tentatives si LLM hallucine
        llm_call_fn: async fn(prompt, system) -> str
                     Si None: tente forge_cognitive_router.route_task

    Returns: PlanTree validé et persisté.
    """
    import time as _t

    global _PLAN_CACHE_HITS, _PLAN_CACHE_MISSES
    _ck = _plan_cache_key(goal, context, ring_max)
    _hit = _PLAN_CACHE.get(_ck)
    if _hit and (_t.time() - _hit[0]) < _PLAN_CACHE_TTL:
        _PLAN_CACHE_HITS += 1
        return _hit[1]  # cache : skip l'appel LLM (~40-50s économisés)
    _PLAN_CACHE_MISSES += 1

    # Planner DÉTERMINISTE : goal code reconnaissable -> plan FIXE, bypass total
    # du LLM (ni hallucination ni latence Ollama). Le LLM ne sert qu'aux goals ouverts.
    _tpl = _template_plan(goal, ring_max)
    if _tpl is not None and _tpl.subgoals:
        persist_plan(_tpl)
        if len(_PLAN_CACHE) > 256:
            _PLAN_CACHE.clear()
        _PLAN_CACHE[_ck] = (_t.time(), _tpl)
        return _tpl

    if llm_call_fn is None:

        def _sync_ollama_call(p, s):
            import requests as _req, json as _json

            payload = {
                "model": _planner_model(),
                "messages": [{"role": "system", "content": s}, {"role": "user", "content": p}],
                "stream": False,
                "format": "json",
                # A GOAP plan JSON is small: 420 tokens is ample. 800 doubled
                # generation time past the orchestrate wait_for budget and
                # triggered fast_path timeouts. keep_alive avoids cold reloads
                # between retries.
                "options": {"num_predict": 420},
                "keep_alive": "10m",
            }
            # 90s (>55) : laisse le cold-load de laforge-qwen sur APU aboutir si
            # le warm n'a pas fini (race au boot). 2 tentatives × 90 ≈ couvre le
            # wait_for 180s amont. Sinon "Read timed out" -> decomposition failed.
            r = _req.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=90)
            return r.json().get("message", {}).get("content", "") or ""

        async def _default_llm_call(p, s):
            import os

            # Goals OUVERTS : la puissance locale (laforge-qwen/APU) hallucine sur la
            # planification. On route vers le ROUTER cascade -> modèle cloud free-tier
            # FORT (use_case=strategy : groq-70b/sambanova) AVEC SemanticFirewall
            # (Golden Rule #4 : call_cascade applique pre_flight) + fallback local auto.
            # Override souverain : LAFORGE_PLANNER_LOCAL_ONLY=1 -> local strict.
            if os.environ.get("LAFORGE_PLANNER_LOCAL_ONLY") != "1":
                try:
                    from nokido_agent.app.forge_llm_router import LLMRouter

                    r = await asyncio.to_thread(
                        lambda: LLMRouter().call_cascade(
                            p, use_case="strategy", system=s, max_tokens=600,
                            temperature=0.2, json_mode=True
                        )
                    )
                    if isinstance(r, dict) and r.get("ok") and (r.get("text") or "").strip():
                        return r["text"]
                except Exception:
                    pass
            return await asyncio.to_thread(_sync_ollama_call, p, s)  # fallback / local-only

        llm_call_fn = _default_llm_call

    methods_available = [m for m, meta in ALLOWED_METHODS.items() if meta.get("ring", 0) <= ring_max]
    # Outils DYNAMIQUES forges (registre separe) : injectes pour que le planner les
    # invoque via forge_call_dynamic (1 seul method whitelist, ring-gate).
    dyn = ""
    if "forge_call_dynamic" in methods_available:
        try:
            from nokido_agent.app.forge_tool_forger import forge_list_dynamic_tools

            _lst = forge_list_dynamic_tools().get("tools", [])
            if _lst:
                _rows = [f"  - {t['name']}{t.get('signature', '')} — {t.get('description', '')}" for t in _lst[:30]]
                dyn = (
                    '\n\nOUTILS DYNAMIQUES forges (invoquer via '
                    '{"method":"forge_call_dynamic","params":{"name":"<nom>","kwargs":{...}}}) :\n'
                    + "\n".join(_rows)
                )
        except Exception:
            pass
    system = GOAP_SYSTEM_PROMPT.format(
        ring_max=ring_max,
        methods=", ".join(sorted(methods_available)),
    ) + dyn
    # Vascularisation (fiche_capability_graph_joint) : le planificateur PREFERE les methodes EPROUVEES
    # par l'usage en trajectoire (joint forge_capability_crosswalk.actions_prouvees sur la preuve reelle
    # des INTENTS = analyze_trajectories, pas le socle MCP). Advisory (aucune methode retiree),
    # reversible (LAFORGE_GOAP_PREUVE=0), fail-open (sans donnee/joint : prompt inchange).
    import os as _os
    import sys as _sys
    if _os.environ.get("LAFORGE_GOAP_PREUVE", "1") != "0":
        try:
            _td = str(ROOT / "tools")
            if _td not in _sys.path:
                _sys.path.insert(0, _td)
            from forge_capability_crosswalk import annotation_preference
            from nokido_agent.app.forge_trajectory import analyze_trajectories

            _stats = analyze_trajectories(limit=500).get("method_stats", {})
            system += annotation_preference(methods_available, ALLOWED_METHODS, _stats)
        except Exception:  # muet-ok : advisory, ne doit jamais casser la planification
            pass
    ctx_str = json.dumps(context or {}, ensure_ascii=False)[:500]
    prompt = f"Goal: {goal}\nContext: {ctx_str}"

    last_err = ""
    for attempt in range(max_retries + 1):
        full_prompt = (
            prompt
            if attempt == 0
            else (
                f"{prompt}\n\n[Erreur tentative {attempt}: {last_err}]\n"
                "Re-génère le plan JSON en corrigeant l'erreur. Aucun texte hors JSON."
            )
        )
        try:
            raw = await llm_call_fn(full_prompt, system)
            plan = _parse_plan_response(raw, goal, ring_max)
            plan = _sanitize_plan(plan, goal)  # Grille corrige Réseau (fichier exact, zone_name valide)
            persist_plan(plan)
            if len(_PLAN_CACHE) > 256:
                _PLAN_CACHE.clear()
            _PLAN_CACHE[_ck] = (_t.time(), plan)
            return plan
        except (GOAPError, Exception) as e:
            last_err = str(e)

    raise GOAPError(f"GOAP decomposition failed after {max_retries + 1} attempts: {last_err}")


class GOAPExecutionError(GOAPError):
    def __init__(self, message: str, step_idx: int, trajectory: Trajectory):
        super().__init__(message)
        self.step_idx = step_idx
        self.trajectory = trajectory


def make_reconstruction_aware_dispatch(base_dispatch, max_expansions: int = 1):
    """Wraps dispatch_fn avec reconstruction-loss retry.

    Sur échec : calcule Jaccard vs golden_dataset. Si RETRY_WITH_EXPANSION,
    relance forge_extern_patterns en DEEP_AST puis retente une fois.
    Si NO_GOLDEN ou score OK : raise normalement.
    """
    import logging as _log

    _logger = _log.getLogger("Nokido.GOAP.ReconDispatch")
    expansions = [0]

    async def _wrapped(action: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await base_dispatch(action)
        except GOAPExecutionError:
            raise
        except Exception as first_err:
            if expansions[0] >= max_expansions:
                raise
            try:
                from nokido_agent.app.forge_reconstruction_loss import validate_and_adapt

                task_id = action.get("method", "unknown")
                produced = [{"name": task_id, "arguments": action.get("params", {})}]
                verdict = validate_and_adapt(task_id, {"tool_calls": produced})
                if verdict["status"] == "RETRY_WITH_EXPANSION":
                    expansions[0] += 1
                    from nokido_agent.app.forge_extern_patterns import extract_patterns_from_gitingest

                    lib_hint = action.get("params", {}).get("lib")
                    r = extract_patterns_from_gitingest(lib_name=lib_hint, depth="DEEP_AST")
                    _logger.info(f"[GOAP] Expansion #{expansions[0]} for {task_id} | patterns={r}")
                    return await base_dispatch(action)
            except (GOAPExecutionError, Exception):
                pass
            raise first_err from None

    return _wrapped


async def rollback_action(action: Dict[str, Any], result: Any) -> bool:
    """Tente d'annuler une action (best-effort). NON IMPLÉMENTÉ : renvoie False.

    HONNÊTETÉ (audit ZCode 2026-07-23) : l'ancien code renvoyait True sans rien
    annuler = il MENTAIT sur le succès du rollback. Pour un système qui écrit des
    fichiers/exécute du code, prétendre un rollback réussi laisse un état incohérent
    pris pour propre. Tant que les undo réels ne sont pas câblés (write->restore,
    rag_ingest->rag_delete), on renvoie False = "rollback NON effectué", le caller
    sait qu'il reste un résidu à traiter, plutôt que de le croire nettoyé.
    """
    method = action.get("method")
    params = action.get("params", {})
    import logging as _log
    _log.getLogger("Nokido.GOAP").warning(
        "[goap] rollback NON implémenté pour %s (params=%s) — état résiduel NON annulé",
        method, list(params.keys()),
    )
    return False


async def _execute_subgoal(sg: SubGoal, dispatch_fn: Any, traj: Trajectory) -> None:
    """Exécute un subgoal séquentiellement avec arrêt au premier échec."""
    for action in sg.actions:
        idx = len(traj.steps)
        traj.append(action, agent="goap")
        try:
            # Dispatcher strict ALLOWED_METHODS via forge_trajectory
            result = await dispatch_fn(action)

            # Gestion des erreurs JSON-RPC
            if isinstance(result, dict) and result.get("error"):
                err = result["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                traj.fail(idx, msg)
                raise GOAPExecutionError(f"Action failed: {msg}", idx, traj)

            # Succès
            res_data = result.get("result") if isinstance(result, dict) else result
            traj.complete(idx, res_data)

        except GOAPExecutionError:
            raise
        except Exception as e:
            traj.fail(idx, str(e))
            raise GOAPExecutionError(f"Execution crash: {e}", idx, traj)


async def execute_plan(
    plan: PlanTree,
    dispatch_fn=None,
    rollback: bool = True,
    use_reconstruction_loss: bool = False,
) -> Trajectory:
    """Exécute un PlanTree, track dans Trajectory, rollback si échec.

    Args:
        plan: PlanTree issu de decompose_goal
        dispatch_fn: async fn(intent) -> dict
        rollback: si True, tente d'annuler les étapes réussies en cas d'échec

    Returns: Trajectory complète.
    """
    import asyncio
    from nokido_agent.app.forge_trajectory import dispatch_intent

    fn = dispatch_fn or dispatch_intent
    if use_reconstruction_loss:
        fn = make_reconstruction_aware_dispatch(fn)
    traj = Trajectory(metadata={"goal": plan.goal, "plan_id": plan.plan_id})

    try:
        if plan.parallel:
            # Note: le rollback en parallèle est plus complexe, ici on gather
            await asyncio.gather(*[_execute_subgoal(sg, fn, traj) for sg in plan.subgoals])
        else:
            for sg in plan.subgoals:
                await _execute_subgoal(sg, fn, traj)

    except GOAPExecutionError as exc:
        if rollback:
            print(f"[goap] Failure detected at step {exc.step_idx}. Starting rollback...")
            # Rollback en sens inverse des étapes complétées
            for i in range(exc.step_idx - 1, -1, -1):
                step = traj.steps[i]
                if step.status == "completed":
                    await rollback_action(step.intent, step.result)

    persist_trajectory(traj)
    return traj


# ============================================================
# Queue runner — agent_messages → PlanTree → execute_plan
# ============================================================
def _task_to_intent(task: dict) -> dict:
    """Convert agent_messages task dict → JSON-RPC intent."""
    desc = (task.get("desc") or task.get("title") or "").strip()
    tid = task.get("id") or f"task_{uuid.uuid4().hex[:8]}"
    if desc.startswith("!"):
        return {"jsonrpc": "2.0", "method": "run_shell", "params": {"command": desc[1:].strip()}, "id": tid}
    if desc.lower().startswith("cmd:"):
        return {"jsonrpc": "2.0", "method": "run_shell", "params": {"command": desc[4:].strip()}, "id": tid}
    if desc.lower().startswith(("python:", "py:")):
        code = desc.split(":", 1)[1].strip()
        return {"jsonrpc": "2.0", "method": "run_python", "params": {"code": code}, "id": tid}
    return {
        "jsonrpc": "2.0",
        "method": "llm_call",
        "params": {"prompt": f"[Task: {task.get('title', '')}]\n{desc}"},
        "id": tid,
    }


def tasks_to_plan(tasks: list, ring_max: int = 3) -> PlanTree:
    """Convert list of task dicts (agent_messages format) → PlanTree."""
    plan = PlanTree(goal=f"Queue: {len(tasks)} tasks", ring_max=ring_max, parallel=False)
    for task in sorted(tasks, key=lambda t: t.get("priority", 99)):
        intent = _task_to_intent(task)
        required_ring = ALLOWED_METHODS.get(intent["method"], {}).get("ring", 0)
        if required_ring > ring_max:
            continue
        plan.subgoals.append(SubGoal(name=task.get("title") or task.get("id") or "task", actions=[intent]))
    return plan


async def run_queue(
    agent: str = "agt_daemon",
    max_tasks: int = 10,
    ring_max: int = 3,
    db_path: Optional[Path] = None,
    dispatch_fn=None,
) -> dict:
    """Read pending task_batch from agent_messages, execute as sequential GOAP plan."""
    import sqlite3 as _sql
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M : agent_messages, pas goap_plans

    db = Path(db_path) if db_path else Path(_m2m_path())
    try:
        conn = _sql.connect(str(db), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute(
            "SELECT id, payload FROM agent_messages WHERE to_agent=? AND status='unread' ORDER BY created_at LIMIT ?",
            (agent, max_tasks * 4),
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    tasks: List[Dict[str, Any]] = []
    msg_ids: List[str] = []
    for row_id, payload_str in rows:
        try:
            payload = json.loads(payload_str)
            if payload.get("type") == "task_batch":
                for t in payload.get("tasks", []):
                    tasks.append(t)
                    msg_ids.append(row_id)
        except Exception:
            pass

    # Resume stale 'processing' messages (crashed mid-run, > 5 min ago)
    try:
        _rc = _sql.connect(str(db), timeout=10)
        _rc.execute("PRAGMA journal_mode=WAL")
        stale = _rc.execute(
            "SELECT id, payload FROM agent_messages "
            "WHERE to_agent=? AND status='processing' "
            "AND created_at < datetime('now', '-5 minutes') LIMIT ?",
            (agent, max_tasks),
        ).fetchall()
        for sid, spay in stale:
            try:
                sp = json.loads(spay)
                if sp.get("type") == "task_batch":
                    for t in sp.get("tasks", []):
                        tasks.append(t)
                        msg_ids.append(sid)
            except Exception:
                pass
        # Reset stale to unread so they go through normal path
        if stale:
            _rc.execute(
                "UPDATE agent_messages SET status='unread' WHERE id IN (%s)" % ",".join("?" * len(stale)),
                [r[0] for r in stale],
            )
            _rc.commit()
        _rc.close()
    except Exception:
        pass

    if not tasks:
        return {"ok": True, "tasks": 0, "skipped": len(rows)}

    tasks = tasks[:max_tasks]
    plan = tasks_to_plan(tasks, ring_max=ring_max)
    persist_plan(plan)

    # Mark as processing before execution (checkpoint start)
    try:
        conn = _sql.connect(str(db), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        for mid in set(msg_ids[: len(tasks)]):
            conn.execute("UPDATE agent_messages SET status='processing' WHERE id=?", (mid,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    traj = await execute_plan(plan, dispatch_fn=dispatch_fn, rollback=False)
    done = sum(1 for s in traj.steps if s.status == "completed")
    failed = sum(1 for s in traj.steps if s.status == "failed")

    # Mark final status
    try:
        conn = _sql.connect(str(db), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        for mid in set(msg_ids[: len(tasks)]):
            final = "done" if failed == 0 else "partial_done"
            conn.execute("UPDATE agent_messages SET status=? WHERE id=?", (final, mid))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {"ok": True, "plan_id": plan.plan_id, "tasks": len(tasks), "completed": done, "failed": failed}


def drain_queue(
    agent: str = "agt_daemon",
    max_tasks: int = 10,
    ring_max: int = 3,
    db_path: Optional[Path] = None,
) -> dict:
    """Synchronous wrapper — safe to call from homeostasis tick or CLI."""
    import asyncio

    coro = run_queue(agent, max_tasks, ring_max, db_path)
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Already inside a running loop
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=120)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# CLI debug
# ============================================================
if __name__ == "__main__":
    import sys

    if "--list-plans" in sys.argv:
        plans = list_plans(20)
        print(json.dumps(plans, indent=2, ensure_ascii=False))
    elif "--load" in sys.argv:
        idx = sys.argv.index("--load")
        plan_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        p = load_plan(plan_id)
        print(json.dumps(p.to_dict() if p else {"error": "not found"}, indent=2, ensure_ascii=False))
    elif "--methods" in sys.argv:
        ring = int(sys.argv[sys.argv.index("--ring") + 1]) if "--ring" in sys.argv else 2
        avail = {m: v for m, v in ALLOWED_METHODS.items() if v.get("ring", 0) <= ring}
        print(json.dumps(avail, indent=2))
    elif "--drain-queue" in sys.argv:
        _agent = sys.argv[sys.argv.index("--agent") + 1] if "--agent" in sys.argv else "agt_daemon"
        _ring = int(sys.argv[sys.argv.index("--ring") + 1]) if "--ring" in sys.argv else 3
        _max = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10
        print(json.dumps(drain_queue(agent=_agent, max_tasks=_max, ring_max=_ring), indent=2))
    else:
        print("Usage:")
        print("  forge_goap.py --list-plans              # plans récents")
        print("  forge_goap.py --load <plan_id>          # charger un plan")
        print("  forge_goap.py --methods [--ring N]      # méthodes disponibles par ring")
        print("  forge_goap.py --drain-queue [--agent X] [--ring N] [--max N]  # exécute queue")
