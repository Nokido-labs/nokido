# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-05 | VER:v1_multi_llm_daemon
#FORGE:[score:85|agent:claude-sonnet-4-6|temp:0.00|risk:0.20|ast:OK|test:KO|lint:OK|color:GREEN|attempt:1]

tools/multi_llm_daemon.py — Daemon multi-provider (Pattern D3 étendu)
======================================================================

Gère les agents : agt_ollama, agt_llamacpp, agt_lmstudio, agt_groq,
                  agt_hf, agt_mistral, agt_cohere, agt_openrouter
Poll agent_messages → backend LLM → result → agent_messages (to=from_agent)
Résultats surfacés au prochain tick via claude_inbox_tick.py

Config env :
  (base des messages)   : agent_messages suit forge_db_path.m2m_path(), interrupteur sandbox/m2m.switch
  MULTI_LLM_POLL_INTERVAL : secondes entre polls (défaut 15)
  OLLAMA_MODEL          : modèle Ollama (défaut qwen2.5-coder:7b)
  GROQ_API_KEY          : clé Groq (lue aussi dans Nokido.env)
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import ast
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
(ROOT / "logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MultiLLM] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            ROOT / "logs" / "multi_llm_daemon.log",
            encoding="utf-8",
            maxBytes=10485760,
            backupCount=5,
        ),
    ],
)
logger = logging.getLogger("MultiLLM.Daemon")

sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
DB_PATH = Path(m2m_path())
POLL_INTERVAL = int(os.environ.get("MULTI_LLM_POLL_INTERVAL", "15"))
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:1.5b")
SANDBOX = ROOT / "sandbox"
SANDBOX.mkdir(exist_ok=True)
HB_FILE = SANDBOX / "multi_llm_daemon.heartbeat"


def _read_env(key: str, default: str = "") -> str:
    """Lit une variable depuis os.environ puis Nokido.env."""
    val = os.environ.get(key, "")
    if val:
        return val
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    return default


def _read_wcm(target: str, username: str) -> str:
    """Lit un credential depuis Windows Credential Manager via keyring."""
    try:
        import keyring as _kr

        val = _kr.get_password(target, username)
        return val or ""
    except Exception:
        return ""


# Agents gérés par ce daemon
AGENTS = (
    "agt_ollama",
    "agt_llamacpp",
    "agt_lmstudio",
    "agt_groq",
    "agt_hf",
    "agt_mistral",
    "agt_cohere",
    "agt_openrouter",
    "agt_sambanova",
    "agt_github",
    "agt_tavily",
    "agt_cerebras",
    "agt_nvidia",
    "agt_cloudflare",
)

_stop = False


def _signal_handler(sig, frame):
    global _stop
    logger.info(f"Signal {sig} — arrêt propre")
    _stop = True


