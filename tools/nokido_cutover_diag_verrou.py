"""nokido_cutover_diag_verrou.py — pourquoi le renommage rend ACCES REFUSE.

CONTEXTE. Quatre tentatives de cutover, toutes refusees sans rien modifier. La derniere
a change de symptome, et c'est le seul indice qui compte :

    essai 1  : WinError 32 (fichier utilise), 3 processus tenants  -> coherent
    essais 4+: WinError  5 (ACCES REFUSE),   0 processus tenant    -> autre chose

Sous NTFS, renommer un DOSSIER dont un fichier ENFANT est ouvert par un autre processus
rend ACCESS_DENIED, pas SHARING_VIOLATION. Or le detecteur du cutover ne regarde que le
repertoire courant et l'executable des processus : il est AVEUGLE aux handles ouverts.
Un daemon qui garde un journal ouvert suffit donc a bloquer, sans jamais apparaitre.

CE QUE CET OUTIL MESURE, dans l'ordre, sans rien modifier de durable :
  1. TEMOIN — cree un dossier jetable dans le parent, le renomme, le supprime. Si ce
     temoin echoue, le probleme est le PARENT (droits, protection anti-rançongiciel) et
     pas le depot. Sans ce temoin, on accuse le mauvais coupable.
  2. HANDLES — quel processus tient un fichier DANS l'arborescence. Necessite
     l'elevation ; le nombre de processus illisibles est imprime, faute de quoi
     « personne » ne se distingue pas de « je n'ai pas pu regarder ».
  3. ACCES CONTROLE AUX DOSSIERS — la protection anti-rançongiciel de Defender refuse
     les modifications par une application non autorisee, et son refus est un ACCES
     REFUSE indiscernable d'un probleme de droits.
  4. JONCTIONS — le depot contient un point de montage de VOLUME. C'est une piste a
     verifier, pas une accusation.
  5. TENTATIVE REELLE — le renommage est tente et l'erreur exacte est rendue. C'est
     l'autorite ; tout le reste n'est qu'indice.

LECTURE SEULE sur le depot. Le seul ecrit est le dossier temoin, dans le parent, supprime
aussitot.

CLI : LAFORGE_PYTHON tools/nokido_cutover_diag_verrou.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "outillage/renommage"

import os
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUPER = REPO.parent
CIBLE = SUPER / "Nokido"


def temoin() -> None:
    print("[1] TEMOIN — le parent autorise-t-il un renommage ?")
    a = SUPER / f"_temoin_cutover_{int(time.time())}"
    b = SUPER / f"_temoin_cutover_{int(time.time())}_renomme"
    try:
        a.mkdir()
    except OSError as e:
        print(f"    creation REFUSEE dans le parent : {type(e).__name__}: {e}")
        print("    -> le probleme est le PARENT, pas le depot.")
        return
    try:
        (a / "fichier.txt").write_text("temoin", encoding="utf-8")
        os.rename(a, b)
        print("    creation + renommage : OK — le parent n'est pas en cause")
    except OSError as e:
        print(f"    renommage REFUSE : {type(e).__name__}: {e}")
        print("    -> le probleme est le PARENT (droits ou protection), pas le depot.")
    finally:
        for d in (b, a):
            try:
                if d.exists():
                    for f in d.iterdir():
                        f.unlink()
                    d.rmdir()
            except OSError:
                print(f"    ! menage du temoin impossible : {d}")


def handles() -> None:
    print("[2] HANDLES — qui tient un fichier DANS le depot ?")
    try:
        import psutil
    except ImportError:
        print("    psutil absent — mesure impossible")
        return
    racine = str(REPO).lower()
    vus = illisibles = 0
    coupables: list[tuple[int, str, str]] = []
    for p in psutil.process_iter(["pid", "name"]):
        vus += 1
        try:
            for f in p.open_files():
                if f.path.lower().startswith(racine):
                    coupables.append((p.info["pid"], p.info["name"] or "?", f.path))
                    break
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            illisibles += 1
        except Exception:
            illisibles += 1
    print(f"    {len(coupables)} processus tiennent un fichier ouvert "
          f"(sur {vus} vus, {illisibles} ILLISIBLES depuis ce compte)")
    for pid, nom, chemin in coupables:
        print(f"    - pid {pid:<7} {nom:<22} {chemin}")
    if illisibles and not coupables:
        print("    ! aucun coupable VU, mais des process illisibles : ne pas conclure a l'absence")


def defender() -> None:
    print("[3] ACCES CONTROLE AUX DOSSIERS (protection anti-rançongiciel)")
    try:
        import winreg
        cle = (r"SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard"
               r"\Controlled Folder Access")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cle) as k:
            v = winreg.QueryValueEx(k, "EnableControlledFolderAccess")[0]
        print(f"    EnableControlledFolderAccess = {v} "
              f"({'ACTIF — piste serieuse' if v else 'inactif'})")
    except FileNotFoundError:
        print("    clef absente -> protection non configuree (inactive)")
    except OSError as e:
        print(f"    ILLISIBLE : {type(e).__name__}: {e}")


def jonctions() -> None:
    print("[4] JONCTIONS ET POINTS DE MONTAGE dans le depot")
    trouves = 0
    for p in REPO.iterdir():
        try:
            if p.is_dir() and os.path.islink(str(p)) or (p.is_dir() and _reparse(p)):
                cible = os.path.realpath(str(p))
                print(f"    - {p.name} -> {cible}")
                trouves += 1
        except OSError:
            continue
    if not trouves:
        print("    aucune au premier niveau")


def _reparse(p: Path) -> bool:
    try:
        return bool(os.stat(str(p), follow_symlinks=False).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


def tentative() -> None:
    print("[5] TENTATIVE REELLE — l'autorite, c'est le systeme")
    if CIBLE.exists():
        print(f"    la cible existe deja : {CIBLE}")
        return
    try:
        os.rename(REPO, CIBLE)
    except OSError as e:
        code = getattr(e, "winerror", None)
        sens = {5: "ACCES REFUSE — droits, protection, ou fichier ENFANT ouvert",
                32: "FICHIER UTILISE — un processus tient le dossier lui-meme",
                145: "DOSSIER NON VIDE — la cible existe"}.get(code, "voir le code")
        print(f"    ECHEC WinError {code} : {sens}")
        print(f"    {e}")
        return
    # Renommage reussi : on REVIENT en arriere, ce script ne fait que diagnostiquer.
    try:
        os.rename(CIBLE, REPO)
        print("    RENOMMAGE POSSIBLE — et annule aussitot. Relancer le cutover MAINTENANT.")
    except OSError as e:
        print(f"    !! renomme mais RETOUR IMPOSSIBLE : {e}")
        print(f"    !! le depot s'appelle actuellement {CIBLE}")


def main() -> int:
    print(f"[diag] depot : {REPO}")
    print(f"[diag] cible : {CIBLE}\n")
    temoin(); print()
    handles(); print()
    defender(); print()
    jonctions(); print()
    tentative()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
