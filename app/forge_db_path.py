# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_db_path_1

forge_db_path.py — Chemin CANONIQUE de la base RAG, résolu en REALPATH.

PROBLÈME (récurrent, silencieux) : `RAG/embeddings.db` est un SYMLINK C: -> V:.
Écrire via le symlink C: lève "attempt to write a readonly database" car le
journal -wal/-shm ne peut pas être créé dans le dir C:\\...\\RAG (read-only pour
les contextes non-service : sandbox, runners). Ça a cassé EN SILENCE create_job
(veille morte 5j), access_count, l'eco-embed, watch_jobs, etc.

FIX : toujours ouvrir le REALPATH (%NOKIDO_DATA%\\embeddings.db), writable depuis TOUT
contexte. La lecture marche aussi (même fichier). Source de vérité unique du
chemin DB — les modules qui écrivent doivent passer par `db_path()`.

Override : env `LAFORGE_DB`.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `CheminJournal` — Chemin d'un journal, resolu a CHAQUE acces, jamais fige a l'import.
- `journaux_retenus` — Journaux que l'interrupteur NE deplace PAS, avec leur raison. Nommer, jamais taire.
- `lecteur_journal` — Connexion de LECTURE vers un journal, dediee SEULEMENT s'il a bascule.
- `purger_fts` — Purge des lignes de `rag_fts` SANS balayer la table ; rend (supprimees, laissees).
"""
from __future__ import annotations

import contextlib as _contextlib
import os
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT = _ROOT / "RAG" / "embeddings.db"


# ── Base M2M dediee (P0, decision owner 2026-09-05) ──────────────────────────
# `agent_messages` vivait dans RAG/embeddings.db (24,9 Go) et `handle_notify` y
# ecrivait EN SYNCHRONE dans l'event loop avec busy_timeout=15000 : chaque verrou
# tenu par un autre ecrivain (backfill, ingestion, network_log) gelait le hub
# 15 s — 16 morts en 2 jours quand le kill-watchdog etait a 15 s. Meme sortie que
# `access_switches` le 05/09 (LAFORGE_SWITCHES_DB_PATH) : une base a part, hors du
# chemin des gros ecrivains. Migration + verification : tools/forge_m2m_db_split.py.
_M2M_DEFAULT = _ROOT / "sandbox" / "m2m.db"


# BASCULE GLOBALE de la scission (P0 passe 2, 2026-09-06). Tant que ce fichier
# n'existe pas, `m2m_path()` rend la base du RAG : chaque site migre vers
# `open_m2m()` / `m2m_path()` SANS changer de comportement -- scripts et hooks
# tournent depuis l'arbre, un site bascule seul = un hub qui ecrit d'un cote et lit
# de l'autre (mesure passe 1 : 13 SQL du registry sur la meme table). Le jour J :
# poser le fichier, redemarrer hub et daemons (ils lisent le chemin a l'init),
# copie delta ensuite. `LAFORGE_M2M_DB_PATH` prime toujours (tests, migrations).
_M2M_SWITCH = _ROOT / "sandbox" / "m2m.switch"

# --- Journaux : retirer des ECRIVAINS du verrou RAG (owner 2026-09-19) --------
# « On ne deplace pas des tables ; on retire des ecrivains du verrou RAG. » Le
# critere de succes est le NEGATIF : embeddings.db doit CESSER DE RECEVOIR.
# Mesure du 2026-09-19 sur 33 h : token_usage 4 644 + inspector_log 1 954 +
# conversation_log 1 299 = ~7 900 prises du verrou, et 23 `database is locked`
# qui font PERDRE des indexations post-commit (une ecriture SQLite refusee est
# perdue si personne ne la reprend).
# UN seul interrupteur pour les trois (le gain se mesure globalement) ; une
# variable d'environnement PAR journal reste possible pour un repli chirurgical.
_JOURNAUX_SWITCH = _ROOT / "sandbox" / "journaux.switch"
_JOURNAUX = {
    "token_usage": ("LAFORGE_JOURNAL_TOKEN_USAGE_DB", "journal_token_usage.db"),
    "inspector_log": ("LAFORGE_JOURNAL_INSPECTOR_DB", "journal_inspector.db"),
    "conversation_log": ("LAFORGE_JOURNAL_CONVERSATION_DB", "journal_conversation.db"),
}
# Journaux DECLARES mais RETENUS sur la base historique, interrupteur pose ou non.
# Decision owner du 2026-09-22, apres que la CI eut refuse 869f9de16 :
# `forge_conversation_logger` ecrit `conversation_log` ET `rag_chunks` sur la MEME
# connexion. Le basculer enverrait l'insert rag_chunks dans une base de journal
# sans cette table (`OperationalError` a chaque tour, memoire episodique perdue),
# et scinder les deux ecritures ne retirerait presque aucune prise du verrou tant
# que l'insert rag_chunks reste par tour. La retenue vit ICI, pas dans le site :
# l'ecrivain et ses lecteurs cables consultent tous `journal_path`, donc ils
# restent ensemble -- jamais un site qui bascule seul. Seule la variable
# d'environnement PAR journal (repli chirurgical de l'operateur) la leve.
_JOURNAUX_RETENUS = {
    "conversation_log": "ecrivain couple a rag_chunks sur la meme connexion "
                        "(roadmap point 5 : retention conversation_log)",
}


# --- Base d'AUTORITE ----------------------------------------------------
# Ajoute le 2026-09-13. Apres le resserrement des ACL, l'instrument M0.1 ne
# compte plus qu'UN partage reel : la base RAG, ou `LaForgeSandboxUsers` ecrit
# encore -- et c'est elle qui porte `opsec_state` (kill-switch humain) et
# `forge_tools` (bareme d'autorisation). Une ACL de FICHIER ne sait pas separer
# des TABLES : il faut deplacer les tables, et deplacer AVEC elles le domaine
# de confiance. Poser la cible (ou l'interrupteur) sous `sandbox/` ne fermerait
# rien : ce dossier est `(M)` pour LaForgeSandboxUsers, le client rebasculerait
# l'autorite vers la base qu'il ecrit. D'ou `etat_protege/`, qui herite des ACL
# durcies du depot (bacs a sable en lecture seule).
#
# Meme patron que m2m : un INTERRUPTEUR GLOBAL relu A CHAQUE APPEL, jamais une
# migration site par site -- un site qui bascule seul donne un hub qui ecrit
# d'un cote et lit de l'autre. Tant que l'interrupteur est absent, la
# resolution rend la base RAG : pas de bascule accidentelle du kill-switch.


def _racine_depot():
    from pathlib import Path as _P

    return _P(__file__).resolve().parents[1]


def authority_switch_path():
    """Interrupteur de bascule. HORS sandbox : sinon le client le retourne."""
    return _racine_depot() / "etat_protege" / "authority.switch"


def authority_db_defaut():
    """Cible par defaut, dans la zone que les bacs a sable ne peuvent que LIRE."""
    return _racine_depot() / "etat_protege" / "authority.db"


def authority_switch_actif() -> bool:
    """Vrai quand l'autorite vit HORS de la base du RAG (env pose ou interrupteur)."""
    return bool(os.environ.get("LAFORGE_AUTHORITY_DB")) or authority_switch_path().exists()


