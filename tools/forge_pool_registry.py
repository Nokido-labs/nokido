#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_pool_registry.py — Registre d'efficacité mesurée du pool d'exécution de Nokido.

Fédère les métriques en live de tous les membres du pool :
  - CLIs (codex, gemini, agy, vscode)
  - Modèles locaux (ollama, llamacpp, lmstudio)
  - Providers cloud (groq, mistral, openrouter)
  - Docker, agents distants

Expose :
  - publish(member, metrics) -> met à jour les métriques en live
  - best(task_type, need_caps) -> sélectionne le membre optimal selon le score d'efficacité :
        score = capability_fit / (cost + latency) modulé par quota
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:pool_registry|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent

# Injection des chemins app et tools pour importations inter-modules
for path_dir in (ROOT / "app", ROOT / "tools"):
    if str(path_dir) not in sys.path:
        sys.path.insert(0, str(path_dir))

DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# Mapping par défaut des types de tâches vers les capacités requises
_TASK_TYPE_TO_CAPS: Dict[str, List[str]] = {
    "code": ["code"],
    "lint": ["code", "lint"],
    "docstring": ["code", "docstring"],
    "veille": ["search", "creative"],
    "lightweight": ["lightweight"],
    "interactive": ["interactive"],
    "run_command": ["run_command"],
}


