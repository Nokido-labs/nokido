"""Tient l'etat mode/ring du hub et en derive outils permis, recherche RAG et prompts.

get_core() rend le singleton CoreBridge (StateManager, RAGManager, PromptBuilder,
ServiceManager) : get_context, status, is_allowed, dispatch_task, tui_notify,
push_tui_command, get_tui_command ; plus apply_smart_patch et learn_from_error.
Etat persiste dans sandbox/core_state.json ; SQLite RAG/embeddings.db (rag_chunks,
tui_notifications, tui_commands). ServiceManager sonde 127.0.0.1:8766/health,
redemarre le hub (nssm/systemctl ou sandbox/hub_restart.trigger) et appelle les
API GitHub, Codeberg et Woodpecker ; apply_smart_patch reecrit un fichier du depot.
Utilise par forge_hub_handlers, forge_events, forge_unified_discovery et tests/nr.
"""
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_033324_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings cerberus
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
nokido_core.py — Nokido Core Engine v17.02
=============================================
Source de Vérité unique pour l'architecture Hub v17.

Rôle : Chef d'orchestre externe — ne modifie pas Nokido.py,
       s'en sert comme bibliothèque.

Responsabilités :
  1. StateManager   — état TUI (mode collab, ring sécurité, modèles)
  2. RAGManager     — recherche chunks, filtrage par ring, ingest background
  3. PromptBuilder  — prompts MCP dynamiques selon l'état TUI
  4. CoreBridge     — interface que le Hub interroge à chaque appel

Principe Edge-Control :
  TUI Textual  →  CoreBridge.set_state()
  Hub MCP      →  CoreBridge.get_context()  (lecture seule)
  RAGManager   →  cherche dans SQLite, filtre par ring TUI

Fonctionne offline — aucune dépendance réseau.
"""

import concurrent.futures
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime as _dt
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Nokido.Core")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
_STATE_FILE = ROOT / "sandbox" / "core_state.json"


# =============================================================================
# 1. ENUMS & CONSTANTES
# =============================================================================


class CollabMode(IntEnum):
    SOLO = 0
    ASSISTANT = 1
    COLLAB = 2
    AUTONOMOUS = 3


class SecurityRing(IntEnum):
    SYSTEM = 0
    DEV = 1
    TRUSTED = 2
    COLLAB = 3
    UNTRUSTED = 4


_RING_CAPS: Dict[int, List[str]] = {
    0: [
        "read",
        "write",
        "query",
        "python",
        "github",
        "test_nr",
        "test_module",
        "test_status",
        "atlas_build",
        "atlas_get",
        "save_situation",
        "make_snapshot",
        "snapshot",
        "hub_restart",
        "hub_status",
        "setup_check",
        "unified_discovery",
        "trigger_autonomous_evolution",
        "task_status",
        "get_mode",
        "set_mode",
        "notify",
        "poll",
        "index_result",
        "search_recent",
        "auto_test",
    ],
    1: [
        "read",
        "write",
        "query",
        "python",
        "github",
        "test_nr",
        "test_module",
        "test_status",
        "atlas_build",
        "atlas_get",
        "save_situation",
        "make_snapshot",
        "snapshot",
        "hub_restart",
        "hub_status",
        "setup_check",
        "unified_discovery",
        "trigger_autonomous_evolution",
        "task_status",
        "get_mode",
        "set_mode",
        "notify",
        "poll",
        "index_result",
        "search_recent",
        "auto_test",
    ],
    2: [
        "read",
        "write",
        "query",
        "github",
        "test_nr",
        "test_status",
        "atlas_get",
        "trigger_autonomous_evolution",
        "task_status",
        "get_mode",
        "notify",
        "poll",
        "index_result",
        "search_recent",
    ],
    3: ["read", "query"],
    4: ["read"],
}

_COLLAB_PROMPTS: Dict[int, str] = {
    CollabMode.SOLO: (
        "Tu es Nokido Assistant. Mode SOLO actif. "
        "Tu fournis des informations et analyses. "
        "Tu ne proposes PAS de modifications de code ni de commits. "
        "Attends toujours une instruction explicite avant d'agir."
    ),
    CollabMode.ASSISTANT: (
        "Tu es Nokido Assistant. Mode ASSISTANT actif. "
        "Tu peux analyser, suggérer et préparer des changements. "
        "Toute modification doit être validée par l'humain avant exécution. "
        "Explique ton raisonnement avant chaque proposition."
    ),
    CollabMode.COLLAB: (
        "Tu es Nokido Assistant. Mode COLLABORATION actif. "
        "Tu travailles en binôme avec le développeur. "
        "Tu peux proposer des commits via @ci gh et des modifications via write. "
        "Documente chaque changement dans SITUATION.md."
    ),
    CollabMode.AUTONOMOUS: (
        "Tu es Nokido Assistant. Mode AUTONOME actif. "
        "Tu as l'autorisation de proposer et préparer des commits GitHub Actions. "
        "Reste dans le périmètre du projet Nokido. "
        "Log chaque action dans event_log. Snapshot avant toute mutation RAG."
    ),
}

# Timeout sémantique en mode DEV.
_SEMANTIC_TIMEOUT = 0.5  # secondes

# Executor PARTAGÉ pour la recherche sémantique. Il ne doit PAS être créé par un
# `with` par requête : à la sortie du bloc, ThreadPoolExecutor.__exit__ appelle
# shutdown(wait=True), qui ATTEND la tâche même après un fut.result(timeout=…).
# Mesuré le 2026-08-21 : tâche de 5 s, timeout annoncé 0,5 s -> temps réel 5,0 s
# (×10). Le « timeout strict » n'en était pas un, et nokido_core est appelé par
# forge_hub_handlers — donc dans le chemin chaud du hub. Un pool résident laisse
# fut.result() rendre la main à l'échéance ; le thread bloqué finit tout seul et
# sa lane se libère (max_workers borne la fuite). daemon threads -> pas de blocage
# à l'arrêt du process.
_SEMANTIC_EX: "Optional[concurrent.futures.ThreadPoolExecutor]" = None
_SEMANTIC_EX_LOCK = threading.Lock()


def _semantic_executor() -> "concurrent.futures.ThreadPoolExecutor":
    global _SEMANTIC_EX
    if _SEMANTIC_EX is None:
        with _SEMANTIC_EX_LOCK:
            if _SEMANTIC_EX is None:
                _SEMANTIC_EX = concurrent.futures.ThreadPoolExecutor(
                    max_workers=4, thread_name_prefix="rag-sem")
    return _SEMANTIC_EX


# =============================================================================
# 2. STATE MANAGER
# =============================================================================


@dataclass
class CoreState:
    collab_mode: int = CollabMode.ASSISTANT
    active_ring: int = SecurityRing.DEV
    model_chat: str = "qwen2.5:7b"
    model_action: str = "qwen2.5:7b"
    model_rag: str = "bge-m3"
    rag_topk: int = 5
    rag_min_trust: float = 0.5
    rag_domains: List[str] = field(default_factory=lambda: ["code", "systeme", "securite", "ia", "devops"])
    context_window: int = 4096
    session_id: str = ""
    updated_at: str = ""
    auto_mode: bool = False  # TUI AUTO switch


class StateManager:
    def __init__(self) -> None:
        """Init."""
        self._lock = threading.RLock()
        self._state = CoreState()
        self._load()

    def _load(self) -> None:
        """Load."""
        try:
            if _STATE_FILE.exists():
                data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if hasattr(self._state, k):
                        setattr(self._state, k, v)
        except Exception as e:
            logger.warning("[Core] Impossible de charger l'état: " + str(e))

    def _save(self) -> None:
        """Save."""
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(asdict(self._state), indent=2), encoding="utf-8")
        except Exception:
            pass

    def get(self) -> CoreState:
        """Get."""
        with self._lock:
            return self._state

    def set(self, **kwargs) -> CoreState:
        """Set."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)
            self._state.updated_at = _dt.now().isoformat(timespec="seconds")
            self._save()
            return self._state

    def set_collab_mode(self, mode: int) -> str:
        """Set collab mode.

        Args:
            mode: Description.
        """
        mode = max(0, min(3, int(mode)))
        self.set(collab_mode=mode)
        return CollabMode(mode).name

    def set_ring(self, ring: int) -> str:
        """Set ring.

        Args:
            ring: Description.
        """
        ring = max(0, min(4, int(ring)))
        self.set(active_ring=ring)
        return SecurityRing(ring).name

    def allowed_tools(self) -> List[str]:
        """Allowed tools."""
        return _RING_CAPS.get(self._state.active_ring, ["read"])

    def is_tool_allowed(self, tool: str) -> bool:
        """Is tool allowed.

        Args:
            tool: Description.
        """
        return tool in self.allowed_tools()

    def as_dict(self) -> dict:
        """As dict."""
        with self._lock:
            return asdict(self._state)


