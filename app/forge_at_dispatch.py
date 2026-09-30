"""Implémente les commandes @ de la TUI Nokido et les expose dans la table AT_DISPATCH.

Handlers async (app, cmd_line, parts, cmd) : handle_at_ssh, handle_at_scan,
handle_at_ids, handle_at_agentic, handle_at_evolve, handle_at_ollama, handle_at_ragas,
handle_at_services, handle_at_web et handle_at_graph (ajouté après la table).
Effets : connexion SSH et écriture de Nokido.env, scan de ports par sockets ou
NetworkDiscovery, IDS scapy ou lecture de /proc/net/tcp, ingestion RAG, appels Ollama,
registre de services sauvé dans data/services.json. Crée data/ et logs/ à l'import.
Importé par Nokido.py, forge_commands et forge_dispatch (chargement paresseux).
Plusieurs noms utilisés ne sont pas définis ici (escape, settings, rag_engine...).
"""
from __future__ import annotations

# Imports oublies, mesures le 2026-09-08 : json.loads L761, os.environ L143.
# `Protocol` (L1057) n'est PAS ajoute : `protocol=Protocol.HTTP` designe un enum
# METIER et non typing.Protocol -- poser l'import typing masquerait le vrai
# symbole manquant. Reste a instruire : d'ou vient cet enum.
import json
import os

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_at_dispatch.py — Table de dispatch des commandes @
==========================================================
Extrait de Nokido.py (_handle_at) — v17 refactor.

Chaque fonction handle_at_X(app, cmd_line, parts, cmd)
correspond à un sous-bloc du dispatcher @.

Usage depuis _handle_at :
  from forge_at_dispatch import AT_DISPATCH
  handler = AT_DISPATCH.get(cmd)
  if handler: await handler(app, cmd_line, parts, cmd)
"""

import asyncio
import logging
from pathlib import Path
from rich.markup import escape
from nokido_agent.app.forge_logging import debug_log
from app.core.settings import get_app_attr as _g
from app.forge_agentic_engine import EvolutionOrchestrator
from app.forge_code import get_sandbox
from app.forge_mixin_patch import HAS_SANDBOX
from app.forge_network import MiniIDSAgent
from app.forge_network import NetworkDiscovery
from app.forge_ollama import ollama_stream
from app.forge_services import ServiceEndpoint
from app.forge_services import ServiceStatus
from app.forge_services import ServiceType

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("Nokido.AtDispatch")


# ──────────────────────────────────────────────────────────────────────
# @ssh
# ──────────────────────────────────────────────────────────────────────
async def handle_at_ssh(app, cmd_line: str, parts: list, cmd: str) -> object:
    """Handle at ssh.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    from nokido_agent.app.forge_app_context import get_settings as _gset, get_ssh as _gssh

    settings = getattr(app, "settings", None) or _gset()
    ssh_manager = getattr(app, "ssh_manager", None) or _gssh()
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    # ── Connexion vers une nouvelle cible SSH ────────────────────
    # @ssh <host> [user] [port] [keypath]
    # @ssh save   — enregistre la session courante dans Nokido.env
    # @ssh status — affiche la connexion courante
    _ssh_parts = cmd_line[4:].strip().split()
    _ssh_sub = _ssh_parts[0].lower() if _ssh_parts else "help"

    if _ssh_sub == "status":
        if ssh_manager is None:
            chat.write("[yellow]⚠ SSH non initialisé — configurez SSH_HOST dans Nokido.env[/]")
            return
        _sudo_s = "[green]oui[/]" if ssh_manager.sudo_available else "[yellow]non[/]"
        chat.write(
            "[bold]Connexion SSH courante :[/]\n"
            f"  Hôte : [bold]{settings.ssh_host or '—'}[/] "
            f"port={settings.ssh_port}  user=[bold]{settings.ssh_user or '—'}[/]\n"
            f"  Clé  : [dim]{settings.private_key_path or '—'}[/]\n"
            f"  Sudo : {_sudo_s}"
        )

    elif _ssh_sub == "save":
        # Écrire la config courante dans Nokido.env
        if not settings.ssh_host:
            chat.write("[yellow]⚠ Aucune connexion SSH active à sauvegarder.[/]")
        else:
            try:
                env_path = _ROOT_DIR / "Nokido.env"
                content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
                import re as _re2

                def _set_v(c, k, v) -> object:
                    """Set v.

                    Args:
                        c: Description.
                        k: Description.
                        v: Description.
                    """
                    pat = _re2.compile(rf"^{k}=.*$", _re2.MULTILINE)
                    ln = f"{k}={v}"
                    return pat.sub(ln, c) if pat.search(c) else c.rstrip("\n") + f"\n{ln}\n"

                content = _set_v(content, "SSH_HOST", settings.ssh_host)
                content = _set_v(content, "SSH_PORT", str(settings.ssh_port))
                content = _set_v(content, "SSH_USER", settings.ssh_user)
                content = _set_v(content, "PRIVATE_KEY_PATH", str(settings.private_key_path or ""))
                env_path.write_text(content, encoding="utf-8")
                chat.write("[green]✅ Connexion SSH enregistrée dans Nokido.env[/]")
            except Exception as _e:
                chat.write(f"[red]❌ Écriture Nokido.env : {escape(str(_e))}[/]")

    elif len(_ssh_parts) >= 1 and _ssh_sub not in ("help", "save", "status"):
        # @ssh <host> [user] [port] [keypath]
        _new_host = _ssh_parts[0]
        _new_user = _ssh_parts[1] if len(_ssh_parts) > 1 else settings.ssh_user
        _new_port = int(_ssh_parts[2]) if len(_ssh_parts) > 2 else settings.ssh_port
        _new_key = Path(_ssh_parts[3]) if len(_ssh_parts) > 3 else settings.private_key_path

        if not _new_user or not _new_key:
            chat.write(
                "[yellow]⚠ Usage : @ssh <host> [user] [port] [keypath][/]\n"
                "  Exemple : @ssh localhost admin 22 ~/.ssh/id_rsa\n"
                "  [dim]user/port/keypath optionnels si déjà configurés[/dim]"
            )
        else:
            chat.write(f"[dim]🔌 Connexion vers {_new_user}@{_new_host}:{_new_port}…[/]")

            async def _reconnect(_h=_new_host, _u=_new_user, _p=_new_port, _k=_new_key) -> None:
                """Reconnect.

                Args:
                    _h: Description.
                    _u: Description.
                    _p: Description.
                    _k: Description.
                """
                try:
                    from nokido_agent.app.forge_ssh import _strip_ssh_output

                    # Fermer la connexion existante
                    await ssh_manager.close()
                    # Mettre à jour settings en session
                    settings.ssh_host = _h
                    settings.ssh_user = _u
                    settings.ssh_port = _p
                    settings.private_key_path = _k
                    os.environ["SSH_HOST"] = _h
                    os.environ["SSH_USER"] = _u
                    os.environ["SSH_PORT"] = str(_p)
                    os.environ["PRIVATE_KEY_PATH"] = str(_k)
                    # Reconnecter
                    await ssh_manager.connect()
                    # Récupérer hostname
                    _hn, _kern = "", ""
                    try:
                        _o, _, _ = await ssh_manager.run("hostname -f 2>/dev/null || hostname")
                        _hn = _strip_ssh_output(_o)
                    except Exception:
                        _hn = _h
                    try:
                        _o2, _, _ = await ssh_manager.run("uname -r")
                        _kern = _strip_ssh_output(_o2)
                    except Exception:
                        pass
                    _ks = f" · [dim]kernel {_kern}[/]" if _kern else ""
                    chat.write(
                        f"[green]✅ SSH[/] [bold]{_hn}[/] [dim]({_h}:{_p})[/] "
                        f"{ssh_manager.os_type} privilege={'[green]' + ssh_manager.privilege_method + '[/]' if ssh_manager.sudo_available else '[yellow]none[/]'}{_ks}\n"
                        f"  [dim]@ssh save pour enregistrer dans Nokido.env[/]"
                    )
                    app._set_ssh_mode(True, hostname=_hn)
                    from nokido_agent.app.forge_app_context import _from_main

                    app.sub_title = f"v{_from_main('__version__', '?')} · {_hn}"
                except Exception as _err:
                    chat.write(f"[red]❌ SSH {_h} : {escape(str(_err))}[/]")

            asyncio.create_task(_reconnect())

    else:
        chat.write(
            "[bold]@ssh[/] <host> [user] [port] [keypath]  — connexion vers une nouvelle cible\n"
            "  @ssh status   — connexion active\n"
            "  @ssh save     — enregistre dans Nokido.env\n"
            "[dim]Exemples :\n"
            "  @ssh localhost\n"
            "  @ssh localhost admin 22 ~/.ssh/id_rsa[/]"
        )


