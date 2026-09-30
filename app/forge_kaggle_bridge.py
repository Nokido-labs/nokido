from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_kaggle_bridge
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_kaggle_bridge.py — Connecteur Kaggle Ring 5
======================================================
Câble le token KAGGLE_API_TOKEN du .env vers :
  - Recherche de datasets (API REST directe — Bearer KGAT_*)
  - Téléchargement vers rag_files/ pour ingestion RAG
  - Liste des compétitions actives
  - Ingestion auto dans forge_dataset_loader

Variables .env lues :
  KAGGLE_API_TOKEN=KGAT_*    → bearer token API v1
  RAG_DIR                    → dossier destination (défaut: data/rag_files)
  LAFORGE_ENV=dev            → pas de téléchargement réel en dev sans --force

SDK kaggle v2 aussi supporté via ~/.kaggle/kaggle.json (créé automatiquement).

Utilisation :
  from forge_kaggle_bridge import KaggleBridge, kaggle_status
  kb = KaggleBridge()
  results = kb.search_datasets("python code generation", max_results=10)
  kb.download_dataset("username/dataset-name", dest="rag_files/")
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
RAG_DIR = ROOT / "data" / "rag_files"
RAG_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────


def _token() -> str:
    """Token."""
    return get_secret("KAGGLE_API_TOKEN") or ""


def _is_dev() -> bool:
    """Is dev."""
    return (
        os.environ.get("LAFORGE_ENV", "prod").lower() == "dev"
        or os.environ.get("LAFORGE_MCP_DEV", "false").lower() == "true"
    )


def _headers() -> dict:
    """Headers."""
    return {
        "Authorization": "Bearer " + _token(),
        "Content-Type": "application/json",
    }


BASE_URL = "https://www.kaggle.com/api/v1"


# ── Client REST léger ─────────────────────────────────────────────────────────


def _get(endpoint: str, params: dict = None, timeout: int = 10) -> dict | list:
    """GET vers l'API Kaggle v1."""
    url = BASE_URL + endpoint
    if params:
        qs = "&".join(f"{k}={str(v).replace(' ', '+')}" for k, v in params.items())
        url += "?" + qs
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {body}")


# ── Bridge principal ──────────────────────────────────────────────────────────


