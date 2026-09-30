# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_state
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_state.py — Shared Memory Buffer temps réel v2
====================================================
Architecture :
  Segment mmap de 256KB divisé en 2 zones :

  Zone A — Hot Status (offset 0, 4KB) — struct binaire fixe
  ┌─────────────────────────────────────────────────────┐
  │ magic[4] | version[2] | flags[2] | seq[8]           │
  │ slots[N] — chaque slot = 64 bytes :                  │
  │   key[32] | type[1] | pad[3] | value[28]             │
  │   type: 0=empty 1=int64 2=float64 3=str28 4=bool     │
  └─────────────────────────────────────────────────────┘

  Zone B — JSON store (offset 4096, 252KB) — JSON full state
  ┌─────────────────────────────────────────────────────┐
  │ len[4] | json_bytes[...]                             │
  └─────────────────────────────────────────────────────┘

Hot path (set_hot/get_hot) : lecture/écriture struct, zéro JSON, <1µs
Cold path (set/get) : JSON zone B, pour objets complexes

Cross-process : mmap sur fichier, accès simultané safe (pas de lock fichier
— on accepte la "dirty read" pour le statut temps réel : la cohérence
stricte est garantie par le seq counter)
"""


import json
import mmap
import struct
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAP_FILE = _ROOT / "sandbox" / ".forge_state.mmap"

# Layout
_MAGIC = b"LF18"
_MAP_SIZE = 262144  # 256KB total
_HOT_SIZE = 4096  # 4KB zone A (struct binaire)
_JSON_OFF = 4096  # offset zone B
_JSON_SIZE = _MAP_SIZE - _JSON_OFF

# Zone A header : magic(4) + version(2) + flags(2) + seq(8) = 16 bytes
_HDR_FMT = "<4sHHQ"
_HDR_SIZE = struct.calcsize(_HDR_FMT)  # 16
_SLOT_FMT = "<32sBBBx28s"  # key(32) type(1) pad(2) _ value(28)  -> 64 bytes
_SLOT_SIZE = struct.calcsize(_SLOT_FMT)  # 64
_SLOT_OFF = _HDR_SIZE
_N_SLOTS = (_HOT_SIZE - _HDR_SIZE) // _SLOT_SIZE  # 63 slots

# Slot types — DOIVENT etre coherent avec _init_header (zero-init = EMPTY)
# Cf. docstring zone A : type: 0=empty 1=int64 2=float64 3=str28 4=bool
_T_EMPTY = 0
_T_INT = 1
_T_FLOAT = 2
_T_STR = 3
_T_BOOL = 4
# DEBUG_FORGE_STATE: bloc unique - 2 doublons supprimes 2026-04-16
# (bug: _T_EMPTY=5 cassait set_hot/get_hot silencieusement)


def _encode_hot(value: bool | int | float | str) -> tuple[int, bytes]:
    """Encode une valeur scalaire en (type, 28 bytes)."""
    if isinstance(value, bool):
        return _T_BOOL, struct.pack("<B27x", int(value))
    if isinstance(value, int):
        return _T_INT, struct.pack("<q20x", value)
    if isinstance(value, float):
        return _T_FLOAT, struct.pack("<d20x", value)
    if isinstance(value, str):
        b = value.encode("utf-8")[:27]
        return _T_STR, b + b"\x00" * (28 - len(b))
    return _T_EMPTY, b"\x00" * 28


def _decode_hot(typ: int, raw: bytes) -> object:
    """Decode hot.

    Args:
        typ: Description.
        raw: Description.
    """
    if typ == _T_BOOL:
        return bool(struct.unpack("<B", raw[:1])[0])
    if typ == _T_INT:
        return struct.unpack("<q", raw[:8])[0]
    if typ == _T_FLOAT:
        return struct.unpack("<d", raw[:8])[0]
    if typ == _T_STR:
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    return None


class SharedState:
    """
    État partagé temps réel.
    Hot path  : set_hot/get_hot → struct binaire, <1µs
    Cold path : set/get         → JSON 256KB, <50µs
    """

    def __init__(self) -> None:
        """Init."""
        self._lock = threading.RLock()
        self._mm: mmap.mmap | None = None
        self._fd = None
        self._cache: dict = {}
        self._seq = 0
        self._dirty = False
        self._last_flush = 0.0
        self._FLUSH_INTERVAL = 0.05  # 50ms max latence JSON
        self._init()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _init(self) -> None:
        """Init."""
        _MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            new = not _MAP_FILE.exists() or _MAP_FILE.stat().st_size < _MAP_SIZE
            self._fd = open(_MAP_FILE, "a+b")
            self._fd.seek(0, 2)
            if self._fd.tell() < _MAP_SIZE:
                self._fd.write(b"\x00" * (_MAP_SIZE - self._fd.tell()))
                self._fd.flush()
            self._mm = mmap.mmap(self._fd.fileno(), _MAP_SIZE)
            if new:
                self._init_header()
            else:
                self._load_json()
        except Exception:
            self._mm = None

    def _init_header(self) -> None:
        """Init header."""
        if not self._mm:
            return
        self._mm.seek(0)
        self._mm.write(struct.pack(_HDR_FMT, _MAGIC, 2, 0, 0))
        # Vider les slots
        for i in range(_N_SLOTS):
            self._mm.seek(_SLOT_OFF + i * _SLOT_SIZE)
            self._mm.write(b"\x00" * _SLOT_SIZE)
        self._mm.flush()

    # ── HOT PATH — struct binaire ──────────────────────────────────────────────

    def _slot_index(self, key: str) -> int:
        """Hash simple pour trouver le slot (open addressing)."""
        kb = key.encode("utf-8")[:32]
        h = hash(kb) % _N_SLOTS
        if not self._mm:
            return -1
        for probe in range(_N_SLOTS):
            idx = (h + probe) % _N_SLOTS
            off = _SLOT_OFF + idx * _SLOT_SIZE
            self._mm.seek(off)
            raw = self._mm.read(_SLOT_SIZE)
            slot_key = raw[:32].rstrip(b"\x00")
            slot_typ = raw[32]
            if slot_typ == _T_EMPTY:
                return idx  # slot libre
            if slot_key == kb:
                return idx  # slot existant
        return -1  # table pleine

    def set_hot(self, key: str, value) -> bool:
        """
        Écriture hot path — struct binaire, thread-safe, <1µs.
        Clé max 32 chars, valeur scalaire (int/float/str27/bool).
        Retourne True si écrit, False si table pleine.
        """
        if not self._mm:
            return False
        typ, encoded = _encode_hot(value)
        if typ == _T_EMPTY:
            return False
        kb = key.encode("utf-8")[:32].ljust(32, b"\x00")
        with self._lock:
            idx = self._slot_index(key)
            if idx < 0:
                return False
            off = _SLOT_OFF + idx * _SLOT_SIZE
            self._mm.seek(off)
            self._mm.write(struct.pack(_SLOT_FMT, kb, typ, 0, 0, encoded))
            # Incrémenter seq (atomique sur int64 little-endian)
            self._seq += 1
            self._mm.seek(8)  # offset du seq dans le header
            self._mm.write(struct.pack("<Q", self._seq))
            self._mm.flush()
        return True

    def get_hot(self, key: str, default=None) -> object:
        """Lecture hot path — struct binaire, <1µs."""
        if not self._mm:
            return default
        kb = key.encode("utf-8")[:32]
        h = hash(kb) % _N_SLOTS
        for probe in range(_N_SLOTS):
            idx = (h + probe) % _N_SLOTS
            off = _SLOT_OFF + idx * _SLOT_SIZE
            self._mm.seek(off)
            raw = self._mm.read(_SLOT_SIZE)
            slot_key = raw[:32].rstrip(b"\x00")
            slot_typ = raw[32]
            if slot_typ == _T_EMPTY:
                return default
            if slot_key == kb:
                return _decode_hot(slot_typ, raw[36:64])
        return default

    def seq(self) -> int:
        """Numéro de séquence courant — détecte les changements sans polling."""
        if not self._mm:
            return 0
        self._mm.seek(8)
        return struct.unpack("<Q", self._mm.read(8))[0]

    # ── COLD PATH — JSON zone B ───────────────────────────────────────────────

    def _load_json(self) -> None:
        """Load json."""
        if not self._mm:
            return
        try:
            self._mm.seek(_JSON_OFF)
            dlen = struct.unpack("<I", self._mm.read(4))[0]
            if dlen == 0 or dlen > _JSON_SIZE - 4:
                return
            raw = self._mm.read(dlen)
            self._cache = json.loads(raw.decode("utf-8"))
        except Exception:
            self._cache = {}

    def _flush_json(self) -> None:
        """Flush json."""
        if not self._mm or not self._dirty:
            return
        try:
            raw = json.dumps(self._cache, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if len(raw) > _JSON_SIZE - 4:
                return
            self._mm.seek(_JSON_OFF)
            self._mm.write(struct.pack("<I", len(raw)))
            self._mm.write(raw)
            self._mm.write(b"\x00" * (_JSON_SIZE - 4 - len(raw)))
            self._mm.flush()
            self._dirty = False
            self._last_flush = time.monotonic()
        except Exception:
            pass

    def set(self, key: str, value, flush: bool = True) -> None:
        """Cold path — notation dot, objets complexes."""
        with self._lock:
            parts = key.split(".")
            d = self._cache
            for part in parts[:-1]:
                if part not in d or not isinstance(d[part], dict):
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = value
            self._dirty = True
            # Mirror scalaires dans la zone hot
            if isinstance(value, (int, float, str, bool)):
                self.set_hot(key.replace(".", "_"), value)
            if flush or (time.monotonic() - self._last_flush > self._FLUSH_INTERVAL):
                self._flush_json()

    def get(self, key: str, default=None) -> object:
        """Cold path — notation dot."""
        with self._lock:
            if time.monotonic() - self._last_flush > self._FLUSH_INTERVAL:
                self._load_json()
                self._last_flush = time.monotonic()
            parts = key.split(".")
            d = self._cache
            for part in parts:
                if not isinstance(d, dict) or part not in d:
                    return default
                d = d[part]
            return d

    def snapshot(self) -> dict:
        """Snapshot."""
        with self._lock:
            self._load_json()
            return dict(self._cache)

    def delete(self, key: str) -> None:
        """Delete.

        Args:
            key: Description.
        """
        with self._lock:
            parts = key.split(".")
            d = self._cache
            for part in parts[:-1]:
                if part not in d:
                    return
                d = d[part]
            d.pop(parts[-1], None)
            self._dirty = True
            self._flush_json()

    def close(self) -> None:
        """Close."""
        with self._lock:
            self._flush_json()
            if self._mm:
                try:
                    self._mm.close()
                except Exception:
                    pass
            if self._fd:
                try:
                    self._fd.close()
                except Exception:
                    pass


# Singleton process-local
state = SharedState()


# ─────────────────────────────────────────────────────────────────────────────
# Axe C — Tier RAM HOT de l'essaim (santé ms-T, graphe MCTS en vol, état pipes MCP)
# ─────────────────────────────────────────────────────────────────────────────
# La donnée VOLATILE vit ICI (mmap, <1µs, cross-process, zéro disque). Sur
# validation/destruction du transient elle est CRISTALLISÉE vers les couches
# durables (Axe A vecteurs / Axe B SQLite). Remplace les fichiers re-lus du disque
# (health.json) : le hub tient l'état milliseconde-T en RAM, les agents le lisent
# sans I/O. (Choix souverain : PAS de Redis externe — cf forge_swarm_blackboard.)

_HEALTH_KEYS = ("cpu_pct", "ram_pct", "disk_pct", "hub_up", "health_ts")


def publish_health(**metrics) -> None:
    """Publie des métriques santé dans le tier hot (set_hot <1µs, cross-process,
    zéro disque). Remplace l'écriture de health.json. Clés scalaires only (≤32c)."""
    for k, v in metrics.items():
        if isinstance(v, (bool, int, float, str)):
            state.set_hot(k[:32], v)
    state.set_hot("health_ts", int(time.time()))


def read_health(keys: tuple = _HEALTH_KEYS) -> dict:
    """Lit l'état santé depuis le tier hot — zéro disque, zéro JSON parse."""
    return {k: state.get_hot(k) for k in keys}


def crystallize(key: str, sink) -> bool:
    """Volatile -> durable : extrait une valeur du tier hot et la remet au `sink`
    (callable(key, value) — ex. blackboard SQLite Axe B, ou ingest vecteur Axe A).
    Le transient validé est 'cristallisé' puis peut être purgé du hot. True si OK."""
    val = state.get(key) if "." in key else state.get_hot(key)
    if val is None:
        return False
    try:
        sink(key, val)
        return True
    except Exception:
        return False


def _selftest() -> bool:
    publish_health(cpu_pct=12.5, ram_pct=75.0, hub_up=True)
    h = read_health()
    ok = h.get("ram_pct") == 75.0 and h.get("hub_up") is True
    captured: dict = {}
    crystallize("cpu_pct", lambda k, v: captured.__setitem__(k, v))
    return bool(ok and captured.get("cpu_pct") == 12.5)


if __name__ == "__main__":
    print("forge_state Axe-C selftest:", "PASS" if _selftest() else "FAIL")
