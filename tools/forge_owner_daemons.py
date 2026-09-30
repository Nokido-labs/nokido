#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_owner_daemons.py — launcher OWNER unique (lancé en pythonw = windowless).

Tourne les daemons owner-context en threads d'UN seul process pythonw (aucune
fenêtre console), stdout/stderr redirigés vers un log fichier (pythonw → None).

  - forge_wasm_bridge.daemon        : queue wsl wasmedge (wasi_nn)
  - forge_privileged_bridge.user_daemon : pont gouverné tier USER

Lancé par la tâche planifiée LaForge-Daemons (/RU user, AtLogOn).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("tools", "app"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

# pythonw → sys.stdout/err = None → tout print() crasherait. Rediriger vers log.
LOG = ROOT / "sandbox" / "owner_daemons.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
class _StampedWriter:
    """Date chaque LIGNE écrite sur stdout/err redirigés vers le journal.

    Ces daemons tournent sous `pythonw` : leurs `print()` atterrissent tels quels
    dans `owner_daemons.log`, qui n'avait donc aucune date — 0,6 Mo d'événements
    impossibles à situer dans le temps (mandat owner 2026-07-26).

    On préfixe au DÉBUT DE LIGNE seulement : `print()` émet le texte puis le "\\n"
    en deux écritures, et dater chaque fragment produirait des dates au milieu
    des phrases. L'état `_bol` porte cette frontière.
    """

    def __init__(self, fh):
        self._fh = fh
        self._bol = True

    def _now(self) -> str:
        try:
            from nokido_agent.app.forge_timecode import now_iso

            return now_iso()
        except Exception:  # noqa: BLE001
            from datetime import datetime as _dt
            from datetime import timezone as _tz

            return _dt.now(tz=_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def write(self, s):
        if not s:
            return 0
        stamp = self._now()
        out = []
        for part in s.split("\n"):
            if self._bol and part:
                out.append("%s %s" % (stamp, part))
                self._bol = False
            else:
                out.append(part)
        text = "\n".join(out)
        if s.endswith("\n"):
            self._bol = True
        return self._fh.write(text)

    def flush(self):
        try:
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


if sys.stdout is None or sys.stderr is None:
    _lf = open(LOG, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = _StampedWriter(_lf)

print(f"[owner_daemons] launcher up {time.time()}", flush=True)


def _guarded(fn, name: str) -> None:
    while True:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - une boucle ne doit jamais tuer l'autre
            print(f"[owner_daemons] {name} crashed: {e!r} — restart 2s", flush=True)
            time.sleep(2)


def main() -> int:
    from nokido_agent.tools import forge_privileged_bridge as pb
    from nokido_agent.tools import forge_wasm_bridge as wb

    # Seed la clé HMAC du pont dans le vault AU DÉMARRAGE (daemon = owner, peut écrire) :
    # garantit que le 1er appel client (sandbox, lecture seule du vault) trouve la clé.
    try:
        pb._bridge_key()
        print("[owner_daemons] HMAC key seeded", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[owner_daemons] seed key err: {e!r}", flush=True)

    from nokido_agent.tools import forge_backend_power as bp  # autopoïèse : lazy-start wakes + idle-unload VRAM (on-demand)

    threading.Thread(target=_guarded, args=(wb.daemon, "wasm_bridge"), daemon=True).start()
    threading.Thread(target=_guarded, args=(pb.user_daemon, "priv_bridge"), daemon=True).start()
    threading.Thread(
        target=_guarded, args=(lambda: bp.daemon(15.0, 60.0), "backend_power"), daemon=True
    ).start()
    print("[owner_daemons] 3 daemons threads started", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
