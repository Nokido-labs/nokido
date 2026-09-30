#!/usr/bin/env python
"""forge_llama_reconcile.py — Reconcilie les llama-server DUPLIQUES.

PROPRIOCEPTION -> REGULATION COGNITIVE (owner 2026-07-23). Un port gere (8099 embed,
8100 reranker) doit avoir UN listener = le pid REVENDIQUE par le superviseur. Tout
AUTRE listener sur ce port = enfant perdu du registre (zombie-gap au boot, race de
generation) -> terminate. La legitimite se DEMANDE au superviseur (registre), JAMAIS
deduite du RSS/port (le RSS ment : orphelin 665Mo vs legitime 303Mo, mesure 07-16).

Args : --list (diagnostic, ne tue pas) | <rien> (reconcilie).
Doit tourner en COMPTE avec droit de terminate sur les enfants du superviseur
(trusted_script / service). Le sandbox = AccessDenied.
"""
from __future__ import annotations
import json
import sys
import urllib.request

PORT_SERVICE = {8099: "NokidoLlamaEmbed", 8100: "NokidoLlamaReranker"}


def _claimed() -> dict:
    """pid revendique par le superviseur, par nom de service."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=8) as r:
            svc = json.loads(r.read()).get("services", {})
        return {n: i.get("pid") for n, i in svc.items() if i.get("status") == "running"}
    except Exception as e:  # noqa: BLE001
        return {"__err": str(e)[:100]}


def main() -> int:
    import psutil
    do_kill = "--list" not in sys.argv
    claimed = _claimed()
    listeners: dict = {}
    for c in psutil.net_connections("tcp"):
        if (c.status == "LISTEN" and c.pid and c.laddr
                and c.laddr.port in PORT_SERVICE):
            listeners.setdefault(c.laddr.port, []).append(c.pid)
    report = {"claimed": {}, "zombies": [], "killed": [], "kill_mode": do_kill}
    for port, svc_name in PORT_SERVICE.items():
        legit = claimed.get(svc_name)
        report["claimed"][port] = {"service": svc_name, "legit_pid": legit,
                                   "listeners": listeners.get(port, [])}
        if legit is None:
            continue  # superviseur ne revendique pas -> on ne devine pas, on ne tue pas
        for pid in listeners.get(port, []):
            if pid == legit:
                continue
            z = {"port": port, "zombie_pid": pid, "legit_pid": legit, "service": svc_name}
            report["zombies"].append(z)
            if do_kill:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except Exception:  # noqa: BLE001
                        p.kill()
                    report["killed"].append(pid)
                except Exception as e:  # noqa: BLE001
                    z["err"] = str(e)[:100]
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
