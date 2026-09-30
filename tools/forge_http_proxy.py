"""
forge_http_proxy.py — Proxy HTTP/HTTPS souverain pour LobeHub & autres clients.

Filtres :
- Whitelist domains LLM/AI/work (passthrough sans logging contenu)
- Greylist domains analytics/telemetry connus → bloqué
- Audit log toutes connexions (host, port, method, latency, bytes)
- HTTPS tunneling via CONNECT (pas de MITM, on touche pas TLS)

Bind 127.0.0.1:7780 (LAN-only par défaut).

Usage :
  LAFORGE_PYTHON tools/forge_http_proxy.py [--port 7780] [--log-file logs/forge_proxy.log]

Configuration LobeHub :
  Settings → Proxy → Activer
  Type : HTTP
  Adresse : 127.0.0.1
  Port : 7780
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "forge_proxy.log"

# Domaines whitelist LLM/AI/work — passthrough rapide
WHITELIST = re.compile(
    r"\.("
    r"anthropic\.com|claude\.ai|"
    r"openai\.com|chatgpt\.com|"
    r"googleapis\.com|google\.com|gstatic\.com|"
    r"groq\.com|deepseek\.com|x\.ai|"
    r"mistral\.ai|cohere\.ai|perplexity\.ai|"
    r"huggingface\.co|hf\.co|"
    r"openrouter\.ai|kimi\.com|moonshot\.cn|"
    r"github\.com|githubusercontent\.com|"
    r"lobehub\.com|lobechat\.com|lobeobjects\.space|"
    r"vercel\.app|vercel\.com|"
    r"amazonaws\.com|cloudflare\.com|cloudfront\.net|"
    r"microsoft\.com|live\.com|office\.com|"
    r"npmjs\.org|pypi\.org|debian\.org|ubuntu\.com|"
    r"docker\.com|docker\.io|"
    r"ollama\.com|"
    r"crawl4ai\.com|searxng\.org|"
    r"smartscreen\.microsoft\.com|wdcp\.microsoft\.com"
    r")$",
    re.IGNORECASE,
)

# Blocklist tracking/telemetry — refusé par défaut
BLOCKLIST = re.compile(
    r"\.("
    r"google-analytics\.com|googletagmanager\.com|googlesyndication\.com|"
    r"doubleclick\.net|googleadservices\.com|"
    r"facebook\.com|facebook\.net|fbcdn\.net|"
    r"hotjar\.com|mixpanel\.com|segment\.io|amplitude\.com|"
    r"sentry\.io|bugsnag\.com|datadog\.com|"
    r"adobe\.com|adobedtm\.com|"
    r"branch\.io|appsflyer\.com|adjust\.com"
    r")$",
    re.IGNORECASE,
)


_log_fp = None


def log(line: str) -> None:
    global _log_fp
    if _log_fp is None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _log_fp = LOG_FILE.open("a", encoding="utf-8")
    _log_fp.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    _log_fp.flush()


def classify(host: str) -> str:
    """ALLOW | BLOCK | NEUTRAL"""
    if WHITELIST.search(host):
        return "ALLOW"
    if BLOCKLIST.search(host):
        return "BLOCK"
    return "NEUTRAL"


async def relay(src: asyncio.StreamReader, dst: asyncio.StreamWriter, label: str) -> int:
    total = 0
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
            total += len(data)
    except Exception:
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass
    return total


async def handle_connect(reader, writer, target_host: str, target_port: int, peer: str) -> None:
    """HTTPS tunneling via CONNECT method. Pas de MITM TLS."""
    cls = classify(target_host)
    t0 = time.monotonic()
    if cls == "BLOCK":
        log(f"BLOCK CONNECT {peer} -> {target_host}:{target_port} (blocklist)")
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    try:
        remote_reader, remote_writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port), timeout=10
        )
    except Exception as e:
        log(f"FAIL CONNECT {peer} -> {target_host}:{target_port} : {e}")
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    writer.write(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: forge-proxy/1.0\r\n\r\n")
    await writer.drain()

    log(f"OPEN  CONNECT {peer} -> {target_host}:{target_port} [{cls}]")

    # Bidirectional relay
    t1 = asyncio.create_task(relay(reader, remote_writer, "c2s"))
    t2 = asyncio.create_task(relay(remote_reader, writer, "s2c"))
    bytes_c2s, bytes_s2c = await asyncio.gather(t1, t2)
    dt = round((time.monotonic() - t0) * 1000)
    log(
        f"CLOSE CONNECT {peer} -> {target_host}:{target_port} dt={dt}ms up={bytes_c2s}B down={bytes_s2c}B"
    )


async def handle_http(reader, writer, first_line: bytes, peer: str) -> None:
    """HTTP plain (rare en 2026, mostly HTTPS). Forward request comme reverse-proxy."""
    # Parse host header
    headers = b""
    while True:
        line = await reader.readline()
        if not line or line == b"\r\n":
            break
        headers += line

    host_match = re.search(rb"^Host:\s*([^\r\n]+)", headers, re.IGNORECASE | re.MULTILINE)
    if not host_match:
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    host_header = host_match.group(1).decode().strip()
    if ":" in host_header:
        target_host, target_port = host_header.rsplit(":", 1)
        target_port = int(target_port)
    else:
        target_host, target_port = host_header, 80

    cls = classify(target_host)
    if cls == "BLOCK":
        log(f"BLOCK HTTP {peer} -> {target_host}:{target_port}")
        writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    # Forward simple : reconstruit request originale
    try:
        remote_reader, remote_writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port), timeout=10
        )
    except Exception as e:
        log(f"FAIL HTTP {peer} -> {target_host}:{target_port} : {e}")
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        await writer.drain()
        writer.close()
        return

    log(f"OPEN  HTTP {peer} -> {target_host}:{target_port} [{cls}]")

    remote_writer.write(first_line + headers + b"\r\n")
    await remote_writer.drain()
    t1 = asyncio.create_task(relay(reader, remote_writer, "c2s"))
    t2 = asyncio.create_task(relay(remote_reader, writer, "s2c"))
    bc, bs = await asyncio.gather(t1, t2)
    log(f"CLOSE HTTP {peer} -> {target_host}:{target_port} up={bc}B down={bs}B")


async def handle_client(reader, writer) -> None:
    peer = writer.get_extra_info("peername")
    peer_str = f"{peer[0]}:{peer[1]}" if peer else "unknown"
    try:
        first_line = await asyncio.wait_for(reader.readline(), timeout=10)
    except TimeoutError:
        writer.close()
        return

    if not first_line:
        writer.close()
        return

    if first_line.startswith(b"CONNECT "):
        # CONNECT host:port HTTP/1.1
        m = re.match(rb"^CONNECT\s+([^\s:]+):(\d+)\s+HTTP", first_line)
        if not m:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        host = m.group(1).decode()
        port = int(m.group(2))
        # Drain remaining headers
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
        await handle_connect(reader, writer, host, port, peer_str)
    elif first_line.startswith(
        (b"GET ", b"POST ", b"HEAD ", b"PUT ", b"DELETE ", b"PATCH ", b"OPTIONS ")
    ):
        await handle_http(reader, writer, first_line, peer_str)
    else:
        log(f"REJECT bad-method {peer_str} : {first_line[:80]}")
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7780)
    args = parser.parse_args()

    server = await asyncio.start_server(handle_client, args.host, args.port)
    addr = server.sockets[0].getsockname()
    msg = f"[+] forge_http_proxy listen {addr[0]}:{addr[1]} | log={LOG_FILE}"
    print(msg)
    log(f"START {addr[0]}:{addr[1]}")
    print()
    print("LobeHub config :")
    print("  Type    : HTTP")
    print(f"  Adresse : {addr[0]}")
    print(f"  Port    : {addr[1]}")
    print("  Auth    : aucune")
    print("  Test URL: https://api.anthropic.com/v1/models  (whitelist verifie)")
    print()
    async with server:
        await server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
