# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/aer-evenementiel"
BANC DE SPARSITE AER — chiffrer le gain evenementiel sur l'historique REEL.

Rejoue la serie `sandbox/vitals_history.jsonl` en boucle SHADOW : chaque mesure passe
dans l'ANCIEN formateur (JSON continu) ET dans le NOUVEAU routeur AER (delta quantifie,
paquets de 8 octets). Une seule passe donne le delta exact avant/apres.

TROIS AXES, et le troisieme est le plus important
=================================================
1. TRANSIT   : sparsite effective, octets/s, nombre d'ecritures (batching).
2. CPU       : microsecondes de (de)serialisation par tic, part des evenements de
               controle — un keepalive trop bavard annulerait le gain.
3. FIDELITE  : l'AER est VOLONTAIREMENT lossy. Un gain de bande passante qui detruit
               le signal d'alerte serait une regression deguisee en optimisation.
               On mesure donc l'erreur de reconstruction ET la latence de detection
               de detresse sur les episodes REELS.

CE QUE CE BANC NE MESURE PAS, ET LE DIT
=======================================
Il chronometre l'ENCODAGE, pas des syscalls reels : rien n'est ecrit sur une socket
ici. Le nombre d'ecritures rapporte est donc un nombre d'APPELS QU'IL FAUDRAIT FAIRE
(un par lot non vide), pas une mesure kernel. Annoncer une reduction de context
switches sans avoir touche le kernel serait une extrapolation, pas un resultat.

    LAFORGE_PYTHON tools/forge_aer_sparsity_bench.py [--keepalive 300] [--json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_aer as AER  # noqa: E402

SERIE = ROOT / "sandbox" / "vitals_history.jsonl"
SORTIE = ROOT / "sandbox" / "aer_sparsity_bench.json"
# Verite terrain EMPRUNTEE au corps, jamais inventee : c'est le seuil de detresse de
# forge_resource_manager, le meme que celui du banc neuromorphique du 2026-08-04.
DETRESSE_LIBRE_GB = 1.5


def _aplatir(row: dict) -> dict:
    """Ligne de serie -> {canal: valeur|None}. La carte des services est ouverte en
    canaux nommes ; `None` reste `None` (illisible), il ne devient jamais 0."""
    out = {}
    for k, v in row.items():
        if k in ("ts", "top"):
            continue
        if k == "s" and isinstance(v, dict):
            for nom, paire in v.items():
                if isinstance(paire, list):
                    out["svc.%s.go" % nom] = paire[0] if len(paire) > 0 else None
                    out["svc.%s.ratio" % nom] = paire[1] if len(paire) > 1 else None
            continue
        out[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gain de l'encodage AER, mesure sur l'historique")
    ap.add_argument("--keepalive", type=float, default=AER.KEEPALIVE_S)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    AER.KEEPALIVE_S = a.keepalive

    if not SERIE.exists():
        print("[banc] serie absente : %s" % SERIE)
        return 1
    lignes = SERIE.read_text(encoding="utf-8", errors="replace").splitlines()

    enc = AER.Encodeur()
    # Le decodeur LIVRE avec le codec, pas une reconstruction maison : la premiere
    # version du banc re-implementait le decodage et divergeait de l'encodeur, ce qui
    # affichait une MSE de 1,8e10 sur `ctx`. L'instrument etait faux, pas le format.
    dec = AER.Decodeur()
    n_tics = n_evts = n_ctrl = n_keepalive = 0
    octets_ancien = octets_aer = 0
    ecritures_ancien = ecritures_aer = 0
    us_ancien = us_aer = 0.0
    canaux_vus: set = set()
    illisibles = 0
    # reconstruction : valeur reconstruite par canal, et erreurs par canal
    recon: dict = {}
    err: dict = {}
    # detresse : instants ou la verite terrain bascule, et instants ou l'AER tire
    episodes: list = []
    tirs_ram: list = []
    prec_detresse = False
    t0 = None

    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            row = json.loads(ligne)
        except Exception:  # noqa: BLE001
            continue
        ts = float(row.get("ts") or 0)
        if not ts:
            continue
        t0 = t0 if t0 is not None else ts
        n_tics += 1
        ech = _aplatir(row)
        canaux_vus.update(ech)
        illisibles += sum(1 for v in ech.values() if v is None)

        # --- ANCIEN : on re-serialise TOUT l'etat a chaque tic
        d = time.perf_counter()
        brut = json.dumps(row, ensure_ascii=False).encode("utf-8")
        us_ancien += (time.perf_counter() - d) * 1e6
        octets_ancien += len(brut)
        ecritures_ancien += 1

        # --- NOUVEAU : delta quantifie + paquets de 8 octets
        d = time.perf_counter()
        evts = enc.encode(ech, ts)
        buf = AER.empaqueter(evts)
        us_aer += (time.perf_counter() - d) * 1e6
        octets_aer += len(buf)
        if evts:
            ecritures_aer += 1     # un lot non vide = une ecriture socket
        n_evts += len(evts)
        for e_ in evts:
            if isinstance(e_, tuple) and len(e_) == 3 and e_[0] == "VAL":
                continue   # trame de continuation : compte en octets, pas en spike
            (_t, sid, pol, mag) = e_
            if pol == 0:
                n_ctrl += 1
                if mag == AER.CTRL_KEEPALIVE:
                    n_keepalive += 1

        # --- FIDELITE : reconstruire depuis les evenements SEULS, via le decodeur
        for evt in evts:
            dec.applique(evt)
        for canal, val in ech.items():
            if val is None:
                continue
            r = dec.lire(AER.src_id(canal))
            if r is None:
                continue
            recon[canal] = r
            e = float(val) - r
            err.setdefault(canal, []).append(e * e)

        # --- LATENCE D'ALERTE : verite terrain = seuil de detresse du corps
        libre = row.get("ram_free_gb")
        det = libre is not None and 0.0 < float(libre) < DETRESSE_LIBRE_GB
        if det and not prec_detresse:
            episodes.append(ts)
        prec_detresse = det
        if any(e_[1] in (AER.SRC["ram_free_gb"], AER.SRC["ram_pct"]) and e_[2] != 0
               for e_ in evts
               if not (isinstance(e_, tuple) and len(e_) == 3 and e_[0] == "VAL")):
            tirs_ram.append(ts)

    duree_s = (float(json.loads(lignes[-1])["ts"]) - t0) if t0 else 0.0
    n_canaux = len(canaux_vus)
    emplacements = n_canaux * n_tics
    sparsite = 1.0 - (n_evts / emplacements) if emplacements else 0.0

    # latence : pour chaque episode, l'ecart au tir AER le plus proche AVANT ou A
    # l'instant de l'episode. Un tir POSTERIEUR serait un retard, on le compte tel quel.
    latences = []
    for e in episodes:
        av = [t for t in tirs_ram if t <= e]
        if av:
            latences.append(e - av[-1])
    mse = {c: statistics.fmean(v) for c, v in err.items() if v}

    rapport = {
        "echantillons": n_tics,
        "duree_jours": round(duree_s / 86400.0, 2),
        "canaux": n_canaux,
        "transit": {
            "evenements_aer": n_evts,
            "emplacements_possibles": emplacements,
            "sparsite_pct": round(100.0 * sparsite, 2),
            "octets_ancien": octets_ancien,
            "octets_aer": octets_aer,
            "reduction_octets_pct": round(100.0 * (1 - octets_aer / octets_ancien), 2)
            if octets_ancien else None,
            "octets_par_s_ancien": round(octets_ancien / duree_s, 2) if duree_s else None,
            "octets_par_s_aer": round(octets_aer / duree_s, 2) if duree_s else None,
            "ecritures_ancien": ecritures_ancien,
            "ecritures_aer": ecritures_aer,
            "reduction_ecritures_pct": round(100.0 * (1 - ecritures_aer / ecritures_ancien), 2)
            if ecritures_ancien else None,
            "_note": "les ecritures sont des appels QU'IL FAUDRAIT faire (un par lot "
                     "non vide) : rien n'est ecrit sur une socket ici",
        },
        "cpu": {
            "us_par_tic_ancien": round(us_ancien / n_tics, 2) if n_tics else None,
            "us_par_tic_aer": round(us_aer / n_tics, 2) if n_tics else None,
            "evenements_controle": n_ctrl,
            "dont_keepalive": n_keepalive,
            "part_controle_pct": round(100.0 * n_ctrl / n_evts, 2) if n_evts else None,
            "keepalive_s": a.keepalive,
        },
        "fidelite": {
            "mse_median": round(statistics.median(list(mse.values())), 6) if mse else None,
            "pires_canaux": [{"canal": c, "mse": round(v, 4)}
                             for c, v in sorted(mse.items(), key=lambda kv: -kv[1])[:6]],
            "episodes_detresse": len(episodes),
            "episodes_precedes_d_un_tir": len(latences),
            "latence_mediane_s": round(statistics.median(latences), 1) if latences else None,
            "_note": "verite terrain = ram_free_gb < %.1f Go, seuil de detresse de "
                     "forge_resource_manager (emprunte au corps, pas invente)"
                     % DETRESSE_LIBRE_GB,
        },
        "lectures_illisibles": illisibles,
    }
    try:
        SORTIE.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    if a.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0
    t, c, f = rapport["transit"], rapport["cpu"], rapport["fidelite"]
    print("=== Banc de sparsite AER — %d mesures / %.2f jours / %d canaux ==="
          % (n_tics, rapport["duree_jours"], n_canaux))
    print("TRANSIT  sparsite %.2f%% | %d evenements pour %d emplacements"
          % (t["sparsite_pct"], t["evenements_aer"], t["emplacements_possibles"]))
    print("         octets %s -> %s (%s%% de moins) | %s -> %s octets/s"
          % (t["octets_ancien"], t["octets_aer"], t["reduction_octets_pct"],
             t["octets_par_s_ancien"], t["octets_par_s_aer"]))
    print("         ecritures %s -> %s (%s%% de moins)"
          % (t["ecritures_ancien"], t["ecritures_aer"], t["reduction_ecritures_pct"]))
    print("CPU      %.2f us/tic -> %.2f us/tic | controle %s%% dont %d keepalives"
          % (c["us_par_tic_ancien"], c["us_par_tic_aer"], c["part_controle_pct"],
             c["dont_keepalive"]))
    print("FIDELITE MSE mediane %s | %d/%d episodes de detresse precedes d'un tir, "
          "latence mediane %ss"
          % (f["mse_median"], f["episodes_precedes_d_un_tir"], f["episodes_detresse"],
             f["latence_mediane_s"]))
    for p in f["pires_canaux"]:
        print("         pire: %-22s MSE %s" % (p["canal"], p["mse"]))
    print("\nrapport: %s" % SORTIE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