def get_db_connection():
    """Crée et configure une connexion SQLite avec WAL."""
    import sqlite3
    os.makedirs(DEFAULT_DB.parent, exist_ok=True)
    conn = sqlite3.connect(str(DEFAULT_DB), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Initialise le schéma de la table du registre si elle n'existe pas."""
    conn = get_db_connection()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS forge_pool_registry (
            member TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            capability_tags TEXT NOT NULL,
            cost REAL DEFAULT 0.0,
            latency_ms REAL DEFAULT 1000.0,
            quota_restant REAL DEFAULT 100.0,
            available INTEGER DEFAULT 1,
            last_updated REAL NOT NULL
        )
        """)
        conn.commit()
    except Exception as e:
        print(f"Error creating table: {e}", file=sys.stderr)
    finally:
        conn.close()



def get_member_cost(member: str) -> float:
    """Calcule le coût d'un membre à l'aide de forge_token_meter ou de fallbacks."""
    try:
        from nokido_agent.tools import forge_token_meter
        if hasattr(forge_token_meter, "get_member_cost"):
            return float(forge_token_meter.get_member_cost(member))
        elif hasattr(forge_token_meter, "get_cost"):
            return float(forge_token_meter.get_cost(member))
    except Exception:
        pass

    # Fallback sur les tiers d'identité d'endpoints
    try:
        from nokido_agent.tools import forge_endpoint_registry
        ep = forge_endpoint_registry.resolve(member)
        if ep:
            tier = ep.get("tier")
            if tier in ("local", "free"):
                return 0.0
            if tier == "subscription_quota":
                return 0.05
            if tier == "paid_api":
                return 1.0
    except Exception:
        pass

    # Coût arbitraire par défaut selon le nom du membre
    if "local" in member or "ollama" in member or "llamacpp" in member:
        return 0.0
    if "cli:codex" in member:
        return 0.05
    if "cli:gemini" in member:
        return 0.2
    return 0.1


def _modulate_by_quota(score: float, quota_restant: Optional[float]) -> float:
    """Module le score final selon l'état du quota restant."""
    if quota_restant is None:
        return score
    if quota_restant <= 0:
        return 0.0
    # Quota exprimé en fraction (0.0 - 1.0)
    if 0.0 < quota_restant <= 1.0:
        return score * quota_restant
    # Quota exprimé en pourcentage (1.0 - 100.0)
    if 1.0 < quota_restant <= 100.0:
        return score * (quota_restant / 100.0)
    # Quota absolu (nombre de tokens restants / limite)
    return score * min(1.0, quota_restant / 10000.0)


def publish(member: str, metrics: Dict[str, Any]) -> bool:
    """Publie ou met à jour en live les métriques d'un membre dans le pool.

    metrics: dict contenant optionnellement :
      {kind, capability_tags, cost, latency_ms, quota_restant, available}
    """
    init_db()
    conn = get_db_connection()
    try:
        # Tenter de charger l'état existant pour fusion partielle
        row = conn.execute("SELECT * FROM forge_pool_registry WHERE member=?", (member,)).fetchone()

        kind = metrics.get("kind")
        if not kind:
            kind = row["kind"] if row else "unknown"

        tags = metrics.get("capability_tags")
        if tags is not None:
            tags_json = json.dumps(list(tags))
        elif row:
            tags_json = row["capability_tags"]
        else:
            tags_json = json.dumps([])

        cost = metrics.get("cost")
        if cost is None:
            cost = row["cost"] if row else get_member_cost(member)

        latency = metrics.get("latency_ms")
        if latency is None:
            latency = row["latency_ms"] if row else 1000.0

        quota = metrics.get("quota_restant")
        if quota is None:
            quota = row["quota_restant"] if row else 100.0

        available = metrics.get("available")
        if available is None:
            available = row["available"] if row else 1

        conn.execute("""
        INSERT OR REPLACE INTO forge_pool_registry
        (member, kind, capability_tags, cost, latency_ms, quota_restant, available, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (member, kind, tags_json, float(cost), float(latency), float(quota), int(available), time.time()))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error publishing to pool registry for {member}: {e}", file=sys.stderr)
        return False
    finally:
        conn.close()


def bootstrap_registry() -> None:
    """Initialise le pool d'exécution de base avec les CLIs et endpoints découverts."""
    # CLIs de base
    publish("cli:codex", {
        "kind": "cli",
        "capability_tags": ["code", "lint", "docstring", "lightweight"],
        "cost": 0.05,
        "latency_ms": 400.0,
        "quota_restant": 100.0,
        "available": 1
    })
    publish("cli:gemini", {
        "kind": "cli",
        "capability_tags": ["heavy_task", "search", "creative", "multilingual"],
        "cost": 0.5,
        "latency_ms": 1500.0,
        "quota_restant": 100.0,
        "available": 1
    })
    publish("cli:agy", {
        "kind": "cli",
        "capability_tags": ["run_command", "mcp_registry", "local_execution"],
        "cost": 0.1,
        "latency_ms": 800.0,
        "quota_restant": 100.0,
        "available": 1
    })
    publish("cli:vscode", {
        "kind": "cli",
        "capability_tags": ["editor", "interactive", "workspace"],
        "cost": 0.0,
        "latency_ms": 200.0,
        "quota_restant": 100.0,
        "available": 1
    })

    # Endpoints découverts par le forge_endpoint_registry
    try:
        from nokido_agent.tools import forge_endpoint_registry
        inv = forge_endpoint_registry.build_inventory()
        for cid, ep in inv.get("endpoints", {}).items():
            tier = ep.get("tier")
            kind = "model_local" if tier in ("local", "free") else "model_cloud"
            
            # Reconstruction basique des capabilities
            caps = ["llm"]
            if any(kw in cid.lower() for kw in ("code", "coder", "coding")):
                caps.append("code")
            if tier == "local":
                caps.append("offline")
            
            lat = 300.0 if tier == "local" else 1000.0
            available = 1 if ep.get("key_present") is not False else 0
            
            publish(cid, {
                "kind": kind,
                "capability_tags": caps,
                "cost": get_member_cost(cid),
                "latency_ms": lat,
                "quota_restant": 100.0,
                "available": available
            })
    except Exception as e:
        print(f"Warning: unable to bootstrap from endpoint registry: {e}", file=sys.stderr)


def best(task_type: str, need_caps: Optional[List[str]] = None) -> Optional[str]:
    """Sélectionne le meilleur membre disponible pour exécuter la charge donnée.

    Score d'efficacité = capability_fit / (cost + latency_in_seconds) modulé par quota.
    """
    init_db()
    conn = get_db_connection()
    try:
        # Bootstrap automatique si aucun membre n'est présent
        count = conn.execute("SELECT count(*) FROM forge_pool_registry").fetchone()[0]
        if count == 0:
            conn.close()
            bootstrap_registry()
            conn = get_db_connection()

        rows = conn.execute("SELECT * FROM forge_pool_registry WHERE available=1").fetchall()
        if not rows:
            return None

        # Construction de l'ensemble des capacités ciblées
        target_caps: Set[str] = set(need_caps) if need_caps else set()
        if task_type and not need_caps:
            for cap in _TASK_TYPE_TO_CAPS.get(task_type.lower(), []):
                target_caps.add(cap)
        if task_type:
            target_caps.add(task_type.lower())

        best_member: Optional[str] = None
        best_score: float = -1.0
        candidates: List[Dict[str, Any]] = []

        for row in rows:
            member = row["member"]
            try:
                tags = set(json.loads(row["capability_tags"]))
            except Exception:
                tags = set()

            # Latence convertie en secondes pour préserver l'équilibre du score
            latency_s = float(row["latency_ms"]) / 1000.0
            
            # Coût recalculé à chaud (pour supporter l'injection dynamique du token_meter)
            cost = get_member_cost(member)
            if cost <= 0.0 and row["cost"] > 0.0:
                cost = float(row["cost"])

            quota_restant = row["quota_restant"]

            # Calcul du fit de capacités
            if target_caps:
                matched = len(target_caps.intersection(tags))
                if matched == 0:
                    capability_fit = 0.05
                else:
                    capability_fit = (matched + 0.1) / (len(target_caps) + 0.1)
            else:
                capability_fit = 1.0

            # Score = Efficacité brute
            # Ajout de 0.001 pour éviter une éventuelle division par zéro
            denom = cost + latency_s + 0.001
            score = capability_fit / denom

            # Modulation par quota
            score = _modulate_by_quota(score, quota_restant)

            # Candidat pour le solveur a contrainte dure (P7, capability=floor dur)
            candidates.append({
                "name": member, "capability": capability_fit, "cost": cost,
                "latency_ms": float(row["latency_ms"]),
                "quota_ok": (quota_restant if quota_restant is not None else 1) > 0,
            })

            if score > best_score:
                best_score = score
                best_member = member

        # P7 : solveur a contrainte dure (anti-Goodhart) en OPTION (flag OFF par defaut
        # = comportement inchange). capability = plancher DUR ; cout = objectif minimise.
        if os.environ.get("LAFORGE_ROUTE_SOLVER") == "1" and candidates:
            try:
                from nokido_agent.tools.forge_route_solver import solve_route
                rs = solve_route(task_type, candidates)
                if rs:
                    return rs
            except Exception:
                pass

        return best_member
    except Exception as e:
        print(f"Error resolving best member in pool: {e}", file=sys.stderr)
        return None
    finally:
        conn.close()


def main() -> int:
    """Affiche l'état en direct du registre du pool."""
    init_db()
    conn = get_db_connection()
    try:
        count = conn.execute("SELECT count(*) FROM forge_pool_registry").fetchone()[0]
        if count == 0:
            print("Pool registry is empty, bootstrapping defaults...")
            conn.close()
            bootstrap_registry()
            conn = get_db_connection()

        rows = conn.execute("SELECT * FROM forge_pool_registry ORDER BY available DESC, last_updated DESC").fetchall()
        summary = []
        for r in rows:
            summary.append({
                "member": r["member"],
                "kind": r["kind"],
                "tags": json.loads(r["capability_tags"]),
                "cost": r["cost"],
                "latency_ms": r["latency_ms"],
                "quota": r["quota_restant"],
                "available": bool(r["available"]),
                "last_updated": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r["last_updated"]))
            })
        print(json.dumps({
            "total_members": len(summary),
            "members": summary,
            "best_for_code": best("code"),
            "best_for_veille": best("veille"),
            "best_for_run": best("run_command")
        }, indent=2, ensure_ascii=False))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
