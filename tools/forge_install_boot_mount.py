#!/usr/bin/env python3
"""
forge_install_boot_mount.py — Installeur boot du montage at-rest, CROSS-OS.

Monte le conteneur chiffré (forge_at_rest_veracrypt --mount) au démarrage, AVANT
que les services Nokido ouvrent embeddings.db. Clé au machine_vault (jamais sur
disque). Backends :
  - Windows : tâche schtasks /sc onstart /ru SYSTEM (wrapper C:\\tmp\\*.cmd, évite
              l'enfer de quoting) + services NSSM en démarrage différé (anti-race).
  - Linux   : unité systemd oneshot `laforge-vc-mount.service` (Before=multi-user)
              + (manuel) ajouter `After=laforge-vc-mount.service` aux units Nokido.
  - macOS   : launchd daemon /Library/LaunchDaemons/com.nokido.vcmount.plist
              (RunAtLoad).

⚠️ Linux/macOS groundés sur syntaxe standard, NON testés sur Windows. Root/admin
   requis. Idempotent.

Usage : --install [--dry-run] | --uninstall | --status
        --services "LaForge-Master,NokidoMCP" (Windows : services à différer)
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VC_SCRIPT = ROOT / "tools" / "forge_at_rest_veracrypt.py"
PY = sys.executable

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Windows
TASK = "LaForge-VC-Boot"
# Le wrapper vivait sous C:\tmp — repertoire VOLATILE (nettoye periodiquement). Un
# nettoyage l'a fait disparaitre : la tache boot pointait sur un .cmd inexistant, le
# montage n'avait plus lieu et V: restait absent au demarrage -> jonction LaForge/RAG
# pendue -> gate hub fail-closed sur TOUT appel (incident 2026-08-12). On ancre le
# wrapper a cote du conteneur, hors-repo ET hors-tmp.
WRAPPER = Path(r"C:\LaForge_data\nokido_vc_boot_mount.cmd")
_LEGACY_WRAPPERS = (Path(r"C:\tmp\nokido_vc_boot_mount.cmd"),)
DEFAULT_SERVICES = ["LaForge-Master", "NokidoMCP"]
# Linux
SYSTEMD_UNIT = Path("/etc/systemd/system/laforge-vc-mount.service")
# macOS
LAUNCHD_PLIST = Path("/Library/LaunchDaemons/com.nokido.vcmount.plist")


def _log(m: str) -> None:
    print(f"[boot-mount] {m}", flush=True)


def _is_priv() -> bool:
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"introuvable: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


# ════════════════════════════ WINDOWS ════════════════════════════

def _win_wrapper() -> str:
    return ("@echo off\r\n"
            "rem Genere par forge_install_boot_mount.py - monte le volume at-rest.\r\n"
            f'"{PY}" "{VC_SCRIPT}" --mount\r\n')


def _win_install(services: list[str], dry: bool) -> int:
    task_cmd = ["schtasks", "/create", "/tn", TASK, "/sc", "onstart",
                "/ru", "SYSTEM", "/rl", "highest", "/tr", str(WRAPPER), "/f"]
    svc_cmds = [["sc", "config", s, "start=", "delayed-auto"] for s in services]
    if dry:
        _log("DRY-RUN :")
        _log(f"  wrapper {WRAPPER}:\n" + _win_wrapper())
        _log("  " + " ".join(task_cmd))
        for c in svc_cmds:
            _log("  " + " ".join(c))
        return 0
    WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER.write_text(_win_wrapper(), encoding="ascii")
    _log(f"wrapper écrit: {WRAPPER}")
    for old in _LEGACY_WRAPPERS:
        if old.exists() and old != WRAPPER:
            with contextlib.suppress(OSError):
                old.unlink()
                _log(f"  ancien wrapper volatile purgé: {old}")
    rc, out = _run(task_cmd)
    if rc != 0:
        _log(f"ERREUR schtasks rc={rc}: {out.strip()}")
        return 1
    _log("  tâche OK")
    rc_old, _ = _run(["schtasks", "/delete", "/tn", "LaForge-VC-Mount", "/f"])
    if rc_old == 0:
        _log("  ancienne tâche 'LaForge-VC-Mount' (redondante) supprimée")
    for s, c in zip(services, svc_cmds):
        rc, out = _run(c)
        _log(f"  service {s} -> {'différé' if rc == 0 else 'WARN absent: ' + out.strip()[:80]}")
    _log("OK installé (Windows). Reboot pour valider.")
    return 0


def _win_uninstall() -> int:
    rc, _ = _run(["schtasks", "/delete", "/tn", TASK, "/f"])
    _log(f"tâche '{TASK}' : {'supprimée' if rc == 0 else 'absente'}")
    for w in (WRAPPER, *_LEGACY_WRAPPERS):
        if w.exists():
            with contextlib.suppress(OSError):
                w.unlink()
                _log(f"wrapper supprimé: {w}")
    for s in DEFAULT_SERVICES:
        _run(["sc", "config", s, "start=", "auto"])
    return 0


def _win_status() -> int:
    # La visibilité des tâches planifiées dépend du COMPTE : une tâche /ru SYSTEM est
    # invisible depuis un compte sandbox/trusted non élevé. Repondre "ABSENTE" dans ce
    # cas est un garde MENTEUR — le 2026-08-12 la tâche existait ("Prêt" en session
    # owner) pendant que ce status la declarait absente, ce qui a envoye le diagnostic
    # sur une fausse piste. On distingue donc "pas vue" de "pas la".
    priv = _is_priv()
    rc, _ = _run(["schtasks", "/query", "/tn", TASK])
    if rc == 0:
        _log(f"tâche '{TASK}' : présente")
    elif priv:
        _log(f"tâche '{TASK}' : ABSENTE (constate en compte eleve)")
    else:
        _log(f"tâche '{TASK}' : INDETERMINE -- invisible sous '{getpass.getuser()}' "
             f"(non eleve). Trancher en admin : schtasks /query /tn {TASK}")
    # Le wrapper manquant est la panne SILENCIEUSE du 2026-08-12 (tâche verte, montage
    # jamais fait) : on imprime le chemin et on crie quand il manque.
    if WRAPPER.exists():
        _log(f"wrapper : présent ({WRAPPER})")
    else:
        _log(f"wrapper : ABSENT ({WRAPPER}) -> la tâche boot ne monte RIEN, relancer --install")
    for s in DEFAULT_SERVICES:
        rc, out = _run(["sc", "qc", s])
        default = "introuvable" if priv else "INDETERMINE (droits insuffisants sur sc qc)"
        line = next((l.strip() for l in out.splitlines() if "START_TYPE" in l.upper()), default)
        _log(f"  {s}: {line}")
    return 0


# ════════════════════════════ LINUX (systemd) ════════════════════════════

def _linux_unit() -> str:
    return (
        "[Unit]\n"
        "Description=Nokido at-rest container mount\n"
        "DefaultDependencies=no\n"
        "After=local-fs.target\n"
        "Before=multi-user.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"ExecStart={PY} {VC_SCRIPT} --mount\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _linux_install(dry: bool) -> int:
    if dry:
        _log(f"DRY-RUN : écrire {SYSTEMD_UNIT} :\n" + _linux_unit())
        _log("  systemctl daemon-reload ; systemctl enable laforge-vc-mount.service")
        return 0
    SYSTEMD_UNIT.write_text(_linux_unit(), encoding="utf-8")
    _log(f"unité écrite: {SYSTEMD_UNIT}")
    _run(["systemctl", "daemon-reload"])
    rc, out = _run(["systemctl", "enable", "laforge-vc-mount.service"])
    _log(f"enable: {'OK' if rc == 0 else out.strip()[:120]}")
    _log("OK (Linux). AJOUTER 'After=laforge-vc-mount.service' aux units des services")
    _log("Nokido qui ouvrent embeddings.db (anti-race), puis reboot pour valider.")
    return 0


def _linux_uninstall() -> int:
    _run(["systemctl", "disable", "laforge-vc-mount.service"])
    if SYSTEMD_UNIT.exists():
        SYSTEMD_UNIT.unlink()
        _log(f"unité supprimée: {SYSTEMD_UNIT}")
    _run(["systemctl", "daemon-reload"])
    return 0


def _linux_status() -> int:
    _log(f"unité {SYSTEMD_UNIT} : {'présente' if SYSTEMD_UNIT.exists() else 'ABSENTE'}")
    rc, out = _run(["systemctl", "is-enabled", "laforge-vc-mount.service"])
    _log(f"  is-enabled: {out.strip() or rc}")
    return 0


# ════════════════════════════ macOS (launchd) ════════════════════════════

def _mac_plist() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        '  <key>Label</key><string>com.nokido.vcmount</string>\n'
        '  <key>ProgramArguments</key><array>\n'
        f'    <string>{PY}</string><string>{VC_SCRIPT}</string><string>--mount</string>\n'
        '  </array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>StandardErrorPath</key><string>/tmp/nokido_vcmount.err</string>\n'
        '</dict></plist>\n'
    )


def _mac_install(dry: bool) -> int:
    if dry:
        _log(f"DRY-RUN : écrire {LAUNCHD_PLIST} :\n" + _mac_plist())
        _log(f"  launchctl load -w {LAUNCHD_PLIST}")
        return 0
    LAUNCHD_PLIST.write_text(_mac_plist(), encoding="utf-8")
    _log(f"plist écrit: {LAUNCHD_PLIST}")
    rc, out = _run(["launchctl", "load", "-w", str(LAUNCHD_PLIST)])
    _log(f"load: {'OK' if rc == 0 else out.strip()[:120]}")
    _log("OK (macOS). Reboot pour valider.")
    return 0


def _mac_uninstall() -> int:
    _run(["launchctl", "unload", "-w", str(LAUNCHD_PLIST)])
    if LAUNCHD_PLIST.exists():
        LAUNCHD_PLIST.unlink()
        _log(f"plist supprimé: {LAUNCHD_PLIST}")
    return 0


def _mac_status() -> int:
    _log(f"plist {LAUNCHD_PLIST} : {'présent' if LAUNCHD_PLIST.exists() else 'ABSENT'}")
    return 0


# ════════════════════════════ dispatch ════════════════════════════

def cmd_install(services: list[str], dry: bool) -> int:
    if not VC_SCRIPT.exists():
        _log(f"ERREUR: script absent: {VC_SCRIPT}")
        return 1
    if not dry and not _is_priv():
        _log("ERREUR: privilèges requis (admin Windows / root POSIX).")
        return 1
    if IS_WIN:
        return _win_install(services, dry)
    if IS_LINUX:
        return _linux_install(dry)
    if IS_MAC:
        return _mac_install(dry)
    _log(f"OS non supporté: {sys.platform}")
    return 1


def cmd_uninstall() -> int:
    if not _is_priv():
        _log("ERREUR: privilèges requis.")
        return 1
    if IS_WIN:
        return _win_uninstall()
    if IS_LINUX:
        return _linux_uninstall()
    if IS_MAC:
        return _mac_uninstall()
    return 1


def cmd_status() -> int:
    _log(f"OS: {sys.platform} | priv: {_is_priv()}")
    if IS_WIN:
        return _win_status()
    if IS_LINUX:
        return _linux_status()
    if IS_MAC:
        return _mac_status()
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Installeur boot at-rest (cross-OS).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--install", action="store_true")
    g.add_argument("--uninstall", action="store_true")
    g.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--services", default=",".join(DEFAULT_SERVICES))
    args = p.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.uninstall:
        return cmd_uninstall()
    if args.install:
        svcs = [s.strip() for s in args.services.split(",") if s.strip()]
        return cmd_install(svcs, args.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())
