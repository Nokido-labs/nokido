# -*- coding: utf-8 -*-
"""
forge_task_queue.py — File d attente persistante pour les rôles
================================================================
Remplace l envoi de 18 tâches en batch par un système de queue.
- Dépôt instantané (SQLite WAL)
- Consommation par worker asynchrone (max 2 simultanés)
- Priorité HIGH > NORMAL > LOW
- Circuit breaker par rôle via forge_roles
Session 5 — 2026-04-27
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.TaskQueue")

ROOT = Path(__file__).resolve().parent.parent

# ── LA FILE NE VIT PLUS DANS LA BASE DU RAG (2026-09-18) ─────────────────────
#
# Avant : `DB = ROOT / "RAG" / "embeddings.db"` et SEPT `sqlite3.connect(str(DB))`
# bruts. Mesure du jour : ce chemin et celui de `forge_db_path.db_path()`
# designent LE MEME FICHIER PHYSIQUE — `V:` est un lecteur SUBSTITUE vers
# `Nokido/RAG/` (meme `dev`, meme `ino`, `os.path.samefile()` rend True). La file
# de taches disputait donc le verrou d'ecriture de la base RAG de 25 Go alors
# qu'elle n'a aucun rapport metier avec elle : SQLite n'admet qu'UN writer par
# FICHIER, que le WAL soit actif ou non.
#
# ⚠️ Le defaut etait invisible a la relecture : comparer les deux chemins en
# TEXTE rend False, et ce faux negatif va dans le sens rassurant.
#
# `DB` garde sa forme pour ses lecteurs, mais suit desormais l'interrupteur et se
# resout a CHAQUE APPEL — jamais fige a l'import. Figer le chemin est exactement
# ce qui produit un site qui bascule seul pendant que les autres ecrivent ailleurs.
from nokido_agent.app import forge_db_path as _dbp


def _db_courante() -> str:
    """Chemin de la base de la file, relu a chaque appel (patron M2M)."""
    return _dbp.tasks_path()


class _CheminDerive:
    """Se comporte comme un chemin, mais interroge l'interrupteur a chaque lecture."""

    def __str__(self) -> str:
        return _db_courante()

    def __fspath__(self) -> str:
        return _db_courante()

    def __repr__(self) -> str:
        return "<DB task_queue -> %s>" % _db_courante()


DB = _CheminDerive()


def _connexion() -> sqlite3.Connection:
    """Connexion GOUVERNEE : WAL, autocommit, busy_timeout, schema garanti.

    Remplace `sqlite3.connect(str(DB))` nu. Le schema n'est ecrit que dans la base
    DEDIEE : avant la bascule, la cible est la base du RAG (GELEE), ou la table
    existe deja.
    """
    return _dbp.open_tasks(timeout=10.0)

_WORKER_RUNNING = False
_WORKER_THREAD: Optional[threading.Thread] = None


def _init_table() -> None:
    """Garantit le schema.

    Le SQL vit desormais dans `forge_db_path.TASKS_SCHEMA`, releve dans
    `sqlite_master` de la base VIVANTE : une seule definition, donc aucune derive
    possible entre le createur et le migrateur.
    """
    _connexion().close()


# L'APPEL A L'IMPORT A ETE RETIRE (2026-09-18). `_init_table()` s'executait au
# chargement du module : tout import de `forge_task_queue` — y compris par un
# outil qui ne touche jamais la file — ouvrait une connexion sur la base de 25 Go
# et y posait un CREATE TABLE. Le schema est garanti par `_connexion()`, donc au
# premier usage REEL, et par la migration pour la base dediee.


def enqueue(title: str, role: str = "EXECUTOR", priority: str = "NORMAL", context: str = "") -> int:
    """Dépose une tâche dans la queue. Retourne l id."""
    conn = _connexion()
    try:
        cur = conn.execute(
            "INSERT INTO task_queue (title,role,priority,context) VALUES (?,?,?,?)",
            (title, role.upper(), priority.upper(), context),
        )
        return cur.lastrowid
    finally:
        conn.close()


def enqueue_many(tasks: list[dict]) -> list[int]:
    """Dépose plusieurs tâches en UNE transaction.

    Avant : une boucle sur `enqueue()`, donc un `connect` + un `COMMIT` PAR TACHE.
    Pour 100 taches, 100 transactions — 100 prises du verrou d'ecriture, 100
    fsync — sur la base de 25 Go partagee avec le RAG.

    Toute la preparation se fait AVANT le `BEGIN` : le verrou d'ecriture ne doit
    jamais couvrir autre chose que l'ecriture elle-meme.
    """
    lignes = [
        (
            t.get("title", "?"),
            str(t.get("role", "EXECUTOR")).upper(),
            str(t.get("priority", "NORMAL")).upper(),
            t.get("context", ""),
        )
        for t in tasks
    ]
    if not lignes:
        return []
    conn = _connexion()
    try:
        conn.execute("BEGIN IMMEDIATE")
        avant = conn.execute("SELECT COALESCE(MAX(id), 0) FROM task_queue").fetchone()[0]
        conn.executemany(
            "INSERT INTO task_queue (title,role,priority,context) VALUES (?,?,?,?)", lignes
        )
        apres = conn.execute("SELECT MAX(id) FROM task_queue").fetchone()[0]
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:  # muet-ok : rien a annuler
            pass
        raise
    finally:
        conn.close()
    # Les ids sont contigus : l'insertion tient dans UNE transaction, donc aucun
    # autre ecrivain n'a pu s'intercaler entre le premier et le dernier.
    return list(range(avant + 1, apres + 1))


