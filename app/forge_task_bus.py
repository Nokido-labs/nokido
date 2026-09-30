"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_task_bus.py — Bus de tâches multi-agents pour La Forge
=============================================================
La Forge est le supercontrôleur. Les agents externes (Ollama, GPT…)
sont des outils distribués qu'elle pilote via cette interface.

Flux standard :
  1. La Forge crée une tâche (create_task)
  2. La Forge injecte le contexte RAG (inject_rag_context)
  3. L'agent externe lit la tâche (claim_task / get_task)
  4. L'agent exécute et écrit les résultats (submit_result)
  5. La Forge valide ou amende (forge_review)
  6. Tâche archivée dans le RAG (archive_to_rag)

Rôles interchangeables — orchestrator/executor sont des strings libres :
  "laforge", "ollama:qwen2.5", "ollama:deepseek", "gpt4", "any"

Accès MCP depuis les agents externes :
  query(action="task_create",  ...)
  query(action="task_claim",   executor="ollama:qwen2.5")
  query(action="task_result",  id=..., results=[...])
  query(action="task_list",    status="pending")
  query(action="task_get",     id=...)
  query(action="task_review",  id=..., verdict="approved")
"""


import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_ROOT_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT_DIR / "RAG" / "embeddings.db"

VALID_STATUSES = {"pending", "assigned", "running", "review", "done", "failed", "cancelled"}
VALID_VERDICTS = {"approved", "rejected", "amended"}

# Identite de LA FORGE quand elle juge le travail d'un agent EXTERNE (modes de
# collaboration). C'est l'orchestrateur EN PROCESS qui la porte : ce n'est jamais un nom
# recu d'un appelant distant (AUTH-6 : un acteur ne se DECLARE pas par une chaine venue
# du reseau). La Forge ne juge pas ce qu'elle a produit elle-meme : ces resultats restent
# NON REVUS (statut « review »), et ne sont donc pas archives comme « valides ».
ACTEUR_FORGE = "NOKIDO"
VALID_TYPES = {"generic", "code", "devops", "research", "review", "audit", "data"}


# =============================================================================
# CONNEXION DB
# =============================================================================


def _conn() -> sqlite3.Connection:
    """
    tablit une connexion  la base de donnes.

    Returns:
        Une connexion SQLite configure avec le mode journal WAL et
        une row factory permettant l'accs par nom de colonne.
    """
    con = sqlite3.connect(str(_DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


def ensure_schema() -> None:
    """
    Crée la table agent_tasks si elle n'existe pas.

    Args:
        None

    Returns:
        None
    """
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS agent_tasks (
        id           TEXT PRIMARY KEY,
        created_at   TEXT DEFAULT (datetime('now')),
        updated_at   TEXT DEFAULT (datetime('now')),
        orchestrator TEXT NOT NULL DEFAULT 'laforge',
        executor     TEXT NOT NULL DEFAULT 'any',
        title        TEXT NOT NULL,
        description  TEXT NOT NULL,
        task_type    TEXT DEFAULT 'generic',
        priority     INTEGER DEFAULT 5,
        plan         TEXT DEFAULT '[]',
        status       TEXT DEFAULT 'pending',
        results      TEXT DEFAULT '[]',
        forge_verdict TEXT DEFAULT '',
        forge_notes   TEXT DEFAULT '',
        rag_context  TEXT DEFAULT '',
        meta         TEXT DEFAULT '{}',
        sequence_id  TEXT,
        session_id   TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_status   ON agent_tasks(status);
    CREATE INDEX IF NOT EXISTS idx_tasks_executor ON agent_tasks(executor);
    CREATE INDEX IF NOT EXISTS idx_tasks_created  ON agent_tasks(created_at DESC);
    """)
    # 2026-09-24 : `create_task` insere `sequence_id` et `session_id`, que ce schema ne
    # declarait pas -- sur une base NEUVE, toute creation de tache levait
    # (« no column named sequence_id ») ; la base de production les avait recus par une
    # migration anterieure, d'ou un defaut invisible. Le schema les porte, et une base
    # existante qui ne les aurait pas les recoit ici.
    _cols = {r[1] for r in con.execute("PRAGMA table_info(agent_tasks)")}
    for _nom, _decl in (("sequence_id", "TEXT"), ("session_id", "TEXT DEFAULT ''")):
        if _nom not in _cols:
            con.execute("ALTER TABLE agent_tasks ADD COLUMN %s %s" % (_nom, _decl))
    con.commit()
    con.close()


# =============================================================================
# OPÉRATIONS PRINCIPALES
# =============================================================================


