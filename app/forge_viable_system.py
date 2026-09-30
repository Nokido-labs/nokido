#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_viable_system.py — Organisateur cybernétique (VSM) + orchestrateur multi-pool.

Pousse forge_nervous_map (descriptif) -> PRESCRIPTIF : assigne à chaque organe son niveau
de contrôle (Viable System Model, Beer) et ORCHESTRE des pools d'agents collaboratifs en
couplant 2 CLI OAuth (claude_cli + gemini_cli) + le pool LOCAL + le CLOUD dispo.

Doc : docs/CYBERNETIC_ORGANIZATION_VSM.md

ANTI-DUP : ce module N'IMPLÉMENTE aucun provider ni swarm. Il COMPOSE :
  - forge_cli_swarm.swarm   (panel multi-provider : "provider:model")
  - forge_videur.authorize  (S5 : cadre identité×capacité, fail-closed)
  - forge_agent_proxy.ask   (10+ providers, firewall INBYPASSABLE) via forge_cli_swarm
  - blackboard (zone temporaire) + un miroir fichier local = substrat de PLANIFICATION

Niveaux (VSM) : S1 ops · S2 coord/comm · S3 homéostasie · S4 intelligence · S5 identité.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "sandbox" / "orchestration_plans"

# ── VSM : organe (census) -> niveau de contrôle (cf doc) ─────────────────────
VSM_LEVEL = {
    # S1 — effecteurs
    "locomoteur": "S1", "metabolisme_llm": "S1", "digestif": "S1",
    "offensif": "S1", "swebench": "S1", "agent_expert": "S1",
    # S2 — coordination / communication
    "reseau": "S2", "observabilite": "S2",
    # S3 — homéostasie / contrôle opérationnel
    "vegetatif": "S3", "infra": "S3", "qualite": "S3",
    # S4 — intelligence / anticipation
    "cognition": "S4", "memoire": "S4", "graph": "S4",
    # S5 — identité / politique
    "immunitaire": "S5",
    # transverse (nexus)
    "snc": "S2/S4/S5", "core": "transverse",
}

# ── Substrats (couplage CLI OAuth + local + cloud) par TIER de besoin ─────────
def _codex_available() -> bool:
    """codex_cli rejoint le tier premium SEULEMENT si le CLI est installé (ou flag
    LAFORGE_ENABLE_CODEX) : évite de router vers un provider absent ; prêt dès qu'on l'installe."""
    import shutil
    return bool(shutil.which("codex")) or bool(os.environ.get("LAFORGE_ENABLE_CODEX"))


# reason_premium = CLI OAuth (quota gratuit) -> round-robin sur DISPONIBLES, rôles NON figés.
PROVIDER_TIERS = {
    "reason_premium": ["claude_cli", "gemini_cli"] + (["codex_cli"] if _codex_available() else []),
    "bulk_local": ["ollama:qwen3:8b", "ollama:qwen2.5-coder:7b-instruct"],
    "fast_cloud": ["groq:llama-3.3-70b-versatile", "cerebras:llama-3.3-70b"],
}

# ⚠ JAMAIS l'API Claude/Gemini (payante, 429). UNIQUEMENT les CLI OAuth (quota gratuit).
FORBIDDEN_API = {"claude", "gemini", "anthropic", "google"}


def _safe_provider(p: str) -> str:
    """Garde anti-API : un provider 'claude'/'gemini' bare = API payante -> redirige vers le
    CLI OAuth (claude_cli/gemini_cli). Les 2 CLI = la SEULE voie premium autorisée."""
    base = (p or "").split(":")[0].strip().lower()
    if base in FORBIDDEN_API and not p.endswith("_cli"):
        return base + "_cli"
    return p


def level_of(organ: str) -> str:
    """Niveau VSM d'un organe/module (match mot-clé). 'agent_*' -> S1 récursif."""
    o = (organ or "").lower()
    if o.startswith("agent_"):
        return "S1"
    for key, lvl in VSM_LEVEL.items():
        if key in o:
            return lvl
    return "?"


