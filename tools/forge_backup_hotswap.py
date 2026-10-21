#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forge_backup_hotswap.py — Nokido Hot-Swap Backup Module
==========================================================
DATE: 2026-07-01

CONTEXTE
--------
Disque cible : "Grodata" (F:), tiroir SATA interne hot-swap, NTFS, GPT,
~3726 Go, Disque 4 (diskpart). Confirmé sain (SMART), aucune erreur VSS/volsnap
liée à ce disque au moment de l'écriture de ce module.

Benchmarks diskspd (2026-07-01, séquentiel 1MiB Q8T1) :
    C: Systeme    787 MB/s R/W   -> HOT  (jamais cible d'ecriture de backup)
    D: FileHistory 527/ 56 MB/s  -> ecriture bridee, EVITER en cible d'ecriture
    E: Data       107/ 94 MB/s   -> WARM (source de sauvegarde)
    H: (178G)     523/ 15 MB/s   -> ecriture quasi inutilisable, EVITER
    F: Grodata    149/149 MB/s   -> COLD (destination, hot-swap)

REGLE D'OR (post-mortem 2026-06-02, cf. forge_db_path.py / forge_at_rest_veracrypt.py)
---------------------------------------------------------------------------------------
Un ancien montage en file-symlink (RAG/embeddings.db -> V:) a corrompu le WAL
car le journal -wal/-shm ne peut pas etre garanti atomique a travers un
support qui peut disparaitre. CE MODULE NE COPIE JAMAIS UN FICHIER SQLITE
"EN CHAUD" (.db + -wal + -shm) DEPUIS LE DISQUE HOT-SWAP CIBLE. Toute base
est exportee via `VACUUM INTO` (snapshot atomique, fichier unique, coherent)
AVANT d'etre copiee vers F:.

CE QUE FAIT CE MODULE
----------------------
1. Verifie l'identite du disque cible (numero diskpart + lettre + label)
   AVANT toute ecriture — refuse si ca ne correspond pas exactement.
2. Met le disque "online" (diskpart) s'il est hot-swap et actuellement
   offline, attend le montage effectif.
3. Exporte les bases SQLite (VACUUM INTO) vers un dossier temporaire local
   rapide (C:) puis les copie vers F: — jamais d'ecriture directe du live.
4. Copie les repertoires "tree" (logs, warm data) via robocopy avec retry.
5. Applique une politique de retention par generations horodatees.
6. Ecrit un manifest JSON (hash + tailles + duree) pour chaque run.
7. Remet le disque "offline" proprement en fin de sauvegarde (best-effort,
   desactivable via --no-offline).
8. Emet un evenement sur l'EventBus Nokido (best-effort, ne bloque jamais
   le backup si le hub est down).

USAGE
-----
    python tools/forge_backup_hotswap.py status
    python tools/forge_backup_hotswap.py backup [--dry-run] [--no-offline]
    python tools/forge_backup_hotswap.py online
    python tools/forge_backup_hotswap.py offline
    python tools/forge_backup_hotswap.py list
    python tools/forge_backup_hotswap.py archive-flux --source <db> --cible <arc.7z>
    python tools/forge_backup_hotswap.py archive-verifier --archive <arc.7z>
    python tools/forge_backup_hotswap.py archive-restaurer --archive <arc.7z> --dest <db>

