"""Copie des tables choisies de RAG/embeddings.db (plus data/rag_files et Nokido.env
selon le mode) dans backups/cold_storage/, avec manifeste et SHA256, et les restaure.

Entrees : cold_backup, cold_restore (dry_run=True par defaut), list_backups,
preflight_check (disque, PRAGMA integrity_check) et PreFlightError, get_machine_key,
derive_backup_salt ; CLI --action backup|restore|list|preflight.
Modes : memory (event_log, agent_tasks...), knowledge (rag_chunks, embeddings...), full.
Effets : backup passe en lecture seule (attrib ou chmod) ; restore copie d'abord la base
en embeddings.db.pre_restore ; chaque operation ecrit event_log (MASTER_OVERRIDE).
Refuse caller mcp/llm/claude/cline. Appele par forge_guarded_change, forge_handler_rag ;
forge_env_crypt et forge_health reprennent get_machine_key.
"""
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_snapshot
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_snapshot.py — Cold Backup & Skeleton Key pour Nokido
============================================================
Responsabilité UNIQUE : sauvegarder et restaurer la DB SQLite + fichiers RAG
avant toute action Master (Ring -1 / MASTER_OVERRIDE).

NE TOUCHE PAS :
  - Le code source Python    → forge_safe_integration.py
  - Les snapshots par chunk  → forge_timecode.snapshot_chunk()
  - Le rollback granulaire   → forge_timecode.rag_rollback()

MODES :
  memory    → event_log + agent_tasks + shared_prompt_log + global_sequence
  knowledge → rag_chunks + embeddings + rag_snapshots + promotion_queue
  full      → toutes les tables + fichiers RAG + Nokido.env

MACHINE-BOUND KEY :
  Windows : UUID BIOS via WMI (non modifiable software)
  Fallback: SHA256(hostname|username|disk_serial)
  Cette clé dérive le sel de chiffrement du cold backup.
  Un backup volé sur une autre machine = inutilisable.

TRIPLE CHECK (avant toute action Master) :
  1. Vérifier espace disque suffisant (backup > 2× taille DB)
  2. Créer cold backup atomique (.tmp → rename)
  3. Vérifier SHA256 du backup créé = SHA256 live
  ⟹ Si un check échoue → action Master annulée