# =============================================================================
# 3. RAG MANAGER
# =============================================================================


class RAGManager:
    """
    Interface RAG pilotée par le Core.

    Stratégie de recherche par ring :
      ring <= 1 (SYSTEM/DEV) : tente sémantique avec timeout 0.5s,
                                fallback silencieux vers keyword si timeout/erreur
      ring >= 2 (autres)     : keyword matching SQLite direct — stable, offline
    """

    def __init__(self, state_mgr: StateManager) -> None:
        """Init.

        Args:
            state_mgr: Description.
        """
        self._state = state_mgr

    # ── Recherche principale ──────────────────────────────────────────────────

    def search(
        self,
        query: str,
        k: Optional[int] = None,
        domain: Optional[str] = None,
        ring_max: Optional[int] = None,
        role_hint: Optional[str] = None,
    ) -> List[Dict]:
        """Search.

        Args:
            query: Description.
            k: Description.
            domain: Description.
            ring_max: Description.
            role_hint: Description.
        """
        state = self._state.get()
        k = k or state.rag_topk
        ring_max = ring_max if ring_max is not None else state.active_ring
        min_trust = state.rag_min_trust

        # Mode DEV uniquement : tentative sémantique avec timeout RÉELLEMENT strict.
        # Le pool est partagé (cf. _semantic_executor) : à l'échéance on retombe sur
        # le keyword search SANS attendre le thread lent — l'ancien `with` attendait.
        if state.active_ring <= 1 and query:
            fut = _semantic_executor().submit(
                self._semantic_search, query, k, domain, ring_max, min_trust)
            try:
                result = fut.result(timeout=_SEMANTIC_TIMEOUT)
                if result:
                    logger.debug("[RAG] sémantique OK (" + str(len(result)) + " chunks)")
                    return result
            except concurrent.futures.TimeoutError:
                # On abandonne l'attente ; le thread finit seul et libère sa lane.
                fut.cancel()
                logger.debug("[RAG] sémantique timeout → fallback keyword")
            except Exception as e:
                logger.debug("[RAG] sémantique erreur → fallback keyword: " + str(e))

        # Tous les autres modes + fallback DEV : keyword matching
        return self._keyword_search(query, k, domain, ring_max, min_trust, role_hint)

    # ── Sémantique (mode DEV, optionnel) ─────────────────────────────────────

    def _semantic_search(
        self, query: str, k: int, domain: Optional[str], ring_max: int, min_trust: float
    ) -> Optional[List[Dict]]:
        """
        Recherche sémantique via forge_rag_engine.
        Appelée dans un thread séparé — ne doit JAMAIS bloquer.
        Retourne None si le moteur n'est pas disponible.
        """
        try:
            from nokido_agent.app.forge_rag_engine import _get_rag_engine

            engine = _get_rag_engine()
            if engine is None:
                return None
            # Appel synchrone au moteur RAG
            import asyncio

            loop = asyncio.new_event_loop()
            chunks = loop.run_until_complete(engine.search(query, k=k, ring_max=ring_max, min_trust=min_trust))
            loop.close()
            if not chunks:
                return None
            return [
                {
                    "id": c.get("id", ""),
                    "text": c.get("text", "")[:500],
                    "source": c.get("source", ""),
                    "domain": c.get("domain", ""),
                    "role_hint": c.get("role_hint", ""),
                    "trust": c.get("trust_score", 0.5),
                    "ring": c.get("ring", ring_max),
                    "consensus": c.get("consensus_level", ""),
                    "_mode": "semantic",
                }
                for c in chunks[:k]
            ]
        except Exception:
            return None

    # ── Keyword matching (universel, fallback) ────────────────────────────────

    def _keyword_search(
        self,
        query: str,
        k: int,
        domain: Optional[str],
        ring_max: int,
        min_trust: float,
        role_hint: Optional[str] = None,
    ) -> List[Dict]:
        """Keyword matching SQLite — stable, offline, jamais bloquant."""
        try:
            conn = sqlite3.connect(str(DB))
            conn.execute("PRAGMA journal_mode=WAL")

            conditions = ["json_extract(meta, '$.trust_score') >= ?"]
            params: List[Any] = [min_trust]

            if ring_max < 4:
                conditions.append("CAST(json_extract(meta, '$.ring') AS INTEGER) <= ?")
                params.append(ring_max)
            if domain:
                conditions.append("domain = ?")
                params.append(domain)
            if role_hint:
                conditions.append("role_hint = ?")
                params.append(role_hint)

            where = " AND ".join(conditions)
            sql = (
                "SELECT id, text, source, domain, role_hint, "
                "json_extract(meta, '$.trust_score') as trust, "
                "json_extract(meta, '$.ring') as ring, "
                "json_extract(meta, '$.consensus_level') as consensus "
                "FROM rag_chunks WHERE " + where + " ORDER BY trust DESC LIMIT ?"
            )
            params.append(k * 3)  # over-fetch pour le scoring keyword
            rows = conn.execute(sql, params).fetchall()
            conn.close()

            # Scoring keyword sur les résultats
            if query:
                q_words = set(query.lower().split())
                scored = []
                for row in rows:
                    text_lower = (row[1] or "").lower()
                    score = sum(1 for w in q_words if w in text_lower)
                    scored.append((score, row))
                scored.sort(key=lambda x: x[0], reverse=True)
                rows = [r for _, r in scored]

            return [
                {
                    "id": r[0],
                    "text": r[1][:500],
                    "source": r[2],
                    "domain": r[3],
                    "role_hint": r[4],
                    "trust": r[5],
                    "ring": r[6],
                    "consensus": r[7],
                    "_mode": "keyword",
                }
                for r in rows[:k]
            ]
        except Exception as e:
            logger.error("[RAG] keyword_search error: " + str(e))
            return []

    # ── Stats & contexte ─────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Stats."""
        try:
            conn = sqlite3.connect(str(DB))
            total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            by_domain = conn.execute(
                "SELECT domain, COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 5"
            ).fetchall()
            by_ring = conn.execute("SELECT json_extract(meta,'$.ring'), COUNT(*) FROM rag_chunks GROUP BY 1").fetchall()
            conn.close()
            return {
                "total": total,
                "by_domain": dict(by_domain),
                "by_ring": {str(k): v for k, v in by_ring},
            }
        except Exception as e:
            return {"error": str(e)}

    def context_for_prompt(self, query: str, max_chars: int = 2000) -> str:
        """Context for prompt.

        Args:
            query: Description.
            max_chars: Description.
        """
        if not query:
            return ""
        chunks = self.search(query, k=5)
        if not chunks:
            return ""
        lines = ["[CONTEXT RAG — Nokido Knowledge Base]"]
        total = 0
        for i, c in enumerate(chunks, 1):
            snippet = c["text"][:300].replace("\n", " ")
            entry = "[" + str(i) + "] (" + c["domain"] + "/" + c["role_hint"] + ") " + snippet
            if total + len(entry) > max_chars:
                break
            lines.append(entry)
            total += len(entry)
        lines.append("[FIN CONTEXT]")
        return "\n".join(lines)


