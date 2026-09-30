#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_keeper_base.py — base commune des OrganAgents KEEPER (tenue + présentation).

Directive user : décliner le MÊME principe que forge_roadmap_keeper sur la MÉMOIRE et
TOUT ce qui doit être PARTAGÉ. Un KEEPER = l'OWNER dédié d'un artefact partagé : il le
TIENT (regen/maintien) et le PRÉSENTE (vues), sous contrat OrganAgent
(cf. blackboard architecture_rules:organ_agent_contract).

Fournit le SOCLE réutilisé par chaque keeper concret :
  - keeper_contract(...)   : construit le contrat OrganAgent normalisé.
  - register(...) / KEEPER_REGISTRY : tous les keepers déclarés, DÉCOUVRABLES (portier/gate).
  - present_any / status_any : dispatch générique vers le bon keeper.
  - discover() : importe les keepers connus pour peupler le registre.
  - find(pattern) : recherche via l'INDEX LOCAL RAPIDE (RAG FTS5 BM25, souverain) au lieu
    de Grep natif (directive user : « index rapide local plus intelligent »). Le code
    Nokido est ~100% vectorisé/indexé -> recall sans re-scan disque.

ANTI-DUP : n'EXÉCUTE aucun métier — fédère les keepers concrets + l'index RAG existant
(RAG/embeddings.db, rag_fts FTS5). Ne réimplémente NI le RAG NI les primitives mémoire.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
_DB = ROOT / "RAG" / "embeddings.db"

# Registre des keepers : name -> {owns, present, status, regen, contract, source}
KEEPER_REGISTRY: dict[str, dict] = {}

# Keepers concrets connus (importés par discover() pour auto-enregistrement).
_KNOWN_KEEPERS = ("forge_roadmap_keeper", "forge_memory_keeper")


def keeper_contract(agent: str, *, organ: str, owns: str, modalities=None,
                    triggers=None, poolable: bool = False, connects_to=None,
                    verbs=None) -> dict:
    """Contrat OrganAgent normalisé pour un keeper (forme unique = alignement émané)."""
    return {
        "agent": agent,
        "organ": organ,
        "owns": owns,
        "modalities": modalities or ["text", "markdown"],
        "proactive_triggers": triggers or ["on_request", "post_commit", "schedule_daily"],
        "poolable": poolable,                 # owner UNIQUE par défaut (source de vérité)
        "connects_to": connects_to or ["RAG", "blackboard", "forge_postal(facteur)"],
        "verbs": verbs or ["regen", "present", "status", "contract"],
        "kind": "KEEPER",
    }


def register(name: str, *, owns: str, present, status=None, regen=None,
             contract=None, source: str = "module") -> str:
    """Enregistre un keeper. `present`/`status`/`regen` = callables (ou None). `source` :
    'module' (keeper dédié) | 'pointer' (artefact possédé par un module existant)."""
    KEEPER_REGISTRY[name] = {
        "owns": owns, "present": present, "status": status, "regen": regen,
        "contract": contract, "source": source,
    }
    return name


def declare(name: str, *, owns: str, owner_module: str, how: str) -> str:
    """Déclare un artefact partagé dont l'OWNER est un module EXISTANT (pas un keeper dédié).
    Anti-dup : on n'invente pas un keeper là où un propriétaire existe — on le RÉFÉRENCE."""
    return register(name, owns=owns, present=None, source=f"pointer:{owner_module} ({how})")


