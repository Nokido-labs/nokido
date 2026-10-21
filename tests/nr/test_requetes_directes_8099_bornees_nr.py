"""NR -- voie longue de l'embedding : les REQUETES directes a l'embedder :8099 passent par la borne du routeur.

Item SSoT roadmap_p1_voie_longue_embedding_20261008 (reste : « bornes des requetes directes forge_mcp_registry /
forge_epistemic_veille ») ; releve AGY 19/10 (job_34d934a0) : `app/forge_epistemic_veille.py:188` et la recherche
hybride du registre postaient la requete BRUTE a `:8099/v1/embeddings` -- une requete plus longue que le contexte de
l'embedder echouait ou se tronquait sans le dire, la ou `forge_embed_router._llama8099_call` borne (`_borner_textes_8099`)
et inscrit les tronques. On reste sur :8099 (meme espace de vecteurs que Qdrant) : jamais le repli cloud generique.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_aucune_requete_brute_a_8099_dans_ces_deux_modules():
    for rel in ("app/forge_epistemic_veille.py", "app/forge_mcp_registry.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r":8099/v1/embeddings", src), "%s poste encore la requete brute a :8099" % rel
        assert "_llama8099_call(" in src, "%s doit passer par forge_embed_router._llama8099_call" % rel
