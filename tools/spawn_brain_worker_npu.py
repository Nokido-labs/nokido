"""Spawn brain_worker.py avec env NPU ryzen-ai-1.7.0 en process détaché caché.

Subprocess flags Windows :
- DETACHED_PROCESS : pas de console parent
- CREATE_NO_WINDOW : pas de fenêtre terminal
- CREATE_NEW_PROCESS_GROUP : Ctrl+C pas propagé

Logs : sandbox/brain_worker_npu.log + heartbeat sandbox/brain_worker_npu.heartbeat
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NPU_PYTHON = Path(__import__("os").path.expanduser(r"~/miniforge3/envs/ryzen-ai-final/python.exe"))
SCRIPT = ROOT / "app" / "brain_worker.py"
LOG = ROOT / "sandbox" / "brain_worker_npu.log"
PID_FILE = ROOT / "sandbox" / "brain_worker_npu.pid"

# Flags Windows pour process caché détaché
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def main() -> int:
    if not NPU_PYTHON.exists():
        print(f"ERR: ryzen-ai-final python introuvable : {NPU_PYTHON}")
        return 2
    if not SCRIPT.exists():
        print(f"ERR: brain_worker.py introuvable : {SCRIPT}")
        return 3

    # Kill ancien si tourne
    try:
        import psutil

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if "brain_worker.py" in cmd:
                    p.kill()
                    print(f"[+] killed old brain_worker PID {p.info['pid']}")
            except Exception:
                pass
    except ImportError:
        pass
    time.sleep(1)

    # Setup log + env NPU
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(LOG, "ab", buffering=0)

    env = os.environ.copy()
    env["XLNX_VART_FIRMWARE"] = r"C:\Windows\System32\AMD\1x4_3.5.0.0-2044_ipu_2.xclbin"
    env["XLNX_TARGET_NAME"] = "AMD_AIE2_Nx4_Overlay"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # Spawn détaché caché
    proc = subprocess.Popen(
        [str(NPU_PYTHON), str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )

    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    print(f"[+] brain_worker NPU spawned PID={proc.pid}")
    print(f"[+] log : {LOG}")
    print(f"[+] pid : {PID_FILE}")
    print(f"[+] env XLNX_VART_FIRMWARE={env['XLNX_VART_FIRMWARE']}")
    print(f"[+] env XLNX_TARGET_NAME={env['XLNX_TARGET_NAME']}")
    print()
    # 25 s : la compilation a froid du graphe par l'IPU AMD (VitisAI) fige le
    # thread ; a 6 s la sonde tombait sur "Resource temporarily unavailable".
    print("Wait 25s for ZMQ :5557 + compilation a froid du graphe IPU...")
    time.sleep(25)

    # Verify alive
    try:
        import msgpack
        import zmq

        ctx = zmq.Context()
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.RCVTIMEO, 15000)
        s.setsockopt(zmq.LINGER, 0)
        s.connect("tcp://127.0.0.1:5557")
        s.send(msgpack.packb({"cmd": "ping"}))
        print("ping :", msgpack.unpackb(s.recv()))
        s.send(msgpack.packb({"cmd": "npu_status"}))
        print("npu_status :", msgpack.unpackb(s.recv()))
        s.close()
        ctx.term()
    except Exception as e:
        print(f"ZMQ probe err : {e}")
        print("Tail log :")
        if LOG.exists():
            print(LOG.read_text(encoding="utf-8", errors="replace")[-2000:])
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
