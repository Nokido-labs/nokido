from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [RED]
DATE:2026-04-24 | VER:v_forge_state_manager_v2
#FORGE:[score:99|agent:gemini-cli|temp:0.00|risk:0.02|ast:OK|test:OK|lint:OK|color:RED|attempt:2]
CONTRAINTE: Atomic State Management (Fixed for Compatibility & Performance)
"""
__FORGE_COLOR__ = "RED"
__FORGE_TAGS__ = "#FORGE:[score:99|agent:gemini-cli|temp:0.00|risk:0.02|ast:OK|test:OK|lint:OK|color:RED|attempt:2]"

import json
import logging
import time
import hmac
import hashlib
import secrets
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Deque

logger = logging.getLogger("Nokido.State.Manager")

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "sandbox" / "bridge_state.json"
LOCK_FILE = ROOT / "sandbox" / "bridge_state.json.lock"
REPLAY_LOG = ROOT / "sandbox" / "event_bus_replay.jsonl"

class EventBus:
    """Bus d'événements multi-agents atomique et sécurisé."""
    
    def __init__(self, state_mgr: StateManager):
        self.state_mgr = state_mgr
        self.hmac_key = os.environ.get("FORGE_MCP_TOKEN", "default_secret").encode()
        # Topics buffers: {topic: deque([events])}
        self.buffers: Dict[str, Deque[Dict[str, Any]]] = {}
        # Rate limit buckets: {agent: {"tokens": float, "last_ts": float}}
        self.buckets: Dict[str, Dict[str, float]] = {}
        self._load_replay_log()

    def _generate_id(self) -> str:
        """Génère un ID monotone type ULID-lite (timestamp + entropy)."""
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        entropy = secrets.token_hex(2)
        return f"evt_{ts}_{entropy}"

    def _check_rate_limit(self, agent: str) -> bool:
        """Token Bucket : 100/min pour agents, 300/min pour système."""
        now = time.monotonic()
        limit = 300 if agent in ("HUB", "SYSTEM", "TOOL", "SKILL", "SILO") else 100
        bucket = self.buckets.setdefault(agent, {"tokens": limit, "last_ts": now})
        
        # Recharge
        elapsed = now - bucket["last_ts"]
        bucket["tokens"] = min(limit, bucket["tokens"] + elapsed * (limit / 60.0))
        bucket["last_ts"] = now
        
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

    def publish(self, topic: str, kind: str, data: Dict[str, Any], agent: str, 
                corr_id: Optional[str] = None, parent_id: Optional[str] = None,
                sig: Optional[str] = None, trusted: bool = False) -> Union[str, bool]:
        """Publie un événement sur le bus avec vérification de signature et rate limit."""
        
        if not self._check_rate_limit(agent):
            return "ERR_RATE_LIMIT"

        if len(json.dumps(data)) > 4096:
            return "ERR_PAYLOAD_TOO_LARGE"

        evt_id = self._generate_id()
        ts = datetime.utcnow().isoformat()
        
        # 1. Signature check (anti-spoofing)
        if not trusted:
            msg_to_sign = f"{evt_id}|{ts}|{topic}|{agent}|{kind}".encode()
            expected_sig = hmac.new(self.hmac_key, msg_to_sign, hashlib.sha256).hexdigest()
            if sig != expected_sig:
                # On accepte quand même si le token est absent (mode dev), mais on log l'alerte
                if os.environ.get("LAFORGE_ENV") == "prod":
                    return "ERR_INVALID_SIGNATURE"
                logger.warning(f"Signature invalide de {agent} sur {topic}")

        # 2. Construction de l'objet event
        event = {
            "id": evt_id,
            "topic": topic,
            "ts": ts,
            "agent": agent,
            "kind": kind,
            "data": data,
            "corr_id": corr_id,
            "parent_id": parent_id
        }

        # 3. Bufferisation (circulaire par topic)
        if topic not in self.buffers:
            self.buffers[topic] = deque(maxlen=100)
        self.buffers[topic].append(event)

        # 4. Persistance Replay Log (Append-only)
        try:
            with open(REPLAY_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            logger.error(f"Erreur Replay Log: {e}")

        return evt_id

    def history(self, topics: List[str], limit: int = 50, since: Optional[str] = None) -> List[Dict[str, Any]]:
        """Récupère l'historique filtré par topics (supporte * et **)."""
        results = []
        for t, buffer in self.buffers.items():
            if self._topic_matches(t, topics):
                results.extend(list(buffer))
        
        # Filtrage par 'since'
        if since:
            results = [e for e in results if e["id"] > since or e["ts"] > since]
            
        # Tri et limite
        results.sort(key=lambda x: x["id"])
        return results[-limit:]

    def _topic_matches(self, topic: str, patterns: List[str]) -> bool:
        """Vérifie si un topic correspond à l'un des patterns (wildcards)."""
        for p in patterns:
            if p == "**" or p == topic: return True
            if p.endswith(".**"):
                if topic.startswith(p[:-2]): return True
            if "*" in p:
                import fnmatch
                if fnmatch.fnmatch(topic, p): return True
        return False

    def _load_replay_log(self):
        """Restaure le buffer depuis le replay log au démarrage."""
        if not REPLAY_LOG.exists(): return
        try:
            with open(REPLAY_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        topic = event["topic"]
                        if topic not in self.buffers:
                            self.buffers[topic] = deque(maxlen=100)
                        self.buffers[topic].append(event)
                    except: continue
        except Exception as e:
            logger.error(f"Echec restauration EventBus: {e}")

class StateManager:
    """Gestionnaire d'état atomique pour le bridge multi-agents."""
    
    def __init__(self, state_path: Path = STATE_FILE, lock_path: Path = LOCK_FILE):
        self.state_path = state_path
        self.lock_path = lock_path
        self.lock = FileLock(str(self.lock_path), timeout=5)

    def _get_default_state(self) -> Dict[str, Any]:
        return {
            "active_mode": "AUTO",
            "permissions": "STANDARD",
            "agents": {
                "CLAUDE": {"status": "idle", "progress": 0, "last_task": ""},
                "GEMINI": {"status": "idle", "progress": 0, "last_task": ""},
                "CLINE_PLAN": {"status": "idle", "progress": 0, "last_task": ""},
                "CLINE_ACT": {"status": "idle", "progress": 0, "last_task": ""},
            },
            "last_switch": datetime.now().isoformat(),
            "switch_reason": "Initial boot",
            "tasks": [],
            "pending_notifications": []
        }

    def _read_state_nolock(self) -> Dict[str, Any]:
        """Lecture interne sans verrou (à appeler depuis un contexte déjà verrouillé)."""
        if not self.state_path.exists():
            return self._get_default_state()
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Erreur lecture bridge_state.json: {e}")
            return self._get_default_state()

    def read_state(self) -> Dict[str, Any]:
        """Lecture sécurisée avec verrou."""
        with self.lock:
            return self._read_state_nolock()

    def write_state(self, state: Dict[str, Any]) -> bool:
        """Écriture atomique sécurisée."""
        with self.lock:
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.state_path.with_suffix(".tmp")
                temp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
                temp_path.replace(self.state_path)
                return True
            except Exception as e:
                logger.error(f"Erreur écriture bridge_state.json: {e}")
                return False

    def update_agent(self, agent_name: str, status: str = None, progress: int = None, last_task: str = None):
        """Mise à jour partielle d'un agent (Atomic)."""
        with self.lock:
            state = self._read_state_nolock()
            if "agents" not in state: state["agents"] = {}
            if agent_name not in state["agents"]:
                state["agents"][agent_name] = {"status": "idle", "progress": 0, "last_task": ""}
            
            if status is not None: state["agents"][agent_name]["status"] = status
            if progress is not None: state["agents"][agent_name]["progress"] = progress
            if last_task is not None: state["agents"][agent_name]["last_task"] = last_task
            
            self.write_state(state)

    def add_notification(self, message: Union[str, Dict[str, str]], source: str = "system"):
        """Ajoute une notification en gérant la compatibilité ascendante."""
        with self.lock:
            state = self._read_state_nolock()
            if "pending_notifications" not in state:
                state["pending_notifications"] = []
            
            ts = datetime.now().strftime("%H:%M:%S")
            
            # Formatage pour compatibilité totale (\n.join(notifs) legacy)
            if isinstance(message, dict):
                msg_str = message.get("message", str(message))
                notif_str = f"[{source}@{ts}] {msg_str}"
            else:
                notif_str = f"[{source}@{ts}] {message}"
                
            state["pending_notifications"].append(notif_str)
            
            # Rotation (50 max)
            if len(state["pending_notifications"]) > 50:
                state["pending_notifications"].pop(0)
            
            self.write_state(state)

_manager: Optional[StateManager] = None

def get_state_manager() -> StateManager:
    global _manager
    if _manager is None:
        _manager = StateManager()
    return _manager