def authority_path() -> str:
    """Base portant opsec_state et forge_tools. Resolue A CHAQUE APPEL.

    Une constante figee a l'import ne se redirige pas -- defaut paye le
    2026-09-10 puis repaye le 2026-09-12.
    """
    force = os.environ.get("LAFORGE_AUTHORITY_DB")
    if force:
        return force
    if authority_switch_path().exists():
        return str(authority_db_defaut())
    return db_path()


# ── LE PATRON DE BASCULE, ECRIT UNE SEULE FOIS (2026-09-18) ──────────────────
#
# Le gate `duplication` a refuse le commit precedent : en ajoutant la bascule de
# `task_queue`, j'avais RECOPIE les quatre fonctions de M2M au lieu de les
# factoriser. Je croyais « reutiliser le patron prouve » -- je clonais sa forme.
# La regle du depot dit REUTILISER avant de RECONSTRUIRE ; recopier, c'est
# reconstruire avec les memes mots.
#
# Le cout d'un clone n'est pas esthetique : le jour ou l'ordre de priorite change
# (env > interrupteur > historique), il faut le corriger a N endroits, et c'est
# celui qu'on oublie qui fait loi.
def _bascule_active(variable: str, interrupteur: Path) -> bool:
    """Vrai quand une table vit HORS de la base du RAG (env posee ou interrupteur)."""
    return bool(os.environ.get(variable)) or interrupteur.exists()


def _chemin_bascule(variable: str, interrupteur: Path, dediee: Path) -> str:
    """Env > interrupteur > base du RAG. Lu a CHAQUE appel, jamais fige a l'import.

    L'ordre est l'invariant : une variable d'environnement l'emporte sur un
    interrupteur, et l'absence des deux laisse le comportement HISTORIQUE. C'est
    ce dernier point qui rend une bascule sure -- tant qu'on ne l'a pas demandee,
    rien ne change.
    """
    env = os.environ.get(variable)
    if env:
        return str(env)
    if interrupteur.exists():
        return str(dediee)
    return db_path()


def m2m_switch_actif() -> bool:
    """Vrai quand agent_messages vit HORS de la base du RAG."""
    return _bascule_active("LAFORGE_M2M_DB_PATH", _M2M_SWITCH)