def queue_status() -> dict:
    """Statistiques de la queue."""
    conn = _connexion()
    try:
        rows = conn.execute("SELECT status, COUNT(*) FROM task_queue GROUP BY status").fetchall()
    finally:
        conn.close()
    return {r[0]: r[1] for r in rows}


def get_results(limit: int = 20) -> list[dict]:
    """Derniers résultats."""
    conn = _connexion()
    try:
        rows = conn.execute(
            "SELECT id,title,role,priority,status,result,done_at FROM task_queue ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "title": r[1],
            "role": r[2],
            "priority": r[3],
            "status": r[4],
            "result": r[5][:200] if r[5] else "",
            "done_at": r[6],
        }
        for r in rows
    ]


async def _process_one(task_id: int, title: str, role: str, context: str):
    """Traite une tâche via le bon rôle."""
    from nokido_agent.app.forge_roles import call_role

    # LE PASSAGE A 'RUNNING' N'EST PLUS FAIT ICI : il appartient desormais au
    # CLAIM ATOMIQUE de `_reclamer()`, qui selectionne et marque dans la MEME
    # transaction. Le faire ici laissait une fenetre entre le SELECT du worker et
    # cet UPDATE, pendant laquelle un second consommateur pouvait selectionner
    # les memes lignes PENDING et traiter la tache deux fois.
    try:
        result = await call_role(role, title, context)
        status = "DONE" if result.get("ok") else "ERROR"
        result_text = result.get("text", "") or result.get("error", "")
    except Exception as e:
        status = "ERROR"
        result_text = str(e)[:200]

    conn = _connexion()
    try:
        conn.execute(
            "UPDATE task_queue SET status=?, result=?, done_at=datetime('now') WHERE id=?",
            (status, result_text[:1000], task_id),
        )
    finally:
        conn.close()
    logger.info(f"[Queue] #{task_id} {status} — {title[:50]}")


def _reclamer(limite: int = 6) -> list:
    """Selectionne des taches PENDING **et les marque RUNNING dans la MEME transaction**.

    Avant, le worker faisait un `SELECT ... WHERE status='PENDING'` puis laissait
    `_process_one` poser `RUNNING` dans une transaction SEPAREE. Entre les deux, un
    second consommateur — autre processus, ou le meme loop re-entre — pouvait
    selectionner les memes lignes : la tache partait deux fois, et le second
    resultat ecrasait le premier.

    `BEGIN IMMEDIATE` prend le verrou d'ecriture AVANT le SELECT, donc la lecture
    et le marquage sont indivisibles. La reclamation ne fait QUE cela : aucun appel
    de role, aucun reseau, aucun LLM sous le verrou.
    """
    conn = _connexion()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id,title,role,priority,context FROM task_queue "
            "WHERE status='PENDING' ORDER BY "
            "CASE priority WHEN 'HIGH' THEN 0 WHEN 'NORMAL' THEN 1 ELSE 2 END, id "
            "LIMIT ?",
            (limite,),
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE task_queue SET status='RUNNING', started_at=datetime('now') "
                "WHERE id IN (%s)" % ",".join("?" * len(rows)),
                [r[0] for r in rows],
            )
        conn.execute("COMMIT")
        return rows
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:  # muet-ok : rien a annuler
            pass
        raise
    finally:
        conn.close()


async def _worker_loop():
    """Worker asynchrone — consomme la queue par priorité, max 2 simultanés."""
    priority_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
    semaphore = asyncio.Semaphore(2)  # max 2 simultanés — protège GPU

    async def process_with_sem(tid, title, role, ctx):
        async with semaphore:
            await _process_one(tid, title, role, ctx)

    while _WORKER_RUNNING:
        rows = _reclamer(6)

        if rows:
            tasks = [process_with_sem(r[0], r[1], r[2], r[4]) for r in rows]
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(2)  # attente si queue vide


def start_worker():
    """Démarre le worker en background thread."""
    global _WORKER_RUNNING, _WORKER_THREAD
    if _WORKER_RUNNING:
        return
    _WORKER_RUNNING = True

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_worker_loop())
        finally:
            loop.close()

    _WORKER_THREAD = threading.Thread(target=_run, daemon=True, name="task_queue_worker")
    _WORKER_THREAD.start()
    logger.info("[Queue] Worker démarré")


def stop_worker():
    global _WORKER_RUNNING
    _WORKER_RUNNING = False


# ── Usage rapide depuis run(action=python) ───────────────────────────────────
def submit_plan(tasks: list[str], role: str = "EXECUTOR", priority: str = "NORMAL") -> dict:
    """
    Soumet une liste de tâches à la queue.
    Usage : submit_plan(["tâche 1", "tâche 2"], role="EXECUTOR", priority="HIGH")
    """
    ids = enqueue_many([{"title": t, "role": role, "priority": priority} for t in tasks])
    start_worker()
    return {"queued": len(ids), "ids": ids, "status": queue_status()}
