"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
app/forge_web_service.py — Façade Web Nokido
==============================================
Point d entrée unique pour la Web UI (Streamlit) vers les services Nokido.

Security by design :
  - Credentials lus depuis forge_settings / Nokido.env une seule fois au boot
  - Aucun credential ou path sensible ne remonte à la couche UI
  - Toutes les entrées utilisateur sont validées avant exécution SSH
  - Toutes les exceptions sont catchées et retournées sous forme de dict {ok, error}
  - SSH : commandes filtrées (blocklist), timeout imposé, sortie tronquée

Ce module est testable indépendamment de Streamlit.
Import depuis Streamlit : from forge_web_service import svc
"""

# =====================================================================
# AVERTISSEMENT AJOUTE LE 2026-09-19 — audit de la classe « injection de
# commande », avant publication du depot.
#
# CE MODULE N'A AUCUN IMPORTEUR. Mesure AST : 1884 fichiers de app/ et
# tools/ lus, 0 non parsable, zero import. C'est une facade Streamlit de
# mars 2026, restee en place. Elle EST publiee dans le dist : suivie par
# git, sans `export-ignore`, et non bloquee par les 66 motifs du profil
# public.
#
# CE QUE L'EN-TETE CI-DESSUS PROMET, ET QUE LE CODE NE TIENT PAS.
# « Toutes les entrees utilisateur sont validees » : `run_local(command)`
# et `workflow_run(name)` passent leur chaine a `subprocess.run(...,
# shell=True)`. Le seul garde est `_SSH_BLOCKLIST`, une liste NOIRE de
# douze motifs (rm -rf, mkfs, shutdown, passwd...).
#
# UNE LISTE NOIRE SUR DU SHELL N'EST PAS UNE SECURITE. La constitution
# semantique du 2026-09-05 le dit pour les agregats et cela vaut ici :
# on classe par liste BLANCHE, parce qu'une liste noire laisse passer
# tout ce qui n'a pas ete imagine. Sur un interpreteur de commandes,
# l'espace des formulations est infini — enchainements, substitutions,
# encodages — et la blocklist ne couvre meme pas la lecture de fichiers
# ni l'exfiltration.
#
# CE MODULE EST GELE, PAS SUPPRIME. Si un jour on veut cette capacite :
# repartir d'une liste BLANCHE de commandes nommees, sans `shell=True`,
# avec des arguments passes en LISTE. Et non pas etendre la blocklist.
#
# `tests/nr/test_facade_web_service_gelee_nr.py` echoue si ce module
# acquiert un importeur : ce serait un elargissement de la surface
# d'execution, a decider explicitement.
# =====================================================================

import os, json, sqlite3, re
from pathlib import Path
from typing import Optional
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
APP = Path(__file__).resolve().parent

# ── SSH blocklist — commandes interdites depuis la Web UI ─────────────────────
_SSH_BLOCKLIST = re.compile(
    r"(rm\s+-rf|mkfs|dd\s+if=|shutdown|reboot|halt|poweroff"
    r"|passwd|visudo|chmod\s+777|>\s*/etc|curl\s.*\|\s*sh"
    r"|wget\s.*\|\s*sh|base64\s+-d\s.*\|\s*sh)",
    re.IGNORECASE,
)


# ── Config chargée une seule fois ─────────────────────────────────────────────
class _Config:
    """Singleton configuration — lue depuis forge_settings au premier accès."""

    _instance: Optional["_Config"] = None
    _loaded = False

    def __new__(cls) -> object:
        """new  ."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load(self) -> None:
        """load."""
        if self._loaded:
            return
        self._loaded = True
        env_path = ROOT / "Nokido.env"
        self._raw: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    self._raw[k.strip()] = v.strip()

    def get(self, key: str, default: str = "") -> str:
        """Get."""
        self._load()
        return self._raw.get(key, default)

    @property
    def ssh_host(self) -> str:
        """Ssh host."""
        return self.get("SSH_HOST")

    @property
    def ssh_user(self) -> str:
        """Ssh user."""
        return self.get("SSH_USER", "root")

    @property
    def ssh_port(self) -> int:
        """Ssh port."""
        try:
            return int(self.get("SSH_PORT", "22"))
        except ValueError:
            return 22

    @property
    def ssh_key_path(self) -> str:
        """Ssh key path."""
        return self.get("PRIVATE_KEY_PATH")

    @property
    def hub_url(self) -> str:
        """Hub url."""
        return self.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")

    @property
    def llamacpp_model_path(self) -> str:
        """Llamacpp model path."""
        return self.get("LLAMACPP_MODEL_PATH")

    @property
    def ollama_model(self) -> str:
        """Ollama model."""
        return self.get("OLLAMA_MODEL_DEFAULT", "qwen2.5-coder:latest")


cfg = _Config()


# ── Hub ───────────────────────────────────────────────────────────────────────


# Context:


def hub_health() -> dict[str, object]:
    """GET /health depuis le Hub Nokido.

    Sends a GET request to ``cfg.hub_url + "/health"`` with a 3second timeout.
    On success returns the decoded JSON payload as a dictionary.
    On any error returns a dictionary with ``"status": "error"`` and a truncated
    error message under the ``"error"`` key.
    """
    try:
        with urllib.request.urlopen(cfg.hub_url + "/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status": "error", "error": str(e)[:80]}


