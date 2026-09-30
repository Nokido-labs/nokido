"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_auto_pilot
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_auto_pilot.py — Auto-Pilote Ring 5.5
================================================
Système végétatif autonome — tourne en DETACHED ou service NSSM.

Lit l'état du système via MMap (256KB IPC) toutes les N secondes.
Si un seuil est franchi → appelle le MCP Bridge (R9) sans attendre l'humain.

Variables .env lues :
  LAFORGE_ENV=dev         → seuils plus permissifs, pas d'actions destructives
  LAFORGE_MCP_DEV=true    → actions simulées seulement
  LAFORGE_IDLE_TIMEOUT    → timeout avant auto-rollback (défaut 3600s)

Déclencheurs (MMap → Action MCP) :
  gui.heartbeat vieux > 10s   → restart_service NokidoMCP (auto-heal)
  inspector.drift > 0.85      → context_rollback session active
  inspector.entropy < -0.5    → flush context + reset swarm IDLE
  llm.*.vram_mb > 95%         → clear_cache (kill NPU + restart)
  swarm.state == THINKING > 90s → force_idle (watchdog swarm)
  mesh.last_adr défini        → auto-ingest ADR dans RAG ring 2

ADR-010 → ADR-011 : Auto-Pilote Ring 5.5 — Système Végétatif Autonome.
"""

import asyncio
import json
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

logger = logging.getLogger("Nokido.AutoPilot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [AutoPilot] %(message)s")


def _is_dev() -> bool:
    """Is dev."""
    return (
        os.environ.get("LAFORGE_ENV", "prod").lower() == "dev"
        or os.environ.get("LAFORGE_MCP_DEV", "false").lower() == "true"
    )


# ── Seuils — dev plus permissifs ──────────────────────────────────────────────


def _thresholds() -> dict:
    """Thresholds."""
    dev = _is_dev()
    return {
        "heartbeat_stale_s": 15 if dev else 10,
        "drift_rollback": 0.90 if dev else 0.85,
        "entropy_flush": -1.0 if dev else -0.5,
        "vram_pct_max": 99 if dev else 95,
        "swarm_stuck_s": 120 if dev else 90,
        "poll_interval_s": 10 if dev else 5,
    }


# ── Lecture MMap ──────────────────────────────────────────────────────────────


class MMapReader:
    """Lit les clés MMap sans dépendance Qt."""

    def __init__(self) -> None:
        """Init."""
        self._bridge = None
        self._available = False
        try:
            from nokido_agent.app.live_bridge import bridge

            self._bridge = bridge
            self._available = True
        except Exception:
            pass

    def get(self, key: str, default=None) -> object:
        """Get.

        Args:
            key: Description.
            default: Description.
        """
        if not self._available:
            return default
        try:
            return self._bridge.json_get(key)
        except Exception:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get float.

        Args:
            key: Description.
            default: Description.
        """
        v = self.get(key, default)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    def set(self, key: str, value) -> None:
        """Set.

        Args:
            key: Description.
            value: Description.
        """
        if not self._available:
            return
        try:
            self._bridge.json_set(key, value)
        except Exception:
            pass


# ── Actions MCP ───────────────────────────────────────────────────────────────


async def _call_mcp(tool: str, args: dict, timeout: float = 8.0) -> dict:
    """Appelle un tool MCP via mcp_connector — non-bloquant."""
    try:
        from forge_desktop.core.mcp_connector import local_bridge

        result = await asyncio.wait_for(
            local_bridge().call_tool(tool, args, timeout=timeout),
            timeout=timeout + 1,
        )
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:80]}


async def _fire_mcp(tool: str, args: dict) -> None:
    """Fire & forget — Ring 5 cascade."""
    try:
        from forge_desktop.core.mcp_connector import local_bridge

        await local_bridge().fire_and_forget(tool, args)
    except Exception:
        pass


# ── Décisions autonomes ───────────────────────────────────────────────────────


