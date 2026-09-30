"""
app/netcfg_silo_bridge.py - Pont netcfg-agent-mcp <-> SiloEngine Nokido
========================================================================

Orchestration :
    1. FETCH : appelle les tools MCP du fork netcfg-agent-mcp via stdio subprocess
       (list_equipments, audit, topology) pour recuperer les donnees reelles
       du parc reseau demo ou user.
    2. INJECT : injecte ces donnees comme 'context' dans des silos Nokido
       avec domains pre-selectionnes (recon, security, strategy, synthesis).
    3. DISPATCH : SiloEngine.evolve() decompose, route vers les modeles
       (llama.cpp local en priorite, GitHub Models en cascade cloud), synthetise.
    4. RETURN : renvoie le rapport consolide + indexe le resultat dans le RAG.

Usage typique depuis la TUI ou un tool MCP Nokido :

    result = await audit_parc_netcfg(
        intention="Audit complet du parc et priorites de remediation"
    )
    # -> {"silos": [...], "synthesis": "...", "mcp_raw": {...}}

Respect des directives user :
- Backend local : llama.cpp server (port 8080, OpenAI-compat via LAFORGE_LLM_ENDPOINT)
- Cascade cloud : GitHub Models (GITHUB_MODELS_TOKEN, priorite dans USE_CASE_CHAINS)
- Ollama garde comme fallback absolu uniquement
- Aucune modification du fork netcfg-agent-mcp (binaire v0.1.2 utilise tel quel)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Localisation par defaut du binaire netcfg-agent-mcp
# Peut etre override via env var NETCFG_MCP_BIN
_DEFAULT_BIN = Path(__file__).resolve().parent.parent.parent / "netcfg-agent-mcp" / "dist" / "netcfg-agent-mcp.exe"


def _resolve_netcfg_bin() -> Path:
    """Retourne le path du binaire netcfg-agent-mcp.exe.

    Priorite :
      1. env var NETCFG_MCP_BIN
      2. path par defaut (voisin de Nokido)
    """
    env_bin = os.environ.get("NETCFG_MCP_BIN", "").strip()
    if env_bin:
        p = Path(env_bin)
        if p.is_file():
            return p
    return _DEFAULT_BIN


# ============================================================================
# PHASE 1 : FETCH tools MCP du fork netcfg-agent-mcp
# ============================================================================


async def _call_netcfg_tool(bin_path: Path, tool_name: str, args: dict | None = None) -> dict:
    """Appelle un tool MCP netcfg via stdio subprocess. Retourne le dict parse.

    Si le binaire n'existe pas ou echoue, retourne {"error": "..."} sans crash.
    """
    if not bin_path.is_file():
        return {"error": f"Binaire netcfg-agent-mcp introuvable : {bin_path}"}

    try:
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters, ClientSession
    except ImportError as e:
        return {"error": f"mcp SDK absent : {e}"}

    params = StdioServerParameters(
        command=str(bin_path),
        args=["serve", "--transport", "stdio", "--standalone"],
        env={
            "PATH": os.environ.get("PATH", ""),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
        },
    )

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, args or {})
                if res.content:
                    return json.loads(res.content[0].text)
                return {"error": "Pas de contenu retourne"}
    except Exception as e:
        logger.error(f"[netcfg_bridge] call_tool({tool_name}) echec: {e}")
        return {"error": f"Exception tool {tool_name}: {str(e)[:200]}"}


async def fetch_netcfg_snapshot(bin_path: Optional[Path] = None) -> dict:
    """Recupere un snapshot complet du parc en appelant 3 tools en sequence.

    Retourne :
        {
            "equipments": {...},    # netcfg_list_equipments
            "dashboard":  {...},    # netcfg_get_dashboard
            "audit":      {...},    # netcfg_audit
            "topology":   {...},    # netcfg_topology
            "errors":     [...],    # liste des erreurs par tool
        }
    """
    bin_path = bin_path or _resolve_netcfg_bin()
    logger.info(f"[netcfg_bridge] fetch snapshot via {bin_path.name}")

    snapshot: dict[str, Any] = {"errors": []}

    for tool_name in ("netcfg_list_equipments", "netcfg_get_dashboard", "netcfg_audit", "netcfg_topology"):
        result = await _call_netcfg_tool(bin_path, tool_name)
        key = tool_name.replace("netcfg_", "")
        if "error" in result:
            snapshot["errors"].append({"tool": tool_name, "error": result["error"]})
            snapshot[key] = None
        else:
            snapshot[key] = result

    return snapshot


# ============================================================================
# PHASE 2 + 3 : INJECT dans les silos + DISPATCH
# ============================================================================


def _format_context_for_silo(snapshot: dict, domain: str) -> str:
    """Formate une section du snapshot adaptee au domaine du silo.

    Chaque silo voit uniquement ce dont il a besoin (principe de souverainete).
    """
    parts = []

    equipments = snapshot.get("list_equipments") or {}
    dashboard = snapshot.get("get_dashboard") or {}
    audit = snapshot.get("audit") or {}
    topology = snapshot.get("topology") or {}

    if domain == "recon":
        # Recon : inventaire complet
        eqs = equipments.get("equipments", [])
        parts.append(f"INVENTAIRE : {len(eqs)} equipements, {dashboard.get('total_pages', '?')} sites")
        parts.append(f"Vendors : {dashboard.get('vendor_counts', {})}")
        parts.append(f"Roles : {dashboard.get('role_counts', {})}")
        if eqs:
            parts.append("\nEquipements (hostname, vendor, role, mgmt_ip) :")
            for e in eqs[:20]:
                parts.append(f"  - {e.get('hostname')} | {e.get('vendor_key')} | {e.get('role')} | {e.get('mgmt_ip')}")

    elif domain == "security":
        # Security : focus audit + severity
        parts.append(f"AUDIT DRIFT : available={audit.get('available')}")
        sev = audit.get("severity_counts") or {}
        parts.append(f"Severity : {sev}")
        eqs = audit.get("equipment", [])
        heavies = [e for e in eqs if e.get("severity") == "drift_heavy"]
        mediums = [e for e in eqs if e.get("severity") == "drift_medium"]
        if heavies:
            parts.append(f"\nDRIFT HEAVY ({len(heavies)} switches - priorite haute) :")
            for e in heavies[:10]:
                parts.append(
                    f"  - {e.get('shape_id')} : {e.get('operations')} operations, ops={e.get('op_names', [])[:5]}"
                )
        if mediums:
            parts.append(f"\nDRIFT MEDIUM ({len(mediums)} switches) :")
            for e in mediums[:10]:
                parts.append(f"  - {e.get('shape_id')} : {e.get('operations')} operations")

    elif domain == "strategy":
        # Strategy : topologie + SPOFs potentiels
        ls = topology.get("length_stats") or {}
        cs = topology.get("cycle_stats") or {}
        parts.append(
            f"TOPOLOGIE : {ls.get('total_trunks')} trunks, "
            f"{ls.get('total_meters')}m cable total, "
            f"{cs.get('total')} cycles detectes"
        )
        parts.append(
            f"Classifications cycles : ha_lag={cs.get('ha_lag')}, "
            f"ha_redundancy={cs.get('ha_redundancy')}, anomaly={cs.get('anomaly')}"
        )
        # Ajout pour raisonnement strategique
        parts.append(f"Stats longueurs : {ls}")
        parts.append(f"Pages (sites) : {dashboard.get('pages', [])}")

    elif domain == "synthesis":
        # Synthesis : resume global tous axes
        parts.append(
            f"PARC : {dashboard.get('total_equipments')} switches, "
            f"{dashboard.get('total_pages')} sites, "
            f"{dashboard.get('total_racks')} racks"
        )
        parts.append(f"Vendors : {dashboard.get('vendor_counts')}")
        parts.append(f"Drift summary : {audit.get('severity_counts')}")
        ls = topology.get("length_stats") or {}
        parts.append(f"Topologie : {ls.get('total_trunks')} trunks, {ls.get('total_meters')}m cable")

    # Fallback : contexte generique
    if not parts:
        parts.append(f"Contexte netcfg pour domaine {domain} - snapshot disponible")

    return "\n".join(parts)


async def audit_parc_netcfg(
    intention: str = "Analyse le parc reseau et propose des ameliorations",
    domains: Optional[list[str]] = None,
    bin_path: Optional[Path] = None,
) -> dict:
    """Point d'entree principal : audit complet du parc via silos Nokido.

    Args:
        intention : question/objectif en langage naturel
        domains : liste optionnelle de domaines a cibler
                  (defaut : recon, security, strategy, synthesis)
        bin_path : override du path du binaire netcfg-agent-mcp

    Returns:
        {
            "intention": str,
            "mcp_snapshot": dict,    # donnees brutes des tools MCP
            "silos_results": list,   # resultats des silos par domaine
            "synthesis": str,        # rapport consolide final
            "errors": list,          # erreurs eventuelles
        }
    """
    logger.info(f"[netcfg_bridge] audit_parc_netcfg : {intention[:80]}")

    # === PHASE 1 : FETCH ===
    snapshot = await fetch_netcfg_snapshot(bin_path)

    if snapshot.get("errors") and not snapshot.get("list_equipments"):
        # Si meme list_equipments a echoue, on ne peut pas continuer
        return {
            "intention": intention,
            "mcp_snapshot": snapshot,
            "silos_results": [],
            "synthesis": "ECHEC : impossible de recuperer le snapshot netcfg",
            "errors": snapshot["errors"],
        }

    # === PHASE 2 : preparer le contexte par silo ===
    from nokido_agent.app.forge_silo_engine import get_silo_engine, Silo, SiloDomain, SiloTask, _pick_model

    # Domaines par defaut adaptes au cas netcfg
    if domains is None:
        domains = ["recon", "security", "strategy", "synthesis"]

    # Convertir en SiloDomain enum
    domain_map = {
        "recon": SiloDomain.RECON,
        "security": SiloDomain.SECURITY,
        "strategy": SiloDomain.STRATEGY,
        "synthesis": SiloDomain.SYNTHESIS,
        "doc": SiloDomain.DOC,
        "code": SiloDomain.CODE,
    }
    silo_domains = [domain_map[d] for d in domains if d in domain_map]

    # Taches specifiques netcfg par domaine
    netcfg_tasks = {
        "recon": f"Analyse l'inventaire reseau et identifie les patterns d'architecture. {intention}",
        "security": f"Identifie les switches avec drift critique et propose un ordre de remediation. {intention}",
        "strategy": f"Analyse la topologie et identifie les SPOFs + ameliorations d'architecture. {intention}",
        "synthesis": f"Produis un rapport executif consolide du parc. {intention}",
        "doc": f"Documente l'etat actuel du parc de maniere structuree. {intention}",
        "code": f"Si pertinent, propose du code pour automatiser la remediation. {intention}",
    }

    # Construction manuelle des silos (bypass decompose() LLM qui ne connait pas le cas netcfg)
    silos = []
    for i, domain in enumerate(silo_domains):
        task_text = netcfg_tasks.get(domain.value, f"Traite le snapshot du point de vue {domain.value}.")
        context = _format_context_for_silo(snapshot, domain.value)
        silo = Silo(
            id=f"netcfg_s{i + 1}",
            domain=domain,
            task=task_text,
            context=context,
            model=_pick_model(domain, task_text),
        )
        silos.append(silo)

    # === PHASE 3 : DISPATCH + SYNTHESIZE ===
    engine = get_silo_engine()
    import uuid as _uuid

    task = SiloTask(
        id=f"netcfg_{_uuid.uuid4().hex[:8]}",
        intention=intention,
        silos=silos,
    )

    try:
        await engine.run_silos(task, rag_chunks=None)
    except Exception as e:
        logger.error(f"[netcfg_bridge] run_silos echec : {e}", exc_info=True)
        return {
            "intention": intention,
            "mcp_snapshot": snapshot,
            "silos_results": [],
            "synthesis": f"ECHEC run_silos : {e}",
            "errors": snapshot.get("errors", []) + [{"phase": "run_silos", "error": str(e)}],
        }

    # Synthesize - met a jour task.synthesis
    try:
        await engine.synthesize(task)
        synthesis = task.synthesis or "Synthese vide (aucun silo n'a produit de sortie exploitable)"
    except Exception as e:
        logger.error(f"[netcfg_bridge] synthesize echec : {e}", exc_info=True)
        synthesis = f"ECHEC synthesize : {e}"

    # Index RAG (best effort)
    try:
        await engine.index_to_rag(task)
    except Exception as e:
        logger.warning(f"[netcfg_bridge] index_to_rag echec (non bloquant) : {e}")

    # === Resultats ===
    silos_results = []
    for silo in silos:
        silos_results.append(
            {
                "id": silo.id,
                "domain": silo.domain.value,
                "model": silo.model,
                "output": getattr(silo, "output", "") or "",
                "error": getattr(silo, "error", "") or "",
                "tokens_in": getattr(silo, "tokens_in", 0),
                "tokens_out": getattr(silo, "tokens_out", 0),
                "duration": getattr(silo, "duration", 0.0),
            }
        )

    return {
        "intention": intention,
        "mcp_snapshot": snapshot,
        "silos_results": silos_results,
        "synthesis": synthesis,
        "errors": snapshot.get("errors", []),
    }


# ============================================================================
# Sync wrapper pour les clients qui ne sont pas async (TUI handlers, etc.)
# ============================================================================


def audit_parc_netcfg_sync(
    intention: str = "Analyse le parc reseau et propose des ameliorations",
    domains: Optional[list[str]] = None,
    bin_path: Optional[Path] = None,
) -> dict:
    """Version bloquante pour les appelants synchrones.

    Attention : cree sa propre event loop. Ne pas appeler depuis un contexte
    deja async (utiliser audit_parc_netcfg direct a la place).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # On est deja dans une loop - impossible d'utiliser run()
            raise RuntimeError(
                "audit_parc_netcfg_sync appele depuis un contexte async. "
                "Utiliser audit_parc_netcfg (coroutine) a la place."
            )
    except RuntimeError:
        pass

    return asyncio.run(audit_parc_netcfg(intention, domains, bin_path))


