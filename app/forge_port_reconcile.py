"""Termine les processus qui ecoutent un port revendique par le superviseur sans etre
le pid revendique ni l'un de ses descendants.

Entree publique : run_cycle(kill=True) rend un dict (zombies, reconciled, skipped) ;
en CLI, --list fait un passage a blanc sans rien tuer. SUPERVISOR donne l'URL lue.
Lit http://127.0.0.1:8765/supervisor/status et les listeners TCP via psutil ;
s'abstient sur un port ou aucun listener legitime n'est present (registre stale).
Effet de bord : terminate puis kill (apres 5 s) des pids juges fantomes.
Utilise par forge_homeostasis_orchestrator, forge_reboot_sentinel et
forge_self_awareness (kill=False) ; forge_resource_manager et
forge_sensor_fusion_probe reprennent _supervisor_ports et _is_descendant.
"""
from __future__ import annotations

__FORGE_COLOR__ = "vegetatif/monitor : proprioception des ports, reconcilier registre et reel"  # organe declare le 2026-09-06 (audit de raccordement)

# -*- coding: utf-8 -*-
"""
forge_port_reconcile.py — Proprioception generalisee a TOUS les organes (owner 2026-07-23).

Nokido = organisme vivant qui se regule seul. Un port REVENDIQUE par le superviseur
doit avoir UN listener = le pid revendique. Tout AUTRE process qui ecoute ce port
(le legit etant CONFIRME present) = enfant perdu du registre au boot (zombie-gap,
race de generation) -> terminate. Il gaspille de la RAM et sert un port fantome.

DOCTRINE (heritee de forge_llama_keeper) :
- La legitimite se DEMANDE au superviseur (registre), JAMAIS deduite du RSS/port
  (l'orphelin faisait 665Mo, le legitime 303Mo, mesure 07-16).
- GARDE 1 : on ne kill QUE si le pid revendique est LUI-MEME en ecoute sur le port.
  Sinon le registre est peut-etre stale (service en cours de restart) -> ne pas
  deviner, ne pas tuer le vrai nouveau process.
- GARDE 2 : on ne tue pas un worker FORK du legit (ppid == legit).
- Le process appelant doit avoir le droit de terminate les enfants du superviseur
  (compte service via l'orchestrateur homeostatique / le keeper). Trusted/sandbox =
  AccessDenied (mesure 07-23).

Usage : import run_cycle (phase homeostatique) OU CLI `--list` (dry-run).
"""
import json
import urllib.request

SUPERVISOR = "http://127.0.0.1:8765/supervisor/status"


def _supervisor_ports() -> dict:
    """{port: (service, claimed_pid)} pour les services RUNNING dotes d'un port."""
    out: dict = {}
    try:
        with urllib.request.urlopen(SUPERVISOR, timeout=4) as r:
            svc = json.loads(r.read()).get("services", {})
        for n, i in svc.items():
            port = i.get("port")
            if i.get("status") == "running" and port and i.get("pid"):
                out[int(port)] = (n, int(i["pid"]))
    except Exception:
        pass
    return out


def _is_descendant(pid: int, ancestor: int, max_depth: int = 8) -> bool:
    """pid descend-il de ancestor via la chaine ppid ? Resout la launcher-indirection :
    le superviseur tracke le WRAPPER, le vrai serveur qui bind le port est son enfant
    (ou petit-enfant). Le ppid se lit sans ACL. Borne anti-boucle."""
    import psutil
    cur = pid
    for _ in range(max_depth):
        try:
            pp = psutil.Process(cur).ppid()
        except Exception:  # noqa: BLE001
            return False
        if pp == ancestor:
            return True
        if pp <= 0 or pp == cur:
            return False
        cur = pp
    return False


def run_cycle(kill: bool = True) -> dict:
    """Reconcilie les listeners fantomes de TOUS les ports geres. Retour type organe."""
    import psutil

    claimed = _supervisor_ports()
    if not claimed:
        return {"ok": False, "reason": "superviseur injoignable", "reconciled": []}

    listeners: dict = {}
    try:
        for c in psutil.net_connections("tcp"):
            if (c.status == "LISTEN" and c.pid and c.laddr
                    and c.laddr.port in claimed):
                listeners.setdefault(c.laddr.port, set()).add(c.pid)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"net_connections: {e}", "reconciled": []}

    reconciled, zombies, skipped = [], [], []
    for port, (name, legit) in claimed.items():
        pids = listeners.get(port, set())
        if not pids:
            continue
        # Listener LEGIT = le pid REVENDIQUE ou un de ses DESCENDANTS (launcher-indirection :
        # le superviseur tracke le wrapper, le vrai serveur qui bind est son enfant).
        legit_set = {p for p in pids if p == legit or _is_descendant(p, legit)}
        if not legit_set:
            # GARDE 1 : aucun listener legitime (ni revendique ni descendant) -> registre
            # stale (service en restart ?) -> on s'abstient, on ne devine pas.
            skipped.append({"port": port, "service": name,
                            "reason": "aucun listener legitime (revendique/descendant absent)",
                            "listeners": sorted(pids)})
            continue
        for pid in pids:
            if pid in legit_set:
                continue  # GARDE 2 : le legit et ses descendants/forks sont intouchables
            # zombie : ecoute le port mais n'est NI le revendique NI un de ses descendants
            z = {"port": port, "service": name, "zombie_pid": pid, "legit_pid": legit}
            zombies.append(z)
            if kill:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except Exception:  # noqa: BLE001
                        p.kill()
                    reconciled.append(pid)
                except Exception as e:  # noqa: BLE001
                    z["err"] = str(e)[:100]
    return {"ok": True, "n_ports": len(claimed), "zombies": zombies,
            "reconciled": reconciled, "skipped": skipped}


if __name__ == "__main__":
    import sys

    print(json.dumps(run_cycle(kill="--list" not in sys.argv), ensure_ascii=False, indent=1))
