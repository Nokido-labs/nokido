"""install_boot_hook.py — generate the OS-specific hook that launches the
Nokido supervisor at boot.

Step 5 of the portable-supervisor migration (docs/portable_supervisor_plan.md).
The supervisor (proxy_deno/core/supervisor.ts) is OS-agnostic; only this
one boot artefact is per-OS:

  Windows -> NSSM service / Scheduled Task
  Linux   -> systemd unit
  macOS   -> launchd plist

    LAFORGE_PYTHON tools/install_boot_hook.py            # generate for this OS
    LAFORGE_PYTHON tools/install_boot_hook.py --all      # generate all 3
    LAFORGE_PYTHON tools/install_boot_hook.py --installer [--env NOM=VALEUR]   # Windows, admin
    LAFORGE_PYTHON tools/install_boot_hook.py --arreter                         # Windows, admin

Generated artefacts land in deploy/ ; without --installer this script does NOT install them.
--installer (Windows, decision owner du 2026-10-09) registers the supervisor as a SYSTEM scheduled task
started at boot, and starts it : the runAs services need CreateProcessAsUser, i.e. SeAssignPrimaryTokenPrivilege,
which only SYSTEM holds -- like the NSSM service LaForge-Master of the reference machine, with no third-party binary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
SUPERVISOR = "proxy_deno/core/supervisor.ts"
TACHE = "LaForge-Master"
JOURNAL_TACHE = ROOT / "logs" / "supervisor" / "laforge-master.tache.log"


def _deno() -> str:
    # Chemin ABSOLU : SYSTEM n'a pas ~/.deno/bin dans son PATH (l'installeur officiel n'y ajoute que l'utilisateur).
    usuel = Path.home() / ".deno" / "bin" / ("deno.exe" if os.name == "nt" else "deno")
    return shutil.which("deno") or (str(usuel) if usuel.is_file() else "deno")


def _dossier_tache() -> Path:
    """Hors du depot : SYSTEM execute l'enveloppe, un dossier modifiable par l'utilisateur ou par LaForgeTrusted (qui a
    Modify sur le depot) ferait d'elle une marche vers SYSTEM. ProgramData, ACL SYSTEM + Administrateurs seuls."""
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Nokido"


