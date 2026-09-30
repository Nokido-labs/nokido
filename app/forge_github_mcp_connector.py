from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_github_mcp_connector
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_github_mcp_connector.py
===================================
Connecteur GitHub MCP Server (Remote HTTP/SSE + REST fallback).

Protocole exact documenté dans host-integration.md :
  URL    : https://api.githubcopilot.com/mcp/
  Méthode: POST uniquement (pas GET)
  Auth   : Authorization: Bearer <PAT> dans chaque requête
  Format : JSON-RPC 2.0 (jsonrpc="2.0" — PAS la version protocolVersion)
  Réponse: text/event-stream — parser les lignes "data: {...}"

Handshake validé live (HTTP 200) :
  1. POST initialize  → result.serverInfo + result.capabilities
  2. POST notifications/initialized → (no response body needed)
  3. POST tools/list  → result.tools[]

Token actuel : ghp_* Classic PAT
  Scopes : repo, workflow, audit_log, write:packages
  Expiry : 2026-04-16
  ⚠ Recommandation GitHub : migrer vers fine-grained PAT (github_pat_*)

Variables .env :
  GITHUB_TOKEN=ghp_*   → bearer
  LAFORGE_ENV=dev      → actions destructives simulées
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

# ── Constantes ────────────────────────────────────────────────────────────────

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"
GITHUB_REST_BASE = "https://api.github.com"
MCP_PROTOCOL_VER = "2024-11-05"


def _token() -> str:
    """Token."""
    return get_secret("GITHUB_TOKEN") or ""


def _is_dev() -> bool:
    """Is dev."""
    return os.getenv("LAFORGE_ENV", "prod").lower() == "dev" or os.getenv("LAFORGE_MCP_DEV", "false").lower() == "true"


def _token_type() -> str:
    """Token type."""
    t = _token()
    if t.startswith("github_pat_"):
        return "fine-grained"
    if t.startswith("ghp_"):
        return "classic"
    if t.startswith("gho_"):
        return "oauth"
    return "unknown"