# =============================================================================
# 4. PROMPT BUILDER
# =============================================================================


class PromptBuilder:
    def __init__(self, state_mgr: StateManager, rag_mgr: RAGManager) -> None:
        """Init.

        Args:
            state_mgr: Description.
            rag_mgr: Description.
        """
        self._state = state_mgr
        self._rag = rag_mgr

    def list_prompts(self) -> List[Dict]:
        """List prompts."""
        return [
            {"name": "system_context", "description": "Prompt système Nokido selon mode TUI", "arguments": []},
            {
                "name": "rag_context",
                "description": "Contexte RAG injecté selon la query",
                "arguments": [{"name": "query", "description": "Question RAG", "required": True}],
            },
            {"name": "collab_rules", "description": "Règles de collaboration mode TUI", "arguments": []},
        ]

    def get_prompt(self, name: str, args: Dict = None) -> Dict:
        """Get prompt.

        Args:
            name: Description.
            args: Description.
        """
        args = args or {}
        state = self._state.get()

        if name == "system_context":
            collab_prompt = _COLLAB_PROMPTS.get(state.collab_mode, _COLLAB_PROMPTS[1])
            ring_name = SecurityRing(state.active_ring).name
            tools = ", ".join(self._state.allowed_tools())
            rag_mode = "sémantique (DEV)" if state.active_ring <= 1 else "keyword"

            # Injecter les 3 dernières leçons apprises
            recent_lessons = ""
            try:
                conn = sqlite3.connect(str(DB))
                rows = conn.execute(
                    "SELECT text FROM rag_chunks WHERE role_hint='rule' ORDER BY id DESC LIMIT 3"
                ).fetchall()
                conn.close()
                if rows:
                    recent_lessons = (
                        chr(10)
                        + chr(10)
                        + "## Leçons récentes (Self-Correction RAG)"
                        + chr(10)
                        + chr(10).join("- " + r[0][:120].replace(chr(10), " ") for r in rows)
                    )
            except Exception:
                pass

            content = (
                "# Nokido Hub v17 — Contexte Système\n\n" + collab_prompt + "\n\n"
                "## Configuration active\n"
                "- Mode collaboration : " + CollabMode(state.collab_mode).name + "\n"
                "- Ring sécurité      : " + ring_name + " (ring=" + str(state.active_ring) + ")\n"
                "- Outils autorisés   : " + tools + "\n"
                "- RAG chunks         : " + str(self._rag.stats().get("total", "?")) + "\n"
                "- RAG mode           : " + rag_mode + "\n"
                "- Modèle chat        : " + state.model_chat + "\n\n"
                "## Base de connaissances\n"
                "J'ai accès à " + str(self._rag.stats().get("total", "?")) + " chunks "
                "de documentation Nokido filtrés par ring="
                + ring_name
                + "."
                + recent_lessons
                + chr(10)
                + chr(10)
                + "## Règle unified_discovery"
                + chr(10)
                + "Si tu manques de contexte technique, utilise run(action='unified_discovery', code='ta query') "
                + "pour auto-alimenter le RAG local. Ne retourne PAS sur le web pour la même question si "
                + "from_cache=True dans le résultat."
            )
            return {"role": "system", "content": content}

        if name == "rag_context":
            query = args.get("query", "")
            content = self._rag.context_for_prompt(query) if query else "[Pas de query RAG]"
            return {"role": "user", "content": content}

        if name == "collab_rules":
            return {"role": "system", "content": _COLLAB_PROMPTS.get(state.collab_mode, _COLLAB_PROMPTS[1])}

        return {"role": "system", "content": "Prompt inconnu: " + name}


