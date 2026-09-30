# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_cognitive_router
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_cognitive_router.py — Routage Dynamique Cognitif v0.13.1
===============================================================
Cervelet de Nokido : dirige chaque intention vers la ressource
la plus apte, en optimisant coût / sécurité / précision.

Piliers implémentés :
  1. Modality Routing     — complexité → modèle (ONNX/Qwen1.5B/7B/Claude)
  2. Security-Aware       — ring de la tâche → chemin forcé (déjà partiel)
  3. Capability Routing   — anticipation proactive [NEED:] avant le 1er appel
  4. Fallback Routing     — Ollama→LiteLLM→Claude si réponse vide/entropique
  5. Context Pruning      — filtre RAG par domaine/type avant injection

Usage :
  from forge_cognitive_router import route_task, prune_rag_context

  result = await route_task(
      task      = "débugge ce script Python",
      rag_ctx   = chunks,
      ring      = 1,
      session_id= "abc123",
  )
"""


import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# PILIER 1 — MODALITY ROUTING (complexité → modèle)
# =============================================================================

# Seuils de confiance NLU → niveau de complexité
_COMPLEXITY_THRESHOLDS = {
    "simple": 0.85,  # conf ≥ 0.85 → ONNX local ou Qwen 1.5B
    "technical": 0.55,  # 0.55 ≤ conf < 0.85 → Qwen 7B (défaut)
    "strategic": 0.00,  # conf < 0.55 → Claude via LiteLLM
}

# Patterns sémantiques → escalade forcée vers Claude
_STRATEGIC_PATTERNS = [
    r"\b(risque|risk|architecture|stratégie|strategy|analyse|sécurité globale)\b",
    r"\b(vulnérabilité critique|CVE|menace|threat model)\b",
    r"\b(décision|recommandation|impact|conséquence)\b",
    r"\b(compare|évalue|arbitre|choisir entre)\b",
]
_STRATEGIC_RE = re.compile("|".join(_STRATEGIC_PATTERNS), re.IGNORECASE)

# Patterns → tâche simple (ONNX/Qwen 0.5B)
_SIMPLE_PATTERNS = [
    r"\b(quelle heure|quel jour|date|bonjour|merci|ok|oui|non)\b",
    r"\b(liste|lire|affiche|montre|donne.?moi)\b.{0,30}\b(fichier|json|log|config)\b",
    r"^\w[\w\s]{0,20}$",  # phrase très courte
]
_SIMPLE_RE = re.compile("|".join(_SIMPLE_PATTERNS), re.IGNORECASE)


def _estimate_complexity(task: str, nlu_conf: float = 0.7) -> str:
    """
    Retourne 'simple' | 'technical' | 'strategic'.
    Combine la confiance NLU et l'analyse sémantique.
    """
    if _STRATEGIC_RE.search(task):
        return "strategic"
    if _SIMPLE_RE.search(task) and nlu_conf >= _COMPLEXITY_THRESHOLDS["simple"]:
        return "simple"
    if nlu_conf >= _COMPLEXITY_THRESHOLDS["simple"]:
        return "simple"
    if nlu_conf >= _COMPLEXITY_THRESHOLDS["technical"]:
        return "technical"
    return "strategic"


def _requires_cloud_capability(task: str) -> bool:
    """Vérifie si la tâche nécessite un accès réseau authentifié ou PAT (ex: GitHub)
    que seul l'exécuteur cloud (Claude/Antigravity via MCP) possède."""
    patterns = [
        r"\b(gh_run|github|gh api|pull request|pr|issue|pat|authentifié)\b",
    ]
    return bool(re.search("|".join(patterns), task, re.IGNORECASE))

def _select_model(complexity: str, ring: int, task: str = "") -> str:
    """
    Sélectionne le backend selon la complexité et le ring.
    ring=0 → local obligatoire (jamais cloud)
    """
    if ring == 0:
        return "local"  # forcé — aucun cloud autorisé

    # Axe 2 : Capacité d'accès (Network/PAT)
    if task and _requires_cloud_capability(task):
        logger.info(f"[cognitive-router] Escalade capability (PAT/Network) forcée pour: {task[:30]}...")
        return "litellm_cloud"

    models = {
        "simple": "onnx_local",  # ONNX MiniLM ou Qwen 0.5B
        "technical": "ollama",  # Qwen 7B local
        "strategic": "litellm_cloud",  # Claude / Gemini
    }
    return models.get(complexity, "ollama")


# =============================================================================
# PILIER 3 — CAPABILITY ROUTING (anticipation proactive [NEED:])
# =============================================================================

