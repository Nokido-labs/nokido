"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_swarm_team
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_swarm_team.py — Sélection de Participants & Orchestration
=====================================================================
Implémente :
  1. Data Model  : SwarmTeam + Participant (dataclass sérialisables JSON)
  2. Orchestration : Lead_Orchestrator route les requêtes vers les actifs
  3. Async distant : LLM distants appelés en asyncio pour ne pas bloquer
  4. Config → events.db : sérialisée avec sequence_id à chaque lancement

Participants disponibles :
  LOCAL  : nokido (Ollama local), llamacpp (Vulkan GPU)
  REMOTE : gemini (Google), ollama_remote (autre machine)
  AGENT  : CLAUDE (MCP), CLINE_PLAN, CLINE_ACT

Usage :
    from forge_swarm_team import team, SwarmTeam, Participant
    team.activate("gemini", "laforge")
    result = await team.run("Explique le module forge_runner")
"""

import asyncio
import json
import sqlite3
import time
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
APP = Path(__file__).resolve().parent
DB_PATH = ROOT / "sandbox" / "events.db"
TEAM_CONFIG_PATH = ROOT / "sandbox" / "swarm_team_config.json"

# ── Data Model ────────────────────────────────────────────────────────────────


@dataclass
class Participant:
    id: str  # identifiant unique ex: "gemini", "nokido"
    label: str  # nom affichage ex: "Gemini 2.5 Flash"
    kind: str  # "local_llm" | "remote_llm" | "agent"
    provider: str  # "ollama" | "gemini" | "llamacpp" | "claude" | "cline"
    icon: str = "🤖"
    active: bool = False
    priority: int = 5  # 1=haute, 9=basse (ordre d'appel)
    async_call: bool = False  # True = appel non-bloquant pour LLM distant
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """To dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Participant":
        """From dict.

        Args:
            cls: Description.
            d: Description.
        """
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SwarmTeam:
    """
    Équipe de participants pour une session swarm.
    Sérialisable JSON → events.db.
    """

    session_id: str
    participants: list[Participant] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    launched_at: Optional[float] = None
    status: str = "draft"  # "draft" | "running" | "done" | "error"

    # ── Accesseurs ────────────────────────────────────────────────────────────

    @property
    def active(self) -> list[Participant]:
        """Active."""
        return sorted([p for p in self.participants if p.active], key=lambda p: p.priority)

    def get(self, pid: str) -> Optional[Participant]:
        """Get.

        Args:
            pid: Description.
        """
        return next((p for p in self.participants if p.id == pid), None)

    def activate(self, *ids: str) -> None:
        """Active les participants donnés SANS désactiver les autres.
        Si l'ID commence par ollama_, cree un participant ollama dynamique.
        """
        import copy as _cp

        existing = {pp.id for pp in self.participants}
        for pid in ids:
            if pid in existing:
                for pp in self.participants:
                    if pp.id == pid:
                        pp.active = True
            elif pid.startswith("ollama_"):
                # Creer participant ollama dynamique
                model_name = pid[7:].replace("_", ":", 1).replace("_", ".")
                base = next((pp for pp in self.participants if pp.id == "laforge"), None)
                if base:
                    clone = _cp.deepcopy(base)
                    clone.id = pid
                    clone.label = f"Ollama:{model_name}"
                    clone.config = {"model": model_name}
                    clone.active = True
                    self.participants.append(clone)
                    existing.add(pid)

    def toggle(self, pid: str) -> bool:
        """Toggle.

        Args:
            pid: Description.
        """
        p = self.get(pid)
        if p:
            p.active = not p.active
            return p.active
        return False

    def set_priority(self, pid: str, priority: int) -> None:
        """Set priority.

        Args:
            pid: Description.
            priority: Description.
        """
        p = self.get(pid)
        if p:
            p.priority = max(1, min(9, priority))

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """To dict."""
        return {
            "session_id": self.session_id,
            "participants": [p.to_dict() for p in self.participants],
            "created_at": self.created_at,
            "launched_at": self.launched_at,
            "status": self.status,
        }

    def to_json(self) -> str:
        """To json."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "SwarmTeam":
        """From dict.

        Args:
            cls: Description.
            d: Description.
        """
        participants = [Participant.from_dict(p) for p in d.get("participants", [])]
        return cls(
            session_id=d["session_id"],
            participants=participants,
            created_at=d.get("created_at", time.time()),
            launched_at=d.get("launched_at"),
            status=d.get("status", "draft"),
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Save."""
        TEAM_CONFIG_PATH.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls) -> "SwarmTeam":
        """Load.

        Args:
            cls: Description.
        """
        if TEAM_CONFIG_PATH.exists():
            return cls.from_dict(json.loads(TEAM_CONFIG_PATH.read_text(encoding="utf-8")))
        return _default_team()

    # ── Injection events.db ───────────────────────────────────────────────────

    def inject_to_events_db(self) -> int:
        """
        Sérialise la config et l'injecte dans events.db.
        Retourne le sequence_id assigné.
        """
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timecode TEXT, sequence_id INTEGER, session_id TEXT,
                agent_id TEXT, event_type TEXT, target TEXT,
                payload TEXT, prev_hash TEXT, new_hash TEXT, status TEXT
            )
        """)
        last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
        seq = last + 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%S") + f".{time.time_ns() % 1_000_000_000:06d}"
        conn.execute(
            "INSERT INTO event_log "
            "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,prev_hash,new_hash,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, seq, self.session_id, "Lead_Orchestrator", "team_config", "swarm_team", self.to_json(), "", "", "ok"),
        )
        conn.commit()
        conn.close()
        return seq

    # ── Flowchart ─────────────────────────────────────────────────────────────

    def flowchart_data(self) -> list[dict]:
        """
        Retourne une liste ordonnée de nœuds pour le flowchart Streamlit.
        Format : [{id, label, kind, icon, active, priority}]
        """
        nodes = [
            {
                "id": "Lead_Orchestrator",
                "label": "Lead Orchestrator",
                "kind": "orchestrator",
                "icon": "🎯",
                "active": True,
                "priority": 0,
            }
        ]
        for p in self.active:
            nodes.append(
                {
                    "id": p.id,
                    "label": p.label,
                    "kind": p.kind,
                    "icon": p.icon,
                    "active": p.active,
                    "priority": p.priority,
                    "async_call": p.async_call,
                }
            )
        nodes.append(
            {"id": "RAG_Sync", "label": "RAG Sync", "kind": "rag", "icon": "📚", "active": True, "priority": 99}
        )
        return nodes


# ── Participants disponibles ──────────────────────────────────────────────────


def _default_team() -> SwarmTeam:
    """Équipe par défaut avec tous les participants Nokido."""
    import time as _t

    sid = "team_" + str(int(_t.time()))
    participants = [
        # ── Agents locaux Nokido ──────────────────────────────────────────
        Participant(
            id="laforge",
            label="Nokido (Ollama local)",
            kind="local_llm",
            provider="ollama",
            icon="⚒️",
            active=False,
            priority=1,
            async_call=False,
            config={"model": "qwen2.5-coder:latest"},
        ),
        Participant(
            id="llamacpp",
            label="LlamaCPP Vulkan",
            kind="local_llm",
            provider="llamacpp",
            icon="⚡",
            active=False,
            priority=2,
            async_call=False,
            config={"max_tokens": 2048, "temperature": 0.1, "n_ctx": 40960},
        ),
        Participant(
            id="qwen_coder",
            label="Qwen2.5-Coder Mermaid",
            kind="local_llm",
            provider="llamacpp",
            icon="📊",
            active=False,
            priority=3,
            async_call=False,
            config={
                "max_tokens": 4096,
                "temperature": 0.1,
                "n_ctx": 40960,
                "system": "Tu génères uniquement du code Mermaid.js valide. Aucun texte avant ou après le bloc ```mermaid```.",
            },
        ),
        # ── LLM distants ──────────────────────────────────────────────────
        Participant(
            id="gemini",
            label="Gemini 2.5 Flash",
            kind="remote_llm",
            provider="gemini",
            icon="✨",
            active=False,
            priority=3,
            async_call=True,
            config={"model": "gemini-2.5-flash"},
        ),
        Participant(
            id="ollama_remote",
            label="Ollama Remote (localhost)",
            kind="remote_llm",
            provider="ollama_remote",
            icon="🌐",
            active=False,
            priority=4,
            async_call=True,
            config={"url": "http://localhost:11434"},
        ),
        # ── Agents MCP ────────────────────────────────────────────────────
        Participant(
            id="CLAUDE",
            label="Nokido MCP",
            kind="agent",
            provider="claude",
            icon="🤖",
            active=False,
            priority=5,
            async_call=True,
            config={"timeout": 120},
        ),
        Participant(
            id="CLINE_PLAN",
            label="Cline Planificateur",
            kind="agent",
            provider="cline",
            icon="🏗️",
            active=False,
            priority=6,
            async_call=True,
            config={"role": "plan"},
        ),
        Participant(
            id="CLINE_ACT",
            label="Cline Acteur",
            kind="agent",
            provider="cline",
            icon="⚙️",
            active=False,
            priority=7,
            async_call=True,
            config={"role": "act"},
        ),
        # ── LiteLLM — gateway unifiée ──────────────────────────────────
        Participant(
            id="litellm",
            label="LiteLLM Gateway",
            kind="remote_llm",
            provider="litellm",
            icon="🔀",
            active=False,
            priority=4,
            async_call=True,
            config={
                "model": "ollama/qwen2.5",
                "api_base": "http://localhost:11434",
            },
        ),
        # ── Ring 8 — Providers gratuits via LLMRouter ─────────────────
        Participant(
            id="groq",
            label="Groq (Llama 3.1 8B)",
            kind="remote_llm",
            provider="router",
            icon="⚡",
            active=False,
            priority=5,
            async_call=True,
            config={"use_case": "speed", "router_slot": "groq_fast"},
        ),
        Participant(
            id="deepseek",
            label="DeepSeek Coder",
            kind="remote_llm",
            provider="router",
            icon="🧠",
            active=False,
            priority=5,
            async_call=True,
            config={"use_case": "code", "router_slot": "deepseek_coder"},
        ),
        Participant(
            id="mistral",
            label="Mistral Small (EU)",
            kind="remote_llm",
            provider="router",
            icon="🇫🇷",
            active=False,
            priority=6,
            async_call=True,
            config={"use_case": "eu", "router_slot": "mistral_small"},
        ),
        Participant(
            id="hf_qwen",
            label="HF Qwen2.5-Coder 32B",
            kind="remote_llm",
            provider="router",
            icon="🤗",
            active=False,
            priority=7,
            async_call=True,
            config={"use_case": "mermaid", "router_slot": "hf_qwen_coder"},
        ),
        # ── Providers directs ────────────────────────────────────────────
        Participant(
            id="groq_direct",
            label="Groq Llama3.1 8B",
            kind="remote_llm",
            provider="groq",
            icon="⚡",
            active=False,
            priority=4,
            async_call=True,
            config={"model": "llama-3.1-8b-instant", "max_tokens": 500},
        ),
        Participant(
            id="groq_70b",
            label="Groq Llama3.3 70B",
            kind="remote_llm",
            provider="groq",
            icon="⚡",
            active=False,
            priority=4,
            async_call=True,
            config={"model": "llama-3.3-70b-versatile", "max_tokens": 800},
        ),
        Participant(
            id="xai_grok",
            label="xAI Grok-3 Mini",
            kind="remote_llm",
            provider="xai",
            icon="𝕏",
            active=False,
            priority=5,
            async_call=True,
            config={"model": "grok-3-mini-latest", "max_tokens": 500},
        ),
        Participant(
            id="mistral_direct",
            label="Mistral Small Direct",
            kind="remote_llm",
            provider="mistral_direct",
            icon="🌊",
            active=False,
            priority=5,
            async_call=True,
            config={"model": "mistral-small-latest", "max_tokens": 500},
        ),
        Participant(
            id="deepseek_direct",
            label="DeepSeek V3 Direct",
            kind="remote_llm",
            provider="deepseek_direct",
            icon="🐋",
            active=False,
            priority=5,
            async_call=True,
            config={"model": "deepseek-chat", "max_tokens": 500},
        ),
        Participant(
            id="nokido_mcp",
            label="Nokido MCP (One-MCP)",
            kind="agent",
            provider="claude",
            icon="⚙",
            active=False,
            priority=2,
            async_call=True,
            config={"use_case": "general", "max_tokens": 500, "timeout": 60},
        ),
    ]
    return SwarmTeam(session_id=sid, participants=participants)


# ── Lead Orchestrator ─────────────────────────────────────────────────────────


class LeadOrchestrator:
    """
    Orchestre les requêtes vers les participants actifs.
    - LLM locaux  → appel synchrone séquentiel
    - LLM distants → appel asyncio concurrent (ne bloque pas les locaux)
    - Agents MCP   → appel asyncio avec timeout
    """

    def __init__(self) -> None:
        """Init."""
        self._lock = threading.Lock()

    async def run(self, prompt: str, team: SwarmTeam, context: str = "") -> dict:
        """
        Point d'entrée principal.
        Retourne {session_id, results: [{participant_id, response, duration_ms, ok}], elapsed_ms}
        """
        # ── Isolation llamacpp — moteur interne partagé ───────────────────────
        # Max 1 participant llamacpp actif simultanément (contention VRAM/CPU)
        llamacpp_actifs = [p for p in team.active if p.provider == "llamacpp"]
        if len(llamacpp_actifs) > 1:
            # Forcer séquential : désactiver async_call sur les llamacpp
            for p in llamacpp_actifs:
                p.async_call = False
        # Si Ollama actif en même temps que llamacpp → réduire GPU layers
        ollama_actifs = [p for p in team.active if p.provider == "ollama"]
        if llamacpp_actifs and ollama_actifs:
            import os as _os

            current_layers = int(_os.environ.get("LLAMACPP_N_GPU_LAYERS", "10"))
            if current_layers > 0:
                # Partage GPU : réduire à 5 layers max pour llamacpp
                for p in llamacpp_actifs:
                    if "n_gpu_layers" not in p.config:
                        p.config["n_gpu_layers"] = min(current_layers, 5)

        team.launched_at = time.time()
        team.status = "running"
        seq = team.inject_to_events_db()

        # Broadcast démarrage
        try:
            import sys

            if str(APP) not in sys.path:
                sys.path.insert(0, str(APP))
            from nokido_agent.app.forge_swarm import broadcast

            broadcast(
                {
                    "type": "team_launched",
                    "session": team.session_id,
                    "participants": [p.id for p in team.active],
                    "seq": seq,
                }
            )
        except Exception:
            pass

        t0 = time.monotonic()
        actives = team.active
        local_ps = [p for p in actives if not p.async_call]
        async_ps = [p for p in actives if p.async_call]
        results = []

        # 1. LLM locaux — séquentiels (non bloquants car on est déjà en async)
        for p in local_ps:
            r = await self._call_participant(p, prompt, context)
            results.append(r)
            # Enrichir le context avec la réponse précédente
            if r["ok"] and r["response"]:
                context += f"\n[{p.label}]: {r['response'][:300]}"

        # 2. LLM distants + agents — concurrents
        if async_ps:
            tasks = [self._call_participant(p, prompt, context) for p in async_ps]
            async_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in async_results:
                if isinstance(r, Exception):
                    results.append({"participant_id": "?", "ok": False, "response": str(r)[:200], "duration_ms": 0})
                else:
                    results.append(r)

        elapsed = int((time.monotonic() - t0) * 1000)

        # Fallback — si tous les participants ont échoué, tenter Nokido local
        all_failed = results and all(not r.get("ok") or not r.get("response", "").strip() for r in results)
        if all_failed:
            try:
                fallback_resp = self._ollama_call(prompt, context, {})
                results.append(
                    {
                        "participant_id": "fallback_nokido",
                        "label": "Nokido (fallback)",
                        "kind": "local_llm",
                        "ok": bool(fallback_resp),
                        "response": fallback_resp,
                        "duration_ms": 0,
                        "is_fallback": True,
                    }
                )
            except Exception:
                pass

        team.status = "done"
        team.save()

        # Log résultat dans events.db
        self._log_result(team.session_id, results, elapsed)

        return {
            "session_id": team.session_id,
            "results": results,
            "elapsed_ms": elapsed,
            "context_out": context[:500],
            "all_failed": all_failed,
        }

    async def _call_participant(self, p: Participant, prompt: str, context: str) -> dict:
        """Appelle un participant et retourne son résultat."""
        t0 = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._dispatch(p, prompt, context), timeout=float(p.config.get("timeout", 30))
            )
            dur = int((time.monotonic() - t0) * 1000)
            # Broadcast token summary
            try:
                import sys

                if str(APP) not in sys.path:
                    sys.path.insert(0, str(APP))
                from nokido_agent.app.forge_swarm import broadcast

                broadcast({"type": "participant_done", "id": p.id, "dur_ms": dur, "chars": len(response)})
            except Exception:
                pass
            return {
                "participant_id": p.id,
                "label": p.label,
                "kind": p.kind,
                "ok": True,
                "response": response,
                "duration_ms": dur,
            }
        except asyncio.TimeoutError:
            return {
                "participant_id": p.id,
                "label": p.label,
                "kind": p.kind,
                "ok": False,
                "response": "Timeout",
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as e:
            return {
                "participant_id": p.id,
                "label": p.label,
                "kind": p.kind,
                "ok": False,
                "response": str(e)[:200],
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }

    async def _dispatch(self, p: Participant, prompt: str, context: str) -> str:
        """Route vers le bon backend selon p.provider."""
        import sys

        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        loop = asyncio.get_event_loop()

        if p.provider == "ollama":
            return await loop.run_in_executor(None, self._ollama_call, prompt, context, p.config)

        elif p.provider == "llamacpp":
            return await loop.run_in_executor(None, self._llamacpp_call, prompt, context, p.config)

        elif p.provider == "gemini":
            return await loop.run_in_executor(None, self._gemini_call, prompt, context, p.config)

        elif p.provider == "ollama_remote":
            return await loop.run_in_executor(None, self._ollama_remote_call, prompt, context, p.config)

        elif p.provider == "claude":
            return await loop.run_in_executor(None, self._claude_call, prompt, context, p.config)

        elif p.provider == "cline":
            return await loop.run_in_executor(None, self._cline_call, prompt, context, p.config)

        elif p.provider == "litellm":
            return await loop.run_in_executor(None, self._litellm_call, prompt, context, p.config)

        elif p.provider == "router":
            return await loop.run_in_executor(None, self._router_call, prompt, context, p.config)

        elif p.provider == "groq":
            return await loop.run_in_executor(None, self._groq_call, prompt, context, p.config)

        elif p.provider == "xai":
            return await loop.run_in_executor(None, self._xai_call, prompt, context, p.config)

        elif p.provider == "mistral_direct":
            return await loop.run_in_executor(None, self._mistral_call, prompt, context, p.config)

        elif p.provider == "deepseek_direct":
            return await loop.run_in_executor(None, self._deepseek_call, prompt, context, p.config)

        # Fallback : essayer ollama avec le modèle si provider inconnu
        return await loop.run_in_executor(None, self._ollama_call, prompt, context, p.config)

    # ── Backends ──────────────────────────────────────────────────────────────

    def _ollama_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel Ollama HTTP direct — bypass litellm."""
        import urllib.request as _ur, json as _j

        try:
            model = config.get("model", "qwen2.5:latest")
            system = config.get("system", "")
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            if context:
                messages.append({"role": "system", "content": "Contexte:\n" + context[:800]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": config.get("max_tokens", 2048),
                        "temperature": config.get("temperature", 0.1),
                    },
                }
            ).encode()
            req = _ur.Request(
                "http://localhost:11434/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            r = _ur.urlopen(req, timeout=60)
            data = _j.loads(r.read())
            return data.get("message", {}).get("content", "")
        except Exception as e:
            return f"[ollama error] {e}"

    def _llamacpp_call(self, prompt: str, context: str, config: dict) -> str:
        """Llamacpp call.

        Args:
            prompt: Description.
            context: Description.
            config: Description.
        """
        try:
            from nokido_agent.app.forge_llamacpp import LlamaCppBridge, llamacpp_call_sync

            b = LlamaCppBridge()
            if not b.is_available():
                return "[llamacpp unavailable — vérifier LLAMACPP_MODEL_PATH]"
            system = config.get("system", "Tu es un assistant expert.")
            if context:
                system += "\nContexte:\n" + context[:800]
            # llamacpp_call attend messages: List[Dict]
            messages = [{"role": "user", "content": prompt}]
            return llamacpp_call_sync(
                messages=messages,
                system=system,
                max_tokens=config.get("max_tokens", 600),
                temperature=config.get("temperature", 0.3),
            )
        except Exception as e:
            return f"[llamacpp error] {e}"

    def _gemini_call(self, prompt: str, context: str, config: dict) -> str:
        """Gemini call.

        Args:
            prompt: Description.
            context: Description.
            config: Description.
        """
        try:
            from nokido_agent.app.forge_collab_modes import gemini_ask_sync

            return gemini_ask_sync(prompt, context=context)
        except Exception as e:
            return f"[gemini error] {e}"

    def _ollama_remote_call(self, prompt: str, context: str, config: dict) -> str:
        """Ollama remote call.

        Args:
            prompt: Description.
            context: Description.
            config: Description.
        """
        try:
            import urllib.request

            url = config.get("url", "http://localhost:11434") + "/api/generate"
            model = config.get("model", "llama3")
            body = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            return data.get("response", "")
        except Exception as e:
            return f"[ollama_remote error] {e}"

    def _claude_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel Claude via Nokido MCP Hub HTTP."""
        import urllib.request as _ur, json as _j, os as _os

        try:
            token = _os.environ.get("FORGE_MCP_TOKEN", "")
            messages = []
            if context:
                messages.append({"role": "system", "content": "Contexte:\n" + context[:800]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "prompt": prompt,
                    "context": context[:800],
                    "use_case": config.get("use_case", "general"),
                    "max_tokens": config.get("max_tokens", 500),
                }
            ).encode()
            req = _ur.Request(
                "http://127.0.0.1:8080/generate",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Agent-ID": "LAFORGE_SWARM",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            r = _ur.urlopen(req, timeout=config.get("timeout", 60))
            data = _j.loads(r.read())
            return data.get("response", data.get("text", "[Nokido MCP: pas de réponse]"))
        except Exception as e:
            return f"[Nokido MCP error] {e}"

    def _router_call(self, prompt: str, context: str, config: dict) -> str:
        """Appelle le LLMRouter Ring 8 — cascade multi-providers."""
        use_case = config.get("use_case", "general")
        router_slot = config.get("router_slot", "")
        max_tokens = config.get("max_tokens", 500)
        system = config.get("system", "")
        try:
            from nokido_agent.app.forge_llm_router import get_router

            router = get_router()
            # Si un slot spécifique est demandé, activer ce provider
            if router_slot:
                slot = router._slots.get(router_slot)
                if slot and slot.is_available:
                    r = router._call_slot(slot, prompt, system, max_tokens, 0.7, 20, use_case)
                    return r.get("text", r.get("error", "[router error]"))
            result = router.call(prompt, use_case=use_case, max_tokens=max_tokens, system=system)
            return result.get("text", result.get("error", "[router error]"))
        except Exception as e:
            return f"[router error] {e}"

    def _litellm_call(self, prompt: str, context: str, config: dict) -> str:
        """Appelle LiteLLM — lit LITELLM_* depuis os.environ (Nokido.env)."""
        import os

        model = config.get("model") or os.environ.get("LITELLM_MODEL", "ollama/qwen2.5")
        api_base = config.get("api_base") or os.environ.get("LITELLM_API_BASE", "http://localhost:11434")
        api_key = config.get("api_key") or os.environ.get("LITELLM_API_KEY", "")
        try:
            from nokido_agent.app.forge_litellm_bridge import ask as litellm_ask

            return litellm_ask(
                task=prompt,
                context=context[:400],
                max_tokens=config.get("max_tokens", 500),
            )
        except Exception as e:
            return f"[litellm error] {e}"

    def _cline_call(self, prompt: str, context: str, config: dict) -> str:
        """Assigne une tâche à Cline via mcp_connector (remplace mcp_bridge._ws)."""
        import asyncio

        role = config.get("role", "plan")
        agent = "CLINE_PLAN" if role == "plan" else "CLINE_ACT"
        try:
            import sys

            sys.path.insert(0, str(ROOT.parent / "forge_desktop" / "core"))
            from mcp_connector import local_bridge

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                local_bridge().call_tool(
                    "llm_generate",
                    {"prompt": prompt, "agent_id": "laforge", "max_tokens": 300},
                    timeout=20.0,
                )
            )
            loop.close()
            resp = result.get("result", {}) if result.get("ok") else {}
            return resp.get("response", f"[{agent}] envoyé") if isinstance(resp, dict) else f"[{agent}] envoyé"
        except Exception as e:
            return f"[cline→mcp error] {e}"

    def _groq_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel Groq via API OpenAI-compatible."""
        import urllib.request as _ur, json as _j, os as _os

        # `_gs` (un seul underscore) est l'aide definie ligne 44. Le double
        # underscore etait un nom qui n'existe nulle part : NameError garanti des
        # que ce provider est sollicite. Bombe dormante introduite par f4707013,
        # trouvee le 2026-08-19 par un audit AST des appels non lies -- ni les
        # tests ni le lint ne la voyaient, car un fichier qui PARSE peut tres
        # bien appeler un nom inexistant.
        api_key = _gs("GROQ_API_KEY")
        if not api_key:
            try:
                from nokido_agent.app.forge_secrets import get_secret

                api_key = get_secret("GROQ_API_KEY") or ""
            except Exception:
                pass
        if not api_key:
            return "[groq] GROQ_API_KEY manquant dans Nokido.env"
        try:
            model = config.get("model", "llama-3.1-8b-instant")
            messages = []
            if context:
                messages.append({"role": "system", "content": context[:400]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "max_tokens": config.get("max_tokens", 500),
                    "temperature": config.get("temperature", 0.7),
                }
            ).encode()
            req = _ur.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            r = _ur.urlopen(req, timeout=30)
            data = _j.loads(r.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[groq error] {e}"

    def _xai_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel xAI Grok via API OpenAI-compatible."""
        import urllib.request as _ur, json as _j, os as _os

        api_key = _gs("XAI_API_KEY")
        if not api_key:
            try:
                from nokido_agent.app.forge_secrets import get_secret

                api_key = get_secret("XAI_API_KEY") or ""
            except Exception:
                pass
        if not api_key:
            return "[xai] XAI_API_KEY manquant dans Nokido.env"
        try:
            model = config.get("model", "grok-3-mini-latest")
            messages = []
            if context:
                messages.append({"role": "system", "content": context[:400]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "max_tokens": config.get("max_tokens", 500),
                }
            ).encode()
            req = _ur.Request(
                "https://api.x.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            r = _ur.urlopen(req, timeout=30)
            data = _j.loads(r.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[xai error] {e}"

    def _deepseek_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel DeepSeek via API OpenAI-compatible."""
        import urllib.request as _ur, json as _j, os as _os

        api_key = _gs("DEEPSEEK_API_KEY")
        if not api_key:
            try:
                from nokido_agent.app.forge_secrets import get_secret

                api_key = get_secret("DEEPSEEK_API_KEY") or ""
            except Exception:
                pass
        if not api_key:
            return "[deepseek] DEEPSEEK_API_KEY manquant"
        try:
            model = config.get("model", "deepseek-chat")
            messages = []
            if context:
                messages.append({"role": "system", "content": context[:400]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "max_tokens": config.get("max_tokens", 500),
                    "temperature": config.get("temperature", 0.7),
                }
            ).encode()
            req = _ur.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            r = _ur.urlopen(req, timeout=30)
            data = _j.loads(r.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[deepseek error] {e}"

    def _mistral_call(self, prompt: str, context: str, config: dict) -> str:
        """Appel Mistral AI direct."""
        import urllib.request as _ur, json as _j, os as _os

        api_key = _os.environ.get("MISTRAL_API_KEY", "")
        if not api_key:
            try:
                from nokido_agent.app.forge_secrets import get_secret

                api_key = get_secret("MISTRAL_API_KEY") or ""
            except Exception:
                pass
        if not api_key:
            return "[mistral] MISTRAL_API_KEY manquant dans Nokido.env"
        try:
            model = config.get("model", "mistral-small-latest")
            messages = []
            if context:
                messages.append({"role": "system", "content": context[:400]})
            messages.append({"role": "user", "content": prompt})
            payload = _j.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "max_tokens": config.get("max_tokens", 500),
                }
            ).encode()
            req = _ur.Request(
                "https://api.mistral.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            r = _ur.urlopen(req, timeout=30)
            data = _j.loads(r.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[mistral error] {e}"

    # ── Log résultat ──────────────────────────────────────────────────────────

    def _log_result(self, session_id: str, results: list, elapsed_ms: int) -> None:
        """Log result.

        Args:
            session_id: Description.
            results: Description.
            elapsed_ms: Description.
        """
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            seq = last + 1
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            payload = json.dumps(
                {
                    "results": [{k: v for k, v in r.items() if k != "response"} for r in results],
                    "elapsed_ms": elapsed_ms,
                },
                ensure_ascii=False,
            )
            conn.execute(
                "INSERT INTO event_log "
                "(timecode,sequence_id,session_id,agent_id,event_type,target,payload,prev_hash,new_hash,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts, seq, session_id, "Lead_Orchestrator", "team_result", "swarm_team", payload, "", "", "ok"),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


# ── Singleton global ──────────────────────────────────────────────────────────
orchestrator = LeadOrchestrator()


def get_team() -> SwarmTeam:
    """Charge ou crée la team courante."""
    return SwarmTeam.load()


def save_team(team: SwarmTeam) -> None:
    """Save team.

    Args:
        team: Description.
    """
    team.save()


async def launch_team(prompt: str, team: SwarmTeam, context: str = "") -> dict:
    """Point d'entrée haut niveau."""
    return await orchestrator.run(prompt, team, context)
