# -*- coding: utf-8 -*-
"""Sonde d'E/S du HUB -- owner 4/11 (« le disque C sature en E/S » ; « OUI » a la sonde).

Mesure job_6a31aad7ac58 : le hub (NokidoMCP, :8766) lit 61-65 Mo/s a ~15 000 ops/s (pages SQLite de 4 Ko) en
RAFALES, hors de toute requete (sandbox/workspace/hub_io_par_requete.jsonl muet) ; sous le compte des jobs,
open_files/memory_maps sont illisibles. Lancee par `run action=trusted_script path=tools/forge_hub_io_probe.py`.

LECTURE SEULE. Echantillonne les octets lus du hub chaque seconde pendant `--duree` s ; a chaque RAFALE (debit >
`--seuil` Mo/s) : gros fichiers ouverts, fils les plus actifs (temps CPU), et pile Python par `py-spy dump` si
l'outil est present. Ce qui ne peut pas etre lu est ILLISIBLE (avec la raison), jamais vide. Rapport JSON :
sandbox/workspace/hub_io_probe_<horodatage>.json. NR tests/nr/test_hub_io_probe_nr.py."""
__FORGE_COLOR__ = "proprioception/disque : sonde des rafales de lecture du hub (fichier, fils, pile)"

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from forge_db_path import racine_donnees  # noqa: E402

RACINE = racine_donnees()
PORT_HUB = 8766


def rafales(echantillons, seuil_mo_s: float = 20.0) -> list:
    """[(t_debut, t_fin)] des intervalles ou le debit de lecture depasse le seuil ; echantillons = [(t, octets_cumules)]."""
    out, debut = [], None
    for (t0, o0), (t1, o1) in zip(echantillons, echantillons[1:]):
        debit = (o1 - o0) / max(t1 - t0, 1e-9) / 1e6
        if debit > seuil_mo_s:
            debut = t0 if debut is None else debut
            fin = t1
        elif debut is not None:
            out.append((debut, fin))
            debut = None
    if debut is not None:
        out.append((debut, fin))
    return out


def lire_ou_illisible(fn) -> dict:
    try:
        return {"etat": "LU", "valeur": fn()}
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "raison": "%s: %s" % (type(e).__name__, e)}


def gros_fichiers(fichiers, n: int = 10) -> list:
    return sorted(fichiers, key=lambda f: -(f[1] if isinstance(f[1], (int, float)) else -1))[:n]


def _hub():
    import psutil
    for c in psutil.net_connections(kind="tcp"):
        if c.laddr and c.laddr.port == PORT_HUB and c.status == psutil.CONN_LISTEN and c.pid:
            return psutil.Process(c.pid)
    return None


_LECTURE = re.compile(r"\b(execute\w*|fetch\w*|read\w*|recv\w*|executescript|getsize|scandir|iterdump)\b")


def resumer_piles(lignes, n: int = 15) -> dict:
    """Agrege la sortie brute de py-spy (`frame;frame;frame COMPTE`) : les piles qui LISENT d'abord."""
    total, illisibles, lecteurs = 0, 0, []
    for brut in lignes:
        pile, _, compte = str(brut).rstrip().rpartition(" ")
        if not pile or not compte.isdigit():
            illisibles += 1
            continue
        total += int(compte)
        feuille = ";".join(pile.split(";")[-3:])
        if _LECTURE.search(feuille):
            lecteurs.append({"n": int(compte), "pile": ";".join(pile.split(";")[-8:])})
    lecteurs.sort(key=lambda x: -x["n"])
    return {"echantillons": total, "illisibles": illisibles, "lecteurs": lecteurs[:n]}


def _py_spy():
    """Le PATH d'abord, puis sandbox/workspace/outils, lisible par le compte de confiance (LAFORGE_PY_SPY le remplace).
    Mesure 4/11 : installe sous C:/tmp par un job, l'exe est invisible a LaForgeTrusted."""
    candidats = [os.environ.get("LAFORGE_PY_SPY"), shutil.which("py-spy"),
                 str(RACINE / "sandbox" / "workspace" / "outils" / "py-spy.exe")]
    return next((c for c in candidats if c and os.path.exists(c)), None)


