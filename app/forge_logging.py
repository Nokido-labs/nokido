"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_logging
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_logging.py — extrait automatiquement depuis Nokido.py
Généré par shredder.py
"""

from contextlib import AbstractContextManager
from typing import Any
from typing import Dict
from typing import Optional
import json
import logging
import logging.handlers
import queue as _queue
import sys as _sys
import time
import uuid
import warnings as _warnings
from datetime import datetime
from pathlib import Path

# Module-level paths for debug log files
_ROOT_LOGGING = Path(__file__).resolve().parent.parent
DEBUG_LOG_PATH = _ROOT_LOGGING / "logs" / "debug_main.log"
DEBUG_ROUTE_PATH = _ROOT_LOGGING / "logs" / "debug_route.log"
DEBUG_LOG_PATH.parent.mkdir(exist_ok=True)

_debug_main_handle = None
_debug_route_handle = None


class _silent(AbstractContextManager):
    """
    Context manager qui supprime temporairement toute sortie sur ``stdout``,
    ``stderr`` ainsi que les warnings.  Il est compatible Windows/Linux/macOS
    et restaure correctement les flux même en cas d’exception.
    """

    def __enter__(self) -> "_silent":
        """Enter."""
        import sys
        import io

        self._old_out: Any = sys.stdout
        self._old_err: Any = sys.stderr
        self._buffer = io.StringIO()
        sys.stdout = self._buffer
        sys.stderr = self._buffer

        self._warnings_ctx = _warnings.catch_warnings()
        self._warnings_ctx.__enter__()
        _warnings.simplefilter("ignore")
        return self

    def __exit__(
        self, exc_type: Optional[type] = None, exc: Optional[BaseException] = None, tb: Optional[Any] = None
    ) -> Optional[bool]:
        """Exit.

        Args:
            exc_type: Description.
            exc: Description.
            tb: Description.
        """
        import sys

        # Restauration des flux – on ignore les erreurs potentielles pour ne
        # jamais laisser le processus sans ``stdout``/``stderr``.
        try:
            sys.stdout = self._old_out
        finally:
            try:
                sys.stderr = self._old_err
            finally:
                # Toujours quitter le contexte warnings, même si une exception
                # s’est produite dans le bloc ``with``.
                self._warnings_ctx.__exit__(exc_type, exc, tb)

        # Ne pas supprimer l’exception – on la laisse se propager.
        return None


class _JSONLHandler(logging.Handler):
    """Handler qui écrit chaque message en JSONL (une ligne JSON par entrée)."""

    def __init__(self, path) -> None:
        """Init.

        Args:
            path: Description.
        """
        super().__init__()
        self._fh = open(path, "w", encoding="utf-8", buffering=4096)

    def emit(self, record) -> None:
        """Emit.

        Args:
            record: Description.
        """
        try:
            entry = {
                "ts": record.created,
                "time": self.format(record).split(" [")[0] if hasattr(record, "created") else "",
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                entry["exc"] = logging.Formatter().formatException(record.exc_info)
            self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            # `handleError` est le mecanisme PREVU par la stdlib pour un handler qui
            # echoue : il ecrit sur stderr et respecte `logging.raiseExceptions`, sans
            # re-entrer dans le logging (ce qu'un `logger.warning` ferait ici, avec
            # recursion infinie a la clef). Un `pass` faisait disparaitre la ligne ET
            # la panne : un journal muet est pire qu'un journal absent, parce qu'on
            # continue de lui faire confiance.
            self.handleError(record)

    def close(self) -> None:
        """Close."""
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:  # muet-ok : fermeture a l'arret de l'interpreteur, ou le
            # logging est deja demonte et stderr souvent ferme. Signaler ici
            # n'atteindrait personne et masquerait l'arret propre. Le silence est
            # DECLARE, pas subi — c'est la difference avec les 2 349 autres.
            pass
        super().close()


# Compteur de pertes par (canal, type d'erreur). Une panne INSTALLEE se signale une
# fois puis se compte : sans cette deduplication, le remede deviendrait le bruit et
# on finirait par filtrer le message — exactement le sort d'un garde qui crie trop.
_PERTES: dict = {}


def _signaler_perte(quoi: str, exc: BaseException) -> None:
    """Dit une ecriture de journal PERDUE. Sur stderr, jamais via `logging` : appeler
    le logging depuis le module de logging est une recursion. Le message porte la
    CONSEQUENCE, pas seulement la cause — un journal incomplet lu comme exhaustif
    fait conclure a une absence d'evenement."""
    import sys

    cle = "%s|%s" % (quoi, type(exc).__name__)
    n = _PERTES.get(cle, 0) + 1
    _PERTES[cle] = n
    if n == 1 or n % 100 == 0:
        try:
            sys.stderr.write(
                "[forge_logging] PERTE %s (%s: %s) — %d ligne(s) perdue(s) depuis le "
                "debut ; consequence: ce journal est INCOMPLET, ne pas le lire comme "
                "une trace exhaustive\n" % (quoi, type(exc).__name__, str(exc)[:80], n))
        except Exception:  # noqa: BLE001 — muet-ok : stderr ferme, plus aucun canal
            pass


