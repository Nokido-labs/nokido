"""
app/forge_tldr_context.py — TLDR + HackTricks Context Injector v1.0
====================================================================
Injecte des exemples de commandes réels (tldr + HackTricks) dans le contexte
des silos AVANT envoi au LLM — le modèle génère des commandes "ready-to-run"
basées sur des sources officielles.

Flux (DIRECTIVE 2026-03-22) :
    1. tldr <outil>          → Exegol-tapple (v0.9.2) ou GitHub raw
    2. HackTricks <port>     → GitHub raw (markdown source)
    3. Contexte enrichi      → injecté dans le prompt du silo LLM
    4. LLM local             → commande prête, syntaxe correcte, exemples réels

Usage :
    from forge_tldr_context import ContextInjector
    injector = ContextInjector()

    # Enrichit un prompt avec tldr + HackTricks
    enriched = injector.enrich(
        prompt="Comment scanner les vulnérabilités SMB sur localhost ?",
        tools=["nmap","smbclient","enum4linux"],
        ports=[445, 139]
    )
    # → prompt + exemples tldr + blocs HackTricks
"""

from __future__ import annotations

import logging
import re
import subprocess
import urllib.request
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# ── Sources ───────────────────────────────────────────────────────────────────
TLDR_GITHUB = "https://raw.githubusercontent.com/tldr-pages/tldr/main/pages"
HACKTRICKS_GITHUB = "https://raw.githubusercontent.com/HackTricks-wiki/hacktricks/master/src"
EXEGOL_CONTAINER = "exegol-tapple"

# Map port → chemin HackTricks
HACKTRICKS_PAGES: dict[int | str, str] = {
    21: "network-services-pentesting/pentesting-ftp/README.md",
    22: "network-services-pentesting/pentesting-ssh.md",
    23: "network-services-pentesting/23-pentesting-telnet.md",
    25: "network-services-pentesting/pentesting-smtp/README.md",
    80: "network-services-pentesting/pentesting-web/README.md",
    110: "network-services-pentesting/pentesting-pop.md",
    139: "network-services-pentesting/pentesting-smb/README.md",
    143: "network-services-pentesting/pentesting-imap.md",
    161: "network-services-pentesting/pentesting-snmp/README.md",
    389: "network-services-pentesting/pentesting-ldap.md",
    443: "network-services-pentesting/pentesting-web/README.md",
    445: "network-services-pentesting/pentesting-smb/README.md",
    1433: "network-services-pentesting/pentesting-mssql-microsoft-sql-server/README.md",
    1883: "network-services-pentesting/1883-pentesting-mqtt-mosquitto.md",
    3306: "network-services-pentesting/pentesting-mysql.md",
    3389: "network-services-pentesting/pentesting-rdp.md",
    5432: "network-services-pentesting/pentesting-postgresql.md",
    5900: "network-services-pentesting/pentesting-vnc.md",
    6379: "network-services-pentesting/6379-pentesting-redis.md",
    8001: "network-services-pentesting/pentesting-upnp.md",
    7676: "network-services-pentesting/pentesting-upnp.md",
    8080: "network-services-pentesting/pentesting-web/README.md",
    # Alias textuels
    "smb": "network-services-pentesting/pentesting-smb/README.md",
    "rdp": "network-services-pentesting/pentesting-rdp.md",
    "ftp": "network-services-pentesting/pentesting-ftp/README.md",
    "web": "network-services-pentesting/pentesting-web/README.md",
    "ssh": "network-services-pentesting/pentesting-ssh.md",
    "upnp": "network-services-pentesting/pentesting-upnp.md",
    "ldap": "network-services-pentesting/pentesting-ldap.md",
    "snmp": "network-services-pentesting/pentesting-snmp/README.md",
    "samsung": "network-services-pentesting/pentesting-upnp.md",
}

# Map outil → commande tldr à utiliser
TOOL_TLDR_ALIASES: dict[str, str] = {
    "secretsdump": "impacket-secretsdump",
    "secretsdump.py": "impacket-secretsdump",
    "psexec.py": "impacket-psexec",
    "wmiexec.py": "impacket-wmiexec",
    "smbexec.py": "impacket-smbexec",
    "msfconsole": "metasploit",
    "feroxbuster": "feroxbuster",
    "gobuster": "gobuster",
    "enum4linux-ng": "enum4linux",
}


