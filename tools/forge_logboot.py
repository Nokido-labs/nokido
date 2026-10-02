#!/usr/bin/env python3
"""forge_logboot.py -- amorceur de JOURNAL SANS PIPE pour les services Python du superviseur.

POURQUOI (mesure du 2026-10-01). Sous Windows, chaque pipe d'enfant lu par le superviseur Deno immobilise
un thread de son pool BLOQUANT, plafonne a 4 x coeurs logiques (16 -> 64). 57 enfants pipes = 114
lectures pour 64 threads : seuls 5 journaux de service sur 56 arrivaient en direct, les autres par
PAQUETS (pair MCP : 4 min 30 de retard ; Ollama : 300 lignes sous un seul horodatage). Le systeme
nerveux du corps ne peut pas dependre d'un pool sature.

CE QU'IL FAIT. Il tourne DANS le process du service, sous l'interpreteur du service (jamais un autre) :
  1. taille le journal comme le superviseur (> 500 Mo : remis a zero ; > 5 Mo : on garde 2 Mo) ;
  2. cree un pipe INTERNE ; un thread de CE process le lit, horodate chaque ligne (meme format que le
     superviseur) et l'ecrit dans le journal -- pas de pool partage, pas de plafond ;
  3. redirige les fd 1 et 2 sur ce pipe (dup2) ET les handles standard Win32 (SetStdHandle) : les
     sorties C et les sous-process lances sans redirection sont donc horodates eux aussi ;
  4. arme faulthandler directement sur le journal (un crash natif laisse sa trace) ;
  5. execute la cible : `SCRIPT.py ARGS` (comme `python SCRIPT.py`) ou `-m MODULE ARGS` ;
     le code de sortie est celui de la cible.
Le superviseur lance alors le service SANS pipe (stdout/stderr null). Un service `runAs` est enveloppe
AU NIVEAU DU LANCEUR (forge_runas_launcher.py), sous le compte du superviseur.

Usage : python tools/forge_logboot.py --journal CHEMIN.log -- SCRIPT.py|-m MODULE [ARGS...]
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/journal-sans-pipe : le service ecrit son journal horodate sans pipe vers le superviseur"

import atexit
import faulthandler
import io
import os
import runpy
import sys
import threading
from datetime import datetime

# Memes bornes que supervisor.ts (LOG_MAX_BYTES, KEEP, seuil firehose) : un journal se taille pareil
# qu'il soit ecrit par le superviseur ou par le service.
TAILLE_MAX = 5 * 1024 * 1024
GARDE = 2_000_000
FIREHOSE = 500_000_000
LIGNE_MAX = 65_536  # une ligne sans fin (barre de progression) est coupee, jamais accumulee sans borne

# REFERENCES VIVANTES (2026-10-01, regression mesuree sur NokidoHomeostasis : code 1 en 3 s,
# `ValueError: I/O operation on closed file` sur un simple print). Un service qui fait
# `sys.stdout = TextIOWrapper(sys.stdout.buffer, ...)` PARTAGE notre tampon ; quand NOTRE enveloppe
# n'est plus referencee, le ramasse-miettes la detruit et FERME ce tampon partage. Avec un vrai
# stdout, sys.__stdout__ tient l'original en vie ; ici c'est ce registre qui le fait.
_GARDES: list = []


def horodatage() -> str:
    """Heure LOCALE au format du superviseur : `AAAA-MM-JJ HH:MM:SS.mmm`."""
    d = datetime.now()
    return d.strftime("%Y-%m-%d %H:%M:%S.") + "%03d" % (d.microsecond // 1000)


def tailler(chemin: str) -> None:
    try:
        taille = os.path.getsize(chemin)
    except OSError:
        return  # absent : il sera cree
    if taille <= TAILLE_MAX:
        return
    if taille > FIREHOSE:
        with open(chemin, "wb"):
            return
    with open(chemin, "rb") as f:
        f.seek(taille - min(TAILLE_MAX, GARDE))
        fin = f.read()
    with open(chemin, "wb") as f:
        f.write(fin)


def _ecrire_tout(fd: int, donnees: bytes) -> None:
    while donnees:
        n = os.write(fd, donnees)
        donnees = donnees[n:]


class Relais:
    """Lit le pipe interne, horodate chaque ligne, l'ecrit dans le journal. Ne meurt jamais sur une
    erreur d'ecriture : il compte, et continue de VIDER le pipe -- un relais arrete bloquerait le
    service des que le pipe serait plein."""

    def __init__(self, lecture_fd: int, journal_fd: int):
        self.lecture_fd = lecture_fd
        self.journal_fd = journal_fd
        self.echecs = 0
        self.fil = threading.Thread(target=self._boucle, name="logboot-relais", daemon=True)

    def _ecrire(self, lignes: list) -> None:
        sortie = b"".join(b"%s %s\n" % (horodatage().encode("ascii"), l.rstrip(b"\r"))
                          for l in lignes if l.strip())
        if not sortie:
            return
        try:
            _ecrire_tout(self.journal_fd, sortie)
        except OSError:
            self.echecs += 1  # disque plein ou journal retire : on continue de vider le pipe

    def _boucle(self) -> None:
        tampon = b""
        while True:
            try:
                bloc = os.read(self.lecture_fd, 65536)
            except OSError:
                break
            if not bloc:
                break
            tampon += bloc
            *lignes, tampon = tampon.split(b"\n")
            if len(tampon) > LIGNE_MAX:
                lignes.append(tampon)
                tampon = b""
            self._ecrire(lignes)
        if tampon:
            self._ecrire([tampon])


def installer(journal: str) -> Relais:
    tailler(journal)
    drapeaux = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    journal_fd = os.open(journal, drapeaux, 0o644)
    lecture, ecriture = os.pipe()
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.flush()
        except Exception:  # noqa: BLE001 -- muet-ok : flux standard deja ferme (lance avec null)
            pass
    os.dup2(ecriture, 1)
    os.dup2(ecriture, 2)
    os.close(ecriture)
    if os.name == "nt":
        # Un sous-process lance SANS redirection herite des handles STANDARD Win32 (CPython les lit par
        # GetStdHandle), pas des fd du CRT : sans ceci, ses sorties partiraient vers le null d'origine.
        import ctypes
        import msvcrt
        noyau = ctypes.windll.kernel32
        noyau.SetStdHandle(-11, msvcrt.get_osfhandle(1))  # STD_OUTPUT_HANDLE
        noyau.SetStdHandle(-12, msvcrt.get_osfhandle(2))  # STD_ERROR_HANDLE
    sys.stdout = io.TextIOWrapper(os.fdopen(1, "wb", closefd=False), encoding="utf-8",
                                  errors="replace", line_buffering=True, write_through=True)
    sys.stderr = io.TextIOWrapper(os.fdopen(2, "wb", closefd=False), encoding="utf-8",
                                  errors="replace", line_buffering=True, write_through=True)
    _GARDES.extend([sys.stdout, sys.stderr])
    sys.__stdout__, sys.__stderr__ = sys.stdout, sys.stderr
    # Les sous-process Python heritent du pipe : sans ceci, leur stdout serait bufferise par blocs.
    os.environ["PYTHONUNBUFFERED"] = "1"
    faulthandler.enable(file=journal_fd, all_threads=True)
    relais = Relais(lecture, journal_fd)
    relais.fil.start()
    atexit.register(_vider, relais)
    return relais


def _vider(relais: Relais) -> None:
    """A la sortie : on ferme NOS bouts d'ecriture pour que le relais lise la fin du pipe, et on lui
    laisse un court delai (un sous-process encore vivant peut tenir le pipe ouvert)."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.flush()
        except Exception:  # noqa: BLE001 -- muet-ok : vidage en fin de vie, rien a faire de plus
            pass
    for fd in (1, 2):
        try:
            os.close(fd)
        except OSError:
            pass  # muet-ok : deja ferme
    relais.fil.join(timeout=3.0)


