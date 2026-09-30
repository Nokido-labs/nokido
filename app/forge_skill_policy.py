"""
forge_skill_policy.py — Politique centralisée install skills externes Claude Code.

Centralise les règles de sécurité ET d économie tokens pour les
marketplaces externes installés dans `~/.claude/plugins/marketplaces/`.

Dépend de :
- forge_opsec : OPSEC level + human_lock (Centaure)
- forge_clawhub_bridge::SkillGuardian : review tier existant
- forge_integrity : IntegrityRing pour capabilities
- forge_self_correction::anchor_solution : audit trail RAG

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:skill_policy|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = Path(os.environ.get("CLAUDE_PLUGINS_DIR", str(Path.home() / ".claude" / "plugins")))
DB = ROOT / "RAG" / "embeddings.db"


# ── Whitelist signed marketplaces (review-passed) ─────────────────────────────
TRUSTED_MARKETPLACES: dict[str, dict] = {
    "anthropic-agent-skills": {
        "repo": "anthropics/skills",
        "tier": "MASTER",
        "reason": "Anthropic officiel, signed",
    },
    "caveman": {
        "repo": "JuliusBrussee/caveman",
        "tier": "TRUSTED",
        "reason": "Community simple (mode terse), pas de code exec",
    },
}


# ── Blacklist patterns (auto-reject pre-install) ──────────────────────────────
BLACKLIST_NAME_PATTERNS = [
    r"-yeet$",  # auto-yeet behavior suspect
    r"wooyun",  # archives exploits offensifs
    r"-legacy$",  # legacy souvent payloads obsolètes vulnérables
    r"vulnerable",
    r"-rce$",
    r"-bypass$",
    r"backdoor",
]

BLACKLIST_FILE_PATTERNS = [
    r"references?/.*sql[\-_]?injection",
    r"references?/.*command[\-_]?exec",
    r"references?/.*file[\-_]?upload",
    r"references?/.*xss",
    r"references?/.*rce",
    r"exploits?/.*",
    r"payloads?/.*",
    r"shellcode",
]

# ── Risk scanners for auto-exec vectors ───────────────────────────────────────
HIGH_RISK_FILES = [
    "hooks.json",  # auto-exec pre/post-tool
    ".claude-plugin/hooks.json",
    "postinstall.sh",
    "postinstall.py",
    "install.sh",
    "install.py",
]


# ── Moindre-privilège par ring (P1 sync + P2 hub) — SOURCE UNIQUE partagée ────────────────────
# Ring BAS = PLUS de droits (IntegrityRing). Un appelant de ring R accède à un skill de min_ring M
# si R <= M (is_at_least). Règle d'or Nokido : GRILLE DÉTERMINISTE binaire, appliquée APRÈS le
# routage sémantique (RRF/BGE-M3), jamais dans le scoring -> +sécurité = 0 perte de fidélité.
DEFAULT_MIN_RING = 3  # COLLAB : par défaut tous (aucune restriction)
SKILL_MIN_RING: dict[str, int] = {
    "forge-core": 2,          # écrit/patch code, gère le hub — blast radius élevé
    "forge-rescue": 2,       # restart services / restore config
    "netcfg-agent": 2,         # deploy SSH infra (irréversible)
    "forge-android": 2,        # shell ADB / install APK sur device
    "forge-skills": 2,       # install/run skills = exécution de code
    "forge-skill-seekers": 2,  # génère + installe des skills depuis le web
}


def skill_min_ring(slug: str, fm: dict | None = None) -> int:
    """Ring minimal requis : `min_ring:` frontmatter (override) > SKILL_MIN_RING > DEFAULT_MIN_RING."""
    mr = (fm or {}).get("min_ring")
    if mr is None:
        mr = SKILL_MIN_RING.get(slug, DEFAULT_MIN_RING)
    try:
        return int(mr)
    except (TypeError, ValueError):
        return DEFAULT_MIN_RING


def skill_allowed_for_ring(slug: str, caller_ring: int, fm: dict | None = None) -> bool:
    """Grille binaire : appelant de ring R accède au skill si R <= min_ring (is_at_least).
    Ring inconnu -> fail-open (la grille coarse _TOOL_MIN_RING['skill']=3 gate déjà UNTRUSTED)."""
    try:
        return int(caller_ring) <= skill_min_ring(slug, fm)
    except (TypeError, ValueError):
        return True


@dataclass
class PolicyVerdict:
    """Verdict d audit pre-install."""

    plugin_name: str
    marketplace: str
    decision: str  # "ALLOW" | "REVIEW" | "BLOCK"
    risk_score: float  # 0.0-1.0
    issues: list[str] = field(default_factory=list)
    auto_exec_files: list[str] = field(default_factory=list)
    blacklist_files: list[str] = field(default_factory=list)
    requires_human: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT
# ══════════════════════════════════════════════════════════════════════════════


def audit_plugin(plugin_dir: Path, marketplace: str = "unknown") -> PolicyVerdict:
    """Audit pre-install d un plugin (dossier `plugins/<name>/` cloné).

    Retourne PolicyVerdict : ALLOW (signed/safe) | REVIEW (suspect) | BLOCK.
    """
    name = plugin_dir.name
    verdict = PolicyVerdict(plugin_name=name, marketplace=marketplace, decision="REVIEW", risk_score=0.0)

    # 1. Marketplace whitelist
    if marketplace in TRUSTED_MARKETPLACES:
        verdict.decision = "ALLOW"
        verdict.risk_score = 0.0
        return verdict

    # 2. Blacklist name patterns
    for pat in BLACKLIST_NAME_PATTERNS:
        if re.search(pat, name, re.IGNORECASE):
            verdict.decision = "BLOCK"
            verdict.risk_score = 1.0
            verdict.issues.append(f"name matches blacklist pattern: {pat}")
            verdict.requires_human = True
            return verdict

    # 3. Scan auto-exec files
    if not plugin_dir.exists():
        verdict.decision = "BLOCK"
        verdict.issues.append(f"plugin_dir missing: {plugin_dir}")
        return verdict

    for risky in HIGH_RISK_FILES:
        for found in plugin_dir.rglob(risky):
            verdict.auto_exec_files.append(str(found.relative_to(plugin_dir)))
            verdict.risk_score += 0.3

    # 4. Scan files matching blacklist patterns
    for f in plugin_dir.rglob("*.md"):
        rel = str(f.relative_to(plugin_dir)).replace("\\", "/")
        for pat in BLACKLIST_FILE_PATTERNS:
            if re.search(pat, rel, re.IGNORECASE):
                verdict.blacklist_files.append(rel)
                verdict.risk_score += 0.4
                break

    # 5. Scan suspicious shell scripts
    for ext in (".sh", ".ps1", ".bat", ".py", ".js"):
        for f in plugin_dir.rglob(f"*{ext}"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:5000]
                if re.search(r"curl\s+.*\|\s*(?:sh|bash|python|pwsh)", content):
                    verdict.issues.append(f"curl-pipe-shell in {f.name}")
                    verdict.risk_score += 0.5
                if re.search(r"\beval\s*\(", content) and ext in (".js", ".py"):
                    verdict.issues.append(f"eval() in {f.name}")
                    verdict.risk_score += 0.3
            except Exception:
                pass

    # Decision
    verdict.risk_score = min(1.0, verdict.risk_score)
    if verdict.risk_score >= 0.7 or verdict.blacklist_files:
        verdict.decision = "BLOCK"
        verdict.requires_human = True
    elif verdict.risk_score >= 0.3 or verdict.auto_exec_files:
        verdict.decision = "REVIEW"
        verdict.requires_human = True
    else:
        verdict.decision = "ALLOW"

    return verdict


def audit_marketplace(marketplace_dir: Path) -> list[PolicyVerdict]:
    """Audit complet de tous les plugins d un marketplace cloné."""
    name = marketplace_dir.name
    plugins_subdir = marketplace_dir / "plugins"
    if not plugins_subdir.exists():
        return []

    verdicts = []
    for p in plugins_subdir.iterdir():
        if p.is_dir():
            verdicts.append(audit_plugin(p, marketplace=name))
    return verdicts


# ══════════════════════════════════════════════════════════════════════════════
# OPSEC INTEGRATION (Centaure)
# ══════════════════════════════════════════════════════════════════════════════


def can_install(marketplace: str, plugin: str = "") -> dict[str, Any]:
    """Vérifie si install autorisé selon OPSEC + lock + whitelist.

    Returns dict {allowed: bool, reason: str, requires_human: bool}.
    """
    # 1. OPSEC level check
    try:
        from nokido_agent.app.forge_opsec import get_opsec_level, is_human_locked, OpsecLevel

        level = get_opsec_level()
        locked = is_human_locked()
    except Exception:
        level = None
        locked = False

    # 2. Marketplace trusted ?
    if marketplace in TRUSTED_MARKETPLACES:
        return {
            "allowed": True,
            "reason": f"trusted marketplace ({TRUSTED_MARKETPLACES[marketplace]['tier']})",
            "requires_human": False,
        }

    # 3. PARANOID + lock = bloque tout externe
    if level is not None and level.name == "PARANOID" and locked:
        return {
            "allowed": False,
            "reason": "OPSEC PARANOID + human lock active. External skills BLOCKED.",
            "requires_human": True,
        }

    # 4. Default : require human review
    return {
        "allowed": False,
        "reason": f"untrusted marketplace '{marketplace}'. Audit required AVANT install.",
        "requires_human": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT TRAIL (RAG)
# ══════════════════════════════════════════════════════════════════════════════

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_policy_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    action TEXT NOT NULL,
    marketplace TEXT,
    plugin TEXT,
    decision TEXT,
    risk_score REAL,
    actor TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_skill_policy_ts ON skill_policy_audit(ts);
"""