# =============================================================================
# 5. CORE BRIDGE
# =============================================================================


class CoreBridge:
    def __init__(self) -> None:
        """Init."""
        self.state = StateManager()
        self.rag = RAGManager(self.state)
        self.prompts = PromptBuilder(self.state, self.rag)
        self.services = ServiceManager()
        logger.info(
            "[Core] CoreBridge v17.02 | mode="
            + CollabMode(self.state.get().collab_mode).name
            + " ring="
            + SecurityRing(self.state.get().active_ring).name
            + " | hub="
            + ("UP" if self.services.hub_status()["running"] else "DOWN")
        )

    def get_context(self, query: str = "") -> Dict:
        """Get context.

        Args:
            query: Description.
        """
        state = self.state.get()
        ctx = {
            "collab_mode": state.collab_mode,
            "collab_name": CollabMode(state.collab_mode).name,
            "active_ring": state.active_ring,
            "ring_name": SecurityRing(state.active_ring).name,
            "allowed_tools": self.state.allowed_tools(),
            "system_prompt": self.prompts.get_prompt("system_context")["content"],
            "rag_mode": "semantic" if state.active_ring <= 1 else "keyword",
            "updated_at": state.updated_at,
        }
        if query:
            ctx["rag_chunks"] = self.rag.search(query, k=3)
            ctx["rag_context"] = self.rag.context_for_prompt(query)
        return ctx

    def is_allowed(self, tool: str) -> bool:
        """Is allowed.

        Args:
            tool: Description.
        """
        return self.state.is_tool_allowed(tool)

    def status(self) -> Dict:
        """Status."""
        s = self.state.get()
        rag = self.rag.stats()
        return {
            "version": "17.02-Core",
            "collab_mode": CollabMode(s.collab_mode).name,
            "active_ring": SecurityRing(s.active_ring).name,
            "rag_mode": "semantic" if s.active_ring <= 1 else "keyword",
            "allowed_tools": self.state.allowed_tools(),
            "models": {"chat": s.model_chat, "action": s.model_action, "rag": s.model_rag},
            "rag": rag,
            "context_window": s.context_window,
            "updated_at": s.updated_at,
        }

    def tui_set_collab(self, mode: int) -> str:
        """Tui set collab.

        Args:
            mode: Description.
        """
        return self.state.set_collab_mode(mode)

    def tui_set_ring(self, ring: int) -> str:
        """Tui set ring.

        Args:
            ring: Description.
        """
        return self.state.set_ring(ring)

    def tui_set_models(self, chat: str = None, action: str = None, rag: str = None) -> None:
        """Tui set models.

        Args:
            chat: Description.
            action: Description.
            rag: Description.
        """
        kwargs = {}
        if chat:
            kwargs["model_chat"] = chat
        if action:
            kwargs["model_action"] = action
        if rag:
            kwargs["model_rag"] = rag
        if kwargs:
            self.state.set(**kwargs)

    def tui_sync_from_nokido(self, app_instance: object) -> bool:
        """Tui sync from nokido.

        Args:
            app_instance: Description.
        """
        try:
            kwargs = {}
            if hasattr(app_instance, "_collab_mode"):
                mode_map = {"autonome": 0, "assistant": 1, "collaboration": 2, "comite": 3}
                kwargs["collab_mode"] = mode_map.get(getattr(app_instance, "_collab_mode", "assistant"), 1)
            if hasattr(app_instance, "model_chat"):
                kwargs["model_chat"] = app_instance.model_chat
            if hasattr(app_instance, "model_action"):
                kwargs["model_action"] = app_instance.model_action
            if hasattr(app_instance, "model_rag"):
                kwargs["model_rag"] = app_instance.model_rag
            if kwargs:
                self.state.set(**kwargs)
            return True
        except Exception as e:
            logger.warning("[Core] sync_from_nokido error: " + str(e))
            return False

    # =============================================================================
    # 6. SERVICE MANAGER — gestion cycle de vie Hub via NSSM
    # =============================================================================

    # ── TUI ↔ Hub bridge ─────────────────────────────────────────────────────

    def tui_notify(self, message: str, type: str = "info", payload: Dict = None) -> dict:
        """
        LLM → TUI : écrit une notification dans la TUI via SQLite.
        La TUI poll tui_notifications et affiche le message.
        type : info | success | warning | error | action
        """
        import json

        try:
            conn = sqlite3.connect(str(DB))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO tui_notifications (source, type, message, payload) VALUES (?,?,?,?)",
                ("llm", type, message[:1000], json.dumps(payload or {})),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "type": type, "message": message[:80]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_tui_command(self, consume: bool = True) -> Optional[Dict]:
        """
        Hub → lit le prochain ordre TUI (bouton cliqué).
        consume=True : marque l'ordre comme consommé.
        Retourne None si aucun ordre en attente.
        """
        import json

        try:
            conn = sqlite3.connect(str(DB))
            conn.execute("PRAGMA journal_mode=WAL")
            row = conn.execute(
                "SELECT id, command, payload, created_at FROM tui_commands "
                "WHERE status='pending' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if not row:
                conn.close()
                return None
            cmd_id, command, payload_str, created_at = row
            if consume:
                conn.execute(
                    "UPDATE tui_commands SET status='consumed', consumed_at=datetime('now') WHERE id=?", (cmd_id,)
                )
                conn.commit()
            conn.close()
            return {
                "id": cmd_id,
                "command": command,
                "payload": json.loads(payload_str or "{}"),
                "created_at": created_at,
            }
        except Exception as e:
            return {"error": str(e)}

    def push_tui_command(self, command: str, payload: Dict = None, source: str = "tui") -> dict:
        """
        TUI → pousse un ordre vers le Hub (bouton cliqué).
        Utilisé par Nokido.py quand l'utilisateur clique sur Deploy/Test/Auto.
        """
        import json

        try:
            conn = sqlite3.connect(str(DB))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO tui_commands (source, command, payload) VALUES (?,?,?)",
                (source, command, json.dumps(payload or {})),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "command": command}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_auto_mode(self, enabled: bool) -> dict:
        """
        TUI AUTO switch → autorise le LLM à enchaîner apply_smart_patch
        sans confirmation humaine.
        """
        self.state.set(auto_mode=enabled)
        mode_str = "ACTIVÉ" if enabled else "DÉSACTIVÉ"
        self.tui_notify("Mode AUTO " + mode_str + " — patches sans confirmation", type="warning" if enabled else "info")
        return {"ok": True, "auto_mode": enabled}

    def is_auto_mode(self) -> bool:
        """Retourne True si le mode AUTO est activé depuis la TUI."""
        return bool(self.state.get().auto_mode)

    def dispatch_task(
        self,
        task: str,
        target: str = "auto",
        payload: Optional[Dict] = None,
    ) -> dict:
        """
        Point d'entrée unique pour @ci / @workflow.
        Routing auto : local (ring<=1) ou remote GitHub Actions (ring>=2).

        task   : "run-tests" | "run-heavy" | "lint" | "build" | "snapshot"
        target : "local" | "remote" | "auto"
        """
        state = self.state.get()

        if target == "auto":
            target = "local" if state.active_ring <= 1 else "remote"

        if target == "remote":
            """
            Routing remote par priorité :
              1. Woodpecker local  — si WOODPECKER_TOKEN présent (le plus rapide)
              2. Codeberg Actions  — si CODEBERG_TOKEN présent (privé, gratuit)
              3. GitHub Actions    — fallback final
            """
            import os

            common_payload = {
                **(payload or {}),
                "ring": str(state.active_ring),
                "collab_mode": str(state.collab_mode),
                "triggered_by": "LaForge-Hub",
                "task": task,
            }
            wp_token = get_secret("WOODPECKER_TOKEN") or ""
            cb_token = get_secret("CODEBERG_TOKEN") or ""

            if wp_token:
                result = self.services.dispatch_to_woodpecker(payload=common_payload)
                result["backend"] = "woodpecker"
            elif cb_token:
                result = self.services.dispatch_to_codeberg(
                    event_type="nokido_ci.yml",
                    payload=common_payload,
                )
                result["backend"] = "codeberg"
            else:
                result = self.services.dispatch_to_github(
                    event_type=task,
                    payload=common_payload,
                )
                result["backend"] = "github"

            result["target"] = "remote"
            return result

        # Local → TaskRegistry Hub
        try:
            from nokido_agent.app.forge_hub_client import hub as _hub

            if not _hub.alive():
                return {"ok": False, "error": "Hub non disponible", "target": "local"}
            action_map = {
                "run-tests": ("test_nr", "nr"),
                "run-heavy": ("test_nr", "nr"),
                "lint": ("test_module", "nokido_core"),
                "build": ("atlas_build", ""),
                "snapshot": ("make_snapshot", ""),
            }
            action, code = action_map.get(task, ("test_nr", "nr"))
            r = _hub.tool("run", {"action": action, "code": code})
            return {"ok": True, "target": "local", "task": task, "result": r}
        except Exception as e:
            return {"ok": False, "error": str(e), "target": "local"}


