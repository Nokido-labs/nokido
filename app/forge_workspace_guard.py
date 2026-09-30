"""
forge_workspace_guard.py — Nokido v18.5
==========================================
Contrôle d'accès au répertoire de travail pour les agents externes.
Principe: chaque agent a un workspace isolé. Les zones sensibles sont hors portée.

RINGS:
    Ring 0 (Claude/Cline) : accès total (superviseur)
    Ring 1 (agt_gemini)   : sandbox/ + RAG/chunks/ + app/ (lecture)
    Ring 2 (agt_groq)     : sandbox/ uniquement (écriture), lecture outputs/
    Ring 3 (agt_local)    : sandbox/agent_workspaces/agt_local/ uniquement
    Ring 9 (inconnu)      : BLOQUÉ

Zones ALWAYS_DENIED (tous rings sauf 0):
    .git/                  — historique compromettable
    config/jea/            — scripts admin PowerShell
    Nokido.env            — variables d'environnement
    app/forge_rbac.py      — RBAC lui-même
    app/forge_secrets.py   — gestionnaire secrets
    shadow_mutation/       — vault mutations
    tools/nokido_hub.py   — serveur Hub

Zones READ_ONLY (ring 1+):
    app/                   — lecture code source autorisée
    tools/                 — lecture scripts autorisée
    RAG/embeddings.db      — lecture SQLite WAL

Zone WRITE (ring 1):
    sandbox/               — espace de travail agents

Zone EXCLUSIVE (ring par agent):
    sandbox/agent_workspaces/{agent_id}/
"""

from __future__ import annotations
import json, os, re, stat
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

# ── Zones protégées ────────────────────────────────────────────────────────
ALWAYS_DENIED: list[str] = [
    ".git/",
    "config/jea/",
    "Nokido.env",
    "app/forge_rbac.py",
    "app/forge_secrets.py",
    "shadow_mutation/",
    "tools/nokido_hub.py",
    "tools/hub_minimal.py",
    "RAG/embeddings.db",
]

READ_ONLY: list[str] = [
    "app/",
    "tools/",
    "RAG/",
]

# Rings et leurs permissions
RING_PERMISSIONS: dict[int, dict] = {
    0: {"write": ["**"], "read": ["**"], "label": "Superviseur"},
    1: {"write": ["sandbox/", "outputs/"], "read": ["app/", "tools/", "RAG/", "sandbox/"], "label": "Agent senior"},
    2: {"write": ["sandbox/"], "read": ["sandbox/", "outputs/"], "label": "Agent standard"},
    3: {
        "write": ["sandbox/agent_workspaces/{agent_id}/"],
        "read": ["sandbox/agent_workspaces/{agent_id}/"],
        "label": "Agent isolé",
    },
    9: {"write": [], "read": [], "label": "BLOQUÉ"},
}

# Mapping agent_id → ring par défaut
AGENT_RINGS: dict[str, int] = {
    "agt_claude": 0,  # Superviseur
    "agt_cline": 0,  # Superviseur
    "wrk_laforge": 0,
    "agt_gemini": 1,  # Senior — accès app/ en lecture
    "agt_codex": 1,  # Codex CLI — pair de code (= gemini)
    "agt_antigravity": 1,  # Antigravity CLI (agy) — pair de code (= gemini)
    "CODEX": 1,  # alias identité uppercase (LaForge-Agent-Name)
    "ANTIGRAVITY": 1,  # alias identité uppercase (LaForge-Agent-Name)
    "agt_deepseek": 2,  # Standard
    "agt_mistral": 2,
    "agt_groq": 2,
    "agt_local": 3,  # Isolé dans son workspace
    "agt_hf": 3,
    "local": 3,  # Appels depuis nokido_hub sans agent identifié
}


# ── SSoT ring vivant : config/agent_identities.json ──────────────────────────
# AGENT_RINGS ci-dessus = FALLBACK legacy (clés agt_* du pool local hors registre).
# Source de vérité = le registre identité×ring (même fichier que forge_videur /
# forge_postal / forge_ring_admin). Lecture mtime-cachée ; json PRIORITAIRE.
_IDENTITIES = ROOT / "config" / "agent_identities.json"
_RINGS_CACHE: dict = {"mtime": 0.0, "rings": {}}


