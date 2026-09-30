# -*- coding: utf-8 -*-
"""forge_tool_scope.py — Sprint 2 anti context-bomb : scope dynamique du catalogue MCP.

Un agent declare son INTENTION de session (tool `tool_scope` action=set) ; un
classifieur semantique 100% LOCAL (forge_semantic_routes.SemanticRouter,
embeddings, 0 LLM, 0 token cloud) choisit le GROUPE d'outils pertinent ;
get_tool_list (forge_mcp_registry) ne sert plus que ce groupe + CORE_TOOLS.
Le bus swarm emet un event kind `capability.forged` (kind REUTILISE expres :
le bridge stdio `_watch_capabilities` matche cette chaine dans le miroir
sandbox/reflexion.jsonl et pousse notifications/tools/list_changed -> le
client re-fetch tools/list et voit la vue reduite).

ROBUSTESSE (jamais casser un workflow) :
- Visibilite SEULEMENT : le dispatch registry n'est PAS filtre -> un outil
  hors scope reste appelable (fallback structurel).
- Confiance sous seuil OU embedder indisponible -> AUCUN scope (liste pleine).
- TTL : un scope expire (defaut 4h) -> retour auto a la liste pleine.
- Etat par agent : sandbox/tool_scope.json (lu LIVE, cache mtime).

Reponses M2M : intent codes courts (SCOPE_SET / SCOPE_CLEARED / SCOPE_STATUS /
SCOPE_LOW_CONF_FULL / ERR_*), pas de prose — cf. reflexion M2M AGY 2026-07-05.
"""
from __future__ import annotations

__FORGE_COLOR__ = "snc/mcp : scope dynamique du catalogue MCP (anti context-bomb)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

_ROOT = Path(__file__).resolve().parent.parent
_STATE = _ROOT / "sandbox" / "tool_scope.json"
_TTL_S = int(os.environ.get("LAFORGE_TOOL_SCOPE_TTL", "14400"))
_THRESHOLD = float(os.environ.get("LAFORGE_TOOL_SCOPE_MIN_CONF", "0.5"))

# Toujours visibles, quel que soit le scope : pilotage du scope lui-meme +
# portes de sortie universelles (shell gouverne, lecture, memoire, comms).
CORE_TOOLS = frozenset({
    "tool_scope", "hub", "run", "read", "rag", "task",
    "forge_call_dynamic", "forge_list_dynamic_tools",
    # `introspect` = la porte AVANT d'agir : elle doit exister quelle que soit
    # l'intention declaree. Un agent qui a declare « code_recon » et un agent qui
    # a declare « veille » ont le meme besoin de savoir ce que le corps sait
    # deja. La ranger dans un groupe la rendrait invisible a tous les autres.
    "introspect",
    # `governed_edit` est une porte de sortie au meme titre que `run` -- et la
    # plus SURE des deux. `run` est deja ici, or il ecrit, supprime et execute
    # sans validation AST ni scan de secret ; `governed_edit` fait la meme chose
    # en gouverne (AST, scan secret, tree_lock, relecture disque). L'exclure du
    # noyau pendant que `run` y figure fermait la porte etroite en laissant la
    # large ouverte : un agent scope sur `code_recon` n'avait plus que `run`
    # pour ecrire. Mesure du 2026-09-02 : le perimetre derive de CLAUDE valait
    # 17 tools SANS l'outil d'edition, alors que CLAUDE edite.
    "governed_edit",
    # Precondition de l'edition, donc aussi universelle qu'elle : les regles du
    # depot imposent de LIRE les tree_locks puis de PUBLIER son claim avant de
    # toucher un fichier tracke. Mettre `governed_edit` au noyau en laissant ces
    # deux-la dans `comms_agents` aurait rendu l'action possible en masquant sa
    # precondition -- un agent scope aurait edite sans pouvoir se coordonner,
    # c'est-a-dire en ecrasant les autres surfaces. Le commentaire ci-dessus
    # annonce « comms » depuis le debut : il n'etait pas honore.
    "blackboard_read_zone",
    "blackboard_propose_fact",
})

