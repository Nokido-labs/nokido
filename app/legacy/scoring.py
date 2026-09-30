"""
scoring.py — Banque de scoring des modèles + détection d'architecture cible
=============================================================================
OctoDevOps v5

Ce module est l'unique source de vérité pour :
  - Les scores statiques de chaque modèle par tâche/rôle
  - Le benchmark dynamique (tokens/s, qualité, latence)
  - La détection de l'architecture cible (OS, distrib, arch CPU, containers)
  - La sélection automatique du meilleur modèle pour une tâche donnée
    en tenant compte de l'architecture cible (ex : ne pas proposer du
    code arm64 sur un host x86_64)

Usage :
    from scoring import ModelScorer, ArchitectureProfile, score_models_for_role

    scorer = ModelScorer(ollama_url, ollama_tags_url)
    await scorer.refresh()                     # discover + benchmark en bg
    arch = await scorer.detect_architecture()  # via SSH
    model = scorer.best_model_for(AgentRole.SECURITY, arch)
"""

import asyncio
import aiohttp
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Import des rôles depuis roles.py (déjà dans le projet)
try:
    from roles import AgentRole, MODEL_PROFILES, ROLE_META
except ImportError:
    # Stubs minimaux si roles.py absent
    class AgentRole(Enum):  # type: ignore
        ANALYSTE = "analyste"
        DEBUGGER = "debugger"
        COMPARATEUR = "comparateur"
        STRATEGE = "stratege"
        JUGE = "juge"
        PLANNER = "planner"
        DISCOVERY = "discovery"
        DEVOPS = "devops"
        NETWORK = "network"
        SECURITY = "security"
        LOG_ANALYSIS = "log_analysis"
        RAG_KNOWLEDGE = "rag_knowledge"
        ACTION_EXEC = "action_exec"
        MEMORY = "memory"
        MONITORING = "monitoring"
        PATCH_MGMT = "patch_mgmt"
        COMPLIANCE = "compliance"
        INCIDENT = "incident"
        CONFIG_BACKUP = "config_backup"
        THREAT_INTEL = "threat_intel"
        ACTIVE_DIR = "active_dir"
        WINDOWS_MGMT = "windows_mgmt"
        LINUX_MGMT = "linux_mgmt"
        NETWORK_DEVICE = "network_device"
        DNS_PIHOLE = "dns_pihole"
        IDS_ZEEK = "ids_zeek"

    MODEL_PROFILES: Dict = {}
    ROLE_META: Dict = {}


# =============================================================================
# ARCHITECTURE CIBLE
# =============================================================================


