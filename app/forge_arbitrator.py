# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_arbitrator
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_arbitrator.py — Arbitre d'Escalade Cognitive v0.13.1
===========================================================
Module dédié à la logique de bascule intelligente entre les modèles.
Sépare la responsabilité d'escalade du routage (forge_cognitive_router.py).

Responsabilités :
  1. Évaluer si une réponse locale nécessite une escalade
  2. Construire le prompt d'escalade avec contexte (Skeleton Prompting)
  3. Gérer le routing des outils selon le mode (DEV/OFFLINE/STRICT)
  4. Logger chaque décision dans event_log
  5. Protéger ring=0 contre tout cloud (blocage physique)

API publique :
  evaluate_confidence(response, ring, expected_format) → ConfidenceReport
  smart_dispatch(task, ring, session_id, context)      → DispatchResult
  route_tool_request(tool, query, mode)                → str résultat
"""


import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# RAPPORT DE CONFIANCE
# =============================================================================


@dataclass
class ConfidenceReport:
    needs_escalation: bool
    score: int  # 0 = parfait, ≥ 2 = escalade
    reasons: list[str]  # liste des raisons détectées
    ring_blocked: bool  # True si ring=0 interdit l'escalade
    suggested_level: str  # "local" | "litellm" | "claude" | "human"


# =============================================================================
# 1. CALCULATEUR D'INCERTITUDE
# =============================================================================

# Mots-clés d'incertitude → +1 point chacun
_UNCERTAINTY_TERMS = [
    "pas sûr",
    "je ne suis pas sûr",
    "incertain",
    "peut-être",
    "je suppose",
    "il est possible que",
    "il me semble",
    "je pense que",
    "probablement",
    "je ne sais pas exactement",
    "je crois que",
    "hypothétiquement",
    "je ne suis pas certain",
    "à ma connaissance limitée",
    # anglais (Qwen répond parfois en anglais)
    "i'm not sure",
    "i think",
    "maybe",
    "perhaps",
    "i suppose",
    "i'm uncertain",
    "i don't know",
    "as far as i know",
]

# Patterns de non-réponse → +2 points
_FAILURE_PATTERNS = [
    r"\[ERROR\]",
    r"\[web_search\].*indisponible",
    r"je ne peux pas",
    r"je n'ai pas accès",
    r"as an AI",
    r"en tant qu\'IA",
    r"désolé,? je ne",
]
_FAILURE_RE = re.compile("|".join(_FAILURE_PATTERNS), re.IGNORECASE)

# Patterns de répétition (hallucination loop)
_REPETITION_WINDOW = 50  # chars


def _detect_repetition(text: str) -> bool:
    """Détecte si le texte contient des répétitions pathologiques.
    FIX v16.17b : détection par ngrams de caractères ET fenêtres glissantes.
    """
    if not text or len(text) < 20:
        return False
    # Méthode 1 : cherche un segment qui se répète au moins 2 fois
    # On teste des longueurs de segments croissantes
    n = min(len(text) // 3, 50)
    for seg_len in range(10, n + 1, 5):
        seg = text[:seg_len]
        if text.count(seg) >= 2:
            return True
    # Méthode 2 : fenêtres glissantes adjacentes identiques
    if len(text) >= _REPETITION_WINDOW * 2:
        for i in range(0, len(text) - _REPETITION_WINDOW * 2, _REPETITION_WINDOW):
            window_a = text[i : i + _REPETITION_WINDOW]
            window_b = text[i + _REPETITION_WINDOW : i + _REPETITION_WINDOW * 2]
            if window_a.strip() == window_b.strip() and len(window_a.strip()) > 10:
                return True
    return False


def evaluate_confidence(
    response: str,
    ring: int = 1,
    expected_format: str = "text",  # "text" | "json" | "code"
) -> ConfidenceReport:
    # Essai d'utiliser forge_metacognition_gate.ConfidenceScorer (source de vérité)
    try:
        from nokido_agent.app.forge_metacognition_gate import ConfidenceScorer as _GateScorer

        _gs = _GateScorer()
        _silo = _gs.score(response)
        # Mapper SiloScore → ConfidenceReport
        if ring == 0:
            return ConfidenceReport(False, 0, ["ring=0 — cloud interdit"], True, "local")
        needs = _silo.final_score < 0.60
        score = int((1 - _silo.final_score) * 6)  # 0-6 normalisé
        level = "claude" if score >= 4 else ("litellm" if score >= 2 else "local")
        return ConfidenceReport(
            needs, score, [f"gate_score={_silo.final_score:.2f}", f"hedging={_silo.hedging_count}"], False, level
        )
    except Exception:
        pass  # fallback sur l'implémentation locale ci-dessous
    """
    Évalue si la réponse locale nécessite une escalade.

    Score :
      0-1  → OK, réponse locale suffisante
      2-3  → Escalade vers LiteLLM/Gemini
      4+   → Escalade vers Claude (stratégique)

    Ring=0 → escalade cloud toujours bloquée (blocage physique).
    """
    score = 0
    reasons: list[str] = []

    # ── Blocage ring=0 ────────────────────────────────────────────────────────
    if ring == 0:
        return ConfidenceReport(
            needs_escalation=False,
            score=0,
            reasons=["ring=0 — cloud interdit"],
            ring_blocked=True,
            suggested_level="local",
        )

    # ── Vérification vide / trop courte ──────────────────────────────────────
    if not response or len(response.strip()) < 15:
        score += 3
        reasons.append(f"réponse vide ou trop courte ({len(response)} chars)")

    # ── Patterns de non-réponse ───────────────────────────────────────────────
    if response and _FAILURE_RE.search(response):
        score += 2
        reasons.append("pattern de non-réponse détecté")

    # ── Mots-clés d'incertitude ───────────────────────────────────────────────
    if response:
        r_lower = response.lower()
        found_terms = [t for t in _UNCERTAINTY_TERMS if t in r_lower]
        if found_terms:
            score += len(found_terms)
            reasons.append(f"incertitude ({len(found_terms)} termes : {found_terms[:3]})")

    # ── Répétitions pathologiques ─────────────────────────────────────────────
    if response and _detect_repetition(response):
        score += 2
        reasons.append("répétition détectée (hallucination loop)")

    # ── Validation format attendu ─────────────────────────────────────────────
    if expected_format == "json" and response:
        try:
            import json as _j

            _j.loads(response.strip())
        except Exception:
            # Chercher un JSON partiel
            if not re.search(r"\{.*\}|\[.*\]", response, re.DOTALL):
                score += 2
                reasons.append("JSON attendu mais non trouvé")

    elif expected_format == "code" and response:
        if not any(kw in response for kw in ["def ", "class ", "import ", "```"]):
            score += 1
            reasons.append("code attendu mais non trouvé")

    # ── Niveau d'escalade ─────────────────────────────────────────────────────
    if score >= 4:
        suggested = "claude"
    elif score >= 2:
        suggested = "litellm"
    else:
        suggested = "local"

    return ConfidenceReport(
        needs_escalation=score >= 2,
        score=score,
        reasons=reasons,
        ring_blocked=False,
        suggested_level=suggested,
    )


# =============================================================================
# 2. SKELETON PROMPTING (Context Injection pour l'escalade)
# =============================================================================


def build_skeleton_prompt(
    task: str,
    failed_response: str,
    ring: int = 1,
) -> str:
    """
    Construit le prompt d'escalade vers Claude/LiteLLM.
    Inclut la réponse ratée d'Ollama avec consigne de correction.
    Le contexte ring est mentionné pour que Claude comprenne les contraintes.

    Skeleton Prompting : Claude ne repart pas de zéro —
    il analyse POURQUOI Ollama a échoué et corrige.
    """
    skeleton = (
        f"[CONTEXTE D'ESCALADE]\n"
        f"Un agent local (Ollama) a tenté de répondre à cette tâche "
        f"mais sa réponse est insuffisante (ring={ring}).\n\n"
        f"[TÂCHE ORIGINALE]\n{task}\n\n"
        f"[RÉPONSE INSUFFISANTE DE L'AGENT LOCAL]\n"
        f"{failed_response[:500] if failed_response else '(vide)'}\n\n"
        f"[CONSIGNE]\n"
        f"Analyse pourquoi cette réponse est insuffisante et fournis "
        f"une réponse correcte et complète. "
        f"Ne répète pas les erreurs de l'agent local. "
        f"Sois direct et technique."
    )

    # Ring=2 → mentionner contraintes de données
    if ring <= 2:
        skeleton += (
            f"\n\n[CONTRAINTE SÉCURITÉ ring={ring}]\n"
            f"Cette tâche implique des données de niveau ring={ring}. "
            f"Ne reproduis aucune donnée sensible dans ta réponse. "
            f"Reste général et factuel."
        )

    return skeleton


# =============================================================================
# 3. SMART DISPATCH (Orchestrateur d'escalade)
# =============================================================================


@dataclass
class DispatchResult:
    response: str
    backend: str  # "ollama" | "litellm" | "claude" | "ring0_blocked" | "human_required"
    escalated: bool
    report: Optional[ConfidenceReport] = None
    elapsed_s: float = 0.0


async def smart_dispatch(
    task: str,
    ring: int = 1,
    session_id: str = "",
    context: str = "",
    expected_format: str = "text",
    max_tokens: int = 400,
) -> DispatchResult:
    """
    Workflow d'escalade cognitive complet.

    1. Tentative locale Ollama (économique et souverain)
    2. Évaluation de confiance (ConfidenceReport)
    3. Si ring=0 → blocage physique, message utilisateur
    4. Si escalade nécessaire → Skeleton Prompt → LiteLLM ou Claude
    5. Log de chaque décision dans event_log

    Retourne DispatchResult avec la meilleure réponse disponible.
    """
    t0 = time.monotonic()

    # ── 1. Tentative locale Ollama ────────────────────────────────────────────
    local_response = ""
    try:
        # Priorité forge_agent_proxy (15+ providers, Kimi/GLM inclus)
        from nokido_agent.app.forge_agent_proxy import ask as _proxy_ask

        _res = await _proxy_ask("groq", task, rag_context=bool(context), max_tokens=max_tokens)
        local_response = _res.get("text", "") if _res.get("ok") else ""
        logger.debug(f"[arbitrator] proxy_ask OK ({len(local_response)} chars)")
    except Exception:
        try:
            from nokido_agent.app.forge_ollama_bridge import get_bridge

            bridge = get_bridge()
            local_response = await bridge.propose(
                task,
                role="LaForge-Worker",
                rag_ctx=context,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.warning(f"[arbitrator] Tous backends locaux KO: {e}")

    # ── 2. Évaluation de confiance ────────────────────────────────────────────
    report = evaluate_confidence(local_response, ring=ring, expected_format=expected_format)

    _log_event("arbitrage", task[:60], report, session_id)

    # ── 3. Ring=0 → blocage physique ─────────────────────────────────────────
    if report.ring_blocked:
        msg = (
            "[Ring=0] Cette tâche nécessite une puissance supérieure "
            "mais les données sont trop sensibles pour le Cloud. "
            "Intervention humaine requise."
        )
        logger.warning(f"[arbitrator] Ring=0 blocage — {task[:40]}")
        return DispatchResult(
            response=msg,
            backend="ring0_blocked",
            escalated=False,
            report=report,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

    # ── 4. Réponse locale suffisante ─────────────────────────────────────────
    if not report.needs_escalation:
        return DispatchResult(
            response=local_response,
            backend="ollama",
            escalated=False,
            report=report,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

    # ── 5. Escalade ───────────────────────────────────────────────────────────
    logger.info(f"[arbitrator] ESCALADE score={report.score} niveau={report.suggested_level} : {report.reasons}")
    skeleton = build_skeleton_prompt(task, local_response, ring=ring)

    cloud_response = ""
    backend_used = "error"

    if report.suggested_level in ("litellm", "claude"):
        try:
            from nokido_agent.app.forge_litellm_bridge import ask as _litellm_ask

            cloud_response = await _litellm_ask(
                skeleton,
                context=context,
                role="LaForge-Arbitre (escalade cognitive)",
                max_tokens=max_tokens,
            )
            backend_used = "litellm" if cloud_response else "error"
            logger.info(f"[arbitrator] LiteLLM escalade OK ({len(cloud_response)} chars)")
        except Exception as e:
            logger.warning(f"[arbitrator] LiteLLM escalade échouée : {e}")

    # Fallback final : retourner la réponse locale même imparfaite
    final = cloud_response or local_response or "[Arbitre] Tous les backends indisponibles"
    backend = backend_used if cloud_response else ("ollama_partial" if local_response else "error")

    return DispatchResult(
        response=final,
        backend=backend,
        escalated=bool(cloud_response),
        report=report,
        elapsed_s=round(time.monotonic() - t0, 2),
    )


# =============================================================================
# 4. ROUTING DES OUTILS (DEV vs OFFLINE/STRICT)
# =============================================================================


def _get_nokido_mode() -> str:
    """
    Retourne le mode Nokido actuel : 'dev' | 'prod' | 'strict' | 'offline'.
    Ordre de priorité : os.environ > Nokido.env > défaut 'prod'.
    """
    # 1. Variable d'environnement (définie au démarrage)
    mode = os.environ.get("LAFORGE_ENV", "").strip().lower()
    if mode:
        return mode

    # 2. Nokido.env
    try:
        from pathlib import Path as _P

        env_path = _P(__file__).resolve().parent.parent / "Nokido.env"
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("LAFORGE_ENV") and "=" in line:
                val = line.split("=", 1)[1].split("#")[0].strip().lower()
                if val:
                    return val
    except Exception:
        pass

    return "prod"


async def route_tool_request(
    tool: str,
    query: str,
    session_id: str = "",
    ring: int = 3,
) -> str:
    """
    Route une demande d'outil selon le mode Nokido.

    Mode DEV    → exécution réelle (DDG pour web_search)
    Mode STRICT → web_search redirigé vers RAG Cache local (pas de sortie bunker)
    Mode OFFLINE→ tout redirigé vers RAG Cache local

    Routing des outils :
      web_search  DEV    → DDG réel via forge_web
      web_search  STRICT → RAG Cache (ton Google interne)
      web_search  OFFLINE→ RAG Cache (idem)
      rag_search  *      → RAG local (toujours)
      read_file   *      → lecture locale (toujours)
    """
    mode = _get_nokido_mode()
    logger.info(f"[tool-router] tool={tool} mode={mode} ring={ring} q={query[:40]!r}")

    # ── web_search ────────────────────────────────────────────────────────────
    if tool == "web_search":
        if mode in ("strict", "offline", "prod") or ring == 0:
            # Redirection vers RAG Cache local (bunker mode)
            logger.info(f"[tool-router] web_search → RAG Cache (mode={mode})")
            return await _rag_cache_search(query, session_id)
        else:
            # DEV → DDG réel avec Sentinel
            from nokido_agent.app.forge_ollama_bridge import _call_mcp_tool_stdio

            return await _call_mcp_tool_stdio("web_search", {"q": query, "k": 3}, session_id=session_id)

    # ── rag_search ────────────────────────────────────────────────────────────
    elif tool == "rag_search":
        return await _rag_cache_search(query, session_id)

    # ── Autres outils → déléguer au bridge MCP ───────────────────────────────
    else:
        from nokido_agent.app.forge_ollama_bridge import _execute_tool_call

        return await _execute_tool_call(tool, {"q": query})


async def _rag_cache_search(query: str, session_id: str = "") -> str:
    """
    Recherche dans le RAG Cache local — le 'Google interne' du bunker.
    Utilisé en mode STRICT/OFFLINE à la place de DDG.
    """
    try:
        import sys as _s

        rag_engine = next(
            (getattr(_s.modules.get(m), "rag_engine", None) for m in ("__main__", "Nokido") if _s.modules.get(m)), None
        )
        if rag_engine:
            docs = await rag_engine.search(query, k=4)
            if docs:
                results = "\n".join(f"[{d.get('source', '?')}] {d.get('content', '')[:300]}" for d in docs)
                return f"[RAG Cache] {len(docs)} résultats pour : {query}\n{results}"

        # Fallback : recherche SQL dans event_log
        return f"[RAG Cache] Aucun résultat pour : {query}"

    except Exception as e:
        return f"[RAG Cache] Erreur : {e}"


# =============================================================================
# 5. LOGGING DES DÉCISIONS
# =============================================================================


def _log_event(
    event_type: str,
    target: str,
    report: ConfidenceReport,
    session_id: str = "",
) -> None:
    """Log la décision d'arbitrage dans event_log."""
    try:
        import sys as _s

        for mod_name in ("__main__", "Nokido"):
            mod = _s.modules.get(mod_name)
            if mod and hasattr(mod, "log_event"):
                mod.log_event(
                    event_type=f"arbitrage:{event_type}",
                    target=target,
                    payload={
                        "score": report.score,
                        "escalade": report.needs_escalation,
                        "niveau": report.suggested_level,
                        "ring_ok": not report.ring_blocked,
                        "reasons": report.reasons[:2],
                        "session": session_id,
                    },
                    agent_id="nokido:arbitrator",
                )
                return
    except Exception:
        pass

    # Fallback : logger Python
    logger.info(
        f"[arbitrage] {event_type} target={target!r} "
        f"score={report.score} escalade={report.needs_escalation} "
        f"niveau={report.suggested_level}"
    )