_LOCAL_FREE = ("ollama", "lmstudio", "llamacpp", "docker")


def _quota_filter(cands: list) -> list:
    """QUOTA-AWARE (capacité centrale) : retire les providers near-limit
    (forge_provider_quota.should_skip) pour ne JAMAIS éclater un free-tier. Le LOCAL (gratuit)
    n'est jamais filtré. fail-open si le tracker est incertain (ne brique pas le routage)."""
    try:
        from nokido_agent.app.forge_provider_quota import should_skip
    except Exception:
        return cands
    out = []
    for c in cands:
        base = c.split(":")[0]
        if base in _LOCAL_FREE:
            out.append(c)
            continue
        try:
            if not should_skip(base):
                out.append(c)
        except Exception:
            out.append(c)
    return out


def assign_provider(role: dict, rr_state: dict | None = None) -> str:
    """S3 — couple un rôle à son substrat. provider explicite (sanitizé) sinon role['tier'] ->
    candidats QUOTA-AWARE (skip near-limit) -> round-robin sur les DISPONIBLES. Rôle NON FIGÉ
    sur un CLI : claude/gemini/codex interchangeables, choisis par quota. Tous cloud épuisés ->
    repli LOCAL gratuit (priorité économie tokens, jamais d'éclatement free-tier)."""
    if role.get("provider"):
        return _safe_provider(role["provider"])
    tier = role.get("tier", "bulk_local")
    cands = _quota_filter(PROVIDER_TIERS.get(tier, PROVIDER_TIERS["bulk_local"]))
    if not cands:  # tier entièrement épuisé -> repli LOCAL
        cands = PROVIDER_TIERS["bulk_local"]
    i = (rr_state or {}).get(tier, 0)
    if rr_state is not None:
        rr_state[tier] = i + 1
    return _safe_provider(cands[i % len(cands)])


def plan_orchestration(macro_task: str, roles: list, plan_id: str) -> dict:
    """PUR (testable, sans hub). Décompose en rôles -> (pool, provider). Couple 2 CLI +
    local + cloud. roles = [{name, tier?, pool?, task?, tool?}]. Retourne le PLAN."""
    rr: dict = {}
    assignments = []
    for r in roles:
        assignments.append({
            "role": r["name"],
            "pool": r.get("pool", "default"),
            "tier": r.get("tier", "bulk_local"),
            "provider": assign_provider(r, rr),
            "task": r.get("task", macro_task),
            "tool": r.get("tool"),
        })
    pools: dict = {}
    for a in assignments:
        pools.setdefault(a["pool"], []).append(a)
    return {
        "plan_id": plan_id,
        "macro_task": macro_task,
        "pools": pools,
        "assignments": assignments,
        "providers_used": sorted({a["provider"] for a in assignments}),
        "cli_oauth": sorted({a["provider"] for a in assignments
                             if a["provider"] in ("claude_cli", "gemini_cli", "codex_cli")}),
    }


