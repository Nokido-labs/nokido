"""
app/forge_js_endpoint_extractor.py — Extracteur d'endpoints JS pour Bug Bounty.
=============================================================================
Beautifie les bundles JS, utilise des regex et le LLM pour trouver les URLs cachées.
Intégration directe dans le domaine EXPLOIT du SiloEngine.
"""

import re
import json
import logging
import asyncio
from pathlib import Path
from typing import List, Set, Dict, Any, Optional

logger = logging.getLogger(__name__)


class JSEndpointExtractor:
    """Analyseur de fichiers JS pour extraction de routes API."""

    def __init__(self, llm_provider: str = "groq"):
        self.llm_provider = llm_provider

    def beautify(self, js_content: str) -> str:
        """
        Beautification légère pour faciliter l'analyse.
        Insère des sauts de ligne stratégiques pour les regex multi-lignes.
        """
        # Ajouter sauts de ligne apres ; { } [ ] si absents
        content = re.sub(r"([;{}\[\]])", r"\1\n", js_content)
        # Espacer les opérateurs
        content = re.sub(r"\s*([:=,])\s*", r" \1 ", content)
        # Supprimer les blocs de lignes vides
        content = re.sub(r"\n\s*\n", "\n", content)
        return content

    def extract_via_regex(self, js_content: str) -> Set[str]:
        """
        Extraction intensive par patterns regex.
        Couvre webpack, vite, axios, fetch et patterns de routage SPA.
        """
        found = set()
        patterns = [
            r'["\'](/api/[a-zA-Z0-9/_\-\.]+)["\']',  # Standard /api/
            r'(?:fetch|axios\.(?:get|post|put|patch|delete))\(["\']([^"\']+)["\']',  # HTTP libs
            r'path\s*:\s*["\']([/][^"\']{2,})["\']',  # Vue/React Router
            r'["\'](?:url|endpoint|path|route|uri)["\']\s*[:=]\s*["\'](/[^"\']{2,})["\']',  # Config keys
            r'(?:baseURL|BASE_URL|API_URL)\s*[:=]\s*["\']([^"\']+)["\']',  # Base URLs
            r'["\'](http[s]?://[a-zA-Z0-9./\-_?&=]+)["\']',  # URLs absolues
            r'href\s*[:=]\s*["\'](/[^"\']{2,})["\']',  # Liens internes
            r'\.concat\(["\'](/[^"\']+)["\']\)',  # Concaténations
            r'\+ ["\'](/[^"\']+)["\']',  # Additions de strings
        ]
        for pat in patterns:
            try:
                matches = re.findall(pat, js_content, re.IGNORECASE)
                found.update(matches)
            except Exception as e:
                logger.debug(f"Regex error for pattern {pat}: {e}")

        # Post-filtrage : supprimer les extensions de fichiers et faux positifs
        exclude_ext = (".js", ".css", ".png", ".svg", ".woff", ".map", ".jpg", ".jpeg", ".gif", ".ico")
        clean = {
            e
            for e in found
            if len(e) >= 3
            and not e.lower().endswith(exclude_ext)
            and "node_modules" not in e
            and not e.startswith("//")
            and not re.match(r"^[A-Z_]+$", e)  # Exclure les constantes type MB_PORT
        }
        return clean

    async def refine_with_llm(self, endpoints: List[str], js_context: str) -> List[str]:
        """
        Utilise le LLM pour valider les endpoints et deviner les paramètres manquants.
        """
        if not endpoints:
            return []

        # On limite le contexte pour le LLM
        snippet = js_context[:3000]
        prompt = f"""
        Analyze these detected endpoints and the JS code snippet. 
        Identify hidden parameters (e.g. /api/user/:id) and confirm which ones are likely valid API routes.
        Detected: {endpoints}
        
        JS CODE:
        {snippet}
        
        Return a JSON list of objects: {{"path": "...", "method": "...", "description": "..."}}
        """
        # L'appel effectif serait fait via le hub.ask
        return endpoints  # Fallback si pas d'appel hub direct ici

    def run_pipeline(self, js_path: str) -> Dict[str, Any]:
        """Exécute l'analyse complète."""
        p = Path(js_path)
        if not p.exists():
            return {"error": f"Fichier {js_path} introuvable"}

        try:
            raw = p.read_text("utf-8", errors="replace")
            # 1. Extraction regex sur raw
            raw_eps = self.extract_via_regex(raw)

            # 2. Beautify pour analyse plus fine
            beauty = self.beautify(raw)
            beauty_eps = self.extract_via_regex(beauty)

            all_eps = sorted(list(raw_eps | beauty_eps))

            return {
                "file": str(p.name),
                "total_found": len(all_eps),
                "endpoints": all_eps,
                "summary": f"Extraction terminée : {len(all_eps)} endpoints trouvés dans {p.name}.",
            }
        except Exception as e:
            return {"error": str(e)}


def silo_js_extract(js_path: str) -> Dict[str, Any]:
    """
    Point d'entrée offensif (zone lab — ex-SiloDomain.EXPLOIT, plan séparation 1c).
    """
    extractor = JSEndpointExtractor()
    return extractor.run_pipeline(js_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        res = silo_js_extract(sys.argv[1])
        print(json.dumps(res, indent=2))
    else:
        print("Usage: python forge_js_endpoint_extractor.py <path_to_js>")
