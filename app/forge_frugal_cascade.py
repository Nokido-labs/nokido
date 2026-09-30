"""forge_frugal_cascade.py — Cascade LLM small→large pattern FrugalGPT (Chen et al. 2023).

Source veille 2026-05-29 : FrugalGPT (Stanford) + RouteLLM (LMSYS) + LiteLLM (BerriAI).

Principe : try cheapest model FIRST + confidence gate. Si confidence < threshold,
escalate to bigger model. Economie ~70% tokens vs always-large sans degradation
significative pour 80% des requetes (queries simples/standard).

Tiers (ordre cout croissant, qualite croissante) :
1. local_small  : qwen2.5-coder 7B llama-server :8080 (gratuit, ~5s/42tok CPU)
2. cloud_small  : Cerebras gpt-oss-120b free (~200-500ms, 50k tok/min)
3. cloud_medium : Groq llama-3.3-70b-versatile free (30 req/min)
4. cloud_large  : Mistral large free OR Cerebras zai-glm-4.7

Confidence scoring : (a) self-report LLM "score 0-10 confidence" + (b) heuristique
output coherence (length, format compliance, contradictions).

API : `cascade(prompt, use_case='general')` retourne `{response, model_used, tiers_tried, confidence}`.
"""

from __future__ import annotations
import json, logging, os, re, time, urllib.request, urllib.error
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("frugal_cascade")

ROOT = Path(__file__).resolve().parent.parent


# --- Tiers config ---

TIER_LOCAL_SMALL = {
    "name": "local_qwen_7b",
    "url": f"http://127.0.0.1:{os.environ.get('LAFORGE_LLAMACPP_PORT', '8091')}/v1/chat/completions",
    "model": "qwen2.5-coder-7b",
    "key_env": None,
    "timeout": 30,
    "cost_per_1k": 0.0,
}
TIER_CLOUD_SMALL = {
    "name": "cerebras_gpt_oss_120b",
    "url": "https://api.cerebras.ai/v1/chat/completions",
    "model": "gpt-oss-120b",
    "key_env": "CEREBRAS_API_KEY",
    "timeout": 20,
    "cost_per_1k": 0.0,  # free tier
}
TIER_CLOUD_MEDIUM = {
    "name": "groq_llama_3.3_70b",
    "url": "https://api.groq.com/openai/v1/chat/completions",
    "model": "llama-3.3-70b-versatile",
    "key_env": "GROQ_API_KEY",
    "timeout": 25,
    "cost_per_1k": 0.0,  # free tier 30 req/min
}
TIER_CLOUD_LARGE = {
    "name": "mistral_large",
    "url": "https://api.mistral.ai/v1/chat/completions",
    "model": "mistral-large-latest",
    "key_env": "MISTRAL_API_KEY",
    "timeout": 40,
    "cost_per_1k": 0.0,  # free tier
}

CASCADE_BY_USE_CASE = {
    "general": [TIER_CLOUD_SMALL, TIER_CLOUD_MEDIUM, TIER_CLOUD_LARGE],
    "code": [TIER_LOCAL_SMALL, TIER_CLOUD_SMALL, TIER_CLOUD_MEDIUM],
    "reasoning": [TIER_CLOUD_SMALL, TIER_CLOUD_LARGE],
    "fast": [TIER_LOCAL_SMALL, TIER_CLOUD_SMALL],
}

# Confidence thresholds for ESCALATION (lower = escalate)
CONFIDENCE_THRESHOLD = float(os.environ.get("FRUGAL_CONFIDENCE_THRESHOLD", "0.6"))


def _get_secret(name: str) -> str:
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(name) or os.environ.get(name, "")
    except Exception:
        return os.environ.get(name, "")