def m2m_path() -> str:
    """Chemin de la base M2M (agent_messages), lu a CHAQUE appel."""
    return _chemin_bascule("LAFORGE_M2M_DB_PATH", _M2M_SWITCH, _M2M_DEFAULT)


def journaux_connus() -> tuple:
    """Les journaux que l'interrupteur sait deplacer. Nommer, jamais deviner."""
    return tuple(sorted(_JOURNAUX))


def journaux_retenus() -> dict:
    """Journaux que l'interrupteur NE deplace PAS, avec leur raison. Nommer, jamais taire."""
    return dict(_JOURNAUX_RETENUS)


def journaux_bascules() -> bool:
    """L'interrupteur global est-il pose ? (l'env par journal ne compte pas ici)"""
    return _JOURNAUX_SWITCH.exists()


def journal_path(nom: str) -> str:
    """Chemin de la base d'un JOURNAL, lu a CHAQUE appel, jamais fige a l'import.

    Tant que `sandbox/journaux.switch` est absent, rend `db_path()` : le
    comportement HISTORIQUE. Un site qui migre vers cet accesseur ne change donc
    PAS de comportement — c'est ce qui permet de verifier la migration AVANT de
    basculer, et de basculer d'un seul geste ensuite.

    Un nom inconnu LEVE au lieu de retomber sur la base RAG : un journal non
    declare qui reviendrait silencieusement dans embeddings.db serait exactement
    la panne que ce mecanisme existe pour empecher.
    """
    try:
        variable, fichier = _JOURNAUX[nom]
    except KeyError:
        raise ValueError(
            "journal inconnu: %r — connus: %s. Un nom non declare retomberait dans "
            "la base RAG, ce que cet accesseur existe pour empecher."
            % (nom, ", ".join(journaux_connus()))) from None
    if nom in _JOURNAUX_RETENUS:
        # Env > base historique : l'interrupteur global ne s'applique pas.
        return str(os.environ.get(variable) or db_path())
    return _chemin_bascule(variable, _JOURNAUX_SWITCH, _ROOT / "sandbox" / fichier)


class CheminJournal(os.PathLike):
    """Chemin d'un journal, resolu a CHAQUE acces, jamais fige a l'import.

    Une constante `DB = ROOT / "RAG" / "embeddings.db"` calculee a l'import ne
    peut pas suivre un interrupteur : le jour de la bascule, ce site continue de
    LIRE la base de 26 Go pendant que l'ecrivain part ailleurs. C'est le defaut
    que la regle du depot nomme -- un site qui bascule seul fait ecrire d'un cote
    et lire de l'autre.

    Mesure du 2026-09-22, dans la validation qui a PRECEDE la bascule : ONZE
    lecteurs des trois journaux resolvaient ainsi leur base. Le patron existait
    deja dans `forge_token_monitor` ; il est remonte ICI plutot que recopie onze
    fois -- reutiliser avant de reconstruire.

    Elle se substitue a la constante SANS TOUCHER AUX SITES D'USAGE : `str(DB)`,
    `sqlite3.connect(DB)`, `DB.exists()` et `Path(DB)` continuent de fonctionner.

    Tant que ni la variable d'environnement du journal ni `sandbox/journaux.switch`
    ne sont poses, elle rend la base HISTORIQUE : le cablage ne change donc AUCUN
    comportement, et c'est ce qui permet de le certifier AVANT de basculer.
    """

    __slots__ = ("_journal",)

    def __init__(self, journal: str) -> None:
        # Un nom inconnu echoue ICI, a la construction, et non au premier acces
        # au fond d'une pile d'appels : `journal_path` leve deja pour ne jamais
        # retomber silencieusement sur la base RAG.
        journal_path(journal)
        self._journal = journal

    def __fspath__(self) -> str:
        return journal_path(self._journal)

    def __str__(self) -> str:
        return journal_path(self._journal)

    def __repr__(self) -> str:
        return "CheminJournal(%r -> %s)" % (self._journal, journal_path(self._journal))

    def exists(self) -> bool:
        """Les lecteurs testent `DB.exists()` avant d'ouvrir : on le conserve."""
        return Path(journal_path(self._journal)).exists()

    def as_posix(self) -> str:
        """Plusieurs lecteurs construisent une URI `file:%s?mode=ro`."""
        return Path(journal_path(self._journal)).as_posix()

    @property
    def parent(self) -> Path:
        return Path(journal_path(self._journal)).parent