class ServiceManager:
    """
    Cycle de vie du Hub — abstrait par OS. Simple. Portable.

    Principe :
      - NSSM est une OPTION Windows, pas une dépendance
      - Toujours non-bloquant : Popen, jamais run()
      - Répond à Claude AVANT de couper le service (anti Kill-Switch)
      - Linux/RPi/macOS : systemd ou process direct
    """

    SERVICE_NAME = "NokidoHub"
    HUB_URL = "http://127.0.0.1:8766/health"

    def nssm_available(self) -> bool:
        """Vérifie si NSSM est accessible avec les droits suffisants."""
        import subprocess as sp

        try:
            r = sp.run(["nssm", "status", self.SERVICE_NAME], capture_output=True, text=True, timeout=3, errors="replace")
            # PermissionError NSSM retourne code 5 dans stderr
            return "Accès refusé" not in (r.stdout + r.stderr)
        except (FileNotFoundError, OSError):
            return False

    def restart_hub(self, delay_ms: int = 500) -> str:
        """
        Redémarre NokidoHub — indestructible sur Windows.

        Anti Kill-Switch :
          1. Retourne la confirmation à Claude IMMÉDIATEMENT
          2. Lance le restart dans un thread daemon après delay_ms
             → Claude reçoit la réponse AVANT que le Hub se coupe
          3. NSSM (Windows) ou systemd (Linux) selon OS
          4. Fallback trigger fichier si droits insuffisants

        delay_ms : délai avant le restart effectif (défaut 500ms)
                   Laisse le temps au Hub de flusher la réponse HTTP.
        """
        import os, subprocess as sp, threading

        def _do_restart() -> None:
            """Exécuté en thread daemon — APRÈS que la réponse est envoyée."""
            time.sleep(delay_ms / 1000.0)

            if os.name == "nt":
                try:
                    sp.Popen(
                        ["nssm", "restart", self.SERVICE_NAME],
                        stdout=sp.DEVNULL,
                        stderr=sp.DEVNULL,
                        creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
                    )
                except (FileNotFoundError, PermissionError):
                    # Fallback trigger si NSSM indisponible
                    trigger = ROOT / "sandbox" / "hub_restart.trigger"
                    trigger.parent.mkdir(parents=True, exist_ok=True)
                    trigger.write_text("restart:" + _dt.now().isoformat(), encoding="utf-8")
            elif os.name == "posix":
                try:
                    sp.Popen(
                        ["systemctl", "restart", "laforge-hub"],
                        stdout=sp.DEVNULL,
                        stderr=sp.DEVNULL,
                    )
                except (FileNotFoundError, PermissionError):
                    trigger = ROOT / "sandbox" / "hub_restart.trigger"
                    trigger.parent.mkdir(parents=True, exist_ok=True)
                    trigger.write_text("restart:" + _dt.now().isoformat(), encoding="utf-8")

        # Diagnostiquer le mode AVANT de lancer
        if os.name == "nt":
            mode = "NSSM" if self.nssm_available() else "trigger fichier"
        elif os.name == "posix":
            mode = "systemctl"
        else:
            return "OS non supporté: " + os.name

        # Lancer en thread daemon — retourne immédiatement
        threading.Thread(target=_do_restart, daemon=True, name="HubRestart").start()

        return (
            "NokidoHub restart planifié ("
            + mode
            + ")."
            + chr(10)
            + "Délai avant coupure : "
            + str(delay_ms)
            + "ms."
            + chr(10)
            + "Hub disponible sur :8766 dans ~5-8s."
            + chr(10)
            + "Vérifie avec run(action='hub_status')"
        )

    def _trigger_restart(self) -> str:
        """Fallback universel — fichier trigger pour watcher externe."""
        trigger = ROOT / "sandbox" / "hub_restart.trigger"
        trigger.parent.mkdir(parents=True, exist_ok=True)
        trigger.write_text("restart:" + _dt.now().isoformat(), encoding="utf-8")
        return (
            "Trigger déposé: sandbox/hub_restart.trigger"
            + chr(10)
            + "Prérequis: hub_restart_watcher.ps1 en cours (admin)."
            + chr(10)
            + "Setup: tools/create_restart_task.bat (une seule fois)."
        )

    def hub_status(self) -> dict:
        """Vérifie si le Hub répond — portable, pas de NSSM."""
        import urllib.request as ur, json as j, os

        token = get_secret("FORGE_MCP_TOKEN") or ""
        try:
            req = ur.Request(self.HUB_URL)
            if token:
                req.add_header("Authorization", "Bearer " + token)
            with ur.urlopen(req, timeout=3) as r:
                h = j.loads(r.read().decode())
            return {
                "running": True,
                "version": h.get("version", "?"),
                "auth": h.get("auth", "?"),
                "queue": h.get("queue_size", 0),
            }
        except Exception as e:
            return {"running": False, "error": str(e)}

    def push_file_to_github(
        self,
        local_path: str,
        repo_path: str,
        branch: str = "main",
        commit_msg: str = "",
        owner: str = "user",
        repo: str = "Nokido",
    ) -> dict:
        """
        Pousse un fichier local vers GitHub via API REST.
        Crée ou met à jour le fichier sur la branche cible.
        Utilisé pour déployer les workflows CI sur main.
        """
        import urllib.request as _ur
        import json as _j, os as _os, base64 as _b64

        gh_token = _os.environ.get("GITHUB_TOKEN", "")
        if not gh_token:
            return {"ok": False, "error": "GITHUB_TOKEN absent"}

        file_path = ROOT / local_path
        if not file_path.exists():
            return {"ok": False, "error": "Fichier absent: " + local_path}

        content_str = file_path.read_text(encoding="utf-8")
        encoded = _b64.b64encode(content_str.encode()).decode()
        api_url = "https://api.github.com/repos/" + owner + "/" + repo + "/contents/" + repo_path

        # GET SHA si le fichier existe déjà
        sha = ""
        try:
            req = _ur.Request(api_url + "?ref=" + branch)
            req.add_header("Authorization", "Bearer " + gh_token)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            with _ur.urlopen(req, timeout=10) as r:
                sha = _j.loads(r.read().decode()).get("sha", "")
        except Exception:
            pass

        # PUT
        body = {
            "message": commit_msg or "ci: update " + repo_path.split("/")[-1] + " [skip ci]",
            "content": encoded,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        req2 = _ur.Request(api_url, data=_j.dumps(body).encode(), method="PUT")
        req2.add_header("Authorization", "Bearer " + gh_token)
        req2.add_header("Accept", "application/vnd.github+json")
        req2.add_header("X-GitHub-Api-Version", "2022-11-28")
        req2.add_header("Content-Type", "application/json")

        try:
            with _ur.urlopen(req2, timeout=15) as r:
                resp = _j.loads(r.read().decode())
                commit = resp.get("commit", {}).get("sha", "?")[:8]
                return {"ok": True, "commit": commit, "branch": branch, "path": repo_path}
        except _ur.error.HTTPError as e:
            return {"ok": False, "error": "HTTP " + str(e.code) + ": " + e.read().decode()[:100]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def push_workflows_to_main(self) -> str:
        """Pousse nokido_ci.yml + nokido_ops.yml sur main pour activer le CI."""
        out = []
        for fname in ["nokido_ci.yml", "nokido_ops.yml"]:
            r = self.push_file_to_github(
                local_path=".github/workflows/" + fname,
                repo_path=".github/workflows/" + fname,
                branch="main",
                commit_msg="ci: add " + fname + " on main [skip ci]",
            )
            if r["ok"]:
                out.append("✅ " + fname + " → main commit=" + r["commit"])
            else:
                out.append("❌ " + fname + " : " + r.get("error", "?"))
        return chr(10).join(out)

    # ── Codeberg / Gitea API ──────────────────────────────────────────────────

    def _cb_api(self, method: str, endpoint: str, body: object = None) -> dict:
        """Appel API Codeberg/Gitea — portable, self-contained."""
        import urllib.request, urllib.error, json, os

        t = get_secret("CODEBERG_TOKEN") or ""
        if not t:
            return {"error": "CODEBERG_TOKEN absent"}
        req = urllib.request.Request("https://codeberg.org/api/v1" + endpoint, method=method)
        req.add_header("Authorization", "token " + t)
        req.add_header("Accept", "application/json")
        if body:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            return {"error": str(e.code), "detail": e.read().decode()[:300]}
        except Exception as e:
            return {"error": str(e)}

    def codeberg_status(self) -> dict:
        """Vérifie la connexion Codeberg et retourne l'état du repo."""
        user = self._cb_api("GET", "/user")
        if "error" in user:
            return {"ok": False, "error": user["error"]}
        repo = self._cb_api("GET", "/repos/user/Nokido")
        return {
            "ok": True,
            "user": user.get("login", "?"),
            "repo": repo.get("full_name", "?"),
            "private": repo.get("private", True),
            "clone": repo.get("clone_url", "?"),
            "branches": repo.get("default_branch", "?"),
        }

    def push_file_to_codeberg(
        self,
        local_path: str,
        repo_path: str,
        branch: str = "alpha",
        commit_msg: str = "",
        owner: str = "user",
        repo: str = "Nokido",
    ) -> dict:
        """
        Pousse un fichier vers Codeberg via API Gitea.
        - Fichier existant → PUT avec SHA
        - Nouveau fichier  → POST avec new_branch (Gitea)
        """
        import base64

        file_path = ROOT / local_path
        if not file_path.exists():
            return {"ok": False, "error": "Fichier absent: " + local_path}
        content_str = file_path.read_text(encoding="utf-8")
        encoded = base64.b64encode(content_str.encode()).decode()
        endpoint = "/repos/" + owner + "/" + repo + "/contents/" + repo_path
        fname = repo_path.split("/")[-1]
        msg = commit_msg or "ci: add " + fname

        # Vérifier si le fichier existe déjà
        existing = self._cb_api("GET", endpoint + "?ref=" + branch)

        if "sha" in existing:
            # Fichier existant → PUT avec SHA
            body = {"message": msg, "content": encoded, "branch": branch, "sha": existing["sha"]}
            method = "PUT"
        else:
            # Nouveau fichier → POST avec new_branch
            body = {"message": msg, "content": encoded, "new_branch": branch}
            method = "POST"

        r = self._cb_api(method, endpoint, body)
        if isinstance(r, dict) and r.get("error"):
            return {"ok": False, "error": r["error"], "detail": r.get("detail", "")}
        commit = r.get("commit", {}).get("sha", "?")[:8] if isinstance(r.get("commit"), dict) else "ok"
        return {"ok": True, "commit": commit, "branch": branch, "path": repo_path}

    def dispatch_to_codeberg(
        self,
        event_type: str,
        payload: Optional[Dict] = None,
        owner: str = "user",
        repo: str = "Nokido",
        ref: str = "alpha",
    ) -> dict:
        """
        Déclenche un workflow Gitea Actions via workflow_dispatch.
        Équivalent du repository_dispatch GitHub.

        event_type : nom du workflow (ex: 'nokido_ci.yml')
        payload    : inputs passés au workflow
        """
        body = {
            "ref": ref,
            "inputs": payload or {},
        }
        endpoint = "/repos/" + owner + "/" + repo + "/actions/workflows/" + event_type + "/dispatches"
        r = self._cb_api("POST", endpoint, body)
        if "error" in r and r["error"] not in ("", None):
            return {"ok": False, "error": r["error"], "detail": r.get("detail", "")}
        return {"ok": True, "workflow": event_type, "ref": ref}

    def dispatch_to_woodpecker(
        self,
        repo: str = "user/Nokido",
        branch: str = "alpha",
        payload: Optional[Dict] = None,
    ) -> dict:
        """
        Déclenche un pipeline Woodpecker CI via API REST.
        L'agent Woodpecker local exécute le .woodpecker.yml en mode local backend.

        Endpoint Woodpecker : POST /api/repos/{repo}/pipelines
        """
        import urllib.request, urllib.error, json, os

        wp_server = os.environ.get("WOODPECKER_SERVER", "http://127.0.0.1:8000")
        wp_token = get_secret("WOODPECKER_TOKEN") or ""

        if not wp_token:
            return {"ok": False, "error": "WOODPECKER_TOKEN absent dans Nokido.env"}

        url = wp_server.rstrip("/") + "/api/repos/" + repo + "/pipelines"
        body = {
            "branch": branch,
            "variables": {**(payload or {}), "triggered_by": "LaForge-Hub", "ring": str(self.__class__.__name__)},
        }

        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", "Bearer " + wp_token)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read().decode())
            return {
                "ok": True,
                "pipeline": resp.get("number", "?"),
                "status": resp.get("status", "?"),
                "url": wp_server + "/" + repo + "/" + str(resp.get("number", "?")),
            }
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": "HTTP " + str(e.code), "detail": e.read().decode()[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def woodpecker_status(self) -> dict:
        """Vérifie si l'agent Woodpecker est joignable."""
        import urllib.request, json, os

        wp_server = os.environ.get("WOODPECKER_SERVER", "http://127.0.0.1:8000")
        wp_token = get_secret("WOODPECKER_TOKEN") or ""
        try:
            req = urllib.request.Request(wp_server + "/api/info")
            if wp_token:
                req.add_header("Authorization", "Bearer " + wp_token)
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode())
            return {"ok": True, "version": data.get("version", "?"), "url": wp_server}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": wp_server}

    def push_workflows_to_codeberg(self) -> str:
        """Pousse les workflows Gitea Actions + requirements-ci.txt sur Codeberg."""
        files = [
            ("requirements-ci.txt", "requirements-ci.txt"),
            (".gitea/workflows/nokido_ci.yml", ".gitea/workflows/nokido_ci.yml"),
            (".gitea/workflows/nokido_ops.yml", ".gitea/workflows/nokido_ops.yml"),
        ]
        out = []
        for local, remote in files:
            r = self.push_file_to_codeberg(local, remote, branch="alpha")
            out.append(
                ("✅" if r["ok"] else "❌")
                + " "
                + local
                + (" commit=" + r.get("commit", "?") if r["ok"] else " " + r.get("error", "?"))
            )
        return chr(10).join(out)

    def nssm_status(self) -> str:
        """Statut NSSM — Windows uniquement, optionnel."""
        import os, subprocess as sp

        if os.name != "nt":
            return "N/A (non-Windows)"
        try:
            r = sp.run(["nssm", "status", self.SERVICE_NAME], capture_output=True, text=True, timeout=5, errors="replace")
            return (r.stdout + r.stderr).strip() or "OK"
        except FileNotFoundError:
            return "NSSM non installé"
        except Exception as e:
            return "Erreur: " + str(e)

    def dispatch_to_github(
        self,
        event_type: str,
        payload: Optional[Dict] = None,
        owner: str = "user",
        repo: str = "Nokido",
    ) -> dict:
        """
        Remote Dispatch — envoie un repository_dispatch à GitHub.
        Permet de déléguer une tâche lourde au Cloud depuis le Hub local.

        event_type : identifiant de l'action (ex: 'run-heavy-tests', 'deploy-edge')
        payload    : données libres passées au workflow GitHub Actions

        Retourne {"ok": True, "event": event_type} ou {"ok": False, "error": ...}
        """
        import urllib.request as _ur
        import json as _j, os as _os

        gh_token = _os.environ.get("GITHUB_TOKEN", "")
        if not gh_token:
            return {"ok": False, "error": "GITHUB_TOKEN absent"}

        url = "https://api.github.com/repos/" + owner + "/" + repo + "/dispatches"
        body = {
            "event_type": event_type,
            "client_payload": payload or {},
        }
        req = _ur.Request(url, data=_j.dumps(body).encode(), method="POST")
        req.add_header("Authorization", "Bearer " + gh_token)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("Content-Type", "application/json")

        try:
            with _ur.urlopen(req, timeout=15) as r:
                # 204 No Content = succès GitHub
                return {"ok": True, "event": event_type, "status": r.status}
        except _ur.error.HTTPError as e:
            body_err = e.read().decode()[:200]
            return {"ok": False, "error": "HTTP " + str(e.code) + ": " + body_err}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# =============================================================================
# SINGLETON
# =============================================================================


# =============================================================================
# APPLY SMART PATCH — outil de modification chirurgicale
# =============================================================================


def learn_from_error(error_msg: str, context: str = "", domain: str = "systeme") -> dict:
    """
    Ancre une erreur dans le RAG + logs/lessons_learned.md.
    Délègue à forge_self_correction.anchor_error.
    À appeler IMMÉDIATEMENT dans chaque except.
    """
    try:
        from nokido_agent.app.forge_self_correction import anchor_error as _ae

        return _ae(error_msg, context=context, domain=domain)
    except Exception:
        # Fallback direct SQLite si forge_self_correction indisponible
        import sqlite3, json

        text = "ERREUR : " + error_msg[:300] + chr(10) + "CONTEXTE : " + context[:200]
        try:
            conn = sqlite3.connect(str(DB))
            conn.execute("PRAGMA journal_mode=WAL")
            # 2026-09-12 : sans `id` (TEXT PRIMARY KEY) la clef restait NULLE.
            from nokido_agent.app.forge_db_path import chunk_id as _cid  # type: ignore

            _src = "session:" + _dt.now().strftime("%Y-%m-%d") + ":error_learning"
            conn.execute(
                "INSERT INTO rag_chunks (id, text, source, domain, role_hint, meta) "
                "VALUES (?,?,?,?,?,?)",
                (
                    _cid(_src, text),
                    text,
                    _src,
                    domain,
                    "rule",
                    json.dumps({"ring": 1, "trust_score": 0.9, "auto_learned": True}),
                ),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "learned": error_msg[:60]}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


def apply_smart_patch(
    file_path: str,
    old: str,
    new: str,
    dry_run: bool = False,
) -> dict:
    """
    Remplace old par new dans file_path — une seule occurrence.
    Valide la syntaxe Python avant d'écrire.
    Retourne {"ok": bool, "line": int|None, "error": str|None}.

    Protocole Self-Correction :
      - Preflight check avant patch
      - learn_from_error si SyntaxError
      - anchor_solution si succès (premier patch sur ce fichier)
    """
    import ast as _ast

    # Preflight check
    try:
        from nokido_agent.app.forge_self_correction import preflight_check as _pfc

        warning = _pfc("apply_smart_patch", file_path)
        if warning:
            import logging

            logging.getLogger("Nokido.Core").debug(warning)
    except Exception:
        pass
    p = ROOT / file_path
    if not p.exists():
        return {"ok": False, "error": "fichier absent: " + file_path}
    src = p.read_text(encoding="utf-8")
    if old not in src:
        return {"ok": False, "error": "pattern non trouvé dans " + file_path}
    count = src.count(old)
    if count > 1:
        return {"ok": False, "error": str(count) + " occurrences — sois plus précis"}
    patched = src.replace(old, new, 1)
    if p.suffix == ".py":
        try:
            _ast.parse(patched)
        except SyntaxError as e:
            return {"ok": False, "error": "SyntaxError L" + str(e.lineno) + ": " + str(e.msg)}
    if dry_run:
        return {"ok": True, "dry_run": True, "lines": len(patched.split(chr(10)))}
    p.write_text(patched, encoding="utf-8")
    line = src[: src.index(old)].count(chr(10)) + 1
    return {"ok": True, "line": line, "file": file_path}


_core_instance: Optional[CoreBridge] = None
_core_lock = threading.Lock()


def get_core() -> CoreBridge:
    """Singleton thread-safe — Hub, TUI et Nokido.py utilisent get_core()."""
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = CoreBridge()
    return _core_instance


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    core = get_core()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "status":
            print(json.dumps(core.status(), indent=2, ensure_ascii=False))
        elif cmd == "collab" and len(sys.argv) > 2:
            print("Mode:", core.tui_set_collab(int(sys.argv[2])))
        elif cmd == "ring" and len(sys.argv) > 2:
            print("Ring:", core.tui_set_ring(int(sys.argv[2])))
        elif cmd == "search" and len(sys.argv) > 2:
            chunks = core.rag.search(" ".join(sys.argv[2:]), k=3)
            for c in chunks:
                print("[" + c["domain"] + "] [" + c.get("_mode", "?") + "] " + c["text"][:100])
        elif cmd == "prompt":
            print(core.prompts.get_prompt("system_context")["content"])
        elif cmd == "hub_status":
            print(json.dumps(core.services.hub_status(), indent=2))
        elif cmd == "hub_restart":
            print(core.services.restart_hub())
    else:
        print(json.dumps(core.status(), indent=2, ensure_ascii=False))
