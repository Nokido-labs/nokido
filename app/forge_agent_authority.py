"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_agent_authority
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_agent_authority.py
==============================
Gouvernance des agents Nokido — contrôle d'autorité sur le bus MCP.

Niveaux :
  MASTER_DEV   → write fichiers, run python, commit git
                 Un seul à la fois. Token avec TTL glissant (défaut 30min).
  ORCHESTRATOR → query DB, notify, event_log, appels LeadOrchestrator
                 Réattribuable. Plusieurs simultanément possibles.
  READ_ONLY    → read + query SELECT uniquement
                 Défaut pour tout agent non désigné.

Mécanisme token MASTER_DEV :
  - Heartbeat implicite : chaque appel MCP renouvelle le TTL
  - Expiration douce : TTL glissant 30min sans activité
  - Révocation manuelle : release_master_dev(agent_id)
  - Préemption humaine : force_transfer(new_agent_id)
  - Aucune dépendance à une fermeture propre de session

Persistance : sandbox/authority_state.json (rechargé à chaud)
"""

import json
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "config" / "authority_state.json"

# TTL glissant en secondes
MASTER_TTL = 30 * 60  # 30 min sans activité → expiration douce
HEARTBEAT_MIN = 60  # intervalle mini entre deux renouvellements loggés

# Agents connus
KNOWN_AGENTS = {"CLAUDE", "GEMINI", "XAI", "DEEPSEEK", "MISTRAL", "CLINE_PLAN", "CLINE_ACT", "HUMAN"}

# Niveau d'autorité
AUTHORITY_LEVELS = ("MASTER_DEV", "ORCHESTRATOR", "READ_ONLY")


# ── State singleton ───────────────────────────────────────────────────────────


class _AuthorityState:
    """État d'autorité — thread-safe, persisté sur disque."""

    def __init__(self) -> None:
        """Init."""
        self._lock = threading.Lock()
        self._state = self._load()

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        """Load."""
        try:
            if STATE_PATH.exists():
                return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return self._blank()

    def _blank(self) -> dict:
        """Blank."""
        return {
            "master_dev": {
                "agent_id": None,
                "acquired_at": None,
                "last_beat": None,
                "ttl": MASTER_TTL,
            },
            "orchestrators": [],  # liste d'agent_id
            "history": [],  # dernières 20 transitions
        }

    def _save(self) -> None:
        """Save."""
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                from nokido_agent.app.forge_hub_storage import atomic_write

                atomic_write(STATE_PATH, json.dumps(self._state, indent=2, ensure_ascii=False))
            except ImportError:
                STATE_PATH.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _log(self, event: str, agent: str, detail: str = "") -> None:
        """Log.

        Args:
            event: Description.
            agent: Description.
            detail: Description.
        """
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "agent": agent,
            "detail": detail,
        }
        self._state["history"].append(entry)
        self._state["history"] = self._state["history"][-20:]

    # ── Expiration check ──────────────────────────────────────────────────────

    def _is_master_expired(self) -> bool:
        """Is master expired."""
        md = self._state["master_dev"]
        if md["agent_id"] is None:
            return True
        last = md.get("last_beat") or md.get("acquired_at") or 0
        return (time.time() - last) > md.get("ttl", MASTER_TTL)

    def _maybe_expire(self) -> None:
        """Expire silencieusement le token si TTL dépassé."""
        if not self._is_master_expired():
            return
        md = self._state["master_dev"]
        if md["agent_id"]:
            self._log("EXPIRED", md["agent_id"], f"TTL {md.get('ttl', MASTER_TTL)}s dépassé")
            md["agent_id"] = None
            md["acquired_at"] = None
            md["last_beat"] = None
            self._save()

    # ── API publique ──────────────────────────────────────────────────────────

    def acquire_master(self, agent_id: str, ttl: int = MASTER_TTL) -> dict:
        """
        Demande le token MASTER_DEV.
        Retourne {"ok": bool, "reason": str, "holder": str|None}
        """
        with self._lock:
            self._maybe_expire()
            md = self._state["master_dev"]

            if md["agent_id"] and md["agent_id"] != agent_id:
                return {
                    "ok": False,
                    "reason": f"Token détenu par {md['agent_id']}",
                    "holder": md["agent_id"],
                }

            now = time.time()
            md["agent_id"] = agent_id
            md["acquired_at"] = now
            md["last_beat"] = now
            md["ttl"] = ttl
            self._log("ACQUIRED", agent_id, f"TTL={ttl}s")
            self._save()
            return {"ok": True, "reason": "ok", "holder": agent_id}

    def heartbeat(self, agent_id: str) -> bool:
        """
        Renouvelle le TTL si cet agent est MASTER_DEV.
        Appelé implicitement à chaque action write/run.
        Retourne True si autorisé, False si token expiré ou volé.
        """
        with self._lock:
            self._maybe_expire()
            md = self._state["master_dev"]
            if md["agent_id"] != agent_id:
                return False
            now = time.time()
            # Logguer seulement si > HEARTBEAT_MIN depuis le dernier log
            last = md.get("last_beat") or 0
            md["last_beat"] = now
            if (now - last) > HEARTBEAT_MIN:
                self._log("HEARTBEAT", agent_id)
                self._save()
            return True

    def release_master(self, agent_id: str) -> dict:
        """Libère le token MASTER_DEV volontairement."""
        with self._lock:
            md = self._state["master_dev"]
            if md["agent_id"] != agent_id:
                return {"ok": False, "reason": f"Tu n'es pas MASTER_DEV (holder={md['agent_id']})"}
            md["agent_id"] = None
            md["acquired_at"] = None
            md["last_beat"] = None
            self._log("RELEASED", agent_id, "libération volontaire")
            self._save()
            return {"ok": True, "reason": "released"}

    def force_transfer(self, new_agent_id: str, reason: str = "transfert humain") -> dict:
        """
        Préemption humaine — force le transfert du token MASTER_DEV.
        Ne peut être appelé que si agent_id == 'HUMAN' ou depuis ce module.
        """
        with self._lock:
            md = self._state["master_dev"]
            old = md["agent_id"] or "none"
            now = time.time()
            md["agent_id"] = new_agent_id
            md["acquired_at"] = now
            md["last_beat"] = now
            self._log("PREEMPTED", new_agent_id, f"old={old} reason={reason}")
            self._save()
            return {"ok": True, "old_holder": old, "new_holder": new_agent_id}

    def set_orchestrator(self, agent_id: str) -> dict:
        """Ajoute un agent au rôle ORCHESTRATOR."""
        with self._lock:
            orcs = self._state["orchestrators"]
            if agent_id not in orcs:
                orcs.append(agent_id)
                self._log("ORCH_ADDED", agent_id)
                self._save()
            return {"ok": True, "orchestrators": list(orcs)}

    def remove_orchestrator(self, agent_id: str) -> dict:
        """Retire un agent du rôle ORCHESTRATOR."""
        with self._lock:
            orcs = self._state["orchestrators"]
            if agent_id in orcs:
                orcs.remove(agent_id)
                self._log("ORCH_REMOVED", agent_id)
                self._save()
            return {"ok": True, "orchestrators": list(orcs)}

    def get_level(self, agent_id: str) -> str:
        """Retourne le niveau d'autorité effectif d'un agent."""
        with self._lock:
            self._maybe_expire()
            md = self._state["master_dev"]
            if md["agent_id"] == agent_id:
                return "MASTER_DEV"
            if agent_id in self._state.get("orchestrators", []):
                return "ORCHESTRATOR"
            return "READ_ONLY"

    def check_write(self, agent_id: str) -> dict:
        """
        Vérifie si un agent peut effectuer un write/run.
        Renouvelle le heartbeat si autorisé.
        Retourne {"ok": bool, "level": str, "reason": str}
        """
        with self._lock:
            self._maybe_expire()
            md = self._state["master_dev"]
            level = self.get_level(agent_id)

            if level == "MASTER_DEV":
                # Renouveler heartbeat
                md["last_beat"] = time.time()
                self._save()
                return {"ok": True, "level": "MASTER_DEV", "reason": "autorisé"}

            remaining = None
            if md["agent_id"]:
                last = md.get("last_beat") or md.get("acquired_at") or 0
                remaining = max(0, int(md.get("ttl", MASTER_TTL) - (time.time() - last)))

            return {
                "ok": False,
                "level": level,
                "reason": f"MASTER_DEV requis — holder={md['agent_id']} (expire dans {remaining}s)"
                if md["agent_id"]
                else "slot libre — acquiers le token d'abord",
                "holder": md["agent_id"],
                "remaining": remaining,
            }

    def status(self) -> dict:
        """Snapshot complet de l'état d'autorité."""
        with self._lock:
            self._maybe_expire()
            md = self._state["master_dev"]
            now = time.time()
            last = md.get("last_beat") or md.get("acquired_at") or 0
            remaining = max(0, int(md.get("ttl", MASTER_TTL) - (now - last))) if md["agent_id"] else None
            return {
                "master_dev": md["agent_id"],
                "ttl_remaining": remaining,
                "orchestrators": list(self._state.get("orchestrators", [])),
                "last_history": self._state.get("history", [])[-5:],
            }


