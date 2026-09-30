# -*- coding: utf-8 -*-
"""
forge_roles.py — Système de rôles locaux Nokido
=================================================
Chaque rôle est un agent autonome avec :
- Un modèle local dédié (Ollama)
- Une responsabilité unique
- Un Semaphore pour éviter la saturation GPU
- Un circuit breaker intégré
- Une escalade cloud optionnelle

RÔLES DISPONIBLES :
  PLANNER     — Décompose les tâches en sous-items assignables
  EXECUTOR    — Exécute une tâche concrète (code, write, run)
  REVIEWER    — Vérifie AST, qualité, cohérence
  ROUTER      — Décide qui fait quoi (local vs cloud)
  SUMMARIZER  — Résume et indexe les résultats dans le RAG
  SENTINEL    — Vérifie la sécurité avant chaque action sensible
  MONITOR     — Surveille les métriques et alerte

Session 5 — 2026-04-27
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Nokido.Roles")

ROOT = Path(__file__).resolve().parent.parent


def best_cloud_for_role(role_name: str, require_joignable: bool = False) -> Optional[dict]:
    """Pick best cloud provider for a role from forge_provider_specs benchmarks.

    Returns dict with {"provider": str, "model": str} or None if no provider available.
    Stub: returns None by default -- callers must handle missing provider gracefully.
    Wire to real benchmark registry when forge_provider_specs.best_for(role) lands.
    """
    try:
        from nokido_agent.app.forge_provider_specs import best_for  # type: ignore

        return best_for(role_name, require_joignable=require_joignable)
    except Exception:
        return None

# ── Semaphore global — protège le GPU/CPU local ──────────────────────────────
# Max 2 appels LLM locaux simultanés (évite OOM et saturation VRAM)
_LOCAL_SEMAPHORE = asyncio.Semaphore(2)


# ── Circuit Breaker simple ────────────────────────────────────────────────────
class CircuitState(Enum):
    CLOSED = "CLOSED"  # normal
    OPEN = "OPEN"  # en panne — rejette tout
    HALF = "HALF_OPEN"  # test de récupération


@dataclass
class RoleCircuitBreaker:
    role: str
    fail_threshold: int = 3
    recovery_s: float = 30.0
    _failures: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _open_since: float = 0.0

    def allow(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._open_since > self.recovery_s:
                self._state = CircuitState.HALF
                return True
            return False
        return True  # HALF_OPEN : laisser passer un test

    def record_success(self):
        self._failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.fail_threshold:
            self._state = CircuitState.OPEN
            self._open_since = time.monotonic()
            logger.warning(f"[CircuitBreaker] {self.role} OPEN — {self._failures} echecs")

    @property
    def status(self) -> str:
        return self._state.value


# ── Définition des rôles ─────────────────────────────────────────────────────
@dataclass
class Role:
    name: str
    model: str  # modèle Ollama local
    system_prompt: str  # prompt système du rôle
    max_tokens: int = 512
    timeout_s: float = 60.0
    cloud_fallback: Optional[str] = None  # provider cloud si local échoue
    breaker: RoleCircuitBreaker = field(default_factory=lambda: RoleCircuitBreaker("?"))

    def __post_init__(self):
        self.breaker.role = self.name


ROLES: dict[str, Role] = {
    "PLANNER": Role(
        name="PLANNER",
        model="qwen3:8b",
        system_prompt=(
            "Tu es PLANNER, un agent de planification Nokido. "
            "Tu reçois une liste de tâches et tu les décomposes en items atomiques. "
            "Pour chaque item tu retournes un JSON : "
            "{id, title, role_assigné, priorité(HIGH/NORMAL/LOW), "
            "dépendances:[], tool_mcp, args_mcp, escalade_cloud:bool}. "
            "Rôles disponibles : EXECUTOR, REVIEWER, ROUTER, SUMMARIZER, SENTINEL. "
            "Jamais plus de 5 items en parallèle. "
            "Réponds UNIQUEMENT en JSON valide, rien d autre."
        ),
        max_tokens=1024,
        timeout_s=90.0,
        cloud_fallback="github_llama_70b",
    ),
    "EXECUTOR": Role(
        name="EXECUTOR",
        model="qwen2.5-coder:7b-instruct-q4_K_M",
        system_prompt=(
            "Tu es EXECUTOR, un agent d exécution Nokido. "
            "Tu reçois une tâche concrète avec tool_mcp et args. "
            "Tu génères le code minimal pour accomplir la tâche. "
            "Règles : subprocess encoding utf-8, sys.path inject, "
            "jamais lire Nokido.env, toujours auto_test AST après write. "
            "Réponds avec le code Python à exécuter, rien d autre."
        ),
        max_tokens=800,
        timeout_s=60.0,
        cloud_fallback="github_gpt41_mini",
    ),
    "REVIEWER": Role(
        name="REVIEWER",
        model="qwen3:8b",
        system_prompt=(
            "Tu es REVIEWER, un agent de revue Nokido. "
            "Tu reçois du code Python ou une modification. "
            "Tu vérifies : syntaxe AST, patterns forge_known_bugs, "
            "encoding utf-8 subprocess, pas de lecture .env, "
            "imports circulaires, timeout SSE. "
            "Tu retournes : {ok:bool, issues:[str], score:0-100}. "
            "Sois concis. JSON uniquement."
        ),
        max_tokens=400,
        timeout_s=45.0,
        cloud_fallback=None,
    ),
    "ROUTER": Role(
        name="ROUTER",
        model="laforge-qwen:latest",
        system_prompt=(
            "Tu es ROUTER, l agent de routage Nokido. "
            "Tu reçois une tâche et tu décides : "
            "local (quel rôle) ou cloud (quel provider). "
            "Critères local : code, review, plan, sécurité, RAG. "
            "Critères cloud : raisonnement complexe, context > 8K, génération longue. "
            "Retourne : {destination:local|cloud, role:str, provider:str, raison:str}. "
            "JSON uniquement."
        ),
        max_tokens=200,
        timeout_s=20.0,
        cloud_fallback=None,
    ),
    "SUMMARIZER": Role(
        name="SUMMARIZER",
        model="laforge-qwen:latest",
        system_prompt=(
            "Tu es SUMMARIZER, agent de synthèse Nokido. "
            "Tu reçois des résultats de tâches et tu produis : "
            "1. Un résumé 3 phrases max. "
            "2. Les points clés en bullet list. "
            "3. Les actions suivantes recommandées. "
            "Format : markdown concis. "
            "Tu indexes automatiquement dans le RAG."
        ),
        max_tokens=600,
        timeout_s=30.0,
        cloud_fallback=None,
    ),
    "SENTINEL": Role(
        name="SENTINEL",
        model="qwen3:8b",
        system_prompt=(
            "Tu es SENTINEL, l agent de sécurité Nokido. "
            "Avant chaque action sensible (write, run, cloud call), "
            "tu vérifies : secrets dans payload, paths protégés, "
            "ring suffisant, patterns forge_known_bugs. "
            "Tu retournes : {allowed:bool, risk:LOW|MEDIUM|HIGH, raison:str}. "
            "En cas de doute : allowed=false. JSON uniquement."
        ),
        max_tokens=200,
        timeout_s=15.0,
        cloud_fallback=None,
    ),
    "MONITOR": Role(
        name="MONITOR",
        model="laforge-qwen:latest",
        system_prompt=(
            "Tu es MONITOR, agent de surveillance Nokido. "
            "Tu analyses les métriques : latences bridge, network_log, "
            "provider_scores, erreurs récentes. "
            "Tu retournes une alerte si : lat > 5s, erreurs > 3/min, "
            "provider down, zombie process. "
            "Format : {status:OK|WARN|CRIT, alertes:[str], actions:[str]}."
        ),
        max_tokens=300,
        timeout_s=20.0,
        cloud_fallback=None,
    ),
}


# ── Moteur d exécution des rôles ─────────────────────────────────────────────


def _log_usage(
    role: str,
    model: str,
    provider: str,
    elapsed_ms: float,
    ok: bool,
    prompt_len: int = 0,
    completion_len: int = 0,
    source: str = "role",
    escalated: bool = False,
):
    """Enregistre chaque appel modèle dans token_usage SQLite."""
    import sqlite3, uuid, os, json as _j, pathlib as _pl

    try:
        # RACCORDE au recorder canonique (A3, 2026-09-12) :
        # UNIQUE_WRITER(token_usage) = app/forge_token_monitor.log_call.
        # A3 forcait `cost_usd=0.0` pour preserver l'ancien comportement (la
        # colonne prenait son DEFAULT 0). A4 le RETIRE : ce 0 etait precisement
        # le faux zero comptable que le chantier corrige. Ce module ne calcule
        # aucun prix, donc le recorder tranchera -- FREE si le provider est
        # local et prouve gratuit, UNKNOWN_PRICING sinon, avec cost_usd NULL.
        #
        # DETTE SEMANTIQUE SIGNALEE, NON corrigee ici : `prompt_len` et
        # `completion_len` sont des LONGUEURS DE TEXTE, pas des tokens, et
        # atterrissent dans des colonnes de tokens. A qualifier au moment de la
        # provenance (`measurement_kind` ESTIMATED ou UNKNOWN), pas dans un
        # raccordement de plomberie qui doit rester neutre.
        from nokido_agent.app.forge_token_monitor import log_call

        log_call(
            agent_id=f"role_{role.lower()}",
            provider=provider,
            model=model,
            prompt_tokens=prompt_len,
            completion_tokens=completion_len,
            latency_ms=round(elapsed_ms, 1),
            source=source,
            meta={"role": role, "escalated": escalated, "ok": ok},
        )
        logger.debug(f"[usage] {role}/{model} {elapsed_ms:.0f}ms ok={ok}")
    except Exception as e:
        logger.debug(f"[usage] log failed: {e}")


async def call_role(role_name: str, task: str, context: str = "") -> dict:
    """
    Appelle un rôle local via Ollama.
    - Semaphore global : max 2 simultanés
    - Circuit breaker : fail-fast si rôle en panne
    - Fallback cloud si échec local et cloud_fallback défini
    """
    role = ROLES.get(role_name.upper())
    if not role:
        return {"error": f"Rôle inconnu: {role_name}", "ok": False}

    if not role.breaker.allow():
        return {"error": f"[CircuitBreaker] {role_name} OPEN", "ok": False, "circuit": "OPEN"}

    prompt = f"{context}\n\n{task}" if context else task

    async with _LOCAL_SEMAPHORE:
        t0 = time.monotonic()
        try:
            import urllib.request

            payload = json.dumps(
                {
                    "model": role.model,
                    "messages": [
                        {"role": "system", "content": role.system_prompt},
                        {"role": "user", "content": prompt[:4000]},
                    ],
                    "stream": False,
                    "options": {"num_predict": role.max_tokens},
                }
            ).encode()

            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=role.timeout_s) as r:
                data = json.loads(r.read())
            text = data.get("message", {}).get("content", "").strip()
            elapsed = round((time.monotonic() - t0) * 1000, 1)

            role.breaker.record_success()
            logger.info(f"[{role_name}] OK {elapsed}ms model={role.model}")
            _log_usage(
                role_name, role.model, "ollama", elapsed, ok=True, prompt_len=len(prompt), completion_len=len(text)
            )
            return {"ok": True, "text": text, "role": role_name, "model": role.model, "elapsed_ms": elapsed}

        except Exception as e:
            role.breaker.record_failure()
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            logger.warning(f"[{role_name}] FAIL {elapsed}ms: {e}")
            _log_usage(role_name, role.model, "ollama", elapsed, ok=False)

            # Escalade cloud si définie
            if role.cloud_fallback:
                return await _cloud_fallback(role, prompt, str(e))

            return {"ok": False, "error": str(e)[:100], "role": role_name, "elapsed_ms": elapsed}


async def _cloud_fallback(role: Role, prompt: str, local_error: str) -> dict:
    """Escalade vers meilleur provider cloud (benchmarks réels) + log token_usage."""
    import time as _tc, urllib.request as _ur, os as _os

    _t0 = _tc.monotonic()

    best = best_cloud_for_role(role.name, require_joignable=True)
    _provider_map = {
        "groq": "groq_fast",
        "github_models": "github_gpt41_mini",
        "mistral": "mistral_small",
        "openrouter": "openrouter_gpt_oss",
    }

    if best:
        provider_key = _provider_map.get(best["provider"], role.cloud_fallback)
        model_name = best["model"]
        provider_name = best["provider"]
        logger.info(f"[{role.name}] Escalade → {provider_name}/{model_name} TTFT={best['ttft_ms']}ms")
    else:
        provider_key = role.cloud_fallback or "groq_fast"
        model_name = provider_key
        provider_name = "cloud"
        logger.info(f"[{role.name}] Escalade cloud → {provider_key} (fallback générique)")

    try:
        token = _os.environ.get("FORGE_MCP_TOKEN", "")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "ask",
                    "arguments": {
                        "provider": provider_key,
                        "message": f"[SYSTEM: {role.system_prompt[:200]}]\n\n{prompt[:3000]}",
                        "max_tokens": role.max_tokens,
                    },
                },
            }
        ).encode()
        req = _ur.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Agent-Name": "CLAUDE"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        result = json.loads(data.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        _ok = result.get("ok", False)
        _elapsed = round((_tc.monotonic() - _t0) * 1000, 1)
        _log_usage(role.name, model_name, provider_name, _elapsed, ok=_ok, escalated=True, source="role_cloud")
        return {
            "ok": _ok,
            "text": result.get("text", ""),
            "role": role.name,
            "model": model_name,
            "provider": provider_name,
            "escalated": True,
            "local_error": local_error,
        }
    except Exception as e:
        _elapsed = round((_tc.monotonic() - _t0) * 1000, 1)
        _log_usage(role.name, model_name, provider_name, _elapsed, ok=False, escalated=True, source="role_cloud")
        return {"ok": False, "error": f"cloud fallback failed: {e}", "role": role.name}


async def call_role_cloud(role_name: str, task: str, context: str = "") -> dict:
    """
    Appelle directement le meilleur provider cloud pour ce rôle.
    Utilisé quand le local échoue ou quand cloud_fallback est décidé par ROUTER.
    """
    best = best_cloud_for_role(role_name)
    if not best:
        return {"ok": False, "error": f"Aucun provider cloud pour {role_name}"}

    role = ROLES.get(role_name.upper())
    system = role.system_prompt if role else f"Tu es {role_name} agent Nokido."
    prompt = f"{context}\n\n{task}" if context else task

    import urllib.request, os as _os

    token = _os.environ.get("FORGE_MCP_TOKEN", "")
    # Mapper provider → nom forge_llm_router
    provider_map = {
        "groq": "groq_fast",
        "github_models": "github_gpt41_mini",
        "mistral": "mistral_small",
        "openrouter": "openrouter_gpt_oss",
    }
    provider_key = provider_map.get(best["provider"], best["provider"])

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider_key,
                    "message": f"[SYSTEM: {system[:200]}]\n\n{prompt[:3000]}",
                    "max_tokens": best["max_tokens"],
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8766/mcp",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Agent-Name": "CLAUDE"},
        method="POST",
    )
    try:
        import asyncio as _a

        loop = _a.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: __import__("urllib.request").request.urlopen(req, timeout=30).read()
        )
        data = json.loads(resp)
        result = json.loads(data.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        return {
            "ok": result.get("ok", False),
            "text": result.get("text", ""),
            "role": role_name,
            "cloud_role": best["cloud_role"],
            "model": best["model"],
            "provider": best["provider"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "role": role_name}
