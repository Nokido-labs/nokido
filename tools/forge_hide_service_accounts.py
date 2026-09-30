#!/usr/bin/env python3
"""forge_hide_service_accounts.py — masque les comptes de service Nokido de
l'écran de connexion / verrouillage Windows et rend la tâche onlogon Caddy
silencieuse (relance via pythonw, sans fenêtre console).

Mécanisme compte : HKLM\\...\\Winlogon\\SpecialAccounts\\UserList, DWORD=0 ->
le compte n'apparaît plus sur l'écran de login. Il reste pleinement utilisable
(services, runas, schtasks). 100% RÉVERSIBLE : --show supprime la valeur.

Mécanisme Caddy : bascule l'action de la tâche LaForge-TLS-Caddy de python.exe
(console visible au logon) vers pythonw.exe (aucune console). Couplé au
CREATE_NO_WINDOW posé dans forge_tls_caddy.py -> logon 100% silencieux.

Admin REQUIS (écriture HKLM + schtasks /change sur une tâche d'un autre user).
À lancer via le hub : run action=trusted_script (LaForgeTrustedRunner élevé).

Usage:
  --check                       diag : admin? valeurs UserList? action tâche Caddy?
  --hide LaForgeTrusted[,...]   masque le(s) compte(s) (UserList=0)
  --show LaForgeTrusted[,...]   ré-affiche (supprime la valeur)
  --caddy-quiet                 tâche LaForge-TLS-Caddy -> pythonw (sans fenêtre)
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
from pathlib import Path

try:
    import winreg  # type: ignore
except ImportError:  # non-Windows : module absent
    winreg = None  # type: ignore

USERLIST = (
    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    r"\SpecialAccounts\UserList"
)
CADDY_TASK = "LaForge-TLS-Caddy"
SERVICE_ACCOUNTS = ["LaForgeTrusted", "LaForgeSbxOffline", "LaForgeSbxOnline"]


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def _read_userlist() -> dict:
    out: dict = {}
    if winreg is None:
        return out
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, USERLIST, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return out
    try:
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            out[name] = val
            i += 1
    finally:
        winreg.CloseKey(k)
    return out


def _set_userlist(name: str, value) -> None:
    """value=0 masque ; value=None supprime la valeur (compte redevient visible)."""
    k = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, USERLIST, 0, winreg.KEY_SET_VALUE)
    try:
        if value is None:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))
    finally:
        winreg.CloseKey(k)


def _pythonw() -> str:
    p = Path(sys.executable)
    cand = p.with_name("pythonw.exe")
    return str(cand if cand.is_file() else p)


def _caddy_action() -> str:
    r = subprocess.run(
        ["schtasks", "/query", "/tn", CADDY_TASK, "/fo", "LIST", "/v"],
        capture_output=True, text=True,
    errors="replace")
    return (r.stdout or r.stderr or "").strip()


def _set_caddy_quiet() -> int:
    script = str(Path(__file__).resolve().parent / "forge_tls_caddy.py")
    tr = f'"{_pythonw()}" "{script}" --start'
    r = subprocess.run(
        ["schtasks", "/change", "/tn", CADDY_TASK, "/tr", tr],
        capture_output=True, text=True,
    errors="replace")
    print("[hide] " + (r.stdout.strip() or r.stderr.strip()))
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--hide", default="")
    ap.add_argument("--show", default="")
    ap.add_argument("--caddy-quiet", action="store_true")
    a = ap.parse_args(argv)

    admin = _is_admin()
    print(f"[hide] admin={admin} user={os.environ.get('USERNAME')}")

    if a.check or not (a.hide or a.show or a.caddy_quiet):
        ul = _read_userlist()
        print("[hide] UserList (écran de connexion) :")
        for acc in SERVICE_ACCOUNTS:
            v = ul.get(acc)
            if v is None:
                label = "(absent => VISIBLE)"
            else:
                label = f"{v} ({'masqué' if v == 0 else 'visible'})"
            print(f"   {acc} = {label}")
        print(f"[hide] pythonw = {_pythonw()}")
        print(f"[hide] action tâche {CADDY_TASK} :")
        for line in _caddy_action().splitlines():
            ls = line.strip()
            low = ls.lower()
            if any(s in low for s in ("exécuter", "executer", "run:", "task to run",
                                      "nom de", "taskname", "erreur", "error",
                                      "utilisateur", "run as user")):
                print("   " + ls)
        return 0

    if not admin:
        print("[hide] ERREUR: admin requis (HKLM + schtasks /change). Relancer élevé.")
        return 13

    rc = 0
    for acc in [x.strip() for x in a.hide.split(",") if x.strip()]:
        _set_userlist(acc, 0)
        print(f"[hide] {acc} MASQUÉ (UserList=0)")
    for acc in [x.strip() for x in a.show.split(",") if x.strip()]:
        _set_userlist(acc, None)
        print(f"[hide] {acc} ré-affiché (valeur supprimée)")
    if a.caddy_quiet:
        rc |= _set_caddy_quiet()
    return rc


if __name__ == "__main__":
    sys.exit(main())
