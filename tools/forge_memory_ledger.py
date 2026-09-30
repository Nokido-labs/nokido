"""forge_memory_ledger.py - gate de secours BLOCKCHAIN pour la memoire .claude.

Probleme : MEMORY.md (index chaud) deborde le cap charge en session -> entrees
DROPPEES au load. Le compactor (forge_memory_compactor) deplace en archive froide
mais sans integrite ni metadonnees DB -> rien ne prouve qu'on n'a rien perdu.

Ce gate : table append-only `memory_ledger` qui enregistre CHAQUE VERSION de CHAQUE
fichier memoire (metadonnees + CONTENU complet + sha256 + chain_hash). Append-only +
hash-chaine (facon blockchain) -> tamper-evident, ordonne, et RIEN n'est perdu : meme
si MEMORY.md tronque OU si un fichier-topic est supprime/corrompu, le ledger prouve son
existence et conserve son contenu (recuperable). Reutilise le pattern hash-chain de
forge_timecode/forge_swarm. Cable au SessionStart (apres compaction).

    LAFORGE_PYTHON tools/forge_memory_ledger.py sync     # append toute nouvelle version
    LAFORGE_PYTHON tools/forge_memory_ledger.py verify   # verifie l'integrite de la chaine
    LAFORGE_PYTHON tools/forge_memory_ledger.py status   # registre complet (autoritaire, hors MEMORY.md)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_REL = ".claude/projects/C--Users-user-Script-python-IA/memory"


def _resolve_dir() -> Path:
    """Resout le dossier memoire SANS se fier a expanduser seul.

    Mesure 2026-08-11 : sous un compte de service (LaForgeTrusted, run_job),
    HOME vaut C:/Users/Default -> expanduser("~") pointe un dossier ABSENT et
    sqlite3.connect leve OperationalError. Le garde du compactor coupait alors
    ("ledger indisponible") alors que le ledger reel est intact.
    """
    env = os.environ.get("NOKIDO_MEMORY_DIR") or os.environ.get("CLAUDE_MEMORY_DIR")
    if env:
        return Path(env)
    p = Path(os.path.expanduser("~/" + _REL))
    if p.is_dir():
        return p
    fallback = Path("%USERPROFILE%") / _REL
    return fallback if fallback.is_dir() else p


DIR = _resolve_dir()
DB = DIR / "_memory_ledger.db"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS memory_ledger ("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, fname TEXT, name TEXT, mtype TEXT, "
    "description TEXT, sha256 TEXT, size INTEGER, event TEXT, content TEXT, "
    "prev_hash TEXT, chain_hash TEXT)"
)
# `sync` (via `_last`) et `prune` posent UNE requete `WHERE fname=?` par fichier
# memoire. Sans index, 975 balayages d'une table qui porte les textes entiers :
# 5 s au calme, et le hook SessionStart tue a 8 s a CHAQUE demarrage (mesure
# 2026-09-26, 47 fois sur 47) -- la reingestion de MEMORY.md, placee apres, n'etait
# jamais atteinte. NR : tests/nr/test_memory_ledger_index_fname_nr.py.
INDEX = "CREATE INDEX IF NOT EXISTS idx_memory_ledger_fname_seq ON memory_ledger(fname, seq)"


def _conn(db=None):
    c = sqlite3.connect(str(db or DB), timeout=5)
    c.execute(SCHEMA)
    try:
        c.execute(INDEX)
    except sqlite3.OperationalError:  # muet-ok : compte en lecture seule (sandbox du hub) ;
        pass  # il lit sans index, plus lentement, et le premier ecrivain le posera
    return c


def _meta(text):
    """Parse le frontmatter (name/type/description) sans regex."""
    name = mtype = desc = ""
    for ln in text.splitlines()[:18]:
        s = ln.strip()
        if s.startswith("name:") and not name:
            name = s[5:].strip()
        elif s.startswith("type:") and not mtype:
            mtype = s[5:].strip()
        elif s.startswith("description:") and not desc:
            desc = s[12:].strip().strip('"')
    return name, mtype, desc


def _last(conn, fname):
    r = conn.execute(
        "SELECT sha256, event, size, ts FROM memory_ledger WHERE fname=? ORDER BY seq DESC LIMIT 1",
        (fname,),
    ).fetchone()
    return r if r else (None, None, None, None)


# Tranche tournante du mode rapide : chaque fiche est rehachee au moins un jour sur
# _TRANCHES, meme si sa taille et sa date n'ont pas bouge (cf. sync).
_TRANCHES = 10


def _dans_la_tranche_du_jour(fname, jour=None):
    if jour is None:
        jour = int(time.time() // 86400)
    h = int(hashlib.sha256(fname.encode("utf-8")).hexdigest()[:8], 16)
    return h % _TRANCHES == jour % _TRANCHES


def _tip(conn):
    r = conn.execute("SELECT chain_hash FROM memory_ledger ORDER BY seq DESC LIMIT 1").fetchone()
    return r[0] if r else ""


def _append(conn, fname, name, mtype, desc, sha, size, event, content):
    prev = _tip(conn)
    ts = time.time()
    chain = hashlib.sha256((prev + fname + sha + str(ts) + event).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO memory_ledger"
        "(ts,fname,name,mtype,description,sha256,size,event,content,prev_hash,chain_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ts, fname, name, mtype, desc[:300], sha, size, event, content, prev, chain),
    )


def sync(memory_dir=None, rapide=False):
    """Append une entree chainee pour chaque fichier nouveau/modifie/supprime. Idempotent.

    rapide=True (hook SessionStart) : une fiche dont la taille et la date de
    modification n'ont pas bouge depuis sa derniere entree n'est ni ouverte ni
    hachee. Mesure 2026-09-26 : ouvrir et hacher les 975 fiches coutait 6,0 s a
    froid (0,26 s a chaud) et faisait tuer le hook a 8 s a chaque demarrage.
    Limite : un contenu change a taille et date identiques passe inapercu -- la
    tranche du jour (1 fiche sur _TRANCHES, tournante) est donc hachee quoi qu'il
    arrive. Sans le drapeau, tout est hache : c'est le filet des appelants qui
    ecrivent. NR : tests/nr/test_memory_ledger_sync_rapide_nr.py.
    """
    memory_dir = Path(memory_dir) if memory_dir else DIR
    db = memory_dir / "_memory_ledger.db"
    conn = _conn(db)
    n = 0
    present = set()
    # Sous Windows, DirEntry.stat() vient du listage du dossier : aucune fiche ouverte.
    stats = {e.name: e.stat() for e in os.scandir(memory_dir)} if rapide else {}
    for f in sorted(memory_dir.glob("*.md")):
        present.add(f.name)
        last_sha, last_ev, last_size, last_ts = _last(conn, f.name)
        if rapide and last_sha is not None and last_ev != "deleted":
            st = stats.get(f.name) or f.stat()
            if (last_size == st.st_size and last_ts is not None and st.st_mtime <= last_ts
                    and not _dans_la_tranche_du_jour(f.name)):
                continue
        raw = f.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if last_sha == sha and last_ev != "deleted":
            continue
        text = raw.decode("utf-8", "replace")
        nm, mt, ds = _meta(text)
        ev = "created" if last_sha is None else ("recreated" if last_ev == "deleted" else "updated")
        _append(conn, f.name, nm or f.stem, mt, ds, sha, len(raw), ev, text)
        n += 1
    for (fn,) in conn.execute("SELECT DISTINCT fname FROM memory_ledger").fetchall():
        if fn in present:
            continue
        ls, le, _, _ = _last(conn, fn)
        if le and le != "deleted":
            _append(conn, fn, fn, "", "", ls or "", 0, "deleted", "")
            n += 1
    conn.commit()
    conn.close()
    return {"appended": n, "db": str(db)}


def verify():
    """Recalcule toute la chaine ; signale toute rupture (tamper/perte)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT seq,ts,fname,sha256,event,prev_hash,chain_hash FROM memory_ledger ORDER BY seq"
    ).fetchall()
    prev = ""
    broken = []
    for seq, ts, fn, sha, ev, ph, ch in rows:
        exp = hashlib.sha256((prev + fn + sha + str(ts) + ev).encode("utf-8")).hexdigest()
        if ph != prev or ch != exp:
            broken.append(seq)
        prev = ch
    conn.close()
    return {"entries": len(rows), "broken": broken, "ok": not broken}