def _decouper(argv: list) -> tuple:
    """(journal, cible) depuis `--journal CHEMIN -- CIBLE...` ; refuse toute autre forme."""
    if len(argv) < 4 or argv[0] != "--journal" or argv[2] != "--":
        raise SystemExit("usage : forge_logboot.py --journal CHEMIN.log -- SCRIPT.py|-m MODULE [ARGS...]")
    return argv[1], argv[3:]


def executer(cible: list) -> None:
    """Execute la cible comme le ferait l'interpreteur : sys.argv et sys.path[0] identiques."""
    if cible[0] == "-m":
        if len(cible) < 2:
            raise SystemExit("logboot : -m sans module")
        sys.argv = [cible[1]] + cible[2:]
        # `python -m MODULE` met le DOSSIER COURANT en tete de sys.path, pas celui de l'amorceur :
        # sans ceci, un module du cwd (ex. NokidoCapture : -u -m cli_tail_capture) est introuvable.
        sys.path[0] = os.getcwd()
        runpy.run_module(cible[1], run_name="__main__", alter_sys=True)
        return
    script = os.path.abspath(cible[0])
    sys.argv = [cible[0]] + cible[1:]
    sys.path[0] = os.path.dirname(script)  # `python SCRIPT.py` met le dossier du script en tete
    runpy.run_path(script, run_name="__main__")


def main(argv=None) -> None:
    journal, cible = _decouper(sys.argv[1:] if argv is None else argv)
    installer(journal)
    print("[logboot] journal sans pipe : pid %d, cible %s" % (os.getpid(), " ".join(cible)[:200]), flush=True)
    executer(cible)


if __name__ == "__main__":
    main()