# ─── DB helpers ──────────────────────────────────────────────────────────────


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            id TEXT PRIMARY KEY,
            from_agent TEXT,
            to_agent TEXT,
            correlation_id TEXT,
            method TEXT,
            payload TEXT,
            result TEXT,
            status TEXT DEFAULT 'unread',
            created_at TEXT,
            read_at TEXT
        )
    """)
    conn.commit()


def _fetch_pending(conn: sqlite3.Connection) -> list:
    placeholders = ",".join("?" * len(AGENTS))
    return conn.execute(
        f"SELECT * FROM agent_messages WHERE to_agent IN ({placeholders})"
        " AND status='unread' ORDER BY created_at LIMIT 10",
        AGENTS,
    ).fetchall()


def _mark_read(conn: sqlite3.Connection, msg_id: str) -> None:
    conn.execute(
        "UPDATE agent_messages SET status='read', read_at=? WHERE id=?",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), msg_id),
    )
    conn.commit()


def _write_result(conn: sqlite3.Connection, original: sqlite3.Row, result_text: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO agent_messages
           (id, from_agent, to_agent, correlation_id, method, payload, result, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            str(uuid.uuid4()),
            original["to_agent"],  # from = l'agent qui a traité
            original["from_agent"] or "agt_claude",  # to   = l'expéditeur original
            original["id"],
            "task.result",
            json.dumps({"original_method": original["method"]}, ensure_ascii=False),
            result_text[:4000],
            "unread",
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )
    conn.commit()


# ─── Backends LLM ────────────────────────────────────────────────────────────


def _http_post(url: str, body: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    from nokido_agent.tools.forge_bench_http import http_post  # source unique (cliquet clones 21/08)
    return http_post(url, body, headers=headers, timeout=timeout)


def call_ollama(prompt: str, timeout: int = 180) -> str:
    try:
        data = _http_post(
            "http://127.0.0.1:11434/api/generate",
            {"model": OLLAMA_MODEL, "prompt": prompt[:6000], "stream": False},
            timeout=timeout,
        )
        return data.get("response", "").strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR ollama] {e}"


def call_llamacpp(prompt: str, timeout: int = 90) -> str:
    base = _read_env("LLAMACPP_URL", "http://127.0.0.1:8091")
    # llama-cpp-python server = OpenAI-compat /v1/chat/completions
    try:
        data = _http_post(
            f"{base}/v1/chat/completions",
            {
                "model": "local",
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            headers={"User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR llamacpp] {e}"


def call_lmstudio(prompt: str, timeout: int = 120) -> str:
    """LM Studio v0.4+ native /api/v1/chat avec Nokido hub comme MCP éphémère."""
    base = _read_env("LMSTUDIO_URL", "http://127.0.0.1:1234")
    token = _read_env("LMSTUDIO_TOKEN", "")
    model = _read_env("LMSTUDIO_MODEL", "")
    hub = _read_env("LAFORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
    hub_token = _read_env("FORGE_MCP_TOKEN", "")

    if not token:
        return "[ERR lmstudio] LMSTUDIO_TOKEN manquant — ajouter dans nokido.env"

    hdrs = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "LaForge/1.0",
    }

    # Intégration MCP éphémère : LM Studio peut appeler les tools Nokido hub
    mcp_integration = {
        "type": "ephemeral_mcp",
        "server_label": "laforge",
        "server_url": hub,
    }
    if hub_token:
        mcp_integration["headers"] = {"Authorization": f"Bearer {hub_token}"}

    body: dict = {
        "input": prompt[:8000],
        "integrations": [mcp_integration],
        "context_length": 8192,
        "temperature": 0.3,
    }
    if model:
        body["model"] = model

    try:
        data = _http_post(f"{base}/api/v1/chat", body, headers=hdrs, timeout=timeout)
        # Native API returns list of output blocks
        outputs = data.get("output", [])
        texts = [b["content"] for b in outputs if b.get("type") == "message" and b.get("content")]
        return "\n".join(texts).strip() or "[EMPTY]"
    except Exception as e:
        # Fallback: OpenAI-compat endpoint (no MCP)
        try:
            fb_body = {
                "messages": [{"role": "user", "content": prompt[:6000]}],
                "max_tokens": 512,
                "temperature": 0.3,
            }
            if model:
                fb_body["model"] = model
            data = _http_post(f"{base}/v1/chat/completions", fb_body, headers=hdrs, timeout=timeout)
            return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
        except Exception as e2:
            return f"[ERR lmstudio] {e} | fallback: {e2}"


def _groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if key:
        return key
    env_file = ROOT / "Nokido.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def call_groq(prompt: str, timeout: int = 30) -> str:
    key = _read_env("GROQ_API_KEY")
    if not key:
        return "[ERR groq] GROQ_API_KEY absent"
    try:
        data = _http_post(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR groq] {e}"


def call_hf(prompt: str, timeout: int = 45) -> str:
    """HuggingFace Inference Router — OpenAI-compat, free tier."""
    key = _read_env("HF_TOKEN")
    if not key:
        return "[ERR hf] HF_TOKEN absent"
    # HF Router supporte OpenAI-compat pour les gros modèles populaires
    model = _read_env("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    try:
        data = _http_post(
            "https://router.huggingface.co/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR hf] {e}"


def call_mistral(prompt: str, timeout: int = 30) -> str:
    """Mistral API — free tier: open-mistral-7b."""
    key = _read_env("MISTRAL_API_KEY")
    if not key:
        return "[ERR mistral] MISTRAL_API_KEY absent"
    model = _read_env("MISTRAL_MODEL", "open-mistral-7b")
    try:
        data = _http_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR mistral] {e}"


def call_cohere(prompt: str, timeout: int = 30) -> str:
    """Cohere API v2 — OpenAI-compat, free tier: command-r7b-12-2024."""
    key = _read_env("COHERE_API_KEY")
    if not key:
        return "[ERR cohere] COHERE_API_KEY absent"
    model = _read_env("COHERE_MODEL", "command-r7b-12-2024")
    try:
        data = _http_post(
            "https://api.cohere.com/compatibility/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR cohere] {e}"


def call_openrouter(prompt: str, timeout: int = 45) -> str:
    """OpenRouter — agrégateur, free models disponibles."""
    key = _read_env("OPENROUTER_API_KEY")
    if not key:
        return "[ERR openrouter] OPENROUTER_API_KEY absent"
    # openrouter/auto = choisit automatiquement un free model dispo
    model = _read_env("OPENROUTER_MODEL", "openrouter/auto")
    try:
        data = _http_post(
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "LaForge/1.0",
                "HTTP-Referer": "https://github.com/nokido",
                "X-Title": "Nokido",
            },
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR openrouter] {e}"


def call_sambanova(prompt: str, timeout: int = 60) -> str:
    """SambaNova Cloud API — LPU rapide, ~30 req/min free."""
    key = _read_env("SAMBANOVA_API_KEY") or _read_env("cloud.sambanova.ai_API_KEY")
    if not key:
        return "[ERR sambanova] SAMBANOVA_API_KEY absent"
    model = _read_env("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")
    try:
        data = _http_post(
            "https://api.sambanova.ai/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR sambanova] {e}"


def call_cerebras(prompt: str, timeout: int = 30) -> str:
    """Cerebras Cloud — 1M tok/day, ultra-fast inference."""
    key = _read_env("CEREBRAS_API_KEY")
    if not key:
        return "[ERR cerebras] CEREBRAS_API_KEY absent"
    model = _read_env("CEREBRAS_MODEL", "llama3.1-70b")
    try:
        data = _http_post(
            "https://api.cerebras.ai/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR cerebras] {e}"


def call_nvidia(prompt: str, timeout: int = 60) -> str:
    """NVIDIA NIM — 40 RPM, 70+ models via build.nvidia.com."""
    key = _read_env("NVIDIA_NIM_API_KEY")
    if not key:
        return "[ERR nvidia] NVIDIA_NIM_API_KEY absent"
    model = _read_env("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
    try:
        data = _http_post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR nvidia] {e}"


def call_cloudflare(prompt: str, timeout: int = 30) -> str:
    """Cloudflare Workers AI — 10K Neurons/day, fast inference."""
    key = _read_env("CLOUDFLARE_AI_API_KEY")
    account = _read_env("CLOUDFLARE_ACCOUNT_ID")
    if not key or not account:
        return "[ERR cloudflare] CLOUDFLARE_AI_API_KEY ou ACCOUNT_ID absent"
    model = _read_env("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct")
    try:
        import json as _j
        import urllib.request as _ur

        body = _j.dumps(
            {"messages": [{"role": "user", "content": prompt[:3000]}], "max_tokens": 500}
        ).encode()
        req = _ur.Request(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=timeout) as resp:
            data = _j.loads(resp.read())
        return (data.get("result", {}).get("response") or "[EMPTY]").strip()
    except Exception as e:
        return f"[ERR cloudflare] {e}"


def call_github(prompt: str, timeout: int = 30) -> str:
    """GitHub Models — Azure-backed, free avec GitHub token."""
    # Essaie WCM d'abord, fallback Nokido.env
    key = (
        _read_wcm("GITHUB_MODELS_TOKEN@LaForge", "GITHUB_MODELS_TOKEN")
        or _read_wcm("GITHUB_TOKEN@LaForge", "GITHUB_TOKEN")
        or _read_env("GITHUB_MODELS_TOKEN")
        or _read_env("GITHUB_TOKEN")
    )
    if not key:
        return "[ERR github] GITHUB_MODELS_TOKEN absent (WCM+env)"
    model = _read_env("GITHUB_MODEL", "gpt-4o-mini")
    try:
        data = _http_post(
            "https://models.inference.ai.azure.com/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt[:4000]}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {key}", "User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        return data["choices"][0]["message"]["content"].strip() or "[EMPTY]"
    except Exception as e:
        return f"[ERR github] {e}"


def call_tavily(prompt: str, timeout: int = 15) -> str:
    """Tavily Search API — ~1000 crédits/mois, retourne résultats web JSON."""
    key = _read_env("TAVILY_API_KEY")
    if not key:
        return "[ERR tavily] TAVILY_API_KEY absent"
    try:
        data = _http_post(
            "https://api.tavily.com/search",
            {
                "api_key": key,
                "query": prompt[:500],
                "max_results": 5,
                "include_answer": True,
                "search_depth": "basic",
            },
            headers={"User-Agent": "LaForge/1.0"},
            timeout=timeout,
        )
        answer = data.get("answer", "")
        results = data.get("results", [])
        if answer:
            return answer
        return "\n".join(f"- {r.get('title', '')}: {r.get('url', '')}" for r in results[:3])
    except Exception as e:
        return f"[ERR tavily] {e}"


_BACKENDS = {
    "agt_ollama": call_ollama,
    "agt_llamacpp": call_llamacpp,
    "agt_lmstudio": call_lmstudio,
    "agt_groq": call_groq,
    "agt_hf": call_hf,
    "agt_mistral": call_mistral,
    "agt_cohere": call_cohere,
    "agt_openrouter": call_openrouter,
    "agt_sambanova": call_sambanova,
    "agt_github": call_github,
    "agt_tavily": call_tavily,
    "agt_cerebras": call_cerebras,
    "agt_nvidia": call_nvidia,
    "agt_cloudflare": call_cloudflare,
}


# ─── Processing ──────────────────────────────────────────────────────────────


def _full_desc(p: dict) -> str:
    """Get full description from payload — 'text' is truncated by hub; use 'parameters' first."""
    # parameters = Python repr dict: "{'task_id':..., 'description': '...full...', ...}"
    params_raw = p.get("parameters", "")
    if params_raw:
        try:
            params = ast.literal_eval(str(params_raw))
            if isinstance(params, dict):
                desc = params.get("description") or params.get("task") or ""
                if desc:
                    return desc
        except Exception:
            pass
    # Fallback: text (may be truncated) or description
    return p.get("text") or p.get("description") or p.get("task") or p.get("prompt") or ""


def _extract_prompt(msg: sqlite3.Row) -> str:
    """Parse payload intelligemment selon method."""
    method = msg["method"] or ""
    try:
        p = json.loads(msg["payload"] or "{}")
    except Exception:
        return msg["payload"] or "(vide)"

    if method == "task.assign":
        # Hub frame: 'text' is truncated; full description lives in 'parameters' (Python repr dict)
        desc = _full_desc(p)
        intent = p.get("intent", "")
        job_id = p.get("job_id", "")
        return f"[JOB:{job_id}] [{intent}]\n{desc}"

    # Autres méthodes : chercher le champ texte le plus probable
    return p.get("prompt") or p.get("task") or p.get("message") or p.get("description") or str(p)


_HUB_URL = "http://127.0.0.1:8766"
_HUB_TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")


def _hub_shell(cmd: str, workdir: str = "", timeout: int = 120) -> str:
    """Execute shell command via hub MCP /mcp endpoint, return stdout+stderr."""
    # Hub runs via PowerShell — use absolute paths, skip workdir prefix
    full_cmd = cmd
    body: dict = {
        "method": "tools/call",
        "params": {
            "name": "run",
            "arguments": {"action": "shell", "commands": [full_cmd]},
        },
    }
    hdrs: dict = {"Content-Type": "application/json"}
    if _HUB_TOKEN:
        hdrs["Authorization"] = f"Bearer {_HUB_TOKEN}"
    try:
        req = urllib.request.Request(
            f"{_HUB_URL}/mcp",
            data=json.dumps(body).encode(),
            headers=hdrs,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        # MCP wraps result in jsonrpc envelope
        content = data.get("result", {}).get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                results = json.loads(text)
                if isinstance(results, list) and results:
                    r0 = results[0]
                    out = (r0.get("stdout") or "") + (r0.get("stderr") or "")
                    ok = r0.get("ok", True)
                    return f"[{'OK' if ok else 'ERR'}] {out[:2000]}"
            except Exception:
                return text[:2000]
        error = data.get("error")
        return f"[ERR] {error}" if error else str(data)[:500]
    except Exception as e:
        return f"[ERR hub_shell] {e}"


_TASK_EXEC_SYSTEM = """\
You are a Nokido shell executor. Extract the SINGLE command to run from the task.
Return ONLY valid JSON, no markdown fence, no explanation.