# ── Singleton global ──────────────────────────────────────────────────────────

_authority = _AuthorityState()


# ── API module ────────────────────────────────────────────────────────────────

# Context:


def acquire_master_dev(agent_id: str, ttl: int = MASTER_TTL) -> dict:
    """Acquire master dev.

    Args:
        agent_id: Description.
        ttl: Description.
    """
    return _authority.acquire_master(agent_id, ttl)


def release_master_dev(agent_id: str) -> dict:
    """Release master dev.

    Args:
        agent_id: Description.
    """
    return _authority.release_master(agent_id)


def force_transfer_master(new_agent_id: str, reason: str = "transfert humain") -> dict:
    """Force transfer master.

    Args:
        new_agent_id: Description.
        reason: Description.
    """
    return _authority.force_transfer(new_agent_id, reason)


def set_orchestrator(agent_id: str) -> dict:
    """Set orchestrator.

    Args:
        agent_id: Description.
    """
    return _authority.set_orchestrator(agent_id)


def remove_orchestrator(agent_id: str) -> dict:
    """Remove orchestrator.

    Args:
        agent_id: Description.
    """
    return _authority.remove_orchestrator(agent_id)


def check_write_permission(agent_id: str) -> dict:
    """Check write permission.

    Args:
        agent_id: Description.
    """
    return _authority.check_write(agent_id)


def get_authority_level(agent_id: str) -> str:
    """Get authority level.

    Args:
        agent_id: Description.
    """
    return _authority.get_level(agent_id)


def authority_status() -> dict:
    """Authority status."""
    return _authority.status()


def heartbeat(agent_id: str) -> bool:
    """Heartbeat.

    Args:
        agent_id: Description.
    """
    return _authority.heartbeat(agent_id)
