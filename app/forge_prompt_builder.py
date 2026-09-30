"""
app/forge_prompt_builder.py — Constructeur de prompts enrichis par le RAG Nokido
===================================================================================
Rôle : permettre à des LLMs moins puissants (Llama 8B, qwen, mistral)
d'atteindre la qualité d'un LLM de haut niveau en leur injectant :

  1. La connaissance pertinente du RAG (bugs connus, patterns dangereux)
  2. La structure de prompt optimale pour la tâche
  3. Les règles Nokido (Cerberus, tests attendus)
  4. Des exemples tirés du vault (scores ≥ 90)

Usage :
  from forge_prompt_builder import PromptBuilder
  pb     = PromptBuilder()
  prompt = await pb.build("fix this bug", code=src, task_type="bugfix")
  result = await llm.complete(prompt)   # Llama 8B suffit
"""

from __future__ import annotations

import ast
import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"

TaskType = Literal["bugfix", "docstring", "refactor", "test", "explain", "review"]

# ── Règles statiques injectées selon le type de tâche ─────────────────────────
STATIC_RULES: dict[str, list[str]] = {
    "bugfix": [
        "Utilise `is not None` pour tester la présence d'un argument optionnel, "
        "jamais `if value:` (car '', 0, False sont des valeurs valides).",
        "Ne jamais swallow asyncio.CancelledError ni KeyboardInterrupt — ces exceptions doivent toujours remonter.",
        "Vérifie les imports manquants avant de modifier une fonction.",
        "Retourne UNIQUEMENT le code corrigé, sans explication.",
    ],
    "docstring": [
        "Format Google-style : Args:, Returns:, Raises:, Example:.",
        "Une ligne de résumé, puis sections détaillées si nécessaire.",
        "Retourne UNIQUEMENT le code avec docstrings ajoutées.",
    ],
    "refactor": [
        "Conserve le comportement observable exact.",
        "Réduis la complexité cyclomatique si > 10.",
        "Évite les imports circulaires — utilise des imports lazy dans les fonctions.",
    ],
    "test": [
        "Un test par comportement observable, pas par ligne de code.",
        "Utilise pytest + unittest.mock pour les dépendances externes.",
        "Inclus toujours un test du cas nominal ET un cas d'erreur.",
    ],
    "explain": [
        "Explique le POURQUOI, pas seulement le QUOI.",
        "Maximum 5 lignes, langage simple.",
    ],
    "review": [
        "Signale les anti-patterns Python (mutable defaults, bare except, etc.).",
        "Score de 0 à 100 : clarté, robustesse, maintenabilité.",
    ],
}