# Groupes d'outils (noms = catalogue registry). Un outil peut vivre dans
# plusieurs groupes. Source : _raw_tool_catalog (44 tools, census 2026-07-05).
TOOL_GROUPS: Dict[str, tuple] = {
    "code_recon": (
        "forge_deep_explore", "read_function_body", "get_file_skeleton",
        "get_function_dependencies", "query", "bundle", "graph_ppr",
        "graph_edge_score",
    ),
    "edition_code": (
        "governed_edit", "cross_platform_fs", "oracle_python_repl",
        "auto_test", "read_function_body", "get_file_skeleton",
    ),
    "exec_infra": (
        "nokido_ensure_service", "docker_action", "manage_forge_lifecycle",
        "forge_stats", "netcfg", "graph_cve_propagate", "event",
    ),
    "recherche_veille": (
        "web_search", "crawl", "biblio", "research_agent", "ask", "query",
    ),
    "orchestration_swarm": (
        "orchestrate", "loop_orchestrate", "plan", "route_dt", "route_task",
        "forge_spawn_swarm", "trigger_autonomous_evolution",
        "forge_trigger_audit", "skill", "dyn_orchestrate", "dyn_skill_forge",
        "ask",
    ),
    "comms_agents": (
        "event", "blackboard_read_zone", "blackboard_propose_fact",
        "agy_run", "agy_config", "agy_add_dir",
    ),
}

# Exemples d'intention par groupe (fit du SemanticRouter — embeddings locaux).
_UTTERANCES: Dict[str, list] = {
    "code_recon": [
        "explore le code du module et sa structure",
        "comprendre comment fonctionne cette fonction",
        "recon de l'architecture des fichiers du code",
        "ou est definie cette classe dans le code",
        "lire le squelette et les dependances d'un fichier code",
    ],
    "edition_code": [
        "edite le fichier et corrige le bug",
        "patch chirurgical du module puis validation",
        "ecrire un test pytest et corriger le code",
        "refactor de la fonction avec edition gouvernee",
        "appliquer un correctif d'edition sur le depot",
    ],
    "exec_infra": [
        "redemarre le service docker",
        "etat des services conteneurs et daemons",
        "infrastructure reseau switch vlan",
        "assure que le service ollama tourne",
        "diagnostic sante des services de la flotte",
    ],
    "recherche_veille": [
        "recherche web approfondie sur le sujet",
        "veille bibliographique arxiv papier",
        "crawl cette page web et ingere la doc",
        "monte un dossier de recherche web sur ce theme",
        "interroge la documentation et la biblio",
    ],
    "orchestration_swarm": [
        "orchestre une tache multi etapes",
        "lance un essaim swarm d'agents locaux",
        "plan multi agents et orchestration de roles",
        "declenche un audit par essaim",
        "route cette tache vers le bon modele orchestration",
    ],
    "comms_agents": [
        "envoie un message a l'agent",
        "notifie l'autre agent d'un message",
        "lis le blackboard partage entre agents",
        "assigne une tache a antigravity par message",
        "coordination inter agents boite aux lettres message",
    ],
}

_router_cache = None
_cache = {"mtime": -1.0, "data": {}}


def _reset() -> None:
    """Tests : purge les caches module (router + etat)."""
    global _router_cache
    _router_cache = None
    _cache["mtime"] = -1.0
    _cache["data"] = {}
    # `_ROLE_CACHE` en faisait partie sans etre purge : un test heritait alors du
    # perimetre calcule par le precedent, et passait pour de mauvaises raisons.
    # Une fonction qui dit « purge les caches » les purge TOUS.
    _ROLE_CACHE.clear()


def _router(embed_fn=None):
    """SemanticRouter pre-fit sur les groupes. embed_fn injectable (tests).
    Sans embed_fn : embedder Nokido par defaut (forge_embed_router, local)."""
    global _router_cache
    from nokido_agent.app.forge_semantic_routes import SemanticRouter

    if embed_fn is not None:
        sr = SemanticRouter(embed_fn)
        for g, utts in _UTTERANCES.items():
            sr.add_route(g, utts, threshold=_THRESHOLD)
        sr.fit()
        return sr
    if _router_cache is None:
        sr = SemanticRouter()
        for g, utts in _UTTERANCES.items():
            sr.add_route(g, utts, threshold=_THRESHOLD)
        sr.fit()
        _router_cache = sr
    return _router_cache


