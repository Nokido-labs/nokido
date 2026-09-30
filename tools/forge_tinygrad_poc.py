"""
tools/forge_tinygrad_poc.py — PoC tinygrad sur iGPU AMD 780M (Windows, sans DirectML).
=====================================================================================

But : déterminer si tinygrad peut faire du compute GPU sur le Radeon 780M (RDNA3)
SANS DirectML/ONNX (cause des BSOD 0x119 répétés) — donc via le backend OpenCL
(GPU=1) sur Windows. Si viable -> piste training local AMD (JEPA-lite/SFT) +
éventuel embed. Rappel : l'inférence embed bge-m3 est DÉJÀ stable via llama.cpp
Vulkan ; tinygrad vise surtout le TRAINING que llama.cpp ne fait pas.

Phases (argv) :
  --check            : report env + presence tinygrad/pyopencl. Sans réseau ni GPU.
  --install          : pip install pyopencl tinygrad numpy dans sys.executable.
  --enum             : énumère plateformes/devices OpenCL RÉELS (vue hôte). Sûr.
  --matmul[=N]       : tinygrad GPU=1 matmul NxN (def 16) vérifié vs numpy. PETIT.
                       N volontairement petit : escalade batch = étape supervisée
                       à part (risque TDR/BSOD sur gros batch, cf. DirectML).

Tout est loggé dans C:/tmp/tinygrad_poc.log. Idempotent, défensif : aucune phase
ne lève une exception non capturée (rapport propre, pas de crash du runner trusted).
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

LOG = Path("C:/tmp/tinygrad_poc.log")
LOG.parent.mkdir(parents=True, exist_ok=True)

# LaForgeTrusted ne peut pas écrire dans le site-packages de l'env (owned user)
# -> pip fallback user-site = C:/Users/Default/Python = Accès refusé. On installe
# dans un --target writable sous C:/tmp et on le prepend au sys.path.
TARGET = Path("C:/tmp/tinygrad_libs")


def _use_target() -> None:
    if TARGET.is_dir() and str(TARGET) not in sys.path:
        sys.path.insert(0, str(TARGET))


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def phase_check() -> None:
    import importlib.util as u

    log(f"python   = {sys.executable}")
    log(f"version  = {sys.version.split()[0]}")
    log(f"cwd      = {os.getcwd()}")
    log(f"user     = {os.environ.get('USERNAME', '?')}")
    for mod in ("tinygrad", "pyopencl", "numpy"):
        log(f"have {mod:9s} = {u.find_spec(mod) is not None}")


def phase_install() -> None:
    pkgs = ["pyopencl", "tinygrad", "numpy"]
    TARGET.mkdir(parents=True, exist_ok=True)
    log(f"pip install {pkgs} --target {TARGET} -> {sys.executable}")
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--target", str(TARGET),
             "--no-warn-script-location", *pkgs],
            capture_output=True, text=True, timeout=600,
        errors="replace")
        tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-12:])
        log(f"pip rc={out.returncode}\n{tail}")
    except Exception as exc:  # noqa: BLE001
        log(f"pip FAILED: {exc!r}")


def phase_enum() -> None:
    _use_target()
    try:
        import pyopencl as cl
    except Exception as exc:  # noqa: BLE001
        log(f"pyopencl import FAILED: {exc!r}")
        return
    try:
        plats = cl.get_platforms()
    except Exception as exc:  # noqa: BLE001
        log(f"get_platforms FAILED: {exc!r} (ICD vendor non enregistré ?)")
        return
    if not plats:
        log("OpenCL: 0 plateforme (aucun ICD vendor) -> backend GPU=1 mort sur cette machine")
        return
    for p in plats:
        log(f"platform: {p.name} | vendor={p.vendor} | version={p.version}")
        try:
            for d in p.get_devices():
                dtype = cl.device_type.to_string(d.type)
                log(
                    f"   device: {d.name} [{dtype}] "
                    f"CU={d.max_compute_units} "
                    f"glob_mem={d.global_mem_size // (1024**2)}MB "
                    f"clver={d.opencl_c_version}"
                )
        except Exception as exc:  # noqa: BLE001
            log(f"   get_devices FAILED: {exc!r}")


def phase_matmul(n: int) -> None:
    # Force backend OpenCL (GPU=1) AVANT import tinygrad.
    os.environ["GPU"] = "1"
    os.environ.setdefault("PYOPENCL_NO_CACHE", "1")
    # LaForgeTrusted n'a pas de home -> ~ = C:/Users/Default = Accès refusé.
    # Rediriger la diskcache tinygrad (CACHEDB) + cache XDG vers C:/tmp writable.
    cache_dir = Path("C:/tmp/tinygrad_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CACHEDB"] = str(cache_dir / "cache.db")
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    _use_target()
    try:
        import numpy as np
        from tinygrad import Device, Tensor

        log(f"tinygrad DEFAULT device = {Device.DEFAULT}")
        a = np.random.rand(n, n).astype(np.float32)
        b = np.random.rand(n, n).astype(np.float32)
        ta, tb = Tensor(a), Tensor(b)
        tc = (ta @ tb).numpy()  # force realize
        ref = a @ b
        err = float(np.abs(tc - ref).max())
        log(f"matmul {n}x{n} on {Device.DEFAULT}: max_abs_err={err:.3e} "
            f"-> {'OK' if err < 1e-2 else 'MISMATCH'}")
    except Exception as exc:  # noqa: BLE001
        log(f"matmul FAILED: {exc!r}\n{traceback.format_exc()}")


def main() -> None:
    args = sys.argv[1:]
    log(f"=== forge_tinygrad_poc START args={args} ===")
    if "--check" in args:
        phase_check()
    if "--install" in args:
        phase_install()
    if "--enum" in args:
        phase_enum()
    mm = [a for a in args if a.startswith("--matmul")]
    if mm:
        n = 16
        if "=" in mm[0]:
            try:
                n = int(mm[0].split("=", 1)[1])
            except ValueError:
                pass
        phase_matmul(n)
    log("=== forge_tinygrad_poc END ===")


if __name__ == "__main__":
    main()
