"""
tools/forge_dt_router_wire.py — Wire Nokido DT router decisions to Deno nervous system.
Emits routing events to Deno /intent endpoint, polls hub for events to forward.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests as _req
except ImportError:
    sys.exit("pip install requests")

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x


def _entetes_hub() -> dict:
    """En-tetes d'organe vers le hub (2026-09-24) : /nervous_system/emit exige une identite
    prouvee. Jeton propre DT_ROUTER, sinon SERVICES -- jamais le maitre."""
    try:
        racine = str(Path(__file__).resolve().parent.parent)
        if racine not in sys.path:
            sys.path.insert(0, racine)
        from nokido_agent.app.forge_hub_client import entetes_organe

        return entetes_organe("DT_ROUTER")
    except Exception as e:  # noqa: BLE001
        print(f"[dt_router] en-tetes d'organe indisponibles ({type(e).__name__}) : appel sans porteur",
              file=sys.stderr)
        return {}

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT = LAFORGE_ROOT / "sandbox" / "dt_router_wire.heartbeat"


class DTRouterWire:
    def __init__(
        self, deno_url: str = "http://localhost:8000", hub_url: str = "http://localhost:8766"
    ):
        self.deno_url = deno_url
        self.hub_url = hub_url
        self._forwarded = 0
        self._errors = 0

    def emit_routing_event(self, decision: dict) -> bool:
        # Phase 38 (2026-05-25) — bypass Deno /intent (DEPRECATED). POST direct
        # hub :8766 /nervous_system/emit. Garde fallback Deno si hub fail (compat
        # transition). ADR-001 documente la decision suppression future.
        payload = {"type": "routing_decision", "payload": decision, "source": "dt_router"}
        # Path 1 : hub Python direct (Phase 38 cible)
        try:
            r = _req.post(f"{self.hub_url}/nervous_system/emit", json=payload, timeout=5,
                          headers=_entetes_hub())
            r.raise_for_status()
            self._forwarded += 1
            return True
        except Exception as e_hub:
            # Path 2 (fallback transition) : Deno /intent legacy
            try:
                r = _req.post(f"{self.deno_url}/intent", json=payload, timeout=5)
                r.raise_for_status()
                self._forwarded += 1
                return True
            except Exception as e_deno:
                self._errors += 1
                print(f"  [WARN] both hub+deno emit failed: hub={e_hub} deno={e_deno}")
                return False

    def register_with_hub(self) -> bool:
        payload = {
            "event_type": "routing_decision",
            "callback_url": f"{self.deno_url}/intent",
            "source": "dt_router_wire",
        }
        try:
            r = _req.post(f"{self.hub_url}/register", json=payload, timeout=5)
            return r.status_code < 400
        except Exception as e:
            print(f"  [WARN] hub register failed: {e}")
            return False

    def _save_heartbeat(self):
        HEARTBEAT.parent.mkdir(exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "timestamp": time.time(),
                    "forwarded": self._forwarded,
                    "errors": self._errors,
                }
            )
        )

    def watch_and_forward(self, poll_interval: int = 2):
        print(f"[dt_router_wire] watching hub for routing events, poll={poll_interval}s")
        try:
            while True:
                try:
                    r = _req.get(
                        f"{self.hub_url}/mcp", params={"event_type": "routing_decision"}, timeout=5
                    )
                    events = r.json().get("events", []) if r.status_code < 400 else []
                    for ev in tqdm(events, desc="forwarding", unit="event", leave=False):
                        self.emit_routing_event(ev)
                except Exception:
                    pass
                self._save_heartbeat()
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self._save_heartbeat()
            print(f"\n[dt_router_wire] stopped — forwarded={self._forwarded} errors={self._errors}")


def mock_routing_decision(task: str) -> dict:
    task_lower = task.lower()
    if any(k in task_lower for k in ["code", "python", "function", "script"]):
        provider, task_type, conf = "groq", "code_generation", 0.92
    elif any(k in task_lower for k in ["exploit", "ctf", "pwn", "vuln"]):
        provider, task_type, conf = "ollama", "security_analysis", 0.88
    elif any(k in task_lower for k in ["search", "rag", "find", "query"]):
        provider, task_type, conf = "sambanova", "rag_retrieval", 0.85
    else:
        provider, task_type, conf = "mistral", "general", 0.70
    return {
        "provider": provider,
        "confidence": conf,
        "task_type": task_type,
        "task": task,
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    wire = DTRouterWire()
    ok = wire.register_with_hub()
    print(f"Hub registration: {'OK' if ok else 'FAILED (continuing)'}")

    test_tasks = [
        "Write Python code for heap exploit",
        "Search RAG for forge_rag_engine",
        "CTF pwn challenge binary",
    ]
    print("\nEmitting 3 mock decisions:")
    for task in test_tasks:
        decision = mock_routing_decision(task)
        sent = wire.emit_routing_event(decision)
        print(f"  [{'+' if sent else '-'}] {decision['task_type']} → {decision['provider']}")
        time.sleep(0.5)

    wire.watch_and_forward()