# ──────────────────────────────────────────────────────────────────────
# @scan
# ──────────────────────────────────────────────────────────────────────
async def handle_at_scan(app, cmd_line: str, parts: list, cmd: str) -> tuple:
    """Handle at scan.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    # Drapeaux REELS du monolithe (Nokido.py les pose selon l'import de
    # nokido_agent.app.forge_network). L'ancienne heuristique cherchait la cle
    # « forge_network » dans sys.modules : un module importe sous son nom complet
    # y etait invisible, et le mode complet se croyait absent (29/09).
    HAS_SNIF = bool(_g("HAS_SNIF", False))
    HAS_IDS = bool(_g("HAS_IDS", False))
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    # ── Découverte réseau — snif.py complet ou fallback socket ───
    subnet = cmd_line[5:].strip() or "localhost/24"
    if HAS_SNIF:
        # Mode complet nmap+SNMP+mDNS+UPnP
        chat.write(f"[dim]🔍 Scan [bold]{subnet}[/] (mode complet)…[/]")

        async def do_scan(_subnet=subnet) -> None:
            """Do scan.

            Args:
                _subnet: Description.
            """
            try:
                nd = NetworkDiscovery(_subnet)
                # snif.py expose run() synchrone → on_thread pour ne pas bloquer
                import asyncio as _aio

                if hasattr(nd, "run_async"):
                    from nokido_agent.app.forge_app_context import get_rag

                    devs = await nd.run_async(inject_rag=get_rag())
                elif hasattr(nd, "scan_async"):
                    devs = await nd.scan_async()
                elif hasattr(nd, "run_subnet"):
                    devs = await _aio.to_thread(nd.run_subnet)
                elif hasattr(nd, "run"):
                    # méthode synchrone → thread pour ne pas bloquer l'event loop
                    devs = await _aio.to_thread(nd.run)
                elif hasattr(nd, "scan"):
                    devs = await _aio.to_thread(nd.scan)
                else:
                    meths = [m for m in dir(nd) if not m.startswith("_")]
                    raise AttributeError(f"NetworkDiscovery : aucune méthode de scan trouvée. Disponibles : {meths}")
                chat.write(f"[green]✅ {len(devs)} appareil(s) sur {_subnet} :[/]")
                for d in devs:
                    ip = d.get("ip", "?")
                    host = d.get("hostname") or ""
                    os_ = d.get("os") or ""
                    pts = ", ".join(str(p) for p in (d.get("ports") or [])[:6])
                    protos = ", ".join(d.get("protocols") or [])
                    line = f"  [bold]{ip:<16}[/]"
                    if host:
                        line += f" [dim]{host[:20]}[/]"
                    if os_:
                        line += f" · [#79c0ff]{os_[:30]}[/]"
                    if pts:
                        line += f" · ports:[cyan]{pts}[/]"
                    if protos:
                        line += f" · [#8b949e]{protos}[/]"
                    chat.write(line)
                # Afficher la topologie si NetworkX disponible
                topo = nd.topology_summary()
                if topo:
                    chat.write(f"[bold]Topologie ({len(topo)} nœuds) :[/]")
                    for node in topo[:8]:
                        neighbors = ", ".join(node["neighbors"][:4])
                        chat.write(f"  [dim]{node['node']:<16}[/] ↔ {neighbors or 'isolé'}")
                    if len(topo) > 8:
                        chat.write(f"  [dim]… +{len(topo) - 8} nœuds[/]")
                    chat.write("[dim]Résultats injectés dans le RAG ✅[/]")
                debug_log("SECU", "@scan", "Terminé", {"subnet": _subnet, "count": len(devs)})
            except Exception as _e:
                chat.write(f"[red]❌ Scan: {escape(str(_e))}[/]")

        asyncio.create_task(do_scan())
    else:
        # ── Fallback stdlib : socket pur, aucune dépendance externe ──
        import pathlib as _pls

        _miss2 = []
        for _p, _m in [
            ("python-nmap", "nmap"),
            ("zeroconf", "zeroconf"),
            ("miniupnpc", "miniupnpc"),
            ("pysnmp", "pysnmp"),
        ]:
            try:
                __import__(_m)
            except ImportError:
                _miss2.append(_p)
        _dir_s = _pls.Path(__file__).parent
        _hint = ""
        if _miss2:
            _hint = f"\n  [dim]Mode complet : pip install {' '.join(_miss2)} puis copie snif.py dans {_dir_s}[/]"
        else:
            _hint = f"\n  [dim]Mode complet : copie snif.py dans {_dir_s}[/]"
        chat.write(f"[dim]🔍 Scan [bold]{subnet}[/] (mode basique socket){_hint}[/]")

        async def do_scan_basic(_subnet=subnet) -> tuple:
            """Do scan basic.

            Args:
                _subnet: Description.
            """
            import ipaddress, socket as _sock, concurrent.futures as _cf

            try:
                net = ipaddress.ip_network(_subnet, strict=False)
            except ValueError:
                chat.write(f"[red]❌ Subnet invalide : {_subnet}[/]")
                return
            PORTS = [21, 22, 23, 25, 80, 443, 445, 3306, 3389, 8080, 8443, 8888, 161]
            TIMEOUT = 0.08  # 80ms — suffisant sur LAN

            def _probe(ip_s) -> tuple:
                """Probe.

                Args:
                    ip_s: Description.
                """
                open_p, hostname = [], ""
                for p in PORTS:
                    try:
                        s = _sock.socket()
                        s.settimeout(TIMEOUT)
                        if s.connect_ex((ip_s, p)) == 0:
                            open_p.append(p)
                        s.close()
                    except Exception:
                        pass
                if open_p:  # DNS seulement si hôte actif
                    try:
                        hostname = _sock.gethostbyaddr(ip_s)[0]
                    except Exception:
                        pass
                return ip_s, hostname, open_p

            hosts = [str(h) for h in list(net.hosts())[:254]]
            chat.write(f"[dim]  Sonde {len(hosts)} hôtes ({len(PORTS)} ports, timeout={int(TIMEOUT * 1000)}ms)…[/]")
            found = []
            loop = asyncio.get_event_loop()
            with _cf.ThreadPoolExecutor(max_workers=128) as ex:
                for ip_s, host, ports in await loop.run_in_executor(None, lambda: list(ex.map(_probe, hosts))):
                    if ports:
                        found.append((ip_s, host, ports))
            if found:
                chat.write(f"[green]✅ {len(found)} hôte(s) actif(s) :[/]")
                for ip_s, host, ports in sorted(found, key=lambda x: list(map(int, x[0].split(".")))):
                    svc = {
                        22: "SSH",
                        23: "Telnet",
                        80: "HTTP",
                        443: "HTTPS",
                        445: "SMB",
                        3389: "RDP",
                        3306: "MySQL",
                        21: "FTP",
                    }
                    line = f"  [bold]{ip_s:<16}[/]"
                    if host:
                        line += f" [dim]{host[:25]}[/]"
                    line += (
                        " · "
                        + "[cyan]"
                        + ", ".join(f"{p}({svc.get(p, '')})" if p in svc else str(p) for p in ports)
                        + "[/]"
                    )
                    chat.write(line)
            else:
                chat.write(f"[dim]Aucun hôte actif détecté sur {_subnet}[/]")
            debug_log("SECU", "@scan", "Terminé (basique)", {"subnet": _subnet, "count": len(found)})

        asyncio.create_task(do_scan_basic())


# ──────────────────────────────────────────────────────────────────────
# @ids
# ──────────────────────────────────────────────────────────────────────
async def handle_at_ids(app, cmd_line: str, parts: list, cmd: str) -> None:
    """Handle at ids.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    HAS_IDS = bool(_g("HAS_IDS", False))  # drapeau REEL du monolithe, cf. handle_at_scan
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    # ── IDS réseau — scapyshark.py complet ou fallback asyncio ───
    sub = parts[1].lower() if len(parts) > 1 else "help"
    iface = parts[2] if len(parts) > 2 else "eth0"
    if HAS_IDS:
        # Mode complet scapy+pyshark
        if sub == "start":
            _t = getattr(app, "_ids_task", None)
            if _t and not _t.done():
                chat.write("[yellow]⚠ IDS déjà actif — @ids stop[/]")
            else:
                chat.write(f"[dim]🛡 IDS démarré sur [bold]{iface}[/] (scapy)…[/]")
                _agent = MiniIDSAgent(iface=iface)

                async def _ids_alert(msg: str) -> None:
                    """Ids alert.

                    Args:
                        msg: Description.
                    """
                    try:
                        app._chat_log().write(f"[bold red]🚨 IDS:[/] {escape(str(msg))}")
                        debug_log("SECU", "IDS", "Alerte", {"msg": str(msg)[:120]})
                    except Exception:
                        pass

                _agent.alert = _ids_alert
                app._ids_agent = _agent
                app._ids_task = asyncio.create_task(_agent.run())
        elif sub == "stop":
            _t = getattr(app, "_ids_task", None)
            if _t and not _t.done():
                _t.cancel()
                chat.write("[green]✅ IDS arrêté[/]")
            else:
                chat.write("[dim]IDS non actif[/]")
        elif sub == "status":
            _t = getattr(app, "_ids_task", None)
            _ag = getattr(app, "_ids_agent", None)
            if _t and not _t.done():
                sus = sorted(_ag.suspect_ips) if _ag else []
                chat.write(f"[green]🛡 IDS actif[/] — {len(sus)} IP(s) suspecte(s)")
                for ip in sus[:10]:
                    chat.write(f"  [red]⚠[/] {ip}")
            else:
                chat.write("[dim]IDS inactif[/]")
        else:
            chat.write("[bold]@ids[/] start [iface] / stop / status")
    else:
        # ── Fallback asyncio : surveille /proc/net/tcp (Linux) ────
        import pathlib as _pli

        _dir_i = _pli.Path(__file__).parent
        _miss3 = []
        for _p3, _m3 in [("scapy", "scapy"), ("pyshark", "pyshark")]:
            try:
                __import__(_m3)
            except ImportError:
                _miss3.append(_p3)
        _hint_ids = (
            f" [dim](pip install {' '.join(_miss3)} + scapyshark.py dans {_dir_i} pour mode complet)[/]"
            if _miss3
            else f" [dim](copie scapyshark.py dans {_dir_i} pour mode complet)[/]"
        )
        if sub == "start":
            _t = getattr(app, "_ids_task_basic", None)
            if _t and not _t.done():
                chat.write("[yellow]⚠ IDS basique déjà actif — @ids stop[/]")
            else:
                chat.write(f"[dim]🛡 IDS basique démarré{_hint_ids}[/]")
                app._ids_suspects: dict = {}
                _SVC = {
                    22: "SSH",
                    23: "Telnet",
                    80: "HTTP",
                    443: "HTTPS",
                    3389: "RDP",
                    445: "SMB",
                    3306: "MySQL",
                    5432: "PG",
                    21: "FTP",
                    25: "SMTP",
                    53: "DNS",
                }

                async def _ids_basic_loop(_svc=_SVC) -> None:
                    """Ids basic loop.

                    Args:
                        _svc: Description.
                    """
                    _prev = set()
                    while True:
                        try:
                            conns = set()
                            try:
                                with open("/proc/net/tcp") as f:
                                    for ln in f.readlines()[1:]:
                                        p_ = ln.split()
                                        if len(p_) < 4 or p_[3] != "01":
                                            continue
                                        rem = p_[2]
                                        ih, ph = rem.split(":")
                                        ip_s = ".".join(str(int(ih[i : i + 2], 16)) for i in (6, 4, 2, 0))
                                        port = int(ph, 16)
                                        if port in _svc:
                                            conns.add((ip_s, port, _svc[port]))
                            except (FileNotFoundError, PermissionError):
                                pass
                            for ip_s, port, svc_n in conns - _prev:
                                app._ids_suspects[ip_s] = app._ids_suspects.get(ip_s, 0) + 1
                                cnt = app._ids_suspects[ip_s]
                                col = "#ff7b72" if cnt > 3 else "#f0883e"
                                app._chat_log().write(
                                    f"[bold {col}]🛡 IDS:[/] {svc_n} depuis {ip_s}:{port}"
                                    + (f" [red bold]— SUSPECT ×{cnt}[/]" if cnt > 3 else "")
                                )
                                debug_log("SECU", "IDS_BASIC", "Connexion", {"ip": ip_s, "svc": svc_n, "count": cnt})
                            _prev = conns
                        except Exception as _e:
                            logger.debug(f"IDS basic: {_e}")
                        await asyncio.sleep(5)

                app._ids_task_basic = asyncio.create_task(_ids_basic_loop())
        elif sub == "stop":
            _t = getattr(app, "_ids_task_basic", None)
            if _t and not _t.done():
                _t.cancel()
                chat.write("[green]✅ IDS basique arrêté[/]")
            else:
                chat.write("[dim]IDS non actif[/]")
        elif sub == "status":
            _t = getattr(app, "_ids_task_basic", None)
            sus = getattr(app, "_ids_suspects", {})
            if _t and not _t.done():
                chat.write(f"[green]🛡 IDS basique actif[/] — {len(sus)} IP(s) vues")
                for ip_s, cnt in sorted(sus.items(), key=lambda x: -x[1])[:10]:
                    chat.write(f"  {'[red]' if cnt > 3 else '[yellow]'}{ip_s}[/] ×{cnt}")
            else:
                chat.write(f"[dim]IDS inactif — @ids start{_hint_ids}[/]")
        else:
            chat.write(f"[bold]@ids[/] start / stop / status{_hint_ids}")


