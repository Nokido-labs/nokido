"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_dispatch_network
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_dispatch_network.py — Handlers réseau pour Nokido
=========================================================
Extrait de Nokido.py — zéro régression, pattern mixin.

Contient :
  handle_scan(app, args)   — @scan  : découverte réseau nmap/SNMP/mDNS
  handle_ids(app, args)    — @ids   : IDS réseau temps réel
  handle_chain(app, args)  — @chain : pipeline d'outils @ enchaînés
  handle_switch(app, args) — @switch: récupération config switch/routeur

Simplifications v2 :
  - _post_scan() factorise registry+RAG commun aux deux modes scan
  - handle_ids() factorise start/stop/status _g('HAS_IDS', False) vs fallback
  - _missing_lib_msg() factorise le message pip install
  - except Exception: pass → logger.debug() ou supprimés
  - _g() résolu une seule fois par fonction
"""


import asyncio
import logging
import re as _re
import sys as _sys
from rich.markup import escape

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS — accès lazy aux globaux Nokido
# =============================================================================


def _main() -> object:
    """Main."""
    return _sys.modules.get("__main__")


from app.core.settings import get_app_attr as _g
from nokido_agent.app import forge_context  # noqa: F401


def _debug_log(hyp: str, loc: str, msg: str, data: dict | None = None) -> None:
    """Debug log.

    Args:
        hyp: Description.
        loc: Description.
        msg: Description.
        data: Description.
    """
    try:
        _main().debug_log(hyp, loc, msg, data)
    except Exception as e:
        logger.debug(f"debug_log: {e}")


def _missing_lib_msg(chat, cmd: str, deps: list[str], file: str) -> None:
    """Affiche un message d'erreur propre si une dépendance manque."""
    import pathlib as _pl

    missing = []
    for pkg, mod in deps:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        chat.write(f"[yellow]⚠ {cmd}[/] — dépendances manquantes :\n  [dim]pip install {' '.join(missing)}[/]")
    else:
        chat.write(f"[yellow]⚠ {file} introuvable[/] — copie-le dans [dim]{_pl.Path(__file__).parent}[/]")


async def _post_scan(chat, subnet: str, hosts: list, registry, rag_engine=None) -> None:
    """Logique commune post-scan : registry + RAG."""
    if registry:
        registry.save_scan_target(subnet, subnet, ports_found=[str(p) for h in hosts for p in h.get("open_ports", [])])
    if forge_context.get_rag_engine() and hosts:
        summary = f"[SCAN {subnet}]\n" + "\n".join(
            f"{h.get('ip')} {h.get('name', '')} ports={h.get('open_ports', [])} hw={h.get('hardware', '')}"
            for h in hosts
        )
        await forge_context.get_rag_engine().add_session_message(f"scan_{subnet}", "network", summary)
    _debug_log("NET", "@scan", "Terminé", {"subnet": subnet, "hosts": len(hosts)})
    # recon_silo (overlay web 7331) RETIRE le 2026-08-15 : import FANTOME, aucune
    # source (9 depots, historique git, clones d'archeologie). Le scan ci-dessus
    # (registry + RAG) EST la vraie capacite recon ; ce hook echouait a chaque scan.


# =============================================================================
# @scan — Découverte réseau
# =============================================================================


