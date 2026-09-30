#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_swarm_telemetry_guard.py — S5 sur la télémétrie multicast (essaim réseau).

UDP multicast = ZÉRO auth → un nœud LAN rogue peut INJECTER un faux vecteur WorldModel et
empoisonner les index USearch du cluster. Cette couche (transport-AGNOSTIQUE, se branche sur
le NATS/UDP de Gemini) :
  - sign_vector   : encadre + HMAC-SHA256 (clé forge_integrity) AVANT broadcast (egress)
  - verify_vector : vérifie HMAC + fraîcheur (anti-replay) à l'INGESTION (avant update index)
  - egress_ok     : membrane S5 — ce qui PEUT être broadcasté (jamais de secret en clair)

Compose forge_integrity (HMAC) — anti-dup, ne réimplémente pas la crypto d'identité.
Frame : MAGIC(4) | agent_len(2) | agent | ts(8 double BE) | hmac(32) | payload
"""
from __future__ import annotations

import hashlib
import hmac
import struct
import time
from nokido_agent.app.forge_secrets import get_secret

MAGIC = b"LFV1"
_HDR_MIN = 4 + 2 + 8 + 32  # hors agent + payload
_SECRET_OVERRIDE = None  # hook test/inject


def _secret() -> bytes:
    if _SECRET_OVERRIDE is not None:
        return _SECRET_OVERRIDE
    try:
        from nokido_agent.app.forge_integrity import get_manager
        s = getattr(get_manager(), "_secret", None)
        if s:
            return s if isinstance(s, bytes) else str(s).encode("utf-8")
    except Exception:  # noqa: BLE001
        pass
    import os
    return get_secret("LAFORGE_TELEMETRY_KEY") or "laforge-telemetry-dev".encode("utf-8")


def sign_vector(payload: bytes, agent: str, ts: float | None = None) -> bytes:
    """Encadre + signe un vecteur AVANT broadcast multicast (egress émetteur)."""
    ts = time.time() if ts is None else float(ts)
    a = agent.encode("utf-8")[:255]
    head = MAGIC + struct.pack(">H", len(a)) + a + struct.pack(">d", ts)
    mac = hmac.new(_secret(), head + payload, hashlib.sha256).digest()
    return head + mac + payload


def verify_vector(frame: bytes, max_age_s: float = 10.0, now: float | None = None) -> dict:
    """Vérifie un frame reçu AVANT d'updater l'index USearch. {ok, agent, ts, payload, reason}."""
    now = time.time() if now is None else float(now)
    if len(frame) < _HDR_MIN or frame[:4] != MAGIC:
        return {"ok": False, "reason": "frame invalide"}
    alen = struct.unpack(">H", frame[4:6])[0]
    if len(frame) < 6 + alen + 8 + 32:
        return {"ok": False, "reason": "frame tronquee"}
    off = 6
    agent = frame[off:off + alen].decode("utf-8", "replace"); off += alen
    ts = struct.unpack(">d", frame[off:off + 8])[0]; off += 8
    mac = frame[off:off + 32]; off += 32
    payload = frame[off:]
    head = frame[:6 + alen + 8]
    expected = hmac.new(_secret(), head + payload, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return {"ok": False, "reason": "HMAC invalide (injection?)", "agent": agent}
    if abs(now - ts) > max_age_s:
        return {"ok": False, "reason": f"perime/replay ({now - ts:.1f}s)", "agent": agent}
    return {"ok": True, "agent": agent, "ts": ts, "payload": payload}


_SECRET_PATTERNS = (b"begin private key", b"api_key", b"password", b"bearer ", b"akia")


def egress_ok(payload: bytes, is_text: bool = False) -> bool:
    """Membrane S5 : ce qui PEUT être broadcasté. Vecteurs binaires (WorldModel) = OK.
    Texte = scan DLP best-effort (jamais de secret sur le multicast non chiffré)."""
    if not is_text:
        return True
    low = payload.lower()
    return not any(p in low for p in _SECRET_PATTERNS)


def pack_meta(meta: dict) -> bytes:
    """Encode des métadonnées atomiques (worker_id, tags GOAP — les ~766o libres de la trame
    9000) en JSON length-prefixed, INCLUS dans la frame signée (atomique, 1 paquet=1 pensée)."""
    import json
    b = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    return struct.pack(">H", len(b)) + b


def unpack_meta(body: bytes):
    """Sépare (meta, vector) d'un body = pack_meta()+vecteur. (None, body) si pas de meta."""
    import json
    if len(body) < 2:
        return None, body
    mlen = struct.unpack(">H", body[:2])[0]
    if 2 + mlen > len(body):
        return None, body
    try:
        meta = json.loads(body[2:2 + mlen].decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None, body
    return meta, body[2 + mlen:]


def broadcast_vector(send_fn, payload: bytes, agent: str, meta: dict | None = None,
                     is_text: bool = False) -> dict:
    """SEAM émission (à brancher sur le socket multicast de Gemini) : egress S5 -> sign ->
    send_fn(frame). meta = métadonnées atomiques incluses DANS la frame signée."""
    if not egress_ok(payload, is_text=is_text):
        return {"sent": False, "reason": "egress refuse (membrane S5)"}
    body = (pack_meta(meta) + payload) if meta is not None else payload
    frame = sign_vector(body, agent)
    try:
        send_fn(frame)
        return {"sent": True, "bytes": len(frame)}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "reason": f"transport: {e}"}


def ingest_vector(frame: bytes, update_fn=None, max_age_s: float = 10.0,
                  has_meta: bool = False) -> dict:
    """SEAM réception : verify (HMAC + anti-replay) AVANT d'updater l'index USearch.
    update_fn(vector, agent, meta) appelé SEULEMENT si signature valide (anti-injection)."""
    v = verify_vector(frame, max_age_s=max_age_s)
    if not v.get("ok"):
        return v
    meta, vector = (unpack_meta(v["payload"]) if has_meta else (None, v["payload"]))
    v["meta"] = meta
    v["vector"] = vector
    if update_fn is not None:
        try:
            update_fn(vector, v["agent"], meta)
            v["indexed"] = True
        except Exception as e:  # noqa: BLE001
            v["indexed"] = False
            v["index_error"] = str(e)
    return v
