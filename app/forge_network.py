"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_network
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_network.py — Couche réseau unifiée pour La Forge
=======================================================
Fusion de : snif.py · scapyshark.py · boitaswitch.py
"""

import asyncio, logging, socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ── Dépendances optionnelles ──────────────────────────────────────────────────
try:
    import nmap

    HAS_NMAP = True
except ImportError:
    HAS_NMAP = False

try:
    from zeroconf import Zeroconf, ServiceBrowser

    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

try:
    import miniupnpc

    HAS_UPNP = True
except ImportError:
    HAS_UPNP = False

try:
    from pysnmp.hlapi import (
        SnmpEngine,
        CommunityData,
        UdpTransportTarget,
        ContextData,
        ObjectType,
        ObjectIdentity,
        getCmd,
    )

    HAS_SNMP = True
except ImportError:
    HAS_SNMP = False

# scapy : chargement PARESSEUX (2026-09-25). `from scapy.all import ...` a l'import de ce module
# rescanne les interfaces Windows et charge Npcap (conf.ifaces.reload -> load_winpcapy) : sonde du
# chemin reel du bridge :7440, pile encore dans cet import a 18 s (45 s en mesure isolee), et la
# TUI v13 -- qui importe ce module au demarrage, avant tout affichage -- ne rendait AUCUN octet en
# 120 s. Presence du paquet = capacite DECLAREE ; scapy n'est charge qu'au premier sniff, et un
# echec de chargement s'y dit (present n'est pas utilisable).
try:
    import importlib.util as _ilu

    HAS_SCAPY = _ilu.find_spec("scapy") is not None  # type: ignore
except Exception:  # noqa: BLE001 - find_spec leve si un parent est casse : capacite absente
    HAS_SCAPY = False


def _scapy() -> tuple:
    """(sniff, IP, TCP, Ether), charges au PREMIER besoin -- jamais a l'import du module."""
    from scapy.all import IP, TCP, Ether, sniff

    return sniff, IP, TCP, Ether

try:
    import pyshark

    HAS_PYSHARK = True  # type: ignore
except ImportError:
    HAS_PYSHARK = False

try:
    import paramiko

    HAS_PARAMIKO = True  # type: ignore
except ImportError:
    HAS_PARAMIKO = False

try:
    import telnetlib

    HAS_TELNET = True
except ImportError:
    HAS_TELNET = False

CAPABILITIES: Dict[str, bool] = {
    "nmap": HAS_NMAP,
    "snmp": HAS_SNMP,
    "zeroconf": HAS_ZEROCONF,
    "upnp": HAS_UPNP,
    "scapy": HAS_SCAPY,
    "pyshark": HAS_PYSHARK,
    "paramiko": HAS_PARAMIKO,
    "telnet": HAS_TELNET,
}


# =============================================================================
# PARTIE 1 — DÉCOUVERTE RÉSEAU  (ex-snif.py)
# =============================================================================


@dataclass
class Device:
    """Représentation d'un équipement réseau découvert."""

    ip: str
    hostname: str | None = None
    mac: str | None = None
    os: str | None = None
    ports: list[int] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    services: dict[str, object] = field(default_factory=dict)
    device_type: str = "unknown"

    def __post_init__(self) -> None:
        """Post init."""
        if self.ports is None:
            self.ports = []
        if self.protocols is None:
            self.protocols = []
        if self.services is None:
            self.services = {}

    def to_dict(self) -> dict:
        """To dict."""
        return {
            k: getattr(self, k)
            for k in ("ip", "hostname", "mac", "os", "ports", "protocols", "services", "device_type")
        }


