# -*- coding: utf-8 -*-
"""
forge_byte_router.py — Middleware Hub._tool_call AVANT dispatch
==============================================================
Session 5 — 2026-04-27
ADR Gemini 2026-04-15 : middleware dans Hub._tool_call, pas broker séparé.
Rôles : logging structuré, rate-limit par agent, rewrite d'args, ts injection.
"""

from __future__ import annotations
import logging, time, threading

log = logging.getLogger("forge.byte_router")


def _ecrire_console(texte: str) -> None:
    """Decoration TUI qui ne peut PAS bloquer la boucle d'evenements du hub.

    Mesure 2026-09-18 18:25:17 : un `print(..., flush=True)` a cet endroit a gele
    l'event loop 60 s et fait tuer le hub par son propre garde. stdout est un
    tuyau draine par le superviseur, mesure a 7 min de retard le meme jour.

    On delegue a `forge_logging.ecrire_sans_bloquer` (file bornee, fil separe,
    pertes comptees). Si ce module est indisponible, on se TAIT plutot que de
    rebloquer : un affichage manquant se corrige, un hub mort se releve a la main.
    """
    try:
        from app.forge_logging import ecrire_sans_bloquer
    except Exception:  # noqa: BLE001
        try:
            from forge_logging import ecrire_sans_bloquer  # type: ignore
        except Exception:  # noqa: BLE001 — muet-ok : aucun canal sur, on se tait
            return
    ecrire_sans_bloquer(texte)

_CALL_COUNTS: dict = {}
_RATE_LIMITS: dict = {}  # tool -> max calls/min (configurable)

# ── Poll réflexe — déclenché par passage d action, pas par timer ──────────
# Analogie : nœud ganglionnaire — intercepte le signal en transit,
# vérifie les notifications pendantes sans bloquer le flux principal.
# Pas de thread séparé : le poll se glisse entre deux actions.

_POLL_STATE = {
    "call_count": 0,  # appels depuis dernier poll
    "last_poll_ts": 0.0,  # timestamp dernier poll
    "poll_every_n": 5,  # poll toutes les N actions (ajustable)
    "poll_min_gap": 10.0,  # gap minimum entre deux polls (secondes)
    "notifications": [],  # buffer notifs reçues pour affichage TUI
}
_POLL_LOCK = threading.Lock()


def _should_poll(tool_name: str) -> bool:
    """
    Décide si un poll est pertinent à ce tick d action.
    Critères (OR) :
    - N actions écoulées depuis dernier poll
    - Outil "lourd" (write/run) → poll immédiat
    - Gap minimum respecté
    """
    with _POLL_LOCK:
        _POLL_STATE["call_count"] += 1
        n = _POLL_STATE["call_count"]
        gap = time.time() - _POLL_STATE["last_poll_ts"]
        every = _POLL_STATE["poll_every_n"]
        mingap = _POLL_STATE["poll_min_gap"]
        heavy = tool_name in ("write", "run", "trigger_autonomous_evolution")
        return gap >= mingap and (n % every == 0 or heavy)


def _do_reactive_poll(agent: str) -> None:
    """
    Poll non bloquant en thread daemon — ne ralentit pas l action principale.
    Résultat affiché dans TUI via print + stocké dans _POLL_STATE["notifications"].
    """

    def _poll():
        try:
            import sys as _s, os as _o

            _app = _o.path.dirname(__file__)
            if _app not in _s.path:
                _s.path.insert(0, _app)
            # Appel direct au state_manager (pas via MCP — évite récursion)
            from nokido_agent.app.forge_state_manager import get_state_manager  # type: ignore

            sm = get_state_manager()
            notifs = sm.drain_notifications()
            with _POLL_LOCK:
                _POLL_STATE["last_poll_ts"] = time.time()
                _POLL_STATE["call_count"] = 0
            if notifs:
                for n in notifs:
                    msg = f"[POLL→{agent}] {n.get('source', '?')}: {str(n.get('message', ''))[:120]}"
                    _ecrire_console(f"\033[93m{msg}\033[0m\n")  # jaune TUI
                    log.info(msg)
                    with _POLL_LOCK:
                        _POLL_STATE["notifications"].append(
                            {
                                "ts": time.time(),
                                "source": n.get("source"),
                                "msg": n.get("message", "")[:200],
                            }
                        )
            else:
                log.debug("[ByteRouter] poll: 0 notifications")
        except Exception as _e:
            log.debug("[ByteRouter] poll skip: %s", _e)

    t = threading.Thread(target=_poll, name="ByteRouterPoll", daemon=True)
    t.start()


