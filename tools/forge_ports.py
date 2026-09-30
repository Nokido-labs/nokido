#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_ports.py — registre CANONIQUE des ports reseau Nokido + audit/logging.

PROBLEME : les ports sont hardcodes service-par-service. Un clash (deux services
sur le meme port, ou un squatter) = wedge SILENCIEUX (cf LlamaEdge: is_available
faux-positif sur :8080 deja pris). Pas de source unique, pas de log d'etat.

SOLUTION : source unique `PORTS` + helpers logges. Toute nouvelle liaison passe
par `for_service(name)` / `find_free()` au lieu de hardcoder, et `owner_report()`
logge QUI ecoute QUOI -> un wedge se diagnostique en un coup d'oeil.

    LAFORGE_PYTHON tools/forge_ports.py            # audit (map + listening + clashs)
    LAFORGE_PYTHON tools/forge_ports.py --json     # sortie JSON

ANTI-DUP : forge_endpoint_registry = endpoints LLM (providers), PAS les ports
reseau de service. Ce module couvre les ports d'ecoute (bind), lui les modeles.
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/ports : registre canonique des ports Nokido, audit et journal"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import logging
import socket
import sys

log = logging.getLogger("forge.ports")

# ── Registre canonique : service -> port d'ecoute. SOURCE UNIQUE. ────────────
# Etendre ICI quand un service prend un port. Ne JAMAIS hardcoder ailleurs :
# importer `from forge_ports import PORTS, for_service`.
PORTS: dict[str, int] = {
    "hub": 8766,            # Nokido Sovereign Hub (MCP)
    "ollama": 11434,        # Ollama
    "github_sidecar": 9200, # GitHub sidecar (repos RAM)
    "web_portal": 7400,     # portail web (runAs interactif)
    "netcfg_web": 7500,     # netcfg-agent FastAPI
    "netcfg_mcp": 8767,     # netcfg-agent MCP
    "deno_proxy": 8000,     # Nervous System Deno proxy
    "lmstudio": 1234,       # LM Studio (/v1 OpenAI-compat)
    "llamacpp": 8090,       # llama.cpp natif (/v1)
    "llama_native": 8091,   # llama natif
    "embed": 8099,          # embedder router (NPU)
    "lobehub": 3210,        # LobeHub UI
    "acp_ws": 7782,         # ACP WebSocket ingress
    "llamaedge": 8088,      # LlamaEdge WASM /v1 (8080 = canonique LlamaEdge mais DEJA pris ici)
    "webhub_deno": 7401,    # Deno WebHub (portail public)
    "webhub_wasm": 7402,    # Wasmtime daemon (graduation out-of-process)
}

# Plage par defaut pour l'allocation dynamique (find_free).
_DYN_LO, _DYN_HI = 8100, 8999


def probe(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """True si quelque chose ECOUTE sur host:port (connexion TCP acceptee)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


def owner(port: int) -> dict:
    """Qui ecoute sur le port : {listening, pid, proc, path}. psutil si dispo,
    sinon listening seul. Best-effort (l'enum peut etre partiel sans privilege)."""
    info: dict = {"port": port, "listening": probe(port), "pid": None, "proc": None, "path": None}
    try:
        import psutil  # type: ignore

        for c in psutil.net_connections(kind="inet"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN:
                info["listening"] = True
                if c.pid:
                    info["pid"] = c.pid
                    try:
                        p = psutil.Process(c.pid)
                        info["proc"] = p.name()
                        info["path"] = p.exe()
                    except Exception:  # noqa: BLE001
                        pass
                break
    except Exception:  # noqa: BLE001
        pass
    return info


def reserved_collisions() -> dict[int, list[str]]:
    """Clashs de CONFIG : un meme port reserve par >1 service dans PORTS."""
    by_port: dict[int, list[str]] = {}
    for name, port in PORTS.items():
        by_port.setdefault(port, []).append(name)
    return {p: names for p, names in by_port.items() if len(names) > 1}


def for_service(name: str) -> int:
    """Port reserve d'un service (lever si inconnu : force l'enregistrement ICI)."""
    if name not in PORTS:
        raise KeyError(f"port non reserve pour '{name}' — l'ajouter dans forge_ports.PORTS")
    log.debug("port for_service(%s) -> %d", name, PORTS[name])
    return PORTS[name]


def find_free(preferred: int | None = None, lo: int = _DYN_LO, hi: int = _DYN_HI) -> int:
    """Retourne `preferred` s'il est libre, sinon le 1er port libre de [lo, hi].
    Logge le choix (et l'eviction si preferred etait pris)."""
    reserved = set(PORTS.values())
    if preferred and not probe(preferred):
        return preferred
    if preferred:
        log.warning("port prefere %d occupe -> recherche d'un libre dans [%d,%d]", preferred, lo, hi)
    for p in range(lo, hi + 1):
        if p in reserved:
            continue
        if not probe(p):
            log.info("find_free -> %d", p)
            return p
    raise RuntimeError(f"aucun port libre dans [{lo},{hi}]")


def owner_report(log_it: bool = True) -> list[dict]:
    """Etat de TOUS les ports reserves : listening + pid/proc. Logge les anomalies
    (port reserve mais ECOUTE par un proc inattendu n'est pas detectable par nom
    seul ; on logge ce qui ecoute pour inspection humaine + les clashs de config)."""
    rows = []
    for name, port in sorted(PORTS.items(), key=lambda kv: kv[1]):
        o = owner(port)
        o["service"] = name
        rows.append(o)
        if log_it and o["listening"]:
            log.info("port %d (%s) : LISTEN pid=%s proc=%s", port, name, o["pid"], o["proc"])
    if log_it:
        for p, names in reserved_collisions().items():
            log.error("CLASH CONFIG : port %d reserve par %s — corriger forge_ports.PORTS", p, names)
    return rows


def ensure_bindable(name: str, port: int | None = None) -> int:
    """A appeler par un service JUSTE avant de binder. Logge l'intention ; si le port
    ECOUTE deja (clash -> le bind echouerait = wedge silencieux), logge une ERREUR
    explicite avec l'owner (pid/proc) au lieu d'un echec opaque. Retourne le port."""
    p = port if port is not None else PORTS.get(name)
    if p is None:
        raise KeyError(f"port non reserve pour '{name}' — l'ajouter dans forge_ports.PORTS")
    if probe(p):
        o = owner(p)
        log.error(
            "BIND CLASH : '%s' veut :%d mais DEJA pris par pid=%s proc=%s — le bind va echouer",
            name, p, o.get("pid"), o.get("proc"),
        )
    else:
        log.info("bind '%s' -> :%d (libre)", name, p)
    return p


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows = owner_report(log_it=False)
    coll = reserved_collisions()
    if "--json" in sys.argv:
        print(json.dumps({"ports": rows, "config_collisions": coll}, ensure_ascii=False, indent=2))
        return 0
    print("=== forge_ports — registre + etat live ===")
    print(f"{'service':16s} {'port':>5s} {'listen':>6s}  owner")
    for r in rows:
        own = f"pid={r['pid']} {r['proc']}" if r["listening"] else "-"
        print(f"{r['service']:16s} {r['port']:>5d} {('YES' if r['listening'] else 'no'):>6s}  {own}")
    if coll:
        print("\n!! CLASHS DE CONFIG (meme port, >1 service) :")
        for p, names in coll.items():
            print(f"   {p} <- {names}")
    else:
        print("\nconfig OK : aucun port reserve en double.")
    return 1 if coll else 0


if __name__ == "__main__":
    raise SystemExit(main())
