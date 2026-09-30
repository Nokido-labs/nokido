"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_hw_allocator
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
app/forge_hw_allocator.py
===========================
Allocation dynamique CPU / iGPU / NPU.
Cascade : NPU (VitisAI) > iGPU (DirectML) > CPU
Sans jamais saturer la VRAM (780M 4GB partagés).
"""

import os, time, threading
import psutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VRAM_BUDGET_MB = 3500  # marge securite sur 4GB
RAM_BUDGET_GB = 18  # marge OS


def get_memory_state() -> dict:
    """Get memory state."""
    try:
        mem = psutil.virtual_memory()
        return {
            "ram_free_gb": round(mem.available / 1e9, 1),
            "ram_total_gb": round(mem.total / 1e9, 1),
        }
    except Exception:
        return {"ram_free_gb": 8.0, "ram_total_gb": 16.0}


def detect_best_ep() -> str:
    """Detecte le meilleur Execution Provider disponible."""
    try:
        from nokido_agent.app.forge_npu import NPUManager

        mgr = NPUManager()
        status = mgr.detect()
        best = status.get("best_ep", "cpu")
        print(f"[HW] NPUManager best_ep={best}")
        return best
    except Exception:
        pass
    # Fallback : tester directement ONNX
    try:
        import onnxruntime as ort

        eps = ort.get_available_providers()
        if "VitisAIExecutionProvider" in eps:
            return "npu"
        if "DmlExecutionProvider" in eps:
            return "directml"
    except Exception:
        pass
    return "cpu"


def compute_optimal_config(n_ctx_requested: int = 16384) -> dict:
    """
    Calcule la config llamacpp selon la charge et le meilleur EP.

    Strategie par plan :
    A - NPU disponible     : NPU pour embeddings, iGPU 20L pour LLM
    B - DirectML (iGPU)    : iGPU 20L pour LLM, CPU pour le reste
    C - CPU only           : tout sur CPU, contexte reduit
    """
    state = get_memory_state()
    ram_gb = state["ram_free_gb"]
    best_ep = detect_best_ep()

    # Calcul KV cache : Qwen3-0.6B ~0.5KB/token
    kv_mb = round(n_ctx_requested * 0.5 / 1024, 1)

    if best_ep == "npu":
        # Plan A : NPU pour inference rapide + iGPU assist
        plan = "A_npu_primary"
        n_gpu_layers = 20
        n_ctx = min(n_ctx_requested, 16384)
        n_threads = 8
        ep_llm = "npu"

    elif best_ep == "directml" and ram_gb > 8:
        # Plan B : iGPU DirectML
        plan = "B_igpu_primary"
        n_gpu_layers = 20
        n_ctx = min(n_ctx_requested, 16384)
        n_threads = 8
        ep_llm = "directml"

    elif ram_gb > 4:
        # Plan C : CPU principal
        plan = "C_cpu_primary"
        n_gpu_layers = 5
        n_ctx = min(n_ctx_requested, 32768)
        n_threads = 14
        ep_llm = "cpu"

    else:
        # Plan D : memoire critique
        plan = "D_cpu_minimal"
        n_gpu_layers = 0
        n_ctx = 8192
        n_threads = 16
        ep_llm = "cpu"

    return {
        "plan": plan,
        "best_ep": best_ep,
        "ep_llm": ep_llm,
        "n_gpu_layers": n_gpu_layers,
        "n_ctx": n_ctx,
        "n_threads": n_threads,
        "kv_cache_mb": kv_mb,
        "ram_free_gb": ram_gb,
    }


def apply_config(config: dict) -> None:
    """Applique dans les variables d'env llamacpp."""
    os.environ["LLAMACPP_N_GPU_LAYERS"] = str(config["n_gpu_layers"])
    os.environ["LLAMACPP_N_CTX"] = str(config["n_ctx"])
    os.environ["LLAMACPP_N_THREADS"] = str(config["n_threads"])
    os.environ["FORGE_EP"] = config["ep_llm"]


def get_optimal_and_apply(n_ctx: int = 16384) -> dict:
    """Get optimal and apply.

    Args:
        n_ctx: Description.
    """
    config = compute_optimal_config(n_ctx)
    apply_config(config)
    return config


def get_npu_session(model_path: str, prefer_ep: str = "auto") -> object:
    """
    Cree une session ONNX optimisee pour le modele donne.
    Utilise NPU > iGPU > CPU automatiquement.
    """
    try:
        from nokido_agent.app.forge_npu import NPUManager

        mgr = NPUManager()
        mgr.detect()
        sess = mgr.create_session(model_path)
        return sess
    except Exception as e:
        print(f"[HW] NPU session err: {e}")
        return None


