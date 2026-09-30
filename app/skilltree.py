"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_060529_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
skilltree.py — Arbre de competences hierarchique avec apprentissage autonome.

Etats : unknown -> searching -> learning -> verified -> mastered
Regle : UNVERIFIED passe VERIFIED apres 3 succes distincts.
"""

import asyncio, json, logging, time
from pathlib import Path
from typing import Dict, List, Callable
from dataclasses import dataclass, field
from textual.containers import Vertical
from textual.widgets import Static
from textual.reactive import reactive

logger = logging.getLogger(__name__)

# =============================================================================
# ARBRE STATIQUE
# =============================================================================
SKILL_TREE: Dict[str, dict] = {
    "general": {
        "label": "General",
        "children": ["python", "systeme", "reseau", "securite", "devops"],
        "parent": None,
        "keywords": ["aide", "info", "general", "base"],
    },
    "python": {
        "label": "Python",
        "children": ["python_stdlib", "python_async", "python_data", "python_web"],
        "parent": "general",
        "keywords": ["python", "pip", "venv", "script", "module"],
    },
    "python_stdlib": {
        "label": "Stdlib",
        "children": [],
        "parent": "python",
        "keywords": [
            "os",
            "sys",
            "pathlib",
            "json",
            "re",
            "subprocess",
            "logging",
            "collections",
            "itertools",
            "functools",
            "datetime",
            "hashlib",
        ],
    },
    "python_async": {
        "label": "Async/IO",
        "children": [],
        "parent": "python",
        "keywords": ["asyncio", "aiohttp", "await", "coroutine", "event_loop", "zmq"],
    },
    "python_data": {
        "label": "Data Science",
        "children": [],
        "parent": "python",
        "keywords": ["numpy", "pandas", "matplotlib", "sklearn", "torch", "tensorflow", "dataframe", "array"],
    },
    "python_web": {
        "label": "Web/API",
        "children": [],
        "parent": "python",
        "keywords": ["flask", "fastapi", "django", "requests", "api", "rest", "http"],
    },
    "systeme": {
        "label": "Systeme",
        "children": ["systeme_linux", "systeme_windows", "systeme_services"],
        "parent": "general",
        "keywords": ["systeme", "os", "kernel", "processus", "memoire", "disque"],
    },
    "systeme_linux": {
        "label": "Linux",
        "children": [],
        "parent": "systeme",
        "keywords": ["linux", "debian", "ubuntu", "apt", "systemctl", "journalctl", "bash", "shell", "cron", "fstab"],
    },
    "systeme_windows": {
        "label": "Windows",
        "children": [],
        "parent": "systeme",
        "keywords": ["windows", "powershell", "cmd", "registry", "wsl"],
    },
    "systeme_services": {
        "label": "Services",
        "children": [],
        "parent": "systeme",
        "keywords": ["systemd", "service", "daemon", "init", "crontab", "timer"],
    },
    "reseau": {
        "label": "Reseau",
        "children": ["reseau_protocoles", "reseau_vpn", "reseau_dns", "reseau_monitoring"],
        "parent": "general",
        "keywords": ["reseau", "network", "ip", "tcp", "udp", "interface", "routage"],
    },
    "reseau_protocoles": {
        "label": "Protocoles",
        "children": [],
        "parent": "reseau",
        "keywords": ["tcp", "udp", "icmp", "http", "https", "ssh", "ftp", "smtp", "dhcp", "arp"],
    },
    "reseau_vpn": {
        "label": "VPN",
        "children": [],
        "parent": "reseau",
        "keywords": ["wireguard", "openvpn", "ipsec", "vpn", "tunnel"],
    },
    "reseau_dns": {
        "label": "DNS",
        "children": [],
        "parent": "reseau",
        "keywords": ["dns", "bind", "unbound", "adguard", "pihole", "dnsmasq", "nslookup", "dig"],
    },
    "reseau_monitoring": {
        "label": "Monitoring",
        "children": [],
        "parent": "reseau",
        "keywords": ["prometheus", "grafana", "zabbix", "nagios", "snmp", "netdata"],
    },
    "securite": {
        "label": "Securite",
        "children": ["securite_firewall", "securite_hardening", "securite_audit"],
        "parent": "general",
        "keywords": ["securite", "security", "chiffrement", "certificat", "ssl", "tls"],
    },
    "securite_firewall": {
        "label": "Firewall",
        "children": [],
        "parent": "securite",
        "keywords": ["iptables", "nftables", "ufw", "firewalld", "fail2ban", "firewall"],
    },
    "securite_hardening": {
        "label": "Hardening",
        "children": [],
        "parent": "securite",
        "keywords": ["hardening", "cis", "sshd_config", "pam", "selinux", "apparmor"],
    },
    "securite_audit": {
        "label": "Audit Secu",
        "children": [],
        "parent": "securite",
        "keywords": ["audit", "lynis", "openvas", "nmap", "pentest", "cve", "bandit"],
    },
    "devops": {
        "label": "DevOps",
        "children": ["devops_containers", "devops_ci", "devops_iac"],
        "parent": "general",
        "keywords": ["devops", "deploy", "pipeline", "infra", "cloud"],
    },
    "devops_containers": {
        "label": "Containers",
        "children": [],
        "parent": "devops",
        "keywords": ["docker", "podman", "compose", "dockerfile", "kubernetes", "k8s", "helm"],
    },
    "devops_ci": {
        "label": "CI/CD",
        "children": [],
        "parent": "devops",
        "keywords": ["github", "gitlab", "jenkins", "ci", "cd", "pipeline", "actions", "workflow"],
    },
    "devops_iac": {
        "label": "IaC",
        "children": [],
        "parent": "devops",
        "keywords": ["ansible", "terraform", "puppet", "chef", "playbook", "inventory"],
    },
}

# ── Nœuds pentest / IoT — extension dynamique ─────────────────────────────
_PENTEST_NODES: Dict[str, dict] = {
    "securite_pentest": {
        "label": "Pentest",
        "children": ["pentest_recon", "pentest_enum", "pentest_exploit", "pentest_postexploit"],
        "parent": "securite",
        "keywords": [
            "pentest",
            "exegol",
            "pipeline",
            "phase",
            "audit",
            "payload",
            "poc",
            "rce",
            "cve",
            "ghsa",
            "cvss",
            "cwe",
            "arp",
            "ssdp",
        ],
    },
    "pentest_recon": {
        "label": "Reconnaissance",
        "children": [],
        "parent": "securite_pentest",
        "keywords": [
            "recon",
            "reconnaissance",
            "arp",
            "oui",
            "ssdp",
            "multicast",
            "sweep",
            "discovery",
            "nmap",
            "masscan",
        ],
    },
    "pentest_enum": {
        "label": "Enumeration",
        "children": [],
        "parent": "securite_pentest",
        "keywords": ["enum", "enumeration", "banner", "fingerprint", "ssl", "cert", "eureka", "upnp", "snmp", "curl"],
    },
    "pentest_exploit": {
        "label": "Exploitation",
        "children": [],
        "parent": "securite_pentest",
        "keywords": [
            "exploit",
            "exploitation",
            "poc",
            "rce",
            "payload",
            "pickle",
            "deserialization",
            "unauth",
            "bypass",
            "injection",
            "xss",
        ],
    },
    "pentest_postexploit": {
        "label": "Post-exploitation",
        "children": [],
        "parent": "securite_pentest",
        "keywords": ["postexploit", "pivot", "lateral", "report", "remediation", "finding", "ghsa"],
    },
    "reseau_iot": {
        "label": "IoT Network",
        "children": [],
        "parent": "reseau",
        "keywords": [
            "iot",
            "chromecast",
            "smarttv",
            "tizen",
            "smartthings",
            "cast",
            "upnp",
            "8008",
            "8001",
            "8002",
            "philips",
            "ampoule",
            "bulb",
            "samsung",
            "eureka_info",
            "cast_build_revision",
        ],
    },
    "fuzzing": {
        "label": "Semantic Fuzzing",
        "children": [],
        "parent": "securite_audit",
        "keywords": ["fuzzing", "fuzzer", "semantic", "ast", "sandbox", "crash", "leak", "deadlock", "psutil", "rss"],
    },
}
# Sous-arbre déporté (lab borné) : fusionné dans l'arbre vivant SEULEMENT si le lab
# est explicitement activé. Gel, pas suppression — hors lab, ces nœuds n'existent pas
# dans l'arbre par défaut.
import os as _os
if _os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON"):
    SKILL_TREE.update(_PENTEST_NODES)
    SKILL_TREE["securite"]["children"].append("securite_pentest")
SKILL_TREE["reseau"]["children"].append("reseau_iot")
SKILL_TREE["securite_audit"]["children"].append("fuzzing")

_KW_INDEX: Dict[str, List[str]] = {}
for _sid, _sd in SKILL_TREE.items():
    for _kw in _sd.get("keywords", []):
        _KW_INDEX.setdefault(_kw.lower(), []).append(_sid)


def detect_skills(text: str) -> list[str]:
    """Detect skill identifiers present in a description.

    Args:
        text: Freeform description to analyse.

    Returns:
        A sorted list of skill IDs, including all ancestors found in
        :data:`SKILL_TREE`.
    """
    words: set[str] = {w.lower().strip(".,;:!?()[]{}") for w in text.split()}
    found: set[str] = set()
    for w in words:
        for sid in _KW_INDEX.get(w, []):
            found.add(sid)

    with_parents: set[str] = set()
    for sid in found:
        with_parents.add(sid)
        p: str | None = SKILL_TREE.get(sid, {}).get("parent")
        while p is not None:
            with_parents.add(p)
            p = SKILL_TREE.get(p, {}).get("parent")

    return sorted(with_parents)


def get_dependencies(skill_id: str) -> List[str]:
    """Get dependencies.

    Args:
        skill_id: Description.
    """
    deps = []
    p = SKILL_TREE.get(skill_id, {}).get("parent")
    while p:
        deps.append(p)
        p = SKILL_TREE.get(p, {}).get("parent")
    return list(reversed(deps))


def get_subtree(skill_id: str) -> List[str]:
    """Get subtree.

    Args:
        skill_id: Description.
    """
    r = []
    for c in SKILL_TREE.get(skill_id, {}).get("children", []):
        r.append(c)
        r.extend(get_subtree(c))
    return r


# =============================================================================
# SKILL LEARNER
# =============================================================================
@dataclass(slots=True)
class SkillState:
    """Skillstate."""

    name: str
    status: str = "unknown"
    score: float = 0.0
    uses: int = 0
    errors: int = 0
    successes: int = 0
    unverified: bool = True
    last_task: str = ""
    tasks_ok: list = field(default_factory=list)
    last_disco: float = 0.0
    disco_count: int = 0


class SkillLearner:
    """Skilllearner."""

    THRESHOLD = 0.7
    VERIFY_COUNT = 3
    DISCO_COOLDOWN = 300
    MAX_DISCO_PER_CYCLE = 3
    CYCLE_INTERVAL = 120

    def __init__(self, registry_path: Path = None) -> None:
        """Init.

        Args:
            registry_path: Description.
        """
        self._skills: Dict[str, SkillState] = {}
        self._registry_path = registry_path
        self._running = False
        self._callbacks: List[Callable] = []
        if registry_path:
            self._load()

    def _load(self) -> None:
        """Load."""
        if not self._registry_path or not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            for name, d in data.items():
                self._skills[name] = SkillState(
                    name=d.get("name", name),
                    status=d.get("status", "unknown"),
                    score=d.get("score", 0.0),
                    uses=d.get("uses", 0),
                    errors=d.get("errors", 0),
                    successes=d.get("successes", 0),
                    unverified=d.get("unverified", True),
                    last_task=d.get("last_task", ""),
                    tasks_ok=d.get("tasks_ok", []),
                    last_disco=d.get("last_disco", 0.0),
                    disco_count=d.get("disco_count", 0),
                )
        except Exception as e:
            logger.debug(f"SkillLearner._load: {e}")

    def save(self) -> None:
        """Save."""
        if not self._registry_path:
            return
        try:
            self._registry_path.parent.mkdir(exist_ok=True)
            data = {
                n: {
                    "name": s.name,
                    "status": s.status,
                    "score": s.score,
                    "uses": s.uses,
                    "errors": s.errors,
                    "successes": s.successes,
                    "unverified": s.unverified,
                    "last_task": s.last_task,
                    "tasks_ok": s.tasks_ok[-20:],
                    "last_disco": s.last_disco,
                    "disco_count": s.disco_count,
                }
                for n, s in self._skills.items()
            }
            self._registry_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"SkillLearner.save: {e}")

    """On update.

    Args:
        cb: Description.
    """

    def on_update(self, cb) -> None:
        """On update."""
        self._callbacks.append(cb)

    def _notify(self, sid, status) -> None:
        """Notify.

        Args:
            sid: Description.
            status: Description.
        """
        for cb in self._callbacks:
            try:
                cb(sid, status)
            except Exception:
                pass

    def get(self, sid: str) -> SkillState:
        """Get.

        Args:
            sid: Description.
        """
        if sid not in self._skills:
            self._skills[sid] = SkillState(name=SKILL_TREE.get(sid, {}).get("label", sid))
        return self._skills[sid]

    def update_score(self, sid, score) -> None:
        """Update score.

        Args:
            sid: Description.
            score: Description.
        """
        s = self.get(sid)
        s.score = score
        if score >= self.THRESHOLD and s.successes >= self.VERIFY_COUNT:
            s.status = "mastered"
            s.unverified = False
        elif score >= self.THRESHOLD:
            s.status = "verified" if s.successes >= 1 else "learning"
        elif s.disco_count > 0:
            s.status = "learning"
        self._notify(sid, s.status)

    def record_success(self, sid, task_id) -> None:
        """Record success.

        Args:
            sid: Description.
            task_id: Description.
        """
        s = self.get(sid)
        s.uses += 1
        if task_id not in s.tasks_ok:
            s.tasks_ok.append(task_id)
            s.successes += 1
        if s.successes >= self.VERIFY_COUNT and s.score >= self.THRESHOLD:
            s.status = "mastered"
            s.unverified = False
        elif s.successes >= self.VERIFY_COUNT:
            s.status = "verified"
            s.unverified = False
        self._notify(sid, s.status)
        self.save()

    def record_error(self, sid) -> None:
        """Record error.

        Args:
            sid: Description.
        """
        s = self.get(sid)
        s.errors += 1
        if s.errors > s.successes and s.status == "mastered":
            s.status = "learning"
            s.unverified = True
            self._notify(sid, s.status)
        self.save()

    def record_disco(self, sid) -> None:
        """Record disco.

        Args:
            sid: Description.
        """
        s = self.get(sid)
        s.disco_count += 1
        s.last_disco = time.time()
        if s.status == "unknown":
            s.status = "learning"
        self._notify(sid, s.status)
        self.save()

    def needs_learning(self, sid) -> bool:
        """Needs learning.

        Args:
            sid: Description.
        """
        s = self.get(sid)
        if s.status == "mastered":
            return False
        if s.score >= self.THRESHOLD and s.successes >= self.VERIFY_COUNT:
            return False
        if time.time() - s.last_disco < self.DISCO_COOLDOWN:
            return False
        return True

    def dependencies_met(self, sid) -> bool:
        """Dependencies met.

        Args:
            sid: Description.
        """
        for dep in get_dependencies(sid):
            if self.get(dep).status == "unknown":
                return False
        return True

    def get_learning_plan(self) -> List[str]:
        """Get learning plan."""
        plan, q, visited = [], ["general"], set()
        while q:
            c = q.pop(0)
            if c in visited:
                continue
            visited.add(c)
            if self.needs_learning(c) and self.dependencies_met(c):
                plan.append(c)
                if len(plan) >= self.MAX_DISCO_PER_CYCLE:
                    break
            q.extend(SKILL_TREE.get(c, {}).get("children", []))
        return plan

    def tree_status(self) -> Dict[str, dict]:
        """Tree status."""
        return {
            sid: {
                "label": SKILL_TREE[sid]["label"],
                "status": self.get(sid).status,
                "score": self.get(sid).score,
                "parent": SKILL_TREE[sid].get("parent"),
                "children": SKILL_TREE[sid].get("children", []),
                "needs_learning": self.needs_learning(sid),
            }
            for sid in SKILL_TREE
        }

    async def run_cycle(self, discover_fn=None, check_fn=None, log_fn=None) -> dict:
        """Run cycle.

        Args:
            discover_fn: Description.
            check_fn: Description.
            log_fn: Description.
        """
        _log = log_fn or (lambda m: logger.info(m))
        plan = self.get_learning_plan()
        if not plan:
            _log("[dim]Arbre OK — rien a apprendre[/dim]")
            return {"learned": [], "failed": []}
        _log(f"[bold]Cycle : {len(plan)} competences[/bold]")
        learned, failed = [], []
        for sid in plan:
            self._notify(sid, "searching")
            if check_fn:
                try:
                    score = await check_fn(sid)
                    self.update_score(sid, score)
                    if score >= self.THRESHOLD:
                        _log(f"  [green]{sid} OK ({score:.2f})[/green]")
                        learned.append(sid)
                        continue
                except Exception:
                    pass
            if discover_fn:
                self._notify(sid, "learning")
                _log(f"  [yellow]{sid} -> disco[/yellow]")
                try:
                    ok = await asyncio.wait_for(discover_fn(sid), timeout=15.0)
                    if ok:
                        self.record_disco(sid)
                        if check_fn:
                            score = await check_fn(sid)
                            self.update_score(sid, score)
                        learned.append(sid)
                    else:
                        failed.append(sid)
                except asyncio.TimeoutError:
                    _log(f"  [red]{sid} timeout[/red]")
                    failed.append(sid)
                except Exception as e:
                    _log(f"  [red]{sid}: {e}[/red]")
                    failed.append(sid)
        self.save()
        _log(f"[bold]Cycle : {len(learned)} OK, {len(failed)} KO[/bold]")
        return {"learned": learned, "failed": failed}

    async def run_autonomous(self, discover_fn=None, check_fn=None, log_fn=None) -> None:
        """Run autonomous.

        Args:
            discover_fn: Description.
            check_fn: Description.
            log_fn: Description.
        """
        self._running = True
        await asyncio.sleep(60)
        while self._running:
            try:
                await self.run_cycle(discover_fn, check_fn, log_fn)
            except Exception as e:
                logger.debug(f"autonomous: {e}")
            await asyncio.sleep(self.CYCLE_INTERVAL)

    """Stop."""

    def stop(self) -> None:
        """Stop."""
        self._running = False

    # ── Intégration RAG ──────────────────────────────────────────────────────

    def sync_from_rag(self, db_path: str) -> int:
        """Bootstrap les skills depuis le RAG (lecture SQLite).

        Lit tous les chunks security/devops, détecte les skills via
        detect_skills(), appelle record_success() pour chaque skill
        trouvé — sans dupliquer si la tâche RAG est déjà dans tasks_ok.

        Args:
            db_path: Chemin vers embeddings.db.

        Returns:
            Nombre de progressions enregistrées.
        """
        import sqlite3 as _sq3

        progressions = 0
        try:
            conn = _sq3.connect(str(db_path), timeout=5)
            rows = conn.execute(
                "SELECT id, text, domain FROM rag_chunks WHERE domain IN ('security','devops') LIMIT 500"
            ).fetchall()
            conn.close()
        except Exception as e:
            logger.debug(f"sync_from_rag: {e}")
            return 0

        for row_id, text, domain in rows:
            task_id = f"rag:{row_id or hash(text[:40])}"
            skills = detect_skills(text or "")
            for sid in skills:
                s = self.get(sid)
                if task_id not in s.tasks_ok:
                    self.record_success(sid, task_id)
                    progressions += 1

        if progressions:
            self.save()
            logger.info(f"SkillLearner.sync_from_rag: {progressions} progressions depuis {len(rows)} chunks")
        return progressions

    def push_to_rag(self, db_path: str, sid: str, event: str, phase: int = 0, severity: str = "info") -> None:
        """Ancre une progression de skill dans le RAG.

        Args:
            db_path: Chemin vers embeddings.db.
            sid: Identifiant du skill (ex: 'pentest_exploit').
            event: Description de l'événement qui a fait progresser le skill.
            phase: Phase pipeline associée (0 si hors pipeline).
            severity: Niveau info/low/medium/high.
        """
        import sqlite3 as _sq3
        import json as _json
        from datetime import datetime as _dt

        s = self.get(sid)
        label = SKILL_TREE.get(sid, {}).get("label", sid)
        score_str = f"{s.score:.2f}"
        text = (
            f"[SkillProgression] {label} ({sid}) -> {s.status} "
            f"(score={score_str} succ={s.successes}) "
            f"Event: {event[:200]}"
        )
        meta = _json.dumps(
            {
                "type": "skill_progression",
                "skill_id": sid,
                "skill_label": label,
                "status": s.status,
                "score": s.score,
                "successes": s.successes,
                "phase": phase,
                "severity": severity,
                "ts": _dt.now().isoformat(),
            }
        )
        try:
            conn = _sq3.connect(str(db_path), timeout=5)
            # 2026-09-12 : sans `id` (TEXT PRIMARY KEY) la clef restait NULLE.
            from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

            _src = f"LaForge/skilltree/{sid}"
            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks (id, text, source, domain, meta) "
                "VALUES (?,?,?,?,?)",
                (_cid(_src, text), text, _src, "security", meta),
            )
            conn.commit()
            conn.close()
            logger.debug(f"push_to_rag: {sid} → {s.status}")
        except Exception as e:
            logger.debug(f"push_to_rag: {e}")

    def record_rag_event(self, db_path: str, text: str, task_id: str, phase: int = 0) -> list:
        """Détecte les skills dans un texte RAG et enregistre le succès.

        Méthode unifiée appelée après chaque rag_save_finding() dans
        le pipeline. Retourne la liste des skills progressés.

        Args:
            db_path: Chemin vers embeddings.db.
            text: Texte du finding (titre + détail).
            task_id: Identifiant unique de la tâche (ex: 'phase3:localhost').
            phase: Phase pipeline (1-5).

        Returns:
            Liste des skill IDs qui ont progressé.
        """
        skills = detect_skills(text)
        progressed = []
        for sid in skills:
            s = self.get(sid)
            old_status = s.status
            self.record_success(sid, task_id)
            if s.status != old_status:
                self.push_to_rag(db_path, sid, f"Phase {phase} — {task_id}: {text[:100]}", phase=phase)
                progressed.append(sid)
                logger.info(f"Skill promoted: {sid} → {s.status}")
        return progressed


# =============================================================================
# WIDGETS TEXTUAL
# =============================================================================
class SkillNode(Static):
    """Skillnode."""

    status = reactive("unknown")
    ICONS = {"unknown": "..", "searching": ">>", "learning": "~~", "verified": "ok", "mastered": "**"}
    COLORS = {
        "unknown": "dim",
        "searching": "blue",
        "learning": "yellow",
        "verified": "green",
        "mastered": "bold green",
    }

    def __init__(self, label, skill_id, depth=0, **kw) -> None:
        """Init.

        Args:
            label: Description.
            skill_id: Description.
            depth: Description.
        """
        super().__init__(**kw)
        self._label = label
        self._skill_id = skill_id
        self._depth = depth

    def render(self) -> object:
        """Render."""
        from rich.text import Text

        i = self.ICONS.get(self.status, "..")
        c = self.COLORS.get(self.status, "dim")
        return Text.from_markup(f"[{c}]{'  ' * self._depth}{i} {self._label}[/]")


class SkillTree(Vertical):
    """Skilltree."""

    def __init__(self, learner=None, **kw) -> None:
        """Init.

        Args:
            learner: Description.
        """
        super().__init__(**kw)
        self._learner = learner
        self._skill_map = {}

    """On mount."""

    def on_mount(self) -> None:
        """On mount."""
        self._build("general", 0)

    def _build(self, sid, depth) -> None:
        """Build.

        Args:
            sid: Description.
            depth: Description.
        """
        if sid not in SKILL_TREE:
            return
        sd = SKILL_TREE[sid]
        st = self._learner.get(sid).status if self._learner else "unknown"
        import re as _re

        _sid = _re.sub(r"[^a-zA-Z0-9_-]", "_", sid)
        n = SkillNode(sd["label"], sid, depth, id=f"skill-{_sid}")
        n.status = st
        self._skill_map[sid] = n
        self.mount(n)
        for c in sd.get("children", []):
            self._build(c, depth + 1)

    def add_or_update_skill(self, name, status) -> None:
        """Add or update skill.

        Args:
            name: Description.
            status: Description.
        """
        if name in self._skill_map:
            self._skill_map[name].status = status
        else:
            d = 1
            p = SKILL_TREE.get(name, {}).get("parent")
            if p and p in self._skill_map:
                d = self._skill_map[p]._depth + 1
            import re as _re

            _sname = _re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            n = SkillNode(name, name, d, id=f"skill-{_sname}")
            n.status = status
            self._skill_map[name] = n
            self.mount(n)

    def refresh_all(self) -> None:
        """Refresh all."""
        if not self._learner:
            return
        for sid, n in self._skill_map.items():
            n.status = self._learner.get(sid).status


__all__ = [
    "SKILL_TREE",
    "detect_skills",
    "get_dependencies",
    "get_subtree",
    "SkillState",
    "SkillLearner",
    "SkillNode",
    "SkillTree",
]
