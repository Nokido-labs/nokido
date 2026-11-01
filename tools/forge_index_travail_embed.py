"""Index partiel de TRAVAIL du rattrapage de vectorisation (decision owner 24/10, creation de nuit).

POURQUOI. `idx_embedding_null` (WHERE embedding IS NULL) garde les lignes deja marquees SKIP_*
(leur embedding reste NULL a vie) : le rattrapage (tools/forge_embed_backfill_cool.py) les
retraverse -- 8,4 Go lus en 3,5 min au reboot du 24/10. `idx_embed_a_faire` (WHERE embedding IS
NULL AND embedding_model IS NULL) ne contient que le travail RESTANT : une ligne marquee en sort.

COUT. La creation lit la table une fois (45 Go sur V:) et ecrit l'index : operation lourde,
hors chaine critique (constitution), donc de nuit, mesuree avant/apres, refusee si une CI tourne,
et le rattrapage COUPE pendant la creation (interrupteur sandbox/embed_backfill.off).

Usage :
    LAFORGE_PYTHON tools/forge_index_travail_embed.py              # --mesurer : EXPLAIN + presence, n'ecrit rien
    LAFORGE_PYTHON tools/forge_index_travail_embed.py --creer      # cree, rapport sandbox/workspace/index_travail_embed_rapport.json
Retour arriere : DROP INDEX idx_embed_a_faire (le rattrapage revient seul a idx_embedding_null).
NR : tests/nr/test_index_travail_embed_nr.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/index-travail-vectorisation : index partiel du reste a vectoriser, cree de nuit"

import json
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return RACINE
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
sys.path.insert(0, str(RACINE / "tools"))
import forge_embed_backfill_cool as _bf  # noqa: E402

NOM = "idx_embed_a_faire"
DDL = ("CREATE INDEX IF NOT EXISTS idx_embed_a_faire ON rag_chunks(id) "
       "WHERE embedding IS NULL AND embedding_model IS NULL")
RAPPORT = _RACINE_DONNEES / "sandbox" / "workspace" / "index_travail_embed_rapport.json"
_LOT = ("SELECT id, text FROM rag_chunks INDEXED BY {idx} WHERE embedding IS NULL AND id > ? "
        "AND embedding_model IS NULL AND text IS NOT NULL AND length(text) > 50 ORDER BY id LIMIT ?")


def ci_en_cours():
    """Une CI tourne-t-elle (runner = poste owner) ? Rend sa description, ou None. Illisible = dit."""
    try:
        import psutil
    except ImportError:
        return None
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
        except Exception:  # muet-ok : processus disparu ou d'un autre compte pendant l'iteration
            continue
        if "ci_local.py" in cmd or "forge_ci_reference.py" in cmd:
            return "pid %s %s" % (p.info["pid"], "ci_local.py" if "ci_local.py" in cmd else "forge_ci_reference.py")
    return None


def _present(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (NOM,)).fetchone() is not None


def _plans(conn) -> dict:
    out = {}
    for idx in ("idx_embedding_null", NOM):
        try:
            out[idx] = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + _LOT.format(idx=idx), ("", 32))]
        except sqlite3.OperationalError as e:
            out[idx] = "absent (%s)" % e
    return out


def mesurer(db) -> dict:
    """Presence de l'index + plans du lot ; lecture seule, EXPLAIN seulement (aucune donnee lue)."""
    conn = sqlite3.connect("file:%s?mode=ro" % Path(db).as_posix(), uri=True, timeout=10)
    try:
        return {"index_present": _present(conn), "plans": _plans(conn),
                "taille_go": round(Path(db).stat().st_size / 1e9, 2)}
    finally:
        conn.close()


def _creer_index(conn) -> None:
    conn.execute(DDL)
    conn.commit()


def creer(db, interrupteur=None) -> dict:
    interrupteur = Path(interrupteur or _bf.INTERRUPTEUR)
    rapport = {"index": NOM, "cree": False, "debut": time.strftime("%Y-%m-%d %H:%M:%S")}
    ci = ci_en_cours()
    if ci:
        rapport["refus"] = "CI en cours (%s) : aucune charge lourde pendant une CI" % ci
        return rapport
    rapport["avant"] = mesurer(db)
    pose = not interrupteur.exists()
    if pose:
        interrupteur.write_text("forge_index_travail_embed : creation de %s en cours" % NOM, encoding="utf-8")
    try:
        conn = sqlite3.connect(str(db), timeout=600)
        try:
            t0 = time.time()
            _creer_index(conn)
            rapport["duree_s"] = round(time.time() - t0, 1)
            rapport["cree"] = _present(conn)
            rapport["plans_apres"] = _plans(conn)
            if rapport["cree"]:
                # index SEUL (WHERE = predicat exact de l'index partiel) : tranche le filtre par
                # tier -- peu de lignes non marquees = filtre inutile (decision 24/10)
                rapport["reste_a_faire"] = conn.execute(
                    "SELECT COUNT(*) FROM rag_chunks INDEXED BY idx_embed_a_faire "
                    "WHERE embedding IS NULL AND embedding_model IS NULL").fetchone()[0]
        finally:
            conn.close()
    finally:
        if pose:
            interrupteur.unlink(missing_ok=True)
    rapport["taille_go_apres"] = round(Path(db).stat().st_size / 1e9, 2)
    return rapport


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    db = _bf.DB
    rapport = creer(db) if "--creer" in argv else mesurer(db)
    texte = json.dumps(rapport, ensure_ascii=False, indent=1)
    print(texte)
    if "--creer" in argv:
        try:
            RAPPORT.write_text(texte, encoding="utf-8")
        except OSError as e:
            print("rapport NON ecrit : %s" % e)
        return 0 if rapport.get("cree") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
