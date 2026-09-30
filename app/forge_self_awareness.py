from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("Nokido.SelfAwareness")
ROOT = Path(__file__).resolve().parent.parent

def self_snapshot() -> Dict[str, Any]:
    """
    Vue unifiée de la conscience de soi et des capacités de Nokido (6 sections).
    """
    # 1. Identity
    identity = {
        "hub": "http://127.0.0.1:8766/mcp",
        "version": "v3_2026",
        "role": "nokido_sovereign_supercontroller"
    }

    # 2. Body Local
    n_modules = 0
    n_organes = 0
    census_file = ROOT / "sandbox" / "workspace" / "organ_map_full.json"
    if not census_file.exists():
        census_file = ROOT / "config" / "organ_map_full.json"
    if census_file.exists():
        try:
            with open(census_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "module_organ" in data:
                n_modules = len(data["module_organ"])
                n_organes = len(data.get("tally", {})) or len(set(data["module_organ"].values()))
            elif isinstance(data, list):
                n_modules = len(data)
            elif isinstance(data, dict):
                n_modules = len(data.get("organs", data.get("modules", [])))
        except Exception:
            pass

    import psutil
    ram_pct = psutil.virtual_memory().percent

    services_up = 0
    services_total = 0
    agy_running = False
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/supervisor/status", headers={"User-Agent": "SelfSnapshot"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            sup_data = json.loads(resp.read().decode("utf-8"))
            if isinstance(sup_data, dict):
                svcs = sup_data.get("services", sup_data)
                if isinstance(svcs, dict):
                    services_total = len(svcs)
                    services_up = sum(1 for s in svcs.values() if isinstance(s, dict) and s.get("status") in ("UP", "RUNNING", "running", "healthy"))
                    _agy_svc = svcs.get("NokidoGeminiAutonomous")
                    if isinstance(_agy_svc, dict) and _agy_svc.get("status") in ("UP", "RUNNING", "running", "healthy"):
                        agy_running = True
                elif isinstance(svcs, list):
                    services_total = len(svcs)
                    services_up = sum(1 for s in svcs if isinstance(s, dict) and s.get("status") in ("UP", "RUNNING", "running", "healthy"))
    except Exception:
        pass

    reconcile_res = None
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_port_reconcile
        if hasattr(forge_port_reconcile, "run_cycle"):
            reconcile_res = forge_port_reconcile.run_cycle(kill=False)
    except Exception:
        pass

    body_local = {
        "n_organes": n_organes,
        "n_modules": n_modules,
        "ram_pct": ram_pct,
        "services_up": services_up,
        "services_total": services_total,
        "port_reconcile": reconcile_res
    }

    # 3. Cloud LLM
    cloud_llm = {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_quota_tracker
        base_quotas = forge_quota_tracker.get_all_quotas()
        cloud_llm = base_quotas.get("providers", {})
    except Exception:
        pass

    # Extended Cloud LLM providers check
    extra_providers = {
        "nvidia": {"env_var": "NVIDIA_API_KEY", "note": "Nemotron NIM integrate.api.nvidia.com"},
        "cerebras": {"env_var": "CEREBRAS_API_KEY", "note": "1M tok/j ultra-fast"},
        "sambanova": {"env_var": "SAMBANOVA_API_KEY", "note": "SambaNova Cloud"},
        "cohere": {"env_var": "COHERE_API_KEY", "note": "Command-R / Embed"},
        "hf": {"env_var": "HF_TOKEN", "note": "HuggingFace Serverless / Jobs"}
    }
    
    try:
        from nokido_agent.app import forge_secrets as fs
    except Exception:
        fs = None

    for p_name, p_info in extra_providers.items():
        if p_name not in cloud_llm:
            has_key = False
            if fs:
                try:
                    has_key = bool(fs.get_secret(p_info["env_var"]))
                except Exception:
                    pass
            if not has_key:
                has_key = bool(os.environ.get(p_info["env_var"]))
            cloud_llm[p_name] = {
                "provider": p_name,
                "available": has_key,
                "note": p_info["note"]
            }

    # 4. Compute
    compute = {
        "kaggle": {
            "type": "gpu",
            "quota": "30h/week free T4/P100",
            "note": "Kaggle Kernels API"
        },
        "hf_jobs": {
            "type": "paid_compute",
            "quota": "HTTP 402 / credit-based",
            "note": "HuggingFace Jobs"
        }
    }

    # 5. Agentic
    agy_path = r"%USERPROFILE%\AppData\Local\agy\bin\agy.exe"
    agentic = {
        "agy": {
            "available": bool(agy_running) or os.path.exists(agy_path),
            "backend": "Gemini 3.x via agy.exe",
            "path": agy_path
        },
        "swarm": {
            "available": True,
            "tool": "forge_spawn_swarm"
        }
    }

    # 6. Budget
    cost_usd_today = 0.0
    daily_budget = float(os.environ.get("LAFORGE_DAILY_BUDGET_USD", 5.0))
    cortisol_quota_cloud = 0.0
    try:
        from nokido_agent.app.forge_token_monitor import daily_report
        cost_usd_today = float(daily_report().get("daily_cost_usd", 0.0) or 0.0)
    except Exception:
        pass
    try:
        from nokido_agent.app.forge_endocrine import read as _hormone_read
        cortisol_quota_cloud = float(_hormone_read("CORTISOL_QUOTA_CLOUD") or 0.0)
    except Exception:
        pass

    budget = {
        "cost_usd_today": cost_usd_today,
        "daily_budget": daily_budget,
        "cortisol_quota_cloud": cortisol_quota_cloud
    }

    return {
        "identity": identity,
        "body_local": body_local,
        "cloud_llm": cloud_llm,
        "compute": compute,
        "agentic": agentic,
        "budget": budget
    }


def publish_self_state(path: str | None = None) -> Dict[str, Any]:
    """Calcule self_snapshot() et le persiste = SSoT de soi (sandbox/self_state.json).

    Lisible par tout organe/agent sans recalcul (proprioception partagee, comme
    resource_state.json pour la RAM). Rafraichi par la phase homeostatique.
    """
    import time
    snap = self_snapshot()
    snap["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    target = Path(path) if path else (ROOT / "sandbox" / "self_state.json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(snap, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8",
        )
        return {"ok": True, "path": str(target), "sections": list(snap.keys())}
    except Exception as e:
        return {"ok": False, "err": str(e)[:200]}