async def handle_scan(app, args: str) -> tuple:
    """
    @scan [subnet]  — découverte réseau nmap+SNMP+mDNS+UPnP+NetBIOS.
    """
    chat = app._chat_log()
    subnet = args.strip() or "localhost/24"
    reg = _g("_forge_registry")
    rag = _g("rag_engine")

    if _g("HAS_SNIF", False):
        NetworkScanner = _g("NetworkScanner")
        chat.write(f"[dim]🔍 Scan [bold]{subnet}[/] (nmap+SNMP+mDNS)…[/]")

        async def do_scan(_s=subnet) -> None:
            """Do scan.

            Args:
                _s: Description.
            """

            def _on_host(h) -> None:
                """On host.

                Args:
                    h: Description.
                """
                ip = h.get("ip", "?")
                name = h.get("name", "")
                ports = ", ".join(str(p) for p in h.get("open_ports", [])[:6])
                hw = h.get("hardware", "")
                icon = "🖥" if "linux" in hw.lower() else ("🪟" if "windows" in hw.lower() else "📡")
                chat.write(
                    f"  {icon} [bold]{ip}[/]"
                    + (f" [dim]{name}[/]" if name else "")
                    + (f" [dim]{ports}[/]" if ports else "")
                )

            try:
                scanner = NetworkScanner(_s)
                hosts = await scanner.scan_async(on_host=_on_host)
                chat.write(f"[green]✅ {len(hosts)} hôte(s) trouvé(s)[/]")
                await _post_scan(chat, _s, hosts, reg, rag)
            except Exception as e:
                chat.write(f"[red]❌ Scan : {escape(str(e))}[/]")

        asyncio.create_task(do_scan())

    else:
        # Fallback socket — scan basique sans nmap
        import socket, concurrent.futures as _cf, ipaddress

        chat.write(f"[dim]🔍 Scan basique [bold]{subnet}[/] (socket — install snif.py pour nmap)[/]")

        async def do_scan_basic(_s=subnet) -> tuple:
            """Do scan basic.

            Args:
                _s: Description.
            """
            loop = asyncio.get_event_loop()

            def _ping(ip_str) -> tuple:
                """Ping.

                Args:
                    ip_str: Description.
                """
                for port in (22, 80, 443):
                    try:
                        s = socket.create_connection((ip_str, port), timeout=0.3)
                        s.close()
                        return ip_str, [port]
                    except Exception:
                        continue
                return None, []

            try:
                net = ipaddress.ip_network(_s, strict=False)
                hosts_up = []
                with _cf.ThreadPoolExecutor(max_workers=50) as ex:
                    for ip_s, ports in await loop.run_in_executor(
                        None, lambda: list(ex.map(lambda ip: _ping(str(ip)), net.hosts()))
                    ):
                        if ip_s:
                            hosts_up.append({"ip": ip_s, "open_ports": ports})
                            chat.write(f"  📡 [bold]{ip_s}[/] [dim]ports={ports}[/]")

                chat.write(f"[green]✅ {len(hosts_up)} hôte(s) actif(s) sur {_s}[/]")
                await _post_scan(chat, _s, hosts_up, reg, rag)
            except Exception as e:
                chat.write(f"[red]❌ Scan basique : {escape(str(e))}[/]")

        asyncio.create_task(do_scan_basic())


# =============================================================================
# @ids — IDS réseau temps réel
# =============================================================================


def _ids_is_running(app) -> bool:
    """Vérifie si un IDS (complet ou basique) est actif."""
    for attr in ("_ids_task", "_ids_task_basic"):
        t = getattr(app, attr, None)
        if t and not t.done():
            return True
    return False


def _ids_cancel(app) -> None:
    """Annule l'IDS actif (complet ou basique)."""
    for attr in ("_ids_task", "_ids_task_basic", "_ids_instance"):
        obj = getattr(app, attr, None)
        if obj is None:
            continue
        if hasattr(obj, "cancel"):
            obj.cancel()
        setattr(app, attr, None)