def _ensure_audit_schema() -> None:
    try:
        conn = sqlite3.connect(str(DB))
        for stmt in _AUDIT_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_audit(
    action: str,
    marketplace: str,
    plugin: str = "",
    decision: str = "",
    risk_score: float = 0.0,
    actor: str = "system",
    details: dict | None = None,
) -> None:
    """Persist audit event dans skill_policy_audit + lessons_learned."""
    _ensure_audit_schema()
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute(
            "INSERT INTO skill_policy_audit (ts, action, marketplace, plugin, decision, risk_score, actor, details) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                time.time(),
                action,
                marketplace,
                plugin,
                decision,
                risk_score,
                actor,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════


def status() -> dict[str, Any]:
    """Statut global politique."""
    plugins_dir = PLUGINS_DIR / "marketplaces"
    installed = []
    if plugins_dir.exists():
        for d in plugins_dir.iterdir():
            if d.is_dir() and (d / ".claude-plugin").exists():
                installed.append(d.name)

    return {
        "plugins_dir": str(PLUGINS_DIR),
        "trusted_marketplaces": list(TRUSTED_MARKETPLACES.keys()),
        "installed_marketplaces": installed,
        "untrusted_installed": [m for m in installed if m not in TRUSTED_MARKETPLACES],
        "blacklist_name_patterns": BLACKLIST_NAME_PATTERNS,
        "blacklist_file_patterns": BLACKLIST_FILE_PATTERNS,
    }


if __name__ == "__main__":
    import argparse, sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--audit-marketplace", help="path to marketplace dir")
    ap.add_argument("--audit-plugin", help="path to single plugin dir")
    ap.add_argument("--can-install", help="marketplace name to check")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif args.audit_marketplace:
        verdicts = audit_marketplace(Path(args.audit_marketplace))
        for v in verdicts:
            print(f"[{v.decision:6}] {v.plugin_name:30} risk={v.risk_score:.2f}")
            for issue in v.issues + v.auto_exec_files + v.blacklist_files:
                print(f"           - {issue}")
    elif args.audit_plugin:
        v = audit_plugin(Path(args.audit_plugin))
        print(
            json.dumps(
                {
                    "plugin": v.plugin_name,
                    "decision": v.decision,
                    "risk_score": v.risk_score,
                    "issues": v.issues,
                    "auto_exec_files": v.auto_exec_files,
                    "blacklist_files": v.blacklist_files,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    elif args.can_install:
        print(json.dumps(can_install(args.can_install), indent=2, ensure_ascii=False))
    else:
        ap.print_help()