def _read_token_expiry() -> str:
    """Lit la vraie date d'expiration du token via header HTTP GitHub.

    Le header 'github-authentication-token-expiration' est present sur toute reponse API
    pour les fine-grained PAT et certains classic PAT avec expiration.
    Retourne 'no-expiry' si absent (token sans expiration), 'unknown' si erreur.
    """
    try:
        req = urllib.request.Request(
            GITHUB_REST_BASE + "/user",
            headers=_rest_headers(),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            exp = r.headers.get("github-authentication-token-expiration", "")
            if not exp:
                return "no-expiry"
            # Format type "2026-07-15 11:38:26 UTC" -> garder juste la date
            return exp.split(" ")[0] if " " in exp else exp
    except Exception:
        return "unknown"


def _mcp_headers() -> dict:
    """
    Headers corrects pour le Remote GitHub MCP Server.
    POST uniquement — Accept inclut text/event-stream pour recevoir SSE.
    """
    return {
        "Authorization": "Bearer " + _token(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _rest_headers() -> dict:
    """Rest headers."""
    return {
        "Authorization": "Bearer " + _token(),
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ── JSON-RPC 2.0 sur HTTP/SSE ─────────────────────────────────────────────────


def _jsonrpc_post(method: str, params: dict, timeout: int = 15, read_size: int = 65536) -> dict:
    """
    POST JSON-RPC 2.0 vers GitHub MCP Server.
    Réponse = SSE (text/event-stream) → parser les lignes "data: {...}".
    jsonrpc doit être "2.0" — pas la version du protocole MCP.
    """
    payload = json.dumps(
        {
            "jsonrpc": "2.0",  # ← CRITIQUE : "2.0" pas "2024-11-05"
            "id": int(time.time() * 1000) % 999999,
            "method": method,
            "params": params,
        }
    ).encode()

    req = urllib.request.Request(
        GITHUB_MCP_URL,
        data=payload,
        headers=_mcp_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(read_size).decode(errors="replace")
            return _parse_sse_body(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")[:300]
        return {"error": {"code": e.code, "message": err_body}}
    except Exception as e:
        return {"error": {"code": -1, "message": str(e)[:120]}}


def _parse_sse_body(body: str) -> dict:
    """Parse une réponse SSE — extrait le premier objet JSON après 'data:'."""
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    # Fallback : JSON brut
    body = body.strip()
    if body.startswith("{"):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    return {}


# ── Session MCP ───────────────────────────────────────────────────────────────


class GitHubMCPSession:
    """
    Session JSON-RPC avec le GitHub Remote MCP Server.
    Gère le handshake initialize → notifications/initialized → tools/list.
    """

    def __init__(self) -> None:
        """Init."""
        self._initialized = False
        self._server_info = {}
        self._capabilities = {}
        self._tools_cache: list = []

    def initialize(self) -> dict:
        """Handshake MCP — retourne serverInfo + capabilities."""
        result = _jsonrpc_post(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VER,
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {"name": "Nokido", "version": "17.0.0"},
            },
        )
        if "result" in result:
            self._server_info = result["result"].get("serverInfo", {})
            self._capabilities = result["result"].get("capabilities", {})
            # Envoyer notifications/initialized (fire & forget)
            try:
                _jsonrpc_post("notifications/initialized", {})
            except Exception:
                pass
            self._initialized = True
        return result

    def list_tools(self) -> list:
        """Retourne la liste des tools GitHub MCP."""
        if not self._initialized:
            self.initialize()
        result = _jsonrpc_post("tools/list", {}, read_size=131072)
        tools = result.get("result", {}).get("tools", [])
        if tools:
            self._tools_cache = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict, timeout: int = 20) -> dict:
        """Appelle un tool GitHub MCP."""
        if not self._initialized:
            self.initialize()
        result = _jsonrpc_post(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
            timeout=timeout,
        )
        return result.get("result", result)

    def server_info(self) -> dict:
        """Server info."""
        return self._server_info

    def capabilities(self) -> dict:
        """Capabilities."""
        return self._capabilities


# ── REST API directe ─────────────────────────────────────────────────────────


def _rest_get(endpoint: str, timeout: int = 10) -> object:
    """Rest get.

    Args:
        endpoint: Description.
        timeout: Description.
    """
    req = urllib.request.Request(GITHUB_REST_BASE + endpoint, headers=_rest_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _rest_post(endpoint: str, body: dict, timeout: int = 10) -> object:
    """Rest post.

    Args:
        endpoint: Description.
        body: Description.
        timeout: Description.
    """
    data = json.dumps(body).encode()
    req = urllib.request.Request(GITHUB_REST_BASE + endpoint, data=data, headers=_rest_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── Bridge unifié ─────────────────────────────────────────────────────────────


class GitHubMCPBridge:
    """
    Façade unifiée : MCP Remote (HTTP/SSE) + REST API fallback.
    Le MCP Remote donne accès aux tools GitHub avancés.
    Le REST couvre les opérations de base (repos, issues, PRs).
    """

    def __init__(self) -> None:
        """Init."""
        self._session = GitHubMCPSession()
        self._token = _token()

    def is_available(self) -> bool:
        """Is available."""
        return bool(self._token)

    # ── MCP Remote ────────────────────────────────────────────────────────────

    def mcp_initialize(self) -> dict:
        """Mcp initialize."""
        return self._session.initialize()

    def mcp_list_tools(self) -> list:
        """Mcp list tools."""
        return self._session.list_tools()

    def mcp_call(self, tool_name: str, arguments: dict) -> dict:
        """Mcp call.

        Args:
            tool_name: Description.
            arguments: Description.
        """
        return self._session.call_tool(tool_name, arguments)

    # ── REST API ──────────────────────────────────────────────────────────────

    def get_user(self) -> dict:
        """Get user."""
        try:
            return _rest_get("/user")
        except Exception as e:
            return {"error": str(e)[:80]}

    def list_repos(self, per_page: int = 10) -> list:
        """List repos.

        Args:
            per_page: Description.
        """
        try:
            return _rest_get(f"/user/repos?per_page={per_page}&sort=updated")
        except Exception as e:
            return [{"error": str(e)[:80]}]

    def list_issues(self, owner: str, repo: str, state: str = "open", limit: int = 10) -> list:
        """List issues.

        Args:
            owner: Description.
            repo: Description.
            state: Description.
            limit: Description.
        """
        try:
            return _rest_get(f"/repos/{owner}/{repo}/issues?state={state}&per_page={limit}")
        except Exception as e:
            return [{"error": str(e)[:80]}]

    def list_prs(self, owner: str, repo: str, state: str = "open", limit: int = 10) -> list:
        """List prs.

        Args:
            owner: Description.
            repo: Description.
            state: Description.
            limit: Description.
        """
        try:
            return _rest_get(f"/repos/{owner}/{repo}/pulls?state={state}&per_page={limit}")
        except Exception as e:
            return [{"error": str(e)[:80]}]

    def search_code(self, query: str, limit: int = 5) -> list:
        """Search code.

        Args:
            query: Description.
            limit: Description.
        """
        try:
            import urllib.parse

            q = urllib.parse.quote(query)
            result = _rest_get(f"/search/code?q={q}&per_page={limit}")
            return [
                {
                    "path": i.get("path", ""),
                    "repo": i.get("repository", {}).get("full_name", ""),
                    "url": i.get("html_url", ""),
                }
                for i in result.get("items", [])
            ]
        except Exception as e:
            return [{"error": str(e)[:80]}]

    def create_issue(self, owner: str, repo: str, title: str, body: str = "", labels: list = None) -> dict:
        """Create issue.

        Args:
            owner: Description.
            repo: Description.
            title: Description.
            body: Description.
            labels: Description.
        """
        if _is_dev():
            return {"ok": True, "action": "dev_skip", "message": f"Dev mode — issue '{title}' non créée"}
        try:
            payload = {"title": title, "body": body}
            if labels:
                payload["labels"] = labels
            return _rest_post(f"/repos/{owner}/{repo}/issues", payload)
        except Exception as e:
            return {"error": str(e)[:80]}

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Status."""
        user = self.get_user()
        return {
            "available": self.is_available(),
            "token_type": _token_type(),
            "token_prefix": _token()[:12] + "...",
            "token_expiry": _read_token_expiry(),  # FIX 2026-04-16: vrai header HTTP
            "login": user.get("login", "?"),
            "mcp_url": GITHUB_MCP_URL,
            "mcp_protocol": MCP_PROTOCOL_VER,
            "dev_mode": _is_dev(),
            "recommendation": (
                "Migrer vers fine-grained PAT (github_pat_*) selon GitHub policies-and-governance.md"
                if _token_type() == "classic"
                else "OK"
            ),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_bridge: Optional[GitHubMCPBridge] = None


def get_bridge() -> GitHubMCPBridge:
    """Get bridge."""
    global _bridge
    if _bridge is None:
        _bridge = GitHubMCPBridge()
    return _bridge


def github_mcp_status() -> dict:
    """Github mcp status."""
    return get_bridge().status()