class NetworkDiscovery:
    """
    Découverte réseau multi-protocoles.
    Mode complet  : nmap + SNMP + mDNS + UPnP + LLDP/CDP
    Mode dégradé  : socket pur (aucune dépendance externe)
    """

    def __init__(self, subnet: str = "localhost/24") -> None:
        """Init.

        Args:
            subnet: Description.
        """
        self.subnet = subnet
        self.devices: Dict[str, Device] = {}

    def _get(self, ip: str) -> Device:
        """Get.

        Args:
            ip: Description.
        """
        if ip not in self.devices:
            self.devices[ip] = Device(ip=ip)
        return self.devices[ip]

    def _nmap_scan(self) -> None:
        """Nmap scan."""
        if not HAS_NMAP:
            return
        nm = nmap.PortScanner()
        nm.scan(hosts=self.subnet, arguments="-O -sS --open")
        for host in nm.all_hosts():
            dev = self._get(host)
            if "tcp" in nm[host]:
                dev.ports = list(nm[host]["tcp"].keys())
            if nm[host].get("osmatch"):
                dev.os = nm[host]["osmatch"][0]["name"]

    def _snmp_probe(self, device: Device) -> None:
        """Snmp probe.

        Args:
            device: Description.
        """
        if not HAS_SNMP:
            return
        try:
            err_ind, err_st, _, vbs = next(
                getCmd(
                    SnmpEngine(),
                    CommunityData("public"),
                    UdpTransportTarget((device.ip, 161), timeout=1, retries=0),
                    ContextData(),
                    ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
                )
            )
            if not err_ind and not err_st:
                val = str(vbs[0][1])
                device.services["snmp"] = val
                device.protocols.append("SNMP")
                for kw, brand in [
                    ("cisco", "cisco"),
                    ("hp", "hp"),
                    ("aruba", "aruba"),
                    ("juniper", "juniper"),
                    ("mikrotik", "mikrotik"),
                    ("huawei", "huawei"),
                    ("fortinet", "fortinet"),
                    ("h3c", "hp"),
                ]:
                    if kw in val.lower():
                        device.device_type = brand
                        break
        except Exception:
            pass

    def _rdns(self, device: Device) -> None:
        """Rdns.

        Args:
            device: Description.
        """
        try:
            device.hostname = socket.gethostbyaddr(device.ip)[0]
        except Exception:
            pass

    def _mdns_discovery(self) -> None:
        """Mdns discovery."""
        if not HAS_ZEROCONF:
            return
        disc = self

        class _L:
            def add_service(self, zc, t, n) -> None:
                """Add service.

                Args:
                    zc: Description.
                    t: Description.
                    n: Description.
                """
                info = zc.get_service_info(t, n)
                if info and info.addresses:
                    dev = disc._get(socket.inet_ntoa(info.addresses[0]))
                    dev.protocols.append("mDNS")
                    dev.services["mdns"] = n

        zc = Zeroconf()
        ServiceBrowser(zc, "_services._dns-sd._udp.local.", _L())

    def _upnp_discovery(self) -> None:
        """Upnp discovery."""
        if not HAS_UPNP:
            return
        try:
            u = miniupnpc.UPnP()
            u.discoverdelay = 200
            if u.discover() > 0:
                dev = self._get(u.lanaddr)
                dev.protocols.append("UPnP")
        except Exception:
            pass

    def _lldp_sniff(self, timeout: int = 5) -> None:
        """Lldp sniff.

        Args:
            timeout: Description.
        """
        if not HAS_SCAPY:
            return
        try:
            sniff, _ip, _tcp, Ether = _scapy()
        except Exception as exc:  # noqa: BLE001 - present n'est pas utilisable : on le DIT
            logger.warning("scapy present mais inutilisable (%s) : LLDP/CDP non ecoute", type(exc).__name__)
            return

        def _pkt(pkt) -> None:
            """Pkt.

            Args:
                pkt: Description.
            """
            try:
                src = pkt[Ether].src
                dev = self._get(src)
                if pkt.haslayer("LLDPDU"):
                    dev.protocols.append("LLDP")
                elif pkt.haslayer("CDPMsgDeviceID"):
                    dev.protocols.append("CDP")
            except Exception:
                pass

        try:
            sniff(filter="ether proto 0x88cc", prn=_pkt, timeout=timeout, store=False)
        except Exception:
            pass

    def _socket_fallback(self) -> tuple:
        """Scan socket pur — aucune dépendance externe."""
        import ipaddress as _ip

        PORTS = [21, 22, 23, 80, 443, 445, 161, 3389, 8080, 8443]
        try:
            hosts = [str(h) for h in list(_ip.ip_network(self.subnet, strict=False).hosts())[:254]]
        except ValueError:
            return

        def _probe(ip_s) -> tuple:
            """Probe.

            Args:
                ip_s: Description.
            """
            open_p, hn = [], ""
            try:
                hn = socket.gethostbyaddr(ip_s)[0]
            except Exception:
                pass
            for p in PORTS:
                try:
                    s = socket.socket()
                    s.settimeout(0.35)
                    if s.connect_ex((ip_s, p)) == 0:
                        open_p.append(p)
                    s.close()
                except Exception:
                    pass
            return ip_s, hn, open_p

        with ThreadPoolExecutor(max_workers=50) as ex:
            for ip_s, hn, ports in ex.map(_probe, hosts):
                if ports:
                    dev = self._get(ip_s)
                    dev.hostname = hn or None
                    dev.ports = ports

    def run(self) -> List[dict]:
        """Lance la découverte complète. Retourne la liste des équipements."""
        if HAS_NMAP:
            self._nmap_scan()
        else:
            self._socket_fallback()
        with ThreadPoolExecutor(max_workers=20) as ex:
            for dev in list(self.devices.values()):
                ex.submit(self._snmp_probe, dev)
                ex.submit(self._rdns, dev)
        self._mdns_discovery()
        self._upnp_discovery()
        try:
            self._lldp_sniff()
        except Exception:
            pass
        return [d.to_dict() for d in self.devices.values()]


