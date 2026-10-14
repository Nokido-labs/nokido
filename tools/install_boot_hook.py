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
    # NOKIDO_DENO d'abord : sous sudo, PATH et HOME sont ceux de root, et le deno de l'utilisateur n'y est pas.
    impose = os.environ.get("NOKIDO_DENO", "").strip()
    if impose:
        return impose
    usuel = Path.home() / ".deno" / "bin" / ("deno.exe" if os.name == "nt" else "deno")
    return shutil.which("deno") or (str(usuel) if usuel.is_file() else "deno")


# --- Linux / macOS (decision owner du 2026-10-09, « Go, superviseur root ») ----------------------
# Meme role que la tache SYSTEM : le superviseur tourne en root pour lancer les services runAs sous leurs comptes
# dedies. L'artefact est INSTALLE hors du depot (deploy/ est versionne) : unite systemd SYSTEME, LaunchDaemon.
UNITE_SYSTEMD = Path("/etc/systemd/system/laforge-master.service")
DAEMON_LAUNCHD = Path("/Library/LaunchDaemons/com.nokido.master.plist")


# Ni systemd ni launchd ne posent HOME pour un service systeme : les services SANS runAs (lances par le superviseur
# root lui-meme) n'en avaient aucun -- Ollama s'arretait sur « Error: $HOME is not defined » (mesure 5, run
# 38162661913, Linux et macOS). HOME = celui de root, jamais celui de l'installateur (des fichiers root chez lui).
# Les services runAs recoivent celui de LEUR compte (forge_runas_launcher.main_posix).
HOME_ROOT_LINUX = "/root"
HOME_ROOT_MACOS = "/var/root"