def publish_plan(plan: dict) -> dict:
    """Blackboard TEMPORAIRE de planification = (1) miroir fichier local (toujours, même
    hub down) + (2) zone blackboard hub best-effort. Les 2 CLI + pools le lisent."""
    out = {"file": None, "blackboard": False}
    try:
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        fp = PLAN_DIR / f"{plan['plan_id']}.json"
        fp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        out["file"] = str(fp)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # `out` sort alors SANS la clef "file". L'appelant voit une absence, jamais
        # une raison — et une absence se lit « pas de plan » plutot que « plan non
        # ecrit ».
        _lg.getLogger(__name__).error(
            "[vsm] plan %s NON ecrit sur disque (%s: %s) | consequence: le plan "
            "n'existe qu'en memoire et disparaitra avec le processus",
            plan.get("plan_id"), type(e).__name__, str(e)[:90])
    try:  # zone blackboard hub (coordination inter-CLI) — lazy, fail-safe
        from nokido_agent.app.forge_swarm_blackboard import _write_fact, init_db
        init_db()
        _write_fact(f"orchestration_plan_{plan['plan_id']}", "plan",
                    json.dumps(plan, ensure_ascii=False), "orchestration", 0.9,
                    "forge_viable_system")
        out["blackboard"] = True
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).error(
            "[vsm] plan %s NON publie au tableau noir (%s: %s) | consequence: les "
            "autres CLI ne verront pas ce plan et pourront en produire un concurrent",
            plan.get("plan_id"), type(e).__name__, str(e)[:90])
    try:  # hook collaboration : assignment par agent dans son inbox (les CLI lisent + reagissent)
        from nokido_agent.app.forge_swarm_blackboard import _write_fact
        for a in plan.get("assignments", []):
            ag = ((a.get("provider", "") or "").split(":")[0].replace("_cli", "").upper()) or "UNKNOWN"
            _write_fact(f"orchestration_inbox_{ag}", plan["plan_id"],
                        json.dumps(a, ensure_ascii=False), "orchestration", 0.9, "forge_viable_system")
        out["notified"] = True
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Le plan peut etre ECRIT et PUBLIE sans que personne ne soit prevenu : les
        # assignations dorment alors dans un plan que nul agent ne lit. C'est le
        # motif « tache deposee, drain non verifie ».
        _lg.getLogger(__name__).error(
            "[vsm] assignations du plan %s NON distribuees (%s: %s) — %d agent(s) "
            "concerne(s) | consequence: le plan existe mais aucun agent n'a ete "
            "sollicite, et son immobilite passera pour de l'inaction",
            plan.get("plan_id"), type(e).__name__, str(e)[:80],
            len(plan.get("assignments", [])))
    return out


def _authorize(a: dict, token: str, local: bool) -> dict:
    """S5 — cadre. fail-closed si authorize indispo."""
    try:
        from nokido_agent.app.forge_videur import authorize
        return authorize(agent=a["role"], token=token, local=local, tool=a.get("tool"))
    except Exception as e:  # noqa: BLE001
        return {"allow": False, "reason": f"authorize indispo: {e}"}


def _run_maybe_async(value):
    """forge_cli_swarm.swarm est async -> exécute la coroutine (sync passthrough sinon)."""
    import asyncio
    import inspect
    if not inspect.iscoroutine(value):
        return value
    try:
        return asyncio.run(value)
    except RuntimeError:  # déjà dans une loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(value)
        finally:
            loop.close()


def execute_plan(plan: dict, token: str = "", local: bool = True, serve_fn=None) -> dict:
    """Exécute chaque pool : (1) S5 authorize chaque membre, (2) serving. Défaut =
    forge_cli_swarm.swarm sur les providers assignés ; serve_fn(allowed_members) override =
    point de COMPOSITION avec le swarm_router (serving physiologie-aware) de Gemini. Lazy."""
    from nokido_agent.tools.forge_cli_swarm import swarm
    results: dict = {"plan_id": plan.get("plan_id"), "pools": {}, "denied": []}
    if any(("ollama" in a.get("provider", "")) or ("lmstudio" in a.get("provider", ""))
           for mem in plan["pools"].values() for a in mem):
        try:  # token economy : réveille le pool LOCAL avant d'exécuter (zéro quota cloud)
            from nokido_agent.tools.forge_local_pool_wake import ensure_local_pool
            results["pool_wake"] = ensure_local_pool(["ollama", "lmstudio"])
        except Exception:  # noqa: BLE001
            pass
    for pool_name, members in plan["pools"].items():
        allowed = []
        for a in members:
            v = _authorize(a, token, local)
            (allowed.append(a) if v.get("allow")
             else results["denied"].append({**a, "reason": v.get("reason")}))
        if not allowed:
            continue
        if serve_fn is not None:  # composition : route via swarm_router Gemini (physiologie)
            results["pools"][pool_name] = _run_maybe_async(serve_fn(allowed))
            continue
        provs = [a["provider"] for a in allowed]
        results["pools"][pool_name] = _run_maybe_async(
            swarm(allowed[0]["task"], members=provs, max_tokens=plan.get("max_tokens", 800)))
    return results


