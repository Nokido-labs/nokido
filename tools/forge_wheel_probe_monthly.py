"""tools/forge_wheel_probe_monthly.py - Trigger Acte 5 quand ecosystem cp314t pret.

Tourne via schtasks LaForge-WheelProbe (mensuel).

Pipeline :
1. Probe wheels sur 3 envs : miniforge3 base (3.12), laforge_py314 (3.14 GIL), laforge_py314t (3.14t no-GIL)
2. Compare vs dernier snapshot dans sandbox/wheel_matrix_history/
3. Si py314t OK_count >= TRIGGER_THRESHOLD (28/32) :
   - notify CLAUDE via hub (action recommandee : Acte 5 flip)
   - log critical_event
4. Toujours archive nouveau snapshot

Usage manual :
    LAFORGE_PYTHON tools/forge_wheel_probe_monthly.py
    LAFORGE_PYTHON tools/forge_wheel_probe_monthly.py --notify  # force notify meme sans trigger

Install schtasks :
    schtasks /Create /SC MONTHLY /D 1 /TN LaForge-WheelProbe ^
        /TR __import__("os").path.expanduser("~/miniforge3/python.exe %NOKIDO_WORKSPACE%/LaForge/tools/forge_wheel_probe_monthly.py") ^
        /ST 03:00 /RU SYSTEM /RL HIGHEST
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "sandbox" / "wheel_matrix_history"
PROBE_SCRIPT = ROOT / "tools" / "forge_wheel_probe.py"

# Envs a probe (chemin python.exe).
#
# POURQUOI PAS `expanduser` SEUL (mesure 2026-08-30). `~` se resout sur le profil du
# compte QUI LANCE. Lance en `run_job`, ce script tourne sous le compte sandbox, dont
# HOME vaut `C:\Users\Default` : les trois interpreteurs deviennent introuvables et le
# probe ecrit un snapshot 100 % en erreur (581 octets contre 14 417) qui ECRASE le
# precedent. C'est arrive ce jour-la. Les chemins ABSOLUS sont deja declares dans
# `proxy_deno/core/services.toml` : on les lit la, et `expanduser` ne sert plus que de
# repli -- un repli qui le DIT, au lieu de rendre silencieusement de mauvais chemins.
_VAR_RE = __import__("re").compile(
    r'^\s*(PYTHON|PY314|PY314T)\s*=\s*"([^"]+)"', __import__("re").M)


def _envs_depuis_services_toml() -> tuple[dict, str]:
    """(chemins, provenance). Rend ({}, motif) si le fichier ne dit rien d'exploitable."""
    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    try:
        texte = toml.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {}, "services.toml illisible (%s)" % type(exc).__name__
    vus = dict(_VAR_RE.findall(texte))
    couples = {"py312_base": vus.get("PYTHON"),
               "py314_gil": vus.get("PY314"),
               "py314t_nogil": vus.get("PY314T")}
    manquants = [k for k, v in couples.items() if not v]
    if manquants:
        return {}, "variables absentes de services.toml : %s" % ",".join(manquants)
    return {k: str(Path(v)) for k, v in couples.items()}, "services.toml [vars]"


def _envs_par_expanduser() -> dict:
    return {
        "py312_base": os.path.expanduser(r"~/miniforge3/python.exe"),
        "py314_gil": os.path.expanduser(r"~/miniforge3/envs/laforge_py314/python.exe"),
        "py314t_nogil": os.path.expanduser(r"~/miniforge3/envs/laforge_py314t/python.exe"),
    }


TARGET_ENVS, ENVS_PROVENANCE = _envs_depuis_services_toml()
if not TARGET_ENVS:
    TARGET_ENVS = _envs_par_expanduser()
    ENVS_PROVENANCE = "repli expanduser (~ du compte courant) — %s" % ENVS_PROVENANCE

# Trigger Acte 5 = flip canonical LAFORGE_PYTHON vers py314t
TRIGGER_THRESHOLD = 28  # sur 32 wheels critiques (87.5%)
TRIGGER_ENV = "py314t_nogil"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("wheel_probe_monthly")


def snapshot_est_reel(snapshot: dict) -> bool:
    """Au moins un env a-t-il ete SONDE (pas seulement tente) ?

    Un snapshot dont tous les envs portent `error` ne mesure rien : il dit « je n'ai
    pas pu regarder », ce qui se lit a tort comme « plus rien ne marche ».
    """
    envs = (snapshot or {}).get("envs") or {}
    return any(not (e or {}).get("error") for e in envs.values())


