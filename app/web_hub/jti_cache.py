"""
app/web_hub/jti_cache.py - Cache de revocation JWT (jti + exp).

Resout le trou Gemini #2 : un token vole ou issu avant logout reste valide
jusqu'a son expiration (TTL par defaut = 3600s). Avec ce module :

  - /auth/logout ajoute le jti du token courant au cache.
  - verify_token consulte ce cache et refuse si le jti est revoque.
  - Les entrees expirees sont purgees a la volee (lazy sweep).
  - PERSISTENCE optionnelle (SqlitePersister) : survit aux restarts hub.
    Preload au boot + write-through async a chaque revoke.

THREAD-SAFETY : verrou reentrant (threading.RLock). FastAPI/Starlette
servent souvent sur un single event loop mais uvicorn workers multiples
existent ; le verrou protege aussi les tests unitaires concurrents.

MEMOIRE : plafond souple via MAX_ENTRIES. Au-dela, purge agressive des
jti expires puis, si toujours plein, on refuse l'ajout (fail-closed ->
mieux vaut un logout non-enregistre qu'un OOM).

PERSISTENCE : write-through fire-and-forget via queue + worker daemon.
Une panne SQLite ne bloque JAMAIS le logout (le cache in-mem reste
autoritaire pour la session courante). Le pire cas = restart avant que
le worker ait flush -> quelques revoke perdus (same-as-avant-persistence).

JAMAIS LOG :
  - le contenu d'un jti (opaque mais potentiellement correlable)
  - la taille exacte du cache (fingerprinting)
  - le chemin DB (fingerprinting systeme de fichiers)
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, Protocol

log = logging.getLogger("nokido.hub.jti")

# Plafond souple. 10k jti = ~1 MB (jti = 16 chars url-safe + exp float).
MAX_ENTRIES = 10_000

# Balayage lazy : on purge si taille depasse ce seuil avant un add.
_SWEEP_THRESHOLD = 1024


class JtiRevocationCache:
    """In-memory TTL store. Thread-safe."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._revoked: dict[str, float] = {}  # jti -> exp_unix_ts
        self._lock = threading.RLock()
        self._max = max_entries
        self._persister: Optional["Persister"] = None

    def attach_persister(self, persister: Optional["Persister"]) -> None:
        """Branche ou detache un backend persistance.

        `None` detache (utile en test pour remettre le cache en mode pur).
        Apres attach : les futurs revoke() sont write-through. Les entrees
        deja en cache ne sont PAS repoussees (faire un preload explicite
        si besoin).
        """
        with self._lock:
            self._persister = persister

    def revoke(self, jti: str, exp: float) -> bool:
        """Marque un jti comme revoque jusqu'a son exp.

        Return True si enregistre, False si refus (cache plein apres purge).
        Un exp deja passe = no-op (inutile de stocker).

        Write-through : si un persister est attache, on enqueue un save
        fire-and-forget. Une panne persister ne fait JAMAIS echouer revoke().
        """
        if not jti or not isinstance(jti, str):
            return False
        now = time.time()
        if exp <= now:
            return True  # deja expire, considere revoque de facto
        with self._lock:
            if len(self._revoked) >= _SWEEP_THRESHOLD:
                self._sweep_locked(now)
            if len(self._revoked) >= self._max:
                log.warning("jti cache full (%d), revoke refused", self._max)
                return False
            self._revoked[jti] = exp
            persister = self._persister
        # Hors-lock pour ne pas bloquer d autres threads
        if persister is not None:
            try:
                persister.save(jti, exp)
            except Exception:  # noqa: BLE001
                # Jamais loggue le jti ; on note juste que ca a foire
                log.warning("jti persister save failed", exc_info=False)
        return True

    def load_many(self, pairs: Iterable[tuple[str, float]]) -> int:
        """Hydrate le cache depuis une source externe (preload boot).

        Identique a revoke_many mais SANS write-through (les pairs
        viennent deja du persister, inutile de les renvoyer).
        """
        count = 0
        now = time.time()
        with self._lock:
            for jti, exp in pairs:
                if not jti or not isinstance(jti, str):
                    continue
                if exp <= now:
                    continue
                if len(self._revoked) >= self._max:
                    break
                self._revoked[jti] = exp
                count += 1
        return count

    def is_revoked(self, jti: str) -> bool:
        """Check revocation. Purge lazy de l'entree si expiree."""
        if not jti or not isinstance(jti, str):
            return False
        with self._lock:
            exp = self._revoked.get(jti)
            if exp is None:
                return False
            if exp <= time.time():
                # Expire naturellement : plus besoin de la retenir
                self._revoked.pop(jti, None)
                return False
            return True

    def _sweep_locked(self, now: float) -> int:
        """Purge in-place des entrees expirees. Retourne nombre purge.

        DOIT etre appele sous lock.
        """
        expired = [j for j, e in self._revoked.items() if e <= now]
        for j in expired:
            self._revoked.pop(j, None)
        return len(expired)

    def sweep(self) -> int:
        """Purge publique (pour tests ou hook periodique)."""
        with self._lock:
            return self._sweep_locked(time.time())

    def clear(self) -> None:
        """Vide tout. Utilise uniquement par les tests."""
        with self._lock:
            self._revoked.clear()

    def size(self) -> int:
        """Taille actuelle (apres balayage). Utilise par tests."""
        with self._lock:
            self._sweep_locked(time.time())
            return len(self._revoked)