def _load_state() -> Dict[str, Any]:
    try:
        st = _STATE.stat()
    except OSError:
        return {}
    if st.st_mtime != _cache["mtime"]:
        try:
            _cache["data"] = json.loads(_STATE.read_text(encoding="utf-8"))
        except Exception:
            _cache["data"] = {}
        _cache["mtime"] = st.st_mtime
    return _cache["data"]


def _save_state(data: Dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _STATE)
    _cache["mtime"] = -1.0  # invalide le cache -> relecture


def _notify_list_changed(agent: str, reason: str) -> None:
    """Pousse list_changed au client via le canal EXISTANT : forge_swarm_bus
    kind `capability.forged` -> miroir reflexion.jsonl -> bridge stdio push.
    Best-effort : ne bloque jamais l'appelant."""
    try:
        from nokido_agent.app.forge_swarm_bus import publish

        publish("capability.forged", {"src": "tool_scope", "agent": agent, "reason": reason}, topic="tools")
    except Exception:  # muet-ok : notification best-effort ; le scope est deja pose, seul l'avis au bus manque
        pass


def active_tools_for(agent: str) -> Optional[Set[str]]:
    """Set des tools visibles pour l'agent (scope + CORE), None = pas de scope
    (liste pleine). Consomme par forge_mcp_registry.get_tool_list. Ne leve jamais."""
    try:
        if not agent:
            return None
        entry = _load_state().get(str(agent).upper())
        if not entry:
            return None
        if _TTL_S and (time.time() - float(entry.get("ts", 0))) > _TTL_S:
            return None
        tools = set(entry.get("tools") or ())
        if not tools:
            return None
        return tools | set(CORE_TOOLS)
    except Exception:
        return None


# ── Scope PAR DÉFAUT dérivé du système (Agent Policier — ferme le bypass opt-out) ──
# Le périmètre attendu d'un agent NE doit PAS dépendre de sa bonne volonté (SCOPE_SET
# opt-in + TTL). Fallback system-owned : agent_profiles.specialites -> MÊME router que
# set_scope. Fail-open (None) si pas de profil / embedder down / confiance faible.
_ROLE_CACHE: Dict[str, Dict[str, Any]] = {}
_ROLE_TTL_S = 1800.0


