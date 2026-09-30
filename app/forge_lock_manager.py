"""
forge_lock_manager.py — Phase 2.3 Lock Manager sémantique
==========================================================
"Enzymes de régulation" du cytoplasme Nokido.

Si 2 agents écrivent dans 2 fichiers DIFFÉRENTS → parallèle (chaque locque sa ressource).
Si 2 agents écrivent dans LE MÊME fichier → 2e mis en file FIFO jusqu'au release.

API async (asyncio.Lock par ressource), SQLite-backed pour crash-recovery.

Author-Agent: CLAUDE
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import secrets
import socket
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # psutil ABSENT n'est pas psutil qui dit NON : cf. etat_holder()
    import psutil
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore[assignment]

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:lock_manager|phase:2.3|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT_S = 30.0

# Trois etats du holder. `INCONNU` n'est PAS `MORT` : un verrou dont on ne sait
# pas lire le proprietaire reste tenu. La constitution semantique du corps
# interdit de ranger UNKNOWN du cote « libre » (2026-09-05).
ETAT_VIVANT = "VIVANT"
ETAT_MORT = "MORT"
ETAT_INCONNU = "INCONNU"


def _db_defaut() -> Path:
    """Base du registre de verrous : un fichier DEDIE, jamais celle du RAG.

    ⚠️ C'ETAIT `ROOT/RAG/embeddings.db` — mesure du 2026-09-12 : ce fichier porte
    la MEME taille que `%NOKIDO_DATA%\embeddings.db` (26 519 080 960 octets) et la table
    `locks_state` y existait deja. Le registre ecrivait donc dans la base GELEE
    de 24,7 Go, que la roadmap sort de la chaine critique.

    ⚠️⚠️ PREMIER CORRECTIF, INSUFFISANT, et c'est la CI qui l'a dit. Passer par
    `forge_db_path.m2m_path()` paraissait honorer l'interrupteur global du corps.
    Mais `m2m_path()` ne rend `sandbox/m2m.db` QUE si `sandbox/m2m.switch` existe,
    et ce fichier n'est PAS VERSIONNE : dans un worktree de preuve detache il est
    absent, donc `m2m_path()` retombe sur `db_path()`, c'est-a-dire exactement la
    base gelee qu'on voulait fuir. Mesure : le NR est sorti ROUGE dans le worktree
    de la CI de reference sur `.../worktree/rag/embeddings.db` alors qu'il etait
    VERT dans l'arbre principal.

    Lecon retenue : **l'emplacement d'un registre ne doit pas dependre d'un
    fichier non versionne**, sinon le comportement change selon le checkout. Le
    verrou prend donc un fichier a lui, resolu depuis la racine du code qui
    tourne — ce qui isole aussi correctement un worktree de l'arbre principal.
    """
    env = os.environ.get("LAFORGE_LOCKS_DB")
    if env:
        return Path(env)
    return ROOT / "sandbox" / "locks.db"


DEFAULT_DB = _db_defaut()


def _resource_key(resource: str | Tuple[str, str]) -> str:
    """Normalise resource en clé string. (path, section) -> 'path::section'."""
    if isinstance(resource, tuple):
        return f"{resource[0]}::{resource[1]}"
    return str(resource).strip()


def cle_workdir_agy(workdir) -> str:
    """Ressource REELLE d'un lancement agy : le repertoire qu'il a le droit d'ECRIRE.

    Les deux surfaces qui lancent `agy.exe` passent `--add-dir <workdir>` ET
    `--dangerously-skip-permissions` — agy edite donc ce repertoire. Elles lisent
    la MEME variable `LAFORGE_AGY_WORKDIR` avec des defauts DIFFERENTS :
    `app/forge_agent_proxy.py` (GeminiCLI) retombe sur `C:\\tmp`, et
    `tools/forge_task_executor._delegate_to_agy` sur la racine du depot.

    D'ou la cle : elle vient du CHEMIN RESOLU, jamais de l'identite « AGY ».
      - variable absente -> deux repertoires -> deux cles -> les deux chemins
        tournent EN PARALLELE, c'est le decouplage ;
      - variable posee   -> un repertoire -> une cle -> ils SERIALISENT, sinon
        deux agy en skip-permissions s'ecrasent dans le meme arbre.
    Une cle « agy » tout court se tromperait dans les deux cas : elle bloquerait
    un `ask` interactif pendant une delegation de 20 minutes sans rien garder de
    plus quand les repertoires coincident vraiment.

    NON GARDE ICI, et nomme plutot que tu : les deux chemins forcent aussi
    HOME/LOCALAPPDATA vers le profil owner, donc vers le meme magasin OAuth agy.
    Aucune corruption de ce magasin n'a ete MESUREE — y poser un mutex serait un
    garde branche sur un signal que personne n'emet.
    """
    p = str(workdir).strip().strip('"').strip("'")
    try:
        p = os.path.abspath(os.path.expandvars(os.path.expanduser(p)))
    except Exception:  # noqa: BLE001
        pass
    p = os.path.normcase(os.path.normpath(p)).rstrip("\\/")
    return f"agy:workdir:{p}"


def etat_holder(pid, boot: Optional[float] = None) -> Tuple[str, str]:
    """(etat, motif) du process qui tient un verrou. TROIS etats, jamais deux.

    Un capteur qui rend `False` pour « pas la » ET pour « acces refuse » fabrique
    des faux negatifs indetectables : ici, un verrou vole a un process bien
    vivant. Chaque chemin d'ignorance rend donc INCONNU **avec son motif**, et
    INCONNU ne libere rien.

    `pid` seul ne prouve rien — Windows recycle les pid. L'identite se ferme sur
    le couple (pid, create_time) ; create_time non enregistre => INCONNU, jamais
    VIVANT (on ne fabrique pas une preuve qu'on n'a pas).
    """
    if psutil is None:
        return ETAT_INCONNU, "psutil indisponible dans cet interpreteur"
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ETAT_INCONNU, f"pid non enregistre ({pid!r})"
    if pid <= 0:
        return ETAT_INCONNU, f"pid invalide ({pid})"
    try:
        if not psutil.pid_exists(pid):
            return ETAT_MORT, f"pid {pid} absent de la table des process"
    except Exception as e:  # noqa: BLE001
        return ETAT_INCONNU, f"table des process illisible ({type(e).__name__})"
    try:
        vrai_boot = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return ETAT_MORT, f"pid {pid} disparu entre deux lectures"
    except psutil.AccessDenied:
        return ETAT_INCONNU, f"acces refuse au pid {pid} — process d'un autre compte"
    except Exception as e:  # noqa: BLE001
        return ETAT_INCONNU, f"pid {pid} illisible ({type(e).__name__})"
    if boot is None:
        return ETAT_INCONNU, f"pid {pid} vivant mais create_time non enregistre — identite non prouvee"
    try:
        ecart = abs(float(vrai_boot) - float(boot))
    except (TypeError, ValueError):
        return ETAT_INCONNU, f"create_time enregistre illisible ({boot!r})"
    if ecart > 1.0:
        return ETAT_MORT, f"pid {pid} recycle (create_time {vrai_boot:.0f} != {float(boot):.0f})"
    return ETAT_VIVANT, f"pid {pid} vivant, create_time concordant"


def _mon_boot() -> Optional[float]:
    """create_time du process courant, ou None si illisible — et None se DIT."""
    if psutil is None:
        return None
    try:
        return psutil.Process(os.getpid()).create_time()
    except Exception:  # noqa: BLE001
        return None


@dataclass
class LockState:
    resource: str
    state: str  # FREE | LOCKED | RELEASED
    owner_agent: Optional[str]
    owner_token: Optional[str]
    locked_at: Optional[float]
    queue_size: int = 0
    holder_pid: Optional[int] = None
    holder_etat: str = ETAT_INCONNU
    motif: str = ""


class LockManager:
    """Manager async + SQLite recovery.

    States machine : FREE -> LOCKED (acquire) -> RELEASED (release ou timeout).
    Concurrent acquire même resource = mis en queue interne (asyncio.Lock chain).
    """

    def __init__(self, db_path: Optional[Path] = None, default_timeout: float = DEFAULT_TIMEOUT_S):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.default_timeout = default_timeout
        # In-process locks par ressource (confort asyncio ; ce n'est PAS ce qui
        # exclut : l'exclusion reelle est la ligne `locks_state`, cf. _tenter).
        self._locks: Dict[str, asyncio.Lock] = {}
        # Token -> (resource, owner_agent)
        self._tokens: Dict[str, Tuple[str, str, float]] = {}
        # Queue size par ressource (info)
        self._queue_size: Dict[str, int] = {}
        self.dernier_refus: str = ""
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _init_schema(self) -> None:
        # ⚠️ Pas de `try/except: pass` ici, et c'est mesure : l'exception avalee
        # rendait `exist_ok=True` INTUABLE — un mutant qui le passe a False leve
        # puis se fait manger, donc aucun test ne peut voir la difference. Le
        # cliquet de mutation le signalait comme survivant, et le gate
        # `chemin d'erreur MUET` pointait la meme ligne.
        # Sur le fond : un registre dont on ne peut pas creer le dossier ne peut
        # PAS fonctionner. Echouer ici, bruyamment, vaut mieux que decouvrir
        # l'absence de verrou au premier conflit.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:  # noqa: BLE001
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locks_state (
                resource TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                owner_agent TEXT,
                owner_token TEXT,
                locked_at REAL,
                released_at REAL,
                timeout_s REAL,
                queue_size INTEGER DEFAULT 0
            )
        """)
        # L'identite du holder est ce qui manquait : sans elle, `recover_from_db`
        # ne pouvait QUE liberer aveuglement. Ajout non destructif sur une table
        # deja en place.
        colonnes = {r[1] for r in conn.execute("PRAGMA table_info(locks_state)")}
        for nom, decl in (("holder_pid", "INTEGER"), ("holder_boot", "REAL"), ("holder_host", "TEXT")):
            if nom not in colonnes:
                conn.execute(f"ALTER TABLE locks_state ADD COLUMN {nom} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_locks_state ON locks_state(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_locks_owner ON locks_state(owner_agent)")
        conn.close()

    def _tenter(self, key: str, agent: str, timeout_s: float) -> Tuple[Optional[str], str]:
        """UNE tentative, dans UNE transaction. Rend (token|None, motif)."""
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, owner_agent, holder_pid, holder_boot FROM locks_state WHERE resource=?",
                (key,),
            ).fetchone()
            if row and row[0] == "LOCKED":
                etat, motif = etat_holder(row[2], row[3])
                if etat != ETAT_MORT:
                    conn.execute("ROLLBACK")
                    return None, f"tenu par {row[1]} — holder {etat} ({motif})"
                # Holder MORT et PROUVE mort : on reprend, en le disant.
            token = "lk_" + secrets.token_hex(8)
            conn.execute(
                "INSERT OR REPLACE INTO locks_state "
                "(resource,state,owner_agent,owner_token,locked_at,released_at,timeout_s,"
                " queue_size,holder_pid,holder_boot,holder_host) "
                "VALUES (?,'LOCKED',?,?,?,NULL,?,?,?,?,?)",
                (key, agent, token, time.time(), timeout_s,
                 self._queue_size.get(key, 0), os.getpid(), _mon_boot(), socket.gethostname()),
            )
            conn.execute("COMMIT")
            self._tokens[token] = (key, agent, time.time())
            return token, "acquis"
        except sqlite3.OperationalError as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            return None, f"registre occupe ({e})"
        finally:
            conn.close()

    def acquerir(self, resource: str | Tuple[str, str], agent: str,
                 timeout: Optional[float] = None) -> Optional[str]:
        """Acquisition SYNCHRONE et CROSS-PROCESS. Token si OK, None si refus.

        ⚠️ CE QUI A CHANGE, et pourquoi. L'ancienne version s'appuyait sur un
        `asyncio.Lock` par ressource : in-process, donc ZERO exclusion entre le
        hub (qui porte `forge_agent_proxy.GeminiCLI`) et le service separe qui
        porte `_delegate_to_agy`. L'exclusion tient desormais a la ligne
        `locks_state`, prise en `BEGIN IMMEDIATE`, avec l'identite du holder.
        Contrepartie assumee : l'ordre FIFO promis par la docstring d'origine ne
        valait qu'in-process ; entre process c'est « le premier qui trouve
        libre ». Le recul est jitte, sinon N attendants repartent a la meme
        milliseconde et se rebloquent.
        """
        key = _resource_key(resource)
        timeout_s = timeout if timeout is not None else self.default_timeout
        limite = time.time() + timeout_s
        self._queue_size[key] = self._queue_size.get(key, 0) + 1
        attente = 0.05
        try:
            while True:
                token, motif = self._tenter(key, agent, timeout_s)
                if token:
                    self.dernier_refus = ""
                    return token
                if time.time() >= limite:
                    self.dernier_refus = motif
                    return None
                time.sleep(min(attente, 0.5) * (0.5 + random.random()))
                attente = min(attente * 1.7, 0.5)
        finally:
            self._queue_size[key] = max(0, self._queue_size.get(key, 1) - 1)

    def liberer(self, token: str) -> bool:
        """Libere un verrou par son token. True si ce token tenait bien la ligne."""
        if token not in self._tokens:
            return False
        key, _agent, _ = self._tokens.pop(token)
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE locks_state SET state='RELEASED',released_at=?,owner_agent=NULL,"
                "owner_token=NULL,holder_pid=NULL,holder_boot=NULL WHERE resource=? AND owner_token=?",
                (time.time(), key, token),
            )
        finally:
            conn.close()
        lk = self._locks.get(key)
        if lk is not None and lk.locked():
            try:
                lk.release()
            except RuntimeError:
                pass
        return True

    def _forcer_holder(self, resource: str | Tuple[str, str], pid, boot) -> None:
        """Reecrit l'identite du holder d'une ligne.

        Sert (a) aux NR, (b) a reconcilier le registre avec le reel quand un
        holder a ete tue de l'exterieur — meme geste que `forge_port_reconcile`
        pour un listener fantome. Ne libere rien par lui-meme : c'est
        `recover_from_db` qui tranche, et seulement sur un MORT prouve.
        """
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE locks_state SET holder_pid=?,holder_boot=? WHERE resource=?",
                (pid, boot, _resource_key(resource)),
            )
        finally:
            conn.close()

    async def lock(self, resource: str | Tuple[str, str], agent: str, timeout: Optional[float] = None) -> Optional[str]:
        """Enveloppe async de `acquerir` — meme noyau, donc meme exclusion."""
        return await asyncio.to_thread(self.acquerir, resource, agent, timeout)

    async def release(self, token: str) -> bool:
        """Enveloppe async de `liberer`."""
        return await asyncio.to_thread(self.liberer, token)

    def _lire(self, key: str) -> Optional[tuple]:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT state,owner_agent,owner_token,locked_at,queue_size,holder_pid,holder_boot "
                "FROM locks_state WHERE resource=?",
                (key,),
            ).fetchone()
        except Exception:  # noqa: BLE001
            return None
        finally:
            conn.close()

    def get_state(self, resource: str | Tuple[str, str]) -> LockState:
        """État courant d'une ressource, LU DANS LE REGISTRE PARTAGE.

        ⚠️ L'ancienne version repondait d'abord depuis `self._tokens`, c'est-a-dire
        depuis la memoire de CE process : elle ne pouvait donc pas voir un verrou
        tenu par un voisin, et un token local perime la faisait mentir dans
        l'autre sens. Le registre fait foi ; l'etat du holder est mesure, pas
        deduit.
        """
        key = _resource_key(resource)
        row = self._lire(key)
        if not row:
            return LockState(resource=key, state="FREE", owner_agent=None, owner_token=None,
                             locked_at=None, queue_size=0, holder_etat=ETAT_MORT,
                             motif="aucune ligne au registre")
        etat, motif = (etat_holder(row[5], row[6]) if row[0] == "LOCKED"
                       else (ETAT_MORT, "ligne non LOCKED"))
        return LockState(
            resource=key, state=row[0], owner_agent=row[1], owner_token=row[2],
            locked_at=row[3], queue_size=self._queue_size.get(key, row[4] or 0),
            holder_pid=row[5], holder_etat=etat, motif=motif,
        )

    def list_locked(self) -> List[LockState]:
        """Tous les verrous tenus AU REGISTRE — pas seulement ceux de ce process."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT resource,owner_agent,owner_token,locked_at,queue_size,holder_pid,holder_boot "
                "FROM locks_state WHERE state='LOCKED'"
            ).fetchall()
        except Exception:  # noqa: BLE001
            rows = []
        finally:
            conn.close()
        out = []
        for r in rows:
            etat, motif = etat_holder(r[5], r[6])
            out.append(LockState(resource=r[0], state="LOCKED", owner_agent=r[1], owner_token=r[2],
                                 locked_at=r[3], queue_size=r[4] or 0, holder_pid=r[5],
                                 holder_etat=etat, motif=motif))
        return out

    def recover_from_db(self) -> dict:
        """Reconcilie le registre avec le REEL. Ne libere QUE des morts prouves.

        ⚠️ CE QUE FAISAIT L'ANCIENNE VERSION : elle passait tout `LOCKED` a
        `RELEASED` des qu'aucun token ne figurait dans la memoire de CE process.
        Comme un verrou pris par un voisin n'y figure jamais, elle depossedait
        systematiquement les holders vivants des autres process — `UNKNOWN` lu
        `NO`, exactement la confusion que la constitution semantique interdit.

        Rend un BILAN, pas un compteur : `reclames` / `vivants` / `inconnus`,
        plus les motifs. Un INCONNU garde son verrou et se lit dans `motifs` — il
        est a instruire, pas a balayer. Seul un TTL explicite (a la charge de
        l'appelant) peut trancher un INCONNU, et il devra le DIRE.
        """
        bilan = {"reclames": 0, "vivants": 0, "inconnus": 0, "motifs": []}
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT resource,owner_agent,holder_pid,holder_boot FROM locks_state WHERE state='LOCKED'"
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            conn.close()
            bilan["motifs"].append(f"registre illisible ({type(e).__name__}: {e}) — aucun verdict rendu")
            return bilan
        try:
            for resource, agent, pid, boot in rows:
                etat, motif = etat_holder(pid, boot)
                if etat == ETAT_MORT:
                    conn.execute(
                        "UPDATE locks_state SET state='RELEASED',released_at=?,"
                        "owner_agent=NULL,owner_token=NULL WHERE resource=?",
                        (time.time(), resource),
                    )
                    bilan["reclames"] += 1
                elif etat == ETAT_VIVANT:
                    bilan["vivants"] += 1
                else:
                    bilan["inconnus"] += 1
                bilan["motifs"].append(f"{resource} [{agent}] {etat}: {motif}")
        finally:
            conn.close()
        return bilan


# Singleton process-life
_singleton: Optional[LockManager] = None


def get_lock_manager() -> LockManager:
    global _singleton
    if _singleton is None:
        _singleton = LockManager()
        _singleton.recover_from_db()
    return _singleton
