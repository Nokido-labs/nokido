"""forge_intent_risk.py — risque semantique d'une intention d'outil, evalue AVANT le dispatch MCP.

Deplace tel quel de forge_spike_router (2026-10-02, decision tranchee « import paresseux de torch ») :
`evaluate_intent` est appele en TETE de chaque dispatch du registre MCP (couche SpikeRouter de
forge_mcp_registry) et par nokido_proxy_guard, mais il n'utilise que numpy et l'embedder. Il vivait
dans forge_spike_router, dont la tete fait `import torch` pour son routeur neuronal : chaque processus
qui importait le registre (le hub compris) chargeait torch pour rien. Mesure du 2026-10-02 : importer
forge_mcp_registry chargeait torch via forge_mcp_registry.py:56 -> forge_spike_router.py:35.

Pourquoi un module et non un import paresseux : l'appel a lieu a CHAQUE dispatch, un import differe
aurait seulement decale le chargement de torch au premier outil appele. forge_spike_router reexporte
ces deux noms pour ses anciens appelants.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/risque semantique des intentions d'outil avant dispatch"

import uuid

import numpy as np

RISK_CATEGORIES = {
    "DESTRUCTIVE": [
        "supprimer un dossier",
        "effacer la base de données",
        "formater le disque",
        "delete files",
        "drop table",
        "remove directory",
        "purge logs",
    ],
    "EXPLORATORY": [
        "lister les fichiers",
        "lire la configuration",
        "chercher des secrets",
        "list directory",
        "read config",
        "scan network",
        "check environment",
    ],
    "CONFIGURATIONAL": [
        "modifier le port",
        "changer l'api key",
        "mettre à jour le système",
        "update settings",
        "change password",
        "install package",
    ],
}


def evaluate_intent(payload: dict) -> dict:
    """
    Analyse sémantique de l'intention du payload.
    Retourne un objet de négociation si le risque est élevé.
    """
    from nokido_agent.app.forge_npu_embedder import get_embed

    requested_tools = payload.get("tools", [])
    if not requested_tools:
        return {"status": "safe", "reason": "No tools requested"}

    # Extraction du texte de l'intention (noms des outils + descriptions si présentes)
    intent_text = " ".join(
        [
            f"{t.get('function', {}).get('name', t.get('name', ''))} {t.get('function', {}).get('description', '')}"
            for t in requested_tools
        ]
    )

    # Embedding de l'intention (1024 dims via NPU)
    intent_vec = get_embed([intent_text])
    if not intent_vec:
        return {"status": "error", "message": "NPU embedding failed"}

    intent_vec = np.array(intent_vec[0])

    # Comparaison sémantique avec les catégories de risque
    max_score = 0.0
    detected_category = "UNKNOWN"

    for category, examples in RISK_CATEGORIES.items():
        example_vecs = get_embed(examples)
        if not example_vecs:
            continue

        # Similitude cosinus vectorisée
        m = np.array(example_vecs)
        scores = m @ intent_vec / (np.linalg.norm(m, axis=1) * np.linalg.norm(intent_vec) + 1e-9)
        best_score = np.max(scores)

        if best_score > max_score:
            max_score = best_score
            detected_category = category

    # Seuil de négociation (Human-in-the-Loop)
    if max_score > 0.75 and detected_category == "DESTRUCTIVE":
        return {
            "status": "requires_negotiation",
            "intent_id": f"req_{uuid.uuid4().hex[:6].upper()}",
            "tool_requested": requested_tools[0].get("name", "unknown"),
            "ai_justification": f"L'action est classée comme {detected_category} (score: {max_score:.2f})",
            "risk_assessment": "high_data_loss",
            "payload": payload,
        }

    return {"status": "safe", "category": detected_category, "score": float(max_score)}