@_contextlib.contextmanager
def lecteur_journal(nom: str, conn, base_actuelle: str):
    """Connexion de LECTURE vers un journal, dediee SEULEMENT s'il a bascule.

    Motif repete dans cinq modules le 2026-09-22 : un lecteur ouvre UNE connexion
    et y interroge a la fois un journal et des tables qui restent dans la base du
    RAG. Substituer sa base globale casserait les secondes ; garder la connexion
    unique ferait lire un journal FIGE apres la bascule, sans la moindre erreur.

    Tant que le journal n'a pas bascule, on rend `conn` TELLE QUELLE : aucune
    connexion de plus, aucun comportement change. Des qu'il bascule, on ouvre une
    connexion en lecture seule vers sa base et on la ferme en sortant -- et
    SEULEMENT celle-la : fermer la connexion de l'appelant le priverait de la
    sienne au milieu de son travail.

    Ce helper vit ICI, chez le proprietaire du domaine, parce que la meme logique
    avait commence a etre recopiee site par site. Et il rend l'ecriture dans les
    fichiers appelants MINIMALE -- ce qui compte pour un CRITICAL_FILE de 9 241
    lignes, dont l'edition gouvernee a fait tomber le hub le 2026-09-22.
    """
    cible = journal_path(nom)
    if cible == str(base_actuelle):
        yield conn
        return
    dedie = sqlite3.connect("file:%s?mode=ro" % cible.replace("\\", "/"),
                            uri=True, timeout=5)
    dedie.row_factory = getattr(conn, "row_factory", None)
    try:
        yield dedie
    finally:
        dedie.close()


# Schema d'`agent_messages` tel que lu dans sqlite_master de RAG/embeddings.db le
# 2026-09-05 (table + 6 index). La MIGRATION relit la source ; ceci n'est que le
# filet pour un hub qui ecrit dans une base M2M encore vide.
M2M_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS agent_messages ("
    " id TEXT PRIMARY KEY, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL,"
    " correlation_id TEXT, method TEXT NOT NULL, payload TEXT, result TEXT,"
    " status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')), read_at TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_to ON agent_messages(to_agent, status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_corr ON agent_messages(correlation_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_status ON agent_messages(status)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_created_at ON agent_messages(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_method ON agent_messages(method)",
    "CREATE INDEX IF NOT EXISTS idx_agent_messages_from_agent ON agent_messages(from_agent)",
)


def _poser_schema(conn: sqlite3.Connection, schema) -> None:
    for sql in schema:
        conn.execute(sql)


def _ouvrir_dediee(chemin: str, schema, dediee_active: bool,
                   timeout: float) -> sqlite3.Connection:
    """Connexion ecriture a une base BASCULEE, schema garanti si elle est dediee.

    Le garde `dediee_active` n'est pas un detail : AVANT la bascule, `chemin` est
    la base du RAG (25 Go, GELEE) ou la table existe deja. Y poser un schema
    serait ecrire dans la grosse base pour rien -- et un CREATE sur une base
    gelee est exactement ce qu'on cherche a eviter.
    """
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    c = open_writer(timeout=timeout, path=chemin)
    if dediee_active:
        _poser_schema(c, schema)
    return c


def ensure_m2m_schema(conn: sqlite3.Connection) -> None:
    _poser_schema(conn, M2M_SCHEMA)


def open_m2m(timeout: float = 15.0) -> sqlite3.Connection:
    """Connexion ecriture a la base M2M : memes reglages qu'`open_writer`, schema garanti."""
    return _ouvrir_dediee(m2m_path(), M2M_SCHEMA, m2m_switch_actif(), timeout)


# ── FILE DE TACHES — meme patron d'interrupteur que M2M (2026-09-18) ──────────
#
# POURQUOI. `forge_task_queue` ouvrait 7 fois `sqlite3.connect(str(DB))` avec
# `DB = ROOT/RAG/embeddings.db`. Mesure du 2026-09-18 : ce chemin et celui rendu
# par `db_path()` designent LE MEME FICHIER PHYSIQUE (`V:` est un lecteur
# SUBSTITUE vers `Nokido/RAG/` — meme `dev`, meme `ino`, `os.path.samefile()`
# rend True). La file de taches se battait donc pour le verrou d'ecriture de la
# base RAG de 25 Go, sans aucune raison metier : SQLite n'admet qu'UN writer par
# FICHIER, WAL ou non.
#
# ⚠️ Le piege qui rend ce defaut invisible : comparer les deux chemins en TEXTE
# rend False. Le faux negatif va dans le sens rassurant — il fait conclure a une
# absence de contention qui existe. Seul `samefile`/`st_dev+st_ino` tranche.
#
# FORME. Identique a `m2m_*`, volontairement : l'interrupteur est lu A CHAQUE
# APPEL, les sites migrent SANS changement de comportement, et tant que la
# bascule n'a pas eu lieu le chemin reste celui d'avant. Un site qui bascule seul
# est le defaut qu'on evite : un producteur qui ecrit d'un cote et un drain qui
# lit de l'autre.
_TASKS_DEFAULT = _ROOT / "sandbox" / "task_queue.db"
_TASKS_SWITCH = _ROOT / "sandbox" / "task_queue.switch"


