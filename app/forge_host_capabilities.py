# -*- coding: utf-8 -*-
"""
forge_host_capabilities.py - Detection capacite hote Nokido
=============================================================
Determine ce que la machine hote peut faire tourner localement (CPU+RAM+VRAM+disk).
Decide si un modele Ollama/llama.cpp est viable LOCAL vs doit etre route CLOUD.

Source-of-truth pour cascade router (forge_llm_router) :
- Si modele requis > VRAM dispo + 20% marge -> skip local providers
- Si RAM totale < min model footprint -> skip local
- Sinon prefer local (latence + free + sovereignty)

Cache : data/host_capabilities.json (refresh manuel via --refresh)

Pour Nokido sur poste user (Win11, Radeon 780M iGPU 16GB shared, AMD Ryzen) :
- VRAM partagee = pas isole, RAM=VRAM virtuellement
- DirectML inference au lieu CUDA/ROCm
- Modeles 7b q4 OK, 14b q4 limite, 32b+ inviable local
"""

from __future__ import annotations
import datetime
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

__FORGE_COLOR__ = "GREEN"

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "host_capabilities.json"


# Table footprint VRAM/RAM minimum par modele Ollama (Q4 quantized, sans
# contexte etendu). Reference : ollama.com/library + Hugging Face cards.
# Format : {model_slug: {ram_gb_min, vram_gb_min, params_b}}
MODEL_FOOTPRINT_GB = {
    # Petits (< 8B parametres) - viables RAM/CPU only
    "qwen2.5-coder:7b-instruct-q4_K_M": {"ram_gb_min": 5, "vram_gb_min": 5, "params_b": 7.6},
    "qwen3:8b": {"ram_gb_min": 6, "vram_gb_min": 6, "params_b": 8.0},
    "llama3.1:8b": {"ram_gb_min": 6, "vram_gb_min": 6, "params_b": 8.0},
    "mistral:7b": {"ram_gb_min": 5, "vram_gb_min": 5, "params_b": 7.3},
    "gemma2:9b": {"ram_gb_min": 7, "vram_gb_min": 7, "params_b": 9.0},
    "deepseek-r1:7b": {"ram_gb_min": 5, "vram_gb_min": 5, "params_b": 7.6},
    "phi3:medium": {"ram_gb_min": 9, "vram_gb_min": 9, "params_b": 14.0},
    # Moyens (14-32B) - VRAM >=12-20 GB necessaire
    "qwen2.5-coder:14b": {"ram_gb_min": 11, "vram_gb_min": 11, "params_b": 14.0},
    "deepseek-r1:14b": {"ram_gb_min": 11, "vram_gb_min": 11, "params_b": 14.8},
    "qwen2.5-coder:32b-instruct-q4_K_M": {"ram_gb_min": 20, "vram_gb_min": 20, "params_b": 32.5},
    "llama3.3:70b-q4_K_M": {"ram_gb_min": 40, "vram_gb_min": 40, "params_b": 70.0},
    # Lourds (40B+) - cluster GPU obligatoire
    "llama3.1:70b": {"ram_gb_min": 42, "vram_gb_min": 42, "params_b": 70.6},
    "mistral-large:123b": {"ram_gb_min": 73, "vram_gb_min": 73, "params_b": 123.0},
    "mixtral:8x22b": {"ram_gb_min": 80, "vram_gb_min": 80, "params_b": 141.0},
    # Multimodaux gros - typiquement cloud only
    "mimo-v2-omni": {"ram_gb_min": 100, "vram_gb_min": 100, "params_b": 200.0},
    "llama3.2-vision:90b": {"ram_gb_min": 50, "vram_gb_min": 50, "params_b": 90.0},
}

# Marge securite (% RAM/VRAM totale a garder libre pour OS + autres process)
SAFETY_MARGIN_PCT = 25

