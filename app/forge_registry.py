"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_registry
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_registry.py — Registre de persistance cross-sessions pour Nokido
========================================================================
Centralise la persistance de :
  - workflows (@workflow add/del/run)
  - historique CI (@ci run/status)
  - chains (@chain)
  - cibles SSH (@switch)
  - plages scan (@scan)
  - règles IDS (@ids)

Format : data/forge_registry.json (JSON simple, human-readable)
Accès   : get(section, key) / set(section, key, value) / append(section, key, item)
"""


import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Chemin calculé depuis __file__ ───────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _APP_DIR.parent
_DATA_DIR = _ROOT_DIR / "data"
_REGISTRY_FILE = _DATA_DIR / "forge_registry.json"

_HISTORY_MAX = 200  # max entrées dans les listes d'historique


# =============================================================================
# STRUCTURE PAR DÉFAUT
# =============================================================================

_DEFAULT: Dict[str, Any] = {
    "_meta": {
        "version": "1.0",
        "description": "Registre de persistance Nokido",
        "last_updated": "",
    },
    # @workflow : {nom: {steps: [...], created: iso, runs: int, last_run: iso}}
    "workflows": {},
    # @ci : repos connus + historique global
    "ci": {
        "repos": {},  # {url: {alias, branch_default, workdir, last_run, runs, last_status}}
        "history": [],  # [{repo, branch, status, duration_s, ts, errors}]
    },
    # @chain : {nom: {steps: [...], created: iso}}
    "chains": {},
    # @switch : cibles SSH nommées {nom: {host, port, user, key}}
    "ssh_targets": {},
    # @scan : plages réseau connues {label: {target, last_scan, ports_found}}
    "scan_targets": {},
    # @ids : règles persistantes {id: {pattern, action, created}}
    "ids_rules": {},
    # @audit : résultats résumés {host: {ts, score, issues_count, top_issues}}
    "audit_results": {},
    # @role : rôles personnalisés {nom: {prompt, created}}
    "custom_roles": {},
}


# =============================================================================
# REGISTRE SINGLETON
# =============================================================================


class ForgeRegistry:
    """
    Singleton de persistance cross-sessions.
    Chargé une fois au boot, sauvegardé à chaque modification.
    Thread-safe via un lock simple (Textual est single-threaded async).
    """

    _instance: Optional["ForgeRegistry"] = None

    def __new__(cls) -> "ForgeRegistry":
        """New.

        Args:
            cls: Description.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data: Dict[str, Any] = {}
            cls._instance._loaded = False
        return cls._instance

    # ── Chargement ───────────────────────────────────────────────────────────

    def load(self) -> "ForgeRegistry":
        """Charge le registre depuis le disque. Idempotent."""
        if self._loaded:
            return self
        try:
            if _REGISTRY_FILE.exists():
                raw = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
                # Fusionner avec les valeurs par défaut (nouvelles clés)
                self._data = _deep_merge(_DEFAULT, raw)
            else:
                self._data = json.loads(json.dumps(_DEFAULT))  # deep copy
                self._save_now()
            self._loaded = True
            logger.debug(f"[Registry] chargé ({_REGISTRY_FILE})")
        except Exception as e:
            logger.warning(f"[Registry] chargement échoué: {e} — défauts utilisés")
            self._data = json.loads(json.dumps(_DEFAULT))
            self._loaded = True
        return self

    # ── Lecture ──────────────────────────────────────────────────────────────

    def get(self, section: str, key: str = "", default: Any = None) -> Any:
        """
        registry.get("workflows")           → dict tous les workflows
        registry.get("workflows", "deploy") → entrée du workflow "deploy"
        registry.get("ci", "repos")         → dict des repos connus
        """
        self.load()
        sec = self._data.get(section, {})
        if not key:
            return sec
        return sec.get(key, default)

    def all(self, section: str) -> Dict[str, Any]:
        """Retourne toute une section."""
        return self.get(section) or {}

    # ── Écriture ─────────────────────────────────────────────────────────────

    def set(self, section: str, key: str, value: Any) -> None:
        """registry.set("workflows", "deploy", {steps: [...], runs: 0})"""
        self.load()
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value
        self._save()

    def update(self, section: str, key: str, patch: Dict) -> None:
        """Mise à jour partielle d'une entrée."""
        self.load()
        existing = self.get(section, key) or {}
        existing.update(patch)
        self.set(section, key, existing)

    def delete(self, section: str, key: str) -> bool:
        """Supprime une entrée. Retourne True si existait."""
        self.load()
        sec = self._data.get(section, {})
        if key in sec:
            del sec[key]
            self._save()
            return True
        return False

    def append_history(self, section: str, item: Dict, max_items: int = _HISTORY_MAX) -> None:
        """Ajoute une entrée dans une liste d'historique avec purge auto."""
        self.load()
        if section not in self._data:
            self._data[section] = []
        lst = self._data[section]
        if not isinstance(lst, list):
            # section = dict avec sous-clé "history"
            if "history" not in lst:
                lst["history"] = []
            lst = lst["history"]
        lst.append(item)
        # Purge
        if len(lst) > max_items:
            del lst[:-max_items]
        self._save()

    def append_ci_history(self, item: Dict) -> None:
        """Spécialisé pour l'historique CI."""
        self.load()
        hist = self._data.setdefault("ci", {}).setdefault("history", [])
        hist.append(item)
        if len(hist) > _HISTORY_MAX:
            del hist[:-_HISTORY_MAX]
        self._save()

    # ── Helpers métier ───────────────────────────────────────────────────────

    def save_workflow(self, name: str, steps: List[str]) -> None:
        """Save workflow.

        Args:
            name: Description.
            steps: Description.
        """
        now = _now_iso()
        existing = self.get("workflows", name) or {}
        self.set(
            "workflows",
            name,
            {
                "steps": steps,
                "created": existing.get("created", now),
                "modified": now,
                "runs": existing.get("runs", 0),
                "last_run": existing.get("last_run", ""),
                "last_status": existing.get("last_status", ""),
            },
        )
        logger.debug(f"[Registry] workflow '{name}' sauvegardé ({len(steps)} étapes)")

    def record_workflow_run(self, name: str, status: str) -> None:
        """Record workflow run.

        Args:
            name: Description.
            status: Description.
        """
        now = _now_iso()
        self.update(
            "workflows",
            name,
            {
                "last_run": now,
                "last_status": status,
                "runs": (self.get("workflows", name) or {}).get("runs", 0) + 1,
            },
        )

    def save_ci_repo(self, url: str, alias: str = "", branch: str = "main", workdir: str = "/tmp/ci-repo") -> None:
        """Save ci repo.

        Args:
            url: Description.
            alias: Description.
            branch: Description.
            workdir: Description.
        """
        now = _now_iso()
        existing = self.get("ci", "repos") or {}
        repo_key = alias or url.split("/")[-1].replace(".git", "")
        repos = existing if isinstance(existing, dict) else {}
        repos[repo_key] = {
            "url": url,
            "alias": repo_key,
            "branch_default": branch,
            "workdir": workdir,
            "added": repos.get(repo_key, {}).get("added", now),
            "runs": repos.get(repo_key, {}).get("runs", 0),
            "last_run": repos.get(repo_key, {}).get("last_run", ""),
            "last_status": repos.get(repo_key, {}).get("last_status", ""),
        }
        self._data.setdefault("ci", {})["repos"] = repos
        self._save()

    def record_ci_run(self, repo_key: str, branch: str, status: str, duration_s: float, errors: str = "") -> None:
        """Record ci run.

        Args:
            repo_key: Description.
            branch: Description.
            status: Description.
            duration_s: Description.
            errors: Description.
        """
        now = _now_iso()
        # Mettre à jour le repo
        repos = self._data.get("ci", {}).get("repos", {})
        if repo_key in repos:
            repos[repo_key].update(
                {
                    "last_run": now,
                    "last_status": status,
                    "runs": repos[repo_key].get("runs", 0) + 1,
                }
            )
        # Ajouter à l'historique
        self.append_ci_history(
            {
                "repo": repo_key,
                "branch": branch,
                "status": status,
                "duration_s": round(duration_s, 1),
                "ts": now,
                "errors": errors[:200] if errors else "",
            }
        )

    def save_chain(self, name: str, steps: List[str]) -> None:
        """Save chain.

        Args:
            name: Description.
            steps: Description.
        """
        now = _now_iso()
        existing = self.get("chains", name) or {}
        self.set(
            "chains",
            name,
            {
                "steps": steps,
                "created": existing.get("created", now),
                "modified": now,
            },
        )

    def save_ssh_target(self, name: str, host: str, port: int = 22, user: str = "", key: str = "") -> None:
        """Save ssh target.

        Args:
            name: Description.
            host: Description.
            port: Description.
            user: Description.
            key: Description.
        """
        self.set(
            "ssh_targets",
            name,
            {
                "host": host,
                "port": port,
                "user": user,
                "key": key,
                "added": _now_iso(),
            },
        )

    def save_scan_target(self, label: str, target: str, ports_found: List[str] = None) -> None:
        """Save scan target.

        Args:
            label: Description.
            target: Description.
            ports_found: Description.
        """
        existing = self.get("scan_targets", label) or {}
        self.set(
            "scan_targets",
            label,
            {
                "target": target,
                "added": existing.get("added", _now_iso()),
                "last_scan": _now_iso(),
                "ports_found": ports_found or existing.get("ports_found", []),
            },
        )

    def save_audit_result(self, host: str, score: int, issues_count: int, top_issues: List[str]) -> None:
        """Save audit result.

        Args:
            host: Description.
            score: Description.
            issues_count: Description.
            top_issues: Description.
        """
        self.set(
            "audit_results",
            host,
            {
                "ts": _now_iso(),
                "score": score,
                "issues_count": issues_count,
                "top_issues": top_issues[:5],
            },
        )

    # ── Stats / résumé ───────────────────────────────────────────────────────

    def summary(self) -> str:
        """Résumé lisible pour @workflow list / @ci status."""
        self.load()
        wf = len(self._data.get("workflows", {}))
        ci = len(self._data.get("ci", {}).get("repos", {}))
        ch = len(self._data.get("chains", {}))
        ssh = len(self._data.get("ssh_targets", {}))
        sc = len(self._data.get("scan_targets", {}))
        return f"{wf} workflows · {ci} repos CI · {ch} chains · {ssh} cibles SSH · {sc} cibles scan"

    # ── Sauvegarde ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Sauvegarde différée — marque comme dirty."""
        self._data.setdefault("_meta", {})["last_updated"] = _now_iso()
        self._save_now()

    def _save_now(self) -> None:
        """Save now."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _REGISTRY_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(_REGISTRY_FILE)
        except Exception as e:
            logger.error(f"[Registry] sauvegarde: {e}")


# =============================================================================
# HELPERS
# =============================================================================


def _now_iso() -> str:
    """Now iso."""
    return datetime.datetime.utcnow().isoformat()


def _deep_merge(base: dict, override: dict) -> dict:
    """Fusionne override dans base (base fournit les défauts)."""
    result = json.loads(json.dumps(base))
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# Singleton global
_registry: Optional[ForgeRegistry] = None


def get_registry() -> ForgeRegistry:
    """Retourne le singleton ForgeRegistry, chargé si nécessaire."""
    global _registry
    if _registry is None:
        _registry = ForgeRegistry()
    return _registry.load()