# ──────────────────────────────────────────────────────────────────────
# @agentic
# ──────────────────────────────────────────────────────────────────────
async def handle_at_agentic(app, cmd_line: str, parts: list, cmd: str) -> None:
    """Handle at agentic.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    from nokido_agent.app.forge_app_context import get_agentic

    agentic_engine = get_agentic()
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    _ag_offset = len(cmd) + 1
    parts_ag = cmd_line[_ag_offset:].strip().split(None, 1)
    sub_ag = parts_ag[0].lower() if parts_ag else "help"
    arg_ag = parts_ag[1] if len(parts_ag) > 1 else ""

    if sub_ag in ("search", "find", "learn"):
        # @disco search <query> — unified_discovery
        if not arg_ag:
            chat.write("[bold #a371f7]@disco search[/] [dim]<query>[/] — recherche web + ancrage RAG")
            return
        try:
            from nokido_agent.app.forge_unified_discovery import unified_discovery as _ud

            chat.write("[dim]🔍 Unified Discovery: " + arg_ag[:60] + "...[/]")
            res = _ud(arg_ag, notify_core=True)
            anchored = res.get("chunks_anchored", 0)
            cached = res.get("from_cache", False)
            icon = "🧠" if cached else "✅"
            chat.write(
                icon
                + " [bold #a371f7]Discovery[/] "
                + ("[dim]depuis cache RAG[/]" if cached else str(anchored) + " pépite(s) vectorisée(s)")
                + chr(10)
                + "[dim]Collection:[/] "
                + res.get("collection", "disco")
                + chr(10)
                + "[dim]Tag:[/] "
                + res.get("tag", "#disco_unified")
                + chr(10)
                + "[dim]Permanent:[/] "
                + str(res.get("permanent", False))
            )
            if res.get("top_chunks"):
                for i, chunk in enumerate(res["top_chunks"][:2], 1):
                    chat.write("[dim]Pépite " + str(i) + ":[/] " + chunk[:100])
        except Exception as e:
            chat.write("[red]❌ unified_discovery: " + str(e) + "[/]")
        return

    if sub_ag == "skills":
        if agentic_engine:
            skills = agentic_engine.get_skill_summary()
            if skills:
                chat.write("[bold #a371f7]🧠 Compétences RAG :[/]")
                for s in skills:
                    v = "🏆" if s["verified"] else ("✅" if s["status"] == "mastered" else "🧪")
                    chat.write(
                        f"  {v} [bold]{s['name']:<12}[/] "
                        f"score=[cyan]{s['score']:.2f}[/] "
                        f"uses={s['uses']} "
                        f"{'[green]VERIFIED[/]' if s['verified'] else '[yellow]UNVERIFIED[/]'}"
                    )
            else:
                chat.write("[dim]Aucune compétence enregistrée. @agentic run <tâche>[/dim]")
        else:
            chat.write("[yellow]AgenticEngine non initialisé[/]")

    elif sub_ag == "clear":
        if agentic_engine:
            agentic_engine._skills.clear()
            agentic_engine._save_skills()
            app.skill_panel.clear_skills()
            chat.write("[dim]Registre de compétences vidé.[/dim]")

    elif sub_ag == "verify":
        # Forcer re-vérification de toutes les compétences
        if agentic_engine:

            async def _reverify() -> None:
                """Reverify."""
                from nokido_agent.app.forge_app_context import app_ctx as _actx

                _ac = _actx()
                agentic_engine = _ac.agentic_engine
                for skill in list(agentic_engine._skills.keys()):
                    score = await agentic_engine.check_competence(skill)
                    agentic_engine._skills[skill].score = score
                agentic_engine._save_skills()
                app.skill_panel.render_summary(agentic_engine.get_skill_summary())
                chat.write("[green]✅ Re-vérification terminée[/]")

            asyncio.create_task(_reverify())
        else:
            chat.write("[yellow]AgenticEngine non initialisé[/]")

    elif sub_ag in ("run", "") or (sub_ag not in ("skills", "clear", "verify", "help") and sub_ag):
        # @agentic <tâche> — analyser et préparer les compétences
        task_text = cmd_line[_ag_offset:].strip()
        if sub_ag == "run":
            task_text = arg_ag
        if not task_text:
            chat.write(
                "[bold]@agentic[/] <tâche>  — analyse les compétences requises\n"
                "  skills  — liste les compétences enregistrées\n"
                "  verify  — re-vérifie tous les scores\n"
                "  clear   — remet à zéro le registre\n"
                "[dim]Exemple : @agentic configure un VPN WireGuard avec authentification[/dim]"
            )
        elif not agentic_engine:
            chat.write("[red]❌ AgenticEngine non initialisé[/]")
        else:

            async def _run_agentic(_t=task_text) -> None:
                """Run agentic.

                Args:
                    _t: Description.
                """
                try:
                    result = await agentic_engine.process_complex_task(_t)
                    s_list = ", ".join(result["skills"])
                    miss = ", ".join(result["missing"]) if result["missing"] else "aucune"
                    chat.write(
                        f"[bold]Compétences analysées :[/] {s_list}\n"
                        f"  Manquantes : [yellow]{miss}[/]\n"
                        f"  Prêt : {'[green]OUI ✅[/]' if result['ready'] else '[yellow]NON — apprentissage en cours[/]'}"
                    )
                    # Rafraîchir le panneau
                    app.skill_panel.render_summary(agentic_engine.get_skill_summary())
                except Exception as _err:
                    chat.write(f"[red]❌ @agentic : {escape(str(_err))}[/]")

            asyncio.create_task(_run_agentic())

    else:
        chat.write(
            "[bold]@agentic[/] <tâche> | skills | verify | clear\n"
            "[dim]Analyse les compétences RAG requises pour une tâche complexe.\n"
            "Déclenche l'apprentissage automatique si une compétence est insuffisante.[/dim]"
        )


# ──────────────────────────────────────────────────────────────────────
# @evolve
# ──────────────────────────────────────────────────────────────────────
async def handle_at_evolve(app, cmd_line: str, parts: list, cmd: str) -> None:
    """Handle at evolve.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    settings = _ac.settings
    version_manager = _ac.version_manager
    # ── Cycle auto-évolution RAG ─────────────────────────────────
    parts_ev = cmd_line[7:].strip().split(None, 1)
    sub_ev = parts_ev[0].lower() if parts_ev else "start"
    arg_ev = parts_ev[1] if len(parts_ev) > 1 else ""

    if sub_ev in ("start", "") or (sub_ev not in ("status", "bench", "scores", "help") and sub_ev):
        # @evolve <query> — lancer le cycle avec la query donnée
        query_ev = cmd_line[7:].strip() if sub_ev not in ("start", "status", "bench", "scores", "help") else arg_ev
        if not query_ev:
            chat.write(
                "[bold]@evolve[/] <requête>  — cycle auto-évolution RAG\n"
                "  Exemple : @evolve comment mieux détecter les switches Cisco\n"
                "  [dim]status — état · bench — lancer benchmark · scores — afficher scores[/dim]"
            )
        else:
            if not rag_engine:
                chat.write("[red]❌ RAG non initialisé[/]")
            else:
                _evo = EvolutionOrchestrator(
                    ollama_url=settings.ollama_url,
                    vm=version_manager,
                    rag=rag_engine,
                    sandbox=get_sandbox(settings.ollama_url, rag_engine) if HAS_SANDBOX else None,
                    log_fn=lambda m: chat.write(m),
                )
                # Extraire max_cycles si specifie ex: @evolve query #10
                _max_c = 5
                if query_ev.endswith(tuple(f"#{i}" for i in range(1, 21))):
                    try:
                        _max_c = int(query_ev.rsplit("#", 1)[-1])
                        query_ev = query_ev.rsplit("#", 1)[0].strip()
                    except ValueError:
                        pass

                async def _run_evo(_q=query_ev, _e=_evo, _mc=_max_c) -> None:
                    """Run evo.

                    Args:
                        _q: Description.
                        _e: Description.
                        _mc: Description.
                    """
                    try:
                        result = await _e.run_cycles(_q, max_cycles=_mc)
                    except Exception as _err:
                        chat.write(f"[red]❌ @evolve : {escape(str(_err))}[/]")

                asyncio.create_task(_run_evo())

    elif sub_ev == "bench":
        if not rag_engine:
            chat.write("[red]❌ RAG non initialisé[/]")
        else:
            chat.write("[dim]⏳ Benchmark RAG en cours…[/dim]")

            async def _bench_only() -> None:
                """Bench only."""
                from nokido_agent.app.forge_app_context import app_ctx as _actx

                _ac = _actx()
                rag_engine = _ac.rag_engine
                settings = _ac.settings
                version_manager = _ac.version_manager
                _e = EvolutionOrchestrator(
                    ollama_url=settings.ollama_url,
                    vm=version_manager,
                    rag=rag_engine,
                    log_fn=lambda m: chat.write(m),
                )
                score = await _e._run_benchmark()
                chat.write(f"[bold]Score benchmark RAG : {score:.3f}[/bold]")

            asyncio.create_task(_bench_only())

    elif sub_ev == "scores":
        _sf = _DATA_DIR / "last_scores.json"
        if _sf.exists():
            try:
                _sc = json.loads(_sf.read_text())
                chat.write(f"[bold]Dernier score benchmark :[/bold] {_sc.get('avg', 0):.3f}")
            except Exception:
                chat.write("[dim]Fichier scores illisible[/dim]")
        else:
            chat.write("[dim]Aucun score benchmark enregistré — @evolve bench[/dim]")

    elif sub_ev == "bootstrap":
        # @evolve bootstrap — auto-ingestion structuree (3 rings)
        if not rag_engine:
            chat.write("[red]RAG non initialise[/]")
        else:

            async def _do_bootstrap() -> None:
                """Do bootstrap."""
                try:
                    from nokido_agent.app.forge_ingest_self import force_self_ingestion as _fsi

                    await _fsi(rag_engine, log_fn=chat.write)
                except Exception as _eb:
                    chat.write(f"[red]@evolve bootstrap : {_eb}[/]")

            asyncio.create_task(_do_bootstrap())

    elif sub_ev == "ingest":
        if not arg_ev:
            chat.write(
                "[bold]@evolve ingest[/] <texte|domaine:texte>\n"
                "  Force ingestion savoir dans RAG + benchmark avant/apres.\n"
                "  [dim]Ex : @evolve ingest security: SNMPv3 est plus sur[/]"
            )
        elif not rag_engine:
            chat.write("[red]RAG non initialise[/]")
        else:

            async def _do_ingest(_text=arg_ev) -> None:
                """Do ingest.

                Args:
                    _text: Description.
                """
                try:
                    _evo_i = EvolutionOrchestrator(
                        ollama_url=settings.ollama_url,
                        vm=version_manager,
                        rag=rag_engine,
                        log_fn=lambda m: chat.write(m),
                    )
                    chat.write("[dim]Benchmark avant...[/]")
                    _score_before = await _evo_i._run_benchmark()
                    _domain, _content = "general", _text
                    if ":" in _text[:20] and not _text.startswith("http"):
                        _domain, _content = _text.split(":", 1)
                        _domain = _domain.strip().lower()
                        _content = _content.strip()
                    chat.write(f"[dim]Ingestion domaine={_domain}...[/]")
                    await rag_engine.add_session_message("evolve_ingest", _domain, f"[EVOLVE INGEST] {_content}")
                    _score_after = await _evo_i._run_benchmark()
                    _delta = _score_after - _score_before
                    _col = "[green]" if _delta >= 0 else "[red]"
                    chat.write(
                        f"[bold]Ingestion OK[/]\n"
                        f"  Avant : {_score_before:.3f}\n"
                        f"  Apres : {_score_after:.3f}\n"
                        f"  Delta : {_col}{_delta:+.3f}[/]"
                    )
                except Exception as _ei:
                    chat.write(f"[red]@evolve ingest : {_ei}[/]")

            asyncio.create_task(_do_ingest())

    else:
        chat.write(
            "[bold]@evolve[/] <requête>\n"
            "  @evolve <query>            — cycles jusqu'à convergence (défaut 5)\n"
            "  @evolve <query> #10        — forcer 10 cycles max\n"
            "  @evolve bootstrap          — ingestion forcée contexte projet\n"
            "  @evolve ingest <texte>     — ingestion savoir + benchmark\n"
            "  @evolve bench              — benchmark seul\n"
            "  @evolve scores             — dernier score\n"
            "[dim]ingest accepte prefixe domaine: security: reseau: debug:[/dim]"
        )