async def handle_ids(app, args: str) -> None:
    """
    @ids [start|stop|status] [iface]
    IDS réseau temps réel — PacketIDS (scapyshark) ou fallback asyncio SSH.
    """
    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else "help"
    iface = parts[1] if len(parts) > 1 else "eth0"
    HAS_IDS = _g("HAS_IDS", False)
    PacketIDS = _g("PacketIDS")

    # ── stop ────────────────────────────────────────────────────────────────
    if sub == "stop":
        if hasattr(app, "_ids_instance") and app._ids_instance:
            try:
                await app._ids_instance.stop()
            except Exception as e:
                logger.debug(f"ids stop: {e}")
        _ids_cancel(app)
        chat.write("[yellow]🛑 IDS arrêté[/]")
        return

    # ── status ──────────────────────────────────────────────────────────────
    if sub == "status":
        sus = getattr(app, "_ids_suspects", {})
        if _ids_is_running(app):
            mode = "complet" if _g("HAS_IDS", False) else "basique"
            chat.write(f"[green]🛡 IDS {mode} actif[/] — {len(sus)} suspect(s)")
            for ip, info in list(sus.items())[:10]:
                chat.write(f"  [bold]{ip}[/] [dim]{info}[/]")
        else:
            chat.write("[dim]IDS inactif — @ids start [iface][/]")
        return

    # ── start ────────────────────────────────────────────────────────────────
    if sub == "start":
        if _ids_is_running(app):
            chat.write("[yellow]⚠ IDS déjà actif[/]")
            return

        if _g("HAS_IDS", False) and PacketIDS:
            # Mode complet — PacketIDS (scapyshark)
            chat.write(f"[dim]🛡 IDS démarré sur [bold]{iface}[/] (mode complet)…[/]")

            async def _run_ids(_iface=iface) -> None:
                """Run ids.

                Args:
                    _iface: Description.
                """
                ids = PacketIDS(_iface)
                app._ids_instance = ids

                def _on_alert(alert) -> None:
                    """On alert.

                    Args:
                        alert: Description.
                    """
                    icon = "🔴" if alert.severity == "HIGH" else "🟡"
                    chat.write(
                        f"{icon} [bold red]IDS[/] {alert.src_ip} → {alert.dst_ip} "
                        f"[dim]{alert.rule_name} ({alert.protocol})[/]"
                    )
                    _debug_log("SECU", "@ids", "Alerte", {"src": alert.src_ip, "rule": alert.rule_name})

                try:
                    await ids.start(on_alert=_on_alert)
                except Exception as e:
                    chat.write(f"[red]❌ IDS : {escape(str(e))}[/]")

            app._ids_task = asyncio.create_task(_run_ids())

        else:
            # Mode basique — surveillance SSH périodique
            chat.write(
                f"[dim]🛡 IDS basique sur [bold]{iface}[/] "
                f"(scapyshark.py absent — pip install scapy pour mode complet)[/]"
            )

            async def _ids_basic(_iface=iface) -> None:
                """Ids basic.

                Args:
                    _iface: Description.
                """
                run_ssh = _g("run_ssh")
                suspects: dict = {}
                app._ids_suspects = suspects
                while True:
                    try:
                        if run_ssh:
                            out, _, _ = await run_ssh(
                                "last -F | grep 'still logged in' "
                                "| awk '{print $3}' | sort | uniq -c | sort -rn | head -5"
                            )
                            for line in out.splitlines():
                                p = line.strip().split()
                                if len(p) >= 2 and int(p[0]) > 3 and p[1] not in suspects:
                                    suspects[p[1]] = f"{p[0]} connexions"
                                    chat.write(
                                        f"🟡 [bold]IDS[/] Activité SSH suspecte : [bold]{p[1]}[/] ({p[0]} sessions)"
                                    )
                    except Exception as e:
                        logger.debug(f"ids_basic loop: {e}")
                    await asyncio.sleep(30)

            app._ids_task_basic = asyncio.create_task(_ids_basic())
        return

    # ── help ─────────────────────────────────────────────────────────────────
    chat.write(
        "[bold #58a6ff]@ids[/] start [iface] | stop | status\n"
        "  [dim]Détecte : SSH brute-force, scans ports, anomalies HTTP/DNS[/]\n"
        "  [dim]Mode complet : pip install scapy (scapyshark.py requis)[/]"
    )


# =============================================================================
# @chain — Pipeline d'outils
# =============================================================================


