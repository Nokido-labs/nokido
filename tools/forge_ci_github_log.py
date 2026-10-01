"""forge_ci_github_log.py — diagnostique un run GitHub Actions EN ÉCHEC via `gh api`.

`gh` n'est utilisable que sous LaForgeTrusted (auth + egress GitHub ; run_job online est
bloqué vers api.github.com). On passe par `gh api` (pas `gh run view --log-failed`) pour
éviter le cache `~/.cache` non inscriptible sous ce compte, et on redirige XDG_CACHE_HOME.
    run action=trusted_script path=tools/forge_ci_github_log.py script_args="<run_id>"
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/trace : diagnostique un run GitHub Actions en echec"

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Nokido-labs/nokido-private"   # atelier source (renomme le 2026-09-30)
_PAT = re.compile(
    r"(Traceback|Error|FAILED|assert|ModuleNotFound|ImportError|No such file|non class|"
    r"^E |exit code|Process completed with exit code|\.py::|=+ .*(passed|failed))",
    re.I,
)


def _gh(env, *args):
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True,
                          env=env, errors="replace")


def main() -> int:
    sys.path.insert(0, str(ROOT / "app"))
    try:
        from forge_secrets import get_secret
        tok = get_secret("GITHUB_TOKEN") or ""
    except Exception:
        tok = ""
    cache = ROOT / "sandbox" / "ghcache"
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GH_TOKEN=tok, GITHUB_TOKEN=tok, XDG_CACHE_HOME=str(cache))
    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not run_id:
        print("usage: forge_ci_github_log.py <run_id>")
        return 2

    r = _gh(env, "repos/%s/actions/runs/%s/jobs" % (REPO, run_id))
    if r.returncode != 0:
        print("gh api jobs rc=%d ERR=%s" % (r.returncode, (r.stderr or "")[:600]))
        return 1
    data = json.loads(r.stdout or "{}")
    fails = [j for j in data.get("jobs", []) if j.get("conclusion") == "failure"]
    print("jobs=%d  en_echec=%d" % (len(data.get("jobs", [])), len(fails)))
    for j in fails:
        steps = [s.get("name") for s in j.get("steps", []) if s.get("conclusion") == "failure"]
        print("JOB FAIL: %s (id=%s) steps=%s" % (j.get("name"), j.get("id"), steps))
        lr = _gh(env, "repos/%s/actions/jobs/%s/logs" % (REPO, j.get("id")))
        log = lr.stdout or ""
        (ROOT / "sandbox" / "gh_failed_log.txt").write_text(log, encoding="utf-8", errors="replace")
        lignes = [ln for ln in log.splitlines() if _PAT.search(ln)]
        print("  log_len=%d filtered=%d (40 dernieres) :" % (len(log), len(lignes)))
        for ln in lignes[-40:]:
            print("   ", ln.strip()[:260])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