# ──────────────────────────────────────────────────────────────────────
# @ollama
# ──────────────────────────────────────────────────────────────────────
async def handle_at_ollama(app, cmd_line: str, parts: list, cmd: str) -> None:
    """Handle at ollama.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    args = cmd_line[len(cmd) :].strip()
    sub = args.lower() if args else "status"
    if sub in ("connect", "reconnect", "start", ""):
        chat.write("[dim]⏳ Reconnexion Ollama…[/]")
        await app._check_ollama_models()
    elif sub == "status":
        try:
            import aiohttp as _aio_ol
            from nokido_agent.app.forge_app_context import get_settings

            settings = get_settings()

            async with _aio_ol.ClientSession() as _s_ol:
                async with _s_ol.get(settings.ollama_tags_url, timeout=_aio_ol.ClientTimeout(total=3)) as _r_ol:
                    _models = [m["name"] for m in (await _r_ol.json()).get("models", [])]
                    chat.write(f"[green]✅ Ollama actif[/] — {len(_models)} modèles : {', '.join(_models[:5])}")
        except Exception as _e_ol:
            chat.write(f"[red]❌ Ollama hors ligne : {_e_ol}[/]")
        # Statut LiteLLM fallback
        try:
            from nokido_agent.app.forge_litellm_bridge import get_litellm_bridge as _gll

            _ll = _gll()
            _ll_st = _ll.status()
            _ll_icon = "[green]✅[/]" if _ll_st["has_litellm"] else "[yellow]⚠[/]"
            chat.write(f"{_ll_icon} LiteLLM fallback — modèle=[bold]{_ll_st['model']}[/] base={_ll_st['api_base']}")
            if not _ll_st["has_litellm"]:
                chat.write("  [dim]pip install litellm pour activer[/]")
        except Exception:
            pass
    elif sub == "models":
        await app._select_model()
    else:
        chat.write(
            "[bold]@ollama[/] [connect|status|models]\n"
            "  connect — relancer la détection Ollama à chaud\n"
            "  status  — vérifier si Ollama répond\n"
            "  models  — changer le modèle actif"
        )


# ──────────────────────────────────────────────────────────────────────
# @ragas
# ──────────────────────────────────────────────────────────────────────
async def handle_at_ragas(app, cmd_line: str, parts: list, cmd: str) -> None:
    """Handle at ragas.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    from nokido_agent.app.forge_app_context import get_rag as _gr

    rag_engine = _gr()
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    _ra = cmd_line[6:].strip()
    if not rag_engine:
        chat.write("[yellow]⚠ RAG non initialisé[/]")
    elif not _ra:
        chat.write(
            "[bold]@ragas[/] <question>\n  Évalue la qualité du pipeline RAG sur une question test.\n  Mesure : context_relevancy · answer_relevancy · faithfulness · precision\n[dim]Exemple : @ragas comment configurer wireguard[/]"
        )
    else:
        chat.write(f"[dim]📊 RAGAS : évaluation sur '{_ra[:50]}'…[/]")
        try:
            docs = (
                await rag_engine.smart_search(_ra, k=5, use_hyde=True)
                if hasattr(rag_engine, "smart_search")
                else await rag_engine.search(_ra, k=5)
            )
            _ctx = "\n".join(d.get("content", "")[:300] for d in docs[:3])
            # Verifier Ollama avant de generer
            # Utiliser l'etat Ollama deja connu par la TUI
            # plutot que de re-checker via HTTP (evite faux negatifs)
            _ollama_ok = bool(getattr(app, "model_chat", None) and not getattr(app, "_ollama_offline", False))
            _answer = ""
            if _ollama_ok:
                try:
                    _answer = await asyncio.wait_for(
                        ollama_stream(
                            app.model_rag or app.model_chat,
                            [
                                {
                                    "role": "user",
                                    "content": "Contexte :\n"
                                    + _ctx
                                    + "\n\nQuestion : "
                                    + _ra
                                    + "\nReponds de maniere concise.",
                                }
                            ],
                            lambda _: None,
                            lambda: None,
                        ),
                        timeout=30.0,
                    )
                except Exception:
                    _ollama_ok = False
            m = rag_engine.ragas_evaluate(_ra, _answer, docs)

            def _b(v):
                """b."""
                return "█" * int(v * 10) + "░" * (10 - int(v * 10))

            chat.write(
                f"[bold]📊 RAGAS — {_ra[:40]}[/]\n"
                f"  Context Relevancy : {_b(m['context_relevancy'])} {m['context_relevancy']:.1%}\n"
                f"  Answer Relevancy  : {_b(m['answer_relevancy'])} {m['answer_relevancy']:.1%}\n"
                f"  Faithfulness      : {_b(m['faithfulness'])} {m['faithfulness']:.1%}\n"
                f"  Context Precision : {_b(m['context_precision'])} {m['context_precision']:.1%}\n"
                f"  [bold]Overall           : {_b(m['overall'])} {m['overall']:.1%}[/]\n"
                f"[dim]  {len(docs)} docs - reponse {len(_answer)} chars[/]"
            )
            if not _ollama_ok:
                chat.write(
                    "[yellow]Ollama hors ligne[/] [dim]\u2014 evaluation partielle (RAG only)[/]\n"
                    "  [dim]Answer Relevancy et Faithfulness necessitent Ollama pour generer une reponse.[/]\n"
                    "  [dim]Lance Ollama puis retente pour un score complet.[/]"
                )
                if docs:
                    chat.write("[bold]Sources RAG trouvees :[/]")
                    for i, d in enumerate(docs[:3], 1):
                        src_label = d.get("source", "?")
                        content = d.get("content", "")[:200].replace("\n", " ")
                        score = d.get("score", 0)
                        chat.write(
                            f"  [bold cyan]{i}.[/] [dim]{src_label}[/]"
                            + (f" [dim](score={score:.2f})[/]" if score else "")
                            + f"\n     {content}"
                        )
                else:
                    chat.write("[red]Aucun document trouve dans le RAG pour cette question.[/]")
        except Exception as _re:
            chat.write(f"[red]RAGAS erreur : {_re}[/]")