def orchestrate(macro_task: str, roles: list, plan_id: str | None = None,
                token: str = "", local: bool = True, execute: bool = False) -> dict:
    """Pipeline complet : plan -> publish (blackboard temp) -> [execute]. Par défaut
    execute=False (plan seulement, sûr). execute=True = lance les pools (hub requis)."""
    pid = plan_id or f"orc_{int(time.time())}"
    plan = plan_orchestration(macro_task, roles, pid)
    plan["published"] = publish_plan(plan)
    if execute:
        plan["results"] = execute_plan(plan, token, local)
    return plan


# ── Boucles inter-organes VSM (composables ; les organes les ADOPTENT) ───────
def s5_gate_allocation(agent: str, tool: str | None = None, token: str = "", local: bool = True) -> dict:
    """S5->S3 : la Police gate une allocation. homeostasis_orchestrator appelle ceci AVANT
    d'allouer/différencier (autorité ⊃ régulation). Fail-closed."""
    try:
        from nokido_agent.app.forge_videur import authorize
        return authorize(agent=agent, token=token, local=local, tool=tool)
    except Exception as e:  # noqa: BLE001
        return {"allow": False, "reason": f"police indispo: {e}"}


def algedonic_to_police(signal: dict) -> dict:
    """Algédonique->S5 : un signal critique (menace) remonte à la Police pour réévaluer le
    périmètre, pas seulement à l'immune. {escalate, level, action}."""
    sev = (signal or {}).get("severity", "low")
    hot = sev in ("high", "critical")
    return {"escalate": hot, "level": sev,
            "action": "reevaluer_perimetre_police" if hot else "log"}


def loop_status() -> dict:
    """Monitore la fermeture des boucles inter-organes (boucle ouverte = pathologie
    cybernétique). Vérifie la disponibilité des modules de chaque boucle."""
    def _has(mod: str) -> bool:
        try:
            __import__(mod)
            return True
        except Exception:  # noqa: BLE001
            return False
    loops = {
        "S5->S3 police->homeostasie": _has("forge_videur") and _has("forge_homeostasis_orchestrator"),
        "S4->S3 active_inference->homeostasie": _has("forge_active_inference") and _has("forge_homeostasis_orchestrator"),
        "algedonique->S5": _has("forge_critical_events") and _has("forge_videur"),
    }
    return {"loops": loops, "all_closed": all(loops.values()),
            "open": [k for k, v in loops.items() if not v]}


def serve_via_swarm_router(allowed_members, token: str = "", local: bool = True, _route_fn=None):
    """serve_fn (composition #2) : route chaque membre via le swarm_router de Gemini
    (forge_swarm_router.route_subtask = serving physiologie-aware VRAM/circadien). La Police a
    déjà gate (authorize dans execute_plan) ; tier -> use_case. Relais police×orchestration×ressources."""
    route = _route_fn
    if route is None:
        from nokido_agent.app.forge_swarm_router import route_subtask as route
    return [route(agent_cible=a["role"], task_prompt=a["task"], tool_vise=a.get("tool"),
                  token=token, local=local, use_case=a.get("tier", "general"))
            for a in allowed_members]


def read_my_inbox(agent: str) -> list:
    """Lecture SANCTIONNÉE de son PROPRE inbox d'orchestration (scopé à l'agent). In-process,
    pas de gate ring MCP : un agent lit TOUJOURS son courrier, quel que soit son ring (résout
    le GATE_DENIED ring3 sur blackboard_read_zone sans bypass). Retourne ses assignments."""
    ag = (agent or "").split(":")[0].replace("_cli", "").upper()
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone
        return read_zone(f"orchestration_inbox_{ag}") or []
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]
