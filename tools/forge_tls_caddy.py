#!/usr/bin/env python3
"""
forge_tls_caddy.py — Terminaison TLS du hub via Caddy (méthode retenue panel
multi-LLM 2026-06-01, après l'échec asyncio SSL Windows).

Pourquoi Caddy : reverse-proxy TLS qui gère NATIVEMENT keep-alive HTTP/1.1, SSE
streaming, WebSocket, gros corps (RAG) ; binaire UNIQUE cross-OS (Windows/Linux/
macOS) → cohérence ; Caddyfile déclaratif ; souverain (tourne en local, Apache2.0).
Contourne le bug asyncio SSL Windows (proxy/in-hub) en n'étant pas asyncio.

Rôle : termine TLS sur :8443 (LAFORGE_HUB_TLS_PORT) avec le cert auto-signé local
puis reverse_proxy vers le hub HTTP 127.0.0.1:8766. HTTP:8766 reste intact
(non-cassant) ; les clients qui veulent TLS visent :8443.

INSTALL Caddy :
  Windows : winget install Caddy.Caddy
  Linux   : apt install caddy  /  dnf install caddy
  macOS   : brew install caddy

Usage : --status | --write-config | --run
Boot/service : `caddy` peut tourner en service, ou réutiliser
forge_install_boot_mount (adapter la cible). Cert : forge_gen_tls_cert.py.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERT = os.environ.get("LAFORGE_HUB_TLS_CERT", str(ROOT / "sandbox" / "tls" / "cert.pem"))
KEY = os.environ.get("LAFORGE_HUB_TLS_KEY", str(ROOT / "sandbox" / "tls" / "key.pem"))
CADDYFILE = ROOT / "sandbox" / "Caddyfile"
LISTEN = int(os.environ.get("LAFORGE_HUB_TLS_PORT", "8443"))
TARGET = os.environ.get("LAFORGE_HUB_PORT", "8766")

# Win32 : empêche caddy.exe (app console) d'allouer une fenêtre visible au logon
# (tâche onlogon silencieuse). Noop hors Windows (creationflags=0 accepté partout).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _log(m: str) -> None:
    print(f"[caddy] {m}", flush=True)


def _caddy_bin() -> str | None:
    # Priorité : env > binaire vendored (sandbox/caddy[.exe], souverain, 0 install) > PATH.
    env = os.environ.get("LAFORGE_CADDY_BIN")
    if env and os.path.isfile(env):
        return env
    name = "caddy.exe" if sys.platform == "win32" else "caddy"
    vendored = ROOT / "sandbox" / name
    if vendored.is_file():
        return str(vendored)
    return shutil.which("caddy")


# mTLS (RFC 8705) : la CA qui signe les certificats CLIENTS. Absente -> pas de mTLS,
# et on le DIT plutot que de laisser croire a une authentification forte.
CLIENT_CA = ROOT / "sandbox" / "tls" / "clients_ca.pem"


def write_config(mtls: bool = False) -> str:
    """Genere le Caddyfile. `bind` EXPLICITE : mesure 2026-09-02, le socket ecoutait
    sur 0.0.0.0 ET [::] alors que le site ne declarait que 127.0.0.1/localhost --
    donc le hub, pourtant bind en loopback, etait joignable depuis le LAN. Une
    adresse de site n'est PAS une contrainte d'ecoute : seul `bind` l'est.

    `mtls=True` exige un certificat CLIENT valide (RFC 8705). Le bearer prouve la
    possession d'un secret ; le certificat prouve l'identite du porteur. Pour un
    contre-expert distant, c'est ce qui rattache une contribution a un contributeur.
    """
    CADDYFILE.parent.mkdir(parents=True, exist_ok=True)
    if mtls and not CLIENT_CA.exists():
        _log(f"ERREUR: --mtls demande mais CA client absente ({CLIENT_CA}). "
             "Refus d'ecrire une config qui aurait l'air protegee sans l'etre.")
        raise SystemExit(2)
    if mtls:
        bloc_tls = (
            f'\ttls "{CERT}" "{KEY}" {{\n'
            f'\t\tclient_auth {{\n'
            f'\t\t\tmode require_and_verify\n'
            f'\t\t\ttrust_pool file {{\n\t\t\t\tpem_file "{CLIENT_CA}"\n\t\t\t}}\n'
            f'\t\t}}\n'
            f'\t}}\n'
        )
    else:
        # Pas de bloc vide : une directive `tls ... {}` sans contenu est du bruit,
        # et un lecteur pourrait la prendre pour une configuration active.
        bloc_tls = f'\ttls "{CERT}" "{KEY}"\n'
    cfg = (
        "{\n"
        # admin API sur loopback (défaut localhost:2019) — requis pour caddy stop/reload.
        "\tauto_https off\n"
        "}\n"
        f"https://127.0.0.1:{LISTEN}, https://localhost:{LISTEN} {{\n"
        # Sans ceci, Caddy ecoute sur TOUTES les interfaces (mesure : 0.0.0.0 + [::]).
        "\tbind 127.0.0.1 ::1\n"
        + bloc_tls +
        f"\treverse_proxy 127.0.0.1:{TARGET}\n"
        "}\n"
    )
    CADDYFILE.write_text(cfg, encoding="utf-8")
    _log(f"Caddyfile écrit -> {CADDYFILE} (bind loopback"
         + (", mTLS require_and_verify" if mtls else ", mTLS off") + ")")
    return cfg


def cmd_run(mtls: bool = False) -> int:
    caddy = _caddy_bin()
    if not caddy:
        _log("ERREUR: caddy absent. Windows: winget install Caddy.Caddy ; Linux: apt/dnf caddy ; mac: brew.")
        return 1
    if not (os.path.isfile(CERT) and os.path.isfile(KEY)):
        _log(f"ERREUR: cert/key absent ({CERT}). Lancer tools/forge_gen_tls_cert.py.")
        return 1
    write_config(mtls=mtls)
    _log(f"run TLS :{LISTEN} -> 127.0.0.1:{TARGET} (Ctrl+C pour arrêter)")
    return subprocess.run([caddy, "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"]).returncode


def cmd_start(mtls: bool = False) -> int:
    caddy = _caddy_bin()
    if not caddy:
        _log("ERREUR: caddy absent. winget install CaddyServer.Caddy (puis nouveau terminal).")
        return 1
    if not (os.path.isfile(CERT) and os.path.isfile(KEY)):
        _log(f"ERREUR: cert/key absent ({CERT}). Lancer tools/forge_gen_tls_cert.py.")
        return 1
    write_config(mtls=mtls)
    rc = subprocess.run([caddy, "start", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
                        creationflags=_NO_WINDOW).returncode
    _log(f"caddy {'démarré en background (caddy stop pour arrêter)' if rc == 0 else 'échec ' + str(rc)}")
    return rc


def cmd_stop() -> int:
    caddy = _caddy_bin()
    if not caddy:
        _log("caddy absent.")
        return 1
    return subprocess.run([caddy, "stop"], creationflags=_NO_WINDOW).returncode


_TASK = "LaForge-TLS-Caddy"
_WIN_WRAPPER = Path(r"C:\tmp\nokido_tls_caddy.cmd")
_SELF = str(Path(__file__).resolve())
_PY = sys.executable


def _boot_install() -> int:
    """Persistance au login (compte user — caddy dans le PATH user, pas de SYSTEM/
    vendoring). Windows=schtasks onlogon ; Linux=systemd --user ; macOS=launchd agent."""
    if sys.platform == "win32":
        # pythonw.exe = pas de console -> tâche onlogon 100% silencieuse (combiné au
        # CREATE_NO_WINDOW sur caddy.exe ci-dessus). Plus de wrapper .cmd (qui ouvrait
        # une fenêtre cmd au logon). Ancien wrapper nettoyé par _boot_uninstall.
        pyw = Path(_PY).with_name("pythonw.exe")
        launcher = str(pyw if pyw.is_file() else _PY)
        rc = subprocess.run(["schtasks", "/create", "/tn", _TASK, "/sc", "onlogon",
                             "/tr", f'"{launcher}" "{_SELF}" --start', "/f"]).returncode
        _log(f"tâche onlogon '{_TASK}' : {'OK' if rc == 0 else 'échec ' + str(rc)} (launcher {launcher})")
        return rc
    if sys.platform.startswith("linux"):
        unit = Path.home() / ".config" / "systemd" / "user" / "laforge-tls-caddy.service"
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(
            "[Unit]\nDescription=Nokido TLS (Caddy) reverse proxy\nAfter=network.target\n\n"
            f"[Service]\nType=simple\nExecStart={_PY} {_SELF} --run\nRestart=on-failure\n\n"
            "[Install]\nWantedBy=default.target\n", encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        rc = subprocess.run(["systemctl", "--user", "enable", "--now", "laforge-tls-caddy.service"]).returncode
        _log(f"systemd --user : {'OK' if rc == 0 else 'échec'} ({unit}). `loginctl enable-linger` pour pré-login.")
        return rc
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.nokido.tlscaddy.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>\n'
            '  <key>Label</key><string>com.nokido.tlscaddy</string>\n'
            f'  <key>ProgramArguments</key><array><string>{_PY}</string>'
            f'<string>{_SELF}</string><string>--run</string></array>\n'
            '  <key>RunAtLoad</key><true/>\n</dict></plist>\n', encoding="utf-8")
        rc = subprocess.run(["launchctl", "load", "-w", str(plist)]).returncode
        _log(f"launchd agent : {'OK' if rc == 0 else 'échec'} ({plist})")
        return rc
    _log(f"OS non supporté: {sys.platform}")
    return 1


def _boot_uninstall() -> int:
    if sys.platform == "win32":
        rc = subprocess.run(["schtasks", "/delete", "/tn", _TASK, "/f"]).returncode
        if _WIN_WRAPPER.exists():
            _WIN_WRAPPER.unlink()
        _log(f"tâche '{_TASK}' supprimée ({rc})")
        return 0
    if sys.platform.startswith("linux"):
        subprocess.run(["systemctl", "--user", "disable", "--now", "laforge-tls-caddy.service"])
        u = Path.home() / ".config" / "systemd" / "user" / "laforge-tls-caddy.service"
        if u.exists():
            u.unlink()
        return 0
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "LaunchAgents" / "com.nokido.tlscaddy.plist"
        subprocess.run(["launchctl", "unload", "-w", str(p)])
        if p.exists():
            p.unlink()
        return 0
    return 1


def cmd_status() -> int:
    _log(f"OS         : {sys.platform}")
    _log(f"caddy bin  : {_caddy_bin() or 'ABSENT (installer)'}")
    _log(f"cert       : {CERT} (existe={os.path.isfile(CERT)})")
    _log(f"key        : {KEY} (existe={os.path.isfile(KEY)})")
    _log(f"Caddyfile  : {CADDYFILE} (existe={CADDYFILE.exists()})")
    _log(f"cible      : TLS :{LISTEN} -> 127.0.0.1:{TARGET}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Terminaison TLS du hub via Caddy (cross-OS, robuste).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--write-config", action="store_true", help="Génère le Caddyfile sans lancer")
    g.add_argument("--run", action="store_true", help="Lance caddy (foreground)")
    g.add_argument("--start", action="store_true", help="Lance caddy en background (caddy start)")
    g.add_argument("--stop", action="store_true", help="Arrête caddy (caddy stop)")
    g.add_argument("--install-boot", action="store_true", help="Persistance au login (onlogon/systemd/launchd)")
    g.add_argument("--uninstall-boot", action="store_true")
    # mTLS (RFC 8705) : preuve de possession cote CLIENT. Un bearer prouve qu'on
    # detient un secret ; un certificat prouve QUI le detient. Necessaire des qu'un
    # contributeur distant participe -- une contribution doit etre rattachable a son
    # auteur, pas seulement etiquetee par un en-tete.
    p.add_argument("--mtls", action="store_true",
                   help="Exige un certificat CLIENT valide (require_and_verify, CA "
                        "sandbox/tls/clients_ca.pem). Refuse d'ecrire si la CA manque.")
    args = p.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.write_config:
        write_config(mtls=args.mtls)
        return 0
    if args.run:
        return cmd_run(mtls=args.mtls)
    if args.start:
        return cmd_start(mtls=args.mtls)
    if args.stop:
        return cmd_stop()
    if args.install_boot:
        return _boot_install()
    if args.uninstall_boot:
        return _boot_uninstall()
    return 2


if __name__ == "__main__":
    sys.exit(main())