def hub_metrics() -> dict:
    """GET /metrics depuis le Hub Nokido."""
    try:
        with urllib.request.urlopen(cfg.hub_url + "/metrics", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:80]}


def hub_live_bridge_json() -> dict:
    """Snapshot du live_bridge (état RT : LLM, agents, tasks)."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.live_bridge import bridge

        snap = bridge.snapshot()
        return snap.get("json", {})
    except Exception:
        return {}


def hub_live_tasks() -> list:
    """Tasks récentes depuis le live_bridge."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.live_bridge import bridge

        return bridge.snapshot().get("tasks", [])
    except Exception:
        return []


# ── RAG ───────────────────────────────────────────────────────────────────────


def rag_db_stats() -> dict:
    """Stats RAG depuis la DB SQLite (chunks, domaines, fichiers récents)."""
    try:
        db = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(db))
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        doms = conn.execute(
            "SELECT domain, COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        recent = conn.execute("SELECT path FROM file_index ORDER BY updated_at DESC LIMIT 8").fetchall()
        conn.close()
        return {
            "total": total,
            "domains": {d: c for d, c in doms},
            "recent": [r[0] for r in recent],
        }
    except Exception as e:
        return {"error": str(e)[:80]}


def rag_search(query: str, top_k: int = 8) -> list[dict]:
    """
    Recherche sémantique NPU DML sur la base RAG.
    Retourne une liste de {score, file, source, domain, text}.
    Entrée validée : query tronquée à 512 chars.
    """
    query = str(query).strip()[:512]
    if not query:
        return []
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_npu_embedder import NPUEmbedder

        emb = NPUEmbedder()
        hits = emb.search_db(query, top_k=min(int(top_k), 20))
        if not hits:
            return []
        db = ROOT / "RAG" / "embeddings.db"
        conn = sqlite3.connect(str(db))
        # `source` (relatif/#chunk) n'a pas de prefixe commun avec file_path (absolu)
        # -> le pont reste le basename, non-indexable (idx_rag_source ne mord pas sur
        # `%fname%`). Mais on remplace jusqu'a 20 full-scans (un LIKE/hit, 1.17M lignes
        # chacun) par UNE seule passe OR : ~20x moins de scans, memes lignes.
        fnames = [Path(h["file_path"]).name for h in hits]
        uniq = list(dict.fromkeys(fnames))  # dedup, ordre preserve
        found: dict = {}
        if uniq:
            clauses = " OR ".join(["source LIKE ?"] * len(uniq))
            params = ["%" + f + "%" for f in uniq]
            for txt, src, dom in conn.execute(
                f"SELECT text, source, domain FROM rag_chunks WHERE {clauses}", params
            ):
                s = src or ""
                for f in uniq:
                    if f not in found and f in s:
                        found[f] = (txt, src, dom)
                if len(found) == len(uniq):
                    break  # tous les basenames resolus -> stop
        results = []
        for h in hits:
            fp = h["file_path"]
            score = h["score"]
            row = found.get(Path(fp).name)
            results.append(
                {
                    "score": round(score, 4),
                    "file": fp,
                    "source": row[1] if row else fp,
                    "domain": row[2] if row else "?",
                    "text": (row[0][:300] if row else "(non disponible)"),
                }
            )
        conn.close()
        return results
    except Exception as e:
        return [{"score": 0, "file": "ERROR", "source": str(e)[:120], "domain": "?", "text": ""}]


def rag_reindex(changed_only: bool = True) -> dict:
    """Lance index_app_dir(). Retourne les stats ou {ok:False, error:...}."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_rag_index_app import index_app_dir

        return index_app_dir(changed_only=changed_only, verbose=False)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def rag_warmup() -> dict:
    """Déclenche rag_warmup_spawn(). Retourne {task_id} ou {error}."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_rag_warmup import rag_warmup_spawn

        tid = rag_warmup_spawn()
        return {"task_id": tid}
    except Exception as e:
        return {"error": str(e)[:120]}


# ── SSH ───────────────────────────────────────────────────────────────────────


def ssh_status() -> dict:
    """Retourne la config SSH (hôte/user seulement — pas la clé privée)."""
    return {
        "host": cfg.ssh_host,
        "user": cfg.ssh_user,
        "port": cfg.ssh_port,
        "key_exists": os.path.exists(cfg.ssh_key_path) if cfg.ssh_key_path else False,
        "configured": bool(cfg.ssh_host),
    }


def ssh_exec(command: str, timeout: int = 15) -> dict:
    """
    Exécute une commande SSH sur l hôte configuré.
    Security :
      - commande validée contre _SSH_BLOCKLIST
      - timeout imposé (max 60s)
      - sortie tronquée à 4000 chars
      - credentials jamais retournés
    """
    command = str(command).strip()
    if not command:
        return {"ok": False, "error": "Commande vide"}
    if _SSH_BLOCKLIST.search(command):
        return {"ok": False, "error": "Commande refusée (sécurité)"}
    timeout = max(5, min(int(timeout), 60))

    try:
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pkey = None
        if cfg.ssh_key_path and os.path.exists(cfg.ssh_key_path):
            try:
                pkey = paramiko.RSAKey.from_private_key_file(cfg.ssh_key_path)
            except Exception:
                pkey = paramiko.Ed25519Key.from_private_key_file(cfg.ssh_key_path)
        client.connect(
            hostname=cfg.ssh_host,
            username=cfg.ssh_user,
            port=cfg.ssh_port,
            pkey=pkey,
            timeout=10,
            allow_agent=True,
            look_for_keys=False,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode(errors="replace")[:4000]
        err = stderr.read().decode(errors="replace")[:500]
        client.close()
        return {"ok": True, "stdout": out, "stderr": err}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def ssh_ping() -> dict:
    """Test SSH rapide (echo + uname)."""
    return ssh_exec("echo PONG && uname -sr && uptime -p", timeout=8)


# ── Modèles & mémoire ─────────────────────────────────────────────────────────


def model_info() -> dict:
    """Infos sur les modèles disponibles et le backend actif."""
    info: dict = {}
    info["llamacpp_model_path"] = cfg.llamacpp_model_path
    info["ollama_model"] = cfg.ollama_model
    info["onnx_path"] = cfg.get("ONNXGENAI_MODEL_PATH")
    # GGUF dispos dans le cache HF
    hf_cache = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface")))
    gguf_files = list(hf_cache.rglob("*.gguf")) + list((ROOT / "models").rglob("*.gguf"))
    info["available_gguf"] = [
        {"name": f.name, "size_mb": f.stat().st_size // (1024 * 1024), "path": str(f)} for f in gguf_files
    ]
    # Bridge llama.cpp
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_llamacpp import LlamaCppBridge

        b = LlamaCppBridge()
        info["vulkan_available"] = b.is_available()
        info["current_model"] = getattr(b, "model_name", "?")
    except Exception as e:
        info["vulkan_available"] = None
        info["bridge_error"] = str(e)[:80]
    # LLM status live
    lb = hub_live_bridge_json()
    info["llm_status"] = lb.get("llm.status", "idle")
    info["llm_backend"] = lb.get("llm.backend", "?")
    info["llm_dur_ms"] = lb.get("llm.dur_ms", None)
    return info


def mem_info() -> dict:
    """Usage RAM système (Windows)."""
    result: dict = {}
    try:
        import ctypes

        class _MEM(ctypes.Structure):
            """mem."""

            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = _MEM()
        ms.dwLength = ctypes.sizeof(ms)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        result["ram_total_gb"] = round(ms.ullTotalPhys / 1024**3, 1)
        result["ram_avail_gb"] = round(ms.ullAvailPhys / 1024**3, 1)
        result["ram_load_pct"] = ms.dwMemoryLoad
    except Exception as e:
        result["ram_error"] = str(e)[:80]
    return result


# ── Workflows ─────────────────────────────────────────────────────────────────


def _bs_path() -> Path:
    """bs path."""
    return ROOT / "sandbox" / "bridge_state.json"


def workflow_list() -> dict:
    """Charge les workflows depuis bridge_state.json."""
    try:
        bs = _bs_path()
        if bs.exists():
            data = json.loads(bs.read_text(encoding="utf-8"))
            return data.get("custom_workflows", data.get("workflows", {}))
        return {}
    except Exception:
        return {}


def workflow_save(name: str, steps: list[str]) -> dict:
    """Crée ou met à jour un workflow. Validation : nom alphanumérique."""
    name = re.sub(r"[^a-zA-Z0-9_\-]", "", name.strip())[:40]
    if not name:
        return {"ok": False, "error": "Nom invalide"}
    steps = [str(s).strip() for s in steps if str(s).strip()][:20]
    if not steps:
        return {"ok": False, "error": "Étapes vides"}
    try:
        bs = _bs_path()
        data = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        wfs = data.get("custom_workflows", {})
        wfs[name] = steps
        data["custom_workflows"] = wfs
        bs.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "name": name, "steps": len(steps)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def workflow_delete(name: str) -> dict:
    """Supprime un workflow."""
    try:
        bs = _bs_path()
        data = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        wfs = data.get("custom_workflows", {})
        if name not in wfs:
            return {"ok": False, "error": f"'{name}' introuvable"}
        del wfs[name]
        data["custom_workflows"] = wfs
        bs.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def workflow_run(name: str) -> list[dict]:
    """
    Exécute les étapes d un workflow local.
    Chaque étape est validée contre le blocklist SSH avant exécution locale.
    Retourne une liste de {step, ok, stdout, stderr}.
    """
    import subprocess

    wfs = workflow_list()
    if name not in wfs:
        return [{"step": name, "ok": False, "stdout": "", "stderr": f"Workflow '{name}' inconnu"}]
    results = []
    for step in wfs[name]:
        step = str(step).strip()
        if _SSH_BLOCKLIST.search(step):
            results.append({"step": step, "ok": False, "stdout": "", "stderr": "Commande refusée (sécurité)"})
            continue
        try:
            r = subprocess.run(step, shell=True, capture_output=True, text=True, timeout=30, cwd=str(ROOT), errors="replace")
            results.append(
                {
                    "step": step,
                    "ok": r.returncode == 0,
                    "stdout": r.stdout[:500],
                    "stderr": r.stderr[:200],
                }
            )
        except subprocess.TimeoutExpired:
            results.append({"step": step, "ok": False, "stdout": "", "stderr": "Timeout"})
        except Exception as e:
            results.append({"step": step, "ok": False, "stdout": "", "stderr": str(e)[:100]})
    return results


# ── Loop / Evolve / Collab / Estim ───────────────────────────────────────────


def loop_status() -> dict:
    """État de la boucle d amélioration autonome."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        # Lire depuis bridge_state + live_bridge
        bs = ROOT / "sandbox" / "bridge_state.json"
        state = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        loop_info = state.get("loop", {})
        # Chercher aussi dans sandbox/loop_state.json
        ls = ROOT / "sandbox" / "loop_state.json"
        if ls.exists():
            loop_info.update(json.loads(ls.read_text(encoding="utf-8")))
        # Lire les versions git
        import subprocess

        branches = []
        try:
            r = subprocess.run(
                ["git", "branch", "--list", "B[123]*"], capture_output=True, text=True, timeout=5, cwd=str(ROOT)
            , errors="replace")
            branches = [b.strip().lstrip("* ") for b in r.stdout.splitlines() if b.strip()]
        except Exception:
            pass
        return {
            "ok": True,
            "active": loop_info.get("active", False),
            "phase": loop_info.get("phase", "idle"),
            "cycle": loop_info.get("cycle", 0),
            "last_run": loop_info.get("last_run", ""),
            "branches": branches,
            "raw": loop_info,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def loop_start(branch: str = "B1") -> dict:
    """Démarre la boucle d amélioration sur la branche donnée."""
    branch = re.sub(r"[^a-zA-Z0-9_\-]", "", branch.strip())[:20] or "B1"
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_runner import spawn

        code = (
            "import sys; sys.path.insert(0, r'" + str(APP) + "')\n"
            "from forge_loop import post_loop_safe_check\n"
            "import asyncio\n"
            "print('loop started branch=" + branch + "')\n"
        )
        tid = spawn(code, task_id="loop_" + branch)
        # Marquer dans bridge_state
        bs = ROOT / "sandbox" / "bridge_state.json"
        data = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        data["loop"] = {"active": True, "phase": "starting", "branch": branch, "cycle": 0}
        bs.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "task_id": tid, "branch": branch}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def loop_stop() -> dict:
    """Arrête la boucle (marque inactive dans bridge_state)."""
    try:
        bs = ROOT / "sandbox" / "bridge_state.json"
        data = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        data["loop"] = {"active": False, "phase": "stopped", "cycle": data.get("loop", {}).get("cycle", 0)}
        bs.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def evolve_run(query: str) -> dict:
    """
    Lance un cycle d auto-évolution RAG sur la query donnée.
    Utilise forge_runner.spawn (DETACHED) pour ne pas bloquer.
    """
    query = str(query).strip()[:512]
    if not query:
        return {"ok": False, "error": "Query vide"}
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_runner import spawn

        code = (
            "import sys\n"
            "sys.path.insert(0, r'" + str(APP) + "')\n"
            "query = " + repr(query) + "\n"
            "try:\n"
            "    from forge_rag_index_app import index_app_dir\n"
            "    stats = index_app_dir(changed_only=False, verbose=False)\n"
            "    with open(r'" + str(ROOT / "sandbox" / "evolve_last.json") + "', 'w') as f:\n"
            "        import json; json.dump({'query': query, 'stats': stats, 'ok': True}, f, indent=2)\n"
            "except Exception as e:\n"
            "    with open(r'" + str(ROOT / "sandbox" / "evolve_last.json") + "', 'w') as f:\n"
            "        import json; json.dump({'query': query, 'ok': False, 'error': str(e)}, f)\n"
        )
        tid = spawn(code, task_id="evolve_" + query[:16].replace(" ", "_"))
        return {"ok": True, "task_id": tid, "query": query}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def evolve_status() -> dict:
    """Résultat du dernier cycle evolve."""
    try:
        p = ROOT / "sandbox" / "evolve_last.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"ok": False, "error": "Aucun run evolve"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def collab_status() -> dict:
    """État du mode collab (bridge_state.json)."""
    try:
        bs = ROOT / "sandbox" / "bridge_state.json"
        state = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        return {
            "ok": True,
            "active_mode": state.get("active_mode", "AUTO"),
            "agents": state.get("agents", {}),
            "permissions": state.get("permissions", {}),
            "tasks_count": len(state.get("tasks", [])),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def collab_set_mode(mode: str) -> dict:
    """Change le mode de collaboration (AUTO/CLINE/CHEF/DEBAT/PING)."""
    valid = {"AUTO", "CLINE", "CHEF", "DEBAT", "PING", "CHAT"}
    mode = mode.upper().strip()
    if mode not in valid:
        return {"ok": False, "error": f"Mode invalide. Valides : {valid}"}
    try:
        bs = ROOT / "sandbox" / "bridge_state.json"
        state = json.loads(bs.read_text(encoding="utf-8")) if bs.exists() else {}
        state["active_mode"] = mode
        bs.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "mode": mode}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def estim_run(description: str) -> dict:
    """
    Lance une estimation/génération de code via llama.cpp (DETACHED).
    Stocke le résultat dans sandbox/estim_last.json.
    """
    description = str(description).strip()[:1000]
    if not description:
        return {"ok": False, "error": "Description vide"}
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_runner import spawn

        code = (
            "import sys, json\n"
            "sys.path.insert(0, r'" + str(APP) + "')\n"
            "desc = " + repr(description) + "\n"
            "out  = r'" + str(ROOT / "sandbox" / "estim_last.json") + "'\n"
            "try:\n"
            "    from ai_service import stream_response\n"
            "    msgs = [{'role':'user','content': 'Génère le code pour : ' + desc}]\n"
            "    result = ''.join(stream_response(msgs, mode='code', use_rag=False))\n"
            "    with open(out, 'w', encoding='utf-8') as f:\n"
            "        json.dump({'ok': True, 'description': desc, 'result': result[:3000]}, f, indent=2, ensure_ascii=False)\n"
            "except Exception as e:\n"
            "    with open(out, 'w', encoding='utf-8') as f:\n"
            "        json.dump({'ok': False, 'description': desc, 'error': str(e)}, f)\n"
        )
        tid = spawn(code, task_id="estim_" + description[:16].replace(" ", "_"))
        return {"ok": True, "task_id": tid}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def estim_status() -> dict:
    """Résultat de la dernière estimation."""
    try:
        p = ROOT / "sandbox" / "estim_last.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"ok": False, "error": "Aucun run estim"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def agents_tasks_list() -> list:
    """Tasks Cline depuis bridge_state.json + tasks.json."""
    try:
        tasks_path = ROOT / "sandbox" / "tasks.json"
        bs_path = ROOT / "sandbox" / "bridge_state.json"
        tasks = []
        if tasks_path.exists():
            data = json.loads(tasks_path.read_text(encoding="utf-8"))
            tasks = data.get("pending", data if isinstance(data, list) else [])
        if bs_path.exists():
            state = json.loads(bs_path.read_text(encoding="utf-8"))
            tasks += state.get("tasks", [])
        return tasks[:50]
    except Exception as e:
        return [{"error": str(e)[:80]}]


# ── CI / CD ───────────────────────────────────────────────────────────────────


def ci_run(repo: str, branch: str = "main", directory: str = "") -> dict:
    """Lance un pipeline CI via SSH : git pull + lint + test."""
    repo = str(repo).strip()[:200]
    branch = re.sub(r"[^a-zA-Z0-9_/\-.]", "", branch.strip())[:50] or "main"
    directory = str(directory).strip()[:200]
    if not repo:
        return {"ok": False, "error": "Repo vide"}
    workdir = directory if directory else ("~/" + repo.rstrip("/").split("/")[-1])
    cmd = (
        f"cd {workdir} && "
        f"git fetch origin && git checkout {branch} && git pull origin {branch} && "
        f"echo '--- LINT ---' && (flake8 . --max-line-length=120 2>&1 || true) && "
        f"echo '--- TESTS ---' && (python -m pytest --tb=short -q 2>&1 || true) && "
        f"echo 'CI DONE'"
    )
    result = ssh_exec(cmd, timeout=60)
    result["repo"] = repo
    result["branch"] = branch
    return result


def ci_status() -> dict:
    """Lit l historique CI depuis sandbox/ci_history.json."""
    try:
        p = ROOT / "sandbox" / "ci_history.json"
        if p.exists():
            return {"ok": True, "history": json.loads(p.read_text(encoding="utf-8"))}
        return {"ok": True, "history": []}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def ci_lint(directory: str = ".") -> dict:
    """Lance flake8/eslint sur un dossier SSH."""
    directory = str(directory).strip()[:200] or "."
    cmd = f"cd {directory} && flake8 . --max-line-length=120 --statistics 2>&1 | head -50"
    return ssh_exec(cmd, timeout=30)


def ci_diff(repo: str = ".") -> dict:
    """Git diff résumé du dernier commit."""
    repo = str(repo).strip()[:200] or "."
    cmd = f"cd ~/{repo.split('/')[-1]} && git log --oneline -5 && echo '---' && git diff HEAD~1 --stat"
    return ssh_exec(cmd, timeout=15)


# ── Run / Apply (code local) ───────────────────────────────────────────────────


def run_local(command: str, timeout: int = 30) -> dict:
    """
    Exécute une commande shell locale (sur la machine Nokido).
    Security : même blocklist que SSH.
    """
    command = str(command).strip()
    if not command:
        return {"ok": False, "error": "Commande vide"}
    if _SSH_BLOCKLIST.search(command):
        return {"ok": False, "error": "Commande refusée (sécurité)"}
    timeout = max(5, min(int(timeout), 120))
    try:
        import subprocess

        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT), errors="replace")
        return {
            "ok": True,
            "stdout": r.stdout[:3000],
            "stderr": r.stderr[:500],
            "rc": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def apply_patch(patch_text: str, target_file: str) -> dict:
    """
    Applique un patch texte sur un fichier local via str_replace ou écriture directe.
    Security : target_file doit être dans ROOT.
    """
    target = Path(target_file)
    if not target.is_absolute():
        target = ROOT / target_file
    # Vérifier que le fichier est dans ROOT
    try:
        target.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return {"ok": False, "error": "Fichier hors du projet (sécurité)"}
    if not target.exists():
        return {"ok": False, "error": f"Fichier introuvable : {target}"}
    try:
        import py_compile

        py_compile.compile(str(target), doraise=True)
        old_content = target.read_text(encoding="utf-8")
        # Écrire le patch
        target.write_text(patch_text, encoding="utf-8")
        # Valider la syntaxe
        try:
            py_compile.compile(str(target), doraise=True)
        except Exception as e:
            # Rollback
            target.write_text(old_content, encoding="utf-8")
            return {"ok": False, "error": f"Syntaxe invalide — rollback : {e}"}
        return {"ok": True, "file": str(target)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Web search ────────────────────────────────────────────────────────────────


def web_search_status() -> dict:
    """État de la recherche web (Nokido.env LAFORGE_WEB_SEARCH)."""
    enabled = cfg.get("LAFORGE_WEB_SEARCH", "false").lower() in ("true", "1", "yes")
    return {"ok": True, "enabled": enabled}


def web_search_toggle(enable: bool) -> dict:
    """Active ou désactive la recherche web dans Nokido.env."""
    try:
        env_path = ROOT / "Nokido.env"
        content = env_path.read_text(encoding="utf-8")
        val = "true" if enable else "false"
        if "LAFORGE_WEB_SEARCH=" in content:
            content = re.sub(r"LAFORGE_WEB_SEARCH=\S+", f"LAFORGE_WEB_SEARCH={val}", content)
        else:
            content += "\nLAFORGE_WEB_SEARCH=" + val + "\n"
        env_path.write_text(content, encoding="utf-8")
        # Mettre à jour os.environ
        import os as _os

        _os.environ["LAFORGE_WEB_SEARCH"] = val
        return {"ok": True, "enabled": enable}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ── Proxy SOCKS5 ──────────────────────────────────────────────────────────────


def proxy_status() -> dict:
    """Vérifie si un tunnel SOCKS5 est actif sur le port configuré."""
    try:
        import subprocess

        port = int(cfg.get("PROXY_PORT", "1080"))
        r = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, timeout=5, encoding="cp850", errors="replace")
        lines = [l for l in r.stdout.splitlines() if f":{port} " in l]
        active = any("LISTENING" in l or "ESTABLISHED" in l for l in lines)
        return {"ok": True, "active": active, "port": port, "lines": lines[:3]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def proxy_start() -> dict:
    """Démarre un tunnel SSH SOCKS5."""
    try:
        port = int(cfg.get("PROXY_PORT", "1080"))
        import subprocess

        key_args = (
            ["-i", cfg.ssh_key_path] if cfg.ssh_key_path and __import__("os").path.exists(cfg.ssh_key_path) else []
        )
        cmd = (
            ["ssh", "-D", str(port), "-N", "-f", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=30"]
            + key_args
            + [f"{cfg.ssh_user}@{cfg.ssh_host}", "-p", str(cfg.ssh_port)]
        )
        subprocess.Popen(cmd)
        return {"ok": True, "port": port, "host": cfg.ssh_host}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def proxy_stop() -> dict:
    """Stoppe le tunnel SSH SOCKS5 actif."""
    try:
        import subprocess

        port = int(cfg.get("PROXY_PORT", "1080"))
        r = subprocess.run(["netstat", "-aon"], capture_output=True, text=True, timeout=5, encoding="cp850", errors="replace")
        import re as _re

        pids = _re.findall(r"TCP\s+\S+:" + str(port) + r"\s+\S+\s+LISTENING\s+(\d+)", r.stdout)
        for pid in set(pids):
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
        return {"ok": True, "stopped_pids": list(set(pids))}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# ── Audit ─────────────────────────────────────────────────────────────────────


def audit_run() -> dict:
    """Lance un audit rapide du projet : py_compile sur les fichiers core."""
    import py_compile as _pyc

    results = []
    files_to_check = list((ROOT / "app").glob("forge_*.py")) + [
        ROOT / "streamlit_ui" / "chat_service.py",
        ROOT / "app" / "forge_web_service.py",
    ]
    for f in files_to_check[:30]:
        try:
            _pyc.compile(str(f), doraise=True)
            results.append({"file": f.name, "ok": True})
        except _pyc.PyCompileError as e:
            results.append({"file": f.name, "ok": False, "error": str(e)[:80]})
    fails = [r for r in results if not r["ok"]]
    return {
        "ok": len(fails) == 0,
        "total": len(results),
        "fails": fails,
        "pass": len(results) - len(fails),
    }


# ── Services ─────────────────────────────────────────────────────────────────


def services_status() -> dict:
    """État de tous les services Nokido (Hub, Streamlit, MCP, Brain)."""
    import subprocess

    services = {}
    for svc_name in ["NokidoHub", "NokidoStreamlit", "NokidoMCP"]:
        try:
            r = subprocess.run(["sc", "query", svc_name], capture_output=True, text=True, timeout=5, errors="replace")
            state_line = next((l.strip() for l in r.stdout.splitlines() if "STATE" in l), "")
            running = "RUNNING" in state_line
            services[svc_name] = {"running": running, "state": state_line}
        except Exception as e:
            services[svc_name] = {"running": False, "error": str(e)[:60]}
    # Hub HTTP
    services["Hub_HTTP"] = {"running": hub_health().get("status") == "ok"}
    return {"ok": True, "services": services}


# ── Scan réseau ───────────────────────────────────────────────────────────────


def scan_network(target: str = "localhost/24", ports: str = "22,80,443,8080") -> dict:
    """
    Scan réseau basique via socket (sans Scapy).
    Security : uniquement RFC1918 (192.168.x.x, 10.x.x.x, 172.16-31.x.x).
    """
    # Valider que la target est un réseau privé
    target = str(target).strip()
    if not re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)", target):
        return {"ok": False, "error": "Scan limité aux réseaux privés RFC1918"}
    try:
        import socket, concurrent.futures

        port_list = [int(p.strip()) for p in ports.split(",") if p.strip().isdigit()][:10]
        # Générer la liste d'IPs (subnet /24 uniquement)
        base_ip = target.split("/")[0].rsplit(".", 1)[0]
        ips = [f"{base_ip}.{i}" for i in range(1, 255)]

        def check_port(ip, port) -> tuple:
            """Check port."""
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.3)
                r = s.connect_ex((ip, port))
                s.close()
                return (ip, port, r == 0)
            except Exception:
                return (ip, port, False)

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
            futures = [ex.submit(check_port, ip, p) for ip in ips for p in port_list]
            for f in concurrent.futures.as_completed(futures, timeout=15):
                ip, port, open_ = f.result()
                if open_:
                    results.append({"ip": ip, "port": port})

        return {"ok": True, "target": target, "open": sorted(results, key=lambda x: x["ip"]), "count": len(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Agentic / Disco ───────────────────────────────────────────────────────────


def disco_search(query: str) -> dict:
    """Recherche unifiée : RAG + web si activé."""
    query = str(query).strip()[:512]
    if not query:
        return {"ok": False, "error": "Query vide"}
    results = {"rag": [], "web_enabled": web_search_status().get("enabled", False)}
    # RAG search
    results["rag"] = rag_search(query, top_k=5)
    return {"ok": True, "query": query, **results}


def tools_list() -> dict:
    """Liste les outils / commandes disponibles dans forge_web_service."""
    import inspect, sys

    current_module = sys.modules.get("forge_web_service")
    if current_module is None:
        # Importer dynamiquement
        import importlib.util

        spec = importlib.util.spec_from_file_location("forge_web_service", __file__)
        current_module = importlib.util.module_from_spec(spec)
    fns = [name for name, obj in inspect.getmembers(current_module, inspect.isfunction) if not name.startswith("_")]
    return {"ok": True, "count": len(fns), "tools": sorted(fns)}


def ragas_eval(question: str, answer: str, context: str = "") -> dict:
    """
    Évaluation RAGAS simplifiée : score de pertinence answer/context via embed cosine.
    """
    if not question or not answer:
        return {"ok": False, "error": "question et answer requis"}
    try:
        import sys, numpy as np

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_npu_embedder import NPUEmbedder

        emb = NPUEmbedder()
        vq = np.array(emb.embed_one(question))
        va = np.array(emb.embed_one(answer))
        vc = np.array(emb.embed_one(context)) if context else None

        def cosine(a, b) -> object:
            """Cosine."""
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

        scores = {
            "answer_relevance": round(cosine(vq, va), 4),
        }
        if vc is not None:
            scores["context_relevance"] = round(cosine(vq, vc), 4)
            scores["answer_faithfulness"] = round(cosine(va, vc), 4)
        return {"ok": True, "question": question[:100], "scores": scores}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def chain_run(commands: list) -> list:
    """
    Exécute une chaîne de commandes locales en séquence.
    Arrêt sur première erreur si stop_on_error=True (défaut).
    Security : chaque commande validée contre le blocklist.
    """
    results = []
    for cmd in commands[:10]:
        r = run_local(str(cmd).strip(), timeout=30)
        results.append({"cmd": cmd, **r})
        if not r["ok"]:
            break
    return results


# ── Swarm — State Machine + Broadcasting ─────────────────────────────────────


def swarm_status() -> dict:
    """État complet du swarm : state machine + queue + events récents."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_swarm import swarm

        return swarm.swarm_status()
    except Exception as e:
        return {"error": str(e)[:120], "state": "UNKNOWN"}


def swarm_recent_events(n: int = 20, agent: str | None = None) -> list:
    """Derniers N events depuis event_log avec sequence_id et hash."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_swarm import swarm

        return swarm.recent_events(n=n, agent=agent)
    except Exception as e:
        return [{"error": str(e)[:120]}]


def swarm_force_idle() -> dict:
    """Reset forcé du swarm vers IDLE (après timeout ou crash agent)."""
    try:
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        from nokido_agent.app.forge_swarm import swarm

        swarm.sm.force_idle()
        return {"ok": True, "state": "IDLE"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


# Singleton socket broadcast — évite le leak de descripteurs
_bcast_listener_sock = None
_bcast_listener_lock = __import__("threading").Lock()


def swarm_broadcast_listen(timeout_ms: int = 200) -> list:
    """
    Écoute le socket broadcast UDP (singleton) pendant timeout_ms.
    Utilisé par Streamlit pour polling non-bloquant.
    Socket créé une seule fois, réutilisé entre les reruns.
    """
    global _bcast_listener_sock
    import socket as _sock, json as _json, time as _time

    with _bcast_listener_lock:
        if _bcast_listener_sock is None:
            try:
                _bcast_listener_sock = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
                _bcast_listener_sock.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
                _bcast_listener_sock.bind(("127.0.0.1", 9765))
                _bcast_listener_sock.setblocking(False)
            except Exception as e:
                return [{"error": "socket init: " + str(e)[:80]}]
    events = []
    deadline = _time.monotonic() + timeout_ms / 1000
    while _time.monotonic() < deadline:
        try:
            data, _ = _bcast_listener_sock.recvfrom(65536)
            events.append(_json.loads(data.decode("utf-8")))
        except BlockingIOError:
            break
        except Exception:
            break
    return events


# ── Singleton exporté ─────────────────────────────────────────────────────────


class _WebService:
    """Interface objet optionnelle (import svc; svc.hub_health())."""

    hub_health = staticmethod(hub_health)
    hub_metrics = staticmethod(hub_metrics)
    hub_live_bridge = staticmethod(hub_live_bridge_json)
    hub_tasks = staticmethod(hub_live_tasks)
    rag_stats = staticmethod(rag_db_stats)
    rag_search = staticmethod(rag_search)
    rag_reindex = staticmethod(rag_reindex)
    rag_warmup = staticmethod(rag_warmup)
    ssh_status = staticmethod(ssh_status)
    ssh_exec = staticmethod(ssh_exec)
    ssh_ping = staticmethod(ssh_ping)
    model_info = staticmethod(model_info)
    mem_info = staticmethod(mem_info)
    workflow_list = staticmethod(workflow_list)
    workflow_save = staticmethod(workflow_save)
    workflow_delete = staticmethod(workflow_delete)
    workflow_run = staticmethod(workflow_run)
    # Sprint 5
    loop_status = staticmethod(loop_status)
    loop_start = staticmethod(loop_start)
    loop_stop = staticmethod(loop_stop)
    evolve_run = staticmethod(evolve_run)
    evolve_status = staticmethod(evolve_status)
    collab_status = staticmethod(collab_status)
    collab_set_mode = staticmethod(collab_set_mode)
    estim_run = staticmethod(estim_run)
    estim_status = staticmethod(estim_status)
    agents_tasks = staticmethod(agents_tasks_list)
    # Sprint 6
    ci_run = staticmethod(ci_run)
    ci_status = staticmethod(ci_status)
    ci_lint = staticmethod(ci_lint)
    ci_diff = staticmethod(ci_diff)
    run_local = staticmethod(run_local)
    apply_patch = staticmethod(apply_patch)
    web_status = staticmethod(web_search_status)
    web_toggle = staticmethod(web_search_toggle)
    proxy_status = staticmethod(proxy_status)
    proxy_start = staticmethod(proxy_start)
    proxy_stop = staticmethod(proxy_stop)
    audit_run = staticmethod(audit_run)
    services_status = staticmethod(services_status)
    scan_network = staticmethod(scan_network)
    disco_search = staticmethod(disco_search)
    tools_list = staticmethod(tools_list)
    ragas_eval = staticmethod(ragas_eval)
    chain_run = staticmethod(chain_run)
    swarm_status = staticmethod(swarm_status)
    swarm_events = staticmethod(swarm_recent_events)
    swarm_force_idle = staticmethod(swarm_force_idle)
    swarm_listen = staticmethod(swarm_broadcast_listen)
    uptime_str = staticmethod(
        lambda s: f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s" if s < 3600 else f"{s // 3600}h{(s % 3600) // 60}m"
    )


svc = _WebService()


# ── Mermaid generation (Qwen2.5-Coder via llamacpp) ───────────────────────────


def mermaid_generate(prompt: str, diagram_type: str = "flowchart") -> dict:
    """Génère un diagramme Mermaid via Qwen2.5-Coder (llamacpp natif)."""
    try:
        import sys

        _root = __import__("pathlib").Path(__file__).resolve().parent.parent
        if str(_root / "app") not in sys.path:
            sys.path.insert(0, str(_root))
        from nokido_agent.app.forge_mermaid_gen import svc_generate_mermaid

        return svc_generate_mermaid(prompt, diagram_type)
    except Exception as e:
        return {"ok": False, "code": "", "error": str(e)[:120], "source": "error"}


def mermaid_types() -> list:
    """Retourne les types de diagrammes supportés."""
    return ["flowchart", "sequence", "class", "er", "state", "c4", "git", "mind"]


# ── Ring states (intégrité des rings) ─────────────────────────────────────────


def ring_states() -> dict:
    """État de chaque ring depuis resonance_log + system_rules."""
    try:
        import sqlite3 as _sq

        _db = __import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
        conn = _sq.connect(str(_db), timeout=3)
        rows = conn.execute(
            "SELECT agent_id,action,drift_score,timestamp FROM resonance_log ORDER BY id DESC LIMIT 30"
        ).fetchall()
        rules_by_ring = dict(conn.execute("SELECT ring, COUNT(*) FROM system_rules GROUP BY ring").fetchall())
        conn.close()
        return {
            "ok": True,
            "resonance_recent": [{"agent": r[0], "action": r[1], "drift": float(r[2] or 0), "ts": r[3]} for r in rows],
            "rules_by_ring": rules_by_ring,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


# ── svc facade update ─────────────────────────────────────────────────────────


class _svc_ext:
    """Extension du singleton svc avec les nouvelles méthodes."""

    mermaid_generate = staticmethod(mermaid_generate)
    mermaid_types = staticmethod(mermaid_types)
    ring_states = staticmethod(ring_states)


try:
    svc.__class__ = type("svc_extended", (svc.__class__, _svc_ext), {})
except Exception:
    pass