# ── ECRIRE SUR stdout SANS BLOQUER L'APPELANT (mesure 2026-09-18) ────────────
#
# Le hub `:8766` est mort a 18:25:17, tue par son propre garde
# (`WEDGE KILL : event-loop gele 60s`). Le dump `faulthandler` designe, dans le
# thread qui porte `run_forever` :
#
#     app/forge_byte_router.py:133 in process    <- la frame la plus recente
#     tools/nokido_hub.py:1199 in _tool_call
#     tools/nokido_hub.py:2961 in mcp_post
#
# La ligne 133 etait `print(..., flush=True)` : une DECORATION de TUI, ecrite
# synchronement dans la boucle d'evenements, a CHAQUE appel d'outil MCP.
#
# Or le stdout du hub est un tuyau draine par `pipeToLog` du superviseur, et ce
# drain a ete mesure le MEME JOUR avec **7 minutes de retard**. Tuyau plein ⇒
# `flush()` attend ⇒ la boucle gele ⇒ le garde tue a 60 s. C'est exactement le
# gel du webhub du 2026-09-18 (`logging:1144 self.stream.flush()`), sur un autre
# service et par un autre chemin : `print` au lieu de `logging`.
#
# `installer_logging_non_bloquant` ne protegeait que `logging`. Un `print` nu
# passe a cote — d'ou cette fonction, pour le meme contrat : l'APPELANT ne bloque
# jamais, un fil separe paie l'attente, et ce qui est perdu est COMPTE.
#
# Une decoration ne vaut pas un gel de service. En cas de saturation on JETTE, et
# on le dit : un affichage muet se corrige, un hub mort se reveille a la main.
# `queue` est importe sous le nom `_queue` (L26) : annoter `queue.Queue` nomme un
# module qui n'existe PAS dans cet espace. L'annotation etant une CHAINE, rien ne
# leve a l'execution -- mais `typing.get_type_hints` echouerait, et l'outillage le
# lit comme un nom indefini. Meme famille que le piege `os`/`_os` du 18/09 : ce
# n'est pas le module qui manque, c'est le NOM sous lequel on le designe.
_FILE_SORTIE: "_queue.Queue | None" = None
_FIL_SORTIE = None


def _demarrer_le_drain() -> None:
    """Cree la file bornee et le fil qui la vide. Idempotent.

    Le flux de DESTINATION voyage dans la file, jamais dans la closure du fil.
    Defaut trouve par le NR, pas par relecture : une premiere version capturait
    le flux du PREMIER appelant, si bien qu'un second appelant nommant un autre
    flux voyait son texte partir dans le premier — mal route, en silence. Un
    canal d'affichage qui ecrit ailleurs qu'ou on le lui demande est pire qu'un
    canal muet : on croit lire la sortie du bon organe.
    """
    global _FILE_SORTIE, _FIL_SORTIE
    if _FIL_SORTIE is not None and _FIL_SORTIE.is_alive():
        return
    import queue as _q
    import threading

    _FILE_SORTIE = _q.Queue(maxsize=2048)

    def _vider() -> None:
        while True:
            item = _FILE_SORTIE.get()
            if item is None:
                return
            flux, texte = item
            try:
                flux.write(texte)
                flux.flush()
            except Exception as e:  # noqa: BLE001
                # Ce fil-ci a le DROIT d'attendre : il n'est pas la boucle.
                # S'il echoue vraiment, on compte et on continue.
                _signaler_perte("sortie console non bloquante", e)

    _FIL_SORTIE = threading.Thread(target=_vider, name="forge-sortie-console", daemon=True)
    _FIL_SORTIE.start()


