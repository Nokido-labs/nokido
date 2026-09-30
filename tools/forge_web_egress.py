"""forge_web_egress.py — Gateway d'egress web firewallé (le "hard hijack" web).

Chokepoint HTTP pour le contenu web : tout client (aichat/llm/curl/CLI non-MCP)
POST une URL -> le gateway fetch côté serveur (réseau local), nettoie via
trafilatura -> markdown épuré, firewall l'injection de prompt INDIRECTE, et si
la page dépasse le seuil l'indexe en RAG local (NPU) + renvoie un pointer.
L'agent ne reçoit JAMAIS du HTML brut ni un contenu non-scanné.

Mirror de forge_openai_proxy (la membrane pour les PROMPTS) appliqué au trafic
WEB sortant. Réutilise forge_crawl_tool (markdown+firewall) + forge_web_fetch
(ingest RAG) déjà construits.

Portée honnête : mode GATEWAY (endpoint /fetch). La transparence HTTPS d'un vrai
forward-proxy exige du MITM (cert CA) = hors scope (trop lourd). Pour les agents
SANDBOXÉS, l'isolation réseau (sockets bloqués) force déjà le passage par le hub ;
ce gateway étend le chemin déporté+firewallé aux clients HÔTE non-MCP.

Run: LAFORGE_PYTHON tools/forge_web_egress.py [--port 7779] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

RAG_THRESHOLD = int(os.environ.get("WEB_EGRESS_RAG_THRESHOLD", "10000"))  # ~2500 tokens

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


def _ssrf_blocked(url: str) -> bool:
    """Bloque les cibles internes/metadata cloud (SSRF). Un gateway qui fetch
    pour autrui ne doit jamais toucher le réseau interne (169.254.169.254, RFC1918,
    loopback, *.local/.internal). Cf. incident DenoProxy RCE 0.0.0.0+unauth."""
    try:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return True
        if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal")):
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(host))
            except Exception:
                return False  # non résolu -> le fetch échouera de lui-même
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    except Exception:
        return True  # fail-closed sur l'inattendu


def _egress(url: str) -> dict:
    """Pipeline déporté : fetch -> markdown firewallé -> seuil auto-RAG."""
    from nokido_agent.app.forge_crawl_tool import crawl_url

    md = crawl_url(url, timeout=20)
    if md.startswith("ERR"):
        return {"ok": False, "error": md, "url": url}
    injected = md.startswith("[⚠")  # firewall_web a préfixé l'avertissement
    if injected:
        # P0-2 FAIL-CLOSED : injection indirecte détectée -> NE PAS auto-ingérer en RAG. Sinon
        # injection STOCKÉE (le pire, risque #3 du débat). Markdown flaggé retourné HORS-RAG.
        return {"ok": True, "url": url, "mode": "blocked_injection", "injected": True,
                "chars": len(md), "markdown": md,
                "note": "Injection indirecte détectée -> contenu NON ingéré en RAG (fail-closed P0-2). Inspecter avant usage."}
    if len(md) > RAG_THRESHOLD:
        try:
            from nokido_agent.app.forge_web_fetch import fetch_and_ingest

            res = fetch_and_ingest(url)
            if res.get("ok"):
                return {
                    "ok": True,
                    "url": url,
                    "mode": "rag_indexed",
                    "domain": res.get("domain"),
                    "chunks": res.get("chunks"),
                    "injected": bool(res.get("injected", injected)),
                    "note": (
                        f"Page volumineuse ({len(md)} chars) indexée en RAG local "
                        f"(0 token cloud). Interroge via l'outil rag/query."
                    ),
                }
        except Exception:
            pass
    return {"ok": True, "url": url, "mode": "markdown", "injected": injected, "chars": len(md), "markdown": md}


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "service": "forge_web_egress", "rag_threshold": RAG_THRESHOLD, "ts": int(time.time())}
    )


async def fetch_ep(request: Request):
    if request.method == "POST":
        try:
            body = await request.json()
            url = (body or {}).get("url", "")
        except Exception:
            url = ""
    else:
        url = request.query_params.get("url", "")
    if not url or not url.startswith(("http://", "https://")):
        return JSONResponse({"ok": False, "error": "url http(s) requise"}, status_code=400)
    if _ssrf_blocked(url):
        return JSONResponse({"ok": False, "error": "SSRF: cible interne/metadata refusée"}, status_code=403)
    res = _egress(url)
    # Accept: text/markdown -> renvoie le markdown brut ; sinon JSON
    if res.get("ok") and res.get("mode") == "markdown" and "text/markdown" in request.headers.get("accept", ""):
        return PlainTextResponse(res["markdown"], media_type="text/markdown")
    return JSONResponse(res, status_code=200 if res.get("ok") else 502)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("LAFORGE_WEB_EGRESS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=7779)
    args = ap.parse_args()

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/fetch", fetch_ep, methods=["GET", "POST"]),
        ]
    )
    import uvicorn

    print(f"[+] forge_web_egress listen {args.host}:{args.port} (RAG seuil {RAG_THRESHOLD})")
    print(f"[+] POST http://{args.host}:{args.port}/fetch  {{'url': '...'}}  -> markdown firewallé")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", workers=1, timeout_keep_alive=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