def tasks_switch_actif() -> bool:
    """Vrai quand `task_queue` vit HORS de la base du RAG."""
    return _bascule_active("LAFORGE_TASKS_DB_PATH", _TASKS_SWITCH)


def tasks_path() -> str:
    """Chemin de la base de la file de taches, lu a CHAQUE appel."""
    return _chemin_bascule("LAFORGE_TASKS_DB_PATH", _TASKS_SWITCH, _TASKS_DEFAULT)


# Schema releve dans `sqlite_master` de la base VIVANTE le 2026-09-18 (293
# caracteres, table SEULE : la source ne portait AUCUN index). La migration
# relit la source ; ceci est le filet pour une base de file encore vide.
#
# Les deux index sont AJOUTES par la bascule, ils n'existaient pas : le worker
# fait `WHERE status=? ORDER BY priority, id`, donc un balayage complet a chaque
# reveil. C'est sans effet a 3 lignes et cela ne le reste pas.
TASKS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS task_queue ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " ts TEXT DEFAULT (datetime('now')),"
    " title TEXT NOT NULL,"
    " role TEXT DEFAULT 'EXECUTOR',"
    " priority TEXT DEFAULT 'NORMAL',"
    " status TEXT DEFAULT 'PENDING',"
    " context TEXT DEFAULT '',"
    " result TEXT DEFAULT '',"
    " started_at TEXT,"
    " done_at TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority, id)",
    "CREATE INDEX IF NOT EXISTS idx_task_queue_ts ON task_queue(ts)",
)


def ensure_tasks_schema(conn: sqlite3.Connection) -> None:
    _poser_schema(conn, TASKS_SCHEMA)


def open_tasks(timeout: float = 15.0) -> sqlite3.Connection:
    """Connexion ecriture a la base de la file : memes reglages qu'`open_writer`."""
    return _ouvrir_dediee(tasks_path(), TASKS_SCHEMA, tasks_switch_actif(), timeout)


def db_path() -> str:
    """Realpath de la base RAG (résout le symlink C:->V:). Writable partout."""
    p = os.environ.get("LAFORGE_DB") or str(_DEFAULT)
    try:
        return os.path.realpath(p)
    except Exception:
        return p


DB_PATH = db_path()


def checkpoint_wal(seuil_mo: float = 512.0, *, truncate: bool = False,
                   attente_s: float = 60.0) -> dict:
    """Verse le WAL dans la base quand il depasse `seuil_mo`.

    Mesure 2026-09-01 : trois ingestions concurrentes (408 325 chunks) ont porte
    `embeddings.db-wal` a 53 Go et SATURE le volume V: — 0 octet libre. Toute
    ecriture RAG s'est alors mise a rendre `disk I/O error` : le sidecar de traces
    est parti en quarantine et le hub est tombe deux fois. Le checkpoint de
    rattrapage a montre l'ampleur du gaspillage — 12 857 716 pages versees pour
    seulement 0,21 Go de donnees reelles : ces 53 Go etaient des REECRITURES.

    L'auto-checkpoint natif de SQLite (1000 pages) n'y suffit pas : il ne tronque
    JAMAIS un WAL qu'un lecteur reference encore, et le hub garde des connexions
    ouvertes en permanence. Le GC glymphatique (`forge_glymphatic_gc`) fait bien
    ce travail, mais seulement en phase NREM3 — une ingestion de jour ne l'atteint
    jamais. Un garde juste, branche sur une horloge la ou il fallait la PRESSION.

    PASSIVE par defaut : on verse ce qui peut l'etre sans jamais bloquer un
    lecteur. Un retour `busy=1` est donc l'ABSTENTION NORMALE, pas un echec — le
    rattrapage du 01/09 a rendu exactement cela, avec 99,998 % des pages versees.
    TRUNCATE (`truncate=True`) ne rend le FICHIER au disque que si personne ne
    tient la base : en pratique, au boot uniquement.

    Rend TOUJOURS un dict qui dit ce qui s'est passe, y compris quand rien n'a pu
    etre fait : distinguer « rien a faire » de « je n'ai pas pu regarder » est
    justement ce dont l'absence a coute l'incident.
    """
    wal = Path(DB_PATH + "-wal")
    try:
        taille_mo = wal.stat().st_size / (1024 * 1024)
    except FileNotFoundError:
        return {"fait": False, "raison": "pas de WAL"}
    except OSError as exc:                      # illisible n'est PAS absent
        return {"fait": False, "raison": "wal illisible: %s" % exc}
    if taille_mo < seuil_mo:
        return {"fait": False, "wal_mo": round(taille_mo, 1),
                "raison": "sous le seuil"}
    mode = "TRUNCATE" if truncate else "PASSIVE"
    # `attente_s` : un TRUNCATE tient le verrou d'ecriture PENDANT qu'il attend les
    # lecteurs. Mesure 2026-09-23 : appele entre chaque depot avec 60 s d'attente,
    # il rendait busy=1 a chaque fois et bloquait tous les ecrivains une minute —
    # l'ingestion elle-meme a fini en `database is locked`. Un appelant repete
    # demande une attente COURTE : s'abstenir vite vaut mieux que bloquer tout.
    try:
        conn = sqlite3.connect(DB_PATH, timeout=attente_s)
        try:
            busy, pages, verses = conn.execute(
                "PRAGMA wal_checkpoint(%s)" % mode).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"fait": False, "wal_mo": round(taille_mo, 1),
                "raison": "sqlite: %s" % exc}
    try:
        apres_mo = round(wal.stat().st_size / (1024 * 1024), 1)
    except OSError:  # muet-ok : le checkpoint a REUSSI, seule la re-mesure echoue
        # -1.0 le DIT, la ou 0.0 ferait passer un echec de lecture pour un WAL
        # vide — soit un disque annonce libere alors qu'il ne l'est pas.
        apres_mo = -1.0
    return {"fait": True, "mode": mode, "busy": busy, "pages": pages,
            "verses": verses, "wal_mo_avant": round(taille_mo, 1),
            "wal_mo_apres": apres_mo}


