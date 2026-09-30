#!/usr/bin/env python3
"""
forge_at_rest_efs.py — Chiffrement at-rest du dossier RAG/ via Windows EFS.

Contrôle de conformité (HIPAA / RGPD / HDS) : chiffrement des données au repos.
EFS (Encrypting File System) chiffre les fichiers RAG/embeddings.db et
RAG/execution_traces.db au niveau du système de fichiers NTFS, en AES-256,
SANS toucher au code applicatif. C'est la voie A de la roadmap compliance :
0 modification des ~631 sites sqlite3.connect() existants, contrairement à
SQLCipher (voie B, cf tools/forge_db_encrypt_migrate.py + app/forge_db_conn.py).

Portée du contrôle :
- EFS protège contre l'accès hors-session (vol de disque, autre compte Windows).
- BitLocker (chiffrement volume entier) le rend redondant : si BitLocker est
  actif sur le volume, EFS au niveau dossier n'ajoute qu'une couche par-compte.
- Aucun des deux ne protège un processus déjà autorisé en cours d'exécution
  (pour cela : SQLCipher, voie B).

ATTENTION — EFS est PAR-COMPTE
------------------------------
EFS chiffre avec la clé du compte qui exécute `--enable`. Seul ce compte
pourra ensuite lire RAG/. Les services Nokido ouvrent embeddings.db en
session interactive de l'utilisateur principal : `--enable` DOIT donc être
lancé sous CE compte (pas un compte sandbox/service distinct), sinon le hub
perd l'accès aux bases. Pour ouvrir l'accès à un autre compte légitime :
`cipher /adduser /user:<compte> RAG\\embeddings.db`.

NOTE INSTALLEUR — BitLocker
---------------------------
Au déploiement chez un utilisateur : si BitLocker est DÉJÀ actif sur le
volume (chiffrement disque complet), le contrôle at-rest est déjà couvert et
EFS devient redondant (n'ajoute qu'une isolation par-compte). `--status`
détecte BitLocker et le signale. Ne pas forcer EFS si BitLocker on.

Usage
-----
  python tools/forge_at_rest_efs.py --status
  python tools/forge_at_rest_efs.py --enable
  python tools/forge_at_rest_efs.py --verify
  python tools/forge_at_rest_efs.py --disable

Opérations réversibles, ne suppriment/déplacent jamais les bases.
Windows uniquement (cipher.exe / manage-bde).
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG_DIR = ROOT / "RAG"
DB_FILES = ["embeddings.db", "execution_traces.db"]


def _log(msg: str) -> None:
    print(f"[at-rest-efs] {msg}", flush=True)


def _guard_windows() -> None:
    if platform.system() != "Windows":
        _log(f"ERREUR: Windows requis (EFS/BitLocker). OS détecté: {platform.system()}")
        sys.exit(1)


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        # cipher.exe / manage-bde sortent en codepage OEM (accents FR) : decoder
        # avec errors="replace" pour ne pas crasher sur les octets non-cp1252.
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"commande introuvable: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout: {' '.join(cmd)}"


def _bitlocker_active() -> bool | None:
    """True/False si déterminable, None si manage-bde indisponible."""
    drive = os.path.splitdrive(str(RAG_DIR))[0] or "C:"
    rc, out = _run(["manage-bde", "-status", drive])
    if rc in (124, 127):
        return None
    low = out.lower()
    if "protection on" in low or "protection activée" in low:
        return True
    if "protection off" in low or "protection désactivée" in low:
        return False
    return None


def _check_rag_dir() -> bool:
    if not RAG_DIR.is_dir():
        _log(f"ERREUR: dossier RAG introuvable: {RAG_DIR}")
        return False
    return True


def cmd_status() -> int:
    if not _check_rag_dir():
        return 1
    bl = _bitlocker_active()
    if bl is True:
        _log("BitLocker: ACTIF sur le volume — at-rest déjà couvert (EFS redondant).")
    elif bl is False:
        _log("BitLocker: inactif sur le volume.")
    else:
        _log("BitLocker: état indéterminé (manage-bde indisponible ou droits insuffisants).")

    rc, out = _run(["cipher", "/c", str(RAG_DIR)])
    _log(f"cipher /c {RAG_DIR}:")
    print(out.strip())
    return 0 if rc == 0 else 1


def _db_encrypted(path: Path) -> bool | None:
    """Lit l'attribut chiffré via 'cipher /c <file>'. None si indéterminé."""
    rc, out = _run(["cipher", "/c", str(path)])
    if rc != 0:
        return None
    for line in out.splitlines():
        s = line.strip()
        if path.name in s:
            # 'E' en début de ligne = chiffré, 'U' = non chiffré
            return s[:1].upper() == "E"
    return None


def cmd_enable() -> int:
    if not _check_rag_dir():
        return 1
    bl = _bitlocker_active()
    if bl is True:
        _log("INFO: BitLocker actif — EFS ajoute une protection par-compte par-dessus.")
    _log(f"Chiffrement EFS récursif de {RAG_DIR} (cipher /e /s) ... (peut durer plusieurs min)")
    rc, out = _run(["cipher", "/e", "/s:" + str(RAG_DIR)], timeout=3600)
    print(out.strip())
    if rc == 124:
        _log("WARN: cipher /e a dépassé le timeout sur gros volume. Les fichiers déjà")
        _log("      traités SONT chiffrés — lancer --verify pour confirmer l'état réel.")
        return 1
    if rc != 0:
        _log("ERREUR: échec cipher /e.")
        return 1
    _log("OK: EFS activé. Lancer --verify pour confirmer les .db.")
    return 0


def cmd_disable() -> int:
    if not _check_rag_dir():
        return 1
    _log(f"Déchiffrement EFS récursif de {RAG_DIR} (cipher /d /s) ... (peut durer plusieurs min)")
    rc, out = _run(["cipher", "/d", "/s:" + str(RAG_DIR)], timeout=3600)
    print(out.strip())
    if rc != 0:
        _log("ERREUR: échec cipher /d.")
        return 1
    _log("OK: EFS désactivé sur RAG/.")
    return 0


def cmd_verify() -> int:
    if not _check_rag_dir():
        return 1
    ok = True
    for name in DB_FILES:
        p = RAG_DIR / name
        if not p.is_file():
            _log(f"  {name}: ABSENT (ignoré)")
            continue
        enc = _db_encrypted(p)
        if enc is True:
            _log(f"  {name}: CHIFFRÉ (EFS) ✓")
        elif enc is False:
            _log(f"  {name}: EN CLAIR ✗")
            ok = False
        else:
            _log(f"  {name}: état indéterminé")
            ok = False
    bl = _bitlocker_active()
    if bl is True and not ok:
        _log("NOTE: BitLocker actif — at-rest couvert au niveau volume même si EFS off.")
        return 0
    return 0 if ok else 1


def main(argv=None) -> int:
    _guard_windows()
    p = argparse.ArgumentParser(description="Chiffrement at-rest EFS du dossier RAG/.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="État chiffrement + BitLocker")
    g.add_argument("--enable", action="store_true", help="Activer EFS sur RAG/ (récursif)")
    g.add_argument("--disable", action="store_true", help="Désactiver EFS sur RAG/")
    g.add_argument("--verify", action="store_true", help="Vérifier l'attribut chiffré des .db")
    args = p.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.enable:
        return cmd_enable()
    if args.disable:
        return cmd_disable()
    if args.verify:
        return cmd_verify()
    return 2


if __name__ == "__main__":
    sys.exit(main())
