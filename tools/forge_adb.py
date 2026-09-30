#!/usr/bin/env python3
"""forge_adb.py - pont ADB privilegie pour Nokido (compte LaForgeTrusted).

Appel via le hub :
    run(action="trusted_script", path="tools/forge_adb.py", script_args="<cmd>")

Commandes :
    devices                 -> liste les devices ADB connectes
    info                    -> modele / version Android / marque du 1er device
    connect <IP:PORT>       -> adb connect (utile apres reboot du tel)
    pair <IP:PORT> <CODE>   -> adb pair avec code d'association
    shell <commande...>     -> adb shell <commande> sur le 1er device
    shizuku                 -> (re)lance le service Shizuku
    status                  -> device detecte + etat Shizuku en un coup

Notes :
    - ADB pointe sur l'install platform-tools de l'utilisateur (cf. ADB ci-dessous).
    - Le port du debogage sans-fil de l'A50 change a chaque reactivation :
      en cas de "aucun device", refaire `connect <IP:PORT>` (le pairing reste memorise).
"""

__FORGE_COLOR__ = "infra/bridge : pont ADB privilegie (compte LaForgeTrusted)"  # organe declare le 2026-09-06 (audit de raccordement)
import subprocess
import shlex
import sys

# --- Configuration ---
ADB = __import__("os").path.expanduser(r"~\platform-tools\adb.exe")
SHIZUKU_START = "sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh"
SHIZUKU_PKG = "moe.shizuku.privileged.api"


def _run(args, timeout=30):
    """Execute adb avec les args donnes. Retourne (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            [ADB, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return (r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip())
    except FileNotFoundError:
        return (127, "", f"ERREUR: adb introuvable a {ADB}")
    except subprocess.TimeoutExpired:
        return (124, "", f"ERREUR: timeout apres {timeout}s")


def device():
    """Retourne l'identifiant du 1er device en etat 'device', sinon None."""
    rc, out, _ = _run(["devices"])
    if rc != 0:
        return None
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line.endswith("\tdevice"):
            return line.split("\t")[0]
        # tolerance espaces selon version d'adb
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            return parts[0]
    return None


def _need_device():
    dev = device()
    if not dev:
        print("ERREUR: aucun device ADB connecte. "
              "Faire 'connect <IP:PORT>' (debogage sans-fil actif ?).")
    return dev


def cmd_devices():
    print(_run(["devices"])[1])


def cmd_connect(target):
    print(_run(["connect", target])[1])


def cmd_pair(target, code):
    # adb pair lit le code sur stdin
    try:
        r = subprocess.run(
            [ADB, "pair", target],
            input=code + "\n",
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        print((r.stdout or "").strip() or (r.stderr or "").strip())
    except Exception as e:
        print(f"ERREUR pair: {e}")


def cmd_info():
    dev = _need_device()
    if not dev:
        return
    props = (
        "ro.product.model",
        "ro.build.version.release",
        "ro.product.manufacturer",
    )
    for p in props:
        val = _run(["-s", dev, "shell", "getprop", p])[1]
        print(f"{p} = {val}")


def cmd_shell(parts):
    dev = _need_device()
    if not dev:
        return
    print(_run(["-s", dev, "shell", *parts])[1])


def cmd_shizuku():
    dev = _need_device()
    if not dev:
        return
    print(_run(["-s", dev, "shell", *shlex.split(SHIZUKU_START)])[1])


def cmd_status():
    dev = device()
    print(f"device = {dev or 'AUCUN'}")
    if not dev:
        return
    # process shizuku_server present ?
    running = _run(["-s", dev, "shell", "pgrep", "-f", "shizuku_server"])[1]
    print(f"shizuku_server = {'running (pid ' + running + ')' if running else 'arrete'}")


def cmd_reverse(rest):
    """adb reverse : device:localhost:PORT -> host:127.0.0.1:PORT. Permet au
    navigateur du tel d'atteindre les services Starlette bindés localhost.
    `reverse web` = 7400/8766/7401/8767 d'un coup."""
    dev = _need_device()
    if not dev:
        return
    ports = ["7400", "8766", "7401", "8767"] if (rest and rest[0] == "web") else None
    if ports:
        for p in ports:
            _run(["-s", dev, "reverse", f"tcp:{p}", f"tcp:{p}"])
    elif len(rest) >= 2:
        _run(["-s", dev, "reverse", f"tcp:{rest[0]}", f"tcp:{rest[1]}"])
    print(_run(["-s", dev, "reverse", "--list"])[1] or "(aucun reverse)")


def cmd_open(rest):
    """Ouvre une URL dans le navigateur du device (VIEW intent)."""
    dev = _need_device()
    if not dev:
        return
    url = rest[0] if rest else "http://localhost:7400"
    print(_run(["-s", dev, "shell", "am", "start", "-a",
                "android.intent.action.VIEW", "-d", url])[1])


def cmd_screenshot(rest):
    """Capture l'écran -> PNG local (exec-out = binaire propre). Défaut :
    sandbox/workspace/adb_screen.png (lisible par l'agent via Read)."""
    dev = _need_device()
    if not dev:
        return
    import os as _os
    default = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "sandbox", "workspace", "adb_screen.png")
    local = rest[0] if rest else default
    remote = "/sdcard/laf_screen.png"
    # screencap -> fichier device puis pull (fiable ; exec-out binaire = flaky sur adb-tls)
    _run(["-s", dev, "shell", "screencap", "-p", remote])
    _os.makedirs(_os.path.dirname(local), exist_ok=True)
    rc, out, err = _run(["-s", dev, "pull", remote, local])
    _run(["-s", dev, "shell", "rm", "-f", remote])
    if _os.path.exists(local) and _os.path.getsize(local) > 1000:
        print(f"OK screenshot {_os.path.getsize(local)} octets -> {local}")
    else:
        print(f"ECHEC pull (taille={_os.path.getsize(local) if _os.path.exists(local) else 0}) out={out} err={err}")


def main(argv):
    if not argv:
        print("usage: devices | info | status | connect <ip:port> | "
              "pair <ip:port> <code> | shell <cmd...> | shizuku")
        return
    op = argv[0]
    rest = argv[1:]
    if op == "devices":
        cmd_devices()
    elif op == "info":
        cmd_info()
    elif op == "status":
        cmd_status()
    elif op == "connect" and rest:
        cmd_connect(rest[0])
    elif op == "pair" and len(rest) >= 2:
        cmd_pair(rest[0], rest[1])
    elif op == "shell" and rest:
        cmd_shell(rest)
    elif op == "shizuku":
        cmd_shizuku()
    elif op == "reverse":
        cmd_reverse(rest)
    elif op == "open":
        cmd_open(rest)
    elif op == "screenshot":
        cmd_screenshot(rest)
    else:
        print(f"commande inconnue ou args manquants: {op}")


if __name__ == "__main__":
    main(sys.argv[1:])