def _call_llm(tier: dict, prompt: str, max_tokens: int = 600,
              motifs: dict | None = None) -> str | None:
    """OpenAI-compat call. Returns text or None on failure.

    `motifs` (optionnel, defaut None = comportement inchange pour les appelants
    existants) recoit la RAISON de l'echec, par nom de tier.

    Mesure 2026-08-30 : ce `None` couvrait TROIS causes indiscernables -- aucune
    cle, reponse sans `choices`, et exception reseau/HTTP -- dont la seule trace
    partait en `logger.debug`, donc invisible en production. Consequence concrete :
    les widgets generes de la GUI servaient leur repli et personne ne pouvait dire
    si c'etait un quota, une cle absente ou un 401. Un echec qui ne se nomme pas
    ne se repare pas.
    """
    def _echec(raison: str) -> None:
        if motifs is not None:
            motifs[tier["name"]] = raison
        return None

    key = ""
    if tier.get("key_env"):
        key = _get_secret(tier["key_env"])
        if not key:
            return _echec("aucune cle : %s absent du coffre ET de l'environnement"
                          % tier["key_env"])
    body = json.dumps(
        {
            "model": tier["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
    ).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "LaForge-Frugal"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        req = urllib.request.Request(tier["url"], data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=tier["timeout"]) as r:
            data = json.loads(r.read())
        choices = data.get("choices", [])
        if not choices:
            return _echec("reponse HTTP sans champ choices")
        msg = choices[0].get("message", {})
        # gpt-oss returns "reasoning" sometimes instead of "content"
        texte = (msg.get("content") or msg.get("reasoning") or "").strip() or None
        return texte if texte else _echec("choices present mais contenu vide")
    except Exception as e:
        logger.debug(f"{tier['name']} KO: {e}")
        return _echec("%s: %s" % (type(e).__name__, str(e)[:120]))


def _heuristic_confidence(text: str, prompt: str) -> float:
    """Score 0-1 confidence based on output coherence heuristics.

    Signals :
    - Length appropriate (not truncated, not too short)
    - No "I don't know" / hedging markers
    - JSON format respected if asked
    - Has structure (newlines, bullets if expected)
    """
    if not text:
        return 0.0
    score = 0.5  # start neutral
    n = len(text)

    # Length sanity
    if n < 20:
        score -= 0.3
    elif 50 < n < 4000:
        score += 0.1

    # Hedging markers reduce confidence
    hedges = (
        "i don't know",
        "i'm not sure",
        "cannot determine",
        "unclear",
        "as an ai",
        "i cannot",
        "je ne sais pas",
        "incertain",
    )
    low = text.lower()
    for h in hedges:
        if h in low:
            score -= 0.2
            break

    # JSON requested but not present
    if "json" in prompt.lower() and not (text.strip().startswith("{") or text.strip().startswith("[")):
        score -= 0.2
    # JSON requested and parseable
    if "json" in prompt.lower():
        try:
            json.loads(text.strip())
            score += 0.3
        except Exception:
            pass

    # Has structure
    if "\n" in text or "- " in text or "1. " in text:
        score += 0.1

    return max(0.0, min(1.0, score))


def _ask_self_confidence(tier: dict, prompt: str, response: str) -> float | None:
    """Optional : ask LLM itself for confidence score. Costly, use only at last tier.

    Rend None quand le juge n'a PAS pu noter : juge muet, reponse sans nombre, valeur
    illisible. Ces trois cas rendaient 0.5, c'est-a-dire une note MOYENNE — un echec
    de mesure deguise en mesure, qui se moyennait ensuite dans la confiance retenue et
    DECIDAIT donc de l'escalade. Meme famille que le troisieme etat de la confiance
    d'intuition (cf. tests/nr/test_confiance_troisieme_etat_nr.py).
    """
    judge_prompt = (
        f"Prompt original: {prompt[:500]}\n\n"
        f"Reponse generee: {response[:800]}\n\n"
        "Note la confiance (0.0 to 1.0) que cette reponse repond correctement au prompt. "
        "Format : juste le nombre decimal."
    )
    raw = _call_llm(tier, judge_prompt, max_tokens=20)
    if not raw:
        return None
    m = re.search(r"(\d+\.?\d*)", raw)
    if not m:
        return None
    try:
        return max(0.0, min(1.0, float(m.group(1))))
    except Exception as e:  # noqa: BLE001 — valeur illisible : UNKNOWN, mais NOMME
        logger.info("[frugal] note du juge illisible (%s: %s) sur %r — confiance INCONNUE",
                    type(e).__name__, str(e)[:60], m.group(1)[:20])
        return None


def cascade(
    prompt: str,
    use_case: str = "general",
    max_tokens: int = 600,
    confidence_threshold: float | None = None,
    self_judge_at_last: bool = False,
) -> dict:
    """Execute FrugalGPT-style cascade. Returns dict with response + metadata.

    Args:
        prompt: user prompt
        use_case: 'general' | 'code' | 'reasoning' | 'fast'
        max_tokens: cap per call
        confidence_threshold: escalate if below this (default 0.6)
        self_judge_at_last: if True, ask last successful tier to self-rate (extra call)

    Returns:
        {
            "response": str | None,
            "model_used": str,
            "tiers_tried": list[str],
            "confidence": float,
            "latency_ms": float,
            "escalated": bool,
        }
    """
    threshold = confidence_threshold if confidence_threshold is not None else CONFIDENCE_THRESHOLD
    tiers = CASCADE_BY_USE_CASE.get(use_case, CASCADE_BY_USE_CASE["general"])
    t_start = time.time()
    tried = []
    motifs: dict = {}
    final = {
        "response": None,
        "model_used": None,
        "confidence": 0.0,
        "tiers_tried": [],
        "escalated": False,
        "latency_ms": 0.0,
    }

    # ROUTE GOUVERNEE D'ABORD (2026-08-30, recadrage owner). Ce module joignait les
    # providers par `urllib` sur des URL et des modeles EN DUR, hors du routeur
    # souverain : donc sans rotation de cles, sans circuit breaker, sans RPM -- et
    # surtout SANS REPLI LOCAL, puisque `CASCADE_BY_USE_CASE` n'aligne que du cloud
    # la ou toutes les chaines de `forge_llm_router` se terminent par
    # `lmstudio_native` puis `ollama_local`. Mesure du jour : les trois tiers cloud
    # rendaient 402 / 403 / 404 et la GUI generative etait morte, alors que la
    # machine porte un modele local. Les codes HTTP n'etaient donc pas le defaut :
    # ils etaient le SYMPTOME du contournement. Le routeur rend en prime
    # `attempts: [(slot, error)]`, c'est-a-dire le denominateur ET les raisons.
    try:
        from nokido_agent.app.forge_llm_router import get_router

        r = get_router().call_cascade(prompt, use_case=use_case,
                                      max_tokens=max_tokens, timeout=45)
        essais = r.get("attempts") or []
        final["tiers_tried"] = [str(s) for s, _e in essais] or [r.get("provider") or "?"]
        final["echecs"] = {str(s): str(e)[:120] for s, e in essais if e}
        final["latency_ms"] = round(
            r.get("elapsed_ms") or (time.time() - t_start) * 1000, 1)
        texte = (r.get("text") or "").strip()
        if r.get("ok") and texte:
            final.update({
                "response": texte,
                "model_used": r.get("provider") or r.get("model") or "routeur",
                "confidence": round(_heuristic_confidence(texte, prompt), 3),
                "escalated": len(essais) > 1,
                "route": "routeur souverain",
            })
            return final
        # Le routeur a REPONDU et aucun slot n'a abouti. On ne repasse PAS par les
        # appels directs : ce serait refaire le contournement qu'on retire ici, et
        # le routeur a deja essaye la chaine entiere, repli local compris.
        final["route"] = "routeur souverain : aucun slot n'a repondu"
        return final
    except Exception as e:  # noqa: BLE001 - routeur INDISPONIBLE : repli NOMME
        # Seul cas ou l'ancien chemin sert encore : le routeur ne s'importe pas.
        # Un repli silencieux ferait passer une panne de routeur pour un choix.
        final["route"] = "routeur indisponible (%s: %s) -- repli appels directs" % (
            type(e).__name__, str(e)[:70])
        motifs["_routeur"] = final["route"]
        logger.warning("[frugal] %s", final["route"])

    for i, tier in enumerate(tiers):
        tried.append(tier["name"])
        response = _call_llm(tier, prompt, max_tokens=max_tokens, motifs=motifs)
        if not response:
            continue
        conf = _heuristic_confidence(response, prompt)
        logger.debug(f"tier={tier['name']} conf_heur={conf:.2f}")
        # Last tier : optionally self-judge
        if i == len(tiers) - 1 and self_judge_at_last:
            sj = _ask_self_confidence(tier, prompt, response)
            if sj is None:
                # Le juge n'a pas pu noter. Moyenner une note absente reviendrait a
                # tirer la confiance vers 0.5 sans aucune mesure ; on garde donc
                # l'heuristique seule et on DIT que le second avis manque.
                motifs["_self_judge"] = "juge du dernier tier sans note lisible"
                logger.info("[frugal] self-judge INDISPONIBLE : confiance heuristique seule")
            else:
                conf = (conf + sj) / 2
        if conf >= threshold or i == len(tiers) - 1:
            final.update(
                {
                    "response": response,
                    "model_used": tier["name"],
                    "confidence": round(conf, 3),
                    "escalated": i > 0,
                }
            )
            break
        logger.info(f"escalate from {tier['name']} (conf={conf:.2f} < {threshold})")

    final["tiers_tried"] = tried
    # RAISON de chaque tier qui n'a pas repondu, par nom. Sans elle, un echec
    # complet de cascade se lit « aucun modele n'a repondu » sans jamais dire
    # POURQUOI -- et les trois causes (cle absente, quota, panne reseau) appellent
    # trois remedes differents.
    final["echecs"] = motifs
    final["latency_ms"] = round((time.time() - t_start) * 1000, 1)
    return final


def main():
    """CLI test."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: forge_frugal_cascade.py <prompt> [use_case]")
        return
    prompt = sys.argv[1]
    use_case = sys.argv[2] if len(sys.argv) > 2 else "general"
    result = cascade(prompt, use_case=use_case)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
