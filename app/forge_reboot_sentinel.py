# -*- coding: utf-8 -*-
"""
forge_reboot_sentinel.py — Le corps SENT son propre reboot
==========================================================
Owner 2026-07-23 : "le pid X survit au stop... c'est reboot, le vois-tu ?".
Trou mesure : apres un reboot systeme, Nokido ne SAIT pas qu'il a redemarre.
Le registre superviseur n'est pas re-synchronise avec la realite post-boot ->
les process ancres au boot (lances par le SCM/owner hors LaForge-Master) restent
orphelins/invisibles, et un `stop` superviseur les rate. Le lifecycle journal
etant muet, aucun respawn/reboot n'est visible dans le temps.

Ce sentinel persiste boot_time et le compare a chaque tick homeostatique. Sur
changement (= reboot) : (1) JOURNALISE l'evenement (forge_lifecycle_audit.record,
revit le journal sur l'evenement cle), (2) RECONCILIE le registre vs la realite
post-boot (forge_port_reconcile). Le corps voit enfin son redemarrage.

Anti-dup : reutilise forge_lifecycle_audit.record (journal) + forge_port_reconcile
(reconcile deja cable dans le tick). N'introduit aucun nouveau tracker.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "sandbox" / "boot_sentinel.json"


def _windows_last_shutdown(days: int = 2) -> dict:
    """L'arret PRECEDENT etait-il PROPRE ? La reponse vient de l'OS, pas de nous.

    - Kernel-Power 41 = « le systeme a redemarre sans s'arreter correctement ».
    - EventLog 6008 porte l'heure du dernier arret inattendu.
    - BugcheckCode != 0 => BSOD, et alors un dump existe (Minidump/MEMORY.DMP).
      BugcheckCode == 0 => gel ou coupure d'alimentation, et AUCUN dump n'est
      ecrit. C'est exactement le cas qu'on ne savait pas nommer le 2026-07-26.
    - PowerButtonTimestamp != 0 => l'OS a VU le bouton (arret demande).

    UN seul spawn PowerShell, au boot uniquement. Best-effort : en cas d'echec on
    renvoie unclean=None — « je ne sais pas » et « tout va bien » ne doivent
    jamais se confondre (un scanner qui n'a pas pu regarder se lit rassurant).
    """
    import subprocess
    import sys as _sys

    if _sys.platform != "win32":
        return {"unclean": None, "why": "non-Windows"}
    ps = (
        "$e=Get-WinEvent -FilterHashtable @{LogName='System';Id=41;"
        f"StartTime=(Get-Date).AddDays(-{days})}} -MaxEvents 1 -ErrorAction SilentlyContinue; "
        "if($e){$d=([xml]$e.ToXml()).Event.EventData.Data;"
        "$bc=($d|Where-Object {$_.Name -eq 'BugcheckCode'}).'#text';"
        "$pb=($d|Where-Object {$_.Name -eq 'PowerButtonTimestamp'}).'#text';"
        "'41|'+$e.TimeCreated.ToString('s')+'|'+$bc+'|'+$pb}; "
        "$f=Get-WinEvent -FilterHashtable @{LogName='System';Id=6008;"
        f"StartTime=(Get-Date).AddDays(-{days})}} -MaxEvents 1 -ErrorAction SilentlyContinue; "
        "if($f){'6008|'+$f.TimeCreated.ToString('s')}"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"unclean": None, "why": f"sonde indisponible: {type(exc).__name__}: {exc}"[:150]}
    out: dict = {"unclean": False, "why": "aucun Kernel-Power 41 recent"}
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split("|")
        if parts[0] == "41" and len(parts) >= 4:
            try:
                bugcheck = int(parts[2] or 0)
            except ValueError:
                bugcheck = 0
            try:
                power_button = int(parts[3] or 0)
            except ValueError:
                power_button = 0
            out = {
                "unclean": True,
                "event41_at": parts[1],
                "bugcheck_code": bugcheck,
                "power_button_timestamp": power_button,
                "kind": ("bsod (un dump doit exister)" if bugcheck
                         else "gel ou coupure (AUCUN dump ecrit par Windows)"),
                "why": "Kernel-Power 41",
            }
        elif parts[0] == "6008" and len(parts) >= 2:
            out["event6008_at"] = parts[1]
    return out


def _post_mortem(boot_ts: float) -> dict:
    """Joint la courbe de vitaux a un arret SALE, et le consigne.

    Pourquoi : le 2026-07-26 ce sentinel a bien vu le reboot, mais il a ecrit un
    simple « reboot_detected ». Un redemarrage volontaire et un plantage
    laissaient donc la MEME trace — donc aucun des deux n'etait diagnosticable.
    Et il n'existait aucune serie RAM/CPU : l'enquete a pu dater la mort a la
    seconde sans pouvoir dire ce que la machine encaissait.
    """
    info = _windows_last_shutdown()
    if not info.get("unclean"):
        return info
    try:
        from nokido_agent.app.forge_resource_manager import read_vitals_history

        rows = read_vitals_history(since_ts=boot_ts - 1800.0, limit=400)
        # On ne garde que ce qui precede le boot : c'est l'agonie, pas la reprise.
        info["vitals_before_death"] = [r for r in rows if float(r.get("ts") or 0) < boot_ts][-60:]
    except Exception as exc:  # noqa: BLE001
        info["vitals_before_death"] = []
        info["vitals_err"] = f"{type(exc).__name__}: {exc}"[:120]
    try:
        from nokido_agent.app.forge_lifecycle_audit import tail as _lc_tail

        info["last_lifecycle_actions"] = [
            {k: v for k, v in row.items() if k in ("ts", "domain", "action", "reason")}
            for row in _lc_tail(15)
        ]
    except Exception:  # noqa: BLE001
        info["last_lifecycle_actions"] = []
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(boot_ts))
    try:
        path = ROOT / "sandbox" / f"crash_report_{stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        info["report"] = str(path)
    except OSError as exc:
        info["report_err"] = str(exc)[:120]
    try:
        from nokido_agent.app.forge_lifecycle_audit import record

        record(
            "crash_detected",
            "system",
            f"arret sale: {info.get('kind')} (bugcheck={info.get('bugcheck_code')})",
            event41_at=info.get("event41_at"),
            event6008_at=info.get("event6008_at"),
            vitals_points=len(info.get("vitals_before_death") or []),
            report=info.get("report"),
        )
    except Exception:  # noqa: BLE001
        pass
    return info


def check_reboot(state_path: Optional[str] = None) -> dict:
    """Detecte un changement de boot_time (= reboot). Journalise + reconcilie si detecte."""
    import psutil

    boot = float(psutil.boot_time())
    sp = Path(state_path) if state_path else STATE

    prev = None
    if sp.exists():
        try:
            prev = json.loads(sp.read_text(encoding="utf-8")).get("boot_time")
        except Exception:
            prev = None

    first_seen = prev is None
    rebooted = (prev is not None) and abs(boot - float(prev)) > 5.0
    now = time.time()

    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(
            json.dumps(
                {
                    "boot_time": boot,
                    "boot_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(boot)),
                    "last_check": now,
                    "uptime_s": round(now - boot),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    out = {
        "ok": True,
        "boot_time": boot,
        "uptime_s": round(now - boot),
        "first_seen": first_seen,
        "rebooted": rebooted,
        "prev_boot": prev,
    }

    if rebooted:
        # 1. Journaliser le reboot (evenement cle qui revit le lifecycle journal).
        try:
            from nokido_agent.app.forge_lifecycle_audit import record
            record(
                "reboot_detected",
                "system",
                f"boot_time {float(prev):.0f} -> {boot:.0f} (uptime reset)",
                prev_boot=float(prev),
                new_boot=boot,
            )
        except Exception:
            pass
        # 2. Reconcilier le registre superviseur vs la realite post-boot (dry-run :
        #    l'homeostat re-kill les fantomes a sa phase reconcile ; ici on OBSERVE).
        try:
            from nokido_agent.app.forge_port_reconcile import run_cycle as reconcile_cycle
            out["reconcile"] = reconcile_cycle(kill=False)
        except Exception as e:
            out["reconcile"] = {"ok": False, "err": str(e)[:120]}
        # 3. POST-MORTEM : le reboot seul ne dit RIEN. On demande a l'OS si l'arret
        #    precedent etait propre, et si non on joint la courbe de vitaux + les
        #    dernieres actions de cycle de vie dans un rapport. Cf _post_mortem.
        out["post_mortem"] = _post_mortem(boot)

    return out


def run_cycle() -> dict:
    """Alias homeostatique (convention des organes du tick)."""
    return check_reboot()
