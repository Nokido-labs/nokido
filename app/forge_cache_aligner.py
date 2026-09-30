# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_cache_aligner_1

forge_cache_aligner.py — Stabilisation de PRÉFIXE pour HIT le prompt/KV cache des
providers (OpenAI-compat via litellm : groq/cerebras/mistral/openrouter/github =
prefix-cache AUTOMATIQUE ; le hit ne dépend QUE de la stabilité byte-à-byte du
préfixe). Inspiré du « CacheAligner » de Headroom (chopratejas/headroom).

POURQUOI UN MODULE NEUF (anti-dup, Règle d'Or #2) :
  - `forge_handoff_compress` COMPRESSE (réduit la taille). Orthogonal : ici on ne
    réduit RIEN, on rend le préfixe IDENTIQUE tour-à-tour.
  - `forge_sovereign_membrane` fait des alias HMAC stables (sécurité), pas du
    cache-alignment.
  - `forge_semantic_firewall` redige (PII), pas la stabilité de préfixe.
  - `forge_prompt_cache` pose les BREAKPOINTS cache_control (OÙ couper) + keepalive +
    accounting. Il NE stabilise PAS le CONTENU : un timestamp/uuid DANS le bloc caché
    casse le hit malgré le cache_control. STRICTEMENT COMPLÉMENTAIRE — on s'enchaîne :
    align() [stabilise le contenu] -> build_cached_system() [pose le breakpoint].
    Responsabilités disjointes (single-responsibility), pas de recouvrement.
  Neuf justifié (responsabilité = stabilité de contenu, absente partout ailleurs).

PRINCIPE : un cache provider matche le plus long PRÉFIXE de tokens commun aux
appels. Un seul token volatil DANS le préfixe (timestamp, uuid, trace_id, date du
jour) casse le match → 0 hit → tout re-facturé plein tarif (ta douleur « historique
re-facturé ×N »). Solution : EXTRAIRE ces tokens du préfixe et les RELÉGUER en queue
(dernier message). Info préservée, préfixe stable.

UTILISATION (à brancher au waist egress — idéalement SemanticFirewall.pre_flight,
sinon chaque adaptateur : forge_llm_router, forge_agent_proxy, openai_proxy, ...) :
    from forge_cache_aligner import align, align_messages, cache_usage
    system, prompt, rep = align(system, prompt)            # forme (system, prompt)
    messages, rep       = align_messages(messages)         # forme liste OpenAI
    stats = cache_usage(litellm_response)                  # mesure cached_tokens
"""
from __future__ import annotations

import hashlib
import os
import re

# Patterns volatils — HAUTE PRÉCISION (ne mordre QUE sur du connu-volatil pour ne
# jamais altérer du contenu sémantique stable ; un token stable retiré = préfixe
# changé pour rien). Compilés une fois.
_VOLATILE = [
    # datetime ISO (avec composante heure) — quasi toujours volatil
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?"),
    # UUID v4-like
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    # identifiants de corrélation explicitement étiquetés
    re.compile(r"\b(?:trace_id|session_id|run_id|request_id|correlation_id|jti|message_id)\s*[=:]\s*\S+", re.I),
    # phrases de date courante injectées par les harness ("Today's date is ...", "Current date: ...")
    re.compile(r"(?:Today'?s date is|Current date(?: is)?:?|Aujourd'hui(?: nous sommes)?|Date du jour\s*:?)\s*[^\n.]+", re.I),
]

_PLACEHOLDER = "·"  # caractère unique stable (longueur ~constante, neutre)


def _enabled() -> bool:
    return os.environ.get("FORGE_CACHE_ALIGN", "1") not in ("0", "false", "no", "")


def stabilize(text: str):
    """Retire les tokens volatils. Retourne (texte_stable, [tokens_retirés] ordre conservé)."""
    if not text:
        return text, []
    removed: list[str] = []
    out = text
    for rx in _VOLATILE:
        def _sub(m):
            removed.append(m.group(0))
            return _PLACEHOLDER
        out = rx.sub(_sub, out)
    return out, removed


def prefix_hash(text: str) -> str:
    """Empreinte courte du préfixe stabilisé (télémétrie hit-rate sans stocker le texte)."""
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


def _relocate(removed: list[str]) -> str:
    """Bloc de queue qui ré-injecte le volatil HORS du préfixe cacheable (info préservée)."""
    uniq = list(dict.fromkeys(removed))  # dédup, ordre stable
    return f"\n\n[contexte volatil (hors-cache): {' | '.join(uniq)}]" if uniq else ""


def align(system: str, prompt: str):
    """Forme (system, prompt). Stabilise le préfixe `system`, relègue le volatil en
    queue de `prompt`. Idempotent. No-op si désactivé. Retourne (system, prompt, report)."""
    if not _enabled():
        return system, prompt, {"aligned": False}
    sys_stable, removed = stabilize(system or "")
    prompt_aug = (prompt or "") + _relocate(removed)
    return sys_stable, prompt_aug, {
        "aligned": True,
        "removed": len(removed),
        "prefix_hash": prefix_hash(sys_stable),
        "prefix_chars": len(sys_stable),
    }


def align_messages(messages):
    """Forme liste OpenAI [{role,content},...]. Stabilise TOUT sauf le dernier message
    (le préfixe = tout ce qui précède la requête courante), relègue le volatil en queue
    du dernier message. Ne touche pas le contenu non-str (tool calls, images). Idempotent."""
    if not _enabled() or not messages:
        return messages, {"aligned": False}
    msgs = [dict(m) for m in messages]  # copie superficielle
    removed_all: list[str] = []
    for m in msgs[:-1]:
        c = m.get("content")
        if isinstance(c, str):
            m["content"], rem = stabilize(c)
            removed_all.extend(rem)
    last = msgs[-1]
    if removed_all and isinstance(last.get("content"), str):
        last["content"] = last["content"] + _relocate(removed_all)
    prefix = "".join(m.get("content", "") for m in msgs[:-1] if isinstance(m.get("content"), str))
    return msgs, {
        "aligned": True,
        "removed": len(removed_all),
        "prefix_hash": prefix_hash(prefix),
        "prefix_chars": len(prefix),
    }


def cache_usage(response) -> dict:
    """Extrait les tokens servis depuis le cache provider (best-effort, litellm/openai).
    OpenAI/groq/… exposent usage.prompt_tokens_details.cached_tokens. Retourne {} si absent."""
    try:
        u = getattr(response, "usage", None)
        if u is None and isinstance(response, dict):
            u = response.get("usage")
        if not u:
            return {}
        uget = (lambda k: u.get(k)) if isinstance(u, dict) else (lambda k: getattr(u, k, None))
        details = uget("prompt_tokens_details") or {}
        dget = (lambda k: details.get(k)) if isinstance(details, dict) else (lambda k: getattr(details, k, None))
        cached = dget("cached_tokens")
        prompt_toks = uget("prompt_tokens")
        out: dict = {}
        if cached is not None:
            out["cached_tokens"] = cached
        if prompt_toks:
            out["prompt_tokens"] = prompt_toks
            if cached:
                out["cache_hit_pct"] = round(100 * cached / prompt_toks, 1)
        return out
    except Exception:
        return {}


if __name__ == "__main__":
    # Self-test rapide (offline) : préfixe stable malgré timestamp/uuid changeants.
    s1 = "You are Nokido. Today's date is 2026-06-02T11:48:12. trace_id=abc123. Be terse."
    s2 = "You are Nokido. Today's date is 2026-06-03T09:00:00. trace_id=def456. Be terse."
    a1 = align(s1, "ping")
    a2 = align(s2, "ping")
    assert a1[2]["prefix_hash"] == a2[2]["prefix_hash"], "préfixe doit être identique après stabilisation"
    assert "2026-06-02" in a1[1] and "abc123" in a1[1], "volatil doit être préservé en queue"
    m, rep = align_messages([
        {"role": "system", "content": "sys 2026-06-02T00:00:00Z stable"},
        {"role": "user", "content": "question"},
    ])
    assert rep["removed"] == 1 and "2026-06-02" in m[-1]["content"]
    print("forge_cache_aligner self-test OK:", a1[2], "| msgs:", rep)
