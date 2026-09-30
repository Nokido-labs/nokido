import os
import re
import sys
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Primitive d'ingestion canonique (app/forge_ingest_pipeline.py) : ce module lit le
# miroir RFC local, il ne REIMPLEMENTE ni le chunking ni l'ecriture SQLite.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "app"), os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

class LocalRFCIngestionTool:
    """
    Outil d'ingestion JIT (Just-In-Time) SOUVERAIN (Air-gapped).
    Lit les RFC depuis le miroir local rsync au lieu de frapper le web avec SearXNG.
    Latence : ~10ms, 100% déterministe. Évite de saturer l'arbre MCTS avec des appels réseau.
    """
    def __init__(self, mirror_dir: str = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "rfc_mirror")):
        self.mirror_dir = mirror_dir
        self.index_file = os.path.join(self.mirror_dir, "rfc-index.txt")

    def _search_local_index(self, query: str) -> dict:
        """Fouille le rfc-index.txt local pour trouver l'ID exact de la norme."""
        if not os.path.exists(self.index_file):
            logging.error("Miroir RFC non synchronisé. rfc-index.txt introuvable.")
            return {}

        query_terms = query.lower().split()
        
        # Check if the query is asking for a specific RFC number
        explicit_rfc_match = re.search(r'rfc\s*(\d+)', query.lower())
        explicit_rfc_num = explicit_rfc_match.group(1) if explicit_rfc_match else None

        best_match = None
        highest_score = 0
        
        # Lecture du fichier d'index (~20MB, se fait en qq millisecondes)
        with open(self.index_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Les entrées RFC dans l'index IETF sont séparées par lignes vides
        entries = re.split(r'\n\s*\n', content)
        
        for entry in entries:
            entry = entry.strip()
            if not entry or not entry[0].isdigit():
                continue
            
            rfc_match = re.match(r'^(\d+)\s+', entry)
            if not rfc_match:
                continue
                
            entry_rfc_num = rfc_match.group(1)
            
            # If we asked for a specific RFC, and this is it, return it immediately
            if explicit_rfc_num and entry_rfc_num == explicit_rfc_num:
                return {
                    "id": "rfc" + entry_rfc_num,
                    "title": entry.replace('\n', ' ')[:150] + "...",
                    "score": 999
                }
            
            # Score de pertinence (TF sans IDF) pour les concepts (ex: "OAuth 2.0 Threat Model")
            score = sum(1 for term in query_terms if term in entry.lower())
            if score > highest_score:
                highest_score = score
                best_match = {
                    "id": "rfc" + entry_rfc_num,
                    "title": entry.replace('\n', ' ')[:150] + "...",
                    "score": score
                }
        
        return best_match or {}

    def _fetch_local_rfc(self, rfc_id: str) -> str:
        """Charge le fichier texte brut de la RFC depuis le disque (Stockage froid)."""
        filepath = os.path.join(self.mirror_dir, f"{rfc_id}.txt")
        if not os.path.exists(filepath):
            logging.error(f"Fichier RFC introuvable : {filepath}")
            return ""
            
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def process_and_ingest(self, concept_query: str) -> Dict[str, Any]:
        """Pipeline complet appelé par l'agent via le protocole MCP."""
        logging.info(f"Demande d'ingestion JIT SOUVERAINE pour : {concept_query}")
        
        target = self._search_local_index(concept_query)
        if not target:
            return {"status": "error", "message": "Aucune RFC trouvée localement. Veuillez lancer tools/sync_rfc_mirror.ps1 pour hydrater le stockage froid."}
            
        rfc_id = target["id"]
        rfc_title = target["title"]
        
        logging.info(f"Cible locale identifiée : {rfc_id.upper()} ({rfc_title})")
        
        raw_text = self._fetch_local_rfc(rfc_id)
        if not raw_text:
             return {"status": "error", "message": f"Impossible de lire le fichier {rfc_id}.txt localement."}

        # Ingestion REELLE. Ce bloc etait un COMMENTAIRE jusqu'au 2026-07-31 : la
        # fonction comptait des sections et rendait "success" sans qu'aucun chunk
        # n'entre en base (mesure : 0 chunk source rfc:* pour les 9 RFC du rapport
        # AUDIT_RFC_COMPLIANCE du 16/06, qui annoncait 419 vecteurs).
        try:
            from nokido_agent.app.forge_ingest_pipeline import process_document, store_chunks
        except ImportError as exc:
            return {
                "status": "error",
                "rfc_id": rfc_id.upper(),
                "message": f"Primitive d'ingestion indisponible ({exc}) - RIEN n'a ete ingere.",
            }

        source = f"rfc:{rfc_id}"
        chunks = process_document(
            raw_text,
            source=source,
            domain_hint="reference",
            role_hint=f"reference:standards:{rfc_id}",
            author="rfc_ingest",
        )
        for chunk in chunks:
            chunk.meta.update({
                "trust_ring": "R1",
                "knowledge_circle": "reference",
                "verification": "canonical",
                "provenance": f"local_mirror:{rfc_id}.txt",
                "authenticity": "ietf_rfc",
                "rfc_id": rfc_id,
            })

        if not chunks:
            return {
                "status": "error",
                "rfc_id": rfc_id.upper(),
                "message": f"{rfc_id}.txt lu ({len(raw_text)} chars) mais 0 chunk produit.",
            }

        logging.info("%s : %d chunks prets, ecriture RAG...", rfc_id, len(chunks))
        try:
            store_chunks(chunks)
            logging.info("%s : ecriture RAG terminee.", rfc_id)
        except Exception as exc:
            # Etat ILLISIBLE distinct de l'echec metier : une ecriture refusee sur
            # embeddings.db (compte sandbox) ne doit JAMAIS se lire comme un succes.
            return {
                "status": "error",
                "rfc_id": rfc_id.upper(),
                "chunks_processed": len(chunks),
                "chunks_stored": 0,
                "message": (
                    f"Ecriture RAG refusee ({type(exc).__name__}: {str(exc)[:160]}). "
                    "embeddings.db exige le compte LaForgeTrusted (run action=trusted_script)."
                ),
            }

        return {
            "status": "success",
            "rfc_id": rfc_id.upper(),
            "rfc_title": rfc_title,
            "chunks_processed": len(chunks),
            "chunks_stored": len(chunks),
            "source": source,
            "summary": f"'{rfc_id.upper()}' lue depuis le miroir local et INGEREE en {len(chunks)} chunks (source={source}).",
        }

# Definition MCP pour l'enregistrement statique dans forge_mcp_registry.py
def get_mcp_definition() -> dict:
    return {
        "name": "absorb_rfc_knowledge",
        "description": "Recherche une norme IETF/RFC dans le miroir local Air-gapped (Zero-Latency), la découpe et l'ingère dans le RAG. À utiliser OBLIGATOIREMENT en cas de doute sur une spécification protocolaire ou réseau.",
        "parameters": {
            "type": "object",
            "properties": {
                "concept_query": {
                    "type": "string",
                    "description": "Le concept technique exact (ex: 'OAuth 2.0 Threat Model', 'IPv4 MTU')."
                }
            },
            "required": ["concept_query"]
        }
    }