A ADAPTER avant premiere utilisation : la section CONFIGURATION ci-dessous
(chemins SOURCES, ROOT, DISK_NUMBER si le disque est reinstalle ailleurs).
"""

from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# python 3.14 : dataclasses._is_type lit sys.modules[cls.__module__].__dict__ SANS garde :
# un module charge par spec.loader.exec_module (chemin des NR) doit etre enregistre par son
# CHARGEUR avant exec, sinon `None.__dict__` au premier @dataclass. Le module ne
# s'amorce PAS lui-meme ici -- voir _charger_le_module dans tests/nr.

__FORGE_COLOR__ = "infra/deploy : backup hot-swap"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# CONFIGURATION — a adapter a l'environnement local
# ---------------------------------------------------------------------------

DISK_NUMBER = 4                 # "Disque 4" dans diskpart (confirme le 2026-07-01)
DRIVE_LETTER = "F"
EXPECTED_LABEL = "Grodata"      # label NTFS attendu — securite anti-mauvais-disque
MOUNT_ROOT = Path(f"{DRIVE_LETTER}:\\")
BACKUP_ROOT = MOUNT_ROOT / "Nokido_backups"

# Racine DERIVEE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs" / "hotswap_backup"
STAGING_DIR = ROOT / "sandbox" / "hotswap_staging"   # export SQLite intermediaire (C:, rapide)
STATE_FILE = ROOT / "sandbox" / "hotswap_backup_state.json"

# EventBus Nokido (best-effort — cf. forge_agentic_engine.py _emit_skill_event)
HUB_URL = "http://127.0.0.1:8766/mcp"
HUB_TOKEN_ENV = "FORGE_MCP_TOKEN"

# --- Fix #1 (securite) : les bases RAG resolvent vers %NOKIDO_DATA%\ (VeraCrypt). Un VACUUM INTO
# en produit une copie EN CLAIR -> on chiffre l'export (7-Zip AES-256, entetes chiffres,
# cle scellee dans le coffre DPAPI) avant ecriture sur F:. JAMAIS de plaintext du volume
# chiffre sur F:. Restauration : 7z x -p<cle-du-coffre> <fichier>.db.7z
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
BACKUP_ENC_KEY_NAME = "LAFORGE_BACKUP_ENC_KEY"

# --- Fix #2 (safety) : diskpart cible par NUMERO, qui peut changer. On confirme le disque
# par sa TAILLE (discriminant materiel) AVANT online, et par le LABEL du volume avant offline.
EXPECTED_DISK_SIZE_GB = 3726
DISK_SIZE_TOL = 0.04

# Sources — "sqlite" = export atomique VACUUM INTO, "tree" = copie via robocopy
SOURCES = {
    "rag_embeddings": {
        "kind": "sqlite",
        # Passer par le realpath canonique (resout le symlink C:->V:), cf. forge_db_path.py
        "path": ROOT / "RAG" / "embeddings.db",
        "dest_subdir": "rag",
        "encrypt": True,   # source sur V: chiffre -> sortie chiffree obligatoire (Fix #1)
    },
    "execution_traces": {
        "kind": "sqlite",
        "path": ROOT / "RAG" / "execution_traces.db",
        "dest_subdir": "rag",
        "encrypt": True,   # source sur V: chiffre -> sortie chiffree obligatoire (Fix #1)
    },
    "warm_data": {
        "kind": "tree",
        "path": Path(r"E:\LaForge_data"),          # AJUSTER selon l'usage reel de E:
        "dest_subdir": "warm",
        "optional": True,                            # ne bloque pas si absent
    },
    "logs": {
        "kind": "tree",
        "path": LOG_DIR.parent,                       # ROOT/logs
        "dest_subdir": "logs",
    },
}

RETENTION_GENERATIONS = 5   # nombre de sauvegardes horodatees a conserver sur F:

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_backup_hotswap.py', 164, exc_info=True)
logger = logging.getLogger("Nokido.HotswapBackup")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # JOURNAL QUI NE CASSE PAS LA SAUVEGARDE (2026-09-24, mesure) : lance par le compte des
    # jobs, l'ouverture de logs/hotswap_backup/hotswap_backup.log (cree par un autre compte)
    # levait PermissionError A L'IMPORT -- sauvegarde morte avant la moindre ecriture.
    # Repli : journal dans sandbox/, sinon sortie standard seule ; le repli est DIT.
    _repli = ""
    for _chemin in (LOG_DIR / "hotswap_backup.log", ROOT / "sandbox" / "hotswap_backup.log"):
        try:
            _fh = logging.FileHandler(_chemin, encoding="utf-8")
            _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(_fh)
            break
        except OSError as _e_journal:
            _repli += "%s refuse (%s) ; " % (_chemin, type(_e_journal).__name__)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_ch)
    if _repli:
        logger.warning("[journal] repli : %s", _repli)


# ---------------------------------------------------------------------------
# DISKPART — identite, online/offline
# ---------------------------------------------------------------------------

class DiskIdentityError(RuntimeError):
    """Le disque monte sur DRIVE_LETTER ne correspond pas a ce qui est attendu."""


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    logger.debug(f"exec: {' '.join(cmd)}")
    # errors="replace" OBLIGATOIRE : diskpart sort en codepage OEM (accents FR) -> sans
    # ca le decodage texte peut crasher le reader-thread et casser la lecture diskpart (Fix #2).
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)


def _diskpart(script_lines: list[str], timeout: int = 60) -> str:
    """Execute un script diskpart (methode officielle : fichier temporaire)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(script_lines) + "\n")
        script_path = f.name
    try:
        res = _run(["diskpart", "/s", script_path], timeout=timeout)
        return res.stdout + res.stderr
    finally:
        Path(script_path).unlink(missing_ok=True)


def _disk_size_gb() -> Optional[float]:
    """Taille (Go) du disque DISK_NUMBER via `list disk` — marche online ET offline.
    Retourne None si non parsable (=> refus fail-safe cote appelant)."""
    import re
    out = _diskpart(["list disk"])
    for line in out.splitlines():
        low = line.lower()
        if f"disque {DISK_NUMBER} " in low or f"disk {DISK_NUMBER} " in low:
            # diskpart FR : "3726 G octets" / "3,64 T octets" ; EN : "3726 GB" ; parfois "Go/To".
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*([gt])\s*(?:o(?:ctets)?|b(?:ytes)?)", low)
            if not m:
                return None
            val = float(m.group(1).replace(",", "."))
            return val * 1024 if m.group(2) == "t" else val
    return None


def verify_disk_hardware() -> None:
    """Fix #2 : confirme que DISK_NUMBER est le disque attendu par sa TAILLE AVANT tout
    online/offline (le numero diskpart peut changer). Fail-safe : refuse si taille non
    parsable ou hors tolerance."""
    size = _disk_size_gb()
    if size is None:
        raise DiskIdentityError(
            f"Taille du Disque {DISK_NUMBER} non parsable (list disk) — ABANDON par securite."
        )
    if abs(size - EXPECTED_DISK_SIZE_GB) / EXPECTED_DISK_SIZE_GB > DISK_SIZE_TOL:
        raise DiskIdentityError(
            f"Disque {DISK_NUMBER} = {size:.0f} Go, attendu ~{EXPECTED_DISK_SIZE_GB} Go "
            f"(tol {DISK_SIZE_TOL:.0%}) — le numero de disque a peut-etre change. ABANDON."
        )
    logger.info(f"[identity] hardware OK — Disque {DISK_NUMBER} ~{size:.0f} Go")


