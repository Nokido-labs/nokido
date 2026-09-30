"""
app/forge_body_world_model.py — World Model du corps (P2-1).
Pédit l'impact d'une action lifecycle (stop/kill/restart/pause) AVANT exécution.
"""

__FORGE_COLOR__ = "vegetatif/monitor : world model du corps, predit l'impact d'une action lifecycle"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import tomllib
import urllib.request
from collections import deque
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"
SUPERVISOR_STATUS_URL = "http://127.0.0.1:8765/supervisor/status"


def load_services_config(toml_path: Path = SERVICES_TOML) -> Dict[str, dict]:
    """Parse proxy_deno/core/services.toml and extract services metadata."""
    toml_path = Path(toml_path)  # coercition str->Path (robustesse gate, review Claude 23/07)
    if not toml_path.exists():
        return {}
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    
    services = {}
    for s in data.get("service", []):
        name = s.get("name")
        if not name:
            continue
        services[name] = {
            "name": name,
            "port": s.get("port"),
            "deps": s.get("deps", []),  # list of port numbers or service names
            "wave": s.get("wave", 5),
            "essential": s.get("essential", False),
        }
    return services


def get_live_supervisor_status(url: str = SUPERVISOR_STATUS_URL) -> Dict[str, dict]:
    """Interroge :8765/supervisor/status pour la correspondance live port<->service."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NokidoBodyWorldModel/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else {}
    except Exception:  # muet-ok : sonde HTTP best-effort, défaut = {}
        pass
    return {}


def build_dependency_graph(toml_path: Path = SERVICES_TOML) -> tuple[Dict[str, Set[str]], Dict[str, dict]]:
    """
    Construit le graphe de dépendances inverses (reverse-dep).
    Returns (reverse_deps, services_meta).
    reverse_deps[service_A] = set of services that depend on service_A.
    """
    services = load_services_config(toml_path)
    live_status = get_live_supervisor_status()
    
    # Map port -> service_name (merge static toml and live status)
    port_to_service: Dict[int, str] = {}
    for sname, sdata in services.items():
        if sdata.get("port"):
            port_to_service[int(sdata["port"])] = sname
            
    for sname, sdata in live_status.items():
        if isinstance(sdata, dict) and sdata.get("port"):
            port_to_service[int(sdata["port"])] = sname
            if sname not in services:
                services[sname] = {
                    "name": sname,
                    "port": sdata.get("port"),
                    "deps": sdata.get("deps", []),
                    "wave": sdata.get("wave", 5),
                    "essential": sdata.get("essential", False),
                }

    reverse_deps: Dict[str, Set[str]] = {sname: set() for sname in services}
    
    for sname, sdata in services.items():
        deps = sdata.get("deps", [])
        for dep in deps:
            dep_target = None
            if isinstance(dep, int) or (isinstance(dep, str) and dep.isdigit()):
                dep_port = int(dep)
                dep_target = port_to_service.get(dep_port)
            elif isinstance(dep, str):
                dep_target = dep
                
            if dep_target and dep_target in services:
                reverse_deps.setdefault(dep_target, set()).add(sname)

    return reverse_deps, services


def predict_impact(service_name: str, action: str, toml_path: Path = SERVICES_TOML) -> dict:
    """
    Prédit l'impact d'une action lifecycle sur un service.
    Verdict: 'safe' | 'risky' | 'dangerous'
    """
    reverse_deps, services = build_dependency_graph(toml_path)
    
    # Resolve target name (case-insensitive or alias lookup)
    target = None
    for sname in services:
        if sname.lower() == service_name.lower():
            target = sname
            break
            
    if not target:
        # Fallback check if service_name matches hub or port 8766
        if service_name.lower() in ("hub", "NokidoMCP", "8766"):
            target = "NokidoMCP"
        else:
            return {
                "target": service_name,
                "action": action,
                "direct_dependents": [],
                "transitive_dependents": [],
                "essential_affected": [],
                "verdict": "safe",
                "reason": f"Service '{service_name}' non trouve dans le registre.",
            }

    direct_dependents = sorted(list(reverse_deps.get(target, set())))
    
    # BFS pour trouver tous les dépendants transitifs
    transitive_set: Set[str] = set()
    queue = deque(direct_dependents)
    while queue:
        curr = queue.popleft()
        if curr not in transitive_set:
            transitive_set.add(curr)
            for parent in reverse_deps.get(curr, set()):
                if parent not in transitive_set:
                    queue.append(parent)
                    
    transitive_dependents = sorted(list(transitive_set))
    
    # Identifier les services essentiels affectés (cible + dépendants)
    essential_affected = []
    if services.get(target, {}).get("essential"):
        essential_affected.append(target)
    for dep in transitive_dependents:
        if services.get(dep, {}).get("essential"):
            essential_affected.append(dep)
    essential_affected = sorted(list(set(essential_affected)))
    
    # Règles de verdict
    if essential_affected:
        verdict = "dangerous"
        reason = f"Services essentiels affectes: {', '.join(essential_affected)}"
    elif len(transitive_dependents) >= 3:
        verdict = "risky"
        reason = f">=3 dependants non-essentiels affectes ({len(transitive_dependents)})"
    else:
        verdict = "safe"
        reason = f"Aucun service essentiel affecte et <3 dependants ({len(transitive_dependents)})"
        
    # Score de propagation ACTUALISÉ (Successor Representation) : au-delà du compte
    # brut de dépendants, pondère par la distance (proches > lointains) et la
    # centralité. Best-effort : n'altère JAMAIS le verdict existant, champ INFO.
    try:
        from nokido_agent.app.forge_successor_repr import propagation_score
        prop_score = propagation_score(reverse_deps, target)
    except Exception:  # muet-ok: enrichissement SR, jamais bloquant pour le verdict
        prop_score = None

    return {
        "target": target,
        "action": action,
        "direct_dependents": direct_dependents,
        "transitive_dependents": transitive_dependents,
        "essential_affected": essential_affected,
        "propagation_score": prop_score,
        "verdict": verdict,
        "reason": reason,
    }


SUPERVISOR_URL = "http://127.0.0.1:8765/supervisor/status"


def _resolve_pid(pid: int):
    """pid -> (service_name, claimed_pid) via le port ecoute + le registre superviseur.
    (None, None) si hors registre. Le port/pid se lisent sans ACL."""
    import psutil
    import urllib.request

    ports = set()
    try:
        for c in psutil.net_connections("tcp"):
            if c.status == "LISTEN" and c.pid == pid and c.laddr:
                ports.add(c.laddr.port)
    except Exception:
        return None, None
    if not ports:
        return None, None
    try:
        with urllib.request.urlopen(SUPERVISOR_URL, timeout=4) as r:
            svc = json.loads(r.read()).get("services", {})
        for name, info in svc.items():
            if info.get("port") in ports:
                return name, info.get("pid")
    except Exception:
        pass
    return None, None


def guard(target, action, force: bool = False, toml_path: Path = SERVICES_TOML) -> dict:
    """GATE reutilisable AVANT une action destructive. target = nom de service (str)
    OU pid (int). Retourne {allowed: bool, impact: dict}.

    Pour un PID : s'il n'est PAS le listener REVENDIQUE par le superviseur (= un
    duplicata/zombie), le tuer ne fait PAS tomber le service -> allowed (ne casse pas
    le reconcile). S'il EST le legit, on predit l'impact et on refuse un stop/kill
    'dangerous' sauf force. Pour un NOM, on predit directement. Best-effort."""
    import os as _os

    a = str(action).lower()
    destructive = a in ("stop", "kill", "terminate")
    forced = bool(force) or bool(_os.environ.get("LAFORGE_LIFECYCLE_FORCE"))

    name = target
    if isinstance(target, int):
        name, claimed = _resolve_pid(target)
        if name is None:
            return {"allowed": True, "impact": {"verdict": "unknown",
                    "reason": f"pid {target} hors registre superviseur (non gouverne)"}}
        if claimed is not None and target != claimed:
            return {"allowed": True, "impact": {"verdict": "safe",
                    "reason": f"duplicata (pid {target} != legit {claimed}) -> service non affecte"}}
        # target EST le legit -> on predit l'impact ci-dessous

    try:
        imp = predict_impact(name, action, toml_path)
    except Exception as e:  # noqa: BLE001
        # fail-open (best-effort, on ne bloque jamais l'ops) MAIS on le rend VISIBLE :
        # un world-model casse = gate silencieusement neutralise = angle mort (audit 23-07).
        if destructive:
            print(f"[world-model] GATE fail-open sur action destructive '{action}' "
                  f"target={name}: predict err: {e}", flush=True)
        return {"allowed": True, "impact": {"verdict": "unknown", "reason": f"world-model err: {e}"}}
    allowed = not (destructive and imp.get("verdict") == "dangerous" and not forced)
    return {"allowed": allowed, "impact": imp}