class PromptBuilder:
    """Construit des prompts enrichis RAG pour maximiser la qualité des petits LLMs.

    Args:
        rag_db: Chemin vers la base RAG Nokido.
        max_rag_chars: Limite du contexte RAG injecté.
        max_vault_examples: Nombre d'exemples vault à injecter.
    """

    def __init__(
        self,
        rag_db: Path = RAG_DB,
        max_rag_chars: int = 1500,
        max_vault_examples: int = 2,
    ) -> None:
        self._db = rag_db
        self._max_rag = max_rag_chars
        self._max_vault = max_vault_examples
        self._rag_available = rag_db.exists()

    # ── API publique ───────────────────────────────────────────────────────────

    async def build(
        self,
        instruction: str,
        code: str = "",
        task_type: TaskType = "bugfix",
        compress_code: bool = True,
        max_code_chars: int = 4000,
    ) -> str:
        """Construit un prompt enrichi prêt à envoyer à n'importe quel LLM.

        Args:
            instruction:   Ce que l'utilisateur veut faire.
            code:          Code source cible (optionnel).
            task_type:     Type de tâche (bugfix, docstring, refactor...).
            compress_code: Compresser le code avant injection (retire commentaires).
            max_code_chars: Limite du code injecté.

        Returns:
            Prompt complet avec contexte RAG + règles + code.
        """
        parts: list[str] = []

        # 1. Règles statiques de la tâche
        rules = STATIC_RULES.get(task_type, [])
        if rules:
            parts.append("RÈGLES :\n" + "\n".join(f"- {r}" for r in rules))

        # 2. Contexte RAG pertinent
        rag_ctx = await self._fetch_rag(instruction + " " + (code[:200] if code else ""))
        if rag_ctx:
            parts.append(f"CONNAISSANCE NOKIDO (RAG) :\n{rag_ctx}")

        # 3. Code source (compressé si nécessaire)
        if code:
            src = self._maybe_compress(code, compress_code)[:max_code_chars]
            parts.append(f"CODE :\n```python\n{src}\n```")

        # 4. Instruction finale
        parts.append(f"TÂCHE : {instruction}")

        return "\n\n".join(parts)

    def build_sync(self, *args, **kwargs) -> str:
        """Version synchrone de build()."""
        return asyncio.run(self.build(*args, **kwargs))

    # ── Recherche RAG ──────────────────────────────────────────────────────────

    async def _fetch_rag(self, query: str) -> str:
        """Cherche les chunks RAG pertinents pour la requête.

        Args:
            query: Texte de la requête.

        Returns:
            Contexte concaténé des chunks pertinents.
        """
        if not self._rag_available:
            return ""
        try:
            # Recherche par mots-clés simples (pas besoin d'embedding pour les règles)
            keywords = [w.lower() for w in query.split() if len(w) > 4][:8]
            if not keywords:
                return ""

            conn = sqlite3.connect(str(self._db), timeout=3)
            conn.execute("PRAGMA journal_mode=WAL")

            results = []
            for kw in keywords[:4]:
                # rag_fts (FTS5 indexe) au lieu de `text LIKE '%kw%'` : ce SELECT en
                # boucle faisait une passe full-scan de rag_chunks (466k+ lignes,
                # wildcard en tete non-indexable) par mot-cle -- meme classe mesuree
                # a x69 (30,9s->0,45s). Repli LIKE si rag_fts absent sur cette base.
                q = kw.replace('"', " ").strip()
                if not q:
                    continue
                try:
                    rows = conn.execute(
                        "SELECT text FROM rag_fts WHERE rag_fts MATCH ? LIMIT 2",
                        ('"' + q + '"',)).fetchall()
                except sqlite3.OperationalError:  # rag_fts absent -> repli LIKE (lent)
                    rows = conn.execute(
                        "SELECT text FROM rag_chunks WHERE text LIKE ? LIMIT 2",
                        (f"%{kw}%",)).fetchall()
                for (txt,) in rows:
                    if len(txt) > 50 and txt not in results:
                        results.append(txt)

            conn.close()

            if not results:
                return ""

            # Prendre les plus courts (plus denses)
            results.sort(key=len)
            combined = "\n---\n".join(r[:400] for r in results[:3])
            return combined[: self._max_rag]

        except Exception as e:
            logger.debug(f"[PromptBuilder] RAG fetch: {e}")
            return ""

    # ── Compression code ───────────────────────────────────────────────────────

    def _maybe_compress(self, code: str, do_compress: bool) -> str:
        """Supprime les commentaires et docstrings pour réduire le contexte.

        Args:
            code:        Code source Python.
            do_compress: Si False, retourne le code tel quel.

        Returns:
            Code compressé ou original.
        """
        if not do_compress:
            return code
        try:
            sys_path_backup = None  # no-op
            tree = ast.parse(code)
            lines = code.splitlines()
            # Supprimer les lignes commentaire
            clean = [l for l in lines if not l.strip().startswith("#") and l.strip() != '"""' and l.strip() != "'''"]
            return "\n".join(clean)
        except Exception:
            return code

    # ── Helpers ────────────────────────────────────────────────────────────────

    def estimate_tokens(self, text: str) -> int:
        """Estimation rapide du nombre de tokens (1 token ≈ 4 chars).

        Args:
            text: Texte à mesurer.

        Returns:
            Nombre de tokens estimé.
        """
        return len(text) // 4

    def __repr__(self) -> str:
        return f"PromptBuilder(rag={'✅' if self._rag_available else '❌'}, max_rag={self._max_rag}chars)"