def verify_disk_identity() -> None:
    """
    Verification stricte AVANT toute ecriture : le volume monte sur
    DRIVE_LETTER doit etre EXPECTED_LABEL et pointer sur DISK_NUMBER.
    Refuse (leve DiskIdentityError) si ce n'est pas le cas — c'est la
    meme logique que la verification manuelle faite avant le premier
    formatage de ce disque.
    """
    import re

    # Label via `list volume` (diskpart FR n'affiche PAS le label dans `detail volume`).
    vols = _diskpart(["list volume"])
    label_ok = any(
        re.search(rf"\b{DRIVE_LETTER.lower()}\b", ln.lower()) and EXPECTED_LABEL.lower() in ln.lower()
        for ln in vols.splitlines()
    )
    if not label_ok:
        raise DiskIdentityError(
            f"Volume '{EXPECTED_LABEL}' sur {DRIVE_LETTER}: introuvable dans `list volume` "
            f"— ABANDON par securite.\nSortie diskpart:\n{vols}"
        )
    # Numero de disque via `detail volume` (lie le volume au disque physique).
    det = _diskpart([f"select volume {DRIVE_LETTER}", "detail volume"])
    if f"disque {DISK_NUMBER}".lower() not in det.lower() and f"disk {DISK_NUMBER}".lower() not in det.lower():
        raise DiskIdentityError(
            f"Volume {DRIVE_LETTER}: pas confirme sur le Disque {DISK_NUMBER} (detail volume) "
            f"— ABANDON par securite (le disque a peut-etre change de numero).\nSortie diskpart:\n{det}"
        )
    logger.info(f"[identity] OK — {DRIVE_LETTER}: = '{EXPECTED_LABEL}', Disque {DISK_NUMBER}")


def disk_online() -> None:
    verify_disk_hardware()   # Fix #2 : jamais online un disque non confirme par sa taille
    out = _diskpart([f"select disk {DISK_NUMBER}", "online disk", "attributes disk clear readonly"])
    logger.info(f"[online] {out.strip().splitlines()[-1] if out.strip() else 'ok'}")


def disk_offline() -> None:
    # Fix #2 : ne jamais offline un disque non confirme. Volume monte -> verif LABEL (lie
    # le disque a Grodata) ; sinon -> verif TAILLE. Fail-safe (leve si mismatch).
    if MOUNT_ROOT.exists():
        verify_disk_identity()
    else:
        verify_disk_hardware()
    out = _diskpart([f"select disk {DISK_NUMBER}", "offline disk"])
    logger.info(f"[offline] {out.strip().splitlines()[-1] if out.strip() else 'ok'}")


def wait_for_mount(timeout: int = 30) -> bool:
    for _ in range(timeout):
        if MOUNT_ROOT.exists():
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# EXPORT SQLITE ATOMIQUE (jamais de copie de fichier .db live)
# ---------------------------------------------------------------------------

