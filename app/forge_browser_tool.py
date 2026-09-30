"""
forge_browser_tool.py — Bridge Nokido <-> browser-control-mcp (Firefox)

Installe l extension Firefox :
  https://addons.mozilla.org/firefox/addon/browser-control-mcp/

Lance le MCP server Node :
  npx @eyalzh/browser-control-mcp --port 3001
  (port 3001 pour ne pas conflitter avec Nokido :8766 et SearXNG :8080)

Variables d env :
  BROWSER_MCP_PORT   = 3001 (defaut)
  BROWSER_MCP_SECRET = <secret depuis about:addons>

Usage depuis Nokido hub :
  hub action=browser_get_tabs
  hub action=browser_read_page
  hub action=browser_ingest url=https://...
  hub action=browser_history query=python
"""

import os, json, asyncio, urllib.request, urllib.error
from typing import Dict, Any, List, Optional
from nokido_agent.app.forge_secrets import get_secret

BROWSER_PORT = int(os.environ.get("BROWSER_MCP_PORT", "3001"))
BROWSER_SECRET = get_secret("BROWSER_MCP_SECRET") or ""
BROWSER_BASE = f"http://127.0.0.1:{BROWSER_PORT}"


def _call_browser_mcp(tool: str, args: Dict = None) -> Any:
    """
    Appel synchrone vers browser-control-mcp via HTTP JSON-RPC.
    Le serveur ecoute sur HTTP Streamable transport.
    """
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
    ).encode()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if BROWSER_SECRET:
        headers["Authorization"] = f"Bearer {BROWSER_SECRET}"

    try:
        req = urllib.request.Request(
            f"{BROWSER_BASE}/mcp",
            data=payload,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            # Streamable HTTP peut retourner SSE ou JSON direct
            if body.startswith("data:"):
                lines = [l[5:].strip() for l in body.splitlines() if l.startswith("data:") and l.strip() != "data:"]
                body = lines[-1] if lines else "{}"
            data = json.loads(body)
            result = data.get("result", {})
            content = result.get("content", [])
            if content and isinstance(content, list):
                return content[0].get("text", "")
            return json.dumps(result)
    except urllib.error.URLError as e:
        return f"ERR:browser_mcp_unreachable: {e} (lance: npx @eyalzh/browser-control-mcp --port {BROWSER_PORT})"
    except Exception as e:
        return f"ERR:{type(e).__name__}: {e}"


async def get_tabs() -> str:
    """Retourne la liste des onglets ouverts dans Firefox."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _call_browser_mcp, "get_tabs", {})
    return str(result)


async def read_webpage(tab_id: Optional[int] = None, url: Optional[str] = None) -> str:
    """
    Lit le contenu texte d un onglet.
    tab_id : ID de l onglet (depuis get_tabs). Si None, onglet actif.
    """
    args = {}
    if tab_id:
        args["tabId"] = tab_id
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _call_browser_mcp, "read_webpage", args)
    return str(result)[:8000]  # cap 8KB


async def get_history(query: str = "", max_results: int = 10) -> str:
    """Recherche dans l historique Firefox."""
    args = {"maxResults": max_results}
    if query:
        args["text"] = query
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _call_browser_mcp, "get_history", args)
    return str(result)


async def browser_ingest_to_rag(
    url: Optional[str] = None, tab_id: Optional[int] = None, domain: str = "browser"
) -> str:
    """
    Lit un onglet et injecte le contenu dans rag_chunks.
    Pipeline : read_webpage -> chunk -> INSERT rag_chunks
    """
    import sqlite3, hashlib, time
    from pathlib import Path as _P

    db_path = str(_P(__file__).resolve().parent.parent / "RAG" / "embeddings.db")

    content = await read_webpage(tab_id=tab_id, url=url)
    if content.startswith("ERR:"):
        return content

    # Chunking simple : paragraphes de ~500 chars
    chunks = []
    current = []
    current_len = 0
    for line in content.splitlines():
        current.append(line)
        current_len += len(line)
        if current_len >= 500:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
    if current:
        chunks.append("\n".join(current).strip())

    chunks = [c for c in chunks if len(c) > 50]
    if not chunks:
        return "browser_ingest: contenu trop court ou vide"

    source_url = url or f"browser://tab/{tab_id or 'active'}"
    now = __import__("datetime").datetime.now().isoformat()

    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    inserted = 0
    for i, chunk in enumerate(chunks):
        cid = "brw_" + hashlib.md5(f"{source_url}{i}".encode()).hexdigest()[:12]
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks"
            "(id, source, text, domain, role_hint, author, ingested_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, source_url, chunk, domain, "browser_content", "browser_mcp", now),
        )
        inserted += 1
    conn.commit()
    conn.close()

    return f"browser_ingest OK: {inserted} chunks -> rag_chunks domain={domain} source={source_url}"


def is_available() -> bool:
    """Verifie si browser-control-mcp est joignable."""
    try:
        req = urllib.request.Request(f"{BROWSER_BASE}/", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2):
            return True
    except:
        return False
