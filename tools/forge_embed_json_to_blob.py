"""forge_embed_json_to_blob.py — convertit les vecteurs JSON (TEXT ET BLOB) de rag_chunks en float32 binaire.

Pourquoi (archeologie, owner 29/10) : le JSON est le format d'ORIGINE (mars 2026, NPU MiniLM) ; le binaire float32
(forge_embed_router.encode_blob) est canonique depuis avril ; les decodeurs sont tolerants depuis le 01/10. Un vecteur
1024d en JSON pese ~20 Ko contre 4 096 o : ~545 000 vecteurs JSON mesures le 29/10, ~9 Go. Les ecrivains JSON sont
supprimes (8a060f6c5, NR cliquet test_aucun_ecrivain_embedding_json_nr).

Contrat « pas de perte de donnees utiles » (GO owner A, 29/10) :
  - JAMAIS de balayage : plages de rowid (rowid BETWEEN a AND b, cle primaire) ; aucun fetchall de la table ;
  - chaque ligne est VERIFIEE : decodee, re-encodee, relue ; l'ecart max est mesure et rapporte (mesure 29/10 :
    1 008/1 017 exacts, max 4,3e-19) ; JSON illisible = INTACT et compte ;
  - AUCUN trigger supprime : auto_snapshot_before_update ne vise pas embedding ; forge_tier_guard est RESPECTE (un
    UPDATE ignore par la garde est compte, jamais contourne) ;
  - qdrant_sync_pending : le vecteur ne change pas -> seules les entrees CREEES par la conversion sont retirees,
    celles qui existaient avant restent ;
  - journal JSONL (id, rowid, sha256 du JSON d'origine, ecart) pour la tracabilite ; --dry-run compte sans ecrire ;
  - --limite N pour un pilote, mesures page_count / freelist avant/apres.
Remarque : auto_vacuum=0 -> les pages liberees sont REUTILISEES par la croissance ; rendre l'espace au disque demande
un VACUUM (INTO un autre disque), decision owner a part.

Run : run_job tools/forge_embed_json_to_blob.py script_args="--dry-run" puis "--limite 2000" puis complet.
"""
__FORGE_COLOR__ = "memoire/maintenance"

import argparse
import hashlib
import json
import sqlite3
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()


def _db_defaut() -> Path:
    try:
        sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
        from nokido_agent.app import forge_db_path as dbp
        return Path(getattr(dbp, "DB_PATH", None) or dbp.db_path())
    except Exception:  # noqa: BLE001 -- repli DIT : le chemin historique du depot
        return _RACINE_DONNEES / "RAG" / "embeddings.db"


def _json_de(emb):
    """Liste de floats si `emb` est un vecteur JSON (TEXT ou BLOB commencant par '['), sinon None ; 'ILLISIBLE'."""
    if emb is None:
        return None
    if isinstance(emb, str):
        brut = emb
    elif bytes(emb[:1]) == b"[":
        try:
            brut = bytes(emb).decode("utf-8")
        except UnicodeDecodeError:
            return "ILLISIBLE"
    else:
        return None
    try:
        v = json.loads(brut)
    except Exception:  # noqa: BLE001
        return "ILLISIBLE"
    if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) for x in v):
        return "ILLISIBLE"
    return v


def _table(c, nom) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nom,)).fetchone() is not None