# Mots-clés → outils à pré-injecter AVANT le premier appel LLM
_CAPABILITY_TRIGGERS: dict[str, list[str]] = {
    "web_search": [
        "news",
        "actualité",
        "dernière version",
        "release",
        "internet",
        "recherche",
        "google",
        "cherche",
        "trouve sur le web",
        "CVE",
        "exploit",
    ],
    "rag_search": [
        "notre",
        "laforge",
        "le projet",
        "forge_",
        "contexte",
        "historique",
        "comment fonctionne",
        "qu'est-ce que",
    ],
    "read_file": ["fichier", "lis", "ouvre", "affiche", "contenu de", "lire"],
    "sql_query": ["base de données", "sqlite", "requête", "table", "event_log", "SELECT"],
    "run_python": ["exécute", "lance", "code python", "script", "calcule", "test"],
}


def _anticipate_tools(task: str) -> list[str]:
    """
    Analyse l'intent de la tâche et retourne la liste des outils
    à pré-injecter dans le prompt AVANT le premier appel LLM.
    Évite un round-trip inutile.
    """
    task_lower = task.lower()
    needed = []
    for tool, triggers in _CAPABILITY_TRIGGERS.items():
        if any(t in task_lower for t in triggers):
            needed.append(tool)
    return needed


def build_proactive_system(task: str, base_system: str) -> str:
    """
    Injecte la doc des outils anticipés dans le system prompt.
    Si 'news' détecté → doc web_search injectée avant même le [NEED:].
    """
    tools = _anticipate_tools(task)
    if not tools:
        return base_system

    from nokido_agent.app.forge_ollama_bridge import build_late_binding_doc

    docs = []
    for tool in tools:
        docs.append(f"[{tool}] : {build_late_binding_doc(tool)}")

    injection = (
        "\n\n[OUTILS PRÉ-CHARGÉS pour cette tâche]\n"
        + "\n".join(docs)
        + "\nUtilise directement ces outils si nécessaire. "
        "Syntaxe : [NEED: tool_name | ta_query]"
    )
    logger.debug(f"[capability-router] pré-injection : {tools}")
    return base_system + injection


# =============================================================================
# PILIER 4 — FALLBACK ROUTING (escalade Ollama→LiteLLM→Claude)
# =============================================================================


def _entropy_score(text: str) -> float:
    """
    Estime l'entropie d'une réponse (hallucination probable si > seuil).
    Heuristique : répétitions, phrases incohérentes, longueur anormale.
    Score 0.0 (parfait) → 1.0 (hallucination probable).
    """
    if not text:
        return 1.0

    # Longueur anormalement courte
    if len(text) < 20:
        return 0.9

    words = text.lower().split()
    if len(words) < 3:
        return 0.8

    # Répétitions : ratio mots uniques / total
    unique_ratio = len(set(words)) / len(words)
    repetition_score = 1.0 - unique_ratio  # 0 = parfait, 1 = tout répété

    # Patterns de non-réponse
    no_answer_patterns = [
        "je ne sais pas",
        "je ne peux pas",
        "désolé",
        "sorry",
        "i don't know",
        "as an ai",
        "en tant qu'ia",
    ]
    no_answer = any(p in text.lower() for p in no_answer_patterns)

    score = repetition_score * 0.6 + (0.4 if no_answer else 0.0)
    return min(score, 1.0)


_ENTROPY_THRESHOLD = 0.45  # au-dessus → escalade


async def _call_with_fallback(
    task: str,
    system: str,
    rag_ctx: str = "",
    max_tokens: int = 400,
    ring: int = 1,
    session_id: str = "",
) -> tuple[str, str]:
    """
    Délègue à forge_arbitrator.smart_dispatch() — escalade cognitive complète.
    Retourne (réponse, backend_utilisé).
    """
    try:
        from nokido_agent.app.forge_arbitrator import smart_dispatch

        result = await smart_dispatch(
            task=task,
            ring=ring,
            session_id=session_id,
            context=rag_ctx,
            max_tokens=max_tokens,
        )
        return result.response, result.backend
    except Exception as e:
        logger.warning(f"[cognitive-router] arbitrator erreur : {e}")

    # Fallback direct si arbitrator indisponible
    try:
        from nokido_agent.app.forge_ollama_bridge import get_bridge

        bridge = get_bridge()
        answer = await bridge.propose(task, rag_ctx=rag_ctx, max_tokens=max_tokens)
        if answer:
            return answer, "ollama_direct"
    except Exception:
        pass

    return "[Arbitre indisponible]", "error"


# =============================================================================
# PILIER 5 — CONTEXT PRUNING — filtres par domaine
# =============================================================================

