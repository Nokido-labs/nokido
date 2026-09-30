#!/usr/bin/env python3
"""forge_hub_blackbox.py — la boite noire du hub. Elle survit a ce qu'elle observe.

Le hub est tombe 12 fois en trois jours (mesure 2026-08-14, silences dans
`sandbox/hub.log` : jusqu'a 3 h 20 d'affilee) et AUCUN diagnostic n'a pu etre
etabli. Raison structurelle, pas manque d'effort : tous les capteurs vivent
DANS le hub. `vitals_history.jsonl` s'interrompt a la seconde ou il meurt, donc
les seules minutes qui comptent sont precisement celles qui manquent. Les pics
RAM a 99,9 % qu'on y lit sont ceux du REDEMARRAGE, jamais ceux de l'agonie.

Ce processus n'appelle pas le hub, ne l'importe pas, ne partage rien avec lui.
Il echantillonne de l'exterieur et ecrit en append : quand le hub disparait,
les dernieres secondes restent.

Ce qu'il retient a l'instant de la disparition — c'est la seule chose qui
distingue une boite noire d'un journal ordinaire : le contexte AVANT
l'evenement, garde en anneau et vide sur disque au moment ou le PID s'eteint.

Prudence deliberee (incident du 2026-07-26 : une sonde d'echantillonnage a gele
la machine) : aucune sonde GPU (mesuree a 1562 ms), aucun subprocess, aucune
lecture de la base. psutil seul, 5 s d'intervalle, cout par tour de l'ordre de
la milliseconde.

Usage : lancer detache (run_job) ou en tache planifiee. S'arrete sur --once.
"""
from __future__ import annotations

import collections
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sandbox" / "hub_blackbox.jsonl"
INTERVALLE_S = 5.0
ANNEAU = 24                    # 2 minutes de contexte avant la mort
CAP_OCTETS = 20 * 1024 * 1024


def _port_ouvert(port: int = 8766, timeout: float = 0.4) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:  # muet-ok : sur le LOOPBACK un refus de connexion signifie
        # « personne n'ecoute », il n'y a pas de droit a demander ni de reseau a
        # traverser. C'est le seul capteur de ce module qui reste valide sous
        # cecite de cmdline, et il fonde le verdict HUB_DISPARU -- journaliser
        # ce cas attendu, toutes les 5 s pendant une panne, noierait l'evenement.
        return False
    finally:
        s.close()


def _process_hub(psutil):
    """Le process qui SERT le hub, identifie par sa ligne de commande.

    Par le nom seul on ne distingue pas deux `python.exe` — l'identite d'un
    processus est son role, jamais son PID (lecon 2026-08-04).

    Rend (process, aveugle). `aveugle=True` quand le compte n'a pas le droit de
    lire les lignes de commande : mesure du 2026-08-14 sous `LaForgeSbxOffline`,
    310 process sur 314 illisibles. Sans cette distinction, « process introuvable »
    et « interdit de regarder » s'ecrivent tous deux `null` — et une boite noire
    qui confond l'absence avec la cecite date de faux deces.
    """
    lisibles, total = 0, 0
    trouve = None
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        total += 1
        try:
            cl = " ".join(p.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):  # muet-ok : ce
            # silence-ci est deja COMPTE, pas avale -- le process n'incremente
            # pas `lisibles`, donc il pese dans le verdict `aveugle` rendu a
            # l'appelant. Journaliser 331 refus par tour, toutes les 5 s, est
            # exactement le bruit qui masquerait la mort qu'on observe.
            continue
        if cl:
            lisibles += 1
            if trouve is None and ("nokido_hub" in cl or "laforge_hub" in cl):
                trouve = p
    aveugle = total > 20 and lisibles <= max(2, total * 0.1)
    return trouve, aveugle