def _load_identity_rings() -> dict:
    try:
        m = _IDENTITIES.stat().st_mtime
        if m != _RINGS_CACHE["mtime"]:
            data = json.loads(_IDENTITIES.read_text(encoding="utf-8")).get("agents", {})
            _RINGS_CACHE["rings"] = {
                k.upper(): int(v["ring"]) for k, v in data.items() if isinstance(v, dict) and v.get("ring") is not None
            }
            _RINGS_CACHE["mtime"] = m
    except Exception:
        pass
    return _RINGS_CACHE["rings"]


def resolve_agent_ring(agent_id: str) -> int:
    """Ring d'un agent — SSoT json D'ABORD, fallback AGENT_RINGS legacy, sinon 9 (fail-closed)."""
    if not agent_id:
        return 9
    norm = agent_id.upper()
    if norm.startswith("AGT_"):
        norm = norm[4:]
    rings = _load_identity_rings()
    if norm in rings:
        return rings[norm]
    return AGENT_RINGS.get(agent_id, AGENT_RINGS.get(norm, 9))


class WorkspaceGuard:
    """Point d'entrée pour tous les checks d'accès fichier."""

    def __init__(self, agent_id: str, ring: Optional[int] = None):
        self.agent_id = agent_id
        self.ring = ring if ring is not None else resolve_agent_ring(agent_id)
        self._workspace = ROOT / "sandbox" / "agent_workspaces" / agent_id

    def _resolve(self, path_str: str) -> Path:
        """Résoudre un path relatif ou absolu vers un Path canonique."""
        p = Path(path_str)
        if not p.is_absolute():
            p = ROOT / p
        return p.resolve()

    def _rel(self, resolved: Path) -> str:
        """Retourner le chemin relatif depuis ROOT."""
        try:
            return str(resolved.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return str(resolved)

    def _is_always_denied(self, rel: str) -> bool:
        for denied in ALWAYS_DENIED:
            if rel.startswith(denied) or rel == denied.rstrip("/"):
                return True
        return False

    def check_read(self, path_str: str) -> tuple[bool, str]:
        """Vérifier si l'agent peut lire ce path."""
        if self.ring == 0:
            return True, "ring-0"

        resolved = self._resolve(path_str)
        rel = self._rel(resolved)

        if self._is_always_denied(rel):
            return False, f"ALWAYS_DENIED: {rel}"

        perms = RING_PERMISSIONS.get(self.ring, RING_PERMISSIONS[9])
        read_zones = [z.replace("{agent_id}", self.agent_id) for z in perms["read"]]

        if "**" in read_zones:
            return True, "ring-0-wildcard"
        for zone in read_zones:
            if rel.startswith(zone):
                return True, f"zone:{zone}"
        return False, f"RING_{self.ring}_NO_READ: {rel}"

    def check_write(self, path_str: str) -> tuple[bool, str]:
        """Vérifier si l'agent peut écrire dans ce path."""
        if self.ring == 0:
            return True, "ring-0"

        resolved = self._resolve(path_str)
        rel = self._rel(resolved)

        if self._is_always_denied(rel):
            return False, f"ALWAYS_DENIED: {rel}"

        # Read-only zones → pas d'écriture même ring 1
        for ro in READ_ONLY:
            if rel.startswith(ro):
                return False, f"READ_ONLY: {rel}"

        perms = RING_PERMISSIONS.get(self.ring, RING_PERMISSIONS[9])
        write_zones = [z.replace("{agent_id}", self.agent_id) for z in perms["write"]]

        if "**" in write_zones:
            return True, "ring-0-wildcard"
        for zone in write_zones:
            if rel.startswith(zone):
                return True, f"zone:{zone}"
        return False, f"RING_{self.ring}_NO_WRITE: {rel}"

    def get_workspace(self) -> Path:
        """Créer et retourner le workspace exclusif de l'agent."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        return self._workspace

    def safe_write(self, path_str: str, content: str | bytes, mode: str = "w") -> tuple[bool, str]:
        """Écriture sécurisée avec check ring."""
        ok, reason = self.check_write(path_str)
        if not ok:
            return False, reason
        try:
            resolved = self._resolve(path_str)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            enc = "utf-8" if "b" not in mode else None
            with open(resolved, mode, encoding=enc, errors="replace" if "b" not in mode else None) as f:
                f.write(content)
            return True, str(resolved)
        except Exception as e:
            return False, f"IO_ERROR: {e}"

    def safe_read(self, path_str: str) -> tuple[str | None, str]:
        """Lecture sécurisée avec check ring."""
        ok, reason = self.check_read(path_str)
        if not ok:
            return None, reason
        try:
            resolved = self._resolve(path_str)
            return resolved.read_text(errors="replace"), str(resolved)
        except Exception as e:
            return None, f"IO_ERROR: {e}"

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "ring": self.ring,
            "label": RING_PERMISSIONS.get(self.ring, {}).get("label", "?"),
            "workspace": str(self._workspace),
            "can_write_app": self.check_write("app/forge_rbac.py")[0],
            "can_read_app": self.check_read("app/forge_rbac.py")[0],
            "can_write_sandbox": self.check_write("sandbox/test.txt")[0],
            "can_read_hub": self.check_read("tools/nokido_hub.py")[0],
        }


# ── Audit-hook fs-zone pour le tool `run` ──────────────────────────────────
# WorkspaceGuard.check_write() ne protège que le tool `write` (path connu).
# Le tool `run` exécute du Python arbitraire : open()/os.remove() peuvent
# écrire partout sur le disque, hors de toute zone. La seule défense fiable
# est un audit hook (sys.addaudithook) installé DANS le sous-processus
# d'exécution AVANT le code de l'agent — non désinstallable par ce code
# (garantie CPython). Politique = forge_mcp_security.AGENT_WRITE_PATHS.

# PARITE AVEC `run action=shell` (owner 2026-09-27, « envisage ce confinement OS alors »).
# Mesure : sous SANDBOX_EXEC, `action=python` et `action=shell` tournent sous le MEME
# compte bac a sable (LaForgeSbxOffline, ou Online avec network). Le shell n'applique
# aucun filtre de contenu : son garde est le confinement OS du compte. Un sous-processus
# lance depuis python sous ce compte n'a donc AUCUN droit que `run shell` n'ait deja.
# Le hub (de confiance) decide la parite et la FIGE dans le code du hook : litteral, pas
# global -- le code de l'agent partage les globals du header et reassignait `_GZ` a
# volonte (une zone reecrite = un garde desarme). Hors compte bac a sable (pool du hub,
# gVisor), le refus reste binaire. Limite dite : un audit hook n'est pas un bac a sable
# (ctypes appelle CreateProcess sans evenement subprocess) -- la frontiere est le compte.
_RUN_GUARD_TEMPLATE = """\
# ── Nokido WorkspaceGuard — audit hook fs-zone (auto-injecté, non amovible) ─
import sys as _GS, os as _GO
def _gz_ok(_p):
    _GZ = __ZONES__
    try:
        _ap = _GO.path.normcase(_GO.path.abspath(_GO.fspath(_p)))
        if isinstance(_ap, bytes):
            _ap = _ap.decode("utf-8", "replace")
    except Exception:
        return True
    if _ap.endswith(".pyc") or "__pycache__" in _ap:
        return True
    return any(_ap == _z or _ap.startswith(_z + _GO.sep) for _z in _GZ)
def _gz_hook(_ev, _a):
    if _ev == "open":
        _p = _a[0] if _a else None
        _m = _a[1] if len(_a) > 1 else None
        _fl = _a[2] if len(_a) > 2 else None
        _w = False
        if isinstance(_m, str) and any(_c in _m for _c in "wax+"):
            _w = True
        if isinstance(_fl, int) and (_fl & (_GO.O_WRONLY | _GO.O_RDWR | _GO.O_CREAT | _GO.O_APPEND | _GO.O_TRUNC)):
            _w = True
        if _w and _p is not None and not _gz_ok(_p):
            raise PermissionError("WORKSPACE_GUARD: ecriture hors zone agent: %r" % (_p,))
    elif _ev in ("os.rename", "os.remove", "os.unlink", "os.mkdir", "os.rmdir",
                 "os.removedirs", "os.symlink", "os.link", "os.truncate"):
        for _x in _a:
            if isinstance(_x, (str, bytes, _GO.PathLike)) and not _gz_ok(_x):
                raise PermissionError("WORKSPACE_GUARD: %s hors zone agent: %r" % (_ev, _x))
    elif _ev in ("subprocess.Popen", "os.exec", "os.spawn", "os.posix_spawn",
                 "os.system", "os.startfile"):
        if __SOUS_PROCESSUS__:
            return  # parite shell : meme compte bac a sable, meme confinement OS
        raise PermissionError(
            "WORKSPACE_GUARD: %s interdit ICI. MOTIF : ce code ne tourne PAS sous le "
            "compte bac a sable (pool du hub, ou gVisor) ; un sous-processus y "
            "echapperait a ce garde, qui est un audit hook in-process. Sous le compte "
            "bac a sable (SANDBOX_EXEC), il est permis : meme compte et meme "
            "confinement OS que `run action=shell`. CE N'EST PAS UNE CAPACITE "
            "ABSENTE : run action=shell, action=run_job, ou action=trusted_script." % _ev)
    elif _ev in ("winreg.CreateKey", "winreg.DeleteKey", "winreg.SetValue"):
        raise PermissionError("WORKSPACE_GUARD: %s interdit pour agent zone-restreint." % _ev)
_GS.addaudithook(_gz_hook)
# ── fin WorkspaceGuard ──────────────────────────────────────────────────────
"""


def build_run_guard_header(allowed_abspaths: list[str], sous_processus: bool = False) -> str:
    """Construit un header Python qui installe un audit hook bloquant toute
    écriture/suppression hors des préfixes `allowed_abspaths`, et tout spawn
    sauf si `sous_processus` (parite shell, decidee par le hub).

    À préfixer au code d'un agent non-superviseur avant exécution. Lecture
    autorisée partout — seules les mutations sont confinées. `.pyc` et
    `__pycache__` sont exemptés (sinon les imports échoueraient). Zones et
    parite sont FIGEES en litteraux dans le code du hook.
    """
    import os as _o

    zones = []
    for p in allowed_abspaths:
        try:
            zones.append(_o.path.normcase(_o.path.abspath(p)))
        except Exception:
            continue
    return (_RUN_GUARD_TEMPLATE.replace("__ZONES__", repr(tuple(zones)))
            .replace("__SOUS_PROCESSUS__", repr(bool(sous_processus))))


def run_guard_header_for(agent: str, ring: int, root, sous_processus: bool = False) -> str:
    """Header audit-hook confinant TOUT agent à une zone filesystem.

    - Superviseur (ring <= 0 ou zone wildcard '*') : confiné à l'arbre projet
      (ROOT). Liberté totale DANS le projet, rien au-dehors — pas même CLAUDE.
      Ring 0 ne veut PAS dire "disque entier" : c'est de la concentration de
      privilège, pas du moindre privilège.
    - Agent zoné : confiné à ses sous-dossiers AGENT_WRITE_PATHS.

    Ne retourne jamais '' : aucun agent n'écrit hors du projet via `run`.
    Fail-safe — si la politique est indisponible, confinement ROOT.
    `sous_processus` : parite shell, decidee par l'appelant (hub) -- jamais par l'agent.
    """
    root = Path(root)
    try:
        is_supervisor = ring is not None and int(ring) <= 0
    except Exception:
        is_supervisor = False
    try:
        from nokido_agent.app.forge_mcp_security import get_agent_write_paths
    except Exception:
        return build_run_guard_header([str(root)], sous_processus)  # fail-safe : confine ROOT
    prefixes = get_agent_write_paths(agent)
    if "*" in prefixes:
        is_supervisor = True
    if is_supervisor:
        allowed = [str(root)]
    else:
        allowed = [str((root / p).resolve()) for p in prefixes]
    return build_run_guard_header(allowed, sous_processus)


# ── Helper global ──────────────────────────────────────────────────────────
_guards: dict[str, WorkspaceGuard] = {}


def get_guard(agent_id: str, ring: Optional[int] = None) -> WorkspaceGuard:
    key = f"{agent_id}:{ring}"
    if key not in _guards:
        _guards[key] = WorkspaceGuard(agent_id, ring)
    return _guards[key]


if __name__ == "__main__":
    import json as _json

    print("=== WorkspaceGuard Test ===\n")
    for agent in ["agt_claude", "agt_gemini", "agt_groq", "agt_local", "agt_unknown"]:
        g = get_guard(agent)
        s = g.summary()
        print(
            f"  {agent:15s} ring={s['ring']} [{s['label']:15s}]"
            f" write_app={'Y' if s['can_write_app'] else 'N'}"
            f" read_app={'Y' if s['can_read_app'] else 'N'}"
            f" write_sandbox={'Y' if s['can_write_sandbox'] else 'N'}"
            f" read_hub={'Y' if s['can_read_hub'] else 'N'}"
        )