# ──────────────────────────────────────────────────────────────────────
# @services
# ──────────────────────────────────────────────────────────────────────
async def handle_at_services(app, cmd_line: str, parts: list, cmd: str) -> NoneType:
    """Handle at services.

    Args:
        app: Description.
        cmd_line: Description.
        parts: Description.
        cmd: Description.
    """
    from nokido_agent.app.forge_app_context import has_services as _hsvc

    HAS_SERVICES = _hsvc()
    try:
        from nokido_agent.app.forge_services import get_registry
    except ImportError:
        """Get registry."""

        def get_registry() -> None:
            """Get registry."""
            return None

    from nokido_agent.app.forge_app_context import has_services as _hsvc

    HAS_SERVICES = _hsvc()
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    chat = app._chat_log()
    _sa = cmd_line[9:].strip()
    if not HAS_SERVICES:
        chat.write("[yellow]⚠ forge_services.py non disponible[/]")
    else:
        reg = get_registry()
        if not _sa or _sa == "status":
            # Healthcheck + affichage
            chat.write("[dim]🔍 Vérification des services…[/]")
            results = await reg.check_all()
            chat.write(reg.summary())
            # Afficher statut Hub v17
            try:
                from nokido_agent.app.forge_hub_client import hub as _hub

                chat.write(_hub.status_report())
            except Exception:
                pass
        elif _sa == "list":
            for ep in reg.all():
                chat.write(f"  {ep.name} → {ep.type.value} {ep.protocol.value}://{ep.host}:{ep.port}{ep.path}")
        elif _sa.startswith("add "):
            # @services add llm myserver localhost 5000 /v1/chat/completions
            _parts = _sa[4:].split()
            if len(_parts) < 4:
                chat.write("[red]Usage: @services add <type> <nom> <host> <port> [path] [api_key][/]")
            else:
                _stype, _sname, _shost, _sport = _parts[:4]
                _spath = _parts[4] if len(_parts) > 4 else ""
                _skey = _parts[5] if len(_parts) > 5 else ""
                try:
                    from nokido_agent.app.forge_services import (
                        Protocol,
                        ServiceEndpoint,
                        ServiceStatus,
                        ServiceType,
                    )

                    ep = ServiceEndpoint(
                        name=_sname,
                        type=ServiceType(_stype),
                        protocol=Protocol.HTTP,
                        host=_shost,
                        port=int(_sport),
                        path=_spath,
                        api_key=_skey,
                        priority=5,
                        tags=["manual"],
                        metadata={"format": "openai", "models_path": "/v1/models"} if _stype == "llm" else {},
                    )
                    reg.register(ep)
                    reg.save()
                    status = await reg.check_health(_sname)
                    _icon = "✅" if status == ServiceStatus.HEALTHY else "⚠️"
                    chat.write(f"[green]{_icon} Service {_sname} ajouté ({_shost}:{_sport}) — {status.value}[/]")
                except Exception as _se:
                    chat.write(f"[red]❌ Erreur : {_se}[/]")
        elif _sa.startswith("rm "):
            _rname = _sa[3:].strip()
            reg.unregister(_rname)
            reg.save()
            chat.write(f"[dim]Service {_rname} supprimé[/]")
        elif _sa == "save":
            reg.save(_DATA_DIR / "services.json")
            chat.write("[green]✅ Services sauvegardés → data/services.json[/]")
        else:
            chat.write(
                "[bold]@services[/] status | list | add | rm | save\n"
                "  [bold]status[/]  — healthcheck tous les endpoints\n"
                "  [bold]list[/]    — liste les services enregistrés\n"
                "  [bold]add[/] <type> <nom> <host> <port> [path] [key]\n"
                "          types: llm, rag, audit, sidecar, ssh, storage\n"
                "  [bold]rm[/] <nom> — supprime un service\n"
                "  [bold]save[/]    — persiste dans data/services.json\n"
                "[dim]Exemple: @services add llm nas-ollama localhost 11434 /api/chat[/]"
            )


