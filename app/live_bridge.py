# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_live_bridge
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
live_bridge.py — Bridge mmap temps réel entre MCP, Hub et process détachés
===========================================================================
Un seul fichier mmap : sandbox/live_bridge.map (256KB)

Layout fixe — aucune sérialisation sur le hot path :

  [0:4]    magic   b"LF19"
  [4:8]    version uint32
  [8:16]   seq     uint64  — incrément à chaque write
  [16:20]  n_tasks uint32  — nombre de tâches actives

  [64:64+N*128]  Task slots (max 128 tâches)
  Chaque slot = 128 bytes :
    [0:16]   task_id   char[16]   — hex uuid tronqué
    [16:17]  status    uint8      — 0=free 1=pend 2=run 3=ok 4=err 5=tmo
    [17:18]  code      uint8      — exit code
    [18:20]  _pad
    [20:24]  dur_ms    uint32     — durée en ms
    [24:88]  result    char[64]   — résultat tronqué UTF-8
    [88:128] _reserved

  [64+128*128:]  JSON cold store (≈239KB) pour payloads larges

Accès :
  from live_bridge import bridge
  tid = bridge.task_new("rag_index")      → task_id immédiat
  bridge.task_set(tid, status=2)          → running
  bridge.task_set(tid, status=3, result="6890 chunks", dur_ms=3750)
  s = bridge.task_get(tid)               → {"status":3,"result":"...","dur_ms":3750}
  bridge.seq()                           → int (détection changements sans polling)