def _backup_key() -> str:
    """Cle AES du backup, scellee dans le coffre DPAPI (jamais en dur, jamais loggee).
    Generee au 1er run si absente."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_secrets import get_secret, set_secret

    k = get_secret(BACKUP_ENC_KEY_NAME, required=False)
    if not k:
        import secrets as _secrets

        k = _secrets.token_urlsafe(32)
        set_secret(BACKUP_ENC_KEY_NAME, k)
        logger.info("[crypto] cle de backup generee et scellee dans le coffre DPAPI")
    return k


def encrypt_file_7z(src_plain: Path, dest_enc: Path, key: str) -> dict:
    """Fix #1 : chiffre l'export VACUUM (clair) -> dest .7z AES-256 (entetes chiffres, sans
    compression = rapide). N'ecrit JAMAIS le .db clair sur la cible.

    CLE HORS DES ARGUMENTS (2026-09-24) : l'ancienne forme passait `-p<cle>` a 7z.exe -- la
    cle de chiffrement de TOUTES les sauvegardes etait lisible dans la liste des processus
    pendant toute la duree de l'export (dizaines de minutes pour ~45 Go). Le chiffrement se
    fait desormais EN PROCESSUS (py7zr, meme format .7z, relisible par 7-Zip). Sans py7zr :
    REFUS -- jamais de repli qui remettrait la cle en argument.
    """
    try:
        import py7zr
    except ImportError:
        return {"ok": False, "reason": "py7zr absent -- refus : la cle ne passe jamais en argument"}
    dest_enc.parent.mkdir(parents=True, exist_ok=True)
    dest_enc.unlink(missing_ok=True)
    t0 = time.time()
    ok, raison = False, ""
    try:
        filtres = [{"id": py7zr.FILTER_COPY}, {"id": py7zr.FILTER_CRYPTO_AES256_SHA256}]
        with py7zr.SevenZipFile(dest_enc, "w", password=key, header_encryption=True,
                                filters=filtres) as z:
            z.write(src_plain, arcname=src_plain.name)
        ok = dest_enc.exists()
    except Exception as e:  # noqa: BLE001 -- archive partielle retiree, motif dit
        raison = "%s: %s" % (type(e).__name__, str(e)[:120])
        dest_enc.unlink(missing_ok=True)
    elapsed = time.time() - t0
    size = dest_enc.stat().st_size if dest_enc.exists() else 0
    logger.info(f"[crypto] {src_plain.name} -> {dest_enc.name} "
                f"({size / 1e6:.1f} Mo, {elapsed:.1f}s) {'OK' if ok else 'ERREUR ' + raison}")
    return {"ok": ok, "size_bytes": size, "elapsed_s": round(elapsed, 2), "encrypted": True,
            **({"reason": raison} if raison else {})}


def export_sqlite(src: Path, dest: Path) -> dict:
    """
    VACUUM INTO — snapshot atomique coherent en un seul fichier, sans
    toucher aux -wal/-shm du fichier source. Safe meme si le hub ecrit
    dedans en parallele (SQLite gere le lock interne pendant l'export).
    """
    if not src.exists():
        return {"ok": False, "reason": "source absente", "path": str(src)}

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)

    t0 = time.time()
    conn = sqlite3.connect(str(src), timeout=30)
    try:
        conn.execute("VACUUM INTO ?", [str(dest)])
    finally:
        conn.close()
    elapsed = time.time() - t0

    size = dest.stat().st_size if dest.exists() else 0
    logger.info(f"[sqlite] {src.name} -> {dest} ({size / 1e6:.1f} Mo, {elapsed:.1f}s)")
    return {"ok": True, "size_bytes": size, "elapsed_s": round(elapsed, 2)}


# ---------------------------------------------------------------------------
# ARCHIVE CHIFFREE EN FLUX (roadmap p1_archive_chiffree_flux_2026-10-14)
# Une base vivante est archivee SANS aucun octet en clair sur disque : le
# contenu (schema + lignes, FTS comprises) part en parts JSONL dans un .7z
# AES-256 a entetes chiffres ; le manifeste porte l'empreinte sha256 de
# chaque part. `archive-flux` / `archive-verifier` / `archive-restaurer`.
# ---------------------------------------------------------------------------

PART_OCTETS = 64 << 20        # taille cible d'une part JSONL en memoire
WAL_MAX = 4 << 30             # WAL au-dela duquel l'archive abandonne (garde)


def _cle_archive() -> str:
    """Cle AES des archives : LUE au coffre, jamais generee ici.

    `_backup_key` genere une cle si le coffre n'en a pas ; pour une archive c'est un piege :
    une cle jamais sequestree (`export-key`) rend l'archive irrecuperable le jour ou le coffre
    est perdu -- precisement le jour ou on en a besoin. Absente : REFUS, et le geste est dit.
    """
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_secrets import get_secret

    k = get_secret(BACKUP_ENC_KEY_NAME, required=False)
    if not k:
        raise SystemExit(
            "cle d'archive ABSENTE ou illisible pour ce compte : refus. Geste : "
            "`forge_backup_hotswap.py export-key` sous le compte owner, puis relancer.")
    return k


def _q(nom: str) -> str:
    return '"%s"' % nom.replace('"', '""')


def _cellule(v):
    return {"$b64": base64.b64encode(v).decode()} if isinstance(v, (bytes, bytearray, memoryview)) else v


def _decellule(v):
    return base64.b64decode(v["$b64"]) if isinstance(v, dict) and "$b64" in v else v


def tables_a_exporter(con) -> tuple[list, list, list]:
    """(schema SQL ordonne, tables ordinaires, tables virtuelles FTS) -- tables internes FTS ecartees."""
    lignes = con.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, rowid").fetchall()
    virtuelles = [n for t, n, s in lignes if t == "table" and s.upper().startswith("CREATE VIRTUAL TABLE")]
    # 19/10 (relecture avant integration) : SEULS les suffixes d'ombre de SQLite FTS3/4/5 sont internes -- un simple
    # prefixe « <virtuelle>_ » ecartait aussi une table ORDINAIRE au nom voisin (rag_fts_sauvegarde), perdue en silence.
    _OMBRE = ("_data", "_idx", "_content", "_docsize", "_config", "_segments", "_segdir", "_stat")
    internes = {n for n in (x[1] for x in lignes)
                for v in virtuelles if n in {v + suf for suf in _OMBRE}}
    schema = [s for t, n, s in lignes if n not in internes]
    ordinaires = [n for t, n, s in lignes if t == "table" and n not in virtuelles and n not in internes]
    return schema, ordinaires, virtuelles


def tables_sans_rowid(con) -> set[str]:
    """Tables WITHOUT ROWID : `SELECT rowid, *` y est une erreur SQL. L'export se fait
    sans la colonne rowid, et la restauration suit les colonnes annoncees par l'entete
    de part -- donc aussi sans rowid."""
    import re

    return {n for n, s in con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL")
            if not s.upper().startswith("CREATE VIRTUAL TABLE")
            and re.search(r"\bWITHOUT\s+ROWID\b", s, re.IGNORECASE)}


def _ecrire_part(z, manifeste, table, k, lignes) -> None:
    data = ("\n".join(lignes) + ("\n" if lignes else "")).encode()
    nom = "donnees/%s/%05d.jsonl" % (table, k)
    z.writestr(data, nom)
    manifeste["parts"][nom] = {"octets": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def archive_exporter(src: Path, dest_7z: Path, cle: str) -> dict:
    """Archive LOGIQUE chiffree en flux : instantane fige (BEGIN), parts JSONL dans un .7z
    AES-256 a entetes chiffres, aucun fichier en clair sur disque. Rend le manifeste."""
    import py7zr
    if not cle:
        raise SystemExit("cle d'archive ABSENTE : refus (jamais de cle generee ici, elle differerait des autres)")
    con = sqlite3.connect("file:%s?mode=ro" % src.resolve().as_posix(), uri=True, timeout=30)
    con.execute("BEGIN")                     # instantane fige pour TOUTE l'archive
    manifeste = {"source": str(src), "debut": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "tables": {}, "parts": {}}
    filtres = [{"id": py7zr.FILTER_COPY}, {"id": py7zr.FILTER_CRYPTO_AES256_SHA256}]
    dest_7z.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_7z.with_suffix(".7z.partiel")
    try:
        schema, ordinaires, virtuelles = tables_a_exporter(con)
        sans_rowid = tables_sans_rowid(con)
        with py7zr.SevenZipFile(tmp, "w", password=cle, header_encryption=True, filters=filtres) as z:
            z.writestr(";\n".join(schema).encode(), "schema.sql")
            for table in ordinaires + virtuelles:
                cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % _q(table))]
                # WITHOUT ROWID : ni rowid dans le SELECT, ni rowid dans l'entete annoncee.
                entete = cols if table in sans_rowid else ["rowid"] + cols
                requete = ("SELECT * FROM %s" if table in sans_rowid
                           else "SELECT rowid, * FROM %s") % _q(table)
                n, k, tampon, taille = 0, 0, [], 0
                for ligne in con.execute(requete):
                    s = json.dumps([_cellule(c) for c in ligne], ensure_ascii=False)
                    tampon.append(s)
                    taille += len(s) + 1
                    n += 1
                    if taille >= PART_OCTETS:
                        _ecrire_part(z, manifeste, table, k,
                                     [json.dumps({"colonnes": entete})] + tampon)
                        k, tampon, taille = k + 1, [], 0
                        wal = Path(str(src) + "-wal")
                        if wal.exists() and wal.stat().st_size > WAL_MAX:
                            raise RuntimeError("WAL > %d Go pendant l'archive : abandon propre"
                                               % (WAL_MAX >> 30))
                if tampon or n == 0:
                    _ecrire_part(z, manifeste, table, k,
                                 [json.dumps({"colonnes": entete})] + tampon)
                manifeste["tables"][table] = {"lignes": n, "colonnes": entete,
                                              "fts": table in virtuelles}
                logger.info("[archive] %s : %d lignes", table, n)
            manifeste["fin"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            z.writestr(json.dumps(manifeste, ensure_ascii=False, indent=1).encode(), "manifeste.json")
        os.replace(tmp, dest_7z)
    finally:
        con.rollback()
        con.close()
        tmp.unlink(missing_ok=True)
    size = dest_7z.stat().st_size
    logger.info("[archive] %s -> %s (%.1f Mo)", src.name, dest_7z.name, size / 1e6)
    return manifeste


def _fabrique(sur_membre):
    """WriterFactory py7zR : chaque membre est rejoue dans `sur_membre` (morceau/fin),
    avec l'empreinte sha256 calculee en vol. Rien n'est ecrit en clair sur disque."""
    from py7zr.io import Py7zIO, WriterFactory

    class _Ecrivain(Py7zIO):
        def __init__(self, nom):
            self.nom, self._n, self._h = nom, 0, hashlib.sha256()

        def write(self, s):
            self._n += len(s)
            self._h.update(s)
            sur_membre.morceau(self.nom, bytes(s))
            return len(s)

        def read(self, size=None):
            return self._h.hexdigest().encode()

        def seek(self, offset, whence=0):
            return 0

        def flush(self):
            return None

        def size(self):
            return self._n

        def close(self):
            sur_membre.fin(self.nom, self._h.hexdigest())

    class _Fabrique(WriterFactory):
        def create(self, filename):
            return _Ecrivain(filename)

    return _Fabrique()


class _Verificateur:
    def __init__(self):
        self.empreintes, self.petits = {}, {}

    def morceau(self, nom, b):
        if not nom.startswith("donnees/"):
            self.petits[nom] = self.petits.get(nom, b"") + b

    def fin(self, nom, emp):
        self.empreintes[nom] = emp


def archive_verifier(archive: Path, cle: str) -> dict:
    """Relit chaque part en UN passage (archive solide : extraire part par part serait
    O(n^2)), recalcule l'empreinte de CHAQUE part et la compare au manifeste."""
    import py7zr
    v = _Verificateur()
    with py7zr.SevenZipFile(archive, "r", password=cle) as z:
        z.extract(factory=_fabrique(v))
    man = json.loads(v.petits["manifeste.json"].decode())
    fautes = [n for n, m in man["parts"].items() if v.empreintes.get(n) != m["sha256"]]
    return {"parts": len(man["parts"]), "fautes": fautes,
            "tables": {t: x["lignes"] for t, x in man["tables"].items()}}


class _Restaurateur:
    """Schema en DEUX TEMPS, puis insertion ligne a ligne de chaque part a mesure
    qu'elle arrive (memoire bornee a une ligne).

    Temps 1 (fin du membre schema.sql) : CREATE TABLE / CREATE VIRTUAL TABLE SEUL,
    les donnees ont besoin des tables. Temps 2 (apres TOUTES les donnees, avant
    commit, cf. `appliquer_schema_differe`) : CREATE INDEX / CREATE TRIGGER /
    CREATE VIEW -- un declencheur pose AVANT les donnees re-indexe pendant la
    restauration ce que la table FTS archivee contient deja (double indexation).
    """

    def __init__(self, con):
        self.con, self.tampon, self.colonnes = con, {}, {}
        self.schema, self.schema_differe = b"", []

    def morceau(self, nom, b):
        if nom == "schema.sql":
            self.schema += b
            return
        if not nom.startswith("donnees/"):
            return
        t = self.tampon.get(nom, b"") + b
        *completes, reste = t.split(b"\n")
        self.tampon[nom] = reste
        table = nom.split("/")[1]
        for ligne in completes:
            if not ligne:
                continue
            o = json.loads(ligne.decode())
            if isinstance(o, dict) and "colonnes" in o:
                self.colonnes[nom] = o["colonnes"]
                continue
            cols = self.colonnes[nom]
            self.con.execute(
                "INSERT INTO %s (%s) VALUES (%s)" % (_q(table), ",".join(_q(c) for c in cols),
                                                     ",".join("?" * len(cols))),
                [_decellule(c) for c in o])

    def fin(self, nom, _emp):
        if nom == "schema.sql":
            for instr in self.schema.decode().split(";\n"):
                if not instr.strip():
                    continue
                haut = instr.lstrip().upper()
                if haut.startswith("CREATE TABLE") or haut.startswith("CREATE VIRTUAL TABLE"):
                    self.con.execute(instr)
                else:
                    self.schema_differe.append(instr)

    def appliquer_schema_differe(self) -> None:
        """Index, declencheurs, vues : APRES toutes les donnees, avant commit."""
        for instr in self.schema_differe:
            self.con.execute(instr)
        self.schema_differe = []


def archive_restaurer(archive: Path, cle: str, dest_db: Path) -> dict:
    """Restaure une archive chiffree dans une base NEUVE : tables et FTS crees d'abord,
    donnees inserees, puis index/declencheurs/vues -- le FTS se RECONSTRUIT a l'insertion
    de son contenu archive (ses tables internes ne le sont jamais), sans double indexation."""
    import py7zr
    con = sqlite3.connect(str(dest_db))
    r = _Restaurateur(con)
    try:
        with py7zr.SevenZipFile(archive, "r", password=cle) as z:
            z.extract(factory=_fabrique(r))
        r.appliquer_schema_differe()
        con.commit()
        _schema, ordinaires, virtuelles = tables_a_exporter(con)
        out = {t: con.execute("SELECT COUNT(*) FROM %s" % _q(t)).fetchone()[0]
               for t in ordinaires + virtuelles}
    except Exception:
        con.close()
        dest_db.unlink(missing_ok=True)     # jamais de base partielle qui refuserait un re-essai
        raise
    con.close()
    logger.info("[restauration] %s : %s", dest_db.name, out)
    return out


# ---------------------------------------------------------------------------
# COPIE ARBORESCENCE (robocopy)
# ---------------------------------------------------------------------------

def copy_tree(src: Path, dest: Path) -> dict:
    if not src.exists():
        return {"ok": False, "reason": "source absente", "path": str(src)}

    dest.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # /MIR = miroir, /R:2 /W:5 = 2 retries / 5s (evite de bloquer sur fichier verrouille),
    # /NFL /NDL = pas de liste fichiers/dossiers dans la sortie (log allege),
    # /MT:4 = 4 threads (raisonnable pour un HDD ~150MB/s, evite la contention)
    cmd = ["robocopy", str(src), str(dest), "/MIR", "/R:2", "/W:5",
           "/NFL", "/NDL", "/MT:4", "/XJ"]
    res = _run(cmd, timeout=3600)
    elapsed = time.time() - t0
    # robocopy : codes 0-7 = succes (avec nuances), >=8 = erreur reelle
    ok = res.returncode < 8
    logger.info(f"[tree] {src} -> {dest} (rc={res.returncode}, {elapsed:.1f}s) "
                f"{'OK' if ok else 'ERREUR'}")
    if not ok:
        logger.error(res.stdout[-2000:])
    return {"ok": ok, "returncode": res.returncode, "elapsed_s": round(elapsed, 2)}


# ---------------------------------------------------------------------------
# RETENTION
# ---------------------------------------------------------------------------

def rotate_generations(base_dir: Path, keep: int = RETENTION_GENERATIONS) -> list[str]:
    if not base_dir.exists():
        return []
    gens = sorted(
        [p for p in base_dir.iterdir() if p.is_dir() and p.name.startswith("gen_")],
        key=lambda p: p.name,
    )
    removed = []
    while len(gens) > keep:
        oldest = gens.pop(0)
        shutil.rmtree(oldest, ignore_errors=True)
        removed.append(oldest.name)
        logger.info(f"[retention] generation supprimee: {oldest.name}")
    return removed


# ---------------------------------------------------------------------------
# EVENTBUS (best-effort, ne bloque jamais le backup)
# ---------------------------------------------------------------------------

def emit_event(topic: str, kind: str, data: dict) -> None:
    try:
        import os
        import urllib.request

        token = os.environ.get(HUB_TOKEN_ENV, "")
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "event", "arguments": {
                "action": "publish", "topic": topic, "kind": kind, "data": data,
            }},
        }).encode()
        req = urllib.request.Request(
            HUB_URL, data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}",
                     "X-Agent-Name": "HOTSWAP_BACKUP"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.debug(f"[eventbus] emit ignore (hub indisponible ?): {e}")