def write_retry(op, *, attempts: int = 6, base_delay: float = 0.2,
                timeout: float | None = None):
    """Execute `op(conn)` en ECRITURE, en attendant son tour au lieu d'abandonner.

    `open_writer` (autocommit + WAL + busy_timeout) suffit dans l'immense majorite
    des cas. Il reste deux situations ou l'ecriture echoue quand meme :
      - un voisin tient une transaction EXPLICITE plus longue que le busy_timeout ;
      - un voisin mal ecrit (`sqlite3.connect()` nu) garde un verrou implicite.
    Mesure 2026-07-25 : trois veilles lancees pendant une ingestion ont toutes rendu
    `OperationalError: database is locked` et ont ete PERDUES — aucune n'a ete
    reessayee, aucune n'a ete mise en attente.

    Ici l'ecriture n'est jamais jetee : elle est REPRISE avec un recul croissant.
    Le jitter est indispensable — sans lui, N ecrivains reveilles par le meme verrou
    repartent tous a la meme milliseconde et se bloquent mutuellement (« troupeau
    tonnant »). Seules les erreurs de VERROU sont reprises : une contrainte violee
    ou une table absente remonte immediatement, car la reessayer ne changerait rien.

    Usage :
        from forge_db_path import write_retry
        write_retry(lambda c: c.execute("INSERT INTO t VALUES (?)", (x,)))
    """
    import random
    import time

    # UN `None` QUI VEUT DIRE « DECIDE TOI-MEME » NE TRAVERSE PAS UNE FRONTIERE.
    # Mesure 2026-09-07 : en rendant le budget configurable, cette fonction s'est mise
    # a appeler `open_writer(timeout=None)`. Le vrai `open_writer` resout None -- mais
    # un `None` PASSE EXPLICITEMENT ecrase le defaut de toute doublure ecrite contre le
    # contrat precedent (`lambda timeout=30.0: sqlite3.connect(...)`), qui le donnait
    # ensuite a sqlite3 : `TypeError: must be real number, not NoneType`. 8 tests
    # casses dans deux fichiers FTS, pour une seule ligne. On resout ICI, ou la valeur
    # est connue ; le collaborateur ne recoit jamais qu'un nombre.
    # NR : test_socle_attente_bornee_nr::test_write_retry_ne_propage_JAMAIS_None...
    if timeout is None:
        timeout = busy_ms() / 1000.0

    last = None
    for i in range(max(1, attempts)):
        conn = open_writer(timeout=timeout)
        try:
            return op(conn)
        except sqlite3.OperationalError as e:
            last = e
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                raise  # pas un verrou : la reprise serait un deni du vrai probleme
            if i == attempts - 1:
                break
            time.sleep(base_delay * (2 ** i) + random.uniform(0, 0.15))
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001  # muet-ok : fermeture de courtoisie
                # Une connexion deja morte n'a rien a apprendre a l'appelant, et
                # lever ICI masquerait l'erreur d'ecriture qu'on est en train de
                # remonter.
                pass
    raise sqlite3.OperationalError(
        f"ecriture abandonnee apres {attempts} tentatives sur verrou ({last}) — "
        "un voisin tient une transaction trop longue ; chercher un "
        "`sqlite3.connect()` nu chez l'ecrivain concurrent")


