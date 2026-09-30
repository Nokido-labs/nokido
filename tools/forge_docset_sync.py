import os
import requests
import tarfile
import xml.etree.ElementTree as ET
import logging
import re
from typing import List, Set

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mapping : Fichier/Pattern détecté -> Nom du Docset Dash/Zeal
# Les noms sont ceux des FLUX kapeli (https://kapeli.com/feeds/<Nom>.xml), pas des
# etiquettes libres. Mesure 2026-07-31 : "Python_3" n'existe pas cote Dash -- le flux
# renvoie la page d'accueil HTML (ParseError), et l'echec etait avale en silence. Le
# docset s'appelle "Python" (3.14.6). Verifier un nom AVANT de l'ajouter ici.
TECH_MAPPING = {
    "requirements.txt": ["Python", "Requests", "Flask", "Django", "FastAPI"],
    "package.json": ["JavaScript", "NodeJS", "React", "TypeScript"],
    "Cargo.toml": ["Rust"],
    "go.mod": ["Go"],
    "Dockerfile": ["Docker"],
    "docker-compose.yml": ["Docker"],
    "pyproject.toml": ["Python", "NumPy", "Pandas", "PyTorch"],
    "Makefile": ["C", "C++"],
    "CMakeLists.txt": ["CMake", "C++"],
    ".tf": ["Terraform"],
}

# Mapping de mots-clés spécifiques trouvés DANS les fichiers
KEYWORD_MAPPING = {
    "numpy": "NumPy",
    "pandas": "Pandas",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "react": "React",
    "vue": "VueJS",
    "opencv": "OpenCV_Python",
    "sqlite": "SQLite",
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "scipy": "SciPy",
}

class DocsetAutoSync:
    def __init__(self, root_dir: str, dest_dir: str):
        self.root_dir = root_dir
        self.dest_dir = dest_dir
        self.feed_base_url = "https://kapeli.com/feeds"
        
        if not os.path.exists(self.dest_dir):
            os.makedirs(self.dest_dir, exist_ok=True)

    def detect_technologies(self) -> Set[str]:
        """Scanne le code source pour identifier les technologies."""
        detected = set()
        logging.info(f"Scan technologique du dépôt : {self.root_dir}")

        for root, dirs, files in os.walk(self.root_dir):
            # Ignorer les dossiers lourds ou inutiles
            if any(x in root for x in [".git", "node_modules", "__pycache__", "venv", "data"]):
                continue

            for file in files:
                # 1. Détection par nom de fichier
                if file in TECH_MAPPING:
                    for tech in TECH_MAPPING[file]:
                        detected.add(tech)
                
                # 2. Détection par contenu (pour les bibliothèques Python/JS)
                if file in ["requirements.txt", "package.json", "pyproject.toml"]:
                    try:
                        path = os.path.join(root, file)
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read().lower()
                            for kw, docset in KEYWORD_MAPPING.items():
                                if kw in content:
                                    detected.add(docset)
                    except Exception as exc:
                        # Un fichier illisible n'est pas un fichier sans dependance :
                        # le taire fait passer « je n'ai pas pu voir » pour « rien vu ».
                        logging.warning("Lecture impossible (%s) : %s", file, exc)
        
        # Ajouter systématiquement les bases si non détectées
        detected.add("Python")
        logging.info(f"Technologies détectées : {list(detected)}")
        return detected

    def get_download_url(self, docset_name: str) -> str:
        feed_url = f"{self.feed_base_url}/{docset_name}.xml"
        try:
            response = requests.get(feed_url, timeout=10)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            url_node = root.find(".//url")
            if url_node is None:
                logging.warning("Flux %s sans balise <url>.", feed_url)
                return None
            return url_node.text
        except Exception as exc:
            logging.warning("Flux %s injoignable : %s: %s", feed_url, type(exc).__name__, exc)
            return None

    def download_and_extract(self, docset_name: str):
        if os.path.exists(os.path.join(self.dest_dir, f"{docset_name}.docset")):
            logging.info(f"[i] Docset {docset_name} déjà présent.")
            return

        url = self.get_download_url(docset_name)
        if not url:
            logging.warning(f"[!] Impossible de trouver le flux pour {docset_name}")
            return

        target_path = os.path.join(self.dest_dir, f"{docset_name}.tgz")
        logging.info(f"Téléchargement de {docset_name}...")
        try:
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(target_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            with tarfile.open(target_path, "r:gz") as tar:
                tar.extractall(path=self.dest_dir)
            os.remove(target_path)
            logging.info(f"[+] {docset_name} installé.")
        except Exception as e:
            logging.error(f"Erreur pour {docset_name} : {e}")

    def sync(self):
        techs = self.detect_technologies()
        for tech in techs:
            self.download_and_extract(tech)

if __name__ == "__main__":
    # Dans Docker, root_dir est /app. Sur Windows, c'est le chemin actuel.
    import argparse

    ap = argparse.ArgumentParser(description="Synchronise les docsets Dash/Zeal.")
    ap.add_argument(
        "--only",
        default=None,
        help=(
            "Liste de docsets a telecharger, separes par des virgules "
            "(ex: Python_3,Requests,Flask). Defaut : detection automatique. "
            "Sert a borner le volume : le scan complet ramene ~26 docsets, "
            "dont ceux deja ingeres en RAG mais absents du disque."
        ),
    )
    args = ap.parse_args()

    # Le repo se derive de __file__, JAMAIS de os.getcwd() : sous trusted_script le
    # repertoire courant est le workspace du sandbox, et les docsets atterrissaient
    # dans sandbox/workspace/data/docsets (mesure 2026-07-31 : Python + Flask y ont
    # ete telecharges, invisibles de forge_docset_ingest qui lit LaForge/data/docsets).
    # Meme convention que forge_docset_ingest.DOCSETS_DIR -> les deux se rejoignent.
    _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.environ.get("LAFORGE_ROOT", _repo)
    dest = os.environ.get("LAFORGE_DOCSETS_DIR", os.path.join(_repo, "data", "docsets"))
    logging.info("repo=%s | destination docsets=%s", _repo, dest)

    sync = DocsetAutoSync(root_dir=root, dest_dir=dest)
    if args.only:
        cibles = [t.strip() for t in args.only.split(",") if t.strip()]
        logging.info("Telechargement cible : %s", cibles)
        for tech in cibles:
            sync.download_and_extract(tech)
    else:
        sync.sync()
