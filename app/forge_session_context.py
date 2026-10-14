"""
forge_session_context.py - SessionContext unifié Nokido avec osmorégulation
=============================================================================

Successeur et unification canonique des SessionContext de Nokido :
- Fusionne forge_core_models.SessionContext et forge_session_context.SessionContext.
- Osmorégulation : digestion avant éviction pour éliminer l'amnésie.
- Élimination des 4 défauts du brief (§ 3 de docs/CHANTIER_VIABILITE_CELLULE.md) :
  1. Anti-double digestion : drapeau synchrone _is_digesting verrouillé dès l'admission.
  2. Anti-panne muette : try/finally garantissant la réinitialisation du drapeau, repli
     déterministe immédiat pour ne jamais perdre les messages évincés.
  3. Anti-trou de mémoire : compartiment _digesting_messages visible dans get_context()
     tant que le résumé n'est pas posé.
  4. Référence forte aux tâches : _running_tasks pour immuniser contre le garbage collector.
- Extraction déterministe d'abord (faits témoins, chemins, décisions, erreurs) + résumeur
  pluggable.
- Compatibilité ascendante complète (add, unregister, get_context, messages, meta).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"

_EVENT_BUS = None


def _emit(topic: str, kind: str, data: dict, agent: str = "SESSION") -> None:
    global _EVENT_BUS
    try:
        if _EVENT_BUS is None:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_state_manager import EventBus, get_state_manager

            _EVENT_BUS = EventBus(get_state_manager())
        _EVENT_BUS.publish(topic=topic, kind=kind, data=data, agent=agent, trusted=True)
    except Exception as e:
        logger.debug(f"EventBus skipped: {e}")


_PAT_DECISION = re.compile(
    r"(?:DECISIONS?|DÉCISIONS?|CHOIX)(?:\s*\([^)]*\))?:\s*([^\n\r]+?)(?=\s+(?:ERREURS?|ERRORS?|Exceptions?|Chemins|Faits|Synthèse)|\n|$)",
    re.IGNORECASE,
)
_PAT_PATH = re.compile(
    r"(?:^|[\s\"'])((?:app|tools|tests|docs|config|migrations|logs|sandbox)/[a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)"
)
_PAT_ERROR = re.compile(
    r"(?:ERREURS?|ERRORS?|Exceptions?):\s*([^\n\r]+?)(?=\s+(?:DECISIONS?|DÉCISIONS?|CHOIX|Chemins|Faits|Synthèse)|\n|$)",
    re.IGNORECASE,
)
_PAT_FACT = re.compile(r"(?:\[FAIT:\s*([^\]]+)\]|FAIT:\s*([^\n]+)|WITNESS:\s*([^\n]+))")
_PAT_SYNOPSIS = re.compile(r"-\s*\[(?:user|assistant|system|tool)\]\s*([^\n]+)")


@dataclass
class SessionMessage:
    role: str  # user | assistant | system | tool
    text: str
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    @property
    def content(self) -> str:
        """Alias de compatibilité pour forge_core_models.SessionContext."""
        return self.text

    @property
    def tokens(self) -> int:
        """Estimation de tokens ou lecture depuis meta."""
        return self.meta.get("tokens", max(1, len(self.text) // 4))

    def __getitem__(self, item: str) -> Any:
        if item == "content":
            return self.text
        if item == "tokens":
            return self.tokens
        if hasattr(self, item):
            return getattr(self, item)
        if item in self.meta:
            return self.meta[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "content": self.text,
            "ts": self.ts,
            "meta": self.meta,
            "tokens": self.tokens,
        }


@dataclass
class SessionContext:
    """Historique conversationnel unifié + digestion avant éviction + ancrage RAG.

    Gère l'osmorégulation du contexte (mémoire de travail bornée sans amnésie) :
    - Éviction devancée par une digestion (synthèse déterministe + résumeur pluggable).
    - Compartiment 'en digestion' (_digesting_messages) visible dans get_context()
      jusqu'à validation du résumé (zéro trou de mémoire).
    - Drapeau _is_digesting synchrone (zéro double digestion).
    - Gestion robuste d'erreur du résumeur : repli déterministe, zéro perte de faits témoins,
      drapeau toujours réinitialisé dans finally.
    - Tâches asynchrones référencées (_running_tasks, résistant au GC Python).
    """

    name: str = "session"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    messages: list[SessionMessage] = field(default_factory=list)
    max_messages: int = 200
    max_tokens: int = 3000
    max_summary_tokens: Optional[int] = None
    digest_timeout: float = 5.0
    domain: str = "systeme"
    extra: dict = field(default_factory=dict)
    _anchored: bool = False
    session_name: Optional[str] = None
    summary: Optional[str] = None
    _digesting_messages: list[SessionMessage] = field(default_factory=list)
    _is_digesting: bool = False
    _digest_count: int = 0
    _sync_async_skipped_count: int = 0
    _last_error: Optional[str] = None
    archive_window_size: int = 8
    _rag_anchor_count: int = 0
    _last_archive_chunk_id: Optional[str] = None
    _anchored_fact_keys: set[str] = field(default_factory=set)
    _inflight_fact_keys: set[str] = field(default_factory=set)
    _summary_truncated_count: int = 0
    _summary_truncated_chars: int = 0
    _archive_failed_count: int = 0
    _clean_val_dropped_count: int = 0
    _accumulated_decisions: list[str] = field(default_factory=list)
    _accumulated_paths: list[str] = field(default_factory=list)
    _accumulated_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        if self.session_name and self.name == "session":
            self.name = self.session_name
        elif not self.session_name:
            self.session_name = self.name
        self._running_tasks: set[asyncio.Task] = set()
        self._summarizer: Optional[Callable[[list[SessionMessage]], Any]] = None
        _emit("session.start", "info", {"name": self.name, "session_id": self.session_id})
        self._register_rag()

    def _register_rag(self) -> None:
        try:
            import sys

            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_app_context import get_rag as _gr

            rag = _gr()
            if rag and hasattr(rag, "session_ctxs"):
                rag.session_ctxs[self.name] = self
        except Exception as e:
            logger.debug(f"register_rag skipped: {e}")

    # ── messages ─────────────────────────────────────────────────────────
    def add_message(self, role: str, text: str, meta: Optional[dict] = None) -> SessionMessage:
        msg = SessionMessage(role=role, text=text, meta=meta or {})
        self.messages.append(msg)

        # Osmorégulation : digestion avant éviction
        self._check_and_digest()

        _emit(
            "session.message",
            "info",
            {"session_id": self.session_id, "role": role, "len": len(text), "n_messages": len(self.messages)},
        )

        # Ingestion RAG asynchrone si moteur présent
        try:
            from nokido_agent.app.forge_app_context import get_rag as _gr

            rag = getattr(self, "rag_engine", None) or _gr()
            if rag and hasattr(rag, "add_session_message"):
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    rtask = loop.create_task(rag.add_session_message(self.name, role, text))
                    self._running_tasks.add(rtask)
                    rtask.add_done_callback(self._running_tasks.discard)
        except Exception as e:
            logger.debug(f"rag add_session_message skipped: {e}")

        return msg

    def add(self, role: str, content: str) -> SessionMessage:
        """Compatibilité directe pour forge_core_models.SessionContext.add()."""
        return self.add_message(role=role, text=content)

    def latest(self, n: int = 10) -> list[SessionMessage]:
        return self.messages[-n:]

    # ── osmorégulation & digestion ─────────────────────────────────────────
    def _check_and_digest(self) -> None:
        """Contrôle les seuils de mémoire et déclenche la digestion avant éviction."""
        if self._is_digesting:
            # 1. DOUBLE DIGESTION ÉVITÉE : drapeau synchrone vérifié avant tout dispatch.
            return

        to_evict: list[SessionMessage] = []
        if len(self.messages) > self.max_messages:
            evict_count = len(self.messages) - self.max_messages
            # Règle absolue : si max_messages > 2 ou rôle system, on conserve le 1er message (amorce/consigne) ET les derniers messages (dont le message courant).
            if len(self.messages) > 2 and (self.messages[0].role == "system" or self.max_messages > 2):
                available = len(self.messages) - 2
                count = min(evict_count, available)
                to_evict = self.messages[1 : 1 + count]
                self.messages = [self.messages[0]] + self.messages[1 + count :]
            elif len(self.messages) > 1:
                available = len(self.messages) - 1
                count = min(evict_count, available)
                to_evict = self.messages[:count]
                self.messages = self.messages[count:]
        elif self.max_tokens and self.current_tokens > self.max_tokens and len(self.messages) > 1:
            # Branche saturation max_tokens (constat 4) :
            # Règle absolue : ne JAMAIS évincer le dernier message (le message courant qui vient d'entrer).
            while self.current_tokens > self.max_tokens and len(self.messages) > 1:
                if len(self.messages) > 2 and self.messages[0].role == "system":
                    evicted = self.messages.pop(1)
                    to_evict.append(evicted)
                elif len(self.messages) > 2:
                    evicted = self.messages.pop(0)
                    to_evict.append(evicted)
                elif len(self.messages) == 2:
                    if self.messages[0].role != "system":
                        evicted = self.messages.pop(0)
                        to_evict.append(evicted)
                    else:
                        break

        if not to_evict:
            return

        # 1. Verrouillage synchrone IMMÉDIAT (anti-double digestion)
        self._is_digesting = True

        # 3. TROU DE MÉMOIRE ÉVITÉ : Les messages évincés sont immédiatement
        # versés dans le compartiment visible _digesting_messages avant tout calcul
        self._digesting_messages.extend(to_evict)

        # 4. TÂCHE RÉFÉRENCÉE : Dispatch avec référence forte
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            task = loop.create_task(self._async_digest(to_evict))
            self._running_tasks.add(task)
            task.add_done_callback(self._running_tasks.discard)
        else:
            self._sync_digest(to_evict)

    async def _async_digest(self, to_evict: list[SessionMessage]) -> None:
        try:
            det = self._extract_deterministic(to_evict)
            custom_digest = None
            if self._summarizer is not None:
                if asyncio.iscoroutinefunction(self._summarizer):
                    # Constat 3 : délai borné via wait_for pour ne jamais bloquer indéfiniment
                    custom_digest = await asyncio.wait_for(
                        self._summarizer(to_evict),
                        timeout=self.digest_timeout,
                    )
                else:
                    custom_digest = self._summarizer(to_evict)

            final_digest = self._merge_digests(det, str(custom_digest) if custom_digest else None)
            self._commit_digest(to_evict, final_digest)
        except Exception as exc:
            # 2. PANNE MUETTE & TIMEOUT ÉVITÉS : le résumeur qui lève ou timeout applique le repli déterministe
            self._handle_digest_failure(to_evict, exc)
        finally:
            # 2. Le drapeau est TOUJOURS libéré
            self._is_digesting = False

    def _sync_digest(self, to_evict: list[SessionMessage]) -> None:
        try:
            det = self._extract_deterministic(to_evict)
            custom_digest = None
            if self._summarizer is not None:
                if asyncio.iscoroutinefunction(self._summarizer):
                    # Constat 5 : journal et compteur pour signaler le résumeur async ignoré hors boucle
                    self._sync_async_skipped_count += 1
                    logger.warning(
                        "Résumeur asynchrone ignoré dans _sync_digest (aucune boucle d'événements active, "
                        "count=%d) : repli déterministe appliqué",
                        self._sync_async_skipped_count,
                    )
                    _emit(
                        "session.digest",
                        "warning",
                        {
                            "session_id": self.session_id,
                            "warning": "async_summarizer_skipped_in_sync",
                            "skipped_count": self._sync_async_skipped_count,
                        },
                    )
                else:
                    custom_digest = self._summarizer(to_evict)
            final_digest = self._merge_digests(det, str(custom_digest) if custom_digest else None)
            self._commit_digest(to_evict, final_digest)
        except Exception as exc:
            self._handle_digest_failure(to_evict, exc)
        finally:
            self._is_digesting = False

    @property
    def summary_token_budget(self) -> int:
        """Budget de résumé en tokens (<= max_tokens // 4 ou paramétré) (constat 1)."""
        if self.max_summary_tokens is not None and self.max_summary_tokens > 0:
            return self.max_summary_tokens
        if self.max_tokens and self.max_tokens > 0:
            return max(50, self.max_tokens // 4)
        return 750

    @property
    def sync_async_skipped_count(self) -> int:
        return self._sync_async_skipped_count

    @property
    def rag_anchor_count(self) -> int:
        return self._rag_anchor_count

    @property
    def last_archive_chunk_id(self) -> Optional[str]:
        return self._last_archive_chunk_id

    @property
    def summary_truncated_count(self) -> int:
        return self._summary_truncated_count

    @property
    def summary_truncated_chars(self) -> int:
        return self._summary_truncated_chars

    @property
    def archive_failed_count(self) -> int:
        """Nombre d'échecs d'archivage RAG (constat 2 : non muet)."""
        return self._archive_failed_count

    @property
    def rag_archive_failed_count(self) -> int:
        """Alias pour archive_failed_count."""
        return self._archive_failed_count

    @property
    def clean_val_dropped_count(self) -> int:
        """Nombre de valeurs tronquées écartées par _clean_val (constat 4)."""
        return self._clean_val_dropped_count

    @property
    def inflight_fact_keys(self) -> set[str]:
        """Faits actuellement en cours d'archivage en tâche de fond (constat 2 : anti-course)."""
        with self._lock:
            return set(self._inflight_fact_keys)

    def _chunk_exists_in_rag(self, cid: str) -> bool:
        """Vérifie si un chunk existe déjà dans rag_chunks par son id (constat 1 : déduplication idempotente)."""
        try:
            import os
            import sqlite3
            from nokido_agent.app.forge_db_path import db_path

            target_path = db_path()
            if not os.path.exists(target_path):
                return False
            conn = sqlite3.connect(
                f"file:{Path(target_path).as_posix()}?mode=ro", uri=True, timeout=5
            )
            try:
                row = conn.execute("SELECT 1 FROM rag_chunks WHERE id = ? LIMIT 1", (cid,)).fetchone()
                return bool(row)
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Vérification existence chunk RAG impossible (cid=%s) : %s", cid, exc)
            return False

    def _persist_chunk(self, cid: str, source: str, domain: str, text: str) -> bool:
        """Archive un chunk via la voie gouvernée (forge_ingest_pipeline + write_retry).

        Règles d'or (constats 1 & 2) :
        - Passe par la voie existante (process_document + store_chunks).
        - Exécution sous write_retry via store_chunks pour tolérer la contention sans verrou.
        - Aucun INSERT manuel dans rag_fts (l'index lexical est synchronisé par déclencheurs/pipeline).
        - Déjà présent = CONFIRMÉ (idempotence, zéro faux échec ni rejeu infini).
        - En cas d'échec : logger.warning (non muet) et incrémente archive_failed_count.
        - Rend True si l'archive est confirmée, False sinon.
        """
        try:
            import sys

            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_ingest_pipeline import RefinedChunk, process_document, store_chunks

            chunks = process_document(
                text=text,
                source=source,
                domain_hint=domain or self.domain,
                role_hint="archive:osmoregulation",
                author=f"session:{self.session_id}",
                doc_summary=f"Archive osmorégulation {self.session_id}",
            )
            if not chunks:
                chunks = [
                    RefinedChunk(
                        id=cid,
                        text=text,
                        source=source,
                        domain=domain or self.domain,
                        role_hint="archive:osmoregulation",
                        author=f"session:{self.session_id}",
                        meta={"session_id": self.session_id, "fingerprint": cid},
                    )
                ]
            else:
                chunks[0].id = cid
                chunks[0].meta["session_id"] = self.session_id
                chunks[0].meta["fingerprint"] = cid

            inserted = store_chunks(chunks)
            if inserted <= 0:
                # Constat 1 : déduplication / idempotence. Si 0 chunk inséré car déjà présent
                # (fingerprint connu ou id présent dans rag_chunks), l'archive est CONFIRMÉE
                # (évite faux échec et rejeu infini à chaque fenêtre).
                already_present = any(c.meta.get("already_present") for c in chunks)
                if already_present or self._chunk_exists_in_rag(cid):
                    logger.debug(
                        "Chunk déjà présent dans rag_chunks (cid=%s) : archive confirmée (idempotente)",
                        cid,
                    )
                    return True

                self._archive_failed_count += 1
                logger.warning(
                    "Archivage RAG osmorégulation non confirmé (0 chunk inséré, cid=%s)",
                    cid,
                )
                return False

            return True
        except Exception as exc:
            self._archive_failed_count += 1
            logger.warning(
                "Échec de l'archivage RAG osmorégulation (chunk_id=%s, échecs=%d) : %s",
                cid,
                self._archive_failed_count,
                exc,
            )
            return False

    def _anchor_dropped_facts(
        self,
        dropped_decisions: list[str],
        dropped_paths: list[str],
        dropped_errors: list[str],
        force: bool = False,
    ) -> Optional[str]:
        """Ancre UNIQUEMENT ce que la compaction jette vraiment de la fenêtre retenue.

        Règles d'or (constats 1 & 2) :
        - N'ancre QUE les décisions, chemins et erreurs sortis de la fenêtre retenue.
        - Au plus une fois par fenêtre (seuil archive_window_size ou force=True en fin de session).
        - Jamais dans logs/lessons_learned.md (zéro pollution de la mémoire des développeurs).
        - Écriture hors boucle asyncio (to_thread) pour zéro gel d'event loop.
        - Ne jette les faits que SI l'archive est confirmée (constat 2 : zéro perte muette).
        - Retourne l'identifiant réel du chunk (sha256 source+texte) pour pointer l'archive exacte.
        """
        with self._lock:
            new_d = [
                d for d in dropped_decisions
                if f"d:{d}" not in self._anchored_fact_keys and f"d:{d}" not in self._inflight_fact_keys
            ]
            new_p = [
                p for p in dropped_paths
                if f"p:{p}" not in self._anchored_fact_keys and f"p:{p}" not in self._inflight_fact_keys
            ]
            new_e = [
                e for e in dropped_errors
                if f"e:{e}" not in self._anchored_fact_keys and f"e:{e}" not in self._inflight_fact_keys
            ]

            total_new = len(new_d) + len(new_p) + len(new_e)
            if total_new == 0:
                return None

            if not force and total_new < self.archive_window_size:
                # Attend d'accumuler une fenêtre complète avant d'ancrer
                return None

            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            while total_new >= self.archive_window_size or (force and total_new > 0):
                batch_d = new_d[:self.archive_window_size]
                new_d = new_d[len(batch_d):]
                quota = self.archive_window_size - len(batch_d)
                batch_p = new_p[:quota]
                new_p = new_p[len(batch_p):]
                quota2 = quota - len(batch_p)
                batch_e = new_e[:quota2]
                new_e = new_e[len(batch_e):]

                batch_keys = (
                    [f"d:{d}" for d in batch_d]
                    + [f"p:{p}" for p in batch_p]
                    + [f"e:{e}" for e in batch_e]
                )
                # Constat 2 : marquer 'en vol' AVANT de déporter
                for k in batch_keys:
                    self._inflight_fact_keys.add(k)

                lines = []
                if batch_d:
                    lines.append(f"Décisions évincées: {'; '.join(batch_d)}")
                if batch_p:
                    lines.append(f"Chemins évincés: {', '.join(batch_p)}")
                if batch_e:
                    lines.append(f"Erreurs évincées: {'; '.join(batch_e)}")

                source = f"session:{self.session_id}:osmoregulation"
                text_to_anchor = (
                    f"Archive osmorégulation session={self.session_id} seq={self._digest_count}:\n"
                    + "\n".join(lines)
                )

                key = f"{source}|{text_to_anchor}"
                cid = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]

                def _write_and_confirm(
                    b_keys=batch_keys, c_id=cid, s_rc=source, t_ext=text_to_anchor
                ) -> bool:
                    try:
                        ok = self._persist_chunk(c_id, s_rc, self.domain, t_ext)
                    except Exception as err:
                        logger.warning("Erreur dans _persist_chunk (cid=%s) : %s", c_id, err)
                        ok = False

                    # Confirmer ou retirer au retour, sous verrou (constat 2)
                    with self._lock:
                        for k in b_keys:
                            self._inflight_fact_keys.discard(k)
                        if ok:
                            for k in b_keys:
                                self._anchored_fact_keys.add(k)
                            self._last_archive_chunk_id = c_id
                            self._rag_anchor_count += 1
                            arch_tag = f"[Archive RAG: id={c_id}]"
                            if arch_tag not in (self.summary or ""):
                                if self.summary:
                                    self.summary = f"{arch_tag}\n{self.summary}"
                                else:
                                    self.summary = arch_tag
                            return True
                        return False

                if loop and loop.is_running():
                    task = loop.create_task(asyncio.to_thread(_write_and_confirm))
                    self._running_tasks.add(task)
                    task.add_done_callback(self._running_tasks.discard)
                else:
                    _write_and_confirm()

                total_new = len(new_d) + len(new_p) + len(new_e)
                if not force and total_new < self.archive_window_size:
                    break
                if force and total_new == 0:
                    break

            return self._last_archive_chunk_id

    def _enforce_summary_budget(self, raw_summary: str) -> str:
        """Borne la taille du résumé au budget alloué (constat 1 & constat 2).

        Au-delà du budget :
        - Déclenche l'ancrage RAG uniquement pour les faits jetés hors de la fenêtre
          retenue (au plus une fois par fenêtre, jamais dans lessons_learned).
        - Pointeur RAG vers l'id réel du chunk ancré (sha256 source+texte).
        - Si troncature nécessaire, indique explicitement ce qui est coupé avec compteur.
        """
        def _clean_val(v: str) -> str:
            if not v:
                return ""
            if "[tronqué:" in v:
                v = re.sub(r"\s*\.{0,}\s*\[tronqué:[^\]]*\]", "", v).strip()
            if v.startswith("...") or v.startswith("[tronqué:") or v.endswith("car.]") or v.endswith("..."):
                self._clean_val_dropped_count += 1
                logger.warning(
                    "_clean_val : valeur tronquée ou incomplète écartée (val=%r, total_écartés=%d)",
                    v[:60],
                    self._clean_val_dropped_count,
                )
                return ""
            return v.strip()

        # Parse et accumule tous les faits présents dans raw_summary
        for m in _PAT_DECISION.finditer(raw_summary):
            for part in m.group(1).split(";"):
                val = _clean_val(part)
                if val and val not in self._accumulated_decisions:
                    if not any(d.startswith(val) for d in self._accumulated_decisions):
                        self._accumulated_decisions.append(val)

        for m in _PAT_PATH.finditer(raw_summary):
            val = _clean_val(m.group(1))
            if val and val not in self._accumulated_paths:
                if not any(p.startswith(val) for p in self._accumulated_paths):
                    self._accumulated_paths.append(val)

        for m in _PAT_ERROR.finditer(raw_summary):
            for part in m.group(1).split(";"):
                val = _clean_val(part)
                if val and val not in self._accumulated_errors:
                    if not any(e.startswith(val) for e in self._accumulated_errors):
                        self._accumulated_errors.append(val)

        budget_chars = self.summary_token_budget * 4
        if len(raw_summary) <= budget_chars:
            return raw_summary

        synopsis = []
        for m in _PAT_SYNOPSIS.finditer(raw_summary):
            val = m.group(1).strip()
            if val not in synopsis:
                synopsis.append(val)

        # Fenêtre retenue (12 dernières décisions, 12 derniers chemins, 8 dernières erreurs)
        retained_decisions = self._accumulated_decisions[-12:]
        retained_paths = self._accumulated_paths[-12:]
        retained_errors = self._accumulated_errors[-8:]
        retained_synopsis = synopsis[-4:]

        # Faits sortis de la fenêtre retenue (ce que la compaction jette vraiment)
        dropped_decisions = self._accumulated_decisions[:-12]
        dropped_paths = self._accumulated_paths[:-12]
        dropped_errors = self._accumulated_errors[:-8]

        # Ancrage borné par fenêtre des faits jetés
        self._anchor_dropped_facts(dropped_decisions, dropped_paths, dropped_errors)

        # Constat 2 : les faits non archivés RESTENT dans le résumé (ne pas les jeter tant que l'archive n'est pas confirmée)
        unarchived_decisions = [d for d in self._accumulated_decisions if f"d:{d}" not in self._anchored_fact_keys]
        unarchived_paths = [p for p in self._accumulated_paths if f"p:{p}" not in self._anchored_fact_keys]
        unarchived_errors = [e for e in self._accumulated_errors if f"e:{e}" not in self._anchored_fact_keys]

        sections = []
        if self._last_archive_chunk_id:
            sections.append(f"[Archive RAG: id={self._last_archive_chunk_id}]")

        if unarchived_decisions:
            sections.append(f"Décisions (DECISION): {'; '.join(unarchived_decisions)}")
        if unarchived_paths:
            sections.append(f"Chemins: {', '.join(unarchived_paths)}")
        if unarchived_errors:
            sections.append(f"Erreurs: {'; '.join(unarchived_errors)}")
        if retained_synopsis:
            sections.append("Synthèse récente:\n" + "\n".join(f"- {s}" for s in retained_synopsis))

        compacted = "\n".join(sections)
        if len(compacted) > budget_chars:
            cut_chars = len(compacted) - budget_chars
            self._summary_truncated_chars += cut_chars
            self._summary_truncated_count += 1
            trunc_tag = f" ... [tronqué: {cut_chars} car.]"
            available = max(20, budget_chars - len(trunc_tag))
            compacted = compacted[:available] + trunc_tag

        return compacted

    def _commit_digest(self, to_evict: list[SessionMessage], digest_text: str) -> None:
        if self.summary:
            raw = f"{self.summary}\n{digest_text}".strip()
        else:
            raw = digest_text.strip()

        self.summary = self._enforce_summary_budget(raw)

        to_evict_ids = set(id(m) for m in to_evict)
        self._digesting_messages = [m for m in self._digesting_messages if id(m) not in to_evict_ids]
        self._digest_count += 1
        _emit(
            "session.digest",
            "success",
            {
                "session_id": self.session_id,
                "n_digested": len(to_evict),
                "summary_len": len(self.summary),
                "digest_count": self._digest_count,
            },
        )

    def _handle_digest_failure(self, to_evict: list[SessionMessage], exc: Exception) -> None:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            logger.warning("Timeout du résumeur (%.2fs) : repli déterministe appliqué", self.digest_timeout)
            self._last_error = f"Timeout résumeur ({self.digest_timeout}s)"
            err_tag = f"Timeout({self.digest_timeout}s)"
        else:
            logger.error(f"Erreur summarizer lors de la digestion: {exc}", exc_info=True)
            self._last_error = str(exc)
            err_tag = type(exc).__name__

        # Secours déterministe immédiat : ne JAMAIS perdre les messages évincés !
        try:
            fallback = self._extract_deterministic(to_evict)
            if fallback:
                fb_text = f"[secours err={err_tag}] {fallback}"
                if self.summary:
                    raw = f"{self.summary}\n{fb_text}".strip()
                else:
                    raw = fb_text.strip()
                self.summary = self._enforce_summary_budget(raw)
                to_evict_ids = set(id(m) for m in to_evict)
                self._digesting_messages = [m for m in self._digesting_messages if id(m) not in to_evict_ids]
                self._digest_count += 1
        except Exception as fb_exc:
            logger.critical(f"Erreur critique lors du secours déterministe: {fb_exc}")
        _emit(
            "session.digest",
            "error",
            {"session_id": self.session_id, "error": str(exc)[:200]},
        )

    def _extract_deterministic(self, messages: list[SessionMessage]) -> str:
        """Extraction déterministe de faits génériques (chemins, décisions, erreurs) (constat 2)."""
        decisions = []
        paths = []
        errors = []
        generic_facts = []
        synopsis = []

        for m in messages:
            txt = m.text or ""
            for match in _PAT_DECISION.finditer(txt):
                for part in match.group(1).split(";"):
                    val = part.strip()
                    if val and val not in decisions:
                        decisions.append(val)
            for match in _PAT_PATH.finditer(txt):
                val = match.group(1).strip()
                if val not in paths:
                    paths.append(val)
            for match in _PAT_ERROR.finditer(txt):
                for part in match.group(1).split(";"):
                    val = part.strip()
                    if val and val not in errors:
                        errors.append(val)
            for match in _PAT_FACT.finditer(txt):
                val = (match.group(1) or match.group(2) or match.group(3) or "").strip()
                if val and val not in generic_facts:
                    generic_facts.append(val)

            one_line = txt.replace("\n", " ").strip()
            if len(one_line) > 120:
                one_line = one_line[:117] + "..."
            synopsis.append(f"[{m.role}] {one_line}")

        sections = []
        if generic_facts:
            sections.append(f"Faits vérifiés: {', '.join(generic_facts)}")
        if decisions:
            sections.append(f"Décisions (DECISION): {'; '.join(decisions)}")
        if paths:
            sections.append(f"Chemins: {', '.join(paths)}")
        if errors:
            sections.append(f"Erreurs: {'; '.join(errors)}")
        if synopsis:
            sections.append("Synthèse:\n" + "\n".join(f"- {s}" for s in synopsis))

        return "\n".join(sections)

    def _merge_digests(self, deterministic: str, custom: Optional[str]) -> str:
        if not custom:
            return deterministic
        if not deterministic:
            return custom
        return f"{custom.strip()}\n---\n[Faits & repères vérifiés]\n{deterministic.strip()}"

    def get_context(self) -> list[dict]:
        """Retourne le contexte complet :
        1. Résumé accumulé et borné (si présent)
        2. Compartiment 'en digestion' visible tant que le résumé n'est pas posé
        3. Messages actifs récents
        """
        ctx = []
        if self.summary:
            ctx.append({"role": "system", "content": f"Résumé: {self.summary}"})
        for m in self._digesting_messages:
            ctx.append({
                "role": m.role,
                "content": m.text,
                "in_digestion": True,
            })
        for m in self.messages:
            ctx.append({
                "role": m.role,
                "content": m.text,
            })
        return ctx

    def get_recalled_facts(self) -> dict[str, set[str]]:
        """Extrait l'ensemble des faits génériques (chemins, décisions, erreurs) présents dans tout le contexte."""
        decisions: set[str] = set(self._accumulated_decisions)
        paths: set[str] = set(self._accumulated_paths)
        errors: set[str] = set(self._accumulated_errors)

        texts = []
        if self.summary:
            texts.append(self.summary)
        for m in self._digesting_messages:
            texts.append(m.text)
        for m in self.messages:
            texts.append(m.text)

        for t in texts:
            for match in _PAT_DECISION.finditer(t):
                for part in match.group(1).split(";"):
                    val = part.strip()
                    if val:
                        decisions.add(val)
            for match in _PAT_PATH.finditer(t):
                paths.add(match.group(1).strip())
            for match in _PAT_ERROR.finditer(t):
                for part in match.group(1).split(";"):
                    val = part.strip()
                    if val:
                        errors.add(val)

        return {"decisions": decisions, "paths": paths, "errors": errors}

    @property
    def current_tokens(self) -> int:
        return sum(m.tokens for m in self.messages)

    @property
    def is_digesting(self) -> bool:
        return self._is_digesting

    @property
    def in_digestion_count(self) -> int:
        return len(self._digesting_messages)

    @property
    def all_messages(self) -> list[SessionMessage]:
        return list(self._digesting_messages) + list(self.messages)

    def set_summarizer(self, fn: Optional[Callable[[list[SessionMessage]], Any]]) -> None:
        self._summarizer = fn

    async def wait_digestion(self, timeout: float = 5.0) -> None:
        if self._running_tasks:
            await asyncio.wait(list(self._running_tasks), timeout=timeout)

    # ── résumé exportable ─────────────────────────────────────────────────
    def summarize(self, max_chars: int = 800) -> str:
        """Résumé extractif direct ou restitution du résumé digéré."""
        if self.summary:
            s = self.summary
            if len(s) > max_chars:
                return s[: max_chars - 3] + "..."
            return s

        if not self.messages and not self._digesting_messages:
            return ""

        all_msgs = self.all_messages
        lines = []
        for m in all_msgs[-20:]:
            txt = (m.text or "").replace("\n", " ").strip()[:120]
            lines.append(f"[{m.role}] {txt}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text

    # ── ancrage RAG ──────────────────────────────────────────────────────
    def anchor_summary(self, domain: Optional[str] = None, problem: str = "") -> bool:
        """Persiste le résumé dans rag_chunks (sans polluer lessons_learned.md)."""
        if not self.messages and not self._digesting_messages and not self.summary:
            return False
        try:
            summary = self.summarize(max_chars=1500)
            source = f"session:{self.session_id}:summary"
            text_to_anchor = f"{problem or f'Session {self.name}'}\n{summary}"
            key = f"{source}|{text_to_anchor}"
            cid = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]

            confirmed = self._persist_chunk(cid, source, domain or self.domain, text_to_anchor)
            if confirmed:
                self._last_archive_chunk_id = cid
                self._rag_anchor_count += 1
                self._anchored = True
                _emit("session.anchor", "success", {"session_id": self.session_id, "n": len(self.messages), "chunk_id": cid})
                return True
            else:
                _emit("session.anchor", "error", {"session_id": self.session_id, "err": "persist_chunk_failed"})
                return False
        except Exception as e:
            logger.warning(f"anchor_summary fail: {e}")
            _emit("session.anchor", "error", {"session_id": self.session_id, "err": str(e)[:120]})
            return False

    # ── persistence ──────────────────────────────────────────────────────
    def _state_path(self) -> Path:
        return SANDBOX / f"session_{self.name}_{self.session_id}.json"

    @property
    def filename(self) -> Path:
        return self._state_path()

    def save(self) -> Optional[Path]:
        try:
            SANDBOX.mkdir(parents=True, exist_ok=True)
            data = {
                "name": self.name,
                "session_id": self.session_id,
                "started_at": self.started_at,
                "domain": self.domain,
                "max_messages": self.max_messages,
                "max_tokens": self.max_tokens,
                "max_summary_tokens": self.max_summary_tokens,
                "digest_timeout": self.digest_timeout,
                "archive_window_size": self.archive_window_size,
                "summary": self.summary,
                "_digest_count": self._digest_count,
                "_sync_async_skipped_count": self._sync_async_skipped_count,
                "_rag_anchor_count": self._rag_anchor_count,
                "_last_archive_chunk_id": self._last_archive_chunk_id,
                "_summary_truncated_count": self._summary_truncated_count,
                "_summary_truncated_chars": self._summary_truncated_chars,
                "_archive_failed_count": self._archive_failed_count,
                "_clean_val_dropped_count": self._clean_val_dropped_count,
                "extra": self.extra,
                "_anchored": self._anchored,
                "messages": [m.to_dict() for m in self.messages],
            }
            p = self._state_path()
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return p
        except Exception as e:
            logger.warning(f"save fail: {e}")
            return None

    @classmethod
    def load(cls, path: Path) -> Optional["SessionContext"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        raw_msgs = data.pop("messages", [])
        msgs = [
            SessionMessage(
                role=m.get("role", "user"),
                text=m.get("text") or m.get("content", ""),
                ts=m.get("ts", time.time()),
                meta=m.get("meta", {}),
            )
            for m in raw_msgs
        ]
        allowed_fields = set(cls.__dataclass_fields__.keys())
        ctx = cls(**{k: v for k, v in data.items() if k in allowed_fields})
        ctx.messages = msgs
        return ctx

    def unregister(self) -> None:
        """Compatibilité forge_core_models : enregistre et détache de RAG."""
        self.save()
        try:
            from nokido_agent.app.forge_app_context import get_rag as _gr

            rag_engine = getattr(self, "rag_engine", None) or _gr()
            if rag_engine and hasattr(rag_engine, "session_ctxs") and self.name in rag_engine.session_ctxs:
                del rag_engine.session_ctxs[self.name]
        except Exception as e:
            logger.debug(f"unregister rag_engine fail: {e}")

    def end(self, anchor: bool = True) -> None:
        if anchor and not self._anchored:
            self.anchor_summary()
        self.save()
        _emit(
            "session.end",
            "info",
            {
                "session_id": self.session_id,
                "duration_s": int(time.time() - self.started_at),
                "n_messages": len(self.messages),
            },
        )


# ── Singleton "active session" ─────────────────────────────────────────────

_active: Optional[SessionContext] = None


def get_active_session() -> Optional[SessionContext]:
    return _active


def set_active_session(ctx: SessionContext) -> None:
    global _active
    _active = ctx