# Instance module-level partagee
revocation_cache = JtiRevocationCache()


def revoke_jti(jti: str, exp: float) -> bool:
    """Helper : revoque un jti jusqu'a son exp."""
    return revocation_cache.revoke(jti, exp)


def is_jti_revoked(jti: str) -> bool:
    """Helper : check revocation."""
    return revocation_cache.is_revoked(jti)


def revoke_many(pairs: Iterable[tuple[str, float]]) -> int:
    """Helper bulk : utile pour restaurer un snapshot. Retourne nb ajoutes."""
    count = 0
    for jti, exp in pairs:
        if revocation_cache.revoke(jti, exp):
            count += 1
    return count


# ====================================================================
# Persistence layer
# ====================================================================
class Persister(Protocol):
    """Contrat minimal : save(jti, exp), load_all() -> iter[(jti, exp)]."""

    def save(self, jti: str, exp: float) -> None: ...
    def load_all(self) -> Iterable[tuple[str, float]]: ...


class SqlitePersister:
    """Backend SQLite avec WAL + worker daemon fire-and-forget.

    Schema : jwt_revocations(jti TEXT PRIMARY KEY, exp REAL NOT NULL).

    La methode `save` pousse dans une queue en <1ms ; un worker daemon
    draine la queue en INSERT OR IGNORE. Si le worker est planifie mais
    pas encore execute au moment d'un restart hub, le jti est perdu
    (meme comportement qu'avant la persistence pour ce cas-limite).

    Un `close()` est fourni pour les tests / shutdown propre : flush la
    queue puis close la connexion. NE PAS appeler pendant un requete
    live (bloque le worker jusqu'au drain).
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS jwt_revocations (
        jti TEXT PRIMARY KEY,
        exp REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_jwt_revocations_exp
        ON jwt_revocations(exp);
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False : on serialise via un lock dedie
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            timeout=5.0,
        )
        # WAL : cohabite avec les autres DBs hub (events, recon)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

        self._write_lock = threading.Lock()
        self._queue: "queue.Queue[Optional[tuple[str, float]]]" = queue.Queue()
        self._stopped = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="jti-persister",
            daemon=True,
        )
        self._worker.start()

    def save(self, jti: str, exp: float) -> None:
        """Non-bloquant : enqueue et retourne."""
        if self._stopped.is_set():
            return
        self._queue.put((jti, exp))

    def load_all(self) -> Iterable[tuple[str, float]]:
        """Charge toutes les revocations NON expirees. Purge au passage.

        Applique la purge directement en DB pour que le fichier ne
        grossisse pas indefiniment.
        """
        now = time.time()
        with self._write_lock:
            self._conn.execute("DELETE FROM jwt_revocations WHERE exp <= ?", (now,))
            self._conn.commit()
            rows = self._conn.execute(
                "SELECT jti, exp FROM jwt_revocations WHERE exp > ?",
                (now,),
            ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def _worker_loop(self) -> None:
        """Drain la queue et batch-insert. Sentinel = None -> stop."""
        pending: list[tuple[str, float]] = []
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                if pending:
                    self._flush(pending)
                    pending = []
                if self._stopped.is_set():
                    return
                continue
            if item is None:  # sentinel close
                if pending:
                    self._flush(pending)
                return
            pending.append(item)
            # Flush par batch pour amortir le cout I/O
            if len(pending) >= 32:
                self._flush(pending)
                pending = []

    def _flush(self, pending: list[tuple[str, float]]) -> None:
        try:
            with self._write_lock:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO jwt_revocations (jti, exp) VALUES (?, ?)",
                    pending,
                )
                self._conn.commit()
        except sqlite3.Error:
            log.warning("jti persister flush failed (batch=%d)", len(pending))

    def close(self, flush_timeout: float = 2.0) -> None:
        """Arrete le worker et ferme la connexion.

        Bloque jusqu'a `flush_timeout` pour drain la queue pending.
        """
        self._stopped.set()
        self._queue.put(None)  # sentinel
        self._worker.join(timeout=flush_timeout)
        with self._write_lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


# --------------------------------------------------------------------
# Bootstrap helpers : attach + preload
# --------------------------------------------------------------------
def attach_and_preload(
    persister: Persister,
    cache: JtiRevocationCache = None,  # type: ignore[assignment]
) -> int:
    """Branche le persister sur le cache et preload depuis la DB.

    Retourne le nombre d entrees preloadees. Utilise par app.py au
    startup event FastAPI. Idempotent : si deja attache sur le meme
    persister, re-preload (purge DB + hydrate).
    """
    if cache is None:
        cache = revocation_cache
    cache.attach_persister(persister)
    try:
        pairs = list(persister.load_all())
    except Exception:  # noqa: BLE001
        log.warning("jti persister load_all failed, cold start")
        return 0
    return cache.load_many(pairs)


__all__ = [
    "JtiRevocationCache",
    "revocation_cache",
    "revoke_jti",
    "is_jti_revoked",
    "revoke_many",
    "MAX_ENTRIES",
    "Persister",
    "SqlitePersister",
    "attach_and_preload",
]
