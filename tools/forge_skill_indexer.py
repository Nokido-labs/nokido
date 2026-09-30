import os
import time
import json
import logging
import requests
import hashlib

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def _resolve_token() -> str:
    """Token du hub : coffre DPAPI d'abord, variables d'environnement ensuite.

    Un litteral en dur ici a ete bloque par le gate egress le 2026-07-22 ;
    ne jamais le reintroduire.
    """
    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        val = get_secret("FORGE_MCP_TOKEN")
        if val:
            return str(val)
    except Exception:  # noqa: BLE001 - le coffre est optionnel hors hub
        pass
    import os as _os

    return _os.environ.get("FORGE_MCP_TOKEN") or _os.environ.get("LAFORGE_MCP_TOKEN") or ""


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SkillIndexerDaemon:
    def __init__(self,
                 watch_dir: str = os.path.join(_ROOT, "sandbox", "skill_proposals"),
                 state_file: str = os.path.join(_ROOT, "sandbox", "skill_indexer_state.json"),
                 hub_url: str = "http://127.0.0.1:8766/mcp"):
        self.watch_dir = watch_dir
        self.state_file = state_file
        self.hub_url = hub_url
        self.token = _resolve_token()  # vault DPAPI puis env - jamais de litteral
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f)

    def _get_file_hash(self, filepath):
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _index_content(self, filename, content):
        logging.info(f"Indexation vectorielle de : {filename}")
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time()),
            "method": "tools/call",
            "params": {
                "name": "rag",
                "arguments": {
                    "action": "index",
                    "topic": "skill_proposals",
                    "result": content,
                    "task_id": f"auto_idx_{filename}"
                }
            }
        }
        try:
            r = requests.post(
                self.hub_url,
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30,
            )
            return r.status_code == 200
        except Exception as e:
            logging.error(f"Erreur d'indexation Hub : {e}")
            return False

    def run_once(self):
        if not os.path.exists(self.watch_dir):
            os.makedirs(self.watch_dir, exist_ok=True)
            return

        files = [f for f in os.listdir(self.watch_dir) if f.endswith(".md")]
        changed = False

        for f in files:
            path = os.path.join(self.watch_dir, f)
            current_hash = self._get_file_hash(path)

            if self.state.get(f) != current_hash:
                with open(path, 'r', encoding='utf-8', errors='ignore') as file:
                    content = file.read()
                    if self._index_content(f, content):
                        self.state[f] = current_hash
                        changed = True

        if changed:
            self._save_state()

    def loop(self):
        logging.info("Demon SkillIndexer active. Surveillance de sandbox/skill_proposals...")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logging.error(f"Erreur boucle : {e}")
            time.sleep(60)  # Verification toutes les minutes


if __name__ == "__main__":
    daemon = SkillIndexerDaemon()
    daemon.loop()