# ---------------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------------

@dataclass
class BackupResult:
    generation: str
    started_at: str
    finished_at: str = ""
    items: dict = field(default_factory=dict)
    success: bool = False


def _lecteur(p: Path) -> str:
    return (Path(p).drive or "").upper()


def _preparation(racine: Path, cible_fixe: Optional[str]) -> Path:
    """Zone de preparation (export VACUUM en clair, avant chiffrement).

    Cible FIXE : SUR LA CIBLE, jamais sur C: -- decision owner du 2026-09-24 (« la sauvegarde
    doit etre sur E ! pas sur C ! ») ; un premier essai avait deja pose 6,4 Go d'export en
    clair sous sandbox/hotswap_staging avant d'etre arrete. Disque AMOVIBLE (F:) : on garde
    C: comme avant, pour ne jamais laisser de clair sur un support qui peut partir."""
    return racine / "_preparation" if cible_fixe else STAGING_DIR


def _controle_cible_fixe(racine: Path) -> Optional[str]:
    """Cible FIXE (disque interne, pas de diskpart) : rend un motif de refus, ou None.
    Refuse une cible absente, et une cible sans place pour la plus grosse source x2,1
    (export en clair ET archive chiffree coexistent sur la cible le temps du chiffrement)."""
    if not Path(_lecteur(racine) + "\\").exists():
        return "lecteur %s absent" % _lecteur(racine)
    besoin = max((Path(s["path"]).stat().st_size for s in SOURCES.values()
                  if s["kind"] == "sqlite" and Path(s["path"]).exists()), default=0) * 2.1
    libre = shutil.disk_usage(_lecteur(racine) + "\\").free
    if libre < besoin:
        return "place insuffisante sur %s : %.1f Go libres pour %.1f Go" % (
            _lecteur(racine), libre / 1e9, besoin / 1e9)
    return None