# ══════════════════════════════════════════════════════════════════════
# TABLE DE DISPATCH
# ══════════════════════════════════════════════════════════════════════


async def handle_at_web(app, cmd_line: str, parts: list, cmd: str) -> None:
    """@web on/off/status/toggle -- controle la recherche web DuckDuckGo."""
    from nokido_agent.app.forge_web import toggle_web_search, is_web_search_enabled

    chat = app._chat_log()
    sub = parts[1].lower() if len(parts) > 1 else "toggle"
    if sub == "on":
        toggle_web_search(True)
        chat.write("[bold green]Web search ACTIVE[/] -- DuckDuckGo disponible")
    elif sub == "off":
        toggle_web_search(False)
        chat.write("[bold yellow]Web search DESACTIVE[/] -- mode hors-ligne")
    elif sub == "status":
        enabled = is_web_search_enabled()
        chat.write("[bold]Web search:[/] " + ("ACTIVE" if enabled else "DESACTIVE"))
        chat.write("[dim]@web on | @web off | @web (toggle)[/]")
    else:
        new_state = toggle_web_search()
        chat.write("[bold green]Web search ACTIVE[/]" if new_state else "[bold yellow]Web search DESACTIVE[/]")


AT_DISPATCH: dict = {
    "@ssh": handle_at_ssh,
    # `@graph` n'est PAS ici : `handle_at_graph` est defini plus bas dans ce
    # fichier, et le citer a cet endroit levait un NameError AU CHARGEMENT du
    # module -- il figurait meme DEUX FOIS, vestige d'une insertion maladroite.
    # L'entree est ajoutee apres la definition, tout en bas. Meme faute que
    # l'incident du 2026-08-19 : un nom lie APRES son usage rend le module
    # inimportable, et `ast.parse` ne voit rien puisque la syntaxe est correcte.
    "@scan": handle_at_scan,
    "@ids": handle_at_ids,
    "@agentic": handle_at_agentic,
    "@evolve": handle_at_evolve,
    "@ollama": handle_at_ollama,
    "@ragas": handle_at_ragas,
    "@services": handle_at_services,
    "@web": handle_at_web,
}