# ============================================================================
# P4 : ingestion de l'HISTORIQUE DES DEPLOYS (netcfg_deploy_log) dans le RAG
# ----------------------------------------------------------------------------
# Distinct de fetch_netcfg_snapshot (qui ingere le snapshot + synthese LLM).
# Ici : la TRACABILITE operationnelle (qui a pousse quoi, gates, rollback) ->
# chunks RAG idempotents (id deterministe via anchor_solution). Lit le sqlite
# netcfg-agent-web en direct, sans dependance au paquet netcfg.
# ============================================================================


def _default_netcfg_db() -> Path:
    """Chemin par defaut de la DB netcfg-agent-web (voisin de Nokido)."""
    env = os.environ.get("NETCFG_DB", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "netcfg-agent-web" / "data" / "netcfg.db"


def ingest_netcfg_deploys(db_path: Optional[Path] = None, limit: int = 200) -> dict:
    """Ingere l'historique des deploys netcfg dans le RAG Nokido (domain='netcfg').

    Chaque run (cible, operateur, gates approuvees/rejetees, rollback, dry-run/reel,
    hash WAL) devient un chunk RAG. id deterministe -> RE-ingestion idempotente.
    Retourne {ingested, runs, db} ou {error}.
    """
    import sqlite3

    db_path = Path(db_path) if db_path else _default_netcfg_db()
    if not db_path.is_file():
        return {"error": f"DB netcfg introuvable : {db_path}"}

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT d.run_id, d.gate, d.operator, d.validated, d.dry_run, d.ts, "
            "d.hash_current, e.hostname, e.ip_mgmt, e.vendor_key "
            "FROM netcfg_deploy_log d "
            "LEFT JOIN netcfg_equipment e ON e.id = d.equipment_id "
            "ORDER BY d.run_id, d.step_index"
        ).fetchall()
    except Exception as e:  # schema absent / DB vide
        return {"error": f"Lecture deploy_log echouee : {e}"}
    finally:
        con.close()

    runs: dict[str, Any] = {}
    for r in rows:
        run = runs.setdefault(r["run_id"], {
            "run_id": r["run_id"], "hostname": r["hostname"], "mgmt_ip": r["ip_mgmt"],
            "vendor": r["vendor_key"], "operator": r["operator"], "ts_start": r["ts"],
            "ts_end": r["ts"], "gates": {}, "rolled_back": False,
            "dry_run": bool(r["dry_run"]), "final_hash": r["hash_current"],
        })
        run["ts_end"] = r["ts"]
        run["final_hash"] = r["hash_current"]
        if r["gate"] in ("diff_review", "cmd_review", "post_push"):
            run["gates"][r["gate"]] = "approved" if r["validated"] else "rejected"
        if r["gate"] == "rollback":
            run["rolled_back"] = True

    try:
        from nokido_agent.app.forge_self_correction import anchor_solution
    except Exception as e:
        return {"error": f"anchor_solution indisponible : {e}", "runs": len(runs)}

    ingested = 0
    for run in list(runs.values())[:limit]:
        gates = ", ".join(f"{k}={v}" for k, v in run["gates"].items()) or "aucune"
        mode = "DRY-RUN" if run["dry_run"] else "REEL"
        host = run["hostname"] or run["run_id"][:8]
        solution = (
            f"Deploy netcfg {mode} sur {host} ({run['vendor'] or '?'}, "
            f"{run['mgmt_ip'] or '?'}) par {run['operator']}. Gates: {gates}. "
            f"Rollback: {'OUI' if run['rolled_back'] else 'non'}. "
            f"{run['ts_start']} -> {run['ts_end']}. WAL hash={str(run['final_hash'])[:16]}."
        )
        try:
            anchor_solution(
                problem=f"Tracabilite deploy reseau {host} (run {run['run_id'][:8]})",
                solution=solution,
                example=f"netcfg verify {run['run_id']}",
                domain="netcfg",
            )
            ingested += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[netcfg_bridge] anchor run {run['run_id'][:8]} echec: {e}")

    logger.info(f"[netcfg_bridge] P4 ingest: {ingested}/{len(runs)} run(s) -> RAG domain=netcfg")
    return {"ingested": ingested, "runs": len(runs), "db": str(db_path)}