def monitor_and_rebalance(interval_s: int = 30) -> object:
    """Thread daemon qui recalcule la config toutes les N secondes."""

    def _loop() -> None:
        """Loop."""
        while True:
            config = compute_optimal_config()
            apply_config(config)
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name="HWAllocator")
    t.start()
    return t


def unload_ollama_models(keep: str = "") -> list:
    """
    Decharge les modeles Ollama non utilises pour liberer la RAM.
    keep : nom du modele a garder charge (les autres sont decharges).
    Retourne la liste des modeles decharges.
    """
    import urllib.request as _ur

    unloaded = []
    try:
        r = _ur.urlopen("http://localhost:11434/api/ps", timeout=3)
        import json as _j

        models = _j.loads(r.read()).get("models", [])
        for m in models:
            name = m.get("name", "")
            if keep and name.startswith(keep):
                continue
            # Decharger via keep_alive=0
            payload = _j.dumps({"model": name, "keep_alive": 0}).encode()
            req = _ur.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                _ur.urlopen(req, timeout=5)
                unloaded.append(name)
                print(f"[HW] Modele decharge: {name}")
            except Exception:
                pass
    except Exception:
        pass  # Ollama absent — pas une erreur
    return unloaded


def get_optimal_workers(ram_free_gb: float, cloud_mode: bool = False) -> int:
    """
    Nombre de workers parallèles selon la RAM disponible.
    cloud_mode=True : workers OpenRouter (réseau), pas de contrainte RAM locale.
    """
    if cloud_mode:
        # OpenRouter — I/O bound, GIL relâché, RAM non limitante
        # Limité par le rate limit : 20 req/min = 1 req/3s
        # Avec 6 fichiers et cooldown, 3 workers est optimal
        return 3
    # Local Ollama — RAM limitante
    if ram_free_gb >= 12:
        return 3
    elif ram_free_gb >= 8:
        return 2
    elif ram_free_gb >= 5:
        return 2  # OpenRouter peut compenser le local
    else:
        return 1  # RAM critique — séquentiel strict


# ── TOTAL_SILICON_V1 — Thermal_Aware_Offloading ───────────────────────────────
SILICON_POLICY = {
    "kv_cache": "igpu_fast",  # KV cache sur iGPU via offload_kqv
    "weights_processing": "cpu_balanced",  # weights partagés CPU+iGPU
    "embedding": "npu_efficient",  # embeddings sur NPU DirectML
    "max_ram_pct": 70,  # 70% RAM max = ~16GB sur 23GB
    "max_vram_pct": 85,  # 85% VRAM max = ~3.4GB sur 4GB
    "min_cpu_reserved": 2,  # 2 cores réservés OS/bureau
}


def get_silicon_config() -> dict:
    """
    TOTAL_SILICON_V1 — calcule la config optimale selon
    les quotas thermiques et la charge actuelle.
    Respecte max_ram=70%, max_vram=85%, min_cpu=2 cores.
    """
    state = get_memory_state()
    ram_free = state["ram_free_gb"]
    ram_total = state["ram_total_gb"]
    ram_used_pct = (1 - ram_free / ram_total) * 100 if ram_total > 0 else 50

    # Respecter max_system_ram_usage = 70%
    ram_budget_gb = ram_total * (SILICON_POLICY["max_ram_pct"] / 100)
    ram_available = max(0, ram_budget_gb - (ram_total - ram_free))

    # CPU : réserver min_cpu_cores_reserved
    import os

    total_cores = os.cpu_count() or 8
    usable_cores = max(1, total_cores - SILICON_POLICY["min_cpu_reserved"])

    # iGPU : max_vram_usage = 85% de 4GB = 3.4GB
    # Qwen3-0.6B weights = ~400MB → budget KV = 3400 - 400 = 3000MB
    vram_budget_mb = int(4096 * SILICON_POLICY["max_vram_pct"] / 100)  # 3481MB
    weights_mb = 400  # Qwen3-0.6B Q4
    kv_budget_mb = vram_budget_mb - weights_mb  # 3081MB
    # n_ctx max sans dépasser kv_budget : ~0.5KB/token
    n_ctx_max_vram = int(kv_budget_mb * 1024 / 0.5)  # très large
    # En pratique on est limité par le n_ctx_train=40960
    n_ctx_target = min(16384, n_ctx_max_vram, 40960)

    # n_gpu_layers : utiliser iGPU pour KV cache (offload_kqv)
    # weights sur CPU+iGPU partagé = 20 layers sur iGPU
    if ram_available > 6 and ram_used_pct < 65:
        n_gpu_layers = 20
        plan = "SILICON_A_balanced"
    elif ram_available > 3:
        n_gpu_layers = 10
        plan = "SILICON_B_conservative"
    else:
        n_gpu_layers = 0
        n_ctx_target = 8192
        plan = "SILICON_C_cpu_only"

    return {
        "plan": plan,
        "n_gpu_layers": n_gpu_layers,
        "n_ctx": n_ctx_target,
        "n_threads": usable_cores,
        "offload_kqv": True,  # KV cache sur iGPU_Fast
        "flash_attn": True,  # réduit VRAM attention
        "ram_used_pct": round(ram_used_pct, 1),
        "ram_available_gb": round(ram_available, 1),
        "kv_budget_mb": kv_budget_mb,
        "vram_budget_mb": vram_budget_mb,
        "usable_cores": usable_cores,
    }