def enregistrer(pid: int, duree_s: int, frequence: int = 50) -> dict:
    """Echantillonne TOUS les fils du hub, sans le mettre en pause (--nonblocking : le hub sert pendant la mesure, au
    prix de quelques piles incoherentes, comptees comme illisibles ou rares)."""
    exe = _py_spy()
    if not exe:
        return {"etat": "ILLISIBLE", "raison": "py-spy absent (PATH, LAFORGE_PY_SPY, dossier dedie)"}
    sortie = RACINE / "sandbox" / "workspace" / ("hub_piles_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
    r = subprocess.run([exe, "record", "--pid", str(pid), "--duration", str(int(duree_s)), "--rate", str(int(frequence)),
                        "--format", "raw", "--output", str(sortie), "--nonblocking", "--idle", "--threads"],
                       capture_output=True, text=True, errors="replace", timeout=int(duree_s) + 30)
    if not sortie.exists():
        return {"etat": "ILLISIBLE", "raison": "py-spy rc=%s : %s" % (r.returncode, (r.stderr or r.stdout)[-400:])}
    res = resumer_piles(sortie.read_text(encoding="utf-8", errors="replace").splitlines())
    res.update(etat="LU", fichier=str(sortie), rc=r.returncode)
    return res


def _instantane(p) -> dict:
    def _fichiers():
        out = []
        for f in p.open_files():
            try:
                out.append((f.path, os.path.getsize(f.path)))
            except OSError:
                out.append((f.path, "taille ILLISIBLE"))
        return gros_fichiers(out, 12)

    def _fils():
        return sorted(([t.id, round(t.user_time + t.system_time, 2)] for t in p.threads()), key=lambda x: -x[1])[:8]

    def _pile():
        exe = shutil.which("py-spy")
        if not exe:
            raise FileNotFoundError("py-spy absent (pip install py-spy) : pile Python non lisible de l'exterieur")
        r = subprocess.run([exe, "dump", "--pid", str(p.pid)], capture_output=True, text=True, timeout=30,
                           errors="replace")
        if r.returncode != 0:
            raise RuntimeError("py-spy rc=%s : %s" % (r.returncode, (r.stderr or r.stdout)[-300:]))
        return r.stdout[-12000:]
    return {"ts": time.strftime("%H:%M:%S"), "fichiers": lire_ou_illisible(_fichiers),
            "fils_cpu": lire_ou_illisible(_fils), "pile": lire_ou_illisible(_pile)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--duree", type=float, default=120.0)
    ap.add_argument("--seuil", type=float, default=20.0)
    ap.add_argument("--max-instantanes", type=int, default=3)
    ap.add_argument("--enregistrer", type=int, default=0, help="secondes de piles py-spy du hub, puis fin")
    a = ap.parse_args(argv)
    import psutil
    p = _hub()
    if p is None:
        print(json.dumps({"etat": "ILLISIBLE", "raison": "aucun processus n'ecoute :%d" % PORT_HUB}))
        return 1
    if a.enregistrer:
        print(json.dumps(enregistrer(p.pid, a.enregistrer), ensure_ascii=False, indent=1)[:9000])
        return 0
    rapport = {"hub_pid": p.pid, "compte_sonde": os.environ.get("USERNAME"),
               "compte_hub": lire_ou_illisible(p.username), "echantillons": [], "instantanes": []}
    t0 = time.time()
    prec = None
    while time.time() - t0 < a.duree:
        try:
            lu = p.io_counters().read_bytes
        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            rapport["echantillons_illisibles"] = type(e).__name__
            break
        t = round(time.time() - t0, 1)
        rapport["echantillons"].append((t, lu))
        if prec and (lu - prec[1]) / max(t - prec[0], 1e-9) / 1e6 > a.seuil \
                and len(rapport["instantanes"]) < a.max_instantanes:
            inst = _instantane(p)
            inst["debit_mo_s"] = round((lu - prec[1]) / max(t - prec[0], 1e-9) / 1e6, 1)
            rapport["instantanes"].append(inst)
        prec = (t, lu)
        time.sleep(1.0)
    rapport["rafales"] = rafales(rapport["echantillons"], a.seuil)
    sortie = RACINE / "sandbox" / "workspace" / ("hub_io_probe_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    resume = {"hub_pid": p.pid, "compte_hub": rapport["compte_hub"], "rafales": rapport["rafales"],
              "instantanes": [{"ts": i["ts"], "debit_mo_s": i["debit_mo_s"],
                               "fichiers": i["fichiers"].get("valeur", i["fichiers"])[:5]
                               if isinstance(i["fichiers"].get("valeur"), list) else i["fichiers"],
                               "pile": (i["pile"].get("valeur") or "")[:3000] if i["pile"]["etat"] == "LU"
                               else i["pile"]} for i in rapport["instantanes"]],
              "rapport": str(sortie)}
    print(json.dumps(resume, ensure_ascii=False, indent=1, default=str)[:9000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
