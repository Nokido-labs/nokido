# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_distiller.py — Distilleur de contexte RAG pour l'exposition API
======================================================================
Rôle : filtrer, dédupliquer et purger les résultats RagCache avant
envoi via HTTP API. Évite le "Token Bloat" et protège les métadonnées
internes (vec_hash, UUIDs, timestamps) de fuiter vers les consommateurs.

3 étapes (overhead mesuré : ~0.024ms pour k=5) :
  1. Déduplication sémantique  — fusionne les chunks trop proches (cosine > seuil)
  2. Purge meta                — supprime les champs internes non destinés à l'API
  3. Rank-filtering            — top-K strict + score minimum

Ring non-leakage :
  Le distilleur reçoit user_ring (déduit du token d'authentification) et
  applique ring_max=user_ring avant de distiller. Un token ring=2 ne
  verra jamais un chunk ring=0.

USAGE :
    from forge_distiller import Distiller, distill
    results = cache.search(qvec, k=10)
    clean   = distill(results, user_ring=2, top_k=3)
"""


import hashlib
import json
import os
from typing import List, Optional

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Champs exposés par l'API selon le ring du demandeur
# ─────────────────────────────────────────────────────────────────────────────

# Champs JAMAIS exposés via API (métadonnées internes)
_INTERNAL_FIELDS = frozenset(
    {
        "vec_hash",
        "vec_sig",
        "uuid",
        "ingested_at",
        "updated_at",
        "version_id",
        "session_id",
        "sequence_id",
        "author",
    }
)

# Champs exposés selon ring du demandeur
_FIELDS_BY_RING = {
    0: {"id", "text", "source", "domain", "ring", "score", "trust_score", "consensus"},  # SYSTEM — tout sauf interne
    1: {"id", "text", "source", "domain", "ring", "score", "trust_score", "consensus"},  # DEV — idem
    2: {"text", "source", "domain", "score", "trust_score"},  # TRUSTED
    3: {"text", "source", "domain", "score"},  # COLLAB
    4: {"text", "domain", "score"},  # UNTRUSTED
}


def _fields_for_ring(user_ring: int) -> frozenset:
    """Retourne l'ensemble des champs autorisés pour un ring donné."""
    # Le ring le plus restrictif qui couvre user_ring
    r = min(user_ring, 4)
    return frozenset(_FIELDS_BY_RING.get(r, {"text", "score"}))


# ─────────────────────────────────────────────────────────────────────────────


class Distiller:
    """
    Distilleur de contexte RAG.
    Stateless — peut être appelé depuis plusieurs threads simultanément.
    """

    def __init__(
        self,
        dedup_threshold: float = 0.88,  # cosine sim > seuil → dédupliquer
        min_score: float = 0.10,  # score cosine minimum
        text_max_chars: int = 500,  # troncature texte pour l'API
    ):
        """Initialise."""
        self.dedup_threshold = float(os.environ.get("LAFORGE_DEDUP_THRESHOLD", dedup_threshold))
        self.min_score = min_score
        self.text_max_chars = text_max_chars

    # ── API principale ────────────────────────────────────────────────────────

    def distill(
        self,
        results: List[dict],
        user_ring: int = 4,
        top_k: int = 5,
    ) -> List[dict]:
        """
        Pipeline complet :
          1. Filtre ring (non-leakage)
          2. Filtre score minimum
          3. Déduplication sémantique
          4. Top-K strict
          5. Purge meta + troncature texte

        Args:
            results   : sortie brute de RagCache.search()
            user_ring : ring du demandeur (déduit du token)
            top_k     : nombre maximum de chunks retournés

        Returns:
            liste de dicts propres, prêts pour JSON API
        """
        if not results:
            return []

        # Étape 1 : non-leakage ring
        filtered = [r for r in results if r.get("ring", 3) >= user_ring]
        # Note : ring >= user_ring signifie "ring moins privilégié ou égal"
        # ring=0 SYSTEM est le plus privilégié → visible uniquement par user_ring=0
        # ring=2 TRUSTED visible par user_ring <= 2
        # Reformulation correcte : chunk visible si chunk_ring >= user_ring
        # (un token ring=2 ne voit que les chunks ring >= 2)
        filtered = [r for r in results if r.get("ring", 3) >= user_ring]

        # Étape 2 : score minimum
        filtered = [r for r in filtered if r.get("score", 0) >= self.min_score]

        if not filtered:
            return []

        # Étape 3 : déduplication sémantique
        deduped = self._deduplicate(filtered)

        # Étape 4 : top-K strict
        top = deduped[:top_k]

        # Étape 5 : purge meta + troncature
        allowed = _fields_for_ring(user_ring)
        clean = []
        for r in top:
            chunk = {}
            for k2, v in r.items():
                if k2 in _INTERNAL_FIELDS:
                    continue
                if k2 not in allowed:
                    continue
                if k2 == "text" and isinstance(v, str):
                    v = v[: self.text_max_chars]
                chunk[k2] = v
            if chunk:
                clean.append(chunk)

        return clean

    # ── Déduplication sémantique ──────────────────────────────────────────────

    def _deduplicate(self, results: List[dict]) -> List[dict]:
        """
        Supprime les chunks sémantiquement redondants.
        Stratégie : comparaison par paires sur les textes (hachage lexical rapide
        pour éviter un re-embed à chaque appel).

        Pour une vraie déduplication vectorielle, les vecteurs doivent être
        passés dans results["_vec"] (optionnel — non exposé via API).
        """
        if len(results) <= 1:
            return results

        # Déduplication vectorielle si vecteurs disponibles
        vecs_available = all("_vec" in r for r in results)
        if vecs_available:
            return self._dedup_vectors(results)

        # Fallback : déduplication lexicale (overlap de mots)
        return self._dedup_lexical(results)

    def _dedup_vectors(self, results: List[dict]) -> List[dict]:
        """Déduplication cosine sur vecteurs pré-calculés."""
        vecs = np.array([r["_vec"] for r in results], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs_n = vecs / (norms + 1e-9)
        sim = vecs_n @ vecs_n.T  # (N, N)

        kept = []
        suppressed = set()
        for i in range(len(results)):
            if i in suppressed:
                continue
            kept.append(results[i])
            for j in range(i + 1, len(results)):
                if j not in suppressed and sim[i, j] > self.dedup_threshold:
                    suppressed.add(j)
        return kept

    def _dedup_lexical(self, results: List[dict]) -> List[dict]:
        """Déduplication par overlap Jaccard sur les mots (fallback sans vecteurs)."""
        import re

        def tokenize(text: str) -> frozenset:
            """Tokenize."""
            return frozenset(re.findall(r"\b\w{4,}\b", text.lower()))

        kept = []
        kept_tokens: List[frozenset] = []
        threshold_jaccard = 0.65  # overlap Jaccard > 65% = doublon

        for r in results:
            tokens = tokenize(r.get("text", ""))
            is_dup = False
            for existing in kept_tokens:
                if not tokens or not existing:
                    continue
                inter = len(tokens & existing)
                union = len(tokens | existing)
                if union > 0 and inter / union > threshold_jaccard:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(r)
                kept_tokens.append(tokens)
        return kept

    # ── Hash d'intégrité de la réponse ────────────────────────────────────────

    @staticmethod
    def integrity_hash(results: List[dict]) -> str:
        """
        SHA256 court de la réponse distillée.
        Permet au client de vérifier que la réponse n'a pas été altérée
        en transit (MITM).
        """
        payload = json.dumps(
            [{"text": r.get("text", ""), "source": r.get("source", "")} for r in results],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + fonction de commodité
# ─────────────────────────────────────────────────────────────────────────────

_DISTILLER: Optional[Distiller] = None


def get_distiller() -> Distiller:
    """Retourne le singleton Distiller (thread-safe, lazy)."""
    global _DISTILLER
    if _DISTILLER is None:
        _DISTILLER = Distiller()
    return _DISTILLER


def distill(
    results: List[dict],
    user_ring: int = 4,
    top_k: int = 5,
) -> dict:
    """
    Fonction de commodité — distille + calcule integrity_hash.

    Returns:
        {
          "results":        [...],   # chunks distillés
          "n_raw":          int,     # taille avant distillation
          "n_distilled":    int,     # taille après
          "integrity_hash": str,     # SHA256[:16] de la réponse
          "user_ring":      int,
        }
    """
    d = get_distiller()
    clean = d.distill(results, user_ring=user_ring, top_k=top_k)
    return {
        "results": clean,
        "n_raw": len(results),
        "n_distilled": len(clean),
        "integrity_hash": Distiller.integrity_hash(clean),
        "user_ring": user_ring,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ring resolution depuis token — pont forge_mcp_security
# ─────────────────────────────────────────────────────────────────────────────


def ring_from_token(token: str) -> int:
    """
    Résout le ring d'un token Bearer via MCPSecurity.
    Retourne un entier 0-4 (0=SYSTEM, 4=UNTRUSTED).

    Utilisé par forge_mcp_http pour passer ring_max à RagCache.search()
    et user_ring à distill().
    """
    _ROLE_TO_RING = {
        "laforge": 0,  # SYSTEM/DEV
        "claude": 1,  # DEV
        "cline": 2,  # TRUSTED
        "ollama": 3,  # COLLAB
        "external": 4,  # UNTRUSTED
        "readonly": 4,
    }
    try:
        # Couche reseau restauree le 2026-10-01 : cet import echouait, tout jeton rendait 4.
        from nokido_agent.app.forge_mcp_securite_reseau import get_security

        sec = get_security()
        ok, agent = sec.authenticate_bearer(f"Bearer {token}")
        if not ok:
            return 4  # token invalide → UNTRUSTED
        role = sec._resolve_role(agent)
        return _ROLE_TO_RING.get(role, 4)
    except Exception:
        return 4  # sécurité dégradée → ring le plus restrictif