def purger_fts(con, anciens) -> tuple[int, list[str]]:
    """Purge des lignes de `rag_fts` SANS balayer la table ; rend (supprimees, laissees).

    `chunk_id`, `source` et `domain` y sont UNINDEXED : `DELETE ... WHERE chunk_id=?`
    est un SCAN complet de l'index lexical, sous le verrou d'ecriture de la base RAG
    pendant toute sa duree. Mesures : 6,2 Go lus / 2 min 44 s par commit
    (`forge_module_cards`, 2026-09-23) ; l'audit NREM1 en enchainait 17 -- verrou tenu
    ~1 h chaque soir a 22 h, hub fige (2026-09-27 : 347 Mo lus en 15 s, 0 ecrit).

    Seul `text` est indexe : on restreint par une phrase de l'ANCIEN texte -- a lire
    par cle primaire dans `rag_chunks` AVANT de le remplacer -- et l'id reste le
    filtre EXACT. `anciens` = iterable de (chunk_id, ancien_texte).
    Sans mot exploitable, la ligne est LAISSEE et rendue a l'appelant, qui le DIT :
    `purge_rag_fts_fantomes()` (sommeil NREM3) la reprend.
    Source unique : `forge_post_commit._purger_fts` et l'audit du corps y delegent.
    NR : tests/nr/test_audit_regulation_fts_sans_scan_nr.py
    """
    import re

    n, laissees = 0, []
    for cid, texte in anciens:
        mots = re.findall(r"\w+", texte or "")[:8]
        if not mots:
            laissees.append(cid)
            continue
        n += con.execute(
            "DELETE FROM rag_fts WHERE rowid IN (SELECT rowid FROM rag_fts "
            "WHERE rag_fts MATCH ? AND chunk_id = ?)",
            ('"%s"' % " ".join(mots), cid)).rowcount
    return n, laissees


def chunk_id(source: str, texte: str) -> str:
    """Identifiant canonique d'un chunk : sha256(source|texte)[:16].

    MEME formule que `forge_self_correction._chunk_id` et `RAGEngine.make_chunk_id`
    — on ne cree pas une troisieme convention, on expose celle qui existe deja la
    ou tous les ecrivains passent. Deterministe : re-ecrire le meme contenu depuis
    la meme source rend le meme id, donc `INSERT OR REPLACE` remplace au lieu de
    dupliquer.
    """
    import hashlib

    cle = "%s|%s" % (source or "", texte or "")
    return hashlib.sha256(cle.encode("utf-8", errors="replace")).hexdigest()[:16]


def ecrire_chunk(conn, source: str, domain: str, texte: str, *,
                 cap: int | None = None, dire=None) -> dict:
    """Ecrit UN chunk dans `rag_chunks`, avec sa clef, sans amputer en silence.

    DEFAUT CORRIGE le 2026-09-12, mesure sur 2 240 678 chunks. Seize ecrivains
    faisaient `INSERT OR IGNORE INTO rag_chunks(source,domain,text)` — sans `id`,
    alors que c'est un TEXT PRIMARY KEY (regle d'or n°3) : la clef restait NULLE
    et la deduplication ne pouvait plus operer. Quinze d'entre eux tronquaient en
    prime le texte par une tranche muette (`text[:2000]`, `[:800]`, `[:4000]`...).

    Effet MESURE par le test du pic (effectif a la borne contre ses voisines) :
        len == 2000 : 13 896 chunks, ratio 159,7 contre les voisines -> TRONCATURE
        len == 3000 :    562 chunks, ratio  11,7                     -> TRONCATURE
        len == 4000 :  1 053 chunks, ratio   9,4                     -> TRONCATURE
    soit ~15 500 chunks amputes, 0,69 % du corpus. Le contenu etait disponible et
    jete. Aucune contrainte technique ne le justifiait : la plus longue valeur
    presente en base est de 177 479 caracteres.

    `cap` reste possible — on interdit le silence, pas la limite — mais il DIT
    alors ce qu'il ecarte, pour qu'un rattrapage reste possible (gate
    `borne_trop_serree`, qui avait deja compte 377 documents de veille detruits).
    """
    texte = texte or ""
    complet = len(texte)
    ecarte = 0
    if cap is not None and complet > cap:
        ecarte = complet - cap
        texte = texte[:cap]
        msg = ("[chunk] %s : %d caracteres ecartes sur %d (cap %d) — le reste "
               "n'est PAS ingere" % (source, ecarte, complet, cap))
        if dire is not None:
            dire(msg)
        else:
            import sys as _s
            print(msg, file=_s.stderr, flush=True)

    cid = chunk_id(source, texte)
    conn.execute(
        "INSERT OR REPLACE INTO rag_chunks(id, source, domain, text) VALUES(?,?,?,?)",
        (cid, source, domain, texte),
    )
    return {"id": cid, "longueur": len(texte), "ecarte": ecarte}


