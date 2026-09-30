"""
tools/forge_resource_monitor.py — ForgeMemoryGuard + Resource Monitor
======================================================================
Surveillance légère RAM/CPU pour ParallelMutationWorker.

Features :
  - get_usage_mb(include_children=True) — RAM process + workers enfants
  - snapshot() — état système complet pour mutation:poll
  - backpressure() — True si système sous pression
  - check_nvme_temp() — température NVMe si disponible

Seuils (Ryzen 8700G — 24GB UMA iGPU 780M 4GB) :
  RAM > 88% → backpressure (iGPU commence à swapper)
  CPU > 90% → backpressure
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# Seuils
RAM_PRESSURE_PCT = 88.0
CPU_PRESSURE_PCT = 90.0

# NVMe PCIe 5.0 — C: sur ce setup
NVME_PATH = Path("C:/")


# ── Usage process + enfants ───────────────────────────────────────────────────


def get_usage_mb(pid: int | None = None, include_children: bool = True) -> float:
    """
    Retourne la RAM utilisée (MB) par un process et optionnellement ses enfants.
    Utile pour surveiller ParallelMutationWorker + ses 3 workers subprocess.
    """
    if not _HAS_PSUTIL:
        return 0.0
    try:
        proc = psutil.Process(pid or os.getpid())
        mem = proc.memory_info().rss

        if include_children:
            for child in proc.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        return round(mem / 1024 / 1024, 1)
    except Exception:
        return 0.0


# ── Backpressure ──────────────────────────────────────────────────────────────


def backpressure() -> str | None:
    """
    Retourne un message si le système est sous pression, None sinon.
    Appelé avant chaque appel LLM dans forge_openrouter.py.
    """
    if not _HAS_PSUTIL:
        return None
    try:
        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory().percent
        if cpu > CPU_PRESSURE_PCT:
            return f"CPU {cpu:.0f}% > {CPU_PRESSURE_PCT:.0f}%"
        if ram > RAM_PRESSURE_PCT:
            return f"RAM {ram:.0f}% > {RAM_PRESSURE_PCT:.0f}% (iGPU UMA pressure)"
    except Exception:
        pass
    return None


# ── Snapshot complet ──────────────────────────────────────────────────────────


def snapshot() -> dict:
    """
    Retourne un snapshot complet système — utilisé par mutation:poll MCP.
    """
    if not _HAS_PSUTIL:
        return {"error": "psutil absent"}

    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    disk = psutil.disk_usage(str(NVME_PATH))

    # Processus Nokido
    forge_procs = []
    total_forge_mb = 0.0
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        try:
            name = proc.info["name"] or ""
            if any(k in name.lower() for k in ["python", "ollama"]):
                mb = (proc.info["memory_info"].rss or 0) / 1024 / 1024
                forge_procs.append(proc.info["pid"])
                total_forge_mb += mb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # NVMe — espace disque C:
    nvme_free_gb = round(disk.free / 1024**3, 1)

    return {
        "sys": {
            "cpu_pct": round(cpu, 1),
            "mem_used_gb": round(vm.used / 1024**3, 1),
            "mem_total_gb": round(vm.total / 1024**3, 1),
            "mem_pct": round(vm.percent, 1),
            "mem_avail_gb": round(vm.available / 1024**3, 1),
            "nvme_free_gb": nvme_free_gb,
            "pressure": backpressure(),
        },
        "forge": {
            "proc_count": len(forge_procs),
            "total_mem_mb": round(total_forge_mb, 1),
            "total_cpu_pct": round(cpu, 1),
        },
    }


# ── NVMe température ──────────────────────────────────────────────────────────


def check_nvme_temp() -> float | None:
    """
    Retourne la température NVMe en °C si disponible via psutil.sensors_temperatures.
    Windows : nécessite des outils tiers (OpenHardwareMonitor).
    """
    if not _HAS_PSUTIL or not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        temps = psutil.sensors_temperatures()
        for name, entries in temps.items():
            if "nvme" in name.lower() or "ssd" in name.lower():
                for entry in entries:
                    if entry.current and entry.current > 0:
                        return round(entry.current, 1)
    except Exception:
        pass
    return None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    s = snapshot()
    sys_s = s["sys"]
    forge_s = s["forge"]

    print(f"CPU     : {sys_s['cpu_pct']}%")
    print(f"RAM     : {sys_s['mem_used_gb']}/{sys_s['mem_total_gb']}GB ({sys_s['mem_pct']}%)")
    print(f"Dispo   : {sys_s['mem_avail_gb']}GB")
    print(f"NVMe C: : {sys_s['nvme_free_gb']}GB libres")
    print(f"Forge   : {forge_s['proc_count']} procs / {forge_s['total_mem_mb']}MB")

    bp = sys_s["pressure"]
    print(f"Pressure: {'⚠ ' + bp if bp else '✅ OK'}")

    nvme_t = check_nvme_temp()
    if nvme_t:
        print(f"NVMe T° : {nvme_t}°C")

    # Test include_children
    import os

    mb = get_usage_mb(include_children=True)
    print(f"\nProcess actuel + enfants : {mb}MB")
