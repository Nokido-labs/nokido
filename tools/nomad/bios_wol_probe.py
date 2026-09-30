"""Sonde BIOS/UEFI en LECTURE SEULE, pour le diagnostic Wake-on-LAN.

Question a laquelle ce script repond : les deux reglages BIOS qui commandent le
WOL depuis S3/S5 sur l'ASUS B650E MAX GAMING WIFI W sont-ils bons ?

    Advanced > APM Configuration > ErP Ready       = Disabled
        (ErP coupe le rail +5VSB quand le PC est eteint : le PHY de la carte
         reseau n'est plus alimente, aucun magic packet ne peut etre vu)
    Advanced > APM Configuration > Power On By PCI-E = Enabled

CE QUE CE SCRIPT FAIT, ET SES LIMITES -- a lire avant de se fier au resultat :

  * Il n'installe AUCUN driver kernel. Il n'ecrit RIEN dans le firmware. Il
    utilise GetFirmwareEnvironmentVariableW, API Windows documentee, qui exige
    seulement le privilege SeSystemEnvironmentPrivilege (donc une console
    elevee). Les outils qui pretendent editer le BIOS depuis Windows (AMI
    SCEWIN, AsIO3) chargent un driver kernel non supporte par ASUS et peuvent
    corrompre la NVRAM : ils ne sont volontairement pas utilises ici.

  * Le blob "Setup" ainsi lu est OPAQUE. La correspondance octet -> reglage
    vit dans l'IFR (les formulaires HII) du firmware, pas dans la variable.
    Sans ce mapping, un octet a l'offset 0x2A1 ne se laisse pas nommer.
    Ne jamais deviner : un octet mal interprete produirait un diagnostic
    inverse de la realite.

  * D'ou le mode --diff, qui est la vraie voie sans driver : on dump avant,
    l'owner bascule UN reglage dans le BIOS, on dump apres, et le diff designe
    l'offset exact. Une fois l'offset connu, la lecture devient fiable et
    repetable. C'est plus long qu'un outil magique, mais c'est mesure au lieu
    d'etre suppose.

  * WakeUpType (SMBIOS, via Win32_ComputerSystem) est le capteur qui manquait
    pour valider S5 : le journal Power-Troubleshooter ne trace que les sorties
    de VEILLE, jamais un demarrage depuis l'arret complet. WakeUpType vaut 6
    apres un appui sur le bouton, et 8 (PCI PME#) apres un reveil par la carte
    reseau. C'est donc lui qui prouve -- ou refute -- un WOL depuis S5.

Usage, console ELEVEE :
    <LAFORGE_PYTHON> tools/nomad/bios_wol_probe.py
    <LAFORGE_PYTHON> tools/nomad/bios_wol_probe.py --diff
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import sys

GLOBAL_GUID = "{8BE4DF61-93CA-11D2-AA0D-00E098032B8C}"
AMI_SETUP_GUID = "{EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9}"
DUMP_PATH = r"C:\tmp\bios_setup_nvram.bin"
BUF_SIZE = 1 << 17

SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
ERROR_PRIVILEGE_NOT_HELD = 1314
ERROR_ENVVAR_NOT_FOUND = 203

_advapi = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)

WAKEUP_TYPES = {
    0: "Reserved",
    1: "Other",
    2: "Unknown",
    3: "APM Timer",
    4: "Modem Ring",
    5: "LAN Remote",
    6: "Power Switch",
    7: "PCI PME#",
    8: "AC Power Restored",
}


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wt.DWORD), ("HighPart", ctypes.c_long)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", wt.DWORD)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wt.DWORD), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


# Prototypes EXPLICITES, obligatoires en 64 bits. Sans eux ctypes suppose des
# int 32 bits : le pseudo-handle rendu par GetCurrentProcess() vaut -1, il est
# tronque, et OpenProcessToken repond ERROR_INVALID_HANDLE (6) alors meme que
# le process EST eleve. Symptome observe le 2026-07-22 : "elevated": true et
# "OpenProcessToken err=6" dans le meme rapport -- une contradiction qui
# designe le binding, jamais la machine.
_kernel.GetCurrentProcess.argtypes = []
_kernel.GetCurrentProcess.restype = wt.HANDLE
_advapi.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_advapi.OpenProcessToken.restype = wt.BOOL
_advapi.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(_LUID)]
_advapi.LookupPrivilegeValueW.restype = wt.BOOL
_advapi.AdjustTokenPrivileges.argtypes = [
    wt.HANDLE,
    wt.BOOL,
    ctypes.POINTER(_TOKEN_PRIVILEGES),
    wt.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_advapi.AdjustTokenPrivileges.restype = wt.BOOL


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def enable_privilege(name: str) -> tuple[bool, str]:
    """Active un privilege dans le token du process courant."""
    htok = wt.HANDLE()
    if not _advapi.OpenProcessToken(
        _kernel.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(htok)
    ):
        return False, "OpenProcessToken err=%d" % ctypes.get_last_error()
    luid = _LUID()
    if not _advapi.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
        return False, "LookupPrivilegeValueW err=%d" % ctypes.get_last_error()
    tp = _TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    ctypes.set_last_error(0)
    ok = _advapi.AdjustTokenPrivileges(htok, False, ctypes.byref(tp), 0, None, None)
    err = ctypes.get_last_error()
    _kernel.CloseHandle(htok)
    # AdjustTokenPrivileges renvoie succes meme quand il n'a rien accorde :
    # seul GetLastError distingue les deux cas.
    if not ok or err != 0:
        return False, "AdjustTokenPrivileges err=%d" % err
    return True, "ok"


def read_uefi_var(name: str, guid: str) -> tuple[bytes | None, int]:
    fn = _kernel.GetFirmwareEnvironmentVariableW
    fn.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD]
    fn.restype = wt.DWORD
    buf = ctypes.create_string_buffer(BUF_SIZE)
    ctypes.set_last_error(0)
    n = fn(name, guid, buf, BUF_SIZE)
    if n == 0:
        return None, ctypes.get_last_error()
    return buf.raw[: int(n)], 0


def smbios_wakeup() -> dict:
    """Raison du dernier demarrage. Le seul capteur qui couvre S5."""
    out: dict = {}
    try:
        import subprocess

        ps = (
            "Get-CimInstance Win32_ComputerSystem | "
            "Select-Object -ExpandProperty WakeUpType"
        )
        # errors='replace' : sans lui, un octet non decodable dans la sortie
        # PowerShell fait crasher le _readerthread de subprocess en mode texte.
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
        raw = p.stdout.strip()
        out["raw"] = raw
        if raw.isdigit():
            code = int(raw)
            out["code"] = code
            out["meaning"] = WAKEUP_TYPES.get(code, "?")
            out["woke_by_nic"] = code in (5, 7)
        else:
            out["error"] = p.stderr.strip()[:200] or "sortie non numerique"
    except Exception as exc:  # WORKSPACE_GUARD interdit subprocess dans le sandbox agent
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def main() -> int:
    want_diff = "--diff" in sys.argv
    report: dict = {"elevated": is_elevated()}

    if not report["elevated"]:
        print(
            "REFUS : console non elevee. La lecture des variables firmware exige\n"
            "        SeSystemEnvironmentPrivilege. Relancer depuis un PowerShell\n"
            "        Administrateur."
        )
        return 1

    ok, detail = enable_privilege("SeSystemEnvironmentPrivilege")
    report["privilege"] = {"granted": ok, "detail": detail}

    variables = {
        "Setup@AMI": ("Setup", AMI_SETUP_GUID),
        "Setup@global": ("Setup", GLOBAL_GUID),
        "SecureBoot": ("SecureBoot", GLOBAL_GUID),
        "BootOrder": ("BootOrder", GLOBAL_GUID),
    }
    read_out: dict = {}
    setup_blob: bytes | None = None
    for label, (var, guid) in variables.items():
        data, err = read_uefi_var(var, guid)
        if data is None:
            hint = ""
            if err == ERROR_PRIVILEGE_NOT_HELD:
                hint = " (privilege refuse)"
            elif err == ERROR_ENVVAR_NOT_FOUND:
                hint = " (variable absente sous ce GUID)"
            read_out[label] = {"ok": False, "winerr": err, "hint": hint.strip()}
            continue
        read_out[label] = {
            "ok": True,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()[:32],
        }
        if label.startswith("Setup") and setup_blob is None:
            setup_blob = data
    report["uefi_vars"] = read_out

    if setup_blob is not None:
        previous = None
        if os.path.exists(DUMP_PATH):
            with open(DUMP_PATH, "rb") as fh:
                previous = fh.read()
        if want_diff and previous is not None:
            deltas = []
            limit = min(len(previous), len(setup_blob))
            for off in range(limit):
                if previous[off] != setup_blob[off]:
                    deltas.append(
                        {"offset": hex(off), "before": previous[off], "after": setup_blob[off]}
                    )
            report["diff"] = {
                "previous_bytes": len(previous),
                "current_bytes": len(setup_blob),
                "changed": deltas[:64],
                "changed_count": len(deltas),
            }
        else:
            os.makedirs(os.path.dirname(DUMP_PATH), exist_ok=True)
            with open(DUMP_PATH, "wb") as fh:
                fh.write(setup_blob)
            report["dump"] = {"path": DUMP_PATH, "bytes": len(setup_blob)}

    report["last_boot_cause"] = smbios_wakeup()

    print(json.dumps(report, indent=1))

    print("")
    print("LECTURE DU RESULTAT")
    wake = report["last_boot_cause"]
    if wake.get("code") is not None:
        print("  Dernier demarrage : %s (WakeUpType=%s)" % (wake["meaning"], wake["code"]))
        if wake.get("woke_by_nic"):
            print("  => la carte reseau a bien reveille la machine. WOL fonctionnel.")
        else:
            print("  => ce demarrage ne vient PAS de la carte reseau.")
            print("     Attendu apres un WOL reussi : 'PCI PME#' ou 'LAN Remote'.")
    if "dump" in report:
        print("  Blob Setup dumpe. Procedure pour nommer un reglage, sans driver :")
        print("    1. redemarrer, entrer dans le BIOS (Suppr), basculer UN SEUL reglage")
        print("       (ex. ErP Ready), sauver et redemarrer ;")
        print("    2. relancer ce script avec --diff : les offsets listes sont ceux")
        print("       de ce reglage, et de lui seul.")
    if "diff" in report:
        print("  Offsets modifies : %d" % report["diff"]["changed_count"])
        print("  Un seul offset change = c'est celui du reglage bascule. Le noter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