Format: {"cmd": "<full command>", "workdir": "<the WORKDIR given below>"}
Python path: %USERPROFILE%/miniforge3/python.exe (NEVER bare 'python')

Example input: "Check Python version. COMMAND: %USERPROFILE%/miniforge3/python.exe --version"
Example output: {"cmd": "%USERPROFILE%/miniforge3/python.exe --version", "workdir": "<the WORKDIR given below>"}

If task is already a runnable command, wrap it directly in the JSON.
Only return {"cmd": ""} if there is truly ZERO executable action.
"""

_CMD_PATTERNS = [
    # Explicit markers
    re.compile(r"(?:COMMAND|CMD|Command to execute|Commande)[:\s]+([^\n]+)", re.IGNORECASE),
    # Full python path
    re.compile(r"(%USERPROFILE%/miniforge3/python\.exe[^\n]+)"),
    re.compile(r'(__import__("os").path.expanduser("~/miniforge3/python\.exe[^")]+")'),
    # Backtick-quoted
    re.compile(r"`([^`\n]{6,})`"),
]


def _extract_cmd_regex(desc: str) -> str:
    """Extract command directly from description without LLM (explicit patterns)."""
    for pat in _CMD_PATTERNS:
        m = pat.search(desc)
        if m:
            return m.group(1).strip().strip('"')
    return ""


def _process_task_assign(conn: sqlite3.Connection, msg: sqlite3.Row, backend) -> str:
    """Boucle agentique pour task.assign : plan (LLM|regex) -> exec (hub shell) -> result."""
    payload = json.loads(msg["payload"] or "{}")
    desc = _full_desc(payload)
    job_id = payload.get("job_id", "")
    intent = payload.get("intent", "")

    # Étape 1a — Regex first: si commande explicite dans description, pas de LLM
    cmd = _extract_cmd_regex(desc)
    llm_resp = ""
    if cmd:
        logger.info(f"[task_assign] cmd via regex (no LLM): {cmd[:120]}")
    else:
        # Étape 1b — LLM extrait la commande
        # WORKDIR donne au modele : racine DERIVEE, le gabarit ne nomme plus le dossier.
        plan_prompt = f"{_TASK_EXEC_SYSTEM}\n\nWORKDIR: {ROOT}\n\nTASK [{intent}]:\n{desc[:3000]}"
        llm_resp = backend(plan_prompt)
        logger.info(f"[task_assign] LLM plan: {llm_resp[:200]}")

        # Étape 2 — Parser le JSON réponse LLM
        try:
            raw = llm_resp.strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            # Extract JSON object even if LLM adds text before/after
            m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
            plan = json.loads(raw)
            cmd = plan.get("cmd", "").strip()
        except Exception as e:
            logger.warning(f"[task_assign] JSON parse fail: {e} — raw: {llm_resp[:100]}")

        # Étape 2b — Regex fallback si LLM a échoué ou retourné cmd vide
        if not cmd:
            cmd = _extract_cmd_regex(desc)
            if cmd:
                logger.info(f"[task_assign] cmd via regex fallback: {cmd[:120]}")

    if not cmd:
        return f"[WARN] No command found. LLM said: {llm_resp[:400]}"

    # Étape 3 — Exécuter via hub shell
    logger.info(f"[task_assign] exec: {cmd[:120]}")
    workdir = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    result = _hub_shell(cmd, workdir=workdir, timeout=180)
    logger.info(f"[task_assign] result: {result[:150]}")

    return json.dumps(
        {
            "job_id": job_id,
            "intent": intent,
            "cmd": cmd,
            "result": result[:1500],
        },
        ensure_ascii=False,
    )


def _process(conn: sqlite3.Connection, msg: sqlite3.Row) -> None:
    agent = msg["to_agent"]
    method = msg["method"] or ""
    prompt = _extract_prompt(msg)
    logger.info(f"{agent} <- {msg['from_agent']} [{method}] {prompt[:80]}...")

    backend = _BACKENDS.get(agent)
    if backend is None:
        result = f"[ERR] Pas de backend pour {agent}"
    elif method == "task.assign":
        # Boucle agentique : LLM planifie → hub exécute → résultat réel
        result = _process_task_assign(conn, msg, backend)
    else:
        result = backend(prompt)

    logger.info(f"{agent} -> {len(result)} chars: {result[:100]}")
    _write_result(conn, msg, result)
    _mark_read(conn, msg["id"])


# ─── Main loop ────────────────────────────────────────────────────────────────


def run_daemon() -> None:
    logger.info(f"MultiLLM Daemon démarré — agents={AGENTS} poll={POLL_INTERVAL}s")
    logger.info(f"DB: {DB_PATH}")

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    while not _stop:
        try:
            conn = _db()
            _ensure_schema(conn)
            pending = _fetch_pending(conn)
            for msg in pending:
                if _stop:
                    break
                try:
                    _process(conn, msg)
                except Exception as e:
                    logger.error(f"Erreur msg {msg['id']}: {e}")
                    _mark_read(conn, msg["id"])
            conn.close()
        except Exception as e:
            logger.error(f"DB error: {e}")

        HB_FILE.write_text(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "interval_s": POLL_INTERVAL,
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )

        for _ in range(POLL_INTERVAL):
            if _stop:
                break
            time.sleep(1)

    HB_FILE.write_text(
        json.dumps(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "interval_s": POLL_INTERVAL,
                "status": "stopped",
            }
        ),
        encoding="utf-8",
    )
    logger.info("MultiLLM Daemon arrêté.")


if __name__ == "__main__":
    import socket as _sock

    def _hub_up() -> bool:
        try:
            with _sock.create_connection(("127.0.0.1", 8766), timeout=1):
                return True
        except OSError:
            return False

    if not _hub_up():
        sys.exit(0)  # Nokido pas lancé — skip silencieux
    run_daemon()
