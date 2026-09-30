#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_archi_lint.py — lint architectural Nokido via Semgrep (Golden Rules).

Lance `.semgrep/nokido_golden_rules.yml` (invariants archi) sur les cibles
données (défaut app/ + tools/) et résume les findings. Conçu pour CI + Commit
Guard : exit≠0 si severity ERROR. Là où le hook AST Python ne voit que la
syntaxe, Semgrep attrape la sémantique (db_path bypass, INSERT sans id, …).

Roadmap observabilité chantier #4. Usage :
    forge_archi_lint.py [path ...] [--all]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, ".semgrep", "nokido_golden_rules.yml")
CANDIDATES = [
    __import__("os").path.expanduser(r"~\miniforge3\Scripts\semgrep.exe"),
    __import__("os").path.expanduser(r"~\miniforge3\Scripts\pysemgrep.exe"),
]


def _semgrep() -> str | None:
    """Premier binaire semgrep qui DEMARRE reellement, pas le premier trouve.

    `semgrep` route vers le coeur natif (osemgrep), qui construit un client
    OpenTelemetry des le lancement et meurt sous un compte de service :
    « Failed to create system store X509 authenticator: CertOpenSystemStore
    returned NULL » -- y compris sur `--version`. Le chemin Python legacy
    (`pysemgrep`) demarre, lui. Etre PRESENT sur le disque ne prouve donc rien :
    on sonde, sinon le gate repart en silence pour la meme raison qu'avant.
    """
    env = _env()
    for cand in _binaires():
        try:
            r = subprocess.run([cand, "--version"], capture_output=True, text=True,
                               timeout=120, errors="replace", env=env)
        except Exception:  # noqa: BLE001 - binaire absent ou instantanement mort
            continue
        if r.returncode == 0 and (r.stdout or "").strip():
            return cand
        print(f"[archi_lint] {os.path.basename(cand)} ne demarre pas "
              f"(rc={r.returncode}) : {((r.stderr or r.stdout) or '').strip()[:120]}")
    return None


def _binaires() -> list[str]:
    """Candidats, du plus capable au plus robuste."""
    out = []
    for nom in ("semgrep", "pysemgrep"):
        w = shutil.which(nom)
        if w:
            out.append(w)
    out += [c for c in CANDIDATES if os.path.exists(c) and c not in out]
    return out


def _env() -> dict:
    """Environnement du sous-processus, avec un HOME REELLEMENT inscriptible.

    Sous un compte de service (LaForgeTrusted, runner CI), le profil est
    `C:\\Users\\Default` : semgrep y cree son dossier d'etat au demarrage et
    meurt sur `PermissionError [WinError 5] C:\\Users\\Default\\.semgrep`, avant
    meme d'avoir lu une ligne de code. Le chemin natif echouait de son cote sur
    le magasin de certificats du meme profil absent. On ancre donc l'etat dans
    le depot -- pas sous C:/tmp, qui se purge (incident du 2026-08-12).
    """
    env = dict(os.environ)
    home = os.path.join(ROOT, "sandbox", ".semgrep_home")
    try:
        os.makedirs(home, exist_ok=True)
    except OSError:
        return env  # pas de repli silencieux : semgrep dira lui-meme pourquoi
    env["HOME"] = home
    env["USERPROFILE"] = home
    env["XDG_CONFIG_HOME"] = home
    env["XDG_CACHE_HOME"] = home
    env["SEMGREP_SETTINGS_FILE"] = os.path.join(home, "settings.yml")
    return env


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--all", "--debug")]
    if "--all" in sys.argv:
        targets = [ROOT]
    else:
        raw = args or ["app", "tools"]
        # Résoudre vs ROOT : semgrep tourne avec cwd != ROOT -> chemins relatifs
        # ne scannent rien (0 fichier silencieux).
        targets = [t if os.path.isabs(t) else os.path.join(ROOT, t) for t in raw]

    sg = _semgrep()
    if not sg:
        print("ABORT: semgrep introuvable (pip install semgrep)")
        return 2

    cmd = [sg, "--config", CONFIG, "--json", "--quiet",
           "--metrics=off", "--disable-version-check", "--timeout", "20",
           "--no-git-ignore", *targets]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           errors="replace", env=_env())
    except Exception as exc:  # noqa: BLE001
        print(f"ABORT: semgrep run failed: {exc}")
        return 3

    # Un plantage de semgrep laissait stdout VIDE -> json.loads("{}") -> "0 fichier,
    # 0 finding", rc=0, coche verte en CI. Mesure du 2026-08-15 : c'est exactement ce
    # que le gate affichait, run 31873587600. Un outil muet doit crier, pas rassurer.
    if not (r.stdout or "").strip():
        print(f"ABORT: semgrep n'a rien produit (rc={r.returncode}). stderr:\n"
              + (r.stderr or "")[-1500:])
        return 3
    if "--debug" in sys.argv:
        print(f"[dbg] cmd={cmd}")
        print(f"[dbg] rc={r.returncode} outlen={len(r.stdout or '')}")
        print("[dbg] stderr:\n" + (r.stderr or "")[-1200:])
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        print("ABORT: semgrep JSON parse failed. stderr:\n" + (r.stderr or "")[-1500:])
        return 3

    errs_cfg = data.get("errors", [])
    scanned = data.get("paths", {}).get("scanned", [])
    if errs_cfg:
        print(f"[archi_lint] semgrep errors ({len(errs_cfg)}) :")
        for e in errs_cfg[:6]:
            print("   - " + str(e.get("long_msg") or e.get("message") or e)[:300])
    print(f"[archi_lint] scanned_files={len(scanned)}")
    # Zero fichier lu n'est jamais un succes : les cibles existent, donc soit le
    # binaire est casse, soit la config exclut tout. Dans les deux cas le verdict
    # "0 finding" est un mensonge.
    if not scanned:
        print("ABORT: 0 fichier scanne — un gate qui ne lit rien ne vaut pas un vert")
        return 3
    results = data.get("results", [])
    by_sev: dict[str, int] = {}
    for f in results:
        sev = f.get("extra", {}).get("severity", "?")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    print(f"[archi_lint] {len(results)} finding(s) : {by_sev or '{}'}")
    for f in results[:50]:
        rel = os.path.relpath(f["path"], ROOT)
        rid = f["check_id"].split(".")[-1]
        print(f"  [{f.get('extra', {}).get('severity', '?')}] {rid}  {rel}:{f['start']['line']}")
    errors = by_sev.get("ERROR", 0)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
