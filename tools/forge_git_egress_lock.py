"""
FORGE INTELLIGENCE — forge_git_egress_lock [GREEN]  (WinDivert v2, SCAFFOLD)
============================================================================
Verrou EGRESS RÉSEAU du gate git souverain. Intercepte le sortant TCP 443/22,
corrèle le PID, et n'autorise que le process gate (ou les git/ssh qu'il a lui-
même lancés après scan). Rend le gate INVIOLABLE — vs `git push --no-verify`
qui contourne le hook pre-push (couche v1).

SÉCURITÉ (par design) :
- défaut = **DRY-RUN** : observe + log ce qui SERAIT bloqué, ne drop JAMAIS.
- `--enforce` = drop réel des sorties non autorisées.
- **fail-open** : toute exception -> reinject (jamais de black-hole réseau).
- WinDivert ne filtre QUE tant que le handle est ouvert : daemon arrêté/planté
  = trafic 100% normal (pas de règle persistante).

ACTIVATION (changement système, à faire par l'owner) :
  pip install pydivert        # binding Python du driver WinDivert (pré-signé)
  # lancer en ADMINISTRATEUR (1er load du driver) :
  LAFORGE_PYTHON tools/forge_git_egress_lock.py            # dry-run (sûr)
  LAFORGE_PYTHON tools/forge_git_egress_lock.py --enforce  # verrou réel

INTÉGRATION gate (TODO v2) : pour l'enforcement, forge_git_egress doit exécuter
le push LUI-MÊME (après scan) en écrivant son PID dans ALLOW_PIDFILE, afin que
ce verrou autorise SES git/ssh et bloque tout autre. (En v1 le gate est un hook
pre-push = parent git, modèle inversé ; bascule gate-as-executor requise.)

Anti-dup (CLAUDE.md §3) : aucun module n'intercepte l'egress réseau. forge_web_
egress = chokepoint HTTP applicatif (pas driver réseau) ; SemanticFirewall =
contenu LLM. Domaine neuf justifié.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import argparse
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("forge_git_egress_lock")

WATCH_PORTS = {443, 22}  # git HTTPS + git SSH
GIT_PROCS = {"git.exe", "ssh.exe", "git-remote-https.exe", "git-remote-http.exe"}
ALLOW_PIDFILE = Path(os.environ.get(
    "LAFORGE_EGRESS_ALLOW_PIDFILE", r"C:\tmp\forge_git_egress.allow"))


def _pydivert():
    try:
        import pydivert
        return pydivert
    except Exception:
        return None


def available() -> bool:
    return _pydivert() is not None


def _pid_for(src_addr: str, src_port: int) -> int | None:
    """Corrèle (laddr, lport) -> PID via la table TCP (psutil)."""
    try:
        import psutil
    except Exception:
        return None
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == src_port and \
                    (not src_addr or c.laddr.ip in (src_addr, "0.0.0.0", "::")):
                return c.pid
    except Exception:
        return None
    return None


def _proc_name(pid: int | None) -> str:
    if pid is None:
        return ""
    try:
        import psutil
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def _allowed_pids() -> set[int]:
    """PIDs autorisés (le gate + ses enfants). Le gate écrit son PID dans
    ALLOW_PIDFILE pendant un push qu'il a scanné+lancé."""
    pids: set[int] = set()
    if ALLOW_PIDFILE.exists():
        try:
            pids = {int(x) for x in ALLOW_PIDFILE.read_text().split() if x.strip().isdigit()}
        except Exception:
            pids = set()
    try:
        import psutil
        for p in list(pids):
            try:
                for ch in psutil.Process(p).children(recursive=True):
                    pids.add(ch.pid)
            except Exception:
                pass
    except Exception:
        pass
    return pids


def run(enforce: bool = False, duration: float = 0.0) -> dict:
    """Boucle d'interception. DRY-RUN par défaut. fail-open. Admin requis."""
    pd = _pydivert()
    if pd is None:
        raise RuntimeError("pydivert absent : `pip install pydivert` puis lancer en ADMIN")
    flt = "outbound and tcp and (tcp.DstPort == 443 or tcp.DstPort == 22)"
    log.warning("egress_lock %s sur 443/22 — Ctrl-C = stop (trafic normal)",
                "ENFORCE" if enforce else "DRY-RUN")
    t0 = time.monotonic()
    allowed = blocked = 0
    with pd.WinDivert(flt) as w:
        for pkt in w:
            try:
                allow = True
                if getattr(pkt, "tcp", None) and pkt.tcp.syn and not pkt.tcp.ack:
                    pid = _pid_for(str(pkt.src_addr), pkt.src_port)
                    name = _proc_name(pid)
                    if name in GIT_PROCS and pid not in _allowed_pids():
                        allow = False
                        log.warning("egress %s pid=%s %s -> %s:%s",
                                    "BLOCK" if enforce else "WOULD-BLOCK",
                                    pid, name, pkt.dst_addr, pkt.dst_port)
                if allow or not enforce:
                    w.send(pkt)
                    allowed += 1
                else:
                    blocked += 1  # drop = ne pas reinject
            except Exception as e:  # fail-open absolu
                log.debug("egress_lock lookup erreur -> reinject (fail-open): %s", e)
                try:
                    w.send(pkt)
                except Exception:
                    pass
            if duration and (time.monotonic() - t0) > duration:
                break
    return {"allowed": allowed, "blocked": blocked, "enforce": enforce}


def _selftest() -> int:
    print(f"pydivert dispo : {available()}  (sinon: pip install pydivert)")
    try:
        import psutil
        n = len(psutil.net_connections(kind="tcp"))
        print(f"psutil OK : {n} connexions TCP visibles (corrélation PID possible)")
    except Exception as e:
        print(f"psutil KO : {e}")
    print(f"ALLOW_PIDFILE : {ALLOW_PIDFILE} (exists={ALLOW_PIDFILE.exists()})")
    print("filtre WinDivert : outbound and tcp and (DstPort 443 or 22)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="WinDivert egress lock (gate git souverain)")
    ap.add_argument("--enforce", action="store_true", help="drop réel (défaut=dry-run)")
    ap.add_argument("--duration", type=float, default=0.0, help="secondes (0=infini)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    res = run(enforce=a.enforce, duration=a.duration)
    print(res)
    raise SystemExit(0)