# Catalogue des modeles SUGGERES a l'installation (2026-10-07, demande owner : llama.cpp, Ollama, LM Studio).
# Chaque entree est VERIFIEE sur ses trois sources avant d'entrer ici (C:/tmp/corrections/verifier_catalogue_modeles
# + passe 2) : fichier GGUF exact a revision FIXE (sha256 = oid LFS, taille), nom servi par le registre Ollama, page
# LM Studio servie. Licence Apache-2.0 seulement par defaut. Une entree ajoutee sans cette verification est un lien
# invente : trois l'auraient ete a la 1re passe (fichier gpt-oss mal nomme, cles LM Studio de Qwen2.5-Coder fausses,
# depot GGUF Qwen3-Coder inexistant chez Qwen).
_HF = "https://huggingface.co/%s/resolve/%s/%s"
CATALOGUE_SUGGESTIONS: tuple[dict, ...] = (
    {"role": "chat", "nom": "Qwen3 4B", "taille_go": 2.5, "licence": "Apache-2.0", "ollama": "qwen3:4b",
     "lmstudio": "qwen/qwen3-4b", "gguf": _HF % ("Qwen/Qwen3-4B-GGUF", "bc640142c66e1fdd12af0bd68f40445458f3869b",
                                                   "Qwen3-4B-Q4_K_M.gguf"),
     "sha256": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"},
    {"role": "chat", "nom": "Qwen3 8B", "taille_go": 5.0, "licence": "Apache-2.0", "ollama": "qwen3:8b",
     "lmstudio": "qwen/qwen3-8b", "gguf": _HF % ("Qwen/Qwen3-8B-GGUF", "7c41481f57cb95916b40956ab2f0b139b296d974",
                                                   "Qwen3-8B-Q4_K_M.gguf"),
     "sha256": "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"},
    {"role": "chat", "nom": "Qwen3 14B", "taille_go": 9.0, "licence": "Apache-2.0", "ollama": "qwen3:14b",
     "lmstudio": "qwen/qwen3-14b", "gguf": _HF % ("Qwen/Qwen3-14B-GGUF", "530227a7d994db8eca5ab5ced2fb692b614357fd",
                                                    "Qwen3-14B-Q4_K_M.gguf"),
     "sha256": "500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0"},
    {"role": "chat", "nom": "gpt-oss 20B", "taille_go": 12.1, "licence": "Apache-2.0", "ollama": "gpt-oss:20b",
     "lmstudio": "openai/gpt-oss-20b", "gguf": _HF % ("ggml-org/gpt-oss-20b-GGUF",
                                                       "ef9b12f2ff56c69cf32153a02784e7a3c88bf524", "gpt-oss-20b-MXFP4.gguf"),
     "sha256": "27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901"},
    {"role": "code", "nom": "Qwen2.5-Coder 7B", "taille_go": 4.7, "licence": "Apache-2.0", "ollama": "qwen2.5-coder:7b",
     "lmstudio": "qwen/qwen2.5-coder-7b", "gguf": _HF % ("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                                                          "13fb94bfda8c8cf22497dc57b78f391a9acb426a",
                                                          "qwen2.5-coder-7b-instruct-q4_k_m.gguf"),
     "sha256": "509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c"},
    {"role": "code", "nom": "Qwen2.5-Coder 14B", "taille_go": 9.0, "licence": "Apache-2.0",
     "ollama": "qwen2.5-coder:14b", "lmstudio": "qwen/qwen2.5-coder-14b",
     "gguf": _HF % ("Qwen/Qwen2.5-Coder-14B-Instruct-GGUF", "d0a692ef765eefbf2fabb130b3cb2e8917e3d225",
                    "qwen2.5-coder-14b-instruct-q4_k_m.gguf"),
     "sha256": "c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940"},
    {"role": "code", "nom": "Qwen3-Coder 30B-A3B", "taille_go": 18.6, "licence": "Apache-2.0",
     "ollama": "qwen3-coder:30b", "lmstudio": "qwen/qwen3-coder-30b",
     "gguf": _HF % ("unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", "b17cb02dd882d5b6ab62fc777ad2995f19668350",
                    "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"),
     "sha256": "fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093056f088ad"},
)


def suggerer_modeles(host_info: Optional[dict] = None, par_role: int = 2) -> dict:
    """Les modeles du catalogue qui TIENNENT dans la memoire d'inference de cet hote, les plus gros d'abord.

    Tenir = taille du GGUF x 1,2 (contexte et tampons) + la marge de securite <= `effective_inference_ram_gb`
    (VRAM si GPU, sinon la moitie de la RAM). Une machine trop petite pour tout le catalogue recoit une liste vide
    par role, DITE : elle n'est pas « sans suggestion », elle est sous le plus petit modele verifie.
    """
    info = host_info or get_host_info()
    dispo = float(info.get("effective_inference_ram_gb") or 0)
    besoin = lambda m: m["taille_go"] * 1.2 * (1 + SAFETY_MARGIN_PCT / 100)  # noqa: E731
    out = {}
    for role in ("code", "chat"):
        tient = [m for m in CATALOGUE_SUGGESTIONS if m["role"] == role and besoin(m) <= dispo]
        out[role] = sorted(tient, key=lambda m: -m["taille_go"])[:par_role]
    plus_petit = min(besoin(m) for m in CATALOGUE_SUGGESTIONS)
    return {"memoire_inference_go": dispo, "suggestions": out,
            "trop_petite": dispo < plus_petit, "minimum_go": round(plus_petit, 1)}


def _detect_cpu() -> dict:
    """CPU info via psutil + platform."""
    info = {
        "model": platform.processor() or "?",
        "arch": platform.machine(),
        "cores_logical": 0,
        "cores_physical": 0,
        "freq_max_mhz": 0.0,
    }
    try:
        import psutil

        info["cores_logical"] = psutil.cpu_count(logical=True) or 0
        info["cores_physical"] = psutil.cpu_count(logical=False) or 0
        freq = psutil.cpu_freq()
        if freq:
            info["freq_max_mhz"] = freq.max or freq.current or 0
    except Exception:
        pass
    return info


def _detect_ram() -> dict:
    """RAM info via psutil."""
    info = {"total_gb": 0.0, "available_gb": 0.0}
    try:
        import psutil

        vm = psutil.virtual_memory()
        info["total_gb"] = round(vm.total / 1024**3, 2)
        info["available_gb"] = round(vm.available / 1024**3, 2)
    except Exception:
        pass
    return info


def _detect_gpu_windows() -> list[dict]:
    """GPU info via PowerShell Get-CimInstance Win32_VideoController.
    Detect : nom + RAM video (VRAM dedie OR partage iGPU).
    """
    try:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM,DriverVersion,VideoProcessor | "
            "ConvertTo-Json -Compress",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return []
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        out = []
        for g in data:
            adapter_ram = g.get("AdapterRAM") or 0
            out.append(
                {
                    "name": g.get("Name", "?"),
                    "vram_gb": round(adapter_ram / 1024**3, 2) if adapter_ram else 0,
                    "driver": g.get("DriverVersion", "?"),
                    "video_processor": g.get("VideoProcessor", "?"),
                }
            )
        return out
    except Exception:
        return []


def _detect_gpu_linux() -> list[dict]:
    """GPU info Linux via nvidia-smi OR lspci."""
    out = []
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            r = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            errors="replace")
            for line in (r.stdout or "").strip().split("\n"):
                if "," in line:
                    name, mem_mib = [x.strip() for x in line.split(",", 1)]
                    out.append(
                        {
                            "name": name,
                            "vram_gb": round(int(mem_mib) / 1024, 2),
                            "driver": "nvidia",
                            "video_processor": "?",
                        }
                    )
        except Exception:
            pass
    if not out:
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5, errors="replace")
            for line in (r.stdout or "").split("\n"):
                if "VGA compatible" in line or "3D controller" in line:
                    out.append(
                        {
                            "name": line.split(":")[-1].strip(),
                            "vram_gb": 0,
                            "driver": "?",
                            "video_processor": "?",
                        }
                    )
        except Exception:
            pass
    return out