def echantillon(psutil) -> dict:
    vm = psutil.virtual_memory()
    d = {"ts": round(time.time(), 1), "ram_pct": vm.percent,
         "ram_dispo_gb": round(vm.available / 1e9, 2),
         "port8766": _port_ouvert()}
    # Le swap n'est PAS lisible sur cette machine : `PdhAddEnglishCounterW
    # failed, performance counters may be disabled`. Une sonde optionnelle qui
    # leve fait perdre l'echantillon ENTIER — c'est-a-dire exactement les
    # secondes qu'on cherchait. Elle s'isole et se declare absente.
    try:
        d["swap_pct"] = psutil.swap_memory().percent
    except Exception as e:  # noqa: BLE001
        d["swap_pct"] = None
        d["swap_aveugle"] = type(e).__name__
    p, aveugle = _process_hub(psutil)
    if p is None:
        # INDETERMINE n'est pas ABSENT : sans droit de lecture on ne conclut pas.
        d["hub"] = None
        d["process_indetermine"] = bool(aveugle)
        return d
    try:
        with p.oneshot():
            d["hub"] = {
                "pid": p.pid,
                "rss_gb": round(p.memory_info().rss / 1e9, 3),
                "threads": p.num_threads(),
                "handles": getattr(p, "num_handles", lambda: None)(),
                "cpu_pct": p.cpu_percent(interval=None),
                "age_s": round(time.time() - p.create_time()),
                "fds": len(p.open_files()) if hasattr(p, "open_files") else None,
            }
    except Exception as e:  # noqa: BLE001
        # Un capteur aveugle se NOMME : une cle absente se lirait comme un zero.
        d["hub"] = {"erreur": type(e).__name__}
    return d


def _ecrire(obj: dict) -> None:
    if OUT.exists() and OUT.stat().st_size > CAP_OCTETS:
        OUT.replace(OUT.with_suffix(".jsonl.1"))
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main() -> int:
    try:
        import psutil
    except ImportError:
        print("[blackbox] psutil absent — la boite noire ne peut pas observer")
        return 2

    OUT.parent.mkdir(parents=True, exist_ok=True)
    anneau: collections.deque = collections.deque(maxlen=ANNEAU)
    vivant_avant, pid_avant = None, None
    une_fois = "--once" in sys.argv
    print(f"[blackbox] observation externe toutes les {INTERVALLE_S} s -> {OUT}",
          flush=True)

    while True:
        e = echantillon(psutil)
        anneau.append(e)
        # Le PORT fonde le verdict : il reste observable meme sans droits sur les
        # process. Le RSS enrichit le diagnostic, il ne le conditionne pas.
        vivant = bool(e["port8766"])
        pid = (e["hub"] or {}).get("pid")

        if vivant_avant is True and not vivant:
            # L'INSTANT qui manquait : on vide le contexte precedent la mort.
            _ecrire({"ts": e["ts"], "EVENEMENT": "HUB_DISPARU",
                     "dernier_pid": pid_avant,
                     "ram_pct_au_deces": e["ram_pct"],
                     "contexte_avant": list(anneau)})
            print(f"[blackbox] HUB_DISPARU pid={pid_avant} ram={e['ram_pct']}%",
                  flush=True)
        elif vivant_avant is False and vivant:
            _ecrire({"ts": e["ts"], "EVENEMENT": "HUB_REVENU", "pid": pid})
        elif vivant and pid_avant and pid != pid_avant:
            # Redemarrage sans trou observable : le PID change, pas le service.
            _ecrire({"ts": e["ts"], "EVENEMENT": "HUB_REMPLACE",
                     "ancien_pid": pid_avant, "nouveau_pid": pid})
        else:
            _ecrire(e)

        vivant_avant = vivant
        if pid:
            pid_avant = pid
        if une_fois:
            return 0
        # BATTEMENT (2026-08-25). Cet observateur sortait « VIVANT MAIS DENERVE » a
        # l'audit et « mort silencieuse » a l'audit de regulation : il observait le hub
        # sans que personne ne puisse observer QU'IL observe. Un organe qui surveille
        # doit lui-meme etre surveillable, sinon sa disparition ne se voit qu'au trou
        # qu'elle laisse dans les donnees — c'est-a-dire trop tard.
        try:
            _hb = Path(__file__).resolve().parent.parent / "sandbox" / "hub_blackbox.heartbeat"
            _hb.parent.mkdir(parents=True, exist_ok=True)
            _hb.write_text(json.dumps({"ts": time.time(), "pid": os.getpid()}),
                           encoding="utf-8")
        except Exception as _he:  # noqa: BLE001
            print("[blackbox] heartbeat NON ecrit (%s) — cet organe redevient "
                  "invisible au contrat" % type(_he).__name__, flush=True)
        time.sleep(INTERVALLE_S)


if __name__ == "__main__":
    sys.exit(main())