def get_pending_notifications() -> list:
    """API publique — retourne les notifs bufferisées depuis le dernier poll."""
    with _POLL_LOCK:
        notifs = list(_POLL_STATE["notifications"])
        _POLL_STATE["notifications"].clear()
    return notifs


def configure_poll(every_n: int = 5, min_gap_s: float = 10.0) -> None:
    """Ajuste la fréquence du poll réflexe."""
    with _POLL_LOCK:
        _POLL_STATE["poll_every_n"] = every_n
        _POLL_STATE["poll_min_gap"] = min_gap_s
    log.info("[ByteRouter] poll configuré: every_n=%d min_gap=%.1fs", every_n, min_gap_s)


class ByteRouterMiddleware:
    @staticmethod
    async def process(tool_name: str, args: dict, agent: str = "INCONNU") -> tuple:
        """
        Retourne (tool_name, args) — potentiellement modifiés.
        Lève PermissionError si rate-limit dépassé.
        Appeler AVANT Hub._dispatch().

        Le défaut est `INCONNU`, jamais le nom d'un agent réel. Il valait
        `"CLAUDE"` — signalé le 2026-09-18 comme une élévation de privilèges par
        une chasse AI-AND-LLM. Vérification faite, ce n'en est PAS une : le seul
        appelant (`nokido_hub._tool_call`) passe toujours l'agent résolu par le
        videur, ce middleware est enveloppé d'un `except: pass` fail-open donc
        il ne refuse rien, et `_br_agent` qu'il injecte n'a AUCUN lecteur dans
        le dépôt. Le gouverneur est `forge_hub_gate`, en aval, fail-closed.

        Ce qui restait est plus petit et bien réel : un défaut qui DÉGUISE une
        absence d'identité en identité connue. Un appelant sans agent voyait ses
        appels comptés au quota de CLAUDE et tracés sous son nom — la confusion
        `UNKNOWN` ≠ un nom, que la constitution sémantique interdit. Ici l'agent
        ne sert qu'au comptage de rate-limit et à la trace, donc le renommer n'a
        aucun effet sur le chemin de production : il rend seulement lisible ce
        qu'on ne sait pas.
        """
        ts = time.time()

        # Comptage par agent
        key = f"{agent}:{tool_name}"
        _CALL_COUNTS[key] = _CALL_COUNTS.get(key, 0) + 1
        _CALL_COUNTS[agent] = _CALL_COUNTS.get(agent, 0) + 1

        # Log structuré + affichage temps réel chemin de routage
        log.info(
            "[ByteRouter] agent=%s tool=%s args_keys=%s count=%d",
            agent,
            tool_name,
            list(args.keys()),
            _CALL_COUNTS[agent],
        )
        # JAMAIS de `print(flush=True)` ici : ce code tourne DANS la boucle
        # d'evenements du hub, a chaque appel d'outil. Le 2026-09-18 a 18:25:17
        # cette ligne exacte a gele la boucle 60 s et fait tuer le hub par son
        # propre garde (`WEDGE KILL`, dump `faulthandler` a l'appui) : stdout est
        # un tuyau draine par le superviseur, mesure avec 7 min de retard le meme
        # jour, et un tuyau plein fait attendre `flush()`.
        _ecrire_console(f"\033[36m[→ {agent}:{tool_name}]\033[0m ")

        # ── Poll réflexe au tick d action ────────────────────────────────────
        # Déclenché sur passage, pas sur timer — nœud ganglionnaire.
        if _should_poll(tool_name):
            _do_reactive_poll(agent)
        # ─────────────────────────────────────────────────────────────────────

        # ── Capture mémoire épisodique (forge_conversation_logger) ─────────
        # Chaque appel MCP signifiant est tracé dans conversation_log + RAG
        # Capturer : messages entrants (write/run avec contenu), résultats outils
        _content_to_log = None
        if tool_name in ("write",) and args.get("content"):
            _content_to_log = f"[write:{args.get('path', '?')}] {str(args['content'])[:300]}"
        elif tool_name in ("run",) and args.get("code"):
            _content_to_log = f"[run:{args.get('action', '?')}] {str(args['code'])[:300]}"
        elif tool_name in ("query",) and args.get("sql"):
            _content_to_log = f"[query] {str(args['sql'])[:200]}"
        if _content_to_log:
            try:
                import os as _os, sys as _sys

                _app = _os.path.dirname(__file__)
                if _app not in _sys.path:
                    _sys.path.insert(0, _app)
                from nokido_agent.app.forge_conversation_logger import log_turn as _log_turn
                import asyncio as _aio, time as _t

                _sid = f"auto_{agent}_{int(_t.time()) // 3600}"
                # Offload SQLite sync hors event-loop unique — sinon wedge hub (RCA 2026-07-02)
                await _aio.to_thread(_log_turn, session_id=_sid, role="tool_call", content=_content_to_log, agent=agent)
            except Exception as _le:
                log.debug("[ByteRouter] conv_log skip: %s", _le)
        # ─────────────────────────────────────────────────────────────────────

        # ── Anticipation sémantique (arc réflexe) ────────────────────────────
        # Si un message est présent dans les args, on anticipe les outils
        # probables AVANT que le LLM ait à les déduire lui-même.
        # Utilise le keyword matching de _CAPABILITY_TRIGGERS (zéro token,
        # zéro réseau, ~0.1ms). Compatible avec le Prompt Caching car
        # l'injection se fait dans user message, pas dans le system prompt.
        _msg = str(args.get("message", "") or args.get("prompt", "") or args.get("task", ""))
        if _msg and len(_msg) > 5:
            try:
                import sys as _sys, os as _os

                _app = str(_os.path.join(_os.path.dirname(__file__)))
                if _app not in _sys.path:
                    _sys.path.insert(0, _app)
                from nokido_agent.app.forge_cognitive_router import _anticipate_tools

                _anticipated = _anticipate_tools(_msg)
                if _anticipated:
                    args = dict(args)  # copy pour ne pas muter l'original
                    args["_anticipated_tools"] = _anticipated
                    log.info("[ByteRouter] anticipated=%s for agent=%s", _anticipated, agent)
            except Exception as _e:
                log.debug("[ByteRouter] anticipation skip: %s", _e)
        # ─────────────────────────────────────────────────────────────────────

        # Rate-limit optionnel
        limit = _RATE_LIMITS.get(tool_name)
        if limit and _CALL_COUNTS.get(key, 0) > limit:
            raise PermissionError(f"[ByteRouter] Rate-limit: {agent} depasse {limit} appels/min sur {tool_name}")

        # Injecter ts et agent pour traçabilité
        args = dict(args)
        args.setdefault("_br_ts", ts)
        args.setdefault("_br_agent", agent)

        return tool_name, args

    @staticmethod
    def set_rate_limit(tool_name: str, max_per_min: int):
        _RATE_LIMITS[tool_name] = max_per_min

    @staticmethod
    def stats() -> dict:
        return dict(_CALL_COUNTS)