# =============================================================================
# PARTIE 2 — IDS TEMPS-RÉEL  (ex-scapyshark.py)
# =============================================================================


class MiniIDSAgent:
    """
    Agent IDS : détecte comportements suspects en temps réel.
    Mode complet  : scapy + pyshark (nécessite root/CAP_NET_RAW)
    Mode dégradé  : polling /proc/net/tcp  (Linux, aucune dépendance)
    """

    _MONITORED_PORTS: Dict[int, str] = {
        22: "SSH",
        23: "Telnet",
        80: "HTTP",
        443: "HTTPS",
        3389: "RDP",
        445: "SMB",
        3306: "MySQL",
        5432: "PostgreSQL",
        21: "FTP",
        25: "SMTP",
        53: "DNS",
    }

    def __init__(self, iface: str = "eth0") -> None:
        """Init.

        Args:
            iface: Description.
        """
        self.iface = iface
        self.suspect_ips: set = set()
        self._counts: Dict[str, int] = {}

    async def alert(self, message: str) -> None:
        """Alerte IDS : log + TUI + ajout à suspect_ips + bloc optionnel."""
        logger.warning(f"[IDS] {message}")
        # Notifier la TUI si une app Nokido tourne
        try:
            import sys as _sys

            for mod_name in ("__main__", "Nokido", "app.Nokido"):
                app = _sys.modules.get(mod_name)
                if app and hasattr(app, "_chat_log"):
                    app._chat_log().write(f"[bold red]🚨 IDS:[/] {message}")
                    break
        except Exception:
            pass
        # Log sécurité persisté
        try:
            import time as _t

            _log_path = __import__("pathlib").Path(__file__).parent.parent / "logs" / "ids_alerts.log"
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(f"[{_t.strftime('%Y-%m-%dT%H:%M:%S')}] {message}\n")
        except Exception:
            pass

    def _scapy_cb(self, pkt) -> None:
        """Scapy cb.

        Args:
            pkt: Description.
        """
        if not HAS_SCAPY:
            return
        _sniff, IP, TCP, _ether = _scapy()  # deja charge par _run_scapy : lecture de sys.modules
        if IP not in pkt:
            return
        src = pkt[IP].src
        if TCP in pkt and pkt[TCP].dport in self._MONITORED_PORTS:
            self._counts[src] = self._counts.get(src, 0) + 1
            svc = self._MONITORED_PORTS[pkt[TCP].dport]
            if self._counts[src] > 5:
                self.suspect_ips.add(src)
                asyncio.create_task(self.alert(f"Activité suspecte {svc} depuis {src} (×{self._counts[src]})"))

    async def _run_scapy(self) -> None:
        """Run scapy."""
        if not HAS_SCAPY:
            return
        loop = asyncio.get_event_loop()
        # Chargement DANS l'executeur : scapy peut attendre Npcap de longues secondes, jamais
        # dans la boucle.
        await loop.run_in_executor(
            None, lambda: _scapy()[0](iface=self.iface, prn=self._scapy_cb, store=False))

    async def _run_pyshark(self) -> None:
        """Run pyshark."""
        if not HAS_PYSHARK:
            return
        capture = pyshark.LiveCapture(interface=self.iface)
        async for pkt in capture.sniff_continuously():
            try:
                src = pkt.ip.src
                if "http" in pkt:
                    self.suspect_ips.add(src)
                    await self.alert(f"HTTP depuis {src}")
            except AttributeError:
                continue

    async def _run_proc_tcp(self, poll: float = 5.0) -> None:
        """Fallback Linux : lit /proc/net/tcp sans dépendance externe."""
        prev: set = set()
        while True:
            conns: set = set()
            try:
                with open("/proc/net/tcp") as f:
                    for ln in f.readlines()[1:]:
                        p = ln.split()
                        if len(p) < 4 or p[3] != "01":
                            continue
                        ih, ph = p[2].split(":")
                        ip_s = ".".join(str(int(ih[i : i + 2], 16)) for i in (6, 4, 2, 0))
                        port = int(ph, 16)
                        if port in self._MONITORED_PORTS:
                            conns.add((ip_s, port))
            except (FileNotFoundError, PermissionError):
                pass
            for ip_s, port in conns - prev:
                svc = self._MONITORED_PORTS[port]
                self._counts[ip_s] = self._counts.get(ip_s, 0) + 1
                await self.alert(
                    f"{svc} depuis {ip_s}:{port}"
                    + (f" — SUSPECT ×{self._counts[ip_s]}" if self._counts[ip_s] > 3 else "")
                )
                if self._counts[ip_s] > 3:
                    self.suspect_ips.add(ip_s)
            prev = conns
            await asyncio.sleep(poll)

    async def run(self) -> None:
        """Run."""
        if HAS_SCAPY or HAS_PYSHARK:
            tasks = []
            if HAS_SCAPY:
                tasks.append(self._run_scapy())
            if HAS_PYSHARK:
                tasks.append(self._run_pyshark())
            await asyncio.gather(*tasks)
        else:
            await self._run_proc_tcp()


