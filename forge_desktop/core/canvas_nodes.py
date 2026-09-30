"""
forge_desktop/core/canvas_nodes.py
====================================
CANVA_MASTER_ORCHESTRATOR — node definitions
GIT | RAG | LLM | CI — actions via OneMCP uniquement
Reactive_Streams_500ms
"""
from __future__ import annotations
import sys, json, time, threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

# ── Définition des node-types ─────────────────────────────────────────────────

NODE_CATALOG = {
    "GIT": {
        "icon":    "git",
        "color":   "#f44336",
        "actions": {
            "commit": {
                "label": "Commit",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@ci commit"},
                "desc": "Commit les fichiers stagés via CI guard",
            },
            "push": {
                "label": "Push",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@ci push"},
                "desc": "Push origin + codeberg",
            },
            "pull": {
                "label": "Pull",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@run git pull origin alpha"},
                "desc": "Pull depuis origin/alpha",
            },
            "fix_auth": {
                "label": "Fix auth",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@safety"},
                "desc": "Vérifie credentials + .gitignore",
            },
        },
    },
    "RAG": {
        "icon":    "db",
        "color":   "#4caf50",
        "actions": {
            "index": {
                "label": "Indexer",
                "mcp_tool": "rag_ingest_text",
                "args_template": {"text": "{input}", "source": "canvas"},
                "desc": "Indexe le texte dans BGE-M3",
            },
            "query": {
                "label": "Rechercher",
                "mcp_tool": "rag_search",
                "args_template": {"query": "{input}", "top_k": 5},
                "desc": "Recherche sémantique RAG",
            },
            "purge": {
                "label": "Purger",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@rag purge"},
                "desc": "Purge les embeddings obsolètes",
            },
        },
    },
    "LLM": {
        "icon":    "cpu",
        "color":   "#2196f3",
        "actions": {
            "generate": {
                "label": "Générer",
                "mcp_tool": "llm_generate",
                "args_template": {"prompt": "{input}", "agent_id": "{agent}"},
                "desc": "Génération LLM via provider sélectionné",
            },
            "debate": {
                "label": "Débat",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@collab {input}"},
                "desc": "Débat multi-agents",
            },
            "swap": {
                "label": "Swap provider",
                "mcp_tool": None,
                "args_template": {},
                "desc": "Changer le provider LLM dynamiquement",
            },
        },
        "providers": [
            "laforge", "llamacpp", "gemini", "groq_direct",
            "groq_70b", "deepseek_direct", "mistral_direct",
            "xai_grok", "nokido_mcp",
        ],
    },
    "CI": {
        "icon":    "shield",
        "color":   "#ff9800",
        "actions": {
            "pylint": {
                "label": "Pylint",
                "mcp_tool": "code_run_python",
                "args_template": {
                    "code": "import subprocess; r=subprocess.run(['python','-m','py_compile','{input}'],capture_output=True,encoding='utf-8'); print(r.stdout+r.stderr or 'OK')",
                    "timeout": 15,
                },
                "desc": "Vérifie la syntaxe AST",
            },
            "pytest": {
                "label": "Pytest",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@nr"},
                "desc": "Non-régression complète",
            },
            "security_scan": {
                "label": "Security scan",
                "mcp_tool": "nokido_dispatch",
                "args_template": {"command": "@safety"},
                "desc": "Scan secrets + .gitignore",
            },
        },
    },
}


# ── CanvasNodeRunner — exécute une action via Hub MCP ─────────────────────────

class CanvasNodeRunner:
    """
    Execute les actions des noeuds via Hub :8766/mcp (OneMCP).
    Jamais de subprocess direct.
    Reactive_Streams_500ms : émet des updates toutes les 500ms.
    """

    def __init__(self, on_update: Optional[Callable] = None):
        self._on_update = on_update
        self._token = self._load_token()

    def _load_token(self) -> str:
        try:
            import win32cred
            cred = win32cred.CredRead(
                "FORGE_MCP_TOKEN@Nokido",
                win32cred.CRED_TYPE_GENERIC
            )
            blob = cred.get("CredentialBlob", b"")
            return blob.decode("utf-16-le", "replace").rstrip("\x00") if blob else ""
        except Exception:
            return ""

    def _emit(self, node_id: str, status: str, output: str = "", ms: int = 0):
        if self._on_update:
            self._on_update({
                "id": node_id, "status": status,
                "output": output, "elapsed_ms": ms,
            })

    def run(self, node_id: str, node_type: str, action: str,
            input_text: str = "", agent: str = "laforge") -> dict:
        """
        Execute l'action via Hub MCP HTTP.
        Retourne {ok, output, elapsed_ms}.
        """
        node_def  = NODE_CATALOG.get(node_type, {})
        action_def= node_def.get("actions", {}).get(action)
        if not action_def:
            return {"ok": False, "output": f"Action inconnue: {action}"}

        mcp_tool = action_def.get("mcp_tool")
        if not mcp_tool:
            return {"ok": True, "output": "Action locale (swap)"}

        # Résoudre les templates
        args = {}
        for k, v in action_def.get("args_template", {}).items():
            if isinstance(v, str):
                v = v.replace("{input}", input_text[:500])
                v = v.replace("{agent}", agent)
            args[k] = v

        self._emit(node_id, "running")
        t0 = time.time()

        # Appel Hub MCP
        import urllib.request
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": mcp_tool, "arguments": args},
        }).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Forge-Authority": self._token,
            "Authorization": f"Bearer {self._token}",
        }

        # Retry 3x avec backoff
        result_data = {}
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    "http://localhost:8766/mcp",
                    data=payload, headers=headers, method="POST"
                )
                r = urllib.request.urlopen(req, timeout=10)
                result_data = json.loads(r.read())
                break
            except Exception as e:
                if attempt == 2:
                    result_data = {"error": str(e)}
                else:
                    time.sleep(0.2 * (2 ** attempt))

        elapsed = int((time.time() - t0) * 1000)
        ok  = "error" not in result_data
        out = str(result_data.get("result", result_data.get("error", "")))[:400]

        self._emit(node_id, "done" if ok else "failed", out, elapsed)

        # Audit trail
        self._audit(node_id, node_type, action, ok, elapsed)

        return {"ok": ok, "output": out, "elapsed_ms": elapsed}

    def run_async(self, node_id: str, node_type: str, action: str,
                  input_text: str = "", agent: str = "laforge"):
        """Lance run() dans un thread — non bloquant."""
        t = threading.Thread(
            target=self.run,
            args=(node_id, node_type, action, input_text, agent),
            daemon=True
        )
        t.start()
        return t

    def _audit(self, node_id, node_type, action, ok, elapsed_ms):
        try:
            import sqlite3, time as _t
            db = ROOT / "RAG" / "embeddings.db"
            conn = sqlite3.connect(str(db)); conn.execute("PRAGMA journal_mode=WAL")
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO event_log "
                "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_t.strftime("%Y-%m-%dT%H:%M:%S"), int(last)+1,
                 "canvas_node", "CLAUDE", "node_action",
                 f"{node_type}.{action}",
                 json.dumps({"node_id": node_id, "elapsed_ms": elapsed_ms}),
                 "ok" if ok else "err")
            )
            conn.commit(); conn.close()
        except Exception:
            pass


_runner = CanvasNodeRunner()


def get_runner(on_update: object | None = None) -> CanvasNodeRunner:
    if on_update:
        return CanvasNodeRunner(on_update)
    return _runner