def discover() -> dict:
    """Peuple le registre en important les keepers connus. Renvoie {name: owns}."""
    import importlib
    import sys
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT))
    for mod in _KNOWN_KEEPERS:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001 - un keeper KO ne casse pas la découverte
            pass
    # ROSTER COMPLET des artefacts PARTAGÉS (directive user : « décline tous les keepers »).
    # Modules dédiés = roadmap + memory (importés ci-dessus). Le RESTE = pointer-declare vers
    # l'OWNER EXISTANT (anti-dup : on RÉFÉRENCE, on ne recrée pas un keeper là où il y a un
    # propriétaire). Promouvoir en module dédié au cas par cas si une vraie tenue émerge.
    _ROSTER = [
        # (name, owns, owner_module, how)
        ("rules", "blackboard:architecture_rules (alignement émané)", "forge_swarm_blackboard", "blackboard_read_zone"),
        ("canon", "CLAUDE.md + RULES_SHARED.md (règles de session)", "forge_module_census", "read fichier canon"),
        ("organ_map", "organ_map_full.json (anatomie 714 organes)", "forge_module_census", "carte organes"),
        ("skills", "docs/skills + ~/.claude|.gemini/skills", "forge_skill_sync", "--discover/--preview"),
        ("workflow", "plans déportés (sandbox/workspace/wf_plan_*.json)", "forge_workflow", "submit/run_plan"),
        ("agents", "config/agent_identities.json (identité×ring)", "forge_videur", "resolve_identity"),
        ("providers", "pool LLM live (cloud+local)", "forge_resolver", "live_providers"),
        ("gate", "politique de routage 3-voies + prior appris", "forge_orchestration_gate", "plan_route/classify"),
        ("postal", "inbox/messages inter-agents", "forge_postal", "poll/notify"),
        ("blackboard", "mémoire de travail zonée du swarm", "forge_swarm_blackboard", "read_zone"),
        ("docker", "état daemon/conteneurs", "forge_docker_keeper", "docker_action"),
        ("cowork", "projets-docs collègue IA (secrétaire)", "forge_cowork", "CoworkProject"),
        ("trace", "spans/observabilité", "forge_trace_viz", "to_tree"),
        ("graph", "graphe de connaissances", "forge_graph_universal", "ppr/expand"),
        ("veille", "intel/watch (souverain, anti-poison)", "forge_watch_agent", "digest"),
    ]
    for _name, _owns, _owner, _how in _ROSTER:
        declare(_name, owns=_owns, owner_module=_owner, how=_how)
    return {n: v["owns"] for n, v in KEEPER_REGISTRY.items()}


def present_any(name: str, view: str = "terse") -> str:
    k = KEEPER_REGISTRY.get(name)
    if not k:
        return f"[keeper inconnu: {name} — connus: {sorted(KEEPER_REGISTRY)}]"
    if not callable(k.get("present")):
        return f"[{name}] possédé par {k['source']} (pas de presenter dédié)"
    return k["present"](view)


def status_any(name: str) -> dict:
    k = KEEPER_REGISTRY.get(name)
    if not k:
        return {"error": f"keeper inconnu: {name}"}
    return k["status"]() if callable(k.get("status")) else {"source": k["source"]}


def find(pattern: str, *, limit: int = 8, source_like: str | None = None) -> list:
    """Recherche SOUVERAINE via l'index local rapide (RAG FTS5 BM25) — PAS Grep natif.
    `pattern` = expression FTS5 (ex: 'firewall OR pre_flight'). Pour du code/uncommitted
    NON encore indexé, Grep natif reste légitime (l'index suit le commit/ingest)."""
    if not _DB.exists():
        return [{"error": "index absent (RAG/embeddings.db)"}]
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    try:
        q = "SELECT source, substr(text,1,160) FROM rag_fts WHERE rag_fts MATCH ?"
        args: list = [pattern]
        if source_like:
            q += " AND source LIKE ?"
            args.append(source_like)
        q += " ORDER BY bm25(rag_fts) LIMIT ?"
        args.append(limit)
        return [{"source": s, "preview": t} for s, t in con.execute(q, args).fetchall()]
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]
    finally:
        con.close()


def _marker(name: str) -> str:
    """Token FTS5 mono-mot non ambigu pour retrouver l'artefact internalisé d'un keeper."""
    return f"KEEPERART_{name.upper()}"