# =============================================================================
# PARTIE 3 — RÉCUPÉRATION CONFIG SWITCHES/ROUTEURS  (ex-boitaswitch.py)
# =============================================================================

COMMON_PORTS: Dict[str, int] = {
    "ssh": 22,
    "telnet": 23,
    "http": 80,
    "https": 443,
    "snmp": 161,
}

_CFG_CMDS: Dict[str, Dict[str, str]] = {
    "cisco": {"ssh": "show running-config", "telnet": "show running-config\n"},
    "hp": {"ssh": "display current-config", "telnet": "display current-config\n"},
    "aruba": {"ssh": "show running-config", "telnet": "show running-config\n"},
    "juniper": {"ssh": "show configuration", "telnet": "show configuration\n"},
    "mikrotik": {"ssh": "/export", "telnet": "/export\n"},
    "huawei": {"ssh": "display current-configuration", "telnet": "display current-configuration\n"},
    "fortinet": {"ssh": "show full-configuration", "telnet": "show full-configuration\n"},
    "generic": {"ssh": "show config", "telnet": "show config\n"},
}

_SNMP_FP: List[Tuple[str, str]] = [
    ("cisco", "cisco"),
    ("hp", "hp"),
    ("aruba", "aruba"),
    ("juniper", "juniper"),
    ("mikrotik", "mikrotik"),
    ("huawei", "huawei"),
    ("fortinet", "fortinet"),
    ("h3c", "hp"),
]


@dataclass
class SwitchResult:
    ip: str
    device_type: str = None
    protocol: str = None
    config: str = None
    services: dict = None

    def __post_init__(self) -> None:
        """Post init."""
        if self.services is None:
            self.services = {}

    @property
    def ok(self) -> bool:
        """Ok."""
        return bool(self.config)

    def summary(self) -> str:
        """Summary."""
        parts = [f"IP:{self.ip}"]
        if self.device_type:
            parts.append(f"type:{self.device_type}")
        if self.protocol:
            parts.append(f"proto:{self.protocol}")
        if self.config:
            parts.append(f"cfg:{len(self.config)}c")
        svcs = [k for k, v in (self.services or {}).items() if v]
        if svcs:
            parts.append(f"svcs:{','.join(svcs)}")
        return " | ".join(parts)