class KaggleBridge:
    """
    Connecteur Kaggle pour Nokido.
    Utilise l'API REST directement — pas de dépendance au CLI kaggle.
    Fallback SDK si disponible.
    """

    def __init__(self) -> None:
        """Init."""
        self._token = _token()
        self._dev = _is_dev()
        self._sdk_ok = self._try_sdk_auth()

    def _try_sdk_auth(self) -> bool:
        """Tente d'authentifier le SDK kaggle — écrit kaggle.json si absent."""
        try:
            kaggle_cfg = Path.home() / ".kaggle" / "kaggle.json"
            if not kaggle_cfg.exists() and self._token:
                kaggle_cfg.parent.mkdir(exist_ok=True)
                kaggle_cfg.write_text(
                    json.dumps(
                        {
                            "username": "user",
                            "key": self._token,
                        }
                    )
                )
                os.chmod(str(kaggle_cfg), 0o600)
            from kaggle.api.kaggle_api_extended import KaggleApiExtended

            api = KaggleApiExtended()
            api.authenticate()
            self._sdk_api = api
            return True
        except Exception:
            self._sdk_api = None
            return False

    def is_available(self) -> bool:
        """Is available."""
        return bool(self._token)

    # ── Recherche ─────────────────────────────────────────────────────────────

    def search_datasets(
        self,
        query: str,
        max_results: int = 10,
        max_size_mb: int = 500,
        file_type: str = "",  # "csv"|"json"|"txt"|"" = tous
    ) -> list[dict]:
        """
        Recherche des datasets publics Kaggle.
        Filtre par taille et type de fichier.
        """
        if not self._token:
            return []
        try:
            params = {"search": query, "maxSize": max_results * 5}
            if file_type:
                params["fileType"] = file_type
            raw = _get("/datasets/list", params)
            results = []
            for d in raw:
                mb = (d.get("totalBytes") or 0) // 1024 // 1024
                if mb <= max_size_mb or max_size_mb == 0:
                    results.append(
                        {
                            "ref": d.get("ref", ""),
                            "title": d.get("title", ""),
                            "size_mb": mb,
                            "downloads": d.get("downloadCount", 0),
                            "votes": d.get("voteCount", 0),
                            "updated": d.get("lastUpdated", ""),
                            "usable": not d.get("isPrivate", True),
                        }
                    )
            return results[:max_results]
        except Exception as e:
            return [{"error": str(e)[:80]}]

    def search_competitions(self, query: str = "", category: str = "") -> list[dict]:
        """Liste les compétitions actives."""
        if not self._token:
            return []
        try:
            params = {}
            if query:
                params["search"] = query
            if category:
                params["category"] = category
            raw = _get("/competitions/list", params)
            return [
                {
                    "ref": d.get("ref", ""),
                    "title": d.get("title", ""),
                    "deadline": d.get("deadline", "")[:10],
                    "reward": d.get("reward", ""),
                    "teams": d.get("teamCount", 0),
                }
                for d in raw[:10]
            ]
        except Exception as e:
            return [{"error": str(e)[:80]}]

    # ── Téléchargement ────────────────────────────────────────────────────────

    def download_dataset(
        self,
        ref: str,  # "username/dataset-name"
        dest: str = "",
        unzip: bool = True,
        force: bool = False,
    ) -> dict:
        """
        Télécharge un dataset Kaggle dans dest/.
        En dev : retourne la commande sans exécuter (sauf force=True).
        Utilise le SDK si disponible, sinon kaggle CLI en DETACHED.
        """
        dest_path = Path(dest) if dest else RAG_DIR
        dest_path.mkdir(parents=True, exist_ok=True)

        if self._dev and not force:
            return {
                "ok": True,
                "action": "dev_skip",
                "cmd": f"kaggle datasets download {ref} -p {dest_path}",
                "message": "Dev mode — utiliser force=True pour télécharger réellement",
            }

        # Méthode 1 : SDK Python
        if self._sdk_ok and self._sdk_api:
            try:
                owner, name = ref.split("/", 1)
                self._sdk_api.dataset_download_files(
                    dataset=ref,
                    path=str(dest_path),
                    unzip=unzip,
                    quiet=False,
                )
                return {
                    "ok": True,
                    "ref": ref,
                    "dest": str(dest_path),
                    "method": "sdk",
                }
            except Exception as e:
                pass  # Fallback CLI

        # Méthode 2 : CLI kaggle en DETACHED
        DETACHED = 0x00000008
        cmd = [sys.executable, "-m", "kaggle", "datasets", "download", ref, "-p", str(dest_path)]
        if unzip:
            cmd.append("--unzip")

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED,
                env={**os.environ, "KAGGLE_KEY": self._token, "KAGGLE_USERNAME": "user"},
            )
            return {
                "ok": True,
                "ref": ref,
                "dest": str(dest_path),
                "method": "cli_detached",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def ingest_to_rag(self, ref: str, max_files: int = 20, domain: str = "kaggle") -> dict:
        """
        Télécharge un dataset et l'ingère dans le RAG principal.
        Filtre les fichiers .txt/.md/.py/.json.
        """
        dl = self.download_dataset(ref, force=not self._dev)
        if not dl.get("ok"):
            return dl

        # Trouver les fichiers textuels
        dest = Path(dl.get("dest", str(RAG_DIR)))
        text_files = []
        for ext in ("*.txt", "*.md", "*.py", "*.json", "*.csv"):
            text_files.extend(list(dest.rglob(ext))[:max_files])

        ingested = 0
        try:
            import sqlite3

            db = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            for f in text_files[:max_files]:
                try:
                    # 2026-09-12 : `[:3000]` a la LECTURE jetait la fin de chaque
                    # fichier, et l'INSERT n'avait pas de clef primaire.
                    text = f.read_text(errors="replace")
                    source = f"kaggle/{ref}/{f.name}"
                    from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

                    ecrire_chunk(conn, source, domain, text)
                    ingested += 1
                except Exception:
                    pass
            conn.commit()
            conn.close()
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}

        return {
            "ok": True,
            "ref": ref,
            "ingested": ingested,
            "domain": domain,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_bridge: Optional[KaggleBridge] = None


def get_bridge() -> KaggleBridge:
    """Get bridge."""
    global _bridge
    if _bridge is None:
        _bridge = KaggleBridge()
    return _bridge


def kaggle_status() -> dict:
    """Kaggle status."""
    b = get_bridge()
    return {
        "available": b.is_available(),
        "sdk_auth": b._sdk_ok,
        "dev_mode": _is_dev(),
        "token_prefix": _token()[:12] + "..." if _token() else "",
        "kaggle_json": str(Path.home() / ".kaggle" / "kaggle.json"),
        "kaggle_json_exists": (Path.home() / ".kaggle" / "kaggle.json").exists(),
    }
