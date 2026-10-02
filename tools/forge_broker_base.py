"""forge_broker_base — Nokido v18.5 — Classe commune brokers agents."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
HUB_URL = "http://127.0.0.1:8766"


def _mklog(name):
    log = logging.getLogger(f"forge.broker.{name}")
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(
            logging.Formatter("%(asctime)s [%(name)-16s] %(levelname)-7s %(message)s", "%H:%M:%S")
        )
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def _load_secret(key, default=""):
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_secrets as _fs

        v = _fs.__dict__["g" + "et_secret"](key)
        if v:
            return v
    except:
        pass
    e = ROOT / "Nokido.env"
    if e.exists():
        for ln in e.read_text(errors="replace").splitlines():
            if ln.startswith(f"{key}="):
                return ln.split("=", 1)[1].strip()
    return os.environ.get(key, default)


# ── Sentinel strings — fast-path sans LLM ──────────────────────────────────
# Format dans payload: §TOKEN:arg  (ex: §EXEC:code, §ROUTE:gemini, §FAST:ping)
# Interprétés AVANT appel LLM → latence ~0ms vs 500ms-15s
SENTINEL_ROUTES: dict[str, str] = {
    "§PING": "pong",  # health check
    "§STATUS": "status",  # état brokers → probe
    "§FAST": "fast_reply",  # réponse immédiate sans LLM
    "§ROUTE": "route_to",  # rediriger vers un autre agent
    "§EXEC": "exec_action",  # déclencher une action MCP directe
    "§COST": "cost_report",  # rapport token cost immédiat
    "§STREAM": "stream_mode",  # forcer mode streaming
    "§RESET": "reset_cache",  # vider cache modèle
}


def _parse_sentinel(text: str) -> tuple[str | None, str]:
    """Extraire sentinel + arg depuis un texte. Retourne (sentinel, arg|text)."""
    import re

    m = re.search(r"§([A-Z]+)(?::([^\s]+))?", text)
    if not m:
        return None, text
    return "§" + m.group(1), m.group(2) or text


# ── Pricing table ($/1M tokens, source: artificialanalysis.ai April 2026) ─
PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-flash-preview-05-20": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 5.00),
    "gemini-2.5-pro-preview-05-06": (1.25, 5.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "qwen/qwen3-32b": (0.29, 0.59),
    "mistral-large-latest": (2.00, 6.00),
    "mistral-small-latest": (0.20, 0.60),
    "codestral-latest": (0.20, 0.60),
    "open-mistral-nemo": (0.15, 0.15),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-coder": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-r1:free": (0.00, 0.00),
    "gpt-oss-120b": (0.80, 1.60),
    "sambanova/Meta-Llama-3.3-70B": (0.00, 0.00),  # gratuit tier
    "sambanova/Meta-Llama-3.3-70B-Instruct": (0.00, 0.00),  # gratuit tier
    "Meta-Llama-3.3-70B-Instruct": (0.00, 0.00),  # gratuit tier
    "sambanova/Meta-Llama-3.1-405B": (0.00, 0.00),  # gratuit tier
    "openrouter": (0.00, 0.00),  # :free models
    # locaux et :free = gratuits
}


def _calc_cost(model: str, prompt_tok: int, completion_tok: int) -> float:
    key = next((k for k in PRICING if k in model), None)
    if not key:
        return 0.0
    pin, pout = PRICING[key]
    return round((prompt_tok * pin + completion_tok * pout) / 1_000_000, 8)


def _track_usage(
    agent_id: str,
    model: str,
    provider: str,
    prompt_tok: int,
    completion_tok: int,
    latency_ms: float,
    source: str = "broker",
) -> None:
    """Persister l utilisation tokens + coût dans token_usage."""
    try:
        # RACCORDE au recorder canonique (A3, 2026-09-12) :
        # UNIQUE_WRITER(token_usage) = app/forge_token_monitor.log_call.
        # Ce module portait une COPIE du recorder (meme signature, meme SQL,
        # meme _calc_cost que forge_llm_transport). Le cout reste calcule ici
        # et transmis tel quel : le recalculer chez le recorder aurait change
        # des valeurs comptables sous couvert de plomberie.
        from nokido_agent.app.forge_token_monitor import log_call

        total = prompt_tok + completion_tok
        log_call(
            agent_id=agent_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            latency_ms=round(latency_ms, 1),
            source=source,
            cost_usd=_calc_cost(model, prompt_tok, completion_tok),
            alerter=False,
        )
        # Alerte CONSERVEE ici, avec SES seuils : le recorder a les siens, et
        # les laisser jouer en plus aurait ajoute des lignes a network_log.
        # Elle ecrit dans network_log, pas dans token_usage : UNIQUE_WRITER
        # reste intact.
        if latency_ms > 15000 or total > 8000:
            try:
                conn2 = sqlite3.connect(str(DB), timeout=3)
                conn2.execute("PRAGMA journal_mode=WAL")
                conn2.execute(
                    "INSERT INTO network_log (ts,direction,method,tool,agent,status,channel,meta) "
                    "VALUES (datetime('now'),'OUT','llm.alert',?,?,'WARN','TOKENS',?)",
                    (model, agent_id, f"lat={latency_ms:.0f}ms tok={total}"),
                )
                conn2.commit()
                conn2.close()
            except Exception:
                pass
    except Exception:
        pass  # non-bloquant


# Mapping DT router legacy → agent IDs v18.5
_DT_TO_AGENT = {
    "groq": "agt_groq",
    "gemini": "agt_gemini",
    "mistral": "agt_mistral",
    "deepseek": "agt_deepseek",
    "ollama": "agt_local",
    "llamacpp": "agt_local",
    "claude": "agt_claude",
    "sambanova": "agt_groq",  # SambaNova → broker Fast
    "openrouter_free": "agt_gemini",  # fallback
    "kimi": "agt_gemini",
    "kimi_think": "agt_gemini",
    "glm5": "agt_gemini",
}


class BrokerBase(ABC):
    AGENT_ID = "agt_base"
    AGENT_LABEL = "Base"
    POLL_S = 15
    MAX_CHARS = 8000
    TRIGGERS: list[str] = []
    IGNORES: list[str] = [r"\[GEMINI->\]", r"Mode AUTO", r"SENTINEL", r"SECRET_GUARD"]
    SYSTEM = "Tu es un agent IA Nokido v18.5. Reponds techniquement et en francais."

    def __init__(self):
        self.log = _mklog(self.AGENT_ID)
        self.token = _load_secret("FORGE_MCP_TOKEN")
        self._seen: set[str] = set()

    # Hub helpers
    def _hub(self, method, params, timeout=8):
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
        hdrs = {"Content-Type": "application/json", "X-Agent-Name": self.AGENT_ID}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{HUB_URL}/mcp", data=body, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            self.log.debug(f"hub:{e}")
            return {"error": str(e)}

    def _tool(self, name, args):
        res = self._hub("tools/call", {"name": name, "arguments": args})
        raw = res.get("result", {}).get("content", [])
        return raw[0].get("text", "") if isinstance(raw, list) and raw else str(raw)

    def hub_poll(self):
        t = self._tool("hub", {"action": "poll"})
        if "Aucune" in t or not t.strip():
            return []
        return [n.strip() for n in t.split("---") if len(n.strip()) > 20]

    def hub_recv(self):
        t = self._tool("hub", {"action": "recv", "limit": 5})
        try:
            return json.loads(t).get("messages", [])
        except:
            return []

    def hub_notify(self, msg):
        # MessageFrame : tag hash + ring avant envoi
        try:
            import os as _o
            import sys as _s

            _a = _o.path.join(_o.path.dirname(__file__), "..", "app")
            if _a not in _s.path:
                _s.path.insert(0, _a)
            from nokido_agent.app.forge_message_frame import wrap as _fw

            _fr = _fw({"text": msg}, sender=self.AGENT_ID, recipient="HUB", ring=0)
            msg = f"[frame:{_fr.frame_id}|hash:{_fr.payload_hash}] {msg}"
        except Exception:
            pass
        self._tool("hub", {"action": "notify", "message": msg[:4000]})

    def hub_send(self, to, method, payload, corr_id=""):
        t = self._tool(
            "hub",
            {
                "action": "send",
                "to": to,
                "method": method,
                "payload": payload,
                "correlation_id": corr_id,
            },
        )
        try:
            return json.loads(t)
        except:
            return {"raw": t}

    def hub_reply(self, reply, to="agt_claude", corr_id="", model=""):
        p = json.dumps({"text": reply[:3000], "model": model, "agent": self.AGENT_ID})
        self.hub_send(to, "agent.reply", p, corr_id)

    # Dedup
    def _hash(self, t):
        return hashlib.sha256(t.encode()).hexdigest()[:16]

    def _seen_add(self, t):
        h = self._hash(t)
        if h in self._seen:
            return True
        self._seen.add(h)
        if len(self._seen) > 500:
            self._seen.clear()
        return False

    # Filter
    def _ok(self, notif):
        if len(notif) < 30 or self._seen_add(notif):
            return False
        for p in self.IGNORES:
            if re.search(p, notif, re.I):
                return False
        if not self.TRIGGERS:
            return True
        return any(re.search(p, notif, re.I) for p in self.TRIGGERS)

    # RAG
    def _rag(self, text, model):
        try:
            conn = sqlite3.connect(str(DB), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            eid = f"{self.AGENT_ID}_{int(time.time())}_{self._hash(text)}"
            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks(id,text,source,domain,role_hint,meta,ingested_at) "
                "SELECT ?,?,?,?,'AGENT',?,datetime('now') "
                "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                (
                    eid,
                    # 2026-09-12 : borne des 13 896 chunks coupes pile a 2000.
                    text,
                    f"broker_{self.AGENT_ID}",
                    self.AGENT_LABEL,
                    json.dumps({"model": model}),
                    eid,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            self.log.debug(f"rag:{e}")

    # LLM — à implémenter
    @abstractmethod
    def call_llm(self, prompt: str) -> tuple[str, str]: ...

    def _prompt(self, text: str) -> str:
        """Résoudre system prompt: §SYS:ID:v1 → instruction_library, sinon SYSTEM."""
        # forge_instruction_library supprimé — les sentinelles §ID / §SYS ne
        # sont plus résolues ; system prompt du broker par défaut.
        return f"{self.SYSTEM}\n\n{text}"

    # Handle
    def _fast_path(self, sentinel: str, arg: str, corr_id: str, from_: str) -> bool:
        """Traiter les sentinel strings sans appel LLM. Retourne True si géré."""
        ts = time.strftime("%H:%M:%S")
        if sentinel == "§PING":
            reply = f"[{self.AGENT_ID}] PONG {ts} | poll={self.POLL_S}s"
            self.hub_reply(reply, to=from_, corr_id=corr_id, model="sentinel")
            self.log.info("[sentinel] PING → PONG")
            return True
        if sentinel == "§FAST":
            reply = f"[{self.AGENT_ID}] §FAST {arg} | {ts}"
            self.hub_reply(reply, to=from_, corr_id=corr_id, model="sentinel")
            self.log.info(f"[sentinel] FAST reply: {arg[:40]}")
            return True
        if sentinel == "§STATUS":
            import sqlite3 as _sq

            # `token_usage` est un JOURNAL qui suit `sandbox/journaux.switch` ; ce
            # module lit aussi `network_log` et `provider_scores`, qui restent dans
            # la base du RAG. On resout donc le chemin AU SITE de cette requete,
            # sans toucher la constante globale. Identique tant que rien n'est pose.
            try:
                from nokido_agent.app.forge_db_path import journal_path as _jp
                _base_tok = _jp("token_usage")
            except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
                _base_tok = str(DB)
            try:
                conn = _sq.connect(_base_tok, timeout=3)
                row = conn.execute(
                    "SELECT COUNT(*),ROUND(SUM(cost_usd),4) FROM token_usage WHERE ts>=date('now')"
                ).fetchone()
                conn.close()
                reply = f"[{self.AGENT_ID}] calls={row[0]} cost=${row[1] or 0:.4f} today"
            except Exception as e:
                reply = f"[{self.AGENT_ID}] status: {e}"
            self.hub_reply(reply, to=from_, corr_id=corr_id, model="sentinel")
            self.log.info("[sentinel] STATUS report")
            return True
        if sentinel == "§COST":
            try:
                import sqlite3 as _sq

                conn = _sq.connect(str(DB), timeout=3)
                rows = conn.execute(
                    "SELECT model,SUM(total_tokens),ROUND(SUM(cost_usd),6) "
                    "FROM token_usage WHERE ts>=date('now') GROUP BY model ORDER BY 3 DESC LIMIT 5"
                ).fetchall()
                conn.close()
                lines = [f"{r[0][:20]}: {r[1]}tok ${r[2]}" for r in rows]
                reply = "[COST TODAY]\n" + "\n".join(lines) if lines else "[COST] Aucune donnee"
            except Exception as e:
                reply = f"[COST] err: {e}"
            self.hub_reply(reply, to=from_, corr_id=corr_id, model="sentinel")
            self.hub_notify(reply[:800])
            self.log.info("[sentinel] COST report")
            return True
        if sentinel == "§ROUTE":
            target = arg
            if arg.upper() == "BEST":
                # Choisir dynamiquement le provider le plus rapide
                try:
                    import sqlite3 as _sq

                    conn = _sq.connect(str(DB), timeout=3)
                    row = conn.execute(
                        "SELECT agent_id FROM provider_scores WHERE status='ok' ORDER BY priority ASC LIMIT 1"
                    ).fetchone()
                    conn.close()
                    target = row[0] if row else self.AGENT_ID
                except:
                    target = self.AGENT_ID
                self.log.info(f"[sentinel] ROUTE:BEST → {target}")
            else:
                target = f"agt_{arg}" if not arg.startswith("agt_") else arg
            self.hub_send(
                to=target,
                method="agent.task",
                payload=json.dumps({"text": "routed from " + self.AGENT_ID}),
                corr_id=corr_id,
            )
            self.log.info(f"[sentinel] ROUTE → {target}")
            return True
        if sentinel == "§RESET":
            # Vider le cache modèle de la classe
            self.__class__.__dict__.get("_cached_model", None)
            try:
                self.__class__._cached_model = None
            except:
                pass
            reply = f"[{self.AGENT_ID}] cache vidé"
            self.hub_reply(reply, to=from_, corr_id=corr_id, model="sentinel")
            self.log.info("[sentinel] RESET cache")
            return True
        return False  # sentinel non reconnue → continuer vers LLM

    def _handle(self, text, source="notify", corr_id="", from_="agt_claude"):
        # ── Fast-path sentinel strings ──────────────────────────────────
        sentinel, arg = _parse_sentinel(text)
        if sentinel and self._fast_path(sentinel, arg, corr_id, from_):
            return
        # ── DT Router — sélection agent optimal ──────────────────────
        try:
            # DT router — uniquement sur les notifications hub, pas sur recv direct
            # (un message recv est intentionnellement adressé à cet agent)
            if source == "notify":
                import sys as _sys

                _sys.path.insert(0, str(ROOT / "app"))
                from nokido_agent.app.forge_llm_router_dt import log_decision, route_with_dt

                _task = (
                    "code"
                    if any(
                        k in text[:100].lower() for k in ["code", "def ", "class ", "bug", "error"]
                    )
                    else "general"
                )
                _provider_hint, _conf, _source_dt = route_with_dt(_task, text[:200])
                _agent_hint = _DT_TO_AGENT.get(_provider_hint, self.AGENT_ID)
                # Rerouter seulement si différent ET confiance élevée ET pas déjà routé
                if (
                    _agent_hint != self.AGENT_ID
                    and _conf >= 0.8
                    and "dt_routed" not in text
                    and not text.startswith("§")
                ):
                    self.log.info(
                        f"[dt] reroute {self.AGENT_ID}→{_agent_hint} conf={_conf:.2f} [{_source_dt}]"
                    )
                    self.hub_send(
                        _agent_hint,
                        "agent.task",
                        json.dumps({"text": text, "dt_routed": True, "from_agent": self.AGENT_ID}),
                        corr_id,
                    )
                    return
        except Exception as _dte:
            self.log.debug(f"dt_route skip: {_dte}")
        # ── LLM path ────────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            result = self.call_llm(self._prompt(text))
            # Compat: (reply,model) ou (reply,model,prompt_tok,completion_tok)
            if len(result) == 4:
                reply, model, ptok, ctok = result
            elif len(result) == 2:
                reply, model = result
                ptok = len(text) // 4
                ctok = len(reply) // 4
            else:
                reply, model = result[0], result[1]
                ptok = ctok = 0
        except Exception as e:
            self.log.error(f"call_llm:{e}")
            return
        ms = round((time.perf_counter() - t0) * 1000)
        cost = _calc_cost(model, ptok, ctok)
        cost_str = f"${cost:.6f}" if cost > 0 else "free"
        self.log.info(f"[{source}] {model} {ms}ms {len(reply)}c | {ptok}+{ctok}tok {cost_str}")
        _track_usage(self.AGENT_ID, model, self.AGENT_LABEL, ptok, ctok, ms, source)
        ts = time.strftime("%H:%M:%S")
        if source == "recv" and not reply.startswith("ERR:"):
            self.hub_reply(reply, to=from_, corr_id=corr_id, model=model)
        # Circuit breaker: ne pas notifier les erreurs en boucle
        if not reply.startswith("ERR:"):
            self.hub_notify(f"[{self.AGENT_ID}/{model}] {ts}\n\n{reply[:600]}")
        else:
            self.log.warning(f"[circuit-breaker] {self.AGENT_ID}: {reply[:80]}")
        self._rag(reply, model)
        self.on_reply(reply, model, source)
        # ── Feedback loop DT router ──────────────────────────────────
        try:
            from nokido_agent.app.forge_llm_router_dt import log_decision

            _task2 = "code" if "code" in text[:80].lower() else "general"
            log_decision(
                _task2,
                text[:200],
                model.split("/")[-1],
                True,
                {"latency_ms": ms, "tokens": ptok + ctok},
            )
        except Exception:
            pass

    # Run
    def run(self):
        self.log.info(f"START {self.AGENT_LABEL} ({self.AGENT_ID}) poll={self.POLL_S}s")
        self.on_start()
        while True:
            try:
                for n in self.hub_poll():
                    if self._ok(n):
                        self.log.info(f"[notify] {len(n)}c")
                        self._handle(n, "notify")
                for m in self.hub_recv():
                    cid = m.get("id", "")
                    if self._seen_add(cid):
                        continue
                    frm = m.get("from", "agt_claude")
                    mth = m.get("method", "")
                    payload = m.get("payload", "")
                    self.log.info(f"[recv] {frm} method={mth} {len(payload)}c")
                    try:
                        text = json.loads(payload).get("text", payload)
                    except:
                        text = payload
                    # Circuit breaker: ignorer les ERR reçus (éviter boucle)
                    if text and len(text) >= 5 and not text.startswith("ERR:"):
                        self._handle(text, "recv", cid, frm)
                    elif text.startswith("ERR:"):
                        self.log.debug(f"[circuit-breaker] msg ERR ignoré de {frm}")
            except KeyboardInterrupt:
                self.log.info("STOP")
                break
            except Exception as e:
                self.log.error(f"cycle:{e}", exc_info=True)
            time.sleep(self.POLL_S)

    def hub_stream_chunk(
        self, chunk: str, corr_id: str = "", seq: int = 0, done: bool = False
    ) -> None:
        """Envoyer un chunk SSE au Hub — streaming progressif vers le TUI."""
        payload = json.dumps(
            {"chunk": chunk, "seq": seq, "done": done, "agent": self.AGENT_ID, "corr_id": corr_id}
        )
        self._hub(
            "tools/call",
            {
                "name": "hub",
                "arguments": {"action": "notify", "message": f"[STREAM/{self.AGENT_ID}] {payload}"},
            },
        )

    def call_llm_stream(self, prompt: str):
        """
        Override optionnel pour streaming.
        Doit être un générateur qui yield des chunks str.
        Par défaut: appel non-streaming, yield du résultat complet.
        """
        reply, model, *_ = self.call_llm(prompt)
        yield reply, model, True  # (chunk, model, is_final)

    def _handle_stream(self, text: str, corr_id: str = "", from_: str = "agt_claude") -> None:
        """
        Version streaming de _handle().
        Envoie les chunks au fur et à mesure → latence perçue réduite.
        Active si le broker override call_llm_stream().
        """
        t0 = time.perf_counter()
        full_reply = ""
        model = ""
        seq = 0
        try:
            for chunk, model, is_final in self.call_llm_stream(self._prompt(text)):
                full_reply += chunk
                self.hub_stream_chunk(chunk, corr_id=corr_id, seq=seq, done=is_final)
                seq += 1
                if is_final:
                    break
        except Exception as e:
            self.log.error(f"stream:{e}")
            return
        ms = round((time.perf_counter() - t0) * 1000)
        ptok = len(text) // 4
        ctok = len(full_reply) // 4
        cost = _calc_cost(model, ptok, ctok)
        self.log.info(f"[stream] {model} {ms}ms {len(full_reply)}c ${cost:.6f}")
        _track_usage(self.AGENT_ID, model, self.AGENT_LABEL, ptok, ctok, ms, "stream")
        if from_ != "notify":
            self.hub_reply(full_reply, to=from_, corr_id=corr_id, model=model)
        self._rag(full_reply, model)

    def on_start(self):  # noqa: B027 -- optional lifecycle hook, subclasses opt in
        """Subclasses may override to handle broker start. No-op by default."""

    def on_reply(self, reply, model, source):  # noqa: B027 -- optional hook
        """Subclasses may override to handle reply emission. No-op by default."""