def internalize(name: str, body: str, *, domain: str = "reference",
                problem: str | None = None) -> dict:
    """INTERNALISE l'artefact dans le SUBSTRAT SOUVERAIN Nokido (RAG indexé + gouverné, id
    déterministe) — pas un fichier perdu. La consultation devient un lookup interne rapide
    et PARTAGÉ entre agents. Réutilise forge_self_correction.anchor_solution (INSERT
    rag_chunks + sync FTS, règles d'or #3/#6). Le fichier de rendu reste un EXPORT.
    NB : exige un contexte inscriptible-repo (trusted/hub) — le sandbox déporté ne peut pas."""
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"self_correction indispo: {e}"}
    tagged = f"{_marker(name)}\n{(body or '')[:6000]}"
    return anchor_solution(
        problem=f"{_marker(name)} — artefact partagé internalisé ({name})",
        solution=tagged, example=f"consulter via forge_keeper_base.consult('{name}')",
        domain=domain)


def consult(name: str, query: str = "", *, limit: int = 6) -> list:
    """Consultation CENTRALE rapide de l'artefact INTERNALISÉ (index FTS5, pas de re-scan).
    Fluidifie le RAG : on tape l'index interne. `query` affine au sein de l'artefact."""
    pat = _marker(name) if not query else f"{_marker(name)} AND ({query})"
    return find(pat, limit=limit)


def announce(name: str, event: str, detail: str = "") -> dict:
    """INTÉGRATION FACTEUR : annonce un événement keeper (tenue/internalize) aux autres
    agents via forge_postal, awareness partagée. Fallback blackboard:scratch. Best-effort —
    dégrade sans lever si messager absent (l'annonce n'est jamais bloquante)."""
    msg = f"[KEEPER:{name}] {event} {detail}".strip()
    for _attempt in ("postal", "blackboard"):
        try:
            if _attempt == "postal":
                from nokido_agent.app.forge_postal import get_postal
                get_postal().notify(msg, to="ALL")
                return {"ok": True, "via": "postal", "msg": msg}
            from nokido_agent.app.forge_swarm_blackboard import get_blackboard
            get_blackboard().propose_fact("scratch", msg, key=f"keeper_{name}_{event}")
            return {"ok": True, "via": "blackboard", "msg": msg}
        except Exception:  # noqa: BLE001 - essaie le fallback suivant
            continue
    return {"ok": False, "note": "messager indisponible (annonce différée)", "msg": msg}


def integrate_portier() -> dict:
    """INTÉGRATION PORTIER : expose le registre keeper comme SOURCE consultable au portier
    (forge_knowledge_concierge). Le portier devient le dispatcher qui route une requête
    'roadmap/memory/rules/...' vers present_any/consult — consultation CENTRALE et rapide."""
    discover()
    return {"sources": {n: KEEPER_REGISTRY[n]["owns"] for n in KEEPER_REGISTRY},
            "present": "forge_keeper_base.present_any(name, view)",
            "consult": "forge_keeper_base.consult(name, query)"}


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    reg = discover()
    # NB en __main__ : les keeper-modules réimportent une 2e instance de base -> "roadmap"/
    # "memory" s'enregistrent ailleurs (artefact de test). On valide le ROSTER pointer, qui
    # s'enregistre TOUJOURS dans l'instance courante (prod = même instance, cf. memory_keeper).
    chk(len(reg) >= 12 and "agents" in reg and "gate" in reg,
        f"discover peuple le roster ({len(reg)} keepers): {sorted(reg)[:6]}…")
    chk("rules" in KEEPER_REGISTRY and KEEPER_REGISTRY["rules"]["source"].startswith("pointer:"),
        "surfaces pointer déclarées (rules/canon/skills)")
    c = keeper_contract("X_KEEPER", organ="governance", owns="docs/x.md")
    chk(c["kind"] == "KEEPER" and c["poolable"] is False and "present" in c["verbs"],
        "keeper_contract bien formé")
    res = find("firewall OR pre_flight", limit=3)
    chk(isinstance(res, list) and (not res or "source" in res[0] or "error" in res[0]),
        f"find() interroge l'index FTS5 local ({len(res)} hits)")
    miss = present_any("__nope__")
    chk("inconnu" in miss, "present_any gère keeper inconnu")
    chk(callable(internalize) and callable(consult)
        and _marker("roadmap") == "KEEPERART_ROADMAP", "internalize/consult + marker OK")
    cres = consult("__absent__")  # lecture index, ne doit pas lever
    chk(isinstance(cres, list), "consult() renvoie une liste (lookup interne)")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