# ══════════════════════════════════════════════════════════════════════════════
class ContextInjector:
    """
    Injecte des contextes tldr + HackTricks dans les prompts LLM.
    Résultat : des commandes syntaxiquement correctes basées sur des sources réelles.
    """

    def __init__(self, container: str = EXEGOL_CONTAINER, timeout: int = 8):
        self._container = container
        self._timeout = timeout

    # ── TLDR ─────────────────────────────────────────────────────────────────

    @lru_cache(maxsize=128)  # noqa: B019 -- singleton context, no leak risk
    def get_tldr(self, tool: str) -> str:
        """
        Récupère la page tldr d'un outil.
        Ordre : Exegol → tldr-pages GitHub (common) → GitHub (linux) → vide
        """
        real_tool = TOOL_TLDR_ALIASES.get(tool, tool)

        # 1. Exegol (le plus rapide et complet)
        try:
            r = subprocess.run(
                ["docker", "exec", self._container, "bash", "-c", f"tldr {real_tool} 2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            errors="replace")
            clean = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout).strip()
            if clean and len(clean) > 50 and "No tldr" not in clean:
                return self._clean_tldr(clean)
        except Exception:
            pass

        # 2. GitHub raw (pas besoin d'installation)
        for prefix in ["common", "linux", "network"]:
            try:
                url = f"{TLDR_GITHUB}/{prefix}/{real_tool}.md"
                req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
                raw = urllib.request.urlopen(req, timeout=6).read().decode()
                if raw and len(raw) > 50:
                    return self._clean_tldr(raw)
            except Exception:
                pass

        logger.debug(f"[TLDR] '{tool}' non trouvé")
        return ""

    def _clean_tldr(self, raw: str) -> str:
        """Nettoie le tldr pour usage dans un prompt LLM."""
        lines = []
        for line in raw.splitlines():
            s = line.strip()
            if not s:
                continue
            # Garde : titre, description, examples (lignes avec commande)
            if s.startswith("#") or s.startswith("-") or s.startswith(" "):
                lines.append(s)
            elif not s.startswith("More information"):
                lines.append(s)
        return "\n".join(lines)

    # ── HackTricks ────────────────────────────────────────────────────────────

    @lru_cache(maxsize=64)  # noqa: B019 -- singleton context, no leak risk
    def get_hacktricks(self, port_or_topic: str | int) -> str:
        """
        Récupère les commandes de la page HackTricks pour un port ou topic.
        Retourne uniquement les headings + blocs de code.
        """
        path = HACKTRICKS_PAGES.get(port_or_topic) or HACKTRICKS_PAGES.get(str(port_or_topic).lower())
        if not path:
            logger.debug(f"[HackTricks] Pas de page pour '{port_or_topic}'")
            return ""

        url = f"{HACKTRICKS_GITHUB}/{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"})
            md = urllib.request.urlopen(req, timeout=self._timeout).read().decode("utf-8", "ignore")
            return self._extract_commands(md)
        except Exception as e:
            logger.debug(f"[HackTricks] {port_or_topic}: {e}")
            return ""

    def _extract_commands(self, md: str, max_chars: int = 2500) -> str:
        """Extrait les titres + blocs de code d'un markdown HackTricks."""
        lines, in_code = [], False
        for line in md.splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                lines.append(line)
                continue
            if in_code:
                lines.append(line)
            elif s.startswith("#"):
                lines.append(line)
        return "\n".join(lines)[:max_chars]

    # ── Context builder ───────────────────────────────────────────────────────

    def enrich(
        self,
        prompt: str,
        tools: list[str] | None = None,
        ports: list[int] | None = None,
        max_tldr_per_tool: int = 600,
        max_ht_per_port: int = 800,
    ) -> str:
        """
        Enrichit un prompt avec :
        - Les pages tldr des outils mentionnés
        - Les pages HackTricks des ports concernés

        Args:
            prompt : prompt original
            tools  : liste d'outils à documenter (détection auto si None)
            ports  : liste de ports à documenter (détection auto si None)

        Returns:
            prompt enrichi avec contexte de référence
        """
        # Détection auto des outils dans le prompt
        if tools is None:
            tools = self._detect_tools(prompt)
        if ports is None:
            ports = self._detect_ports(prompt)

        if not tools and not ports:
            return prompt

        ctx_parts = []

        # TLDR
        tldr_sections = []
        for tool in tools[:5]:  # max 5 outils
            content = self.get_tldr(tool)
            if content:
                tldr_sections.append(f"### `{tool}` — exemples officiels\n{content[:max_tldr_per_tool]}")

        if tldr_sections:
            ctx_parts.append("## Référence officielle des outils (tldr)\n" + "\n\n".join(tldr_sections))

        # HackTricks
        ht_sections = []
        seen_paths = set()
        for port in ports[:4]:  # max 4 ports
            path = HACKTRICKS_PAGES.get(port, "")
            if path in seen_paths:
                continue
            seen_paths.add(path)
            content = self.get_hacktricks(port)
            if content:
                ht_sections.append(f"### Port {port} — HackTricks\n{content[:max_ht_per_port]}")

        if ht_sections:
            ctx_parts.append("## Référence HackTricks\n" + "\n\n".join(ht_sections))

        if not ctx_parts:
            return prompt

        context_block = (
            "\n\n---\n"
            "# CONTEXTE DE RÉFÉRENCE (sources officielles)\n"
            "Utilise ces exemples comme base pour générer des commandes "
            "syntaxiquement correctes et prêtes à exécuter.\n\n" + "\n\n".join(ctx_parts) + "\n---\n"
        )

        return prompt + context_block

    def build_silo_context(self, ports: list[int], target_ip: str = "") -> str:
        """
        Construit un bloc de contexte complet pour un silo pentest.
        Utilisé par le SiloEngine pour enrichir le prompt SECURITY/EXPLOIT.
        """
        parts = []

        # Outils associés aux ports
        PORT_TOOLS = {
            21: ["ftp", "hydra"],
            22: ["ssh", "hydra", "nmap"],
            445: ["smbclient", "enum4linux", "nmap", "crackmapexec"],
            139: ["smbclient", "nbtscan"],
            3389: ["rdesktop", "xfreerdp", "nmap", "hydra"],
            80: ["curl", "nikto", "ffuf", "gobuster"],
            443: ["curl", "nikto", "ffuf", "gobuster"],
            8001: ["curl", "nmap"],
            7676: ["curl", "nmap"],
        }

        all_tools = []
        for port in ports:
            all_tools.extend(PORT_TOOLS.get(port, []))

        # Déduplication en préservant l'ordre
        seen = set()
        unique_tools = [t for t in all_tools if not (t in seen or seen.add(t))]

        # TLDR pour les outils clés
        tldr_parts = []
        for tool in unique_tools[:4]:
            content = self.get_tldr(tool)
            if content:
                tldr_parts.append(f"[{tool}]\n{content[:500]}")

        if tldr_parts:
            parts.append("# Référence outils (tldr)\n" + "\n\n".join(tldr_parts))

        # HackTricks pour les ports
        ht_parts = []
        seen_ht = set()
        for port in ports:
            ht_path = HACKTRICKS_PAGES.get(port, "")
            if ht_path and ht_path not in seen_ht:
                seen_ht.add(ht_path)
                content = self.get_hacktricks(port)
                if content:
                    ht_parts.append(f"# HackTricks — Port {port}\n{content[:800]}")

        if ht_parts:
            parts.append("\n\n".join(ht_parts))

        if target_ip:
            parts.append(f"# Cible\nIP: {target_ip}")

        return "\n\n".join(parts)

    # ── Détection auto ────────────────────────────────────────────────────────

    KNOWN_TOOLS = {
        "nmap",
        "smbclient",
        "smbmap",
        "enum4linux",
        "enum4linux-ng",
        "crackmapexec",
        "cme",
        "impacket",
        "secretsdump",
        "psexec",
        "wmiexec",
        "smbexec",
        "ntlmrelayx",
        "hydra",
        "john",
        "hashcat",
        "metasploit",
        "msfconsole",
        "ffuf",
        "gobuster",
        "feroxbuster",
        "nikto",
        "dirb",
        "curl",
        "wget",
        "sqlmap",
        "burp",
        "wfuzz",
        "dirsearch",
        "xfreerdp",
        "rdesktop",
        "rdp",
        "ftp",
        "ssh",
        "telnet",
        "nbtscan",
        "rpcdump",
        "GetNPUsers",
        "GetUserSPNs",
    }

    def _detect_tools(self, text: str) -> list[str]:
        words = set(re.findall(r"\b[\w.-]+\b", text.lower()))
        return [t for t in self.KNOWN_TOOLS if t in words]

    def _detect_ports(self, text: str) -> list[int]:
        """Détecte les ports mentionnés dans le texte."""
        # Ports explicites
        found = set(
            int(m)
            for m in re.findall(
                r"\b(21|22|23|80|139|143|161|389|443|445|"
                r"1433|1883|3306|3389|5432|5900|6379|"
                r"7676|8001|8008|8080|8443)\b",
                text,
            )
        )
        # Ports implicites par protocole
        if re.search(r"\bsmb\b|\bsamba\b", text, re.I):
            found.update([139, 445])
        if re.search(r"\brdp\b|\bremote.desktop\b", text, re.I):
            found.add(3389)
        if re.search(r"\bftp\b", text, re.I):
            found.add(21)
        if re.search(r"\bssh\b", text, re.I):
            found.add(22)
        if re.search(r"\bhttp\b|\bweb\b|\burl\b", text, re.I):
            found.update([80, 443])
        if re.search(r"\bsamsung\b|\bsmart.?tv\b|\bwebsocket\b", text, re.I):
            found.update([8001, 7676])
        return sorted(found)


# ── Singleton ──────────────────────────────────────────────────────────────────
_INJECTOR: ContextInjector | None = None


def get_injector(container: str = EXEGOL_CONTAINER) -> ContextInjector:
    global _INJECTOR
    if _INJECTOR is None:
        _INJECTOR = ContextInjector(container=container)
    return _INJECTOR