# ─────────────────────────────────────────────────────────────────────────────
# ByteDataRouter — détection sentinel sur flux bytes bruts
# Moelle épinière : intercepte avant tout parsing applicatif.
# Sentinels = \xc2\xa7 (UTF-8 §) + 4 ASCII majuscules = 6 bytes total.
# ─────────────────────────────────────────────────────────────────────────────


class ByteDataRouter:
    SENTINEL_MAP = {
        b"\xc2\xa7PING": "ping",
        b"\xc2\xa7EXEC": "exec",
        b"\xc2\xa7ROUT": "route",
        b"\xc2\xa7FAST": "fast",
        b"\xc2\xa7COST": "cost",
        b"\xc2\xa7STAT": "status",
        b"\xc2\xa7STRE": "stream",
        b"\xc2\xa7RESE": "reset",
        b"\xc2\xa7SECU": "secure",
        b"\xc2\xa7UPDA": "update",
        b"\xc2\xa7MONI": "monitor",
        b"\xc2\xa7BACK": "backup",
        b"\xc2\xa7ANAL": "analyze",
    }

    def __init__(self, ring: int = 2):
        self.ring = ring

    async def peek_and_route(self, data: bytes) -> tuple[str, bytes]:
        if len(data) < 6:
            return ("raw", data)
        prefix = data[:6]
        for sentinel, action in self.SENTINEL_MAP.items():
            if prefix == sentinel:
                return (action, data[len(sentinel) :])
        try:
            import json

            json.loads(data.decode("utf-8"))
            return ("json", data)
        except (ValueError, UnicodeDecodeError):
            pass
        return ("raw", data)

    def peek_and_route_sync(self, data: bytes) -> tuple[str, bytes]:
        import asyncio

        return asyncio.run(self.peek_and_route(data))
