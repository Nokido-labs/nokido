#!/usr/bin/env python3
"""forge_ble_buddy.py — Nokido = "Hardware Buddy" BLE de Claude Desktop (Couche 7, GOUVERNÉ).

Émule en SOFTWARE le device ESP32 (anthropics/claude-desktop-buddy) : périphérique BLE GATT
(Nordic UART) annoncé `Claude-Nokido`. Claude Desktop (dev-mode ON, "Open Hardware Buddy")
le scanne, s'y connecte, pousse heartbeats + prompts de permission ; Nokido DÉCIDE et renvoie
once/deny. => Nokido gouverne les approbations d'outils du desktop via un canal hardware.

⚠⚠ GOUVERNÉ, JAMAIS auto-approve aveugle. Décision via garde (patterns destructifs -> deny,
sinon once) + extension gate Nokido. FAIL-CLOSED (doute -> deny) pour préserver le
human-in-the-loop. NE JAMAIS transformer en rubber-stamp.

Protocole (REFERENCE.md) :
  Service  6e400001-b5a3-f393-e0a9-e50e24dcca9e
  RX(write,  desktop->device) 6e400002-...   TX(notify, device->desktop) 6e400003-...
  Wire = UTF-8 JSON, 1 objet/ligne, terminé \\n.
  prompt  (desktop->device) : {"prompt":{"id","tool","hint"}}  (dans le heartbeat)
  décision(device->desktop) : {"cmd":"permission","id":...,"decision":"once"|"deny"}

Périphérique BLE => `bless` (bleak = CENTRAL only). `pip install bless`.
Session OWNER (radio Bluetooth). Runtime à VALIDER (pas de radio en sandbox).
Usage : LAFORGE_PYTHON tools/forge_ble_buddy.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/node : hardware buddy BLE de Claude Desktop, emule en logiciel"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="[ble_buddy] %(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ble_buddy")

NUS = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # desktop -> device (write)
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device -> desktop (notify)
DEVICE_NAME = "Claude-Nokido"

_DANGER = re.compile(
    r"rm\s+-rf|rm\s+-fr|\bdel\s+/|format\s|mkfs|drop\s+table|truncate\s+table|shutdown|reboot"
    r"|:\(\)\s*\{|reg\s+delete|rmdir\s+/s|Remove-Item.*-Recurse|git\s+push.*--force|curl.*\|\s*sh",
    re.I,
)


def govern(tool: str, hint: str) -> str:
    """Décision once/deny GOUVERNÉE (jamais aveugle). Destructif -> deny, sinon once.
    FAIL-CLOSED : toute erreur -> deny (human-in-the-loop préservé)."""
    try:
        if _DANGER.search(f"{tool} {hint}"):
            log.warning("DENY (pattern destructif) tool=%s hint=%s", tool, str(hint)[:80])
            return "deny"
        # Extension : consulter forge_orchestration_gate / forge_videur pour un verdict
        # plus fin (ring/qualité). Best-effort, jamais bloquant.
        return "once"
    except Exception:  # noqa: BLE001
        return "deny"


class _Buddy:
    def __init__(self) -> None:
        self.rxbuf = b""
        self.server = None
        self.tx_state = {"total": 0, "running": 0, "waiting": 0, "msg": "Nokido buddy actif"}

    def _notify(self, obj: dict) -> None:
        try:
            line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            ch = self.server.get_characteristic(TX_UUID)
            ch.value = bytearray(line)
            self.server.update_value(NUS, TX_UUID)
        except Exception as e:  # noqa: BLE001
            log.error("notify échec: %s", e)

    def on_write(self, characteristic, value, **kwargs) -> None:
        """RX callback (desktop -> device). Accumule les lignes, traite les prompts."""
        self.rxbuf += bytes(value)
        while b"\n" in self.rxbuf:
            raw, self.rxbuf = self.rxbuf.split(b"\n", 1)
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                continue
            prompt = msg.get("prompt") if isinstance(msg, dict) else None
            if isinstance(prompt, dict) and prompt.get("id"):
                decision = govern(prompt.get("tool", ""), prompt.get("hint", ""))
                self._notify({"cmd": "permission", "id": prompt["id"], "decision": decision})
                log.info("prompt %s tool=%s -> %s", prompt["id"], prompt.get("tool"), decision)

    def on_read(self, characteristic, **kwargs):
        try:
            return bytearray((json.dumps(self.tx_state, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:  # noqa: BLE001
            return bytearray(b"{}\n")


async def main() -> int:
    try:
        from bless import (  # type: ignore
            BlessServer,
            GATTAttributePermissions,
            GATTCharacteristicProperties,
        )
    except Exception as e:  # noqa: BLE001
        print(f"forge_ble_buddy: import bless ECHOUE: {type(e).__name__}: {e}", file=sys.stderr)
        print("  -> conflit probable bless/bleak/winrt. Combo connu compatible :", file=sys.stderr)
        print('     pip install "bless==0.3.0" "bleak==1.1.1"  (bless 0.3 = winrt 2.0.0b1)', file=sys.stderr)
        print("  -> ET dans l'env laforge_py314, pas le base py312.", file=sys.stderr)
        return 2

    buddy = _Buddy()
    server = BlessServer(name=DEVICE_NAME)
    buddy.server = server
    server.read_request_func = buddy.on_read
    server.write_request_func = lambda ch, value, **kw: buddy.on_write(ch, value, **kw)

    await server.add_new_service(NUS)
    await server.add_new_characteristic(
        NUS, RX_UUID,
        GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
        None, GATTAttributePermissions.writeable,
    )
    await server.add_new_characteristic(
        NUS, TX_UUID,
        GATTCharacteristicProperties.notify | GATTCharacteristicProperties.read,
        bytearray(b"{}\n"), GATTAttributePermissions.readable,
    )
    await server.start()
    log.info("BLE buddy '%s' UP (Nordic UART) — attend Claude Desktop (dev-mode).", DEVICE_NAME)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        try:
            await server.stop()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