_DOMAIN_FILTERS: dict[str, dict] = {
    "general": {"include": [], "exclude": []},
    "code": {"include": [".py", "forge_", "def ", "class "], "exclude": ["log", ".yml"]},
    "devops": {"include": [".yml", ".sh", "config", "docker"], "exclude": [".py"]},
    "securite": {"include": ["cve", "vuln", "ring", "token"], "exclude": []},
    "systeme": {"include": ["os", "process", "cpu", "memory"], "exclude": []},
    "reseau": {"include": ["network", "ip", "port", "socket"], "exclude": []},
    "ia": {"include": ["model", "llm", "embedding", "rag"], "exclude": []},
    "chat": {"include": [], "exclude": ["log", ".py", ".yml"]},
}


def prune_rag_context(
    chunks: list[dict],
    intent: str = "general",
    tool: str = "",
    k: int = 3,
) -> list[dict]:
    """
    Filtre les chunks RAG selon l'intent et l'outil demandé.

    Règles :
    - web_search : RAG exclu entièrement (évite de saturer avec l'historique)
    - code/coder : uniquement les chunks .py ou forge_*
    - devops     : uniquement .yml/.sh/config
    - chat       : exclure les logs et les .py

    Retourne au max k chunks filtrés.
    """
    if not chunks:
        return []

    # web_search → pas de RAG local (double-blind pour le web)
    if tool == "web_search":
        logger.debug("[pruning] web_search → RAG exclu entièrement")
        return []

    domain = intent if intent in _DOMAIN_FILTERS else "general"
    rules = _DOMAIN_FILTERS[domain]

    includes = rules.get("include", [])
    excludes = rules.get("exclude", [])

    # Tout exclu → retourner vide
    if "*" in excludes:
        return []

    filtered = []
    for chunk in chunks:
        source = chunk.get("source", "").lower()
        content = chunk.get("content", "").lower()

        # Vérifier exclusions
        if any(ex in source or ex in content for ex in excludes if ex):
            continue

        # Vérifier inclusions (si liste vide → tout accepté)
        if includes:
            if not any(inc in source or inc in content for inc in includes):
                continue

        filtered.append(chunk)

        if len(filtered) >= k:
            break

    logger.debug(f"[pruning] intent={intent} tool={tool} : {len(chunks)}→{len(filtered)} chunks")
    return filtered


# =============================================================================
# POINT D'ENTRÉE PRINCIPAL
# =============================================================================