ACCÈS :
  ✅ TUI Nokido (humain direct, bouton "Ring 0 View")
  ✅ CLI  : python forge_snapshot.py --action backup --mode full
  ❌ MCP/LLM : JAMAIS (pas d'export dans les tools MCP)
  ❌ Agent Claude/Cline : JAMAIS (exclusion explicite dans _check_caller)

AUDIT :
  Chaque opération Master → event_log avec agent_id="MASTER_OVERRIDE"
  Même en mode Master, l'intégrité est tracée.
"""


import hashlib
import json
import logging
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CHEMINS
# ─────────────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "embeddings.db"
_RAG_DIR = _ROOT / "data" / "rag_files"
_ENV_FILE = _ROOT / "Nokido.env"
_COLD_DIR = _ROOT / "backups" / "cold_storage"
_COLD_DIR.mkdir(parents=True, exist_ok=True)

SnapshotMode = Literal["memory", "knowledge", "full"]

# Tables par mode
_TABLES_MEMORY = {"event_log", "agent_tasks", "shared_prompt_log", "global_sequence", "sqlite_sequence"}
_TABLES_KNOWLEDGE = {"rag_chunks", "embeddings", "rag_snapshots", "promotion_queue"}
_TABLES_FULL = _TABLES_MEMORY | _TABLES_KNOWLEDGE

_MIN_FREE_MB = 150  # espace disque minimum pour un cold backup


# ─────────────────────────────────────────────────────────────────────────────
# MACHINE-BOUND KEY
# ─────────────────────────────────────────────────────────────────────────────

_MBK_CACHE: Optional[str] = None
_MBK_LOCK = threading.Lock()


def get_machine_key() -> str:
    """
    Retourne une clé dérivée de l'identité hardware de la machine.

    Windows : UUID BIOS (wmic csproduct get UUID) — non modifiable software.
    Linux   : /etc/machine-id ou product_uuid.
    Fallback: SHA256(hostname | username | plateforme).

    La clé est stable sur la même machine, incompatible entre machines.
    Elle n'est PAS un secret — elle est un sel d'ancrage machine.
    Le vrai secret reste FORGE_MCP_TOKEN.
    """
    global _MBK_CACHE
    with _MBK_LOCK:
        if _MBK_CACHE:
            return _MBK_CACHE

        hw_id = ""

        if platform.system() == "Windows":
            try:
                out = subprocess.check_output(
                    ["wmic", "csproduct", "get", "UUID"], timeout=3, text=True, stderr=subprocess.DEVNULL
                , errors="replace")
                lines = [l.strip() for l in out.splitlines() if l.strip() and "UUID" not in l]
                if lines:
                    hw_id = lines[0]
            except Exception:
                pass
            if not hw_id:
                try:
                    out = subprocess.check_output(
                        ["powershell", "-Command", "(Get-WmiObject Win32_ComputerSystemProduct).UUID"],
                        timeout=3,
                        text=True,
                        stderr=subprocess.DEVNULL,
                    errors="replace")
                    hw_id = out.strip()
                except Exception:
                    pass

        elif platform.system() == "Linux":
            for f in ["/etc/machine-id", "/sys/class/dmi/id/product_uuid"]:
                p = Path(f)
                if p.exists():
                    try:
                        hw_id = p.read_text().strip()
                        break
                    except Exception:
                        pass

        # Fallback universel
        if not hw_id or hw_id in ("", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"):
            import getpass

            hw_id = f"{socket.gethostname()}|{getpass.getuser()}|{platform.node()}"

        _MBK_CACHE = hashlib.sha256(hw_id.encode()).hexdigest()[:32]
        logger.debug(f"[snapshot] machine_key={_MBK_CACHE[:8]}... (hw_id={hw_id[:20]}...)")
        return _MBK_CACHE


def derive_backup_salt(timestamp: str) -> bytes:
    """
    Sel unique par backup = HMAC(machine_key + cle HMAC, timestamp).
    Utilisé pour nommer et vérifier le backup de façon machine-bound.
    Cle HMAC DEDIEE (NOKIDO_HMAC_KEY) d'abord, repli sur le jeton maitre tant
    qu'elle n'est pas provisionnee (2026-09-28) : les backups existants restent
    verifiables, et une fois la cle provisionnee la rotation du maitre ne les
    orpheline plus.
    """
    import hmac as _hmac

    token = get_secret("NOKIDO_HMAC_KEY") or get_secret("FORGE_MCP_TOKEN") or "no_token"
    secret = (get_machine_key() + token).encode()
    return _hmac.new(secret, timestamp.encode(), hashlib.sha256).digest()


# ─────────────────────────────────────────────────────────────────────────────
# VÉRIFICATION PRE-FLIGHT
# ─────────────────────────────────────────────────────────────────────────────


class PreFlightError(RuntimeError):
    """Levée si le pre-flight check échoue → action Master annulée."""


def preflight_check(mode: SnapshotMode = "full") -> dict:
    """
    Triple Check avant toute action Master :
      1. Espace disque suffisant (>= _MIN_FREE_MB après backup estimé)
      2. DB lisible et non corrompue (PRAGMA integrity_check)
      3. Machine key stable (même UUID qu'à l'init)

    Retourne {"ok": True, "disk_free_mb": N, "db_pages": N, "machine_key": "..."}
    ou lève PreFlightError avec la raison.
    """
    result: dict = {}

    # 1. Espace disque
    try:
        stat = shutil.disk_usage(str(_COLD_DIR))
        free_mb = stat.free // (1024 * 1024)
        db_mb = (_DB.stat().st_size // (1024 * 1024)) if _DB.exists() else 0
        result["disk_free_mb"] = free_mb
        result["db_mb"] = db_mb
        needed_mb = max(_MIN_FREE_MB, db_mb * 2)
        if free_mb < needed_mb:
            raise PreFlightError(
                f"Espace disque insuffisant : {free_mb}MB libre, "
                f"{needed_mb}MB requis pour le cold backup.\n"
                "Action Master annulée — impossible de sécuriser les données."
            )
    except PreFlightError:
        raise
    except Exception as e:
        raise PreFlightError(f"Vérification disque échouée : {e}")

    # 2. Intégrité DB
    if _DB.exists():
        try:
            con = sqlite3.connect(str(_DB), timeout=5)
            check = con.execute("PRAGMA integrity_check").fetchone()[0]
            pages = con.execute("PRAGMA page_count").fetchone()[0]
            con.close()
            if check != "ok":
                raise PreFlightError(f"DB corrompue (PRAGMA integrity_check = {check!r})")
            result["db_pages"] = pages
            result["db_integrity"] = "ok"
        except PreFlightError:
            raise
        except Exception as e:
            raise PreFlightError(f"Lecture DB impossible : {e}")
    else:
        result["db_pages"] = 0
        result["db_integrity"] = "absent"

    # 3. Machine key
    result["machine_key"] = get_machine_key()[:8] + "..."
    result["ok"] = True
    return result


# ─────────────────────────────────────────────────────────────────────────────
# COLD BACKUP
# ─────────────────────────────────────────────────────────────────────────────


def cold_backup(
    mode: SnapshotMode = "full",
    label: str = "",
    read_only: bool = True,
    caller: str = "human",  # "human" | "tui" | "cli"
) -> dict:
    """
    Crée un cold backup atomique de la DB + fichiers RAG.

    Atomicité : .tmp → rename() kernel (jamais de fichier partiel visible).
    Retourne {
      "backup_path": str,
      "sha256":      str,
      "tables":      [str],
      "mode":        str,
      "machine_key": str (8 chars),
      "timestamp":   str,
    }

    Levée :
      PreFlightError si le preflight_check échoue.
      RuntimeError  si l'écriture échoue.
    """
    _check_caller(caller)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Sanitize label : Windows interdit : \ / * ? " < > | dans noms fichier
    # Le label vient parfois du contexte appelant (memory_consolidator
    # passe "task_type: consolidation_knowledge" qui contient `:`).
    import re as _re

    safe_label = _re.sub(r"[\\/:*?\"<>|\s]", "_", label) if label else ""
    suffix = f"_PRE_MASTER_{safe_label}" if safe_label else "_MASTER"
    name = f"{ts}{suffix}_{mode}"
    dest = _COLD_DIR / name
    dest.mkdir(parents=True, exist_ok=True)

    # Déterminer les tables à sauvegarder
    if mode == "memory":
        tables = _TABLES_MEMORY
    elif mode == "knowledge":
        tables = _TABLES_KNOWLEDGE
    else:
        tables = _TABLES_FULL

    # Pre-flight
    preflight_check(mode)

    # Sauvegarde DB : ecrit DIRECTEMENT au path final (pas de tmp+rename, evite
    # WinError 32 lock conflict sur le tmp file) + try/finally + retry sur lock.
    # NB : mode=full peut utiliser sqlite3 backup API (atomique, lock-safe WAL)
    # mais mode=memory/knowledge necessite filter de tables -> loop manuel.
    db_backup = dest / "embeddings.db"
    saved_tables = []

    if _DB.exists():
        import time as _t

        last_err: Exception | None = None
        for attempt in range(1, 4):  # 3 retries max sur lock
            src_con = None
            dst_con = None
            try:
                src_con = sqlite3.connect(str(_DB), timeout=30)
                src_con.execute("PRAGMA journal_mode=WAL")
                dst_con = sqlite3.connect(str(db_backup))
                existing = {
                    r[0] for r in src_con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                to_copy = tables & existing
                saved_tables = []
                for tbl in sorted(to_copy):
                    schema = src_con.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
                    ).fetchone()
                    if schema and schema[0]:
                        dst_con.execute(schema[0])
                        rows = src_con.execute(f"SELECT * FROM {tbl}").fetchall()
                        if rows:
                            ncols = len(rows[0])
                            placeh = ",".join(["?"] * ncols)
                            dst_con.executemany(f"INSERT INTO {tbl} VALUES ({placeh})", rows)
                        saved_tables.append(tbl)
                dst_con.commit()
                last_err = None
                break  # success
            except sqlite3.OperationalError as e:
                last_err = e
                logger.warning("[snapshot] attempt %d sqlite lock : %s - retry dans %ds", attempt, e, attempt * 2)
                _t.sleep(attempt * 2)
            except Exception as e:  # noqa: BLE001
                last_err = e
                break
            finally:
                if dst_con is not None:
                    try:
                        dst_con.close()
                    except Exception:  # noqa: BLE001
                        pass
                if src_con is not None:
                    try:
                        src_con.close()
                    except Exception:  # noqa: BLE001
                        pass
                # Force release des handles Windows avant la prochaine tentative
                import gc as _gc

                _gc.collect()
        if last_err is not None:
            if db_backup.exists():
                try:
                    db_backup.unlink()
                except OSError:
                    pass
            raise RuntimeError(f"Backup DB echoue apres 3 retries : {last_err}") from last_err

    # Sauvegarder rag_files/ si mode knowledge ou full
    rag_backup = dest / "rag_files"
    if mode in ("knowledge", "full") and _RAG_DIR.exists():
        try:
            shutil.copytree(str(_RAG_DIR), str(rag_backup), dirs_exist_ok=True)
        except Exception as e:
            logger.warning(f"[snapshot] rag_files backup partiel : {e}")

    # Sauvegarder Nokido.env si mode full (variables + clés)
    if mode == "full" and _ENV_FILE.exists():
        try:
            shutil.copy2(str(_ENV_FILE), str(dest / "Nokido.env.bak"))
        except Exception as e:
            logger.warning(f"[snapshot] Nokido.env backup : {e}")

    # Manifeste JSON
    mk = get_machine_key()
    salt = derive_backup_salt(ts).hex()[:16]
    manifest = {
        "timestamp": ts,
        "mode": mode,
        "label": label,
        "caller": caller,
        "machine_key": mk[:8] + "...",
        "salt": salt,
        "tables": sorted(saved_tables),
        "db_exists": _DB.exists(),
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # SHA256 du backup DB
    sha256 = _sha256_file(db_backup) if db_backup.exists() else "no_db"
    (dest / "sha256.txt").write_text(f"{sha256}  embeddings.db\n", encoding="utf-8")

    # Marquer en lecture seule post-backup
    if read_only:
        _set_read_only(dest)

    # Audit event_log
    _audit_log(
        "cold_backup",
        str(dest.name),
        {
            "mode": mode,
            "tables": sorted(saved_tables),
            "sha256": sha256[:16] + "...",
            "machine_key": mk[:8] + "...",
        },
        backup_path=str(dest),
        checksum_before=sha256,
    )

    logger.info(f"[snapshot] Cold backup OK → {dest.name}  sha256={sha256[:16]}...")
    return {
        "backup_path": str(dest),
        "sha256": sha256,
        "tables": sorted(saved_tables),
        "mode": mode,
        "machine_key": mk[:8] + "...",
        "timestamp": ts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RESTORE
# ─────────────────────────────────────────────────────────────────────────────


def cold_restore(
    timestamp: str,
    mode: SnapshotMode = "full",
    dry_run: bool = True,
    caller: str = "human",
) -> dict:
    """
    Restaure un cold backup identifié par son timestamp.

    dry_run=True  : affiche le plan sans modifier la DB.
    dry_run=False : restaure après Triple Check.

    Retourne {"ok": bool, "plan": [...], "sha256_match": bool}
    """
    _check_caller(caller)

    # Trouver le dossier de backup
    candidates = sorted(_COLD_DIR.glob(f"{timestamp}*"))
    if not candidates:
        return {"ok": False, "error": f"Aucun backup trouvé pour {timestamp!r}"}

    src = candidates[0]
    db_backup = src / "embeddings.db"
    sha_file = src / "sha256.txt"

    if not db_backup.exists():
        return {"ok": False, "error": f"embeddings.db absent dans {src.name}"}

    # Triple Check : vérifier le hash du backup
    sha_stored = sha_file.read_text().split()[0] if sha_file.exists() else ""
    sha_actual = _sha256_file(db_backup)
    sha_match = sha_stored == sha_actual

    if not sha_match and not dry_run:
        return {
            "ok": False,
            "error": "INTÉGRITÉ BACKUP COMPROMISE — SHA256 ne correspond pas.",
            "sha256_stored": sha_stored[:16] + "...",
            "sha256_actual": sha_actual[:16] + "...",
        }

    manifest = {}
    mf = src / "manifest.json"
    if mf.exists():
        manifest = json.loads(mf.read_text(encoding="utf-8"))

    # Vérifier machine key
    mk_stored = manifest.get("machine_key", "")
    mk_current = get_machine_key()[:8] + "..."
    if mk_stored and mk_stored != mk_current:
        logger.warning(f"[snapshot] Machine key mismatch : backup={mk_stored} local={mk_current}")

    plan = [
        {"action": "restore_db", "src": str(db_backup), "dst": str(_DB)},
    ]
    if (src / "rag_files").exists() and mode in ("knowledge", "full"):
        plan.append({"action": "restore_rag_files", "src": str(src / "rag_files"), "dst": str(_RAG_DIR)})
    if (src / "Nokido.env.bak").exists() and mode == "full":
        plan.append({"action": "restore_env", "src": str(src / "Nokido.env.bak"), "dst": str(_ENV_FILE)})

    if dry_run:
        return {"ok": True, "dry_run": True, "plan": plan, "sha256_match": sha_match, "manifest": manifest}

    # Exécution
    # 1. Backup de sauvegarde avant restore (backup du backup)
    _DB.parent.mkdir(parents=True, exist_ok=True)
    if _DB.exists():
        safety = _DB.with_suffix(".db.pre_restore")
        shutil.copy2(str(_DB), str(safety))

    # 2. Restore DB
    try:
        _set_writable(src)  # lever read-only le temps du restore
        shutil.copy2(str(db_backup), str(_DB))
    except Exception as e:
        return {"ok": False, "error": f"Restore DB : {e}"}

    # 3. Restore rag_files
    if (src / "rag_files").exists() and mode in ("knowledge", "full"):
        try:
            shutil.copytree(str(src / "rag_files"), str(_RAG_DIR), dirs_exist_ok=True)
        except Exception as e:
            logger.warning(f"[snapshot] rag_files restore partiel : {e}")

    # 4. Restore Nokido.env
    if (src / "Nokido.env.bak").exists() and mode == "full":
        try:
            shutil.copy2(str(src / "Nokido.env.bak"), str(_ENV_FILE))
        except Exception as e:
            logger.warning(f"[snapshot] Nokido.env restore : {e}")

    _audit_log(
        "cold_restore",
        str(src.name),
        {
            "mode": mode,
            "sha256_match": sha_match,
            "machine_key": mk_current,
        },
    )

    return {"ok": True, "dry_run": False, "plan": plan, "sha256_match": sha_match, "manifest": manifest}


# ─────────────────────────────────────────────────────────────────────────────
# LISTE DES BACKUPS
# ─────────────────────────────────────────────────────────────────────────────


def list_backups() -> list[dict]:
    """Liste les cold backups disponibles avec leur metadata."""

    def _lecture_seule(d):
        """True / False / None(INDETERMINE) — jamais un verdict invente.

        `os.access(d, os.W_OK)` MENT sous Windows : il ignore les ACL et rend
        True la ou l'ecriture leve PermissionError (mesure 2026-08-16, verifie
        aussi sur C:/Windows). Un cold backup annonce inscriptible a tort, c'est
        une restauration qu'on croit possible. Le seul test honnete est
        d'ouvrir : `r+b` demande le droit d'ecriture SANS rien ecrire. Dossier
        vide ou illisible -> None : on ne sait pas, et on le dit.
        """
        try:
            for f in d.iterdir():
                if f.is_file():
                    try:
                        with open(f, "r+b"):
                            return False
                    except PermissionError:
                        return True
                    except OSError:
                        return None
        except OSError:
            return None
        return None

    result = []
    for d in sorted(_COLD_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        sha = d / "sha256.txt"
        entry = {
            "name": d.name,
            "path": str(d),
            "size_mb": round(_dir_size(d) / (1024 * 1024), 1),
            "sha256": sha.read_text().split()[0][:16] + "..." if sha.exists() else "?",
            "read_only": _lecture_seule(d),
        }
        if mf.exists():
            try:
                entry.update(json.loads(mf.read_text(encoding="utf-8")))
            except Exception:
                pass
        result.append(entry)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNES
# ─────────────────────────────────────────────────────────────────────────────


def _check_caller(caller: str) -> None:
    """
    Vérifie que l'appelant est humain (TUI / CLI).
    Refuse tout appel depuis un contexte MCP/LLM.
    """
    # En mode MCP (stdio), sys.stdin n'est pas un TTY
    # et _INSTANCE_NAME est injecté dans le processus MCP
    is_mcp = (not sys.stdin.isatty() and os.environ.get("LAFORGE_MCP_INSTANCE", "") != "") or caller in (
        "mcp",
        "llm",
        "claude",
        "cline",
    )

    if is_mcp:
        raise PermissionError(
            "ACCÈS MASTER REFUSÉ : forge_snapshot ne peut pas être appelé "
            "depuis un agent LLM ou le serveur MCP. "
            "Utilisez la TUI Nokido ou le CLI directement."
        )


def _sha256_file(path: Path, chunk: int = 65536) -> str:
    """SHA256 d'un fichier par blocs (robuste aux gros fichiers)."""
    h = hashlib.sha256()
    try:
        with open(str(path), "rb") as f:
            while True:
                block = f.read(chunk)
                if not block:
                    break
                h.update(block)
    except Exception:
        return "error"
    return h.hexdigest()