def _detect_disk() -> dict:
    """Disk free pour partition contenant ROOT."""
    try:
        usage = shutil.disk_usage(str(ROOT))
        return {
            "total_gb": round(usage.total / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
        }
    except Exception:
        return {"total_gb": 0.0, "free_gb": 0.0}


def detect_host() -> dict:
    """Detect specs hote. Cache JSON (refresh manuel ou >7j auto)."""
    info = {
        "detected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "os": platform.system(),
        "os_release": platform.release(),
        "hostname": platform.node(),
        "cpu": _detect_cpu(),
        "ram": _detect_ram(),
        "disk": _detect_disk(),
        "gpus": [],
    }
    if info["os"] == "Windows":
        info["gpus"] = _detect_gpu_windows()
    else:
        info["gpus"] = _detect_gpu_linux()

    # Compute total VRAM (sum sur GPUs, ignore iGPU shared duplicate RAM)
    info["total_vram_gb"] = round(sum((g.get("vram_gb") or 0) for g in info["gpus"]), 2)

    # Pour iGPU shared RAM (Radeon 780M / Intel UHD), VRAM effective = part RAM allocable
    # Heuristique : si VRAM detected == 0 OR < 2GB et iGPU keyword -> assume RAM/2 dispo
    igpu_keywords = ("radeon graphics", "uhd graphics", "iris", "780m", "880m", "890m", "vega")
    has_igpu_only = (
        all(
            any(kw in (g.get("name", "").lower()) for kw in igpu_keywords) or g.get("vram_gb", 0) < 2
            for g in info["gpus"]
        )
        if info["gpus"]
        else False
    )
    if has_igpu_only and info["ram"]["total_gb"] > 0:
        info["effective_inference_ram_gb"] = round(info["ram"]["total_gb"] * 0.5, 2)
        info["is_igpu_only"] = True
    else:
        info["effective_inference_ram_gb"] = info["total_vram_gb"]
        info["is_igpu_only"] = False

    _save_cache(info)
    return info


def _save_cache(info: dict) -> None:
    # best-effort : un echec d'ecriture cache (data/ read-only, sandbox) ne doit
    # JAMAIS crasher le routing LLM appelant.
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(info, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_cache(max_age_h: float = 168.0) -> Optional[dict]:
    """Charge cache si frais (defaut 7j)."""
    if not CACHE_PATH.exists():
        return None
    age_h = (datetime.datetime.now().timestamp() - CACHE_PATH.stat().st_mtime) / 3600
    if age_h > max_age_h:
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_host_info(refresh: bool = False) -> dict:
    """Retourne info hote (cache si frais, sinon detect)."""
    if not refresh:
        cached = _load_cache()
        if cached:
            return cached
    return detect_host()


def can_run_locally(model_slug: str, host_info: Optional[dict] = None) -> tuple[bool, str]:
    """True si le modele peut tourner local sur cet hote.

    Decision :
    - Cherche footprint dans MODEL_FOOTPRINT_GB
    - Compare avec effective_inference_ram_gb (VRAM + iGPU shared RAM)
    - Marge securite SAFETY_MARGIN_PCT

    Returns:
        (ok: bool, reason: str)
    """
    info = host_info or get_host_info()
    footprint = MODEL_FOOTPRINT_GB.get(model_slug)
    if not footprint:
        # Modele inconnu : tentative best-effort, on accepte si VRAM >= 6 GB
        avail = info.get("effective_inference_ram_gb", 0)
        if avail >= 6:
            return True, f"unknown model footprint, assumed OK ({avail} GB inference RAM)"
        return False, f"unknown model footprint, insufficient inference RAM ({avail} GB)"

    needed = footprint["ram_gb_min"]
    needed_with_margin = needed * (1 + SAFETY_MARGIN_PCT / 100)
    avail = info.get("effective_inference_ram_gb", 0)
    if avail >= needed_with_margin:
        return (
            True,
            f"OK : need {needed:.0f} GB (+{SAFETY_MARGIN_PCT}% margin = {needed_with_margin:.0f}), have {avail:.1f} GB",
        )
    return (
        False,
        f"INSUFFICIENT : need {needed:.0f} GB (+{SAFETY_MARGIN_PCT}% margin = {needed_with_margin:.0f}), have {avail:.1f} GB",
    )


def list_runnable_models(host_info: Optional[dict] = None) -> list[dict]:
    """Liste les modeles MODEL_FOOTPRINT_GB compatibles avec cet hote."""
    info = host_info or get_host_info()
    out = []
    for slug, fp in MODEL_FOOTPRINT_GB.items():
        ok, reason = can_run_locally(slug, info)
        if ok:
            out.append({"slug": slug, "params_b": fp["params_b"], "ram_gb_min": fp["ram_gb_min"]})
    out.sort(key=lambda x: x["params_b"], reverse=True)
    return out


def display_summary() -> str:
    """CLI summary : specs + modeles runnable."""
    info = get_host_info()
    lines = [
        "=== Host Capabilities Summary ===",
        f"OS         : {info['os']} {info['os_release']} ({info['hostname']})",
        f"CPU        : {info['cpu'].get('model', '?')[:60]}",
        f"             {info['cpu'].get('cores_physical', 0)} cores phys, {info['cpu'].get('cores_logical', 0)} threads, {info['cpu'].get('freq_max_mhz', 0):.0f} MHz max",
        f"RAM        : {info['ram'].get('total_gb', 0):.1f} GB total, {info['ram'].get('available_gb', 0):.1f} GB available",
        f"Disk       : {info['disk'].get('free_gb', 0):.1f} GB free / {info['disk'].get('total_gb', 0):.1f} GB total",
        "",
        "GPUs:",
    ]
    for g in info.get("gpus", []):
        lines.append(f"  - {g['name']} | VRAM={g['vram_gb']} GB | driver={g['driver']}")
    if info.get("is_igpu_only"):
        lines.append("")
        lines.append("  /!\\ iGPU shared RAM detected.")
        lines.append(f"      Effective inference RAM = {info['effective_inference_ram_gb']:.1f} GB (50% of system RAM)")
    else:
        lines.append("")
        lines.append(f"  Effective inference VRAM = {info['effective_inference_ram_gb']:.1f} GB (dedicated)")
    lines.append("")
    lines.append(f"=== Models runnable locally on this host ({SAFETY_MARGIN_PCT}% safety margin) ===")
    runnable = list_runnable_models(info)
    if not runnable:
        lines.append("  None match. Use cloud providers only for inference.")
    else:
        for m in runnable:
            lines.append(f"  - {m['slug']:<45} ({m['params_b']}B params, ~{m['ram_gb_min']} GB min)")
    lines.append("")
    blocked = [m for m in MODEL_FOOTPRINT_GB if not can_run_locally(m, info)[0]]
    if blocked:
        lines.append("=== Models REQUIRING cloud (too heavy for this host) ===")
        for slug in blocked:
            fp = MODEL_FOOTPRINT_GB[slug]
            lines.append(f"  - {slug:<45} ({fp['params_b']}B params, needs {fp['ram_gb_min']} GB)")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--refresh" in args:
        info = detect_host()
        print(f"[host-capabilities] refreshed, cached to {CACHE_PATH}")
        print(display_summary())
    elif "--json" in args:
        print(json.dumps(get_host_info(), indent=2))
    elif "--check" in args:
        model = args[args.index("--check") + 1] if len(args) > args.index("--check") + 1 else ""
        if not model:
            print("Usage: --check <model_slug>")
            sys.exit(1)
        ok, reason = can_run_locally(model)
        print(f"Model {model}: {'OK' if ok else 'NO'} - {reason}")
    else:
        print(display_summary())