async def handle_at_graph(app, cmd_line: str, parts: list, cmd: str) -> object:
    """Graph universel Nokido - RAG vectoriel, AST code, CSV, analyse, raisonnement LLM."""
    import asyncio

    chat = app._chat_log()
    sub = parts[1].lower() if len(parts) > 1 else "help"
    args = parts[2:]
    try:
        from nokido_agent.app.forge_graph_universal import UniversalGraph
    except ImportError as e:
        chat.write(f"[red]forge_graph_universal non disponible: {e}[/]")
        return
    if not hasattr(app, "_graph_current"):
        app._graph_current = None
    db_path = str(_ROOT_P / "RAG" / "embeddings.db")

    if sub == "rag":
        domain = args[0] if args else None
        thr = float(args[1]) if len(args) > 1 else 0.82
        mx = int(args[2]) if len(args) > 2 else 200
        chat.write(f"[cyan]Graph RAG[/] domain={domain or 'all'} thr={thr}...")
        try:
            g = UniversalGraph.from_rag(db_path=db_path, domain_filter=domain, sim_threshold=thr, max_nodes=mx)
            app._graph_current = g
            s = g.stats()
            chat.write(f"[green]OK[/] {s['nodes']} noeuds {s['edges']} aretes density={s['density']}")
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "code":
        path = " ".join(args)
        if not path:
            chat.write("[yellow]Usage: @graph code <fichier.py>[/]")
            return
        try:
            g = UniversalGraph.from_code(path)
            app._graph_current = g
            s = g.stats()
            chat.write(f"[green]AST[/] {s['nodes']} fonctions {s['edges']} appels")
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "csv":
        if not args:
            chat.write("[yellow]Usage: @graph csv <edges.csv> [nodes.csv][/]")
            return
        try:
            g = UniversalGraph.from_csv(args[0], args[1] if len(args) > 1 else None)
            app._graph_current = g
            s = g.stats()
            chat.write(f"[green]CSV[/] {s['nodes']} noeuds {s['edges']} aretes")
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "stats":
        if app._graph_current is None:
            chat.write("[yellow]Pas de graphe actif - @graph rag d'abord[/]")
            return
        s = app._graph_current.stats()
        chat.write("[bold]Stats:[/]\n" + "\n".join(f"  {k}: {v}" for k, v in s.items()))

    elif sub == "top":
        if app._graph_current is None:
            chat.write("[yellow]Pas de graphe actif[/]")
            return
        n = int(args[0]) if args else 10
        metric = args[1] if len(args) > 1 else "betweenness"
        try:
            top = app._graph_current.top_central_nodes(n=n, metric=metric)
            g = app._graph_current
            out = [f"[bold]Top {n} ({metric}):[/]"]
            for nid, score in top:
                label = g._nodes[nid].label[:60] if nid in g._nodes else nid
                out.append(f"  {score:.4f}  {label}")
            chat.write("\n".join(out))
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "communities":
        if app._graph_current is None:
            chat.write("[yellow]Pas de graphe actif[/]")
            return
        algo = args[0] if args else "label_propagation"
        try:
            comms = app._graph_current.communities(algo)
            g = app._graph_current
            out = [f"[bold]{len(comms)} communautes ({algo}):[/]"]
            for cid, members in sorted(comms.items(), key=lambda x: -len(x[1]))[:6]:
                sample = [g._nodes[m].label[:35] for m in members[:2] if m in g._nodes]
                out.append(f"  Comm {cid} ({len(members)} noeuds): {sample}")
            chat.write("\n".join(out))
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "search":
        if app._graph_current is None or not args:
            chat.write("[yellow]Usage: @graph search <query>[/]")
            return
        q = " ".join(args)
        results = app._graph_current.semantic_search(q, top_k=8)
        g = app._graph_current
        out = [f"[bold]Recherche '{q}':[/]"]
        for nid, score in results:
            label = g._nodes[nid].label[:65] if nid in g._nodes else nid
            dom = g._nodes[nid].domain if nid in g._nodes else "?"
            out.append(f"  [{dom}] {score:.3f}  {label}")
        chat.write("\n".join(out))

    elif sub == "mermaid":
        if app._graph_current is None:
            chat.write("[yellow]Pas de graphe actif[/]")
            return
        n_e = int(args[0]) if args else 20
        chat.write(f"```mermaid\n{app._graph_current.to_mermaid(n_e)}\n```")

    elif sub == "path":
        if app._graph_current is None or len(args) < 2:
            chat.write("[yellow]Usage: @graph path <src> <dst>[/]")
            return
        try:
            p = app._graph_current.shortest_path(args[0], " ".join(args[1:]))
            if p:
                chat.write(f"[bold]Chemin ({len(p)} noeuds):[/] " + " -> ".join(p))
            else:
                chat.write("[yellow]Aucun chemin[/]")
        except Exception as e:
            chat.write(f"[red]{e}[/]")

    elif sub == "ask":
        if app._graph_current is None or not args:
            chat.write("[yellow]Usage: @graph ask <question>[/]")
            return
        question = " ".join(args)
        prompt = app._graph_current.ask(question)
        if hasattr(app, "_llm_query"):
            try:
                answer = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: app._llm_query(prompt)), timeout=30
                )
                chat.write(f"[bold]Graph reasoning:[/]\n{answer}")
            except Exception:
                chat.write(f"[dim]{prompt[:400]}...[/]")
        else:
            chat.write(f"[dim]{prompt[:400]}...[/]")

    elif sub == "clear":
        app._graph_current = None
        chat.write("[green]Graphe efface[/]")

    else:
        chat.write(
            "[bold]@graph — Universal Graph Engine[/]\n"
            "  @graph rag [domain] [thr] [max]   — graphe semantique RAG\n"
            "  @graph code <fichier.py>           — graphe AST Python\n"
            "  @graph csv <edges> [nodes]         — graphe CSV\n"
            "  @graph stats                       — statistiques\n"
            "  @graph top [n] [metric]            — noeuds centraux\n"
            "  @graph communities [algo]          — communautes\n"
            "  @graph search <query>              — recherche semantique\n"
            "  @graph ask <question>              — raisonnement LLM\n"
            "  @graph mermaid [n]                 — export Mermaid\n"
            "  @graph path <src> <dst>            — chemin court\n"
            "  @graph clear                       — effacer\n"
            "  Domaines: code|general|forge_core|systeme|securite|reseau|ia"
        )


# LIAISON APRES DEFINITION. `handle_at_graph` existe seulement a partir d'ici :
# c'est donc ici, et pas dans le litteral plus haut, que `@graph` rejoint la
# table de dispatch. Sans cette ligne, la commande serait silencieusement
# absente -- une capacite ecrite mais jamais atteignable.
AT_DISPATCH["@graph"] = handle_at_graph
