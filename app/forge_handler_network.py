# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_handler_network
#FORGE:[score:98|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Isolation Network Handlers (Proxy/SSH/Tunnels)
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:98|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncssh
import logging
from typing import Optional

logger = logging.getLogger("Nokido.Handler.Network")

# État global du proxy (partagé dans le process)
proxy_conn: Optional[asyncssh.SSHClientConnection] = None


async def _handle_proxy(app: object, args: str) -> None:
    """@proxy start|stop|status|test — tunnel SOCKS5 via SSH."""
    chat = app._chat_log()
    global proxy_conn
    from nokido_agent.app.forge_app_context import get_settings as _gset_px

    _settings_px = getattr(app, "settings", None) or _gset_px()
    parts = args.split()
    if not parts:
        chat.write("[bold]@proxy[/]  start | stop | status | test")
        return
    sub = parts[0].lower()

    if sub == "start":
        if proxy_conn is not None:
            chat.write("[yellow]⚠ Proxy deja actif — @proxy stop d'abord[/]")
            return
        try:
            proxy_conn = await asyncssh.connect(
                _settings_px.ssh_host,
                port=_settings_px.ssh_port,
                username=_settings_px.ssh_user,
                client_keys=[str(_settings_px.private_key_path)],
                known_hosts=None,
            )
            await proxy_conn.forward_socks("127.0.0.1", 8080)
            chat.write(f"[green]✅ Proxy SOCKS5 actif → {_settings_px.ssh_host}:8080[/]")
        except Exception as e:
            proxy_conn = None
            chat.write(f"[red]❌ @proxy start: {e}[/]")

    elif sub == "stop":
        if proxy_conn is None:
            chat.write("[dim]Proxy non actif[/]")
            return
        try:
            proxy_conn.close()
            await proxy_conn.wait_closed()
        except Exception:
            pass
        proxy_conn = None
        chat.write("[yellow]🛑 Proxy arrêté[/]")

    elif sub in ("status", ""):
        if proxy_conn is not None:
            chat.write("[green]✅ Proxy actif sur 127.0.0.1:8080[/]")
        else:
            chat.write("[dim]Proxy inactif[/]")

    elif sub == "test":
        if proxy_conn is None:
            chat.write("[yellow]⚠ Proxy non actif — @proxy start d'abord[/]")
            return
        try:
            # Test via SSH directement
            result = await proxy_conn.run("curl -s --max-time 5 https://ifconfig.me", check=False)
            ip = result.stdout.strip() if result.stdout else "?"
            chat.write(f"[green]✅ IP via proxy: {ip}[/]")
        except Exception as e:
            chat.write(f"[red]❌ @proxy test: {e}[/]")

    else:
        chat.write("[dim]@proxy start | stop | status | test[/]")