def create_task(
    title: str,
    description: str,
    executor: str = "any",
    orchestrator: str = "laforge",
    task_type: str = "generic",
    priority: int = 5,
    plan: List[Dict] = None,
    meta: Dict = None,
) -> Dict:
    """
    La Forge crée une tâche et la place dans la file.

    Args:
        title (str): Le titre de la tâche.
        description (str): La description de la tâche.
        executor (str, optional): L'exécuteur de la tâche. Defaults to "any".
        orchestrator (str, optional): L'orchestrator de la tâche. Defaults to "nokido".
        task_type (str, optional): Le type de la tâche. Defaults to "generic".
        priority (int, optional): La priorité de la tâche. Defaults to 5.
        plan (List[Dict], optional): Le plan de la tâche. Defaults to None.
        meta (Dict, optional): Les métadonnées de la tâche. Defaults to None.

    Returns:
        Dict: Le dictionnaire de la tâche créée.
    """
    ensure_schema()
    tid = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    task = {
        "id": tid,
        "created_at": now,
        "updated_at": now,
        "orchestrator": orchestrator,
        "executor": executor,
        "title": title,
        "description": description,
        "task_type": task_type if task_type in VALID_TYPES else "generic",
        "priority": priority,
        "plan": json.dumps(plan or []),
        "status": "pending",
        "results": "[]",
        "forge_verdict": "",
        "forge_notes": "",
        "rag_context": "",
        "meta": json.dumps(meta or {}),
        "sequence_id": None,
        "session_id": (meta or {}).get("session_id", ""),
    }
    con = _conn()
    con.execute(
        "INSERT INTO agent_tasks "
        "(id,created_at,updated_at,orchestrator,executor,title,description,"
        "task_type,priority,plan,status,results,forge_verdict,forge_notes,"
        "rag_context,meta,sequence_id,session_id) VALUES "
        "(:id,:created_at,:updated_at,:orchestrator,:executor,:title,:description,"
        ":task_type,:priority,:plan,:status,:results,:forge_verdict,:forge_notes,"
        ":rag_context,:meta,:sequence_id,:session_id)",
        task,
    )
    con.commit()
    con.close()
    logger.info(f"[TaskBus] created {tid} → executor={executor} type={task_type}")
    return _row_to_dict(task)


def inject_rag_context(task_id: str, rag_text: str) -> bool:
    """
    La Forge injecte le contexte RAG dans une tâche avant délégation.

    Args:
        task_id (str): L'ID de la tâche.
        rag_text (str): Le contexte RAG.

    Returns:
        bool: True si l'opération a réussi, False sinon.
    """
    con = _conn()
    cur = con.execute(
        "UPDATE agent_tasks SET rag_context=?, updated_at=? WHERE id=?",
        (rag_text[:3000], datetime.utcnow().isoformat(), task_id),
    )
    con.commit()
    con.close()
    return cur.rowcount > 0


def claim_task(executor: str) -> Optional[Dict]:
    """
    Un agent externe réclame la prochaine tâche qui lui est destinée.

    Args:
        executor (str): L'exécuteur de la tâche.

    Returns:
        Optional[Dict]: Le dictionnaire de la tâche réclamée, ou None si aucune tâche n'est disponible.
    """
    con = _conn()
    row = con.execute(
        """SELECT * FROM agent_tasks
           WHERE status = 'pending'
             AND (executor = ? OR executor = 'any')
           ORDER BY priority DESC, created_at ASC
           LIMIT 1""",
        (executor,),
    ).fetchone()
    if not row:
        con.close()
        return None
    now = datetime.utcnow().isoformat()
    con.execute(
        "UPDATE agent_tasks SET status='assigned', executor=?, updated_at=? WHERE id=?", (executor, now, row["id"])
    )
    con.commit()
    con.close()
    logger.info(f"[TaskBus] claimed {row['id']} by {executor}")
    return dict(row)


def reassign_stale(task_type: str, timeout_s: int = 30, new_executor: str = "any") -> int:
    """
    Réassigne les tâches 'assigned' ou 'pending' non réclamées sous timeout_s secondes.

    Args:
        task_type (str): Le type de tâche.
        timeout_s (int, optional): Le délai d'attente. Defaults to 30.
        new_executor (str, optional): Le nouvel exécuteur. Defaults to "any".

    Returns:
        int: Le nombre de tâches réassignées.
    """
    from datetime import datetime, timedelta

    cutoff = (datetime.utcnow() - timedelta(seconds=timeout_s)).isoformat()
    con = _conn()
    cur = con.execute(
        """UPDATE agent_tasks
           SET executor=?, status='pending', updated_at=?
           WHERE task_type=? AND status='pending'
             AND created_at < ?""",
        (new_executor, datetime.utcnow().isoformat(), task_type, cutoff),
    )
    con.commit()
    con.close()
    n = cur.rowcount
    if n:
        logger.info(f"[TaskBus] {n} tache(s) {task_type} reassignees → {new_executor}")
    return n