def status():
    """Registre AUTORITAIRE : tous les fichiers traces (etat courant), independant de MEMORY.md."""
    conn = _conn()
    rows = conn.execute(
        "SELECT fname, name, mtype, event, MAX(seq), COUNT(*) FROM memory_ledger GROUP BY fname ORDER BY fname"
    ).fetchall()
    live = [r for r in rows if r[3] != "deleted"]
    conn.close()
    return {
        "tracked_files": len(rows),
        "live": len(live),
        "deleted": len(rows) - len(live),
        "files": [{"fname": r[0], "name": r[1], "type": r[2], "versions": r[5]} for r in live],
    }


def recover(fname, out_dir=None):
    """Recupere la derniere version NON supprimee du contenu d'un fichier depuis le ledger."""
    conn = _conn()
    r = conn.execute(
        "SELECT content, sha256 FROM memory_ledger WHERE fname=? AND event!='deleted' ORDER BY seq DESC LIMIT 1",
        (fname,),
    ).fetchone()
    conn.close()
    if not r:
        return {"ok": False, "error": f"{fname} absent du ledger"}
    if out_dir:
        p = Path(out_dir) / fname
        p.write_text(r[0], encoding="utf-8")
        return {"ok": True, "restored_to": str(p), "sha256": r[1]}
    return {"ok": True, "sha256": r[1], "bytes": len(r[0].encode("utf-8"))}


def prune(keep_per_file: int = 2):
    """Borne la croissance : garde le CONTENU des keep_per_file dernieres versions par
    fichier ; vide le contenu des plus anciennes. La chaine + sha256 + metadata restent
    INTACTS (integrite/tamper-evidence preservee ; contenu recoverable via git par sha).
    Le ledger reste append-only ; seul le contenu redondant est elague."""
    conn = _conn()
    n = 0
    for row in conn.execute("SELECT DISTINCT fname FROM memory_ledger").fetchall():
        seqs = [r[0] for r in conn.execute(
            "SELECT seq FROM memory_ledger WHERE fname=? AND content!='' ORDER BY seq DESC",
            (row[0],)).fetchall()]
        for old in seqs[keep_per_file:]:
            conn.execute("UPDATE memory_ledger SET content='' WHERE seq=?", (old,))
            n += 1
    conn.commit()
    conn.close()
    return {"pruned_content": n, "keep_per_file": keep_per_file}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "recover" and len(sys.argv) > 2:
        print(json.dumps(recover(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False, indent=1))
        return
    fn = {"sync": sync, "verify": verify, "status": status, "prune": prune}.get(cmd, sync)
    print(json.dumps(fn(), ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