class AutoPilot:
    """
    Cœur autonome Ring 5.5.
    Boucle de rétroaction : MMap → décision → MCP action.
    """

    def __init__(self) -> None:
        """Init."""
        self._mmap = MMapReader()
        self._running = False
        self._loop = None
        self._last_actions: dict = {}  # évite les répétitions rapides
        self._session_id = f"autopilot_{int(time.time())}"

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def run_loop(self) -> None:
        """Boucle asyncio principale."""
        self._running = True
        thresholds = _thresholds()
        interval = thresholds["poll_interval_s"]
        logger.info(f"AutoPilot démarré — dev={_is_dev()} interval={interval}s")

        # Annoncer dans mmap
        self._mmap.set("autopilot.pid", os.getpid())
        self._mmap.set("autopilot.started", time.time())
        self._mmap.set("autopilot.status", "running")

        while self._running:
            try:
                await self._tick(thresholds)
            except Exception as e:
                logger.error(f"tick error: {e}")
            await asyncio.sleep(interval)

        self._mmap.set("autopilot.status", "stopped")

    async def _tick(self, T: dict) -> None:
        """Un cycle de décision complet."""
        now = time.time()

        # ── 1. Auto-Heal : heartbeat GUI gelé ─────────────────────────────
        hb = self._mmap.get_float("gui.heartbeat", 0.0)
        if hb > 0 and (now - hb) > T["heartbeat_stale_s"]:
            if self._can_act("heal_hub", cooldown=60):
                logger.warning(f"GUI heartbeat gelé depuis {now - hb:.0f}s → restart Hub")
                await self._action_heal_hub()

        # ── 2. Anti-pourrissement : drift Inspecteur R4 ───────────────────
        drift = self._mmap.get_float("inspector.drift", 0.0)
        if drift >= T["drift_rollback"]:
            if self._can_act("rollback", cooldown=120):
                logger.warning(f"Drift {drift:.2f} >= {T['drift_rollback']} → rollback")
                await self._action_context_rollback()

        # ── 3. Entropie critique ───────────────────────────────────────────
        entropy = self._mmap.get_float("inspector.entropy", 0.0)
        if entropy < T["entropy_flush"] and entropy != 0.0:
            if self._can_act("entropy_flush", cooldown=180):
                logger.warning(f"Entropie {entropy:.3f} < {T['entropy_flush']} → flush")
                await self._action_flush_context()

        # ── 4. VRAM saturée ───────────────────────────────────────────────
        for agent_id in ["CLAUDE", "laforge", "llamacpp"]:
            vram = self._mmap.get_float(f"llm.{agent_id}.vram_mb", 0.0)
            total_vram = 16384  # 16GB — AMD 780M
            if vram > 0 and (vram / total_vram * 100) > T["vram_pct_max"]:
                if self._can_act(f"vram_{agent_id}", cooldown=90):
                    logger.warning(f"VRAM {agent_id}: {vram:.0f}MB → clear_cache")
                    await self._action_clear_cache(agent_id)

        # ── 5. Swarm bloqué en THINKING ───────────────────────────────────
        swarm_state = self._mmap.get("swarm.state", "IDLE")
        swarm_since = self._mmap.get_float("swarm.since", now)
        if swarm_state == "THINKING" and (now - swarm_since) > T["swarm_stuck_s"]:
            if self._can_act("swarm_stuck", cooldown=120):
                logger.warning(f"Swarm THINKING depuis {now - swarm_since:.0f}s → force_idle")
                await self._action_force_idle()

        # ── 6. Auto-ADR : nouvelle synthèse mesh → ingestion RAG ──────────
        mesh_adr = self._mmap.get("mesh.last_adr", "")
        mesh_ts = self._mmap.get_float("mesh.ts", 0.0)
        if mesh_adr and (now - mesh_ts) < 30:  # synthèse récente
            if self._can_act(f"auto_adr_{mesh_adr}", cooldown=300):
                logger.info(f"Auto-ADR mesh → RAG: {mesh_adr}")
                await self._action_auto_adr(mesh_adr)

        # Mise à jour status mmap
        self._mmap.set("autopilot.last_tick", now)
        self._mmap.set("autopilot.drift", drift)
        self._mmap.set("autopilot.entropy", entropy)

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _action_heal_hub(self) -> None:
        """Restart NokidoHub si gelé."""
        if _is_dev():
            logger.info("[DEV] heal_hub simulé")
            self._log_action("heal_hub", "dev_sim")
            return
        # Gate anti-régression : restart du hub -> post_check hub_alive
        # (le hub DOIT répondre après ; sinon la régression est ancrée).
        from nokido_agent.app.forge_guarded_change import guarded_change, hub_alive

        with guarded_change("auto_pilot: heal_hub", post_check=hub_alive):
            result = await _call_mcp("service_start", {"name": "NokidoHub"})
        self._mmap.set("autopilot.last_action", "heal_hub")
        self._log_action("heal_hub", result.get("ok", False))

    async def _action_context_rollback(self) -> None:
        """Rollback contexte via MCP tool."""
        if _is_dev():
            logger.info("[DEV] context_rollback simulé")
            self._log_action("context_rollback", "dev_sim")
            return
        result = await _call_mcp(
            "context_rollback",
            {
                "session_id": self._session_id,
                "reason": "AutoPilot R5.5 — drift seuil atteint",
            },
        )
        self._mmap.set("autopilot.last_action", "context_rollback")
        self._log_action("context_rollback", result.get("ok", False))

    async def _action_flush_context(self) -> None:
        """Flush contexte + reset swarm si entropie critique."""
        if _is_dev():
            logger.info("[DEV] flush_context simulé")
            self._log_action("flush_context", "dev_sim")
            return
        await _fire_mcp("swarm_force_idle", {})
        await _call_mcp(
            "context_rollback",
            {
                "session_id": self._session_id,
                "reason": "AutoPilot — entropie critique",
            },
        )
        self._mmap.set("autopilot.last_action", "flush_context")
        self._log_action("flush_context", True)

    async def _action_clear_cache(self, agent_id: str) -> None:
        """Clear cache VRAM d'un agent."""
        if _is_dev():
            logger.info(f"[DEV] clear_cache {agent_id} simulé")
            return
        # Fire & forget — non-bloquant
        await _fire_mcp("swarm_force_idle", {"agent_id": agent_id})
        self._mmap.set("autopilot.last_action", f"clear_cache_{agent_id}")
        self._log_action(f"clear_cache_{agent_id}", True)

    async def _action_force_idle(self) -> None:
        """Force swarm en IDLE."""
        result = await _call_mcp("swarm_force_idle", {})
        self._mmap.set("autopilot.last_action", "force_idle")
        self._log_action("force_idle", result.get("ok", False))

    async def _action_auto_adr(self, adr_id: str) -> None:
        """Ingère un ADR mesh dans le RAG ring 2."""
        try:
            from nokido_agent.app.forge_mesh_memory import get_mesh

            mesh = get_mesh()
            if not mesh.is_available():
                return
            # Chercher la synthèse dans LanceDB
            results = mesh.search_similar("adr_validated", [0.0] * 256, limit=1)
            if not results:
                return
            latest = results[0]
            # Ingérer dans RAG principal
            result = await _call_mcp(
                "rag_ingest_text",
                {
                    "text": latest.get("synthesis", "")[:1000],
                    "source": adr_id,
                    "domain": "adr",
                },
            )
            self._mmap.set("autopilot.last_action", f"auto_adr_{adr_id}")
            self._log_action(f"auto_adr_{adr_id}", result.get("ok", False))
        except Exception as e:
            logger.error(f"auto_adr error: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _can_act(self, action_key: str, cooldown: int = 60) -> bool:
        """Anti-répétition — évite d'agir 10 fois en 1 minute."""
        last = self._last_actions.get(action_key, 0)
        if (time.time() - last) >= cooldown:
            self._last_actions[action_key] = time.time()
            return True
        return False

    def _log_action(self, action: str, result) -> None:
        """Log dans events.db."""
        try:
            import sqlite3

            conn = sqlite3.connect(str(ROOT / "sandbox" / "events.db"), timeout=5)
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO event_log"
                "(timecode,sequence_id,agent_id,event_type,target,payload,status)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    last + 1,
                    "autopilot",
                    "auto_action",
                    action,
                    json.dumps({"result": str(result), "dev": _is_dev()}),
                    "ok" if result else "warn",
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def stop(self) -> None:
        """Stop."""
        self._running = False


# ── Thread launcher ───────────────────────────────────────────────────────────

_pilot: Optional[AutoPilot] = None
_thread: Optional[threading.Thread] = None


def start_autopilot(blocking: bool = False) -> AutoPilot:
    """Lance l'AutoPilot dans un thread daemon."""
    global _pilot, _thread

    if _pilot and _thread and _thread.is_alive():
        return _pilot

    _pilot = AutoPilot()

    def _run() -> None:
        """Run."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_pilot.run_loop())
        finally:
            loop.close()

    if blocking:
        _run()
    else:
        _thread = threading.Thread(target=_run, daemon=True, name="Nokido.AutoPilot")
        _thread.start()
        logger.info(f"AutoPilot thread démarré (daemon) — dev={_is_dev()}")

    return _pilot


def stop_autopilot() -> None:
    """Stop autopilot."""
    global _pilot
    if _pilot:
        _pilot.stop()


def autopilot_status() -> dict:
    """Autopilot status."""
    alive = _thread and _thread.is_alive() if _thread else False
    return {
        "running": alive,
        "dev_mode": _is_dev(),
        "thresholds": _thresholds(),
        "pid": os.getpid(),
    }


# ── Entrée CLI / NSSM ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Charger Nokido.env
    env_path = ROOT / "Nokido.env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    logger.info("AutoPilot lancé en mode STANDALONE (blocking)")
    pilot = AutoPilot()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(pilot.run_loop())
    except KeyboardInterrupt:
        logger.info("AutoPilot arrêté par Ctrl+C")
    finally:
        loop.close()
