"""
forge_demand_proxy.py — Proxy HTTP générique on-demand + idle-kill
==================================================================
Usage: python forge_demand_proxy.py --service <name>

Chaque service définit:
  proxy_port  : port exposé à Nokido (permanent, ~20 MB)
  real_port   : port du backend réel (lancé à la demande)
  idle_timeout: secondes sans requête avant kill du backend
  cmd         : commande pour lancer le backend
  cwd         : répertoire de travail
  startup_wait: secondes max pour attendre le démarrage
  pre_check   : URL de health check (défaut: /health)

Ajouter un service: insérer une entrée dans SERVICE_CONFIGS.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)

ROOT = Path(__file__).resolve().parent.parent

# ── Service registry ──────────────────────────────────────────────────────────

SERVICE_CONFIGS: dict[str, dict[str, Any]] = {
    "llama": {
        "proxy_port": int(os.environ.get("LLAMA_PROXY_PORT", "8091")),
        "real_port": int(os.environ.get("LLAMA_REAL_PORT", "8092")),
        "idle_timeout": int(os.environ.get("LLAMACPP_IDLE_TIMEOUT", "300")),
        "startup_wait": 60,
        "pre_check": "/health",
        "cmd": [
            __import__("os").path.expanduser(r"~\llama-vulkan\llama-server.exe"),
            "-m",
            r"D:\ollama\models\blobs\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463",
            "-md",
            r"D:\ollama\models\blobs\sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104",
            "--host",
            "127.0.0.1",
            "--port",
            "{real_port}",  # {real_port} → substitué au runtime
            "-ngl",
            "99",
            "-ngld",
            "99",
            "-c",
            "32768",
            "-cd",
            "32768",
            "-ctk",
            "q8_0",
            "-ctv",
            "q8_0",
            "-fa",
            "auto",
            "--cache-prompt",
            "--prio",
            "1",
            "--threads",
            "-1",
            "-np",
            "-1",
            "--draft-max",
            "16",
            "--draft-min",
            "4",
            "-a",
            "qwen,qwen2.5-coder,laforge-coder",
        ],
        "cwd": __import__("os").path.expanduser(r"~\llama-vulkan"),
        "log": str(ROOT / "sandbox" / "llama_server.log"),
        "description": "llama.cpp Vulkan GPU server (qwen2.5-coder 32B)",
    },
    # ── Ajouter ici les futurs services ──────────────────────────────────────
    # "lmstudio": {
    #     "proxy_port": 1234,
    #     "real_port": 11234,
    #     "idle_timeout": 600,
    #     "startup_wait": 30,
    #     "pre_check": "/v1/models",
    #     "cmd": [r"C:\...\LM Studio.exe", "--api-port", "{real_port}", "--no-browser"],
    #     "cwd": r"C:\...",
    #     "log": str(ROOT / "sandbox" / "lmstudio.log"),
    #     "description": "LM Studio OpenAI-compat server",
    # },
}

# ── Proxy state ───────────────────────────────────────────────────────────────


class DemandProxy:
    def __init__(self, cfg: dict[str, Any], service_name: str):
        self.cfg = cfg
        self.name = service_name
        self.proxy_port = cfg["proxy_port"]
        self.real_port = cfg["real_port"]
        self.idle_timeout = cfg["idle_timeout"]
        self.startup_wait = cfg.get("startup_wait", 45)
        self.pre_check = cfg.get("pre_check", "/health")
        self.log = Path(cfg.get("log", str(ROOT / "sandbox" / f"{service_name}.log")))
        self.cmd = [a.replace("{real_port}", str(self.real_port)) for a in cfg["cmd"]]
        self.cwd = cfg.get("cwd", str(ROOT))

        self.last_req_ts: float = 0.0
        self._proc: subprocess.Popen | None = None
        self._launch_lock = asyncio.Lock()
        self.log_label = f"proxy:{self.name}"
        self.logger = logging.getLogger(self.log_label)

    # ── Health probe ──────────────────────────────────────────────────────────

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"http://127.0.0.1:{self.real_port}{self.pre_check}")
                return r.status_code < 500
        except Exception:
            return False

    # ── Launch ────────────────────────────────────────────────────────────────

    async def ensure_up(self) -> bool:
        async with self._launch_lock:
            if await self._probe():
                return True

            self.logger.info(f"Backend :{self.real_port} DOWN — launching…")
            self.log.parent.mkdir(parents=True, exist_ok=True)
            try:
                log_f = open(self.log, "a", encoding="utf-8", errors="replace")
                self._proc = subprocess.Popen(
                    self.cmd,
                    cwd=self.cwd,
                    stdout=log_f,
                    stderr=log_f,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                self.logger.info(f"Started pid {self._proc.pid}")
            except Exception as e:
                self.logger.error(f"Launch failed: {e}")
                return False

            deadline = time.monotonic() + self.startup_wait
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                if await self._probe():
                    self.logger.info("Backend ready")
                    return True
            self.logger.warning(f"Not ready after {self.startup_wait}s")
            return False

    # ── Kill ─────────────────────────────────────────────────────────────────

    async def kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self.logger.info(f"Idle kill pid {self._proc.pid}")
            self._proc.terminate()
            self._proc = None
            return
        try:
            import psutil

            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr.port == self.real_port and conn.status == "LISTEN" and conn.pid:
                    psutil.Process(conn.pid).terminate()
                    self.logger.info(f"Idle kill (psutil) pid {conn.pid}")
        except Exception as e:
            self.logger.debug(f"Kill error: {e}")

    # ── Idle watcher ─────────────────────────────────────────────────────────

    async def idle_watcher(self) -> None:
        while True:
            await asyncio.sleep(30)
            if self.last_req_ts <= 0:
                continue
            idle = time.time() - self.last_req_ts
            if idle > self.idle_timeout and await self._probe():
                self.logger.info(f"Idle {idle:.0f}s > {self.idle_timeout}s → killing backend")
                await self.kill()

    # ── Forward request ───────────────────────────────────────────────────────

    async def forward(self, request: Request) -> Any:
        self.last_req_ts = time.time()

        if not await self.ensure_up():
            return JSONResponse(
                {"error": f"Backend :{self.real_port} unavailable"},
                status_code=503,
            )

        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        url = f"http://127.0.0.1:{self.real_port}{request.scope['path']}"  # scope, pas url.path falsifiable par Host (CVE-2026-48710)
        if request.url.query:
            url += f"?{request.url.query}"

        is_stream = b'"stream":true' in body or b'"stream": true' in body

        if is_stream:

            async def _gen():
                async with httpx.AsyncClient(timeout=None) as c:
                    async with c.stream(request.method, url, content=body, headers=headers) as r:
                        async for chunk in r.aiter_bytes():
                            yield chunk
                self.last_req_ts = time.time()

            return StreamingResponse(_gen(), media_type="text/event-stream")

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.request(request.method, url, content=body, headers=headers)
        self.last_req_ts = time.time()
        try:
            return JSONResponse(r.json(), status_code=r.status_code)
        except Exception:
            return StreamingResponse(
                iter([r.content]),
                status_code=r.status_code,
                media_type=r.headers.get("content-type", "application/octet-stream"),
            )


# ── FastAPI factory ───────────────────────────────────────────────────────────


def build_app(proxy: DemandProxy) -> FastAPI:
    app = FastAPI(title=f"demand-proxy:{proxy.name}", docs_url=None, redoc_url=None)

    @app.on_event("startup")
    async def _startup():
        asyncio.create_task(proxy.idle_watcher())
        proxy.logger.info(
            f"UP :{proxy.proxy_port} → :{proxy.real_port} (idle={proxy.idle_timeout}s)"
        )

    @app.get("/proxy/health")
    async def _health():
        real_up = await proxy._probe()
        return {
            "proxy": "ok",
            "service": proxy.name,
            "backend": "up" if real_up else "down",
            "backend_port": proxy.real_port,
            "idle_s": round(time.time() - proxy.last_req_ts, 1) if proxy.last_req_ts else None,
            "idle_timeout": proxy.idle_timeout,
        }

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    async def _passthrough(path: str, request: Request):
        return await proxy.forward(request)

    return app


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Nokido demand proxy")
    parser.add_argument(
        "--service", required=True, choices=list(SERVICE_CONFIGS), help="Service to proxy"
    )
    parser.add_argument("--list", action="store_true", help="List configured services")
    args = parser.parse_args()

    if args.list:
        for name, cfg in SERVICE_CONFIGS.items():
            print(
                f"  {name:20s} :{cfg['proxy_port']} → :{cfg['real_port']}  "
                f"idle={cfg['idle_timeout']}s  {cfg.get('description', '')}"
            )
        sys.exit(0)

    cfg = SERVICE_CONFIGS[args.service]
    proxy = DemandProxy(cfg, args.service)
    app = build_app(proxy)

    uvicorn.run(app, host="127.0.0.1", port=proxy.proxy_port, log_level="info", access_log=True)


if __name__ == "__main__":
    main()
