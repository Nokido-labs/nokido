"""
app/forge_noise_guardian.py — Noise Guardian v1.0
===================================================
Garde-fou sémantique : vérifie et protège chaque fragment
avant envoi à un modèle Cloud.

4 protections :

1. MAGIC CONSTANTS — neutralise les constantes techniques reconnaissables
   0xDEADBEEF → GENERIC_HEX_452, MS17-010 → GENERIC_VULN_SIG_128
   Empêche le LLM cloud de reconnaître des exploits connus.

2. PERSISTENCE DES ALIAS — localhost → GENERIC_IP_ADDR_882
   Même IP = même alias dans toute la session.
   Le LLM garde la cohérence logique sans connaître la vraie valeur.

3. INJECTION D'ENTROPIE — fragments trop "purs" → suspects
   Ajoute des lignes de debug système banales pour que le fragment
   ressemble à une sortie de monitoring standard.

4. VALIDATION MCP — si le fragment contient des instructions
   qui pourraient contourner les tools, blocage avant envoi.
"""

from __future__ import annotations

# DEAD_IMPORT removed: import hashlib
import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Résultats de validation ───────────────────────────────────────────────────
@dataclass
class GuardianResult:
    passed: bool
    fragment: str  # fragment modifié (ou original si bloqué)
    alias_map: dict  # {valeur_réelle: alias_généré}
    warnings: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    entropy_added: bool = False
    constants_neutralized: int = 0
    aliases_applied: int = 0


# ── Magic Constants catalog ───────────────────────────────────────────────────
# Patterns qui permettraient à un LLM cloud de reconnaître une vuln précise
MAGIC_PATTERNS = [
    # CVEs et vuln IDs
    (re.compile(r"\bCVE-\d{4}-\d+\b", re.I), "GENERIC_VULN_SIG"),
    (re.compile(r"\bMS\d{2}-\d{3}\b", re.I), "GENERIC_MSADV"),
    # Noms d'exploit publics — masqués uniquement en mode cloud (add_entropy=True)
    # En mode local (add_entropy=False), ces noms restent visibles pour la lisibilité
    # (re.compile(r'\bEternalBlue\b', re.I),  "EXPLOIT_MODULE_A"),  # désactivé
    # (re.compile(r'\bBlueKeep\b', re.I),     "EXPLOIT_MODULE_B"),  # désactivé
    # (re.compile(r'\bWannaCry\b', re.I),     "EXPLOIT_MODULE_C"),  # désactivé
    # Constantes hex typiques d'exploits
    (re.compile(r"\b0x[0-9A-Fa-f]{4,16}\b"), "GENERIC_HEX_CONST"),
    # Offsets et shellcodes
    (re.compile(r"\b\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2})+"), "SHELLCODE_BYTES"),
    # Outils d'exploitation connus
    (re.compile(r"\bMimikatz\b", re.I), "CRED_TOOL_A"),
    (re.compile(r"\bMetasploit|msfconsole|msfvenom\b", re.I), "EXPLOIT_FW"),
    (re.compile(r"\bCobalt Strike\b", re.I), "C2_PLATFORM_A"),
    (re.compile(r"\bBloodHound\b", re.I), "AD_ENUM_TOOL"),
    # Signatures réseau spécifiques
    (re.compile(r"\bSMB1|SMBv1\b", re.I), "PROTO_LEGACY_A"),
    (re.compile(r"\bNTLMv1\b", re.I), "AUTH_LEGACY_A"),
    # Hash formats reconnaissables
    (re.compile(r"\b[0-9a-fA-F]{32}:[0-9a-fA-F]{32}\b"), "CRED_HASH_NTLM"),
    (re.compile(r"\b\$krb5tgs\$\d+\$[^\s]+"), "CRED_HASH_KERB"),
    (re.compile(r"\b\$krb5asrep\$\d+\$[^\s]+"), "CRED_HASH_ASREP"),
]

# Patterns d'IPs à pseudonymiser
IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Hostnames LAN
HOST_PATTERN = re.compile(r"\b[\w-]+\.(?:local|lan|home|internal|corp|localdomain)\b", re.I)

# Lignes d'entropie : faux logs système anodins
ENTROPY_LINES = [
    "# [sys] kernel: audit: type=1305 audit(1711234567.891:42): auid=0",
    "# [sys] systemd[1]: Started Daily apt upgrade and clean activities.",
    "# [sys] kernel: NET: Registered PF_PACKET protocol family",
    "# [debug] poll_interval=30s last_check=1711234512 status=nominal",
    "# [monitor] cpu_usage=12.4% mem_free=6821MB uptime=14d_3h",
    "# [cron] /usr/sbin/logrotate /etc/logrotate.conf: no action needed",
    "# [watchdog] heartbeat OK ts=1711234590 pid=1337 status=healthy",
    "# [net] interface eth0 stats: rx_bytes=1482305 tx_bytes=893210",
    "# [audit] session_id=8821 login=svc_monitor from=127.0.0.1",
    "# [sched] task_queue: 0 pending, last_run=14:23:07, next=14:53:07",
]