async def handle_chain(app, args: str) -> object:
    """
    @chain <cmd1> | <cmd2> | <cmd3>
    Pipeline d'outils. {output} = résultat précédent, {ip} = 1ère IP.
    """
    chat = app._chat_log()

    if not args or args.strip() in ("", "help"):
        chat.write(
            "[bold #58a6ff]@chain[/] — Pipeline d'outils :\n"
            "  [bold]@chain[/] [dim]<cmd1> | <cmd2> | <cmd3>[/]\n"
            "  Variables : [cyan]{output}[/] résultat précédent · "
            "[cyan]{ip}[/] première IP · [cyan]{line:N}[/] ligne N\n\n"
            "  [dim]Exemples :[/]\n"
            "  [dim]@chain @scan localhost/24 | @switch {ip} admin pass[/]\n"
            "  [dim]@chain @ci run https://github.com/org/repo | @workflow deploy api[/]"
        )
        return

    raw_steps = [s.strip() for s in args.split("|") if s.strip()]
    if len(raw_steps) < 2:
        chat.write("[yellow]⚠ @chain nécessite au moins 2 étapes séparées par |[/]")
        return

    chat.write(
        f"[bold #58a6ff]⛓ Chain[/] — [dim]{len(raw_steps)} étape(s)[/]\n"
        + "\n".join(f"  [dim]{i + 1}.[/] {s}" for i, s in enumerate(raw_steps))
    )

    def _extract_ip(text: str) -> str:
        """Extract ip.

        Args:
            text: Description.
        """
        m = _re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
        return m.group(1) if m else ""

    def _get_line(text: str, n: int) -> str:
        """Get line.

        Args:
            text: Description.
            n: Description.
        """
        ls = text.splitlines()
        return ls[n - 1] if 0 < n <= len(ls) else ""

    def _inject(step: str, prev: str) -> str:
        """Inject.

        Args:
            step: Description.
            prev: Description.
        """
        step = step.replace("{output}", prev.strip()[:500])
        step = step.replace("{ip}", _extract_ip(prev))
        for m in _re.finditer(r"\{line:(\d+)\}", step):
            step = step.replace(m.group(0), _get_line(prev, int(m.group(1))))
        return step

    prev_output = ""
    chain_ok = True
    for step_i, raw_step in enumerate(raw_steps):
        step_cmd = _inject(raw_step, prev_output)
        chat.write(f"\n[dim]── Étape {step_i + 1}/{len(raw_steps)} : [bold]{step_cmd[:80]}[/][/]")
        _captured: list = []
        _orig_write = chat.write

        def _cap(msg, *a, _c=_captured, _ow=_orig_write, **kw) -> None:
            """Cap.

            Args:
                msg: Description.
            """
            _c.append(str(msg))
            _ow(msg, *a, **kw)

        chat.write = _cap  # type: ignore
        try:
            if step_cmd.startswith("@"):
                await app._handle_at(step_cmd)
            else:
                run_ssh = _g("run_ssh")
                if run_ssh:
                    out, _, _ = await run_ssh(step_cmd)
                    chat.write(f"[dim]{out[:400]}[/]" if out else "[dim](vide)[/]")
                    _captured.append(out or "")
            prev_output = "\n".join(_captured)
            _debug_log(
                "CHAIN", f"@chain step {step_i + 1}", "OK", {"cmd": step_cmd[:60], "output_len": len(prev_output)}
            )
        except Exception as _e:
            chat.write = _orig_write  # type: ignore
            chat.write(f"[red]❌ Étape {step_i + 1} échouée : {escape(str(_e))}[/]")
            chain_ok = False
            break
        finally:
            chat.write = _orig_write  # type: ignore

    if chain_ok:
        chat.write(f"\n[green]✅ Chain terminé — {len(raw_steps)} étape(s)[/]")
        reg = _g("_forge_registry")
        if reg:
            reg.save_chain(f"chain_{raw_steps[0][:20].replace(' ', '_')}", raw_steps)
    else:
        chat.write("[red]❌ Chain interrompu[/]")


# =============================================================================
# @switch — Récupération config switch/routeur
# =============================================================================


