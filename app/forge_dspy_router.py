"""app/forge_dspy_router.py - DSPy Signatures pour rendus structures.

Gouvernance Marcus : interdire le debat texte libre entre LLMs. Tout
echange passe par un schema strict (Signature dspy -> JSON parsable).

Usage strategist : remplace `hub_ask(provider, raw_prompt)` par
`signature_call(signature_cls, **inputs, provider, hub_token)`. Le rendu
est garanti JSON-shaped (ou rejet par dspy si parse fail).

Signatures fournies :
  - CodePatchProposal : (file_path, goal, context) -> {code, rationale,
    risk_level, affected_symbols}
  - StrategyHypothesis : (problem, constraints) -> {hypothesis, evidence,
    counter_evidence, confidence_self}

L appel cloud passe par le hub Nokido (`ask` tool) - pas d acces direct
API key. dspy ici sert UNIQUEMENT a forcer le schema, pas a faire la
selection du provider (le routing reste hub).
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

# Meme garde que forge_litellm_bridge / forge_llm_router : dspy tire litellm, qui charge tiktoken A L'IMPORT et ne
# respecte que CUSTOM_TIKTOKEN_CACHE_DIR. Sans lui, un import hors ligne meurt en ConnectionError (mesure 2026-10-12).
_CACHE_TIKTOKEN = Path(__file__).resolve().parent.parent / "sandbox" / "tiktoken_cache"
if _CACHE_TIKTOKEN.is_dir():
    os.environ.setdefault("CUSTOM_TIKTOKEN_CACHE_DIR", str(_CACHE_TIKTOKEN))

try:
    import dspy  # noqa: F401

    _DSPY_OK = True
except Exception:  # ImportError, mais aussi l'echec reseau de tiktoken a l'import : dspy absent, jamais fatal
    _DSPY_OK = False
    dspy = None  # type: ignore

if _DSPY_OK and hasattr(dspy, "configure_cache"):
    # GHSA-w8v5-vhqr-4h9v : diskcache (<= 5.6.3, AUCUNE version corrigee publiee) depique ce qu'il trouve dans son
    # dossier, et dspy ouvre par defaut un tel cache DISQUE (~/.dspy_cache). Ce module ne se sert de dspy que pour ses
    # Signatures -- l'appel LLM passe par le hub, jamais par dspy.LM -- donc ce cache n'a aucun usage ici : on le
    # coupe, et le seul chemin vulnerable du paquet disparait. Registre : docs/cve_sans_correctif.md.
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=True)

HUB_URL = "http://127.0.0.1:8766/mcp"


# === Signatures ===============================================================

if _DSPY_OK:

    class CodePatchProposal(dspy.Signature):  # type: ignore[misc]
        """Propose un patch Python pour atteindre l objectif. Le rendu
        DOIT etre un JSON valide avec les champs imposes."""

        goal: str = dspy.InputField(desc="Objectif technique a atteindre")
        file_context: str = dspy.InputField(desc="Contexte du fichier cible (cap 3500b)")
        constraints: str = dspy.InputField(desc="Contraintes a respecter (liste)")
        code: str = dspy.OutputField(desc="Bloc Python du patch (sans fence)")
        rationale: str = dspy.OutputField(desc="Pourquoi cette approche (<=200 chars)")
        risk_level: str = dspy.OutputField(desc="low | medium | high")
        affected_symbols: str = dspy.OutputField(desc="Symboles touches, csv (def f, class X)")

    class StrategyHypothesis(dspy.Signature):  # type: ignore[misc]
        """Genere une hypothese de strategie + evidence pour et contre.
        Rendu JSON strict, pas de prose libre."""

        problem: str = dspy.InputField(desc="Probleme a resoudre")
        constraints: str = dspy.InputField(desc="Contraintes systeme")
        hypothesis: str = dspy.OutputField(desc="Strategie proposee, <=300 chars")
        evidence: str = dspy.OutputField(desc="Arguments POUR cette hypothese")
        counter_evidence: str = dspy.OutputField(desc="Arguments CONTRE / risques")
        confidence_self: float = dspy.OutputField(desc="Auto-eval 0.0 a 1.0")


# === Hub-backed call avec rendu JSON strict ===================================


def signature_call(
    signature_name: str, inputs: dict, provider: str, hub_token: str, max_tokens: int = 4096, timeout_s: int = 120
) -> dict:
    """Appel cloud avec contrainte de rendu JSON correspondant a la Signature.

    On envoie au LLM un prompt construit manuellement (le hub ask ne supporte
    pas encore dspy.LM nativement) qui demande la sortie JSON conforme aux
    OutputField de la Signature. On parse strictement -> rejet si non-JSON.

    Returns dict {ok, fields, raw, error}.
    """
    if not _DSPY_OK:
        return {"ok": False, "error": "dspy non installe", "raw": ""}
    sig_cls = {"CodePatchProposal": CodePatchProposal, "StrategyHypothesis": StrategyHypothesis}.get(signature_name)
    if sig_cls is None:
        return {"ok": False, "error": f"signature {signature_name} inconnue", "raw": ""}
    out_fields = [
        n
        for n, f in sig_cls.__pydantic_fields__.items()  # type: ignore[attr-defined]
        if getattr(f, "json_schema_extra", {}).get("__dspy_field_type") == "output"
    ]
    if not out_fields:  # fallback signature legere
        out_fields = ["code", "rationale", "risk_level", "affected_symbols"]
    # Build example JSON populated with type hints
    example_vals = {
        "code": "def f():\\n    return 42",
        "rationale": "explanation",
        "risk_level": "low",
        "affected_symbols": "f",
        "hypothesis": "approach X",
        "evidence": "POUR",
        "counter_evidence": "CONTRE",
        "confidence_self": 0.7,
    }
    example = "{" + ", ".join(f'"{k}": {json.dumps(example_vals.get(k, "value"))}' for k in out_fields) + "}"
    schema_lines = "\n".join(f'  "{k}": <string>' for k in out_fields)
    schema_block = "{\n" + schema_lines + "\n}"
    input_dump = "\n".join(f"{k}: {v}" for k, v in inputs.items())
    prompt = (
        "Tu reponds UNIQUEMENT par un objet JSON valide. Pas de markdown, "
        "pas de fence ```, pas de prose autour. Premier caractere = '{', "
        "dernier caractere = '}'. STRICT.\n\n"
        f"Schema attendu (tous champs obligatoires) :\n{schema_block}\n\n"
        f"Exemple de rendu valide :\n{example}\n\n"
        f"Entrees :\n{input_dump}\n\n"
        "Ta reponse (JSON seul) :"
    )
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "provider": provider,
                    "message": prompt,
                    "max_tokens": max_tokens,
                    "rag_context": False,
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        HUB_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {hub_token}",
            "LaForge-Agent-Name": "DSPY_ROUTER",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = json.loads(r.read())
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        # Unwrap hub ask envelope si present
        try:
            inner = json.loads(text)
            if isinstance(inner, dict) and "text" in inner:
                text = inner["text"]
        except (json.JSONDecodeError, TypeError):  # muet-ok : texte hors enveloppe garde tel quel, l'extraction tranche
            pass
        # Extract first JSON object
        import re as _re

        m = _re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {"ok": False, "error": "no JSON object in response", "raw": text[:500]}
        fields = json.loads(m.group())
        missing = [k for k in out_fields if k not in fields]
        if missing:
            return {"ok": False, "error": f"missing fields: {missing}", "raw": text[:500], "fields": fields}
        return {"ok": True, "fields": fields, "raw": text}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "raw": ""}
