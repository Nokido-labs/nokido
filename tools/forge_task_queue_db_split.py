# -*- coding: utf-8 -*-
"""tools/forge_task_queue_db_split.py — sortir `task_queue` de la base du RAG.

Jumeau de `forge_switches_db_split.py` (scission `access_switches`, 2026-09-05) et
de la bascule M2M : meme patron, meme discipline, pas une seconde invention.

POURQUOI. `forge_task_queue` ouvrait neuf fois `sqlite3.connect(str(DB))` avec
`DB = ROOT/RAG/embeddings.db`. Mesure du 2026-09-18 : ce chemin et celui rendu par
`forge_db_path.db_path()` designent LE MEME FICHIER PHYSIQUE — `V:` est un lecteur
SUBSTITUE vers `Nokido/RAG/` (meme `dev`, meme `ino`, `os.path.samefile()` rend
True). La file de taches disputait donc le verrou d'ecriture de la base RAG de
25 Go, sans aucun rapport metier : SQLite n'admet qu'UN writer par FICHIER.

Le defaut etait invisible a la relecture : comparer les deux chemins en TEXTE
rend False, et ce faux negatif va dans le sens rassurant.

ORDRE DES GESTES — il compte, et l'inverse perd des lignes :
  1. `--copier --apply`   recopie les lignes vers la base dediee
  2. `--verifier`         compare ligne a ligne, source contre cible
  3. poser `sandbox/task_queue.switch` SEULEMENT si l'etape 2 rend IDENTIQUE
Tant que l'interrupteur n'est pas pose, `tasks_path()` rend la base du RAG et le
comportement est INCHANGE. C'est cette propriete qui rend la bascule sure.

Dry-run par defaut. `--apply` ecrit.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/db : sortir task_queue de la base du RAG (scission)"

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forge_db_path as dbp  # noqa: E402
from app.forge_install_prerequis import (  # noqa: E402
    ABSENT,
    ILLISIBLE,
    PRESENT,
    _verdict_chemin,
)

COLONNES = ("id", "ts", "title", "role", "priority", "status", "context",
            "result", "started_at", "done_at")
CIBLE_DEFAUT = ROOT / "sandbox" / "task_queue.db"
INTERRUPTEUR = ROOT / "sandbox" / "task_queue.switch"


def _source() -> str:
    """La SOURCE est la base du RAG, meme si l'interrupteur est deja pose.

    On ne lit pas `tasks_path()` ici : une fois l'interrupteur pose, il rendrait
    la CIBLE, et la copie se ferait d'elle-meme vers elle-meme.
    """
    return dbp.db_path()


def _lire(chemin: str) -> tuple:
    """Rend `(lignes, etat)` avec etat PRESENTE / ABSENTE / ILLISIBLE(<motif>).

    Trois etats, jamais deux. Mesure du 2026-09-19 : `mode=ro` ne CREE pas le
    fichier, donc une base absente sortait en `OperationalError: unable to open
    database file` -- une panne la ou il n'y a simplement rien a copier. C'est ce
    qui a fait echouer le NR du point d'entree dans un worktree de CI neuf, ou
    `RAG/embeddings.db` n'existait pas encore au moment du test.

    L'asymetrie etait le defaut : une TABLE absente rendait deja `[]`, une BASE
    absente levait. Et symetriquement une base ILLISIBLE (ACL) ne doit jamais
    etre lue comme vide -- c'est ce faux negatif qui faisait rendre IDENTIQUE a
    `verifier` sur une source muette, donc autorisait la pose de l'interrupteur.
    """
    etat = _verdict_chemin(Path(chemin))
    if etat != PRESENT:
        return [], ("ABSENTE" if etat == ABSENT else "ILLISIBLE(%s)" % ILLISIBLE)
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % chemin.replace("\\", "/"), uri=True)
    except sqlite3.Error as e:
        return [], "ILLISIBLE(%s: %s)" % (type(e).__name__, str(e)[:80])
    try:
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_queue'"
        ).fetchone()
        if not existe:
            return [], "PRESENTE"
        return list(conn.execute(
            "SELECT %s FROM task_queue ORDER BY id" % ", ".join(COLONNES)
        )), "PRESENTE"
    except sqlite3.Error as e:
        return [], "ILLISIBLE(%s: %s)" % (type(e).__name__, str(e)[:80])
    finally:
        conn.close()


def copier(cible: Path, appliquer: bool) -> dict:
    src = _source()
    lignes, etat = _lire(src)
    rapport = {"source": src, "source_etat": etat, "cible": str(cible),
               "lignes_source": len(lignes), "applique": bool(appliquer)}
    if etat != "PRESENTE":
        rapport["applique"] = False
        rapport["refus"] = ("source non lisible (%s) : rien n'est ecrit. Copier "
                            "depuis une source muette fabriquerait une cible vide "
                            "declaree migree." % etat)
        return rapport
    if not appliquer:
        rapport["note"] = "dry-run : rien n'a ete ecrit"
        return rapport
    cible.parent.mkdir(parents=True, exist_ok=True)
    conn = dbp.open_writer(path=str(cible))
    try:
        dbp.ensure_tasks_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            "INSERT OR REPLACE INTO task_queue (%s) VALUES (%s)"
            % (", ".join(COLONNES), ", ".join("?" * len(COLONNES))),
            lignes,
        )
        conn.execute("COMMIT")
        rapport["lignes_cible"] = conn.execute("SELECT COUNT(*) FROM task_queue").fetchone()[0]
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:  # muet-ok : rien a annuler
            pass
        raise
    finally:
        conn.close()
    return rapport


def verifier(cible: Path) -> dict:
    """Compare LIGNE A LIGNE, jamais deux COUNT.

    Deux `COUNT` pris separement sont deux instantanes : l'ecart mesure serait
    l'activite concurrente, pas une perte (mesure du 2026-09-01).
    """
    src, etat_src = _lire(_source())
    dst, etat_dst = _lire(str(cible))
    par_id_src = {r[0]: r for r in src}
    par_id_dst = {r[0]: r for r in dst}
    manquantes = sorted(set(par_id_src) - set(par_id_dst))
    divergentes = sorted(i for i in set(par_id_src) & set(par_id_dst)
                         if par_id_src[i] != par_id_dst[i])
    en_trop = sorted(set(par_id_dst) - set(par_id_src))
    if etat_src != "PRESENTE":
        verdict = "INDETERMINE"          # liste BLANCHE : n'est IDENTIQUE que ce qui
    elif manquantes or divergentes:      # a ete PROUVE identique sur une source LUE.
        verdict = "DIVERGE"
    else:
        verdict = "IDENTIQUE"
    return {
        "source": len(src), "source_etat": etat_src,
        "cible": len(dst), "cible_etat": etat_dst,
        "manquantes": manquantes, "divergentes": divergentes, "en_trop": en_trop,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copier", action="store_true", help="recopier les lignes (avec --apply)")
    ap.add_argument("--verifier", action="store_true", help="comparer ligne a ligne")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    ap.add_argument("--cible", default=str(CIBLE_DEFAUT))
    a = ap.parse_args()
    cible = Path(a.cible)
    fait = False
    if a.copier:
        for k, v in copier(cible, a.apply).items():
            print("  %-14s %s" % (k, v))
        fait = True
    if a.verifier:
        r = verifier(cible)
        for k, v in r.items():
            print("  %-14s %s" % (k, v if not isinstance(v, list) else (v[:20] or "aucune")))
        fait = True
        if r["verdict"] == "INDETERMINE":
            print("  !! source non lisible : NE PAS poser l'interrupteur "
                  "(un INDETERMINE n'est pas un IDENTIQUE)")
        if r["verdict"] != "IDENTIQUE":
            return 1
    if not fait:
        print("rien demande : --copier [--apply] et/ou --verifier")
        print("interrupteur :", INTERRUPTEUR, "->", "POSE" if INTERRUPTEUR.exists() else "absent")
        print("A POSER SEULEMENT si --verifier rend IDENTIQUE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