def ecrire_sans_bloquer(texte: str, flux=None) -> bool:
    """Ecrit sur `flux` (stdout par defaut) SANS jamais bloquer l'appelant.

    Rend True si le texte est entre dans la file, False s'il a ete JETE. Ne leve
    jamais : un canal d'affichage qui casse ne doit pas casser son appelant.
    """
    import queue as _q
    import sys

    flux = flux if flux is not None else sys.stdout
    try:
        _demarrer_le_drain()
        _FILE_SORTIE.put_nowait((flux, texte))
        return True
    except _q.Full:
        # Saturation : on prefere perdre une decoration qu'un service.
        _signaler_perte("sortie console saturee (file de 2048)", _q.Full())
        return False
    except Exception as e:  # noqa: BLE001
        _signaler_perte("sortie console indisponible", e)
        return False


def debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    run_id: str = "post-fix-v2",
) -> None:
    """
    Log structuré NDJSON — fichiers ouverts une seule fois (rapide).
    - Les logs ROUTE vont dans debug-routing.log
    - Tous les logs vont aussi dans debug-93c5ee.log
    """
    entry = {
        "sessionId": "93c5ee",
        "id": f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data or {},
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    try:
        _debug_main_fh().write(line)
    except Exception as e:  # noqa: BLE001
        _signaler_perte("journal de debug principal", e)
    if hypothesis_id == "ROUTE":
        try:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            d = data or {}
            _debug_route_fh().write(f"[{ts}] {location.split('.')[-1]} | {message} | {d}\n")
        except Exception as e:  # noqa: BLE001
            _signaler_perte("journal de routage", e)


def _debug_main_fh() -> object:
    """Debug main fh."""
    global _debug_main_handle
    if _debug_main_handle is None or _debug_main_handle.closed:
        _debug_main_handle = open(DEBUG_LOG_PATH, "a", encoding="utf-8", buffering=4096)
    return _debug_main_handle


def _debug_route_fh() -> object:
    """Debug route fh."""
    global _debug_route_handle
    if _debug_route_handle is None or _debug_route_handle.closed:
        _debug_route_handle = open(DEBUG_ROUTE_PATH, "a", encoding="utf-8", buffering=4096)
    return _debug_route_handle


# ---------------------------------------------------------------------------
# JOURNALISER SANS RETENIR L'APPELANT (2026-09-18)
#
# Ecrit apres la photographie du gel de :7400 du 2026-09-17 a 22:47:31 : le fil
# principal du webhub etait arrete dans `logging/__init__.py:1144`, c'est-a-dire
# `self.stream.flush()` -- l'ecriture du log d'ACCES d'uvicorn, faite DEPUIS la
# boucle d'evenements. Le flux de sortie est un pipe draine par le superviseur ;
# quand le drain prend du retard, le pipe se remplit et l'ecriture ne rend plus
# la main. `/health` se tait alors sans que rien ne soit casse : un transport
# vivant passe pour une application morte.
#
# La propriete visee n'est PAS << le drain doit etre rapide >> -- on ne controle
# pas la latence d'en face. C'est : journaliser ne bloque jamais l'appelant,
# quelle que soit la lenteur du flux. Le report est porte par un fil separe.
#
# Deux facons de se tromper en corrigeant, evitees ici par construction :
#   * une file NON bornee echange un gel contre une fuite memoire ;
#   * une perte MUETTE echange un gel contre une cecite -- exactement le defaut
#     du 2026-07-27, ou 5 h de journaux ont disparu sans un mot nulle part.
# D'ou une file bornee ET un compteur de pertes lisible.
# ---------------------------------------------------------------------------

_FORMAT_JOURNAL = "%(asctime)s %(levelname)s: %(message)s"


class _PoigneeNonBloquante(logging.handlers.QueueHandler):
    """File d'attente qui COMPTE ce qu'elle perd, au lieu d'attendre ou de crier.

    `QueueHandler.enqueue` fait un `put_nowait` dont la `queue.Full` remonterait
    en `handleError` -- du bruit sur stderr, c'est-a-dire une ecriture de plus au
    moment precis ou la sortie est engorgee. On l'intercepte et on tient le
    compte : une perte comptee est un fait, une perte muette est un capteur qui
    ment.
    """

    def __init__(self, file_attente) -> None:
        super().__init__(file_attente)
        self.perdus = 0

    def enqueue(self, record) -> None:
        try:
            self.queue.put_nowait(record)
        except _queue.Full:
            self.perdus += 1


class PoseNonBloquante:
    """Ce qui a ete installe, de quoi le defaire, et le compte des pertes."""

    def __init__(self, ecouteur, poignee, restaurations) -> None:
        self._ecouteur = ecouteur
        self._poignee = poignee
        self._restaurations = restaurations
        self._arretee = False

    @property
    def perdus(self) -> int:
        """Nombre d'entrees tombees parce que la file etait pleine."""
        return self._poignee.perdus

    def _arreter_l_ecouteur(self, attente_max_s: float) -> None:
        """Arrete le fil MEME quand la file est pleine.

        DEFAUT TROUVE PAR LE NR, et il est reel : `QueueListener.stop()` pose son
        sentinel par `put_nowait` (`logging/handlers.py`), donc sur une file
        SATUREE il leve `queue.Full` et le fil n'est jamais arrete. L'arret
        echouerait exactement quand la sortie est engorgee -- le seul moment ou
        il compte. On fait donc de la place, et ce qu'on retire est COMPTE comme
        perdu plutot que tu.

        `stop()` est reappelable : il a deja pose son drapeau d'arret, le fil
        sortira des qu'il aura depile, et la reprise rejoint le fil normalement.
        """
        limite = time.monotonic() + max(0.0, attente_max_s)
        while True:
            try:
                self._ecouteur.stop()
                return
            except _queue.Full:
                if time.monotonic() > limite:
                    raise
                try:
                    self._poignee.queue.get_nowait()
                    self._poignee.perdus += 1
                except _queue.Empty:  # muet-ok : file vidée entre-temps par le fil
                    # Rien a journaliser ici, et surtout pas depuis le chemin
                    # d'ARRET de la journalisation : la file s'est videe toute
                    # seule, ce qui est precisement le resultat cherche. On
                    # repasse par la boucle, `stop()` reussira au tour suivant.
                    pass

    def arreter(self, attente_max_s: float = 5.0) -> None:
        """Vide la file, arrete le fil, rend aux journaux leurs handlers.

        `QueueListener.stop()` traite ce qui reste AVANT de rendre la main : le
        report n'est donc pas une perte. Idempotent -- un arret deja fait ne doit
        pas lever, sinon on le contourne par un `try` et on ne sait plus qui
        arrete quoi.
        """
        if self._arretee:
            return
        self._arretee = True
        try:
            self._arreter_l_ecouteur(attente_max_s)
        finally:
            for journal, anciens, niveau, propage in self._restaurations:
                journal.removeHandler(self._poignee)
                for ancien in anciens:
                    journal.addHandler(ancien)
                journal.setLevel(niveau)
                journal.propagate = propage


def installer_logging_non_bloquant(
    noms,
    flux=None,
    niveau="INFO",
    taille_file: int = 10000,
    format_: Optional[str] = None,
) -> PoseNonBloquante:
    """Detache l'ecriture des journaux nommes vers un fil separe.

    `noms` -- les journaux a detacher (pour le webhub : uvicorn, uvicorn.error,
    uvicorn.access). Leurs handlers existants sont RETIRES puis rendus par
    `arreter()` : laisser l'ancien handler en place le laisserait bloquer, et
    c'est lui qu'on est venu desarmer.

    Rend la pose, qui porte `perdus` et `arreter()`.
    """
    if isinstance(niveau, str):
        resolu = logging.getLevelName(niveau.upper())
        niveau_num = resolu if isinstance(resolu, int) else logging.INFO
    else:
        niveau_num = int(niveau)

    file_attente = _queue.Queue(maxsize=max(1, int(taille_file)))
    sortie = logging.StreamHandler(_sys.stdout if flux is None else flux)
    sortie.setFormatter(logging.Formatter(format_ or _FORMAT_JOURNAL))
    sortie.setLevel(niveau_num)

    poignee = _PoigneeNonBloquante(file_attente)
    poignee.setLevel(niveau_num)

    ecouteur = logging.handlers.QueueListener(
        file_attente, sortie, respect_handler_level=True)
    ecouteur.start()

    restaurations = []
    for nom in noms:
        journal = logging.getLogger(nom)
        restaurations.append(
            (journal, list(journal.handlers), journal.level, journal.propagate))
        for ancien in list(journal.handlers):
            journal.removeHandler(ancien)
        journal.addHandler(poignee)
        journal.setLevel(niveau_num)
        journal.propagate = False

    return PoseNonBloquante(ecouteur, poignee, restaurations)