def set_status(task_id: str, status: str) -> bool:
    """
    Met à jour le statut d'une tâche.

    Args:
        task_id (str): L'ID de la tâche.
        status (str): Le nouveau statut.

    Returns:
        bool: True si l'opération a réussi, False sinon.
    """
    if status not in VALID_STATUSES:
        return False
    con = _conn()
    cur = con.execute(
        "UPDATE agent_tasks SET status=?, updated_at=? WHERE id=?", (status, datetime.utcnow().isoformat(), task_id)
    )
    con.commit()
    con.close()
    return cur.rowcount > 0


def submit_result(
    task_id: str,
    results: List[Dict],
    status: str = "review",
) -> bool:
    """
    L'agent exécutant soumet ses résultats.

    Args:
        task_id (str): L'ID de la tâche.
        results (List[Dict]): Les résultats de la tâche.
        status (str, optional): Le statut de la tâche. Defaults to "review".

    Returns:
        bool: True si l'opération a réussi, False sinon.
    """
    con = _conn()
    cur = con.execute(
        "UPDATE agent_tasks SET results=?, status=?, updated_at=? WHERE id=?",
        (json.dumps(results), status, datetime.utcnow().isoformat(), task_id),
    )
    con.commit()
    con.close()
    logger.info(f"[TaskBus] result submitted {task_id} → {status}")
    return cur.rowcount > 0


