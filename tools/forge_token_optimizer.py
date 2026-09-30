"""
forge_token_optimizer.py — Compression de prompts pour économiser les tokens
=============================================================================
Réduit la taille des prompts envoyés aux LLMs (Groq/Ollama/Gemini) de 20-40%
via trois stratégies :

1. compress_code()      : supprime commentaires, docstrings, lignes vides
2. semantic_trim()      : élague les logs/erreurs volumineux (début + fin)
3. ast_pruning()        : ne garde que la fonction cible + imports + squelettes

Usage dans MultiLLMBridge :
    from tools.forge_token_optimizer import ForgeTokenOptimizer
    opt    = ForgeTokenOptimizer()
    prompt = opt.compress_code(raw_code, aggressive=False)
    prompt = opt.semantic_trim(prompt, max_chars=4000)
"""

from __future__ import annotations

import ast
import json
import re


class ForgeTokenOptimizer:
    """Optimise et compresse les prompts pour économiser les tokens LLM."""

    # Patterns de bruit à supprimer
    CODE_NOISE: list[str] = [
        r"#[^\n]*",  # Commentaires inline
        r"'''[\s\S]*?'''",  # Docstrings triple quotes simples
        r'"""[\s\S]*?"""',  # Docstrings triple quotes doubles
        r"\n{3,}",  # 3+ lignes vides consécutives → 1
    ]

    def __init__(self) -> None:
        """Initialise l'optimiseur avec les patterns de compression."""
        self._compiled = [(re.compile(p), p) for p in self.CODE_NOISE]

    def compress_code(self, code: str, aggressive: bool = False) -> str:
        """Réduit la taille du code source sans changer la logique.

        Supprime commentaires, docstrings et lignes vides superflues.
        Mode agressif : indentation 4→2 espaces (gain ~5% supplémentaire).

        Args:
            code:       Code Python source à compresser.
            aggressive: Si True, réduit l'indentation de 4 à 2 espaces.

        Returns:
            Code compressé (string).
        """
        compressed = code

        for pattern, _ in self._compiled:
            if "'''" in pattern.pattern or '"""' in pattern.pattern:
                compressed = pattern.sub("", compressed)
            elif r"\n{3,}" in pattern.pattern:
                compressed = pattern.sub("\n\n", compressed)
            else:
                compressed = pattern.sub("", compressed)

        # Normaliser les lignes vides et trailing whitespace
        compressed = "\n".join(line.rstrip() for line in compressed.splitlines() if line.strip())

        if aggressive:
            compressed = compressed.replace("    ", "  ")

        return compressed

    def compress_json_payload(self, data: dict) -> str:
        """Compresse un dict de paramètres en JSON minimal (sans espaces).

        Args:
            data: Dictionnaire à compresser.

        Returns:
            JSON minifié.
        """
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)

    def semantic_trim(self, text: str, max_chars: int = 4000) -> str:
        """Élague un texte long en gardant début + fin.

        Idéal pour les logs pytest, erreurs longues, stacktraces.
        Garde les 50% premiers + 50% derniers caractères.

        Args:
            text:      Texte à élager.
            max_chars: Taille maximale autorisée.

        Returns:
            Texte élagé avec marqueur de compression.
        """
        if len(text) <= max_chars:
            return text

        keep = max_chars // 2
        omitted = len(text) - max_chars
        return (
            f"{text[:keep]}\n\n"
            f"[... COMPRESSION SÉMANTIQUE : {omitted} caractères omis ...]\n\n"
            f"{text[-keep:]}"
        )

    def ast_pruning(self, code: str, target_node_name: str) -> str:
        """Chirurgie AST : ne garde que la fonction/classe cible + imports.

        Remplace le corps des autres fonctions/classes par `pass`.
        Évite d'envoyer 1000 lignes quand on n'en modifie que 10.

        Args:
            code:             Code Python complet.
            target_node_name: Nom de la fonction ou classe cible.

        Returns:
            Code élagué avec seulement le contexte nécessaire.
        """
        try:
            tree = ast.parse(code)
            pruned_nodes = []

            for node in tree.body:
                # Garder tous les imports (contexte vital)
                if (
                    isinstance(node, (ast.Import, ast.ImportFrom))
                    or hasattr(node, "name")
                    and node.name == target_node_name
                ):
                    pruned_nodes.append(node)

                # Squelette pour les autres fonctions/classes
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    node.body = [ast.Pass()]
                    pruned_nodes.append(node)

                # Garder les autres nœuds (assignations module-level, etc.)
                else:
                    pruned_nodes.append(node)

            tree.body = pruned_nodes
            return ast.unparse(tree)

        except Exception:
            return code  # Fallback silencieux

    def optimize_prompt(
        self,
        code: str,
        task: str = "",
        max_chars: int = 8000,
        target_fn: str | None = None,
        aggressive: bool = False,
    ) -> tuple[str, dict]:
        """Pipeline complet d'optimisation de prompt.

        Combine compress_code + ast_pruning (si cible) + semantic_trim.

        Args:
            code:       Code source à optimiser.
            task:       Instruction de la tâche (non compressée).
            max_chars:  Taille maximale du code dans le prompt.
            target_fn:  Nom de la fonction cible pour AST pruning.
            aggressive: Mode compression agressive.

        Returns:
            Tuple (code_optimisé, stats_dict).
        """
        original_len = len(code)

        # 1. Compression du code
        optimized = self.compress_code(code, aggressive=aggressive)

        # 2. AST pruning si cible fournie
        if target_fn:
            optimized = self.ast_pruning(optimized, target_fn)

        # 3. Trim sémantique si encore trop long
        optimized = self.semantic_trim(optimized, max_chars=max_chars)

        final_len = len(optimized)
        reduction = (1 - final_len / max(original_len, 1)) * 100

        stats = {
            "original_chars": original_len,
            "final_chars": final_len,
            "reduction_pct": round(reduction, 1),
            "target_fn": target_fn,
            "aggressive": aggressive,
        }
        return optimized, stats


# ── Singleton global ──────────────────────────────────────────────────────────
_optimizer: ForgeTokenOptimizer | None = None


def get_optimizer() -> ForgeTokenOptimizer:
    """Retourne l'instance globale de ForgeTokenOptimizer (singleton).

    Returns:
        Instance ForgeTokenOptimizer prête à l'emploi.
    """
    global _optimizer
    if _optimizer is None:
        _optimizer = ForgeTokenOptimizer()
    return _optimizer