# Score de "pureté" — un fragment trop propre est suspect
PURITY_KEYWORDS = [
    "exploit",
    "vulnerability",
    "attack",
    "payload",
    "shellcode",
    "overflow",
    "injection",
    "bypass",
    "privilege",
    "escalation",
    "lateral",
    "persistence",
    "backdoor",
    "rootkit",
    "keylogger",
    "exfiltration",
    "command",
    "control",
    "beacon",
    "implant",
]


class NoiseGuardian:
    """
    Garde-fou sémantique — s'assure que chaque fragment envoyé à un LLM cloud
    ne permet pas de reconstituer la mission réelle par pattern matching.
    """

    def __init__(self, session_seed: Optional[str] = None):
        # Seed de session pour alias déterministes
        self._seed = session_seed or str(int(time.time()))
        self._rng = random.Random(self._seed)
        # Persistance des alias dans la session
        self._ip_aliases: dict[str, str] = {}
        self._host_aliases: dict[str, str] = {}
        self._const_counts: dict[str, int] = {}

    # ── Génération d'alias ────────────────────────────────────────────────────
    def _ip_alias(self, ip: str) -> str:
        if ip not in self._ip_aliases:
            n = len(self._ip_aliases) + 100 + self._rng.randint(0, 899)
            self._ip_aliases[ip] = f"GENERIC_IP_ADDR_{n}"
        return self._ip_aliases[ip]

    def _host_alias(self, host: str) -> str:
        if host not in self._host_aliases:
            n = len(self._host_aliases) + 200 + self._rng.randint(0, 799)
            self._host_aliases[host] = f"GENERIC_HOST_{n}"
        return self._host_aliases[host]

    def _const_alias(self, base_name: str) -> str:
        n = self._const_counts.get(base_name, 0)
        self._const_counts[base_name] = n + 1
        suffix = 100 + self._rng.randint(0, 899)
        return f"{base_name}_{suffix}"

    # ── Calcul du score de pureté ─────────────────────────────────────────────
    def _purity_score(self, text: str) -> float:
        """
        0.0 = très bruité (bon), 1.0 = trop pur (suspect)
        Un fragment qui parle directement d'exploitation sans bruit
        est plus reconnaissable pour un LLM cloud.
        """
        low = text.lower()
        hits = sum(1 for kw in PURITY_KEYWORDS if kw in low)
        words = max(len(text.split()), 1)
        ratio = hits / (words / 10)  # ratio hits pour 10 mots
        return min(ratio, 1.0)

    # ── Injection d'entropie ──────────────────────────────────────────────────
    def _inject_entropy(self, text: str, lines_count: int = 3) -> str:
        """Insère des lignes de debug système anodines dans le fragment."""
        lines = text.splitlines()
        noise_lines = self._rng.sample(ENTROPY_LINES, min(lines_count, len(ENTROPY_LINES)))
        # Insère au début, au milieu et à la fin
        positions = sorted(
            set(
                [
                    0,
                    len(lines) // 2,
                    max(0, len(lines) - 1),
                ]
            )
        )
        offset = 0
        for pos in positions:
            if noise_lines:
                lines.insert(pos + offset, noise_lines.pop())
                offset += 1
        return "\n".join(lines)

    # ── Validation MCP ────────────────────────────────────────────────────────
    def _check_mcp_compliance(self, text: str) -> tuple[bool, str]:
        """
        Détecte les instructions qui pourraient contourner les tools MCP
        ou injecter des commandes dans le flux cloud.
        """
        injection_patterns = [
            (r"ignore previous instructions", "prompt injection classique"),
            (r"ignore all (?:previous|prior)", "prompt injection variante"),
            (r"(?i)system:\s*override", "override système"),
            (r"disregard (?:all |your )", "injection disregard"),
            (r"you are now", "tentative de jailbreak"),
            (r"\bDAN\b.*do anything now|do anything now", "jailbreak DAN"),
            (r"system:\s*override", "override système"),
            (r"<\|.*?\|>", "token spécial LLM"),
            (r"\[INST\]|\[/INST\]", "format Llama inject"),
            (r"<system>.*?</system>", "balise système"),
        ]
        for pattern, reason in injection_patterns:
            if re.search(pattern, text, re.I | re.DOTALL):
                return False, f"Injection détectée: {reason}"
        return True, ""

    # ── Pipeline principal ────────────────────────────────────────────────────
    def validate(
        self,
        fragment: str,
        silo_name: str = "unknown",
        force_entropy: bool = False,
        entropy_lines: int = 3,
    ) -> GuardianResult:
        """
        Valide et protège un fragment avant envoi cloud.

        Args:
            fragment:      Le texte à protéger
            silo_name:     Nom du silo (pour les logs)
            force_entropy: Force l'injection d'entropie même si non nécessaire
            entropy_lines: Nombre de lignes d'entropie à injecter

        Returns:
            GuardianResult avec le fragment modifié et le rapport
        """
        result = GuardianResult(passed=True, fragment=fragment, alias_map={})

        # ── 1. Validation MCP ─────────────────────────────────────────────
        mcp_ok, mcp_reason = self._check_mcp_compliance(fragment)
        if not mcp_ok:
            result.passed = False
            result.blocked_reason = mcp_reason
            result.warnings.append(f"[BLOCKED] {mcp_reason}")
            return result  # bloqué — renvoie l'original non modifié

        text = fragment

        # ── 2. Pseudonymisation IPs ───────────────────────────────────────
        def repl_ip(m):
            alias = self._ip_alias(m.group(0))
            result.alias_map[m.group(0)] = alias
            result.aliases_applied += 1
            return alias

        text = IP_PATTERN.sub(repl_ip, text)

        # ── 3. Pseudonymisation hostnames LAN ────────────────────────────
        def repl_host(m):
            alias = self._host_alias(m.group(0))
            result.alias_map[m.group(0)] = alias
            result.aliases_applied += 1
            return alias

        text = HOST_PATTERN.sub(repl_host, text)

        # ── 4. Neutralisation magic constants ────────────────────────────
        for pattern, base_name in MAGIC_PATTERNS:

            def repl_const(m, bn=base_name):
                alias = self._const_alias(bn)
                result.alias_map[m.group(0)] = alias
                result.constants_neutralized += 1
                return alias

            text = pattern.sub(repl_const, text)

        # ── 5. Injection d'entropie si fragment trop pur ──────────────────
        purity = self._purity_score(text)
        if force_entropy or purity > 0.3:
            n_lines = entropy_lines if purity < 0.6 else entropy_lines + 2
            text = self._inject_entropy(text, n_lines)
            result.entropy_added = True
            result.warnings.append(f"[ENTROPY] Pureté={purity:.2f} → {n_lines} lignes injectées")

        # ── 6. Rapport final ──────────────────────────────────────────────
        result.fragment = text
        if result.constants_neutralized:
            result.warnings.append(f"[NEUTRALIZED] {result.constants_neutralized} constantes")
        if result.aliases_applied:
            result.warnings.append(f"[ALIASED] {result.aliases_applied} identifiants pseudonymisés")

        return result

    def deanonymize(self, text: str) -> str:
        """
        Restaure les vraies valeurs dans la réponse reçue du LLM cloud.
        Utilise le mapping complet de la session.
        """
        result = text
        # Trie du plus long alias au plus court pour éviter les remplacements partiels
        all_aliases = {}
        for real, alias in self._ip_aliases.items():
            all_aliases[alias] = real
        for real, alias in self._host_aliases.items():
            all_aliases[alias] = real
        # Les magic constants ne sont PAS dé-anonymisées — elles restent génériques
        # dans la réponse (on ne veut pas que la réponse cloud mentionne MS17-010)

        for alias, real in sorted(all_aliases.items(), key=lambda x: -len(x[0])):
            result = result.replace(alias, real)
        return result

    def session_report(self) -> dict:
        """Résumé de la session de protection."""
        return {
            "seed": self._seed,
            "ips_aliased": len(self._ip_aliases),
            "hosts_aliased": len(self._host_aliases),
            "constants_neutralized_types": len(self._const_counts),
            "ip_map": self._ip_aliases.copy(),
            "host_map": self._host_aliases.copy(),
        }