def forge_review(
    task_id: str,
    verdict: str,
    notes: str = "",
    amended_results: List[Dict] = None,
    *,
    acteur: str = None,
) -> bool:
    """
    La Forge valide, rejette ou amende les résultats.

    Args:
        task_id (str): L'ID de la tâche.
        verdict (str): Le verdict de la tâche.
        notes (str, optional): Les notes de la tâche. Defaults to "".
        amended_results (List[Dict], optional): Les résultats amendés. Defaults to None.
        acteur (str, optional): QUI rend ce verdict. Voir ci-dessous.

    Returns:
        bool: True si l'opération a réussi, False sinon.

    L'ACTEUR — ajouté le 2026-09-18 (audit sécurité, finding #9).

    `app/forge_separation.enforce_separation` sait juger quatre actions, dont
    `task.review`. Cette branche n'avait AUCUN appelant, et la raison n'était pas
    un oubli : cette fonction ne portait AUCUNE identité. Le garde exige un
    `actor_agent` ; l'information n'existait pas ici, donc l'appel était
    impossible — pas omis, impossible.

    C'est le motif « un garde branché sur un signal que personne n'émet », et il
    ne se referme pas en ajoutant une ligne : il fallait d'abord que la revue
    sache QUI la rend.

    `acteur=None` reste accepté : les six appelants historiques ne le passent pas,
    et les casser d'un coup remplacerait un trou par une panne. Mais l'absence
    est désormais JOURNALISÉE avec son motif — une revue anonyme cesse d'être
    indiscernable d'une revue attribuée.
    """
    if verdict not in VALID_VERDICTS:
        return False

    # FAIL-CLOSED (2026-09-24, contrat AUTH-6 / AUTH-4 du chantier d'authentification).
    # La version du 18/09 JOURNALISAIT une revue anonyme puis APPROUVAIT quand meme ; de
    # meme quand l'executant etait illisible ou le garde introuvable. Trois chemins ou un
    # verdict sortait alors que la separation n'avait PAS pu etre controlee. Desormais :
    # pas d'acteur, pas d'executant lisible, pas de garde -> REFUS, et c'est dit.
    if not acteur:
        logger.warning("[TaskBus] revue ANONYME de %s REFUSEE (verdict=%s) : sans acteur, "
                       "la separation des pouvoirs ne peut pas etre verifiee (AUTH-6)",
                       task_id, verdict)
        return False

    # SÉPARATION DES POUVOIRS — le juge ne peut pas être le producteur.
    # On n'appelle le garde que lorsqu'on a de quoi le nourrir : lui passer un
    # acteur inventé serait pire que ne pas l'appeler, car le refus porterait
    # alors sur une identité fabriquée.
    #
    # DEUX PIÈGES ÉVITÉS ICI, tous deux mesurés en écrivant ce bloc :
    #
    # 1. `enforce_separation` RETOURNE `(bool, motif)` — elle ne LÈVE PAS. Un
    #    premier jet l'appelait sous `except PermissionError` : le refus aurait
    #    été ignoré en silence, et le garde se serait relu comme actif en ne
    #    gardant rien. C'est exactement le défaut que ce correctif ferme.
    #
    # 2. Pour `task.review`, le garde résout l'exécutant en interrogeant
    #    `sandbox/tasks.db`, table `tasks`. Or cette fonction travaille sur
    #    `agent_tasks`, dans une base DIFFÉRENTE : lui passer l'identifiant nu
    #    n'aurait trouvé aucune ligne, donc AUCUN contrôle — un appel qui rend
    #    « autorisé » parce qu'il n'a rien pu lire. On lui passe donc un dict
    #    portant l'exécutant lu ICI, dans la bonne table.
    _executant = None
    try:
        _c = _conn()
        _r = _c.execute("SELECT executor FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        _executant = _r[0] if _r else None
        _c.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[TaskBus] exécutant de %s ILLISIBLE (%s)", task_id, e)
    if not _executant:
        logger.warning("[TaskBus] revue de %s REFUSEE : exécutant inconnu, donc la séparation "
                       "ne peut pas être vérifiée (UNKNOWN = DENY)", task_id)
        return False
    try:
        from nokido_agent.app.forge_separation import enforce_separation
    except ImportError as e:  # noqa: BLE001
        logger.warning("[TaskBus] garde de séparation INDISPONIBLE (%s) — revue de %s "
                       "REFUSEE (un garde absent ne vaut pas autorisation)", e, task_id)
        return False
    ok, motif = enforce_separation(
        actor_agent=acteur, action="task.review", target={"to_agent": _executant})
    if not ok:
        logger.warning("[TaskBus] revue REFUSÉE — %s", motif)
        return False
    final_status = "done" if verdict in ("approved", "amended") else "failed"
    con = _conn()
    updates = {
        "verdict": verdict,
        "notes": notes,
        "status": final_status,
        "updated": datetime.utcnow().isoformat(),
        "id": task_id,
    }
    if amended_results is not None:
        # 2026-09-24 : cette requete MELANGEAIT un parametre positionnel (?) et des
        # parametres nommes, ce que sqlite3 refuse -- la branche « amended » levait a
        # chaque appel. Parametres NOMMES seulement.
        con.execute(
            "UPDATE agent_tasks SET forge_verdict=:verdict, forge_notes=:notes, "
            "results=:results, status=:status, updated_at=:updated WHERE id=:id",
            {**updates, "results": json.dumps(amended_results)},
        )
    else:
        con.execute(
            "UPDATE agent_tasks SET forge_verdict=:verdict, forge_notes=:notes, "
            "status=:status, updated_at=:updated WHERE id=:id",
            updates,
        )
    con.commit()
    con.close()
    logger.info(f"[TaskBus] forge_review {task_id} → {verdict} → {final_status}")
    return True


def get_task(task_id: str) -> Optional[Dict]:
    """
    Lit une tâche par ID.

    Args:
        task_id (str): L'ID de la tâche.

    Returns:
        Optional[Dict]: Le dictionnaire de la tâche, ou None si la tâche n'existe pas.
    """
    con = _conn()
    row = con.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_tasks(
    status: str = "",
    executor: str = "",
    limit: int = 20,
) -> List[Dict]:
    """
    Liste les tâches avec filtres optionnels.

    Args:
        status (str, optional): Le statut des tâches. Defaults to "".
        executor (str, optional): L'exécuteur des tâches. Defaults to "".
        limit (int, optional): La limite de tâches. Defaults to 20.

    Returns:
        List[Dict]: La liste des tâches.
    """
    sql = "SELECT * FROM agent_tasks WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if executor:
        sql += " AND (executor=? OR executor='any')"
        params.append(executor)
    sql += " ORDER BY priority DESC, created_at DESC LIMIT ?"
    params.append(limit)
    con = _conn()
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def archive_to_rag(task_id: str, rag_engine=None) -> bool:
    """
    Après validation, La Forge archive les résultats dans rag_chunks
    pour que la connaissance soit réutilisable.

    Args:
        task_id (str): L'ID de la tâche.
        rag_engine (optional): Le moteur RAG. Defaults to None.

    Returns:
        bool: True si l'opération a réussi, False sinon.
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    task = get_task(task_id)
    if not task or task["status"] != "done":
        return False
    text = (
        f"[TASK {task_id}] {task['title']}\n"
        f"Type: {task['task_type']} | Executor: {task['executor']}\n"
        f"Description: {task['description'][:300]}\n\n"
        f"Résultats validés:\n"
        + "\n".join(
            f"  Étape {r.get('step', '?')}: {r.get('output', '')[:200]}"
            for r in json.loads(task["results"] or "[]")
            if r.get("ok")
        )
    )
    if rag_engine:
        import asyncio

        try:
            asyncio.get_event_loop().run_until_complete(
                rag_engine.add_session_message(f"task_{task_id}", task["task_type"], text)
            )
            logger.info(f"[TaskBus] archivé dans RAG: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"[TaskBus] archive_to_rag: {e}")
    return False


def stats() -> Dict:
    """
    Statistiques du bus de tâches.

    Returns:
        Dict: Les statistiques du bus de tâches.
    """
    con = _conn()
    rows = con.execute("SELECT status, COUNT(*) FROM agent_tasks GROUP BY status").fetchall()
    execs = con.execute("SELECT executor, COUNT(*) FROM agent_tasks GROUP BY executor").fetchall()
    con.close()
    return {
        "by_status": dict(rows),
        "by_executor": dict(execs),
        "total": sum(v for _, v in rows),
    }


# =============================================================================
# SHARED PROMPT LOG — conversation partagée multi-agents
# =============================================================================


def log_shared_prompt(
    session_id: str,
    agent_id: str,
    content: str,
    role: str = "assistant",
    mode: str = "",
    meta: Dict = None,
) -> int:
    """
    Enregistre un message dans la conversation partagée.

    Args:
        session_id (str): L'ID de la session.
        agent_id (str): L'ID de l'agent.
        content (str): Le contenu du message.
        role (str, optional): Le rôle de l'agent. Defaults to "assistant".
        mode (str, optional): Le mode de la conversation. Defaults to "".
        meta (Dict, optional): Les métadonnées du message. Defaults to None.

    Returns:
        int: L'ID du message inséré.
    """
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    con = _conn()
    # Séquence monotone simple
    last = (
        con.execute("SELECT MAX(sequence_id) FROM shared_prompt_log WHERE session_id=?", (session_id,)).fetchone()[0]
        or 0
    )
    seq = last + 1
    cur = con.execute(
        "INSERT INTO shared_prompt_log "
        "(session_id, timecode, sequence_id, agent_id, role, mode, content, meta) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (session_id, ts, seq, agent_id, role, mode, content, json.dumps(meta or {}, ensure_ascii=False)),
    )
    con.commit()
    row_id = cur.lastrowid
    con.close()
    return row_id


def get_conversation(
    session_id: str,
    limit: int = 100,
    agent_id: str = "",
    mode: str = "",
) -> List[Dict]:
    """
    Récupère la conversation partagée d'une session.

    Args:
        session_id (str): L'ID de la session.
        limit (int, optional): La limite de messages. Defaults to 100.
        agent_id (str, optional): L'ID de l'agent. Defaults to "".
        mode (str, optional): Le mode de la conversation. Defaults to "".

    Returns:
        List[Dict]: La liste des messages de la conversation.
    """
    con = _conn()
    clauses, params = ["session_id=?"], [session_id]
    if agent_id:
        clauses.append("agent_id=?")
        params.append(agent_id)
    if mode:
        clauses.append("mode=?")
        params.append(mode)
    where = " AND ".join(clauses)
    rows = con.execute(
        f"SELECT * FROM shared_prompt_log WHERE {where} ORDER BY sequence_id ASC LIMIT ?", params + [limit]
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_sessions(mode: str = "", limit: int = 20) -> List[Dict]:
    """
    Liste les sessions collab avec leur dernier message.

    Args:
        mode (str, optional): Le mode de la conversation. Defaults to "".
        limit (int, optional): La limite de sessions. Defaults to 20.

    Returns:
        List[Dict]: La liste des sessions.
    """
    con = _conn()
    extra = "AND mode=?" if mode else ""
    params = [mode, limit] if mode else [limit]
    rows = con.execute(
        f"SELECT session_id, mode, COUNT(*) as turns, "
        f"MIN(timecode) as started, MAX(timecode) as last_msg, "
        f"GROUP_CONCAT(DISTINCT agent_id) as agents "
        f"FROM shared_prompt_log {extra} "
        f"GROUP BY session_id ORDER BY last_msg DESC LIMIT ?",
        params,
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


# =============================================================================
# HELPER
# =============================================================================


def _row_to_dict(row) -> Dict:
    """
    Convertit un objet Row en dictionnaire.

    Args:
        row: L'objet Row.

    Returns:
        Dict: Le dictionnaire équivalent.
    """
    if isinstance(row, dict):
        return row
    return dict(row)
