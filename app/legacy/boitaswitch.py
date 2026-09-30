"""
boitaswitch.py — Agent de récupération de config pour équipements réseau.
Supporte SSH / Telnet / SNMP.
Marques : Cisco, HP/Aruba, Juniper, MikroTik, Huawei, Fortinet, Generique.
"""

from __future__ import annotations

import asyncio
import socket
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("boitaswitch")

# ── Dépendances optionnelles ──────────────────────────────────────────────────
try:
    import paramiko

    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

try:
    import telnetlib

    HAS_TELNET = True
except ImportError:  # Python 3.13+ a supprimé telnetlib
    HAS_TELNET = False

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

# ── Constantes ────────────────────────────────────────────────────────────────
COMMON_PORTS: Dict[str, int] = {
    "ssh": 22,
    "telnet": 23,
    "http": 80,
    "https": 443,
    "snmp": 161,
}

# Commandes de config par marque et protocole
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

# Empreintes SNMP → marque
_SNMP_FINGERPRINTS: List[Tuple[str, str]] = [
    ("cisco", "cisco"),
    ("hp", "hp"),
    ("aruba", "aruba"),
    ("juniper", "juniper"),
    ("mikrotik", "mikrotik"),
    ("huawei", "huawei"),
    ("fortinet", "fortinet"),
    ("h3c", "hp"),  # H3C = HP OEM
]


# ── Résultat structuré ────────────────────────────────────────────────────────
@dataclass
class SwitchResult:
    ip: str
    device_type: Optional[str] = None
    protocol: Optional[str] = None  # "ssh" | "telnet"
    config: Optional[str] = None
    services: Dict[str, bool] = field(default_factory=dict)
    snmp_desc: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.config is not None

    def summary(self) -> str:
        lines = [f"[bold]{self.ip}[/] — {self.device_type or '?'}"]
        lines.append(f"  Services  : {', '.join(k for k, v in self.services.items() if v) or 'aucun'}")
        if self.snmp_desc:
            lines.append(f"  SNMP      : {self.snmp_desc[:80]}")
        if self.protocol:
            lines.append(f"  Protocole : {self.protocol}")
        if self.config:
            preview = self.config[:200].replace("\n", "\n    ")
            lines.append(f"  Config    :\n    {preview}…")
        if self.error:
            lines.append(f"  Erreur    : {self.error}")
        return "\n".join(lines)


