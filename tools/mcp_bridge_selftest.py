#!/usr/bin/env python3
"""mcp_bridge_selftest.py — valide B : _write_out (lock) + watcher capabilities.

Démarre _watch_capabilities, écrit un faux event capability.forged dans le miroir
(sandbox/reflexion.jsonl), capture stdout, vérifie qu'un notifications/tools/
list_changed est poussé. Run : `LAFORGE_PYTHON tools/mcp_bridge_selftest.py` (trusted).
"""
import sys
import io
import json
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import mcp_stdio_bridge as b  # noqa: E402


def main() -> int:
    # 1. _write_out serialise (lock) + framing \n
    buf = io.BytesIO()

    class _F:
        buffer = buf

    real = sys.stdout
    sys.stdout = _F()
    try:
        b._write_out(b'{"jsonrpc":"2.0","method":"x"}')
    finally:
        sys.stdout = real
    assert buf.getvalue() == b'{"jsonrpc":"2.0","method":"x"}\n', buf.getvalue()
    assert callable(b._watch_capabilities) and b._STDOUT_LOCK is not None

    # 2. watcher e2e : faux capability.forged dans le miroir -> push list_changed
    mirror = ROOT / "sandbox" / "reflexion.jsonl"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    buf2 = io.BytesIO()

    class _F2:
        buffer = buf2

    sys.stdout = _F2()
    try:
        threading.Thread(target=b._watch_capabilities, daemon=True).start()
        time.sleep(1.3)  # laisse le watcher seek a la fin du miroir
        with open(mirror, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": 1, "topic": "capabilities",
                                "kind": "capability.forged", "data": {"name": "z"}}) + "\n")
        time.sleep(2.6)  # poll 1s + debounce -> push
    finally:
        sys.stdout = real

    pushed = b"notifications/tools/list_changed" in buf2.getvalue()
    assert pushed, f"pas de push: {buf2.getvalue()[:200]!r}"
    print("SELFTEST-B OK | _write_out lock+framing | watcher push list_changed sur capability.forged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