class NetworkRecoveryAgent:
    """
    Récupère la config d'un équipement réseau.
    Workflow : scan ports → SNMP fingerprint → SSH → Telnet fallback.
    """

    def __init__(self, ip: str, timeout: float = 3.0) -> None:
        """Init.

        Args:
            ip: Description.
            timeout: Description.
        """
        self.ip = ip
        self.timeout = timeout
        self._r = SwitchResult(ip=ip)

    def _scan_ports(self) -> Dict[str, bool]:
        """Scan ports."""

        def _probe(np) -> tuple:
            """Probe.

            Args:
                np: Description.
            """
            n, p = np
            try:
                s = socket.socket()
                s.settimeout(self.timeout)
                ok = s.connect_ex((self.ip, p)) == 0
                s.close()
                return n, ok
            except Exception:
                return n, False

        with ThreadPoolExecutor(max_workers=5) as ex:
            self._r.services = dict(ex.map(_probe, COMMON_PORTS.items()))
        return self._r.services

    def _snmp_fp(self) -> str:
        """Snmp fp."""
        if not HAS_SNMP or not (self._r.services or {}).get("snmp"):
            return "generic"
        try:
            err_ind, err_st, _, vbs = next(
                getCmd(
                    SnmpEngine(),
                    CommunityData("public"),
                    UdpTransportTarget((self.ip, 161), timeout=2, retries=1),
                    ContextData(),
                    ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
                )
            )
            if not err_ind and not err_st:
                val = str(vbs[0][1]).lower()
                for kw, brand in _SNMP_FP:
                    if kw in val:
                        return brand
        except Exception:
            pass
        return "generic"

    def _ssh(self, user: str, pwd: str, dtype: str) -> str:
        """Ssh.

        Args:
            user: Description.
            pwd: Description.
            dtype: Description.
        """
        if not HAS_PARAMIKO or not (self._r.services or {}).get("ssh"):
            return None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.ip, username=user, password=pwd, timeout=self.timeout, look_for_keys=False, allow_agent=False
            )
            cmd = _CFG_CMDS.get(dtype, _CFG_CMDS["generic"])["ssh"]
            _, out, _ = ssh.exec_command(cmd, timeout=10)
            cfg = out.read().decode(errors="replace")
            ssh.close()
            return cfg if len(cfg) > 10 else None
        except Exception as e:
            logger.debug(f"SSH {self.ip}: {e}")
            return None

    def _telnet(self, user: str, pwd: str, dtype: str) -> str:
        """Telnet.

        Args:
            user: Description.
            pwd: Description.
            dtype: Description.
        """
        if not HAS_TELNET or not (self._r.services or {}).get("telnet"):
            return None
        try:
            import time

            tn = telnetlib.Telnet(self.ip, 23, timeout=self.timeout)
            tn.read_until(b"sername:", timeout=3)
            tn.write(user.encode() + b"\n")
            tn.read_until(b"assword:", timeout=3)
            tn.write(pwd.encode() + b"\n")
            time.sleep(1)
            cmd = _CFG_CMDS.get(dtype, _CFG_CMDS["generic"])["telnet"]
            tn.write(cmd.encode())
            cfg = tn.read_until(b"#", timeout=10).decode(errors="replace")
            tn.close()
            return cfg if len(cfg) > 10 else None
        except Exception as e:
            logger.debug(f"Telnet {self.ip}: {e}")
            return None

    async def recover_config(
        self,
        username: str,
        password: str,
        on_step=None,
    ) -> SwitchResult:
        """Recover config.

        Args:
            username: Description.
            password: Description.
            on_step: Description.
        """
        loop = asyncio.get_event_loop()

        def step(msg) -> None:
            """Step.

            Args:
                msg: Description.
            """
            if on_step:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(on_step(msg))
                    else:
                        loop.run_until_complete(on_step(msg))
                except Exception:
                    pass

        step(f"Scan ports {self.ip}…")
        svcs = await loop.run_in_executor(None, self._scan_ports)
        if not any(svcs.values()):
            step("Aucun port ouvert")
            return self._r

        step("Fingerprint SNMP…")
        dtype = await loop.run_in_executor(None, self._snmp_fp)
        self._r.device_type = dtype
        step(f"Type: {dtype}")

        step("SSH…")
        cfg = await loop.run_in_executor(None, self._ssh, username, password, dtype)
        if cfg:
            self._r.protocol = "ssh"
            self._r.config = cfg
            step(f"SSH OK ({len(cfg)} chars)")
            return self._r

        step("SSH échoué — Telnet…")
        cfg = await loop.run_in_executor(None, self._telnet, username, password, dtype)
        if cfg:
            self._r.protocol = "telnet"
            self._r.config = cfg
            step(f"Telnet OK ({len(cfg)} chars)")
        else:
            step("Échec récupération config")
        return self._r

    @classmethod
    async def scan_range(
        cls,
        targets: List[str],
        username: str,
        password: str,
        max_concurrent: int = 10,
    ) -> List[SwitchResult]:
        """Scan range.

        Args:
            cls: Description.
            targets: Description.
            username: Description.
            password: Description.
            max_concurrent: Description.
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(ip) -> object:
            """One.

            Args:
                ip: Description.
            """
            async with sem:
                return await cls(ip).recover_config(username, password)

        return await asyncio.gather(*[_one(ip) for ip in targets])


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "NetworkDiscovery",
    "Device",
    "MiniIDSAgent",
    "NetworkRecoveryAgent",
    "SwitchResult",
    "HAS_NMAP",
    "HAS_SNMP",
    "HAS_SCAPY",
    "HAS_PYSHARK",
    "HAS_PARAMIKO",
    "HAS_TELNET",
    "CAPABILITIES",
]