def _specialites_for(agent: str) -> Optional[str]:
    """Lit agent_profiles.specialites (perimetre curé par le système). None si absent."""
    if not agent:
        return None
    a = str(agent)
    variants = {a, a.lower(), a.upper(), "agt_" + a.lower().replace("agt_", "")}
    try:
        import sqlite3

        db = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
        with sqlite3.connect(str(db), timeout=3) as con:
            qmarks = ",".join("?" * len(variants))
            row = con.execute(
                f"SELECT specialites FROM agent_profiles WHERE agent_id IN ({qmarks}) "
                "AND specialites IS NOT NULL AND specialites != '' LIMIT 1",
                tuple(variants),
            ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# Repli deterministe du routeur : mots-clefs -> groupe. Volontairement PAUVRE.
# Un lexique trop riche ferait gagner un groupe par hasard ; ici un mot n'est
# retenu que s'il designe sans ambiguite une famille d'outils.
_LEXIQUE_GROUPES: Dict[str, frozenset] = {
    "code_recon": frozenset({
        "recon", "exploration", "analyse", "architecture", "adr", "audit",
        "graph", "dependances", "squelette", "lecture", "long-context",
    }),
    "edition_code": frozenset({
        "edition", "refactoring", "patch", "tests", "generation-code", "fim",
        "ide", "coding", "code-senior", "multi-fichiers", "debugging", "debug",
    }),
    "exec_infra": frozenset({
        "infra", "service", "docker", "container", "conteneur", "gpu",
        "runtime", "inference", "deploiement", "reseau", "network",
        "maintenance", "cleanup", "sandbox", "execution",
    }),
    "recherche_veille": frozenset({
        "veille", "recherche", "research", "web", "rag", "search", "crawl",
        "biblio", "embeddings", "vectorisation", "recherche-semantique",
    }),
    "orchestration_swarm": frozenset({
        "orchestration", "swarm", "plan", "planification", "dag", "parallele",
        "tasks", "multi-agent", "agentic", "workflow",
    }),
    "comms_agents": frozenset({
        "messaging", "comms", "send", "recv", "poll", "notification", "postal",
        "second-avis", "arbitrage",
    }),
}


def _normaliser(txt: str) -> Set[str]:
    """Mots-clefs comparables : minuscules, sans accent, separes par , / ; / espace."""
    import unicodedata

    plat = unicodedata.normalize("NFKD", str(txt or "").lower())
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    for sep in (",", ";", "/", "|", "\n", "\t"):
        plat = plat.replace(sep, " ")
    return {m.strip() for m in plat.split(" ") if m.strip()}


def _route_lexicale(spec: str) -> Optional[str]:
    """Groupe designe par les mots-clefs, ou None si ce n'est pas net.

    Regle d'abstention : il faut un gagnant STRICT. Une egalite entre deux
    groupes rend None -- sur-contraindre un agent sur un depart au hasard
    coute plus cher que de le laisser voir le catalogue entier.
    """
    mots = _normaliser(spec)
    if not mots:
        return None
    scores = {g: len(mots & lex) for g, lex in _LEXIQUE_GROUPES.items()}
    meilleur = max(scores.values()) if scores else 0
    if meilleur == 0:
        return None
    gagnants = [g for g, s in scores.items() if s == meilleur]
    if len(gagnants) != 1:
        return None  # ambigu : on s'abstient plutot que de trancher au hasard
    groupe = gagnants[0]
    return groupe if groupe in TOOL_GROUPS else None


def role_scope_for(agent: str, embed_fn=None) -> Optional[Set[str]]:
    """Scope attendu dérivé du profil système (specialites -> router). Cache TTL.
    None = non dérivable (pas de profil / embedder down / confiance faible) -> fail-open."""
    if not agent:
        return None
    key = str(agent).upper()
    ent = _ROLE_CACHE.get(key)
    if ent and (time.time() - float(ent.get("ts", 0))) < _ROLE_TTL_S:
        return ent.get("tools")
    spec = _specialites_for(agent)
    if not spec:
        return None
    methode = "semantique"
    group = None
    try:
        group, _score = _router(embed_fn).route(spec)
    except Exception:
        # Embedder indisponible : ne PAS conclure a l'absence de perimetre.
        # Mesure du 2026-09-02 : l'embedder etant HS, cette branche rendait None
        # pour TOUS les agents, y compris les quatre qui ont des specialites --
        # le scope par role etait donc muet exactement quand le corps est degrade.
        # Les specialites sont des mots-clefs ("architecture,securite,ADR"), pas
        # de la prose : un appariement lexical les route sans aucun embedder.
        # embed_fn fourni = test : on n'y masque pas l'echec par un repli.
        if embed_fn is None:
            group = _route_lexicale(spec)
            methode = "lexical"
        else:
            return None
    if not group and embed_fn is None:
        # L'embedder HS ne LEVE PAS : il rend « aucun groupe ». Brancher le repli
        # sur le seul `except` le rendait donc inatteignable -- mesure du
        # 2026-09-02 : `_route_lexicale` tranchait correctement en isolation
        # pendant que `expected_scope_for` rendait None pour tout le monde.
        # Une panne qui se manifeste par une VALEUR ne se rattrape pas par une
        # exception. Le repli s'abstient de lui-meme si les mots-clefs ne
        # designent pas un groupe unique : couvrir les deux cas ne sur-contraint
        # personne.
        group = _route_lexicale(spec)
        methode = "lexical"
    if not group:
        return None  # confiance faible ET repli muet -> pas de scope dérivé
    tools = set(TOOL_GROUPS[group]) | set(CORE_TOOLS)
    _ROLE_CACHE[key] = {"tools": tools, "ts": time.time(),
                        "methode": methode, "groupe": group}
    return tools


def methode_du_role(agent: str) -> Optional[str]:
    """Comment le perimetre de cet agent a ete derive : 'semantique' | 'lexical'.

    None = aucune derivation en cache. Distinguer les deux compte : un scope
    lexical est un REPLI, il dit que l'embedder etait absent au moment ou on a
    tranche. Le confondre avec un routage semantique ferait passer une panne
    pour un fonctionnement nominal.
    """
    ent = _ROLE_CACHE.get(str(agent or "").upper())
    return ent.get("methode") if ent else None


def expected_scope_for(agent: str, embed_fn=None) -> tuple:
    """Périmètre attendu : DÉCLARÉ (SCOPE_SET) prioritaire, sinon dérivé du rôle.
    Retour (tools:set|None, source:'declared'|'role_derived'|None)."""
    declared = active_tools_for(agent)
    if declared:
        return declared, "declared"
    role = role_scope_for(agent, embed_fn=embed_fn)
    if role:
        # La source NOMME la methode : un perimetre obtenu par repli lexical dit
        # que l'embedder etait absent quand on a tranche. Rendre le meme libelle
        # dans les deux cas ferait passer une panne pour un fonctionnement
        # nominal dans les journaux du gate d'intention.
        return role, ("role_derived_lexical"
                      if methode_du_role(agent) == "lexical" else "role_derived")
    return None, None


def set_scope(agent: str, intent: str, embed_fn=None) -> Dict[str, Any]:
    agent = str(agent or "").upper()
    if not agent:
        return {"intent_code": "ERR_NO_AGENT"}
    if not (intent or "").strip():
        return {"intent_code": "ERR_NO_INTENT"}
    try:
        group, score = _router(embed_fn).route(intent)
    except Exception as e:  # embedder down -> liste pleine, jamais bloquer
        return {"intent_code": "ERR_EMBED_DOWN", "error": str(e)[:120], "scope": "full"}
    if not group:
        clear_scope(agent, notify=False)
        return {"intent_code": "SCOPE_LOW_CONF_FULL", "confidence": round(float(score), 3)}
    tools = sorted(set(TOOL_GROUPS[group]))
    data = dict(_load_state())
    data[agent] = {
        "group": group,
        "tools": tools,
        "intent": str(intent)[:200],
        "confidence": round(float(score), 3),
        "ts": time.time(),
    }
    _save_state(data)
    _notify_list_changed(agent, f"set:{group}")
    return {
        "intent_code": "SCOPE_SET",
        "group": group,
        "n_tools": len(set(tools) | set(CORE_TOOLS)),
        "confidence": round(float(score), 3),
        "ttl_s": _TTL_S,
    }


def clear_scope(agent: str, notify: bool = True) -> Dict[str, Any]:
    agent = str(agent or "").upper()
    data = dict(_load_state())
    existed = agent in data
    if existed:
        del data[agent]
        _save_state(data)
        if notify:
            _notify_list_changed(agent, "clear")
    return {"intent_code": "SCOPE_CLEARED", "was_scoped": existed}


def scope_status(agent: str) -> Dict[str, Any]:
    agent = str(agent or "").upper()
    entry = _load_state().get(agent)
    if not entry:
        return {"intent_code": "SCOPE_STATUS", "scoped": False}
    age = time.time() - float(entry.get("ts", 0))
    return {
        "intent_code": "SCOPE_STATUS",
        "scoped": bool(age <= _TTL_S) if _TTL_S else True,
        "group": entry.get("group"),
        "n_tools": len(set(entry.get("tools") or ()) | set(CORE_TOOLS)),
        "age_s": int(age),
        "ttl_s": _TTL_S,
    }


def handle(args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:
    """Point d'entree du verbe MCP `tool_scope` (appele par forge_mcp_registry).
    action=set|clear|status ; target_agent != appelant reserve ring<=1."""
    action = str(args.get("action") or "status").lower()
    target = str(args.get("target_agent") or agent or "").upper()
    if target != str(agent or "").upper() and ring > 1:
        return {"intent_code": "ERR_FORBIDDEN_TARGET", "reason": "target_agent != caller requiert ring<=1"}
    if action == "set":
        return set_scope(target, str(args.get("intent") or ""))
    if action == "clear":
        return clear_scope(target)
    if action == "status":
        return scope_status(target)
    return {"intent_code": "ERR_BAD_ACTION", "allowed": ["set", "clear", "status"]}