def apply_silicon_config() -> dict:
    """Applique TOTAL_SILICON_V1 et retourne la config utilisée."""
    cfg = get_silicon_config()
    os.environ["LLAMACPP_N_GPU_LAYERS"] = str(cfg["n_gpu_layers"])
    os.environ["LLAMACPP_N_CTX"] = str(cfg["n_ctx"])
    os.environ["LLAMACPP_N_THREADS"] = str(cfg["n_threads"])
    os.environ["LLAMACPP_OFFLOAD_KQV"] = "true"
    os.environ["LLAMACPP_FLASH_ATTN"] = "true"
    os.environ["FORGE_EP"] = "directml"  # NPU DirectML pour embeddings
    return cfg


# ── NPU_LOW_LEVEL_PROBE_V1 ────────────────────────────────────────────────────
NPU_DEVICE_ID = "VEN_1022&DEV_1502"  # AMD XDNA Phoenix


def get_npu_load() -> int:
    """
    NPU_LOW_LEVEL_PROBE_V1 — charge NPU en %.
    Cascade : amd_ipu_util -> WMI perf -> registre -> PnP status.
    """
    # 1. amd_ipu_util SDK (si installe)
    try:
        import subprocess as _sp, json as _j

        r = _sp.run(["python", "-m", "amd_ipu_util", "--status", "--json"], capture_output=True, text=True, timeout=1, errors="replace")
        if r.returncode == 0:
            data = _j.loads(r.stdout)
            return int(data.get("ipu_load_percent", 0))
    except Exception:
        pass

    # 2. WMI perf counter (si disponible)
    try:
        import wmi as _wmi

        w = _wmi.WMI()
        for item in w.query("SELECT * FROM Win32_PerfFormattedData_PerfOS_Processor"):
            if "IPU" in str(item) or "NPU" in str(item):
                return int(item.PercentProcessorTime)
    except Exception:
        pass

    # 3. Registre Windows — verifier si le driver est actif
    try:
        import winreg as _wr

        key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        key = _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE, key_path)
        i = 0
        while True:
            try:
                sub = _wr.OpenKey(key, _wr.EnumKey(key, i))
                try:
                    desc = _wr.QueryValueEx(sub, "DriverDesc")[0]
                    if any(k in desc for k in ["IPU", "NPU", "XDNA", "Ryzen AI"]):
                        return 5  # detecte idle
                except Exception:
                    pass
                i += 1
            except OSError:
                break
    except Exception:
        pass

    # 4. PnP status — verification legere
    try:
        import subprocess as _sp2

        r2 = _sp2.run(
            [
                "powershell",
                "-Command",
                f"(Get-PnpDevice | Where-Object {{$_.DeviceID -like '*{NPU_DEVICE_ID}*'}}).Status",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        errors="replace")
        if "OK" in r2.stdout:
            return 3  # present et operationnel
    except Exception:
        pass

    return 0  # non detecte


def log_npu_status() -> object:
    """Affiche le statut NPU dans la console — visible dans le moniteur."""
    load = get_npu_load()
    bar = "█" * (load // 5) + "░" * (20 - load // 5)
    status = "ACTIF" if load > 3 else "IDLE"
    print(f"[NPU] AMD XDNA {status} |{bar}| {load}%")
    return load