async def route_task(
    task: str,
    rag_chunks: list[dict] = None,
    ring: int = 1,
    session_id: str = "",
    nlu_conf: float = 0.7,
    intent: str = "general",
) -> dict:
    """
    Routeur cognitif principal. Orchestre les 5 piliers.

    Retourne :
    {
        "response":   str,
        "backend":    str,        # ollama | litellm | claude | onnx_local
        "complexity": str,        # simple | technical | strategic
        "tools_preloaded": list,  # outils anticipés
        "chunks_used": int,
        "entropy":    float,
    }
    """
    rag_chunks = rag_chunks or []

    # ── Pilier 1 : Modality Routing ───────────────────────────────────────────
    complexity = _estimate_complexity(task, nlu_conf)
    backend = _select_model(complexity, ring, task)
    logger.info(f"[cognitive-router] complexity={complexity} backend={backend} ring={ring}")

    # ── Pilier 0 : AMI Configurator (task_type → actor_N, horizon, cost_lambda) ──
    _ami_config: dict = {}
    try:
        from nokido_agent.app.forge_configurator import configure_from_description

        _ami_config = configure_from_description(task)
        logger.info(
            f"[cognitive-router] ami task_type={_ami_config.get('task_type')} actor_N={_ami_config.get('actor_N')} horizon={_ami_config.get('horizon')}"
        )
    except Exception as _e:
        logger.debug(f"[cognitive-router] configurator skip: {_e}")

    # ── Pilier 6 : MPC Planning (plan_horizon — LeCun §4.3) ──────────────────
    # Uses forge_mpc.plan_horizon() — gradient-free MPC over world model.
    # Fallback: mcts_propose() si plan_horizon indisponible.
    # Projection 1024→384 : base vectorielle reste 1024D, AMI interne = 384D.
    _mpc_best_action: dict = {}
    _mpc_triggers = {"security_audit", "analysis", "orchestration", "refactor", "research"}
    if _ami_config.get("task_type") in _mpc_triggers or _ami_config.get("use_mcts"):
        try:
            import numpy as np
            from nokido_agent.app.forge_state_encoder import encode_state as _enc

            _s_emb_raw = _enc(task)
            # Projection fail-safe : AMI nets attendent 384D, base RAG = 1024D
            if hasattr(_s_emb_raw, "__len__") and len(_s_emb_raw) > 384:
                _s_emb = (_s_emb_raw[:384] / max(float(np.linalg.norm(_s_emb_raw[:384])), 1e-8)).astype("float32")
            else:
                _s_emb = _s_emb_raw
            _goal_emb = _s_emb  # goal = tâche elle-même (pas encore de goal séparé)
            try:
                from nokido_agent.app.forge_mpc import plan_horizon as _plan_horizon

                # plan_horizon → list[(action_seq, cumulative_cost)], sorted asc
                _mpc_seqs = _plan_horizon(
                    state_emb=_s_emb,
                    goal_emb=_goal_emb,
                    goal_text=task,
                    state_text=task,
                    horizon=int(_ami_config.get("horizon", 3)),
                    n_candidates=int(_ami_config.get("actor_N", 5)),
                    use_mcts=True,  # neural path: policy_net+value_net, no LLM
                )
                if _mpc_seqs:
                    _best_seq, _best_cost = _mpc_seqs[0]
                    _mpc_best_action = _best_seq[0] if _best_seq else {}
                logger.info(
                    f"[cognitive-router] mpc_plan seqs={len(_mpc_seqs)} best_cost={_best_cost if _mpc_seqs else 'n/a'}"
                )
            except Exception as _mpc_e:
                # Fallback MCTS
                from nokido_agent.app.forge_actor import mcts_propose as _mcts

                _best_plan, _ = _mcts(_s_emb, _goal_emb, n_simulations=16)
                _mpc_best_action = _best_plan
                logger.debug(f"[cognitive-router] mpc fallback→mcts: {_mpc_e}")
        except Exception as _me:
            logger.debug(f"[cognitive-router] mpc skip: {_me}")

    # ── Pilier 3 : Capability Routing (anticipation) ──────────────────────────
    tools_needed = _anticipate_tools(task)
    system_base = ""
    if tools_needed:
        try:
            system_base = build_proactive_system(task, system_base)
            logger.info(f"[cognitive-router] tools pré-chargés : {tools_needed}")
        except Exception as e:
            logger.debug(f"[cognitive-router] capability error : {e}")

    # ── Pilier 5 : Context Pruning ────────────────────────────────────────────
    tool_for_pruning = tools_needed[0] if tools_needed else ""
    pruned_chunks = prune_rag_context(rag_chunks, intent=intent, tool=tool_for_pruning, k=5)
    rag_ctx = "\n".join(c.get("content", "")[:300] for c in pruned_chunks)

    # ── Pilier 2 : Security-Aware (ring=0 → local forcé) ─────────────────────
    if ring == 0 and backend == "litellm_cloud":
        backend = "ollama"
        logger.warning("[cognitive-router] Ring=0 : cloud refusé → forcé ollama")

    # ── Pilier 4 : Fallback Routing ───────────────────────────────────────────
    if backend == "onnx_local":
        # Tâche simple → réponse rapide sans LLM lourd
        response, used_backend = await _onnx_simple_response(task)
        if not response:
            response, used_backend = await _call_with_fallback(
                task, system_base, rag_ctx, ring=ring, session_id=session_id
            )
    else:
        response, used_backend = await _call_with_fallback(
            task,
            system_base,
            rag_ctx,
            max_tokens=200 if complexity == "simple" else 400,
            ring=ring,
            session_id=session_id,
        )

    entropy = _entropy_score(response)

    logger.info(f"[cognitive-router] done backend={used_backend} chunks={len(pruned_chunks)} entropy={entropy:.2f}")

    return {
        "response": response,
        "backend": used_backend,
        "complexity": complexity,
        "tools_preloaded": tools_needed,
        "chunks_used": len(pruned_chunks),
        "entropy": round(entropy, 3),
        # AMI Configurator fields (Phase 4)
        "task_type": _ami_config.get("task_type", "orchestration"),
        "actor_N": _ami_config.get("actor_N", 3),
        "horizon": _ami_config.get("horizon", 2),
        "cost_lambda": _ami_config.get("cost_lambda", 0.7),
        # AMI Phase 6 — MPC / MCTS best action proposal
        "mpc_best_action": _mpc_best_action,
    }


async def _onnx_simple_response(task: str) -> tuple[str, str]:
    """
    Tente une réponse rapide via le brain ONNX local (Phi-3.5 / MiniLM).
    Fallback silencieux si indisponible.
    """
    try:
        import sys as _s

        brain = _s.modules.get("forge_runtime")
        if brain and hasattr(brain, "brain_generate"):
            resp = await brain.brain_generate(task, max_tokens=150)
            if resp:
                return resp, "onnx_local"
    except Exception:
        pass
    return "", "onnx_local_miss"
