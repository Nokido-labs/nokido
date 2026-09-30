"""forge_db_preflight.py — self-heal de la DB RAG au démarrage du hub.

Câblé en tête de nokido_hub.py (AVANT toute connexion sqlite). À chaque
(re)start du hub, vérifie l'intégrité de RAG/embeddings.db :
  - "ok"            -> rien, le hub ouvre normalement.
  - locked/busy     -> une autre instance tient déjà la DB -> ne touche à rien.
  - malformed/corrupt -> purge -wal/-shm périmés + restaure le backup sain le
    plus récent (C:\\LaForge_data\\backups\\*.db, sinon C:\\LaForge_data\\embeddings.db).

But : casser tout crash-loop sur DB corrompue SANS intervention manuelle.
Cause racine de l'incident 2026-06-02 : symlink RAG->V: -> -wal/-shm créés côté
C: pendant que la DB était sur V: -> WAL appliqué de travers au restart ->
"malformed". Fix structurel = DB en fichier réel sur C: (plus de symlink) +
ce preflight qui auto-restaure si ça se reproduit.

JAMAIS d'exception propagée : un échec du self-heal ne doit pas empêcher le boot.
"""
import os
import shutil
import sqlite3
import time

# Chemin DERIVE du fichier (phase 0 du renommage vers Nokido) : tools/ -> parent.parent.
DEFAULT_DB = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
BACKUPS_DIR = r"C:\LaForge_data\backups"
FALLBACK_BACKUP = r"C:\LaForge_data\embeddings.db"
_CORRUPT_MARKERS = ("malformed", "disk image", "corrupt", "not a database")

# Mode RESCUE : vérification FULL (quick_check, scan complet) au lieu du check
# header rapide. Déclencheurs : env LAFORGE_DB_RESCUE=1, fichier sandbox/db_rescue.flag
# (one-shot), ou -wal résiduel (shutdown non-propre = corruption probable, incident
# 2026-06-02). Sinon header rapide ~1s vs quick_check 8Go sur V: chiffré ~3min.
_RESCUE_FLAG = os.path.join(
    os.path.dirname(os.path.dirname(DEFAULT_DB)), "sandbox", "db_rescue.flag"
)


