
__FORGE_COLOR__ = "memoire/rag : lecteur de docsets"  # organe declare le 2026-09-06 (audit de raccordement)
import sqlite3
import os
import logging
from bs4 import BeautifulSoup
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DocsetReaderTool:
    def __init__(self, docsets_base_dir: str = None):
        """
        Initialise le lecteur en pointant vers le dossier contenant vos Docsets.
        """
        self.docsets_base_dir = docsets_base_dir or os.environ.get(
            "LAFORGE_DOCSETS_DIR", 
            # Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "docsets")
        )

    def extract_text_from_html(self, html_path: str, anchor: str = None) -> str:
        """Nettoie le HTML pour le rendre digeste pour un LLM."""
        try:
            with open(html_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
                
                # Cibler spécifiquement l'ancre HTML si elle existe
                if anchor:
                    target = soup.find(id=anchor) or soup.find(name="a", attrs={"name": anchor})
                    if target and target.parent:
                        return target.parent.get_text(separator='\n', strip=True)[:4000]
                
                # Sinon, texte principal
                return soup.get_text(separator='\n', strip=True)[:4000]
        except Exception as e:
            logging.error(f"Erreur de lecture HTML : {e}")
            return "Erreur lors de l'extraction du document."

    def query_documentation(self, docset_name: str, search_query: str) -> Dict[str, Any]:
        """La fonction appelée par l'agent IA via MCP."""
        if not os.path.exists(self.docsets_base_dir):
            os.makedirs(self.docsets_base_dir, exist_ok=True)
            
        docset_path = os.path.join(self.docsets_base_dir, f"{docset_name}.docset")
        db_path = os.path.join(docset_path, "Contents", "Resources", "docSet.dsidx")
        docs_dir = os.path.join(docset_path, "Contents", "Resources", "Documents")

        if not os.path.exists(db_path):
             return {"status": "error", "message": f"Docset '{docset_name}' introuvable dans le cold storage ({docset_path}). Téléchargez-le via Zeal ou Dash."}

        logging.info(f"Agent interroge le docset {docset_name} pour '{search_query}'...")

        try:
            # 1. Requête instantanée dans l'index SQLite
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT name, type, path FROM searchIndex WHERE name LIKE ? LIMIT 3", 
                (f"%{search_query}%",)
            )
            results = cursor.fetchall()
            conn.close()

            if not results:
                return {"status": "error", "message": f"Aucune définition trouvée pour '{search_query}' dans {docset_name}."}

            # 2. Exploitation du meilleur résultat
            best_match_name, match_type, rel_path = results[0]
            
            path_parts = rel_path.split('#')
            file_path = path_parts[0]
            anchor = path_parts[1] if len(path_parts) > 1 else None

            full_html_path = os.path.join(docs_dir, file_path)
            
            # 3. Extraction
            documentation_text = self.extract_text_from_html(full_html_path, anchor)

            return {
                "status": "success",
                "entity": best_match_name,
                "type": match_type,
                "documentation": documentation_text
            }

        except sqlite3.Error as e:
            logging.error(f"Erreur SQLite : {e}")
            return {"status": "error", "message": "Corruption de l'index du Docset."}

def get_mcp_definition() -> dict:
    return {
        "name": "query_documentation",
        "description": "Interroge la documentation officielle hors-ligne (Python_3, Docker, ONNX) pour obtenir la syntaxe exacte d'une fonction ou API. ZERO-LATENCY.",
        "parameters": {
            "type": "object",
            "properties": {
                "docset_name": {
                    "type": "string",
                    "description": "La technologie ciblée (ex: 'Python_3', 'Docker', 'ONNX')."
                },
                "search_query": {
                    "type": "string",
                    "description": "Le nom exact de la fonction, classe ou commande (ex: 'subprocess.run', 'docker run')."
                }
            },
            "required": ["docset_name", "search_query"]
        }
    }