class OSFamily(Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    UNKNOWN = "unknown"


class Distrib(Enum):
    DEBIAN = "debian"
    UBUNTU = "ubuntu"
    RHEL = "rhel"  # RHEL / CentOS / AlmaLinux / Rocky
    FEDORA = "fedora"
    ARCH = "arch"
    ALPINE = "alpine"
    SUSE = "suse"
    WINDOWS = "windows"
    MACOS = "macos"
    UNKNOWN = "unknown"


class CPUArch(Enum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
    ARMV7 = "armv7"
    X86_32 = "x86_32"
    UNKNOWN = "unknown"


class ContainerRuntime(Enum):
    DOCKER = "docker"
    PODMAN = "podman"
    CONTAINERD = "containerd"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass
class ArchitectureProfile:
    """Profil complet de l'hôte distant détecté via SSH."""

    os_family: OSFamily = OSFamily.UNKNOWN
    distrib: Distrib = Distrib.UNKNOWN
    distrib_version: str = ""
    cpu_arch: CPUArch = CPUArch.UNKNOWN
    kernel: str = ""
    hostname: str = ""
    container_runtime: ContainerRuntime = ContainerRuntime.UNKNOWN
    has_systemd: bool = False
    has_docker: bool = False
    has_snap: bool = False
    pkg_manager: str = ""  # apt / dnf / yum / pacman / apk …
    python_version: str = ""
    raw: Dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        parts = []
        if self.hostname:
            parts.append(self.hostname)
        parts.append(self.distrib.value)
        if self.distrib_version:
            parts.append(self.distrib_version)
        parts.append(self.cpu_arch.value)
        if self.kernel:
            parts.append(f"kernel={self.kernel}")
        if self.container_runtime != ContainerRuntime.NONE:
            parts.append(self.container_runtime.value)
        return " | ".join(parts)

    def context_hint(self) -> str:
        """Texte injecté dans le system-prompt pour contextualiser les commandes."""
        lines = [
            f"CIBLE : {self.os_family.value} / {self.distrib.value} {self.distrib_version}",
            f"ARCH CPU : {self.cpu_arch.value}",
        ]
        if self.pkg_manager:
            lines.append(f"GESTIONNAIRE DE PAQUETS : {self.pkg_manager}")
        if self.has_systemd:
            lines.append("INIT : systemd")
        if self.has_docker:
            lines.append(f"CONTAINER : {self.container_runtime.value}")
        if self.python_version:
            lines.append(f"PYTHON : {self.python_version}")
        lines.append(
            "⚠ Génère UNIQUEMENT des commandes compatibles avec cette architecture. "
            "N'utilise pas de binaires x86_64 sur arm64, ni apt sur rhel, etc."
        )
        return "\n".join(lines)


# =============================================================================
# DÉTECTEUR D'ARCHITECTURE
# =============================================================================


class ArchitectureDetector:
    """Interroge le host distant via SSH pour construire un ArchitectureProfile."""

    # Commandes de détection (ordre : rapide → précis)
    PROBE_COMMANDS: Dict[str, str] = {
        "uname_sr": "uname -sr 2>/dev/null || echo unknown",
        "uname_m": "uname -m 2>/dev/null || echo unknown",
        "hostname": "hostname -s 2>/dev/null || hostname",
        "os_release": "cat /etc/os-release 2>/dev/null || echo ''",
        "systemd": "systemctl --version 2>/dev/null | head -1 || echo ''",
        "docker": "docker --version 2>/dev/null || echo ''",
        "podman": "podman --version 2>/dev/null || echo ''",
        "python": "python3 --version 2>/dev/null || python --version 2>/dev/null || echo ''",
        "pkg_apt": "apt --version 2>/dev/null | head -1 || echo ''",
        "pkg_dnf": "dnf --version 2>/dev/null | head -1 || echo ''",
        "pkg_yum": "yum --version 2>/dev/null | head -1 || echo ''",
        "pkg_pacman": "pacman --version 2>/dev/null | head -1 || echo ''",
        "pkg_apk": "apk --version 2>/dev/null || echo ''",
        "winver": "cmd /c ver 2>/dev/null || echo ''",
    }

    def __init__(self, run_ssh_fn):
        """
        run_ssh_fn : coroutine async (cmd: str) -> (stdout, stderr, exit_code)
        Typiquement run_ssh() de Nokido.
        """
        self._run = run_ssh_fn
        self._cache: Optional[ArchitectureProfile] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 300.0  # re-détecte toutes les 5 min

    async def detect(self, force: bool = False) -> ArchitectureProfile:
        """Retourne le profil mis en cache ou relance la détection."""
        now = time.monotonic()
        if not force and self._cache is not None and now - self._cache_ts < self._cache_ttl:
            return self._cache

        results: Dict[str, str] = {}
        # Parallélise les probes
        cmds = list(self.PROBE_COMMANDS.items())
        outs = await asyncio.gather(*[self._probe(cmd) for _, cmd in cmds], return_exceptions=True)
        for (key, _), out in zip(cmds, outs):
            results[key] = out if isinstance(out, str) else ""

        profile = self._parse(results)
        self._cache = profile
        self._cache_ts = now
        logger.info(f"Architecture détectée : {profile.summary()}")
        return profile

    async def _probe(self, cmd: str) -> str:
        try:
            stdout, _, _ = await self._run(cmd)
            return stdout.strip()
        except Exception:
            return ""

    def _parse(self, r: Dict[str, str]) -> ArchitectureProfile:
        p = ArchitectureProfile(raw=r)

        # ── Hostname ──────────────────────────────────────────────────────
        p.hostname = r.get("hostname", "")

        # ── Kernel / OS family ────────────────────────────────────────────
        uname_sr = r.get("uname_sr", "").lower()
        if "linux" in uname_sr:
            p.os_family = OSFamily.LINUX
            p.kernel = re.search(r"[\d\.\-]+", uname_sr.split()[-1] if uname_sr.split() else "")
            p.kernel = p.kernel.group(0) if p.kernel else uname_sr
        elif "windows" in uname_sr or r.get("winver", ""):
            p.os_family = OSFamily.WINDOWS
        elif "darwin" in uname_sr:
            p.os_family = OSFamily.MACOS

        # ── CPU arch ──────────────────────────────────────────────────────
        arch_raw = r.get("uname_m", "").lower()
        if arch_raw in ("x86_64", "amd64"):
            p.cpu_arch = CPUArch.X86_64
        elif arch_raw in ("aarch64", "arm64"):
            p.cpu_arch = CPUArch.ARM64
        elif arch_raw.startswith("armv7"):
            p.cpu_arch = CPUArch.ARMV7
        elif arch_raw in ("i386", "i686"):
            p.cpu_arch = CPUArch.X86_32

        # ── Distribution (/etc/os-release) ────────────────────────────────
        os_rel = r.get("os_release", "").lower()
        id_match = re.search(r'^id="?([^"\n]+)"?', os_rel, re.MULTILINE)
        ver_match = re.search(r'^version_id="?([^"\n]+)"?', os_rel, re.MULTILINE)
        distrib_id = id_match.group(1).strip() if id_match else ""
        p.distrib_version = ver_match.group(1).strip() if ver_match else ""

        if "ubuntu" in distrib_id:
            p.distrib = Distrib.UBUNTU
        elif "debian" in distrib_id:
            p.distrib = Distrib.DEBIAN
        elif any(x in distrib_id for x in ("rhel", "centos", "almalinux", "rocky")):
            p.distrib = Distrib.RHEL
        elif "fedora" in distrib_id:
            p.distrib = Distrib.FEDORA
        elif "arch" in distrib_id:
            p.distrib = Distrib.ARCH
        elif "alpine" in distrib_id:
            p.distrib = Distrib.ALPINE
        elif "opensuse" in distrib_id or "sles" in distrib_id:
            p.distrib = Distrib.SUSE
        elif p.os_family == OSFamily.WINDOWS:
            p.distrib = Distrib.WINDOWS
        elif p.os_family == OSFamily.MACOS:
            p.distrib = Distrib.MACOS

        # ── Systemd ───────────────────────────────────────────────────────
        p.has_systemd = "systemd" in r.get("systemd", "").lower()

        # ── Container runtime ─────────────────────────────────────────────
        if "docker" in r.get("docker", "").lower():
            p.container_runtime = ContainerRuntime.DOCKER
            p.has_docker = True
        elif "podman" in r.get("podman", "").lower():
            p.container_runtime = ContainerRuntime.PODMAN
        else:
            p.container_runtime = ContainerRuntime.NONE

        # ── Package manager ───────────────────────────────────────────────
        if r.get("pkg_apt", "") and "apt" in r["pkg_apt"].lower():
            p.pkg_manager = "apt"
        elif r.get("pkg_dnf", "") and "dnf" in r["pkg_dnf"].lower():
            p.pkg_manager = "dnf"
        elif r.get("pkg_yum", "") and "yum" in r["pkg_yum"].lower():
            p.pkg_manager = "yum"
        elif r.get("pkg_pacman", "") and "pacman" in r["pkg_pacman"].lower():
            p.pkg_manager = "pacman"
        elif r.get("pkg_apk", "") and "apk" in r["pkg_apk"].lower():
            p.pkg_manager = "apk"

        # ── Python ────────────────────────────────────────────────────────
        py_raw = r.get("python", "")
        py_match = re.search(r"(\d+\.\d+\.\d+)", py_raw)
        p.python_version = py_match.group(1) if py_match else ""

        return p


# =============================================================================
# SCORING ENRICHI — tient compte de l'architecture cible
# =============================================================================

# Pénalités de score appliquées si le modèle est mal adapté à la cible
# Format : (condition_fn(arch), rôles_affectés, pénalité)
ARCH_PENALTIES: List[Tuple] = [
    # Si la cible est Windows, pénaliser les modèles sans profil Windows
    (
        lambda arch: arch.os_family == OSFamily.WINDOWS,
        {AgentRole.LINUX_MGMT, AgentRole.ACTION_EXEC, AgentRole.DEVOPS},
        -2.0,
    ),
    # Si la cible est ARM64, légère pénalité sur les profils trop x86-centrés
    (
        lambda arch: arch.cpu_arch == CPUArch.ARM64,
        {AgentRole.DEVOPS, AgentRole.ACTION_EXEC},
        -0.5,
    ),
    # Alpine → pénalise les suggestions apt/yum
    (
        lambda arch: arch.distrib == Distrib.ALPINE,
        {AgentRole.PATCH_MGMT, AgentRole.LINUX_MGMT},
        -1.0,
    ),
]

# Bonus si profil du modèle inclut une mention spécifique (ex: "adguard", "pihole")
ROLE_ARCH_BONUS: Dict[AgentRole, Dict[Distrib, float]] = {
    AgentRole.DNS_PIHOLE: {Distrib.DEBIAN: 0.5, Distrib.UBUNTU: 0.5},
    AgentRole.LINUX_MGMT: {Distrib.UBUNTU: 0.5, Distrib.DEBIAN: 0.5, Distrib.RHEL: 0.5, Distrib.ARCH: 0.3},
    AgentRole.WINDOWS_MGMT: {Distrib.WINDOWS: 1.5},
    AgentRole.ACTIVE_DIR: {Distrib.WINDOWS: 1.5},
}


@dataclass
class ScoredModel:
    model: str
    role: AgentRole
    static_score: float
    dynamic_score: float
    arch_bonus: float
    arch_penalty: float
    final_score: float

    def __str__(self) -> str:
        meta = ROLE_META.get(self.role, {})
        return (
            f"  {meta.get('icon', '?')} [{meta.get('label', self.role.value):22}] "
            f"→ {self.model:35} "
            f"(S={self.static_score:.1f} D={self.dynamic_score:.1f} "
            f"A={self.arch_bonus:+.1f}/{self.arch_penalty:+.1f} "
            f"F={self.final_score:.2f})"
        )


# =============================================================================
# BENCHMARK DYNAMIQUE (version allégée, sans dépendances loops.py)
# =============================================================================

# Batterie de prompts thématiques — chaque modèle est évalué sur SA spécialité
BENCH_PROMPTS: Dict[str, str] = {
    "security": ("En 3 lignes max : les 3 principaux risques d'une config SSH par défaut sur Linux ?"),
    "devops": ("En 3 lignes max : comment vérifier qu'un service systemd consomme trop de RAM ?"),
    "code": ("En 3 lignes max : quelle commande Python détecte un deadlock dans un programme async ?"),
    "réseau": ("En 3 lignes max : comment diagnostiquer une perte de paquets intermittente sur eth0 ?"),
    "reasoning": ("En 3 lignes max : différence entre un mutex et un sémaphore, avec exemple concret."),
}
# Prompt par défaut (rétro-compat)
BENCH_PROMPT = BENCH_PROMPTS["security"]

# Mots-clés par thème pour le scoring sémantique
BENCH_KEYWORDS: Dict[str, List[str]] = {
    "security": [
        "ssh",
        "root",
        "password",
        "clé",
        "key",
        "port",
        "firewall",
        "auth",
        "permission",
        "sudo",
        "fail2ban",
        "brute",
        "cipher",
        "pubkey",
    ],
    "devops": [
        "systemd",
        "journalctl",
        "memory",
        "ram",
        "cgroup",
        "service",
        "limit",
        "restart",
        "oom",
        "top",
        "ps",
        "rss",
    ],
    "code": [
        "asyncio",
        "deadlock",
        "lock",
        "thread",
        "await",
        "gather",
        "task",
        "debug",
        "traceback",
        "stack",
        "event loop",
    ],
    "réseau": [
        "ping",
        "mtr",
        "tcpdump",
        "packet",
        "loss",
        "eth",
        "interface",
        "arp",
        "route",
        "netstat",
        "ss",
        "mtu",
        "driver",
    ],
    "reasoning": [
        "mutex",
        "sémaphore",
        "semaphore",
        "thread",
        "concurrent",
        "verrou",
        "lock",
        "condition",
        "exclusion",
        "attente",
    ],
}


@dataclass
class BenchResult:
    model: str
    tok_per_sec: float = 0.0
    latency_ms: float = 0.0
    quality: float = 0.0  # [0-10]
    available: bool = True


async def _run_bench(ollama_url: str, model: str) -> BenchResult:
    """Benchmark rapide d'un modèle Ollama."""
    result = BenchResult(model=model)
    try:
        t0 = time.perf_counter()
        first_tok_t: Optional[float] = None
        tokens = 0
        reply_parts: List[str] = []

        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                ollama_url,
                json={"model": model, "messages": [{"role": "user", "content": BENCH_PROMPT}], "stream": True},
                timeout=aiohttp.ClientTimeout(total=25, connect=4),
            ) as resp:
                if resp.status != 200:
                    result.available = False
                    return result
                async for raw in resp.content:
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8", errors="replace").strip())
                    except Exception:
                        continue
                    tok = data.get("message", {}).get("content", "")
                    if tok:
                        if first_tok_t is None:
                            first_tok_t = time.perf_counter()
                            result.latency_ms = (first_tok_t - t0) * 1000
                        tokens += len(tok.split())
                        reply_parts.append(tok)
                    if data.get("done"):
                        break

        elapsed = time.perf_counter() - t0
        result.tok_per_sec = tokens / max(elapsed, 0.1)
        reply = "".join(reply_parts)
        result.quality = _score_reply(reply)
    except Exception as e:
        logger.debug(f"Bench {model}: {e}")
        result.available = False
    return result


def _score_reply(reply: str, theme: str = "security") -> float:
    """Score sémantique [0-10] d'une réponse modèle, normalisé par thème."""
    if not reply or len(reply) < 10:
        return 0.0
    s = 2.0  # base
    # Mots-clés thématiques
    keywords = BENCH_KEYWORDS.get(theme, BENCH_KEYWORDS["security"])
    kw_hits = sum(1 for k in keywords if k in reply.lower())
    s += min(4.0, kw_hits * 0.5)
    # Structure (liste numérotée ou à puces = bonne organisation)
    has_list = bool(re.search(r"(?m)^\s*[\d\-\*]", reply))
    if has_list:
        s += 1.0
    # Densité (ni trop court ni verbeux)
    words = len(reply.split())
    if 10 < words < 250:
        s += 1.0
    if words > 5:
        s += 0.5
    # Pertinence langue (réponse en français demandée)
    fr_markers = ["est", "les", "des", "pour", "avec", "sur", "une", "par"]
    if sum(1 for w in fr_markers if f" {w} " in reply.lower()) >= 3:
        s += 0.5
    # Pénalité : réponse refus ou générique
    refusal = ["je ne peux pas", "i cannot", "i'm unable", "as an ai", "en tant qu"]
    if any(r in reply.lower() for r in refusal):
        s -= 3.0
    return max(0.0, min(10.0, s))
    if len(reply) < 50:
        s -= 1.0
    return min(10.0, max(0.0, s))


# =============================================================================
# SCOREUR CENTRAL
# =============================================================================


class ModelScorer:
    """
    Point d'entrée unique pour le scoring des modèles.

    Workflow :
      1. scorer = ModelScorer(ollama_url, ollama_tags_url, run_ssh_fn)
      2. await scorer.refresh()         → discover + benchmark en arrière-plan
      3. arch = await scorer.get_arch() → profil architecture cible
      4. model = scorer.best_for(role, arch)
    """

    def __init__(
        self,
        ollama_url: str,
        ollama_tags_url: str,
        run_ssh_fn=None,  # async fn(cmd) -> (stdout, stderr, rc)
    ):
        self.ollama_url = ollama_url
        self.ollama_tags_url = ollama_tags_url
        self._run_ssh = run_ssh_fn
        self._models: List[str] = []
        self._benches: Dict[str, BenchResult] = {}
        self._refreshed: bool = False
        self._arch: Optional[ArchitectureProfile] = None
        self._arch_detector: Optional[ArchitectureDetector] = None
        if run_ssh_fn:
            self._arch_detector = ArchitectureDetector(run_ssh_fn)

    # ── Découverte des modèles ─────────────────────────────────────────────────
    async def discover(self) -> List[str]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    self.ollama_tags_url,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    data = await resp.json()
                    _EXCLUDE_PATTERNS = ("embed", "bge-m3", "bge_m3", "nomic-embed")
                    self._models = [
                        m["name"]
                        for m in data.get("models", [])
                        if not any(p in m["name"].lower() for p in _EXCLUDE_PATTERNS)
                    ]
                    logger.info(f"Modèles Ollama : {self._models}")
        except Exception as e:
            logger.warning(f"Discover models: {e}")
        return self._models

    # ── Benchmark en arrière-plan ─────────────────────────────────────────────
    async def refresh(self, bench: bool = True) -> None:
        """Discover + benchmark asynchrone (non-bloquant pour l'UI)."""
        await self.discover()
        if bench and self._models:
            results = await asyncio.gather(
                *[_run_bench(self.ollama_url, m) for m in self._models],
                return_exceptions=True,
            )
            for m, r in zip(self._models, results):
                if isinstance(r, BenchResult):
                    self._benches[m] = r
        self._refreshed = True

    # ── Détection d'architecture ──────────────────────────────────────────────
    async def get_arch(self, force: bool = False) -> Optional[ArchitectureProfile]:
        if self._arch_detector is None:
            return None
        self._arch = await self._arch_detector.detect(force=force)
        return self._arch

    # ── Score d'un modèle pour un rôle ───────────────────────────────────────
    def score(
        self,
        model: str,
        role: AgentRole,
        arch: Optional[ArchitectureProfile] = None,
    ) -> ScoredModel:
        # ── Profil statique ──────────────────────────────────────────────
        profile_key = self._find_profile_key(model)
        profile = MODEL_PROFILES.get(profile_key, MODEL_PROFILES.get("__default__", {}))
        static_s = float(profile.get(role, 6.0))

        # ── Benchmark dynamique ──────────────────────────────────────────
        bench = self._benches.get(model)
        dyn_s = 0.0
        if bench and bench.available:
            speed_s = min(10.0, bench.tok_per_sec / 8.0)
            dyn_s = bench.quality * 0.6 + speed_s * 0.4

        # ── Bonus / Pénalités architecture ───────────────────────────────
        bonus = 0.0
        penalty = 0.0
        if arch:
            # Bonus distrib
            role_bonuses = ROLE_ARCH_BONUS.get(role, {})
            bonus = role_bonuses.get(arch.distrib, 0.0)
            # Pénalités architecture
            for cond_fn, affected_roles, pen in ARCH_PENALTIES:
                if role in affected_roles and cond_fn(arch):
                    penalty += pen

        final = static_s * 0.7 + dyn_s * 0.3 + bonus + penalty
        return ScoredModel(
            model=model,
            role=role,
            static_score=static_s,
            dynamic_score=dyn_s,
            arch_bonus=bonus,
            arch_penalty=penalty,
            final_score=max(0.0, final),
        )

    def _get_profile_val(self, model: str, role) -> float:
        """Retourne la valeur d'un rôle dans le profil d'un modèle."""
        try:
            from roles import MODEL_PROFILES

            key = self._find_profile_key(model)
            return MODEL_PROFILES.get(key, {}).get(role, 6.0)
        except Exception:
            return 6.0

    def _find_profile_key(self, model: str) -> str:
        ml = model.lower()
        # Tri par longueur desc pour préférer la clé la plus précise
        for key in sorted(MODEL_PROFILES.keys(), key=len, reverse=True):
            if key == "__default__":
                continue
            if ml.startswith(key) or key in ml:
                return key
        return "__default__"

    # ── Meilleur modèle pour un rôle ─────────────────────────────────────────
    def best_for(
        self,
        role: AgentRole,
        arch: Optional[ArchitectureProfile] = None,
        exclude: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Retourne le nom du meilleur modèle disponible pour le rôle donné,
        en tenant compte de l'architecture cible.
        """
        if not self._models:
            return None
        # Exclure les modèles embeddings-only (RAG_KNOWLEDGE=0 signale ce cas)
        from roles import AgentRole as _AR

        pool = [
            m
            for m in self._models
            if not (exclude and m in exclude) and self._get_profile_val(m, _AR.RAG_KNOWLEDGE) != 0.0
        ]
        if not pool:
            pool = [m for m in self._models if not (exclude and m in exclude)]

        scored = sorted(
            [self.score(m, role, arch) for m in pool],
            key=lambda s: s.final_score,
            reverse=True,
        )
        return scored[0].model if scored else None

    # ── Attribution multi-rôles (greedy sans doublons si possible) ─────────────
    def assign_roles(
        self,
        roles: List[AgentRole],
        arch: Optional[ArchitectureProfile] = None,
    ) -> Dict[AgentRole, str]:
        """
        Attribue un modèle à chaque rôle.
        Préfère éviter les doublons mais les autorise si nécessaire.
        """
        assignments: Dict[AgentRole, str] = {}
        used: List[str] = []
        for role in roles:
            m = self.best_for(role, arch, exclude=used)
            if m is None:
                m = self.best_for(role, arch)  # fallback avec doublons
            if m:
                assignments[role] = m
                used.append(m)
        return assignments

    # ── Rapport de scoring (pour @role list) ─────────────────────────────────
    def report(self, arch: Optional[ArchitectureProfile] = None) -> str:
        if not self._models:
            return "Aucun modèle découvert."
        lines = ["[bold]Banque de scoring — modèles disponibles :[/]"]
        for m in self._models:
            bench = self._benches.get(m)
            bench_str = ""
            if bench and bench.available:
                bench_str = (
                    f"  {bench.tok_per_sec:5.1f} tok/s  lat={bench.latency_ms:.0f}ms  qualité={bench.quality:.1f}/10"
                )
            lines.append(f"  • {m:40}{bench_str}")
        if arch:
            lines.append(f"\n[bold]Architecture cible :[/] {arch.summary()}")
        return "\n".join(lines)

    @property
    def models(self) -> List[str]:
        return list(self._models)

    @property
    def is_ready(self) -> bool:
        return self._refreshed and bool(self._models)