def cmd_backup(dry_run: bool = False, do_offline: bool = True,
               cible_fixe: Optional[str] = None) -> int:
    gen_name = f"gen_{datetime.now():%Y%m%d_%H%M%S}"
    result = BackupResult(generation=gen_name, started_at=datetime.now().isoformat())

    logger.info(f"=== Backup {'cible FIXE ' + cible_fixe if cible_fixe else 'hot-swap'} — "
                f"generation {gen_name} {'[DRY-RUN]' if dry_run else ''} ===")

    racine = Path(cible_fixe) if cible_fixe else BACKUP_ROOT
    if cible_fixe:
        # CIBLE FIXE (2026-09-24, decision owner : « sauvegarde sur E en attendant la
        # reparation du disque (pb de cable) ») : ni diskpart, ni mise hors ligne.
        do_offline = False
        motif = _controle_cible_fixe(racine)
        if motif:
            logger.error(f"[abandon] {motif}")
            return 1
    else:
        # 1. Identite + online
        try:
            # Le disque doit deja etre insere physiquement ; online s'il ne l'est pas
            disk_online()
            if not wait_for_mount():
                logger.error(f"[abandon] {DRIVE_LETTER}: ne s'est pas monte a temps — "
                              f"le disque est-il bien insere ?")
                return 1
            verify_disk_identity()
        except DiskIdentityError as e:
            logger.error(f"[abandon] {e}")
            return 1

    if dry_run:
        logger.info("[dry-run] controles de cible OK — aucune ecriture effectuee.")
        return 0

    gen_dir = racine / gen_name
    staging = _preparation(racine, cible_fixe)
    staging.mkdir(parents=True, exist_ok=True)

    # Fix #1 : si une source chiffree est prevue, le chiffreur est OBLIGATOIRE. Sinon on
    # REFUSE tout le run plutot que de risquer d'ecrire du plaintext.
    _bk = ""
    if any(s.get("encrypt") for s in SOURCES.values()):
        try:
            import py7zr  # noqa: F401
        except ImportError:
            logger.error("[abandon] py7zr introuvable — impossible de proteger les sources "
                         "chiffrees sans mettre la cle en argument. Backup ANNULE.")
            if do_offline:
                try:
                    disk_offline()
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_backup_hotswap.py', 830, exc_info=True)
            return 1
        _bk = _backup_key()

    # 2. Sources
    for name, spec in SOURCES.items():
        src = Path(spec["path"])
        dest_subdir = gen_dir / spec["dest_subdir"]

        if cible_fixe and _lecteur(src) == _lecteur(racine):
            # Une copie sur le MEME disque que sa source ne survit pas a la perte du disque :
            # ce n'est pas une sauvegarde. Ecartee et DITE, jamais comptee comme reussie.
            logger.info(f"[skip] {name}: meme volume que la cible ({_lecteur(src)}) -- pas une sauvegarde")
            result.items[name] = {"ok": True, "skipped": True, "reason": "meme volume que la cible"}
            continue

        if spec["kind"] == "sqlite":
            staging_file = staging / f"{name}.db"
            export_res = export_sqlite(src, staging_file)
            if export_res.get("ok"):
                dest_subdir.mkdir(parents=True, exist_ok=True)
                if spec.get("encrypt"):
                    # Fix #1 : source sur volume chiffre -> UNIQUEMENT le .7z AES sur F:,
                    # jamais le .db clair. Le clair transite par le staging C: puis est purge.
                    enc_dest = dest_subdir / f"{name}.db.7z"
                    enc_res = encrypt_file_7z(staging_file, enc_dest, _bk)
                    export_res.update(enc_res)
                    export_res["ok"] = bool(enc_res.get("ok"))
                    export_res["copied_to"] = str(enc_dest) if enc_res.get("ok") else None
                else:
                    final_dest = dest_subdir / f"{name}.db"
                    shutil.copy2(staging_file, final_dest)
                    export_res["copied_to"] = str(final_dest)
                staging_file.unlink(missing_ok=True)   # purge le clair du staging C:
            result.items[name] = export_res

        elif spec["kind"] == "tree":
            if not src.exists() and spec.get("optional"):
                logger.info(f"[skip] {name}: source optionnelle absente ({src})")
                result.items[name] = {"ok": True, "skipped": True}
                continue
            result.items[name] = copy_tree(src, dest_subdir)

    # 3. Manifest
    result.finished_at = datetime.now().isoformat()
    result.success = all(v.get("ok", False) for v in result.items.values())
    manifest_path = gen_dir / "manifest.json"
    gen_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(result.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(f"[manifest] {manifest_path}")

    # 4. Retention
    removed = rotate_generations(racine)

    # 5. Event (best-effort)
    emit_event(
        topic="backup.hotswap",
        kind="completed" if result.success else "failed",
        data={"generation": gen_name, "items": list(result.items.keys()),
              "removed_generations": removed},
    )

    # 6. Offline
    if do_offline:
        try:
            disk_offline()
        except Exception as e:
            logger.warning(f"[offline] echec (non bloquant): {e}")

    logger.info(f"=== Backup {'REUSSI' if result.success else 'INCOMPLET'} "
                f"— {gen_name} ===")
    return 0 if result.success else 2


def cmd_status() -> int:
    out = _diskpart(["list disk", f"select volume {DRIVE_LETTER}", "detail volume"])
    print(out)
    return 0


def cmd_list() -> int:
    if not BACKUP_ROOT.exists():
        print(f"Aucune sauvegarde trouvee ({BACKUP_ROOT} inaccessible — disque monte ?)")
        return 1
    for gen in sorted(BACKUP_ROOT.glob("gen_*")):
        manifest = gen / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"{gen.name}  success={data.get('success')}  "
                  f"{data.get('started_at')} -> {data.get('finished_at')}")
        else:
            print(f"{gen.name}  (manifest manquant)")
    return 0