def busy_ms() -> int:
    """Interrupteur global de budget d'attente (ms)."""
    env_val = os.environ.get("LAFORGE_SQLITE_BUSY_MS")
    default_ms = 30000
    if env_val is not None:
        try:
            val = int(env_val)
            if val > 0:
                return val
        except ValueError:
            pass
        print(f"LAFORGE_SQLITE_BUSY_MS invalide ({env_val}), repli sur {default_ms} ms", flush=True)
    return default_ms


# 64 Mo : largement au-dessus d'un cycle d'autocheckpoint (500 pages ~ 2 Mo),
# loin des 23-48 Go mesures le 2026-09-23. Partage avec forge_db._PRAGMAS_RW.
JOURNAL_SIZE_LIMIT_OCTETS = 64 * 1024 * 1024


def open_writer(timeout: float | None = None, path: str | None = None) -> sqlite3.Connection:
    """Connexion ECRITURE au pattern DEJA PROUVE de `forge_swarm_blackboard`
    (decision archi 2026-06-04, SQLite WAL mono-writer, bench « 0 contention /
    0 echec » sous N workers concurrents). A utiliser par TOUT script qui ecrit
    dans la base RAG -- ne pas re-improviser un `sqlite3.connect()` nu.

    Les trois reglages qui font la difference, et pourquoi :
      - `isolation_level=None` (AUTOCOMMIT) : sans lui, le module sqlite3 ouvre une
        transaction IMPLICITE au premier INSERT et ne la referme qu'au commit. Un
        `_step_ingest` de 80 INSERT tient alors le verrou d'ecriture pendant toute
        la boucle, et un second ecrivain echoue malgre son busy_timeout -- c'est
        exactement le « database is locked » mesure le 2026-07-25 pendant un
        rattrapage. En autocommit, chaque INSERT est court : les ecrivains
        concurrents s'entrelacent au lieu de se bloquer.
      - `journal_mode=WAL` : un ecrivain n'exclut plus les lecteurs.
      - `busy_timeout` : sous collision, on ATTEND (ms) au lieu de lever.
    `check_same_thread=False` : ces scripts ecrivent parfois depuis un pool de
    threads, comme le writer du blackboard.
    """
    if timeout is None:
        timeout = busy_ms() / 1000.0
    c = sqlite3.connect(path or db_path(), timeout=timeout, isolation_level=None,
                        check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.execute(f"PRAGMA busy_timeout={int(timeout * 1000)};")
    # Reglages de PERFORMANCE, alignes sur `forge_db.py::_PRAGMAS_RW` (l'autre
    # porte d'ecriture, qui les portait deja) : sans eux, un gros ingest trie sur
    # disque et relit les pages a chaque scan. Ils sont par CONNEXION, donc les
    # poser ici est le seul moyen qu'ils s'appliquent aux ecrivains.
    c.execute("PRAGMA cache_size=-64000;")   # 64 Mo de cache de pages
    c.execute("PRAGMA temp_store=MEMORY;")   # tris / GROUP BY en RAM
    c.execute("PRAGMA mmap_size=2147483648;")  # 2 Go mappes, lectures via le cache OS
    # ALIGNEMENT COMPLETE le 2026-09-18. Le commentaire ci-dessus annonce un
    # alignement sur `forge_db.py::_PRAGMAS_RW` ; il etait PARTIEL --
    # `wal_autocheckpoint` y figure (500) et manquait ici. Consequence : la
    # politique de checkpoint dependait de la PORTE empruntee, 500 d'un cote et
    # le defaut SQLite (1000 pages) de l'autre, pour le MEME fichier. Deux
    # politiques silencieuses valent moins qu'une seule, meme imparfaite : c'est
    # un defaut de relecture, on ne sait pas laquelle s'applique.
    #
    # La valeur n'est pas choisie ici, elle est REPRISE de l'autre porte d'ecriture,
    # ou elle tourne en production. Le bornage explicite du WAL reste
    # `checkpoint_wal()` (mesure du 2026-09-01, apres un WAL parti a 53 Go) :
    # l'autocheckpoint est un filet de fond, pas le mecanisme de bornage.
    c.execute("PRAGMA wal_autocheckpoint=500;")
    # RETRECISSEMENT du WAL (2026-09-23, veille SQLite prioritaire owner). Doc
    # sqlite.org/wal.html : a chaque remise a zero, SQLite reecrit le WAL depuis le
    # debut SANS reduire le fichier, SAUF si journal_size_limit est pose. Il ne
    # l'etait sur aucune porte : WAL a 23 puis 48 Go, V: a 3 Go libres. Il ne
    # guerit pas la famine de checkpoint (un lecteur long empeche la remise a
    # zero) mais rend le disque des qu'elle a lieu, sans TRUNCATE agressif.
    c.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT_OCTETS};")
    return c