def convertir(db, lot: int = 500, journal=None, dry_run: bool = False, limite: int | None = None,
              pause_s: float = 0.0) -> dict:
    db = Path(db)
    c = sqlite3.connect(str(db), timeout=60)
    c.execute("PRAGMA busy_timeout=30000")
    plan = " ".join(str(r) for r in c.execute(
        "EXPLAIN QUERY PLAN SELECT rowid, id, embedding FROM rag_chunks WHERE rowid BETWEEN ? AND ?", (1, 2)))
    if "SCAN" in plan.upper() and "USING INTEGER PRIMARY KEY" not in plan.upper():
        c.close()
        raise RuntimeError("plan non indexe, rien execute : %s" % plan)
    mx = c.execute("SELECT max(rowid) FROM rag_chunks").fetchone()[0] or 0
    bilan = {"a_convertir": 0, "convertis": 0, "illisibles": 0, "refuses_tier_guard": 0, "ecart_max": 0.0,
             "octets_avant": 0, "octets_apres": 0, "max_rowid": mx, "dry_run": dry_run}
    jf = open(journal, "a", encoding="utf-8") if (journal and not dry_run) else None
    # 29/10 : anomalies par id + rowid, a cote du journal (3 077 illisibles et 3 refus sans id a la passe complete :
    # les retrouver aurait demande un parcours complet, interdit). Fichier frere : le journal des convertis ne change pas.
    af = open(str(journal) + ".anomalies.jsonl", "a", encoding="utf-8") if (journal and not dry_run) else None
    t0 = time.time()
    a_pending = _table(c, "qdrant_sync_pending")
    try:
        debut = 1
        while debut <= mx:
            fin = debut + lot - 1
            rows = c.execute("SELECT rowid, id, embedding FROM rag_chunks WHERE rowid BETWEEN ? AND ?",
                             (debut, fin)).fetchall()
            a_faire = []
            for rowid, cid, emb in rows:
                v = _json_de(emb)
                if v is None:
                    continue
                if v == "ILLISIBLE":
                    bilan["illisibles"] += 1
                    if af:
                        af.write(json.dumps({"id": cid, "rowid": rowid, "anomalie": "ILLISIBLE"}) + "\n")
                    continue
                blob = struct.pack("%df" % len(v), *v)
                relu = struct.unpack("%df" % len(v), blob)
                ecart = max(abs(a - b) for a, b in zip(v, relu))
                brut = emb.encode("utf-8") if isinstance(emb, str) else bytes(emb)
                a_faire.append((rowid, cid, blob, ecart, hashlib.sha256(brut).hexdigest()[:16], len(brut)))
            bilan["a_convertir"] += len(a_faire)
            if a_faire and not dry_run:
                ids = [x[1] for x in a_faire]
                deja = {r[0] for r in c.execute(
                    "SELECT chunk_id FROM qdrant_sync_pending WHERE chunk_id IN (%s)" % ",".join("?" * len(ids)),
                    ids)} if a_pending else set()
                c.execute("BEGIN IMMEDIATE")
                try:
                    for rowid, cid, blob, ecart, h, n in a_faire:
                        cur = c.execute("UPDATE rag_chunks SET embedding=? WHERE rowid=?", (blob, rowid))
                        verif = c.execute("SELECT embedding FROM rag_chunks WHERE rowid=?", (rowid,)).fetchone()[0]
                        if cur.rowcount == 0 or verif != blob:
                            bilan["refuses_tier_guard"] += 1
                            if af:
                                af.write(json.dumps({"id": cid, "rowid": rowid, "anomalie": "REFUS_TIER_GUARD"}) + "\n")
                            continue
                        bilan["convertis"] += 1
                        bilan["ecart_max"] = max(bilan["ecart_max"], ecart)
                        bilan["octets_avant"] += n
                        bilan["octets_apres"] += len(blob)
                        if jf:
                            jf.write(json.dumps({"id": cid, "rowid": rowid, "sha256_json": h, "ecart": ecart}) + "\n")
                    nouveaux = [i for i in ids if i not in deja]
                    if a_pending and nouveaux:
                        c.execute("DELETE FROM qdrant_sync_pending WHERE chunk_id IN (%s)"
                                  % ",".join("?" * len(nouveaux)), nouveaux)
                    c.execute("COMMIT")
                except Exception:
                    c.execute("ROLLBACK")
                    raise
            if limite and bilan["a_convertir"] >= limite:
                break
            debut = fin + 1
            if pause_s:
                time.sleep(pause_s)
    finally:
        if jf:
            jf.close()
        if af:
            af.close()
        c.close()
    bilan["duree_s"] = round(time.time() - t0, 1)
    return bilan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None)
    ap.add_argument("--lot", type=int, default=500)
    ap.add_argument("--limite", type=int, default=None, help="pilote : s'arrete apres N vecteurs a convertir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pause", type=float, default=0.05, help="pause entre lots (laisser respirer la machine)")
    a = ap.parse_args(argv)
    db = Path(a.db) if a.db else _db_defaut()
    c = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    avant = {k: c.execute("PRAGMA %s" % k).fetchone()[0] for k in ("page_count", "freelist_count")}
    c.close()
    journal = _RACINE_DONNEES / "sandbox" / "workspace" / ("json_to_blob_journal_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    bilan = convertir(db, lot=a.lot, journal=journal, dry_run=a.dry_run, limite=a.limite, pause_s=a.pause)
    c = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    apres = {k: c.execute("PRAGMA %s" % k).fetchone()[0] for k in ("page_count", "freelist_count")}
    c.close()
    bilan.update(base=str(db), pages_avant=avant, pages_apres=apres, journal=None if a.dry_run else str(journal),
                 gain_go_estime=round((bilan["octets_avant"] - bilan["octets_apres"]) / 2**30, 3))
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
