#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/bench/mesure_profil_client.py — Protocole de mesure du profil « client + SSoT ».

Mesure l'empreinte disque, le temps d'installation, la latence de demarrage
et l'empreinte memoire (RSS au repos apres 60s) d'un venv dedie au profil « client + SSoT ».

Le profil client comprend :
  - Paquet : nokido-agent[hub,rag] (ou requirements minimaux client+SSoT)
  - Hub : tools/nokido_hub.py ou point d'entree nokido-hub sur un port LIBRE (ex: 8798).

Dependances : stdlib + psutil.
Aucune dependance externe lourde requise pour piloter le banc.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


def trouver_port_libre(port_depart: int = 8795, max_essais: int = 50) -> int:
    """Trouve un port TCP local non utilise."""
    for p in range(port_depart, port_depart + max_essais):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue  # muet-ok : port occupe, on essaie le suivant (c'est la recherche elle-meme)
    raise RuntimeError(f"Aucun port libre trouve entre {port_depart} et {port_depart + max_essais}")


def calculer_taille_repertoire_mo(chemin: Path) -> float:
    """Calcule la taille totale d'un repertoire en Mo."""
    taille_octets, illisibles = 0, 0
    for root, _, files in os.walk(chemin):
        for f in files:
            fp = os.path.join(root, f)
            try:
                taille_octets += os.path.getsize(fp)
            except OSError:
                illisibles += 1
    if illisibles:
        print(f"  taille disque : {illisibles} fichier(s) ILLISIBLE(S), non comptes (sous-estimation)")
    return taille_octets / (1024 * 1024)


def creer_venv(dossier_venv: Path) -> Path:
    """Cree un venv Python neuf et retourne le chemin de son executable python."""
    cmd = [sys.executable, "-m", "venv", str(dossier_venv)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace")
    if sys.platform == "win32":
        py_exe = dossier_venv / "Scripts" / "python.exe"
    else:
        py_exe = dossier_venv / "bin" / "python"
    return py_exe


def copier_depot(depot_root: Path, dest: Path) -> Path:
    """Copie ISOLEE du depot (git archive HEAD) : la mesure n'ecrit ni dans l'arbre de travail (egg-info d'un
    `pip install -e`) ni dans son sandbox/ (bases, battements) -- le hub de mesure a son propre dossier (30/10)."""
    import io
    import tarfile

    brut = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(depot_root), "archive", "--format=tar", "HEAD"],
                          check=True, capture_output=True).stdout
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(brut)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def env_isole(tmpdir: Path, port: int) -> dict:
    """Environnement du hub de mesure : base RAG JETABLE (LAFORGE_DB, jamais la base du corps), donnees sous tmpdir."""
    import sqlite3

    stub = tmpdir / "rag_jetable.db"
    sqlite3.connect(stub).close()
    env = os.environ.copy()
    env.update({"LAFORGE_HUB_PORT": str(port), "LAFORGE_HUB_HOST": "127.0.0.1", "PYTHONUNBUFFERED": "1",
                "LAFORGE_DB": str(stub), "NOKIDO_DATA_DIR": str(tmpdir / "donnees")})
    return env


def installer_profil(py_exe: Path, depot_root: Path) -> float:
    """Installe le profil client + ssot dans le venv et chronometre la duree."""
    t0 = time.perf_counter()
    # Installation de pip minimum et du paquet nokido-agent avec extras hub,rag en mode editable ou standard
    # Optionnel: pip install -e ".[hub,rag]"
    cmd = [str(py_exe), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]
    subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace")

    # NON editable, depuis la COPIE isolee : aucun egg-info ecrit dans le depot de travail
    cmd_install = [str(py_exe), "-m", "pip", "install", f"{depot_root}[hub,rag]"]
    subprocess.run(cmd_install, check=True, capture_output=True, text=True, errors="replace")
    t1 = time.perf_counter()
    return t1 - t0