def _log(msg):
    try:
        sb = os.path.join(os.path.dirname(os.path.dirname(DEFAULT_DB)), "sandbox")
        os.makedirs(sb, exist_ok=True)
        with open(os.path.join(sb, "db_preflight.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass
    print(f"[db_preflight] {msg}", flush=True)


def _integrity(db_path):
    """Retourne 'ok' | 'locked' | 'corrupt' | 'missing'."""
    if not os.path.exists(db_path):
        return "missing"
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            row = c.execute("PRAGMA quick_check(1)").fetchone()
        finally:
            c.close()
        return "ok" if row and row[0] == "ok" else "corrupt"
    except sqlite3.OperationalError as e:
        s = str(e).lower()
        if "locked" in s or "busy" in s:
            return "locked"
        if any(m in s for m in _CORRUPT_MARKERS):
            return "corrupt"
        return "locked"  # prudence : inconnu non-corrupt -> ne pas restaurer
    except sqlite3.DatabaseError as e:
        s = str(e).lower()
        if any(m in s for m in _CORRUPT_MARKERS):
            return "corrupt"
        return "corrupt"


def _integrity_fast(db_path):
    """Check HEADER cheap (~1s) : ouvre + schema_version + lecture sqlite_master.
    Détecte malformed / not-a-database / header corrompu SANS scanner toute la DB
    (quick_check lit les 8Go sur V: chiffré = ~3min). Pour le boot propre.
    Retourne 'ok' | 'locked' | 'corrupt' | 'missing'."""
    if not os.path.exists(db_path):
        return "missing"
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            c.execute("PRAGMA schema_version").fetchone()
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            c.close()
        return "ok"
    except sqlite3.OperationalError as e:
        s = str(e).lower()
        if "locked" in s or "busy" in s:
            return "locked"
        if any(m in s for m in _CORRUPT_MARKERS):
            return "corrupt"
        return "locked"
    except sqlite3.DatabaseError as e:
        s = str(e).lower()
        if any(m in s for m in _CORRUPT_MARKERS):
            return "corrupt"
        return "corrupt"


def _wal_residual_bytes(db_path):
    """Taille du -wal résiduel au boot. >0 alors qu'aucune autre instance ne tient
    la DB = WAL non checkpointé au dernier arrêt = shutdown non-propre (cause racine
    de l'incident 2026-06-02). 0 / absent = arrêt propre."""
    try:
        wal = db_path + "-wal"
        return os.path.getsize(wal) if os.path.exists(wal) else 0
    except OSError:
        return 0


def _should_deep_check(db_path):
    """(deep: bool, raison: str). RESCUE (full quick_check d'emblée) ssi FORCÉ
    (env LAFORGE_DB_RESCUE=1 ou sandbox/db_rescue.flag). Sinon header rapide.

    NB : un -wal résiduel (WAL non checkpointé après un kill) N'EST PAS une
    corruption — SQLite le rejoue à l'ouverture (WAL = crash-safe). Le gater
    forcerait un quick_check 8Go à chaque restart hard-kill = inutile. Si le header
    rapide flaire corrompu, self_heal escalade au full quick_check AVANT tout
    restore destructif."""
    if os.environ.get("LAFORGE_DB_RESCUE", "").lower() in ("1", "true", "yes"):
        return True, "LAFORGE_DB_RESCUE=1 (force)"
    if os.path.exists(_RESCUE_FLAG):
        try:
            os.remove(_RESCUE_FLAG)  # one-shot : consommé au boot
        except OSError:
            pass
        return True, "sandbox/db_rescue.flag (force one-shot)"
    return False, f"header rapide (-wal={_wal_residual_bytes(db_path)}o, escalade full si KO)"


def _best_backup():
    """Backup sain le plus récent (mtime), sinon fallback."""
    cands = []
    if os.path.isdir(BACKUPS_DIR):
        for fn in os.listdir(BACKUPS_DIR):
            if fn.endswith(".db"):
                p = os.path.join(BACKUPS_DIR, fn)
                cands.append((os.path.getmtime(p), p))
    cands.sort(reverse=True)
    for _, p in cands:
        if _integrity(p) == "ok":
            return p
    if os.path.exists(FALLBACK_BACKUP) and _integrity(FALLBACK_BACKUP) == "ok":
        return FALLBACK_BACKUP
    return None


def relocate_if_symlink(db_path):
    """Si db_path est un symlink (typiquement -> V:), le remplace par un FICHIER
    RÉEL au même chemin (sur C:). C'est le symlink->V: qui cassait l'atomicité WAL
    (incident 2026-06-02). À exécuter au boot (DB non verrouillée). CONSERVATEUR :
    si la cible est verrouillée / illisible, ne touche à rien (ne casse jamais).
    """
    try:
        if not os.path.islink(db_path):
            return "already-real"
        target = os.path.realpath(db_path)
        if not os.path.exists(target):
            _log(f"relocate: cible symlink absente ({target}) -> skip")
            return "no-target"
        # checkpoint WAL de la cible pour intégrer les écritures avant copie.
        # Si verrouillée -> une autre instance écrit encore -> skip (ne casse rien).
        try:
            c = sqlite3.connect(target, timeout=5)
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            ok = c.execute("PRAGMA quick_check(1)").fetchone()
            c.close()
            if not (ok and ok[0] == "ok"):
                _log(f"relocate: cible {target} pas 'ok' au quick_check -> skip")
                return "target-not-ok"
        except sqlite3.OperationalError as e:
            _log(f"relocate: cible verrouillée/occupée ({str(e)[:50]}) -> skip")
            return "locked"
        tmp = db_path + ".reloc"
        if os.path.exists(tmp):
            os.remove(tmp)
        shutil.copyfile(target, tmp)
        # vérifier la copie avant de toucher au symlink
        cc = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True, timeout=10)
        v = cc.execute("PRAGMA quick_check(1)").fetchone()
        cc.close()
        if not (v and v[0] == "ok"):
            os.remove(tmp)
            _log("relocate: copie corrompue -> abort (symlink intact)")
            return "copy-bad"
        os.unlink(db_path)  # retire le symlink (pas la cible)
        os.rename(tmp, db_path)  # fichier réel au chemin canonique
        # purge d'éventuels -wal/-shm périmés côté symlink
        for ext in ("-wal", "-shm"):
            f = db_path + ext
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        _log(f"relocate: {db_path} symlink->fichier réel C: (depuis {target}) OK")
        return "relocated"
    except Exception as e:
        _log(f"relocate exception (ignorée): {str(e)[:120]}")
        return "error"


def boot_db(db_path):
    """Séquence boot : décide RAPIDE vs RESCUE, relocalise si symlink->V:, self-heal.

    RAPIDE (header ~1s) par défaut. RESCUE (full quick_check 8Go ~3min sur V:
    chiffré) ssi LAFORGE_DB_RESCUE=1, sandbox/db_rescue.flag, ou -wal résiduel
    (shutdown non-propre). Gain boot mesuré : ~196s -> ~8s en mode rapide.
    """
    deep, reason = _should_deep_check(db_path)
    _log(f"boot_db mode={'RESCUE (full quick_check)' if deep else 'RAPIDE (header)'} — {reason}")
    relocate_if_symlink(db_path)
    return self_heal(db_path, deep=deep)


def _parent_is_junction(db_path):
    """RAG/ (parent de la DB) est-il une jonction / reparse-point (Windows) ou un
    symlink (POSIX) ? Si oui ET la DB est 'missing', le volume chiffré n'est
    probablement pas (encore) monté -> NE PAS restaurer (données intactes, attendre).
    Couvre la race boot : boot task SYSTEM monte V: avant les services delayed-auto,
    mais si le hub démarre avant le mount, RAG/embeddings.db (jonction->V:) est
    introuvable sans que la DB soit réellement perdue. Voir incident 2026-06-02."""
    parent = os.path.dirname(os.path.abspath(db_path))
    try:
        if os.name == "nt":
            import stat as _stat
            return bool(os.lstat(parent).st_file_attributes & _stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return os.path.islink(parent)
    except (OSError, AttributeError):
        return False


def self_heal(db_path=DEFAULT_DB, deep=False):
    """Vérifie + restaure si corrompu. Ne lève jamais. Retourne le statut.

    deep=True  -> _integrity full (quick_check, scan complet : mode RESCUE).
    deep=False -> _integrity_fast (header ~1s : boot normal)."""
    try:
        status = (_integrity if deep else _integrity_fast)(db_path)
        if status == "corrupt" and not deep:
            # Header KO en mode rapide -> CONFIRMER au full quick_check avant le
            # restore destructif (évite de restaurer sur un faux-positif header).
            _log("header rapide KO -> escalade full quick_check pour confirmer")
            status = _integrity(db_path)
        if status == "ok":
            return "ok"
        if status == "locked":
            _log("DB verrouillée par une autre instance -> skip (pas de restore)")
            return "locked"
        if status == "missing":
            if _parent_is_junction(db_path):
                _log(f"DB absente ET RAG/ est une jonction -> volume chiffré non monté ? "
                     f"SKIP self-heal (PAS de restore, données chiffrées intactes, attend le mount): {db_path}")
                return "skip-unmounted"
            _log(f"DB absente : {db_path}")
        else:
            _log(f"DB CORROMPUE détectée ({db_path}) -> self-heal")
        backup = _best_backup()
        if not backup:
            _log("AUCUN backup sain disponible -> abandon self-heal (boot continue)")
            return "no-backup"
        # purge DB cassée + WAL/SHM périmés (cause de re-corruption)
        for ext in ("", "-wal", "-shm"):
            f = db_path + ext
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError as e:
                    _log(f"impossible de purger {f}: {e} -> DB encore verrouillée, skip")
                    return "locked"
        shutil.copyfile(backup, db_path)
        post = _integrity(db_path)
        _log(f"restauré depuis {backup} ({round(os.path.getsize(db_path)/1e9,2)}GB) -> {post}")
        return "restored" if post == "ok" else "restore-failed"
    except Exception as e:  # ne JAMAIS casser le boot
        _log(f"self_heal exception (ignorée): {str(e)[:120]}")
        return "error"


if __name__ == "__main__":
    import sys as _sys

    # Rescue manuel : forge_db_preflight.py --deep   (full quick_check)
    _deep = "--deep" in _sys.argv or "--rescue" in _sys.argv
    print(self_heal(deep=_deep))