def _ps(script: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def gen_windows_tache(env: dict | None = None) -> Path:
    """Enveloppe de la tache SYSTEM : se place dans le depot, fixe l'environnement demande, journalise la sortie."""
    dossier = _dossier_tache()
    dossier.mkdir(parents=True, exist_ok=True)
    subprocess.run(["icacls", str(dossier), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F",
                    "*S-1-5-32-544:(OI)(CI)F"], capture_output=True, text=True, errors="replace", timeout=60)
    JOURNAL_TACHE.parent.mkdir(parents=True, exist_ok=True)
    lignes = ["@echo off", 'cd /d "%s"' % ROOT]
    lignes += ['set "%s=%s"' % (k, v) for k, v in (env or {}).items()]
    lignes.append('"%s" run -A %s >> "%s" 2>&1' % (_deno(), SUPERVISOR, JOURNAL_TACHE))
    out = dossier / "laforge-master.cmd"
    # cmd.exe lit son script dans la page OEM : un caractere qu'elle ne represente pas leve ici, jamais en silence.
    out.write_text("\r\n".join(lignes) + "\r\n", encoding="oem" if os.name == "nt" else "ascii")
    return out


def installer_tache_windows(env: dict | None = None, demarrer: bool = True) -> tuple[int, str]:
    """Enregistre LaForge-Master en tache planifiee SYSTEM (au demarrage, sans limite de duree, relancee si elle
    tombe) puis la demarre. Refuse si le service NSSM du poste de reference existe : deux superviseurs se
    disputeraient :8765 et les ports de tous les services."""
    if subprocess.run(["sc", "query", TACHE], capture_output=True, text=True, errors="replace").returncode == 0:
        return 1, "REFUS : un service %s existe deja (poste de reference) ; la tache le doublerait" % TACHE
    enveloppe = gen_windows_tache(env)
    q = lambda s: str(s).replace("'", "''")  # noqa: E731 -- chaine PowerShell entre apostrophes
    script = (
        "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"%s\"' -WorkingDirectory '%s'; "
        "$t = New-ScheduledTaskTrigger -AtStartup; "
        "$p = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest; "
        "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 "
        "-RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-MultipleInstances IgnoreNew; "
        "Register-ScheduledTask -TaskName '%s' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null"
        % (q(enveloppe), q(ROOT), TACHE))
    if demarrer:
        script += "; Start-ScheduledTask -TaskName '%s'" % TACHE
    rc, sortie = _ps(script)
    return rc, "tache %s (SYSTEM) -> %s ; journal %s ; %s" % (TACHE, enveloppe, JOURNAL_TACHE, sortie.strip()[-600:])


def arreter_tache_windows() -> tuple[int, str]:
    """Arrete la tache, puis l'arbre du superviseur qu'elle a lance (les services en sont les descendants)."""
    rc, sortie = _ps(
        "Stop-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue; "
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*supervisor.ts*' } | "
        "ForEach-Object { taskkill /F /T /PID $_.ProcessId | Out-Null; $_.ProcessId }" % TACHE)
    return rc, "arbre(s) arrete(s) : %s" % (sortie.strip().replace("\n", " ") or "aucun")


def gen_systemd() -> Path:
    unit = f"""[Unit]
Description=Nokido Master Supervisor
After=network.target

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={_deno()} run -A {SUPERVISOR}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    DEPLOY.mkdir(exist_ok=True)
    out = DEPLOY / "laforge-master.service"
    out.write_text(unit, encoding="utf-8")
    return out


def gen_launchd() -> Path:
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.nokido.master</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_deno()}</string>
    <string>run</string><string>-A</string>
    <string>{SUPERVISOR}</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""
    DEPLOY.mkdir(exist_ok=True)
    out = DEPLOY / "com.nokido.master.plist"
    out.write_text(plist, encoding="utf-8")
    return out


def gen_windows() -> str:
    nssm_cmd = (
        f'nssm install LaForge-Master "{_deno()}" '
        f"run -A {SUPERVISOR}\n"
        f'nssm set LaForge-Master AppDirectory "{ROOT}"\n'
        f"nssm start LaForge-Master"
    )
    DEPLOY.mkdir(exist_ok=True)
    out = DEPLOY / "install_nokido_master.cmd"
    out.write_text("@echo off\n" + nssm_cmd + "\n", encoding="utf-8")
    return (
        f"Windows boot hook = NSSM service 'LaForge-Master'.\n"
        f"  Already installed on this machine (verify: sc qc LaForge-Master).\n"
        f"  Re-install script written: {out}"
    )


def main() -> int:
    do_all = "--all" in sys.argv
    osname = sys.platform
    if "--installer" in sys.argv or "--arreter" in sys.argv:
        if osname != "win32":
            print("--installer / --arreter : Windows seulement (Linux/macOS : unite systemd / plist generees)")
            return 2
        if "--arreter" in sys.argv:
            rc, msg = arreter_tache_windows()
        else:
            env = dict(a.split("=", 1) for a in sys.argv[sys.argv.index("--env") + 1:sys.argv.index("--env") + 2]
                       if "=" in a) if "--env" in sys.argv else {}
            rc, msg = installer_tache_windows(env)
        print(msg)
        return rc

    if do_all or osname == "win32":
        print(gen_windows())
    if do_all or osname.startswith("linux"):
        p = gen_systemd()
        print(f"systemd unit -> {p}")
        print(
            "  install: sudo cp deploy/laforge-master.service "
            "/etc/systemd/system/ && sudo systemctl enable --now "
            "laforge-master"
        )
    if do_all or osname == "darwin":
        p = gen_launchd()
        print(f"launchd plist -> {p}")
        print(
            "  install: cp deploy/com.nokido.master.plist "
            "~/Library/LaunchAgents/ && launchctl load "
            "~/Library/LaunchAgents/com.nokido.master.plist"
        )

    if not do_all and osname not in ("win32", "darwin") and not osname.startswith("linux"):
        print(f"unsupported OS: {osname}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