async def handle_switch(app, args: str) -> None:
    """
    @switch <ip> <user> <pass> [save]
    @switch range <user> <pass> <ip1> <ip2> …
    """
    chat = app._chat_log()
    parts = args.split()
    reg = _g("_forge_registry")
    rag = _g("rag_engine")
    HAS_SW = _g("HAS_SWITCH", False)
    Agent = _g("NetworkRecoveryAgent")

    if not parts:
        chat.write(
            "[bold #58a6ff]@switch[/] — Récupération de config réseau :\n"
            "  [bold]@switch[/] [dim]<ip> <user> <pass>[/]              récupérer la config\n"
            "  [bold]@switch[/] [dim]<ip> <user> <pass> save[/]         récupérer + indexer RAG\n"
            "  [bold]@switch range[/] [dim]<user> <pass> <ip1> <ip2>…[/] multi-cibles\n\n"
            "  Dépendances : [dim]pip install paramiko pysnmp[/]\n"
            "  Supporte SSH / Telnet / SNMP — Cisco, HP, Juniper, MikroTik, Huawei, Fortinet"
        )
        return

    if not HAS_SW or not Agent:
        _missing_lib_msg(chat, "@switch", [("paramiko", "paramiko"), ("pysnmp", "pysnmp")], "boitaswitch.py")
        return

    # ── range : multi-cibles ─────────────────────────────────────────────────
    if parts[0].lower() == "range" and len(parts) >= 4:
        username, password, targets = parts[1], parts[2], parts[3:]
        chat.write(f"[dim]🔍 Scan de [bold]{len(targets)}[/] cible(s) en parallèle…[/]")

        async def do_range(_t=targets, _u=username, _p=password) -> None:
            """Do range.

            Args:
                _t: Description.
                _u: Description.
                _p: Description.
            """

            def _on_result(r) -> None:
                """On result.

                Args:
                    r: Description.
                """
                icon = "✅" if r.ok else "❌"
                chat.write(
                    f"{icon} [bold]{r.ip}[/] [{r.device_type}] {'via ' + r.protocol if r.protocol else r.error or ''}"
                )
                if r.ok and reg:
                    reg.save_ssh_target(r.ip, r.ip)

            try:
                results = await Agent.scan_range(_t, _u, _p, on_result=_on_result)
                ok = sum(1 for r in results if r.ok)
                chat.write(f"\n[green]✅ {ok}/{len(results)} équipement(s) configuré(s)[/]")
            except Exception as e:
                chat.write(f"[red]❌ Scan range : {escape(str(e))}[/]")

        asyncio.create_task(do_range())
        return

    # ── single : une cible ───────────────────────────────────────────────────
    if len(parts) < 3:
        chat.write("[yellow]⚠ Usage : @switch <ip> <user> <pass> [save][/]")
        return

    ip, username, password = parts[0], parts[1], parts[2]
    do_save = len(parts) >= 4 and parts[3].lower() == "save"
    chat.write(f"[dim]🔌 Connexion à [bold]{ip}[/]…[/]")

    async def do_switch(_ip=ip, _u=username, _p=password, _save=do_save) -> None:
        """Do switch.

        Args:
            _ip: Description.
            _u: Description.
            _p: Description.
            _save: Description.
        """

        def _step(icon: str, msg: str) -> None:
            """Step.

            Args:
                icon: Description.
                msg: Description.
            """
            chat.write(f"{icon} {msg}")

        try:
            loop = asyncio.get_event_loop()
            agent = Agent(_ip)
            result = await loop.run_in_executor(None, lambda: agent.recover_config(_u, _p, on_step=_step))
            if result.ok:
                chat.write(
                    f"[green]✅ Config [bold]{_ip}[/] récupérée "
                    f"([bold]{result.device_type}[/] via {result.protocol}) "
                    f"— {len(result.config)} octets[/]"
                )
                chat.write(f"[dim]  {result.config[:600].replace(chr(10), chr(10) + '  ')}…[/]")
                if reg:
                    reg.save_ssh_target(_ip, _ip)
                if _save and rag:
                    await rag.add_session_message(
                        f"switch_{_ip}", "config", f"[CONFIG {result.device_type} {_ip}]\n{result.config}"
                    )
                    chat.write("[dim]📚 Config indexée dans le RAG[/]")
                _debug_log(
                    "SECU",
                    "@switch",
                    "Config récupérée",
                    {"ip": _ip, "device": result.device_type, "proto": result.protocol, "len": len(result.config)},
                )
            else:
                chat.write(f"[red]❌ @switch {_ip} : {result.error}[/]")
        except Exception as e:
            chat.write(f"[red]❌ @switch : {escape(str(e))}[/]")
            logger.error(f"@switch {_ip}: {e}", exc_info=True)

    asyncio.create_task(do_switch())