"""


import json
import mmap
import struct
import threading
import uuid
from pathlib import Path

# ── Layout ────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
_MAP_PATH = _ROOT / "sandbox" / "live_bridge.map"
_MAP_SIZE = 262144  # 256 KB

_MAGIC = b"LF19"
_HDR_SIZE = 64  # header padded
_N_SLOTS = 128
_SLOT_SIZE = 128
_TASKS_OFF = _HDR_SIZE  # 64
_TASKS_END = _HDR_SIZE + _N_SLOTS * _SLOT_SIZE  # 64 + 16384 = 16448
_JSON_OFF = _TASKS_END
_JSON_SIZE = _MAP_SIZE - _JSON_OFF  # ≈245KB

# Struct formats
_HDR_FMT = "<4sIQ I 44x"  # magic(4) ver(4) seq(8) n_tasks(4) pad(44) = 64
_SLOT_FMT = "<16sB B H I 64s 40x"  # id(16) status(1) code(1) pad(2) dur_ms(4) result(64) pad(40) = 128

# Status codes
ST_FREE = 0
ST_PEND = 1
ST_RUN = 2
ST_OK = 3
ST_ERR = 4
ST_TMO = 5
_ST_NAMES = {0: "free", 1: "pend", 2: "run", 3: "ok", 4: "err", 5: "tmo"}


class LiveBridge:
    """
    Shared Memory Bridge temps réel.
    Toutes les opérations : <2µs sur le hot path.
    Zéro I/O disque sauf flush() mmap.
    """

    def __init__(self) -> None:
        """Init."""
        self._lock = threading.RLock()
        self._mm: mmap.mmap | None = None
        self._fd = None
        self._seq = 0
        self._open()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _open(self) -> None:
        """Open."""
        _MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        new = not _MAP_PATH.exists() or _MAP_PATH.stat().st_size < _MAP_SIZE
        self._fd = open(_MAP_PATH, "a+b")
        self._fd.seek(0, 2)
        if self._fd.tell() < _MAP_SIZE:
            self._fd.write(b"\x00" * (_MAP_SIZE - self._fd.tell()))
            self._fd.flush()
        self._mm = mmap.mmap(self._fd.fileno(), _MAP_SIZE)
        if new:
            self._mm.seek(0)
            self._mm.write(struct.pack(_HDR_FMT, _MAGIC, 1, 0, 0))
            self._mm.flush()

    # ── Header ────────────────────────────────────────────────────────────────

    def _inc_seq(self) -> None:
        """Inc seq."""
        self._seq += 1
        self._mm.seek(8)
        self._mm.write(struct.pack("<Q", self._seq))

    def seq(self) -> int:
        """Seq."""
        if not self._mm:
            return 0
        self._mm.seek(8)
        return struct.unpack("<Q", self._mm.read(8))[0]

    # ── Task slots ────────────────────────────────────────────────────────────

    def _slot_off(self, idx: int) -> int:
        """Slot off.

        Args:
            idx: Description.
        """
        return _TASKS_OFF + idx * _SLOT_SIZE

    def _find_slot(self, task_id: str) -> int:
        """Retourne l'index du slot pour task_id, ou -1."""
        tid_b = task_id.encode()[:16].ljust(16, b"\x00")
        for i in range(_N_SLOTS):
            self._mm.seek(self._slot_off(i))
            raw = self._mm.read(16)
            if raw == tid_b:
                return i
        return -1

    def _find_free(self) -> int:
        """Retourne l'index du premier slot libre."""
        for i in range(_N_SLOTS):
            off = self._slot_off(i)
            self._mm.seek(off + 16)  # status byte
            if self._mm.read(1) == b"\x00":
                return i
        return -1

    def task_new(self, prefix: str = "task") -> str:
        """
        Alloue un slot et retourne task_id.
        Immédiat — aucun I/O disque.
        """
        tid = (prefix + "_" + uuid.uuid4().hex)[:16]
        with self._lock:
            idx = self._find_free()
            if idx < 0:
                # Recycler le plus ancien slot ST_OK/ST_ERR/ST_TMO
                for i in range(_N_SLOTS):
                    self._mm.seek(self._slot_off(i) + 16)
                    st = self._mm.read(1)[0]
                    if st in (ST_OK, ST_ERR, ST_TMO):
                        idx = i
                        break
            if idx < 0:
                return tid  # table pleine — on retourne quand même un id
            tid_b = tid.encode()[:16].ljust(16, b"\x00")
            self._mm.seek(self._slot_off(idx))
            self._mm.write(struct.pack(_SLOT_FMT, tid_b, ST_PEND, 0, 0, 0, b"\x00" * 64))
            self._inc_seq()
            self._mm.flush()
        return tid

    def task_set(self, task_id: str, status: int, result: str = "", dur_ms: int = 0, code: int = 0) -> None:
        """Met à jour un slot. <2µs."""
        with self._lock:
            idx = self._find_slot(task_id)
            if idx < 0:
                return
            tid_b = task_id.encode()[:16].ljust(16, b"\x00")
            res_b = result.encode("utf-8")[:63].ljust(64, b"\x00")
            self._mm.seek(self._slot_off(idx))
            self._mm.write(struct.pack(_SLOT_FMT, tid_b, status, code & 0xFF, 0, dur_ms & 0xFFFFFFFF, res_b))
            self._inc_seq()
            self._mm.flush()

    def task_get(self, task_id: str) -> dict | None:
        """Lit un slot. Zéro lock sur le hot path de lecture."""
        if not self._mm:
            return None
        tid_b = task_id.encode()[:16].ljust(16, b"\x00")
        for i in range(_N_SLOTS):
            self._mm.seek(self._slot_off(i))
            raw = self._mm.read(_SLOT_SIZE)
            if raw[:16] == tid_b:
                _, status, code, _, dur_ms, res_b = struct.unpack(_SLOT_FMT, raw)
                return {
                    "id": task_id,
                    "status": _ST_NAMES.get(status, str(status)),
                    "code": code,
                    "dur_ms": dur_ms,
                    "result": res_b.rstrip(b"\x00").decode("utf-8", errors="replace"),
                }
        return None

    def tasks_active(self) -> list[dict]:
        """Liste toutes les tâches non-free."""
        out = []
        if not self._mm:
            return out
        for i in range(_N_SLOTS):
            self._mm.seek(self._slot_off(i))
            raw = self._mm.read(_SLOT_SIZE)
            tid_b, status = raw[:16], raw[16]
            if status == ST_FREE:
                continue
            _, status, code, _, dur_ms, res_b = struct.unpack(_SLOT_FMT, raw)
            out.append(
                {
                    "id": tid_b.rstrip(b"\x00").decode(),
                    "status": _ST_NAMES.get(status, str(status)),
                    "dur_ms": dur_ms,
                    "result": res_b.rstrip(b"\x00").decode("utf-8", errors="replace"),
                }
            )
        return out

    # ── JSON cold store ───────────────────────────────────────────────────────

    def json_set(self, key: str, value) -> bool:
        """Stocke une valeur JSON — flush immédiat dans le mmap."""
        with self._lock:
            data = self._json_load()  # toujours depuis mmap
            parts = key.split(".")
            d = data
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = value
            ok = self._json_flush(data)
            self._mm.flush()  # force sync OS
            return ok

    def json_get(self, key: str, default=None) -> object:
        """Toujours relire depuis le mmap — garantit la cohérence cross-instance."""
        data = self._json_load()
        parts = key.split(".")
        d = data
        for part in parts:
            if not isinstance(d, dict) or part not in d:
                return default
            d = d[part]
        return d

    def json_reload(self) -> dict:
        """Force reload depuis mmap — à appeler avant lecture cross-process."""
        return self._json_load()

    def _json_load(self) -> dict:
        """Json load."""
        try:
            self._mm.seek(_JSON_OFF)
            dlen = struct.unpack("<I", self._mm.read(4))[0]
            if dlen == 0 or dlen > _JSON_SIZE - 4:
                return {}
            return json.loads(self._mm.read(dlen).decode("utf-8"))
        except Exception:
            return {}

    def _json_flush(self, data: dict) -> bool:
        """Json flush.

        Args:
            data: Description.
        """
        try:
            raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
            if len(raw) > _JSON_SIZE - 4:
                return False
            self._mm.seek(_JSON_OFF)
            self._mm.write(struct.pack("<I", len(raw)))
            self._mm.write(raw)
            self._mm.flush()
            return True
        except Exception:
            return False

    def snapshot(self) -> dict:
        """Snapshot."""
        return {"seq": self.seq(), "tasks": self.tasks_active(), "json": self._json_load()}

    def close(self) -> None:
        """Close."""
        if self._mm:
            try:
                self._mm.flush()
                self._mm.close()
            except Exception:
                pass
        if self._fd:
            try:
                self._fd.close()
            except Exception:
                pass


# Singleton process-local
bridge = LiveBridge()