def doit_ecrire_latest(neuf: dict, ancien: dict | None) -> tuple[bool, str]:
    """Le nouveau snapshot a-t-il le droit de remplacer `latest.json` ?

    Mesure 2026-08-30 : lance sous le compte sandbox (HOME=C:\\Users\\Default), le
    probe n'a trouve aucun interpreteur et a ecrase 14 417 octets de mesures reelles
    par 581 octets d'erreurs. On n'ecrase un snapshot REEL que par un autre snapshot
    REEL ; le fichier date, lui, est toujours ecrit, pour garder la trace de l'echec.
    """
    if snapshot_est_reel(neuf):
        return True, "snapshot reel"
    if ancien is None:
        return True, "aucun latest.json anterieur a proteger"
    if snapshot_est_reel(ancien):
        return False, "snapshot tout-en-erreur : latest.json reel CONSERVE"
    return True, "l'ancien latest.json etait lui aussi tout-en-erreur"


def run_probe(python_exe: str) -> dict:
    """Lance forge_wheel_probe.py --json sur un python.exe target."""
    if not Path(python_exe).exists():
        return {"error": f"executable not found: {python_exe}"}
    try:
        r = subprocess.run(
            [python_exe, str(PROBE_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        errors="replace")
        if r.returncode > 1:
            return {"error": f"probe rc={r.returncode}, stderr={r.stderr[:300]}"}
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def hub_notify(message: str) -> bool:
    """Notify via hub MCP :8766 (passthrough bash_guard via curl)."""
    try:
        import urllib.request

        token = os.environ.get("FORGE_MCP_TOKEN", "")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hub",
                    "arguments": {"action": "notify", "to": "CLAUDE", "message": message},
                },
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Agent-Name": "WHEEL_PROBE",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        log.warning(f"hub notify failed: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true", help="Force notify CLAUDE even without trigger")
    ap.add_argument("--print", action="store_true", help="Print snapshot to stdout")
    args = ap.parse_args()

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    snapshot: dict = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "envs": {},
    }

    for name, exe in TARGET_ENVS.items():
        log.info(f"probing {name} ({exe})")
        snapshot["envs"][name] = run_probe(exe)

    # Trigger check
    trigger = snapshot["envs"].get(TRIGGER_ENV, {})
    ok_count = trigger.get("ok", 0)
    total = trigger.get("total", 32)
    pct = (100 * ok_count / max(1, total))
    snapshot["trigger"] = {
        "env": TRIGGER_ENV,
        "ok": ok_count,
        "total": total,
        "pct": round(pct, 1),
        "threshold": TRIGGER_THRESHOLD,
        "triggered": ok_count >= TRIGGER_THRESHOLD,
    }

    # Archive snapshot
    out_path = HISTORY_DIR / f"wheel_matrix_{snapshot['ts'][:10]}.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    log.info(f"snapshot saved: {out_path}")

    # Latest pointer
    # GARDE D'ECRASEMENT (mesure 2026-08-30) : un snapshot dont AUCUN env n'a pu etre
    # sonde ne doit pas remplacer un snapshot REEL. Sans ce garde, un lancement sous
    # le mauvais compte detruit la seule mesure valide -- et le resultat se lit ensuite
    # comme « plus rien ne marche en free-threaded » au lieu de « je n'ai pas pu voir ».
    _latest = HISTORY_DIR / "latest.json"
    _ancien = None
    if _latest.exists():
        try:
            _ancien = json.loads(_latest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _ancien = None
    _ok, _motif = doit_ecrire_latest(snapshot, _ancien)
    if not _ok:
        log.warning("latest.json NON ecrase — %s. Provenance des chemins : %s. "
                    "Le snapshot date reste ecrit pour la trace.", _motif, ENVS_PROVENANCE)
        return snapshot
    _latest.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if args.print:
        print(json.dumps(snapshot, indent=2))

    # Notify si triggered ou forced
    if snapshot["trigger"]["triggered"] or args.notify:
        msg = (
            f"[WHEEL PROBE] {TRIGGER_ENV} = {ok_count}/{total} OK ({pct:.1f}%). "
            f"Threshold {TRIGGER_THRESHOLD} -> Acte 5 flip LAFORGE_PYTHON candidat. "
            f"Snapshot: sandbox/wheel_matrix_history/latest.json"
        )
        log.info(msg)
        if hub_notify(msg):
            log.info("notified CLAUDE via hub")
        else:
            log.warning("hub notify failed -- check :8766")

    # Chain to py314t_readiness probe (Acte 5 partial trigger). Runs even if wheel
    # threshold not met -- per-workload candidates can become ready before full env.
    readiness_script = ROOT / "tools" / "forge_py314t_readiness.py"
    if readiness_script.exists():
        try:
            log.info("chaining to py314t_readiness probe")
            subprocess.run(
                [__import__("os").path.expanduser(r"~/miniforge3/python.exe"), str(readiness_script)],
                cwd=str(ROOT),
                timeout=120,
            )
        except Exception as e:
            log.warning(f"readiness probe chain failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
