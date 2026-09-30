from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_codeberg_sync
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_codeberg_sync.py — Mirror Codeberg Ring 7
=====================================================
Synchronise le dépôt GitHub → Codeberg après chaque commit.
Codeberg = hébergement souverain EU (Gitea), zéro tracking.

Variables .env :
  CODEBERG_TOKEN=ee2d905b...
  CODEBERG_USER=user
  CODEBERG_REPO=Nokido
  CODEBERG_URL=https://codeberg.org
  CODEBERG_SYNC_AUTO=false   → sync manuelle (true = après chaque commit)
  LAFORGE_ENV=dev            → sync simulée

Modes :
  sync_now()    → push vers Codeberg (DETACHED — non bloquant)
  setup_remote() → configure git remote codeberg
  status()       → état du remote + dernier sync
"""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _is_dev() -> bool:
    """Is dev."""
    return (
        os.environ.get("LAFORGE_ENV", "prod").lower() == "dev"
        or os.environ.get("LAFORGE_MCP_DEV", "false").lower() == "true"
    )


def _token() -> str:
    """Token."""
    return get_secret("CODEBERG_TOKEN") or ""


def _user() -> str:
    """User."""
    return os.environ.get("CODEBERG_USER", "user")


def _repo() -> str:
    """Repo."""
    return os.environ.get("CODEBERG_REPO", "Nokido")


def _base_url() -> str:
    """Base url."""
    return os.environ.get("CODEBERG_URL", "https://codeberg.org")


def _remote_url() -> str:
    """URL authentifiée pour git push."""
    t = _token()
    if t:
        return f"https://{_user()}:{t}@codeberg.org/{_user()}/{_repo()}.git"
    return f"https://codeberg.org/{_user()}/{_repo()}.git"


def _remote_url_display() -> str:
    """URL sans token pour les logs."""
    return f"https://codeberg.org/{_user()}/{_repo()}.git"


DETACHED = 0x00000008


def setup_remote(branch: str = "alpha") -> dict:
    """
    Configure le remote 'codeberg' dans le dépôt git local.
    Remplace si déjà présent.
    """
    url = _remote_url()
    try:
        # Supprimer si existe
        subprocess.run(["git", "remote", "remove", "codeberg"], capture_output=True, cwd=str(ROOT), timeout=5)
        # Ajouter
        r = subprocess.run(
            ["git", "remote", "add", "codeberg", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=5,
        )
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.strip()[:80]}
        return {
            "ok": True,
            "remote": "codeberg",
            "url": _remote_url_display(),
            "branch": branch,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


def sync_now(branch: str = "alpha", force: bool = False) -> dict:
    """
    Pousse la branche vers Codeberg en DETACHED.
    En dev : simulation sauf force=True.
    """
    if _is_dev() and not force:
        return {
            "ok": True,
            "action": "dev_skip",
            "message": f"Dev mode — git push codeberg {branch} simulé",
            "url": _remote_url_display(),
        }

    if not _token():
        return {"ok": False, "error": "CODEBERG_TOKEN absent dans .env"}

    try:
        # S'assurer que le remote existe
        r_check = subprocess.run(
            ["git", "remote", "get-url", "codeberg"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=5,
        )
        if r_check.returncode != 0:
            setup_remote(branch)

        # Push DETACHED
        subprocess.Popen(
            ["git", "push", "codeberg", branch, "--force-with-lease"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(ROOT),
            creationflags=DETACHED,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        # Timestamp dans mmap
        try:
            from nokido_agent.app.live_bridge import bridge

            bridge.json_set("codeberg.last_sync", time.time())
            bridge.json_set("codeberg.branch", branch)
        except Exception:
            pass

        return {
            "ok": True,
            "action": "push_launched",
            "branch": branch,
            "url": _remote_url_display(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def sync_if_auto(branch: str = "alpha") -> dict:
    """
    Sync automatique — appelée après chaque commit si CODEBERG_SYNC_AUTO=true.
    """
    auto = os.environ.get("CODEBERG_SYNC_AUTO", "false").lower() == "true"
    if not auto:
        return {"ok": True, "action": "auto_disabled"}
    return sync_now(branch)


def status() -> dict:
    """État du remote Codeberg et dernier sync."""
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "codeberg"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=5,
        )
        remote_ok = r.returncode == 0

        # Dernier commit pushé sur codeberg
        last_remote = ""
        if remote_ok:
            r2 = subprocess.run(
                ["git", "ls-remote", "codeberg", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(ROOT),
                timeout=8,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            last_remote = r2.stdout.split()[0][:12] if r2.stdout.strip() else "?"

        return {
            "configured": remote_ok,
            "url": _remote_url_display(),
            "user": _user(),
            "repo": _repo(),
            "token_present": bool(_token()),
            "auto_sync": os.environ.get("CODEBERG_SYNC_AUTO", "false"),
            "last_remote": last_remote,
            "dev_mode": _is_dev(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}