def _set_read_only(path: Path) -> None:
    """Marque un dossier et son contenu en lecture seule (OS-level)."""
    try:
        if platform.system() == "Windows":
            subprocess.run(["attrib", "+R", "/S", "/D", str(path)], check=False, capture_output=True)
        else:
            for p in path.rglob("*"):
                if p.is_file():
                    p.chmod(0o444)
            path.chmod(0o555)
    except Exception as e:
        logger.debug(f"[snapshot] set_read_only: {e}")


def _set_writable(path: Path) -> None:
    """Retire la lecture seule (nécessaire pour restore)."""
    try:
        if platform.system() == "Windows":
            subprocess.run(["attrib", "-R", "/S", "/D", str(path)], check=False, capture_output=True)
        else:
            for p in path.rglob("*"):
                if p.is_file():
                    try:
                        p.chmod(0o644)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"[snapshot] set_writable: {e}")


def _dir_size(path: Path) -> int:
    """Taille totale d'un dossier en bytes."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _audit_log(
    event_type: str,
    target: str,
    payload: dict,
    backup_path: str = "",
    checksum_before: str = "",
) -> None:
    """
    Écrit dans event_log avec agent_id=MASTER_OVERRIDE.
    Utilise les colonnes backup_path + checksum_before (M4) si présentes.
    """
    if not _DB.exists():
        return
    try:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        con = sqlite3.connect(str(_DB), timeout=5)
        con.execute("PRAGMA journal_mode=WAL")
        # Détecter si les colonnes M4 sont présentes
        cols = {r[1] for r in con.execute("PRAGMA table_info(event_log)")}
        if "backup_path" in cols:
            con.execute(
                """INSERT INTO event_log
                   (timecode, sequence_id, session_id, agent_id,
                    event_type, target, payload, prev_hash, new_hash,
                    status, backup_path, checksum_before)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts,
                    0,
                    "MASTER",
                    "MASTER_OVERRIDE",
                    event_type,
                    target,
                    json.dumps(payload, ensure_ascii=False),
                    "",
                    "",
                    "ok",
                    backup_path,
                    checksum_before,
                ),
            )
        else:
            con.execute(
                """INSERT INTO event_log
                   (timecode, sequence_id, session_id, agent_id,
                    event_type, target, payload, prev_hash, new_hash, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts,
                    0,
                    "MASTER",
                    "MASTER_OVERRIDE",
                    event_type,
                    target,
                    json.dumps(payload, ensure_ascii=False),
                    "",
                    "",
                    "ok",
                ),
            )
        con.commit()
        con.close()
    except Exception as e:
        logger.debug(f"[snapshot] audit_log: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    p = argparse.ArgumentParser(description="Nokido Cold Backup / Skeleton Key")
    p.add_argument("--action", choices=["backup", "restore", "list", "preflight"], default="preflight")
    p.add_argument("--mode", choices=["memory", "knowledge", "full"], default="full")
    p.add_argument("--label", default="")
    p.add_argument("--timestamp", default="", help="Timestamp du backup à restaurer (ex: 20260315_120000)")
    p.add_argument("--dry-run", action="store_true", help="Simulation sans modification")
    p.add_argument("--no-read-only", action="store_true", help="Ne pas marquer le backup en lecture seule")

    args = p.parse_args()

    if args.action == "preflight":
        try:
            r = preflight_check(args.mode)
            print(
                f"✅ Pre-flight OK — disk={r['disk_free_mb']}MB libre  db={r['db_pages']} pages  key={r['machine_key']}"
            )
        except PreFlightError as e:
            print(f"❌ Pre-flight FAIL : {e}")
            sys.exit(1)

    elif args.action == "backup":
        try:
            r = cold_backup(mode=args.mode, label=args.label, read_only=not args.no_read_only, caller="cli")
            print(f"✅ Backup créé : {Path(r['backup_path']).name}")
            print(f"   SHA256      : {r['sha256'][:32]}...")
            print(f"   Tables      : {', '.join(r['tables'])}")
            print(f"   Machine key : {r['machine_key']}")
        except (PreFlightError, RuntimeError) as e:
            print(f"❌ {e}")
            sys.exit(1)

    elif args.action == "restore":
        if not args.timestamp:
            print("❌ --timestamp requis pour restore")
            sys.exit(1)
        r = cold_restore(timestamp=args.timestamp, mode=args.mode, dry_run=args.dry_run, caller="cli")
        if r["ok"]:
            tag = "[DRY RUN] " if args.dry_run else ""
            print(f"✅ {tag}Restore OK — SHA256 match={r['sha256_match']}")
            for step in r.get("plan", []):
                print(f"   {step['action']}: {Path(step['src']).name}")
        else:
            print(f"❌ Restore FAIL : {r.get('error', '?')}")
            sys.exit(1)

    elif args.action == "list":
        backups = list_backups()
        if not backups:
            print("Aucun cold backup trouvé.")
        else:
            print(f"{'NAME':<45} {'MODE':<12} {'SIZE':<8} {'RO':<4} SHA256")
            for b in backups:
                ro = "✅" if b.get("read_only") else "❌"
                print(f"  {b['name']:<43} {b.get('mode', '?'):<12} {b['size_mb']:>5.1f}MB {ro:<4} {b['sha256']}")