def cmd_export_key(out_path: Optional[str] = None) -> int:
    """Escrow DR : ecrit la cle de dechiffrement des backups dans un FICHIER (jamais
    sur le terminal/les logs), a deplacer hors-machine puis supprimer. La cle DPAPI
    est liee a CETTE machine : sans escrow, un backup .7z est irrecuperable si la
    machine est perdue."""
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_secrets import get_secret

    key = get_secret(BACKUP_ENC_KEY_NAME, required=False)
    if not key:
        logger.error(f"[export-key] {BACKUP_ENC_KEY_NAME} absente du coffre — lance d'abord un `backup`.")
        return 1
    dest = Path(out_path) if out_path else (Path.home() / "Desktop" / "LAFORGE_BACKUP_KEY_ESCROW.txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "Nokido — cle de dechiffrement des backups hot-swap (F:/Grodata)\n"
        f"Nom (coffre DPAPI) : {BACKUP_ENC_KEY_NAME}\n"
        f"Cle                : {key}\n\n"
        "Restauration d'un backup chiffre (7-Zip requis) :\n"
        "  7z x -p<CLE-CI-DESSUS> <nom>.db.7z\n\n"
        "!!! DPAPI est liee a CETTE machine. DEPLACE ce fichier hors-machine (USB / coffre /\n"
        "!!! impression) PUIS SUPPRIME-le de ce disque. Sans cette cle, les .7z sur F: sont\n"
        "!!! irrecuperables si la machine est perdue.\n",
        encoding="utf-8",
    )
    logger.info(f"[export-key] cle ecrite dans : {dest}")
    logger.info("[export-key] >>> DEPLACE ce fichier hors-machine PUIS SUPPRIME-le de C:. Ne le garde pas ici.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Nokido — backup hot-swap vers Grodata (F:)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Affiche l'etat diskpart du disque/volume")
    sub.add_parser("online", help="Met le disque hot-swap en ligne")
    sub.add_parser("offline", help="Met le disque hot-swap hors ligne (ejection propre)")
    sub.add_parser("list", help="Liste les generations de sauvegarde presentes sur F:")

    p_export = sub.add_parser("export-key", help="Escrow DR : exporte la cle de dechiffrement des backups vers un fichier")
    p_export.add_argument("--out", default=None, help="Chemin du fichier d'escrow (defaut: Bureau)")

    p_backup = sub.add_parser("backup", help="Lance une sauvegarde complete")
    p_backup.add_argument("--dry-run", action="store_true",
                           help="Verifie l'identite du disque sans rien ecrire")
    p_backup.add_argument("--no-offline", action="store_true",
                           help="Ne remet pas le disque offline en fin de backup")
    p_backup.add_argument("--cible-fixe", default=None,
                          help="Racine sur un disque FIXE (ex. E:\\Nokido_backups) : sans diskpart")

    p_af = sub.add_parser("archive-flux",
                          help="Archive LOGIQUE chiffree en flux d'une base SQLite vivante (aucun clair sur disque)")
    p_af.add_argument("--source", required=True, help="fichier .db a archiver")
    p_af.add_argument("--cible", required=True, help="fichier .7z de sortie (disque FIXE)")

    p_av = sub.add_parser("archive-verifier",
                          help="Relit chaque part en un passage, compare au manifeste (rc!=0 si ecart)")
    p_av.add_argument("--archive", required=True, help="fichier .7z a verifier")

    p_ar = sub.add_parser("archive-restaurer",
                          help="Restaure une archive chiffree dans une base NEUVE (jamais par-dessus)")
    p_ar.add_argument("--archive", required=True, help="fichier .7z a restaurer")
    p_ar.add_argument("--dest", required=True, help="base SQLite de destination (doit etre ABSENTE)")

    args = parser.parse_args()

    if args.command == "status":
        return cmd_status()
    if args.command == "online":
        disk_online()
        return 0
    if args.command == "offline":
        disk_offline()
        return 0
    if args.command == "list":
        return cmd_list()
    if args.command == "export-key":
        return cmd_export_key(args.out)
    if args.command == "backup":
        return cmd_backup(dry_run=args.dry_run, do_offline=not args.no_offline,
                          cible_fixe=args.cible_fixe)
    if args.command == "archive-flux":
        cle = _cle_archive()
        man = archive_exporter(Path(args.source), Path(args.cible), cle)
        v = archive_verifier(Path(args.cible), cle)     # relecture IMMEDIATE, toujours
        print(json.dumps({"tables": v["tables"], "parts": v["parts"], "fautes": v["fautes"]}, indent=1))
        attendu = {t: x["lignes"] for t, x in man["tables"].items()}
        return 0 if not v["fautes"] and v["tables"] == attendu else 1
    if args.command == "archive-verifier":
        v = archive_verifier(Path(args.archive), _cle_archive())
        print(json.dumps(v, indent=1))
        return 0 if not v["fautes"] else 1
    if args.command == "archive-restaurer":
        if Path(args.dest).exists():
            raise SystemExit("destination EXISTANTE : refus (jamais de restauration par-dessus une base)")
        print(json.dumps(archive_restaurer(Path(args.archive), _cle_archive(), Path(args.dest)), indent=1))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