# ── Singleton de session ──────────────────────────────────────────────────────
_GUARDIAN: Optional[NoiseGuardian] = None


def get_guardian(reset: bool = False) -> NoiseGuardian:
    global _GUARDIAN
    if _GUARDIAN is None or reset:
        _GUARDIAN = NoiseGuardian()
    return _GUARDIAN


# ── Helper rapide pour le SiloEngine ─────────────────────────────────────────
def guard_fragment(text: str, silo: str = "unknown") -> tuple[str, GuardianResult]:
    """
    Protège un fragment en une ligne.
    Retourne (fragment_protégé, résultat).
    """
    guardian = get_guardian()
    result = guardian.validate(text, silo_name=silo)
    return result.fragment, result


def guard_and_log(text: str, silo: str, logger=None) -> str:
    """
    Protège + logue les warnings. Retourne le fragment protégé.
    Bloque si injection détectée.
    """
    protected, result = guard_fragment(text, silo)
    if not result.passed:
        if logger:
            logger.error(f"[Guardian] BLOQUÉ silo={silo}: {result.blocked_reason}")
        raise ValueError(f"Fragment bloqué par le Noise Guardian: {result.blocked_reason}")
    if result.warnings and logger:
        for w in result.warnings:
            logger.info(f"[Guardian] {silo}: {w}")
    return protected
