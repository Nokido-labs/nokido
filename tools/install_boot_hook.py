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

Generated artefacts land in deploy/ ; this script does NOT install them
(installation needs OS privileges and is a deliberate manual step).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
SUPERVISOR = "proxy_deno/core/supervisor.ts"


def _deno() -> str:
    return shutil.which("deno") or "deno"


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