# ── Agent principal ───────────────────────────────────────────────────────────
class NetworkRecoveryAgent:
    """
    Agent de récupération de configuration réseau.
    Détecte automatiquement SSH / Telnet / SNMP,
    identifie la marque, et extrait la config courante.
    """

    def __init__(self, target_ip: str, timeout: float = 3.0):
        self.target = target_ip
        self.timeout = timeout
        self.device_type: Optional[str] = None

    # ── Scan de ports ─────────────────────────────────────────────────────────
    def scan_port(self, port: int) -> bool:
        s = socket.socket()
        s.settimeout(self.timeout)
        try:
            s.connect((self.target, port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def discover_services(self) -> Dict[str, bool]:
        """Scan tous les ports COMMON_PORTS en parallèle."""
        results: Dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=len(COMMON_PORTS)) as ex:
            futures = {ex.submit(self.scan_port, port): name for name, port in COMMON_PORTS.items()}
            for fut, name in futures.items():
                try:
                    results[name] = fut.result(timeout=self.timeout + 1)
                except Exception:
                    results[name] = False
        return {k: v for k, v in results.items() if v}  # seulement les ouverts

    # ── SNMP fingerprint ──────────────────────────────────────────────────────
    def snmp_fingerprint(self) -> Optional[str]:
        if not HAS_SNMP:
            logger.warning("pysnmp non installé — fingerprint SNMP désactivé")
            return None
        try:
            iterator = getCmd(
                SnmpEngine(),
                CommunityData("public", mpModel=0),
                UdpTransportTarget((self.target, 161), timeout=self.timeout, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity("SNMPv2-MIB", "sysDescr", 0)),
            )
            errInd, errStat, _, varBinds = next(iterator)
            if errInd or errStat:
                return None
            desc = str(varBinds[0][1]).lower()
            # Déterminer la marque
            self.device_type = "generic"
            for keyword, brand in _SNMP_FINGERPRINTS:
                if keyword in desc:
                    self.device_type = brand
                    break
            logger.debug(f"SNMP {self.target}: {self.device_type} — {desc[:80]}")
            return desc
        except Exception as e:
            logger.debug(f"SNMP fingerprint {self.target}: {e}")
            return None

    # ── Connexion SSH ─────────────────────────────────────────────────────────
    def ssh_connect(self, username: str, password: str):
        if not HAS_PARAMIKO:
            logger.warning("paramiko non installé — SSH désactivé")
            return None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.target,
                username=username,
                password=password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            return ssh
        except Exception as e:
            logger.debug(f"SSH {self.target}: {e}")
            return None

    # ── Connexion Telnet ──────────────────────────────────────────────────────
    def telnet_connect(self, username: str, password: str):
        if not HAS_TELNET:
            logger.warning("telnetlib non disponible (Python ≥ 3.13)")
            return None
        try:
            tn = telnetlib.Telnet(self.target, 23, timeout=self.timeout)
            tn.read_until(b"login: ", timeout=self.timeout)
            tn.write(username.encode() + b"\n")
            tn.read_until(b"Password: ", timeout=self.timeout)
            tn.write(password.encode() + b"\n")
            # Attendre le prompt (quelques ms)
            import time

            time.sleep(0.5)
            return tn
        except Exception as e:
            logger.debug(f"Telnet {self.target}: {e}")
            return None

    # ── Extraction de config ──────────────────────────────────────────────────
    def _cfg_cmd(self, proto: str) -> str:
        brand = self.device_type or "generic"
        return _CFG_CMDS.get(brand, _CFG_CMDS["generic"])[proto]

    def get_config_ssh(self, ssh) -> str:
        cmd = self._cfg_cmd("ssh")
        _, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        if not out and err:
            logger.warning(f"SSH config {self.target}: stderr={err[:80]}")
        return out or f"(vide — stderr: {err[:80]})"

    def get_config_telnet(self, tn) -> str:
        cmd = self._cfg_cmd("telnet")
        tn.write(cmd.encode())
        try:
            return tn.read_until(b"#", timeout=15).decode(errors="replace").strip()
        except Exception:
            return tn.read_very_eager().decode(errors="replace").strip()

    # ── Workflow principal ────────────────────────────────────────────────────
    def recover_config(
        self,
        username: str,
        password: str,
        on_step: Optional[callable] = None,
    ) -> SwitchResult:
        """
        Workflow complet :
        1. Scan des ports en parallèle
        2. SNMP fingerprint (si disponible)
        3. Tentative SSH
        4. Fallback Telnet
        Retourne un SwitchResult structuré.
        """
        result = SwitchResult(ip=self.target)

        def _step(icon: str, msg: str):
            logger.info(f"{icon} {msg}")
            if on_step:
                try:
                    on_step(icon, msg)
                except Exception:
                    pass

        # 1. Scan
        _step("🔍", f"Scan des services sur {self.target}…")
        result.services = self.discover_services()
        _step("📋", f"Services ouverts : {list(result.services)}")

        # 2. SNMP fingerprint
        if "snmp" in result.services:
            _step("📡", "Fingerprint SNMP…")
            result.snmp_desc = self.snmp_fingerprint()
            result.device_type = self.device_type
            _step("🏷", f"Marque détectée : {self.device_type or 'inconnue'}")
        else:
            self.device_type = "generic"
            result.device_type = "generic"

        # 3. SSH (prioritaire)
        if "ssh" in result.services:
            _step("🔐", "Tentative SSH…")
            ssh = self.ssh_connect(username, password)
            if ssh:
                try:
                    _step("✅", "SSH connecté — extraction config…")
                    result.config = self.get_config_ssh(ssh)
                    result.protocol = "ssh"
                    _step("📄", f"Config extraite ({len(result.config)} octets)")
                finally:
                    try:
                        ssh.close()
                    except Exception:
                        pass
                return result
            else:
                _step("⚠", "SSH : authentification échouée")

        # 4. Telnet (fallback)
        if "telnet" in result.services:
            _step("🔓", "Fallback Telnet…")
            tn = self.telnet_connect(username, password)
            if tn:
                try:
                    _step("✅", "Telnet connecté — extraction config…")
                    result.config = self.get_config_telnet(tn)
                    result.protocol = "telnet"
                    _step("📄", f"Config extraite ({len(result.config)} octets)")
                finally:
                    try:
                        tn.close()
                    except Exception:
                        pass
                return result
            else:
                _step("⚠", "Telnet : authentification échouée")

        result.error = "Aucun protocole disponible ou authentification échouée"
        _step("❌", result.error)
        return result

    # ── Scan multi-cibles en parallèle ───────────────────────────────────────
    @classmethod
    async def scan_range(
        cls,
        targets: List[str],
        username: str,
        password: str,
        timeout: float = 3.0,
        on_result: Optional[callable] = None,
    ) -> List[SwitchResult]:
        """
        Lance recover_config sur une liste d'IPs en parallèle (asyncio + ThreadPool).
        on_result(result) appelé à chaque appareil terminé.
        """
        loop = asyncio.get_event_loop()

        def _run(ip: str) -> SwitchResult:
            agent = cls(ip, timeout=timeout)
            return agent.recover_config(username, password)

        results: List[SwitchResult] = []
        with ThreadPoolExecutor(max_workers=min(len(targets), 10)) as ex:
            futs = {loop.run_in_executor(ex, _run, ip): ip for ip in targets}
            for fut in asyncio.as_completed(list(futs)):
                try:
                    r = await fut
                    results.append(r)
                    if on_result:
                        try:
                            on_result(r)
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"scan_range: {e}")
        return results