def unite_systemd(env: dict) -> str:
    lignes = ["[Unit]", "Description=Nokido Master Supervisor (root)", "After=network.target", "", "[Service]",
              "Type=simple", "WorkingDirectory=%s" % ROOT]
    lignes += ["Environment=%s=%s" % (k, v) for k, v in {**env, "HOME": HOME_ROOT_LINUX}.items()]
    lignes += ["ExecStart=%s run -A %s" % (_deno(), SUPERVISOR), "StandardOutput=append:%s" % JOURNAL_TACHE,
               "StandardError=append:%s" % JOURNAL_TACHE, "Restart=always", "RestartSec=5", "",
               "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lignes)


def daemon_launchd(env: dict) -> str:
    from xml.sax.saxutils import escape as e
    envs = "".join("<key>%s</key><string>%s</string>" % (e(k), e(str(v)))
                   for k, v in {**env, "HOME": HOME_ROOT_MACOS}.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            "<key>Label</key><string>com.nokido.master</string>"
            "<key>ProgramArguments</key><array><string>%s</string><string>run</string><string>-A</string>"
            "<string>%s</string></array><key>WorkingDirectory</key><string>%s</string>"
            "<key>EnvironmentVariables</key><dict>%s</dict>"
            "<key>StandardOutPath</key><string>%s</string><key>StandardErrorPath</key><string>%s</string>"
            "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>\n"
            % (e(_deno()), SUPERVISOR, e(str(ROOT)), envs, e(str(JOURNAL_TACHE)), e(str(JOURNAL_TACHE))))


def _root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def installer_posix(env: dict) -> tuple[int, str]:
    if not _root():
        return 1, "REFUS : --installer exige root (superviseur root, owner 2026-10-09)"
    JOURNAL_TACHE.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        DAEMON_LAUNCHD.write_text(daemon_launchd(env), encoding="utf-8")
        os.chmod(DAEMON_LAUNCHD, 0o644)
        subprocess.run(["launchctl", "bootout", "system/com.nokido.master"], capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", "system", str(DAEMON_LAUNCHD)], capture_output=True, text=True,
                           errors="replace")
        return r.returncode, "LaunchDaemon %s ; journal %s ; %s" % (DAEMON_LAUNCHD, JOURNAL_TACHE, r.stderr.strip())
    UNITE_SYSTEMD.write_text(unite_systemd(env), encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    r = subprocess.run(["systemctl", "enable", "--now", "laforge-master"], capture_output=True, text=True,
                       errors="replace")
    return r.returncode, "unite systemd %s ; journal %s ; %s" % (UNITE_SYSTEMD, JOURNAL_TACHE, r.stderr.strip())


def arreter_posix() -> tuple[int, str]:
    if sys.platform == "darwin":
        r = subprocess.run(["launchctl", "bootout", "system/com.nokido.master"], capture_output=True, text=True,
                           errors="replace")
    else:
        r = subprocess.run(["systemctl", "stop", "laforge-master"], capture_output=True, text=True, errors="replace")
    subprocess.run(["pkill", "-f", "supervisor.ts"], capture_output=True)
    return r.returncode, "superviseur arrete (%s)" % (r.stderr.strip() or "ok")


def amorcer_posix() -> tuple[int, str]:
    """Coffre d'une machine neuve hors Windows (owner 2026-10-09, « Fichier root 0600 ») : memes outils, sous root."""
    if not _root():
        return 1, "REFUS : --amorcer exige root (seul root scelle le coffre reserve hors Windows)"
    sorties, rcs = [], {}
    for cle, args in (("RC_COFFRE", ["tools/forge_coffre_reserve_provision.py", "--machine-neuve", "--appliquer"]),
                      ("RC_JETONS", ["tools/forge_vault_seed_agent_tokens.py", "--generate-missing", "--from-registre"])):
        r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, errors="replace",
                           timeout=900)
        sorties.append(((r.stdout or "") + (r.stderr or "")).strip())
        rcs[cle] = r.returncode
    texte = "\n".join(sorties) + "".join("\n%s=%d" % kv for kv in rcs.items())
    return (0 if all(v == 0 for v in rcs.values()) else 1), texte


def _dossier_tache() -> Path:
    """Hors du depot : SYSTEM execute l'enveloppe, un dossier modifiable par l'utilisateur ou par LaForgeTrusted (qui a
    Modify sur le depot) ferait d'elle une marche vers SYSTEM. ProgramData, ACL SYSTEM + Administrateurs seuls."""
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Nokido"


def _ps(script: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _preparer_dossier_tache() -> Path:
    dossier = _dossier_tache()
    dossier.mkdir(parents=True, exist_ok=True)
    subprocess.run(["icacls", str(dossier), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F",
                    "*S-1-5-32-544:(OI)(CI)F"], capture_output=True, text=True, errors="replace", timeout=60)
    return dossier


TACHE_AMORCE = "Nokido-Amorcage"


def amorcer_windows(attente_s: int = 900) -> tuple[int, str]:
    """Amorce une machine NEUVE sous SYSTEM (decision owner du 2026-10-09) : coffre reserve (secrets generes, jamais
    affiches), cle persona TPM et codes d'appariement (forge_coffre_reserve_provision --machine-neuve), puis jetons
    d'agents FORGE_TOKEN_<AGENT> (forge_vault_seed_agent_tokens). Tache SYSTEM a usage UNIQUE -- seul SYSTEM scelle le
    coffre reserve --, attendue puis desinscrite. Le journal ne porte que des NOMS et des etats."""
    dossier = _preparer_dossier_tache()
    journal = dossier / "amorcage.log"
    py = sys.executable
    lignes = ["@echo off", 'cd /d "%s"' % ROOT,
              '"%s" tools\\forge_coffre_reserve_provision.py --machine-neuve --appliquer > "%s" 2>&1' % (py, journal),
              'echo RC_COFFRE=%%ERRORLEVEL%% >> "%s"' % journal,
              '"%s" tools\\forge_vault_seed_agent_tokens.py --generate-missing --from-registre >> "%s" 2>&1'
              % (py, journal),
              'echo RC_JETONS=%%ERRORLEVEL%% >> "%s"' % journal]
    enveloppe = dossier / "amorcage.cmd"
    enveloppe.write_text("\r\n".join(lignes) + "\r\n", encoding="oem" if os.name == "nt" else "ascii")
    q = lambda s: str(s).replace("'", "''")  # noqa: E731 -- chaine PowerShell entre apostrophes
    script = (
        "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"%s\"' -WorkingDirectory '%s'; "
        "$p = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest; "
        "Register-ScheduledTask -TaskName '%s' -Action $a -Principal $p -Force | Out-Null; "
        "Start-ScheduledTask -TaskName '%s'; $fin = (Get-Date).AddSeconds(%d); "
        "while ((Get-Date) -lt $fin -and -not (Select-String -Path '%s' -Pattern 'RC_JETONS=' -Quiet "
        "-ErrorAction SilentlyContinue)) { Start-Sleep -Seconds 2 }; "
        "Unregister-ScheduledTask -TaskName '%s' -Confirm:$false"
        % (q(enveloppe), q(ROOT), TACHE_AMORCE, TACHE_AMORCE, attente_s, q(journal), TACHE_AMORCE))
    _rc, sortie_ps = _ps(script, timeout=attente_s + 120)
    texte = journal.read_text(encoding="utf-8", errors="replace") if journal.exists() else ""
    rcs = dict(l.strip().split("=", 1) for l in texte.splitlines() if l.strip().startswith(("RC_COFFRE=", "RC_JETONS=")))
    ok = rcs.get("RC_COFFRE") == "0" and rcs.get("RC_JETONS") == "0"
    return (0 if ok else 1), (texte.strip() or "journal ABSENT : " + sortie_ps.strip()[-600:])


def gen_windows_tache(env: dict | None = None) -> Path:
    """Enveloppe de la tache SYSTEM : se place dans le depot, fixe l'environnement demande, journalise la sortie."""
    dossier = _preparer_dossier_tache()
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
    if "--installer" in sys.argv or "--arreter" in sys.argv or "--amorcer" in sys.argv:
        env = dict(a.split("=", 1) for a in sys.argv[sys.argv.index("--env") + 1:sys.argv.index("--env") + 2]
                   if "=" in a) if "--env" in sys.argv else {}
        if osname != "win32":
            if "--amorcer" in sys.argv:
                rc, msg = amorcer_posix()
            elif "--arreter" in sys.argv:
                rc, msg = arreter_posix()
            else:
                env.setdefault("NOKIDO_UTILISATEUR", os.environ.get("SUDO_USER", ""))
                rc, msg = installer_posix({k: v for k, v in env.items() if v})
            print(msg)
            return rc
        if "--amorcer" in sys.argv:
            rc, msg = amorcer_windows()
        elif "--arreter" in sys.argv:
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