def mesurer_iteration(numero: int, depot_root: Path, port: int, repos_s: int = 60, entree: str = "source") -> dict:
    """Execute une repetition du protocole de mesure."""
    tmpdir = Path(tempfile.mkdtemp(prefix=f"nokido_bench_iter_{numero}_"))
    try:
        venv_dir = tmpdir / "venv"
        print(f"[Iter {numero}] Copie isolee du depot (git archive HEAD)...")
        depot_root = copier_depot(depot_root, tmpdir / "depot")
        print(f"[Iter {numero}] Creation venv dans {venv_dir}...")
        py_exe = creer_venv(venv_dir)

        print(f"[Iter {numero}] Installation chronometree du profil [hub,rag]...")
        duree_install = installer_profil(py_exe, depot_root)
        taille_disque_mo = calculer_taille_repertoire_mo(venv_dir)
        print(f"[Iter {numero}] Duree install: {duree_install:.2f} s | Taille disque venv: {taille_disque_mo:.1f} Mo")

        print(f"[Iter {numero}] Demarrage du hub sur le port {port}...")
        env = env_isole(tmpdir, port)

        # entree « roue » (30/10) : l'executable `nokido-hub` INSTALLE dans le venv, lance depuis le dossier
        # temporaire (pas depuis la copie du depot) -- prouve que la roue suffit seule. « source » : le script copie.
        if entree == "roue":
            bin_dir = py_exe.parent
            exe = bin_dir / ("nokido-hub.exe" if sys.platform == "win32" else "nokido-hub")
            commande, dossier = [str(exe)], str(tmpdir)
        else:
            commande, dossier = [str(py_exe), str(depot_root / "tools" / "nokido_hub.py")], str(depot_root)
        print(f"[Iter {numero}] Point d'entree : {entree} ({commande[0]})")
        t_start = time.perf_counter()
        proc = subprocess.Popen(
            commande,
            cwd=dossier,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Attendre que le hub reponde sur /health
        url_health = f"http://127.0.0.1:{port}/health"
        hub_pret = False
        t_boot = None
        for _ in range(60):
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise RuntimeError(f"Le hub a crashe au demarrage (rc={proc.returncode}):\n{err.decode(errors='replace')}")
            try:
                with urllib.request.urlopen(url_health, timeout=1.0) as resp:
                    if resp.status == 200:
                        t_boot = time.perf_counter() - t_start
                        hub_pret = True
                        break
            except Exception:  # muet-ok : hub pas encore pret, c'est l'attente elle-meme (bornee a 60 essais)
                time.sleep(0.5)

        if not hub_pret or t_boot is None:
            proc.kill()
            raise TimeoutError(f"Le hub n'a pas repondu sur {url_health} apres 30 s")

        print(f"[Iter {numero}] Hub pret en {t_boot:.2f} s. Attente au repos {repos_s} s...")
        time.sleep(repos_s)

        # Mesure RSS
        rss_mo = 0.0
        if psutil is not None:
            try:
                p = psutil.Process(proc.pid)
                # Prendre le RSS du hub + d'eventuels sous-processus
                rss_bytes = p.memory_info().rss
                enfants_illisibles = 0
                for child in p.children(recursive=True):
                    try:
                        rss_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        enfants_illisibles += 1
                if enfants_illisibles:
                    print(f"[Iter {numero}] {enfants_illisibles} sous-processus ILLISIBLE(S) : RSS sous-estimee")
                rss_mo = rss_bytes / (1024 * 1024)
            except Exception as e:
                print(f"[Iter {numero}] Erreur mesure psutil: {e}")
        else:
            print(f"[Iter {numero}] psutil non installe, mesure RSS indisponible.")

        print(f"[Iter {numero}] RSS au repos apres {repos_s} s : {rss_mo:.1f} Mo")

        # Arret propre
        print(f"[Iter {numero}] Arret du hub...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        return {
            "duree_install_s": duree_install,
            "disque_venv_mo": taille_disque_mo,
            "boot_s": t_boot,
            "rss_repos_mo": rss_mo,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Mesure du profil client + SSoT Nokido")
    parser.add_argument("--repetitions", type=int, default=3, help="Nombre de repetitions (defaut: 3)")
    parser.add_argument("--repos", type=int, default=60, help="Temps d'attente au repos en secondes (defaut: 60)")
    parser.add_argument("--port", type=int, default=None, help="Port cible libre (defaut: auto-detecte)")
    parser.add_argument("--entree", choices=("source", "roue"), default="source",
                        help="source : tools/nokido_hub.py de la copie ; roue : executable nokido-hub du venv")
    args = parser.parse_args()

    depot_root = Path(__file__).resolve().parent.parent.parent
    port = args.port or trouver_port_libre(8798)

    print("=" * 60)
    print("MESURE PROFIL CLIENT + SSoT (NOKIDO)")
    print(f"Depot : {depot_root}")
    print(f"Port libre retenu : {port}")
    print(f"Repetitions : {args.repetitions} | Pause repos : {args.repos} s")
    print("=" * 60)

    resultats = []
    for i in range(1, args.repetitions + 1):
        res = mesurer_iteration(i, depot_root, port, repos_s=args.repos, entree=args.entree)
        resultats.append(res)

    # Calcul des medianes
    med_install = statistics.median(r["duree_install_s"] for r in resultats)
    med_disque = statistics.median(r["disque_venv_mo"] for r in resultats)
    med_boot = statistics.median(r["boot_s"] for r in resultats)
    med_rss = statistics.median(r["rss_repos_mo"] for r in resultats)

    print("\n" + "=" * 60)
    print("SYNTHESE DES REPETITIONS :")
    for idx, r in enumerate(resultats, 1):
        print(f"  Repetition {idx}: Install={r['duree_install_s']:.2f}s, Disque={r['disque_venv_mo']:.1f}Mo, Boot={r['boot_s']:.2f}s, RSS={r['rss_repos_mo']:.1f}Mo")
    print("-" * 60)
    print(f"MEDIANES : Install={med_install:.2f}s | Disque={med_disque:.1f}Mo | Boot={med_boot:.2f}s | RSS={med_rss:.1f}Mo")
    print("=" * 60)

    # Ligne de bilan finale imperative
    print(f"BILAN mesure_profil_client: entree={args.entree} install_median_s={med_install:.2f} "
          f"disque_median_mo={med_disque:.1f} boot_median_s={med_boot:.2f} rss_median_mo={med_rss:.1f}")


if __name__ == "__main__":
    main()
