"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_npu_env
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_npu_env.py
NPU_ENV_MODULE_V1 - Gestionnaire env Conda Ryzen AI.
Module independant. Active/desactive sans toucher Nokido.
"""

import json, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_NAME = "ryzen-ai-final"
RYZEN_DIR = Path("C:/Program Files/RyzenAI/1.7.0")
CONDA_EXE = os.path.expanduser(r"~\miniforge3\Scripts\conda.exe")

WHEELS = [
    ("pip", "numpy==1.26.4"),
    ("whl", "voe-1.7.0-py3-none-win_amd64.whl"),
    ("whl", "onnxruntime_vitisai-1.23.2-cp312-cp312-win_amd64.whl"),
    ("whl", "onnxruntime_genai_directml_ryzenai-0.11.2-cp312-cp312-win_amd64.whl"),
]


def conda_run(args: list, timeout: int = 300) -> tuple:
    """Execute une commande dans l'env conda ryzen-ai."""
    cmd = [CONDA_EXE, "run", "-n", ENV_NAME] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    return r.returncode, r.stdout, r.stderr


def env_exists() -> bool:
    """Env exists."""
    r = subprocess.run([CONDA_EXE, "env", "list", "--json"], capture_output=True, text=True, timeout=10, errors="replace")
    try:
        return any(ENV_NAME in e for e in json.loads(r.stdout).get("envs", []))
    except Exception:
        return False


def create_env() -> bool:
    """Create env."""
    yaml = RYZEN_DIR / "env.yaml"
    if not yaml.exists():
        print(f"[NPU_ENV] env.yaml introuvable: {yaml}")
        return False
    print(f"[NPU_ENV] Creation env {ENV_NAME}...")
    r = subprocess.run([CONDA_EXE, "env", "create", "-f", str(yaml), "--force"], timeout=600)
    return r.returncode == 0


def install_wheels() -> bool:
    """Install wheels."""
    print("[NPU_ENV] Installation wheels NPU...")
    for kind, item in WHEELS:
        if kind == "whl":
            path = str(RYZEN_DIR / item)
            args = ["pip", "install", path, "--no-deps", "--force-reinstall"]
        else:
            args = ["pip", "install", item, "--force-reinstall"]
        code, out, err = conda_run(args)
        ok = code == 0 or "already" in out.lower()
        print(f"  [{'OK' if ok else 'ERR'}] {item[:60]}")
        if not ok:
            print(f"      {err[:80]}")
    return True


def check_providers() -> list:
    """Check providers."""
    code, out, err = conda_run(
        ["python", "-c", "import onnxruntime as o,json;print(json.dumps(o.get_available_providers()))"]
    )
    try:
        return json.loads(out.strip())
    except Exception:
        return []


def check_genai_version() -> str:
    """Check genai version."""
    code, out, err = conda_run(["python", "-c", "import onnxruntime_genai as og;print(og.__version__)"])
    return out.strip()


def setup() -> dict:
    """Setup complet env NPU. Idempotent."""
    result = {"env": ENV_NAME, "created": False, "providers": [], "genai_version": ""}
    if not env_exists():
        result["created"] = create_env()
        if not result["created"]:
            return result
    else:
        print(f"[NPU_ENV] {ENV_NAME} deja present")
        result["created"] = True
    install_wheels()
    result["providers"] = check_providers()
    result["genai_version"] = check_genai_version()
    vitisai = "VitisAIExecutionProvider" in result["providers"]
    dml = "DmlExecutionProvider" in result["providers"]
    print(f"[NPU_ENV] VitisAI={vitisai} | DirectML={dml} | GenAI={result['genai_version']}")
    return result


def run_in_npu_env(python_args: list) -> tuple:
    """Execute du code Python dans l'env NPU."""
    return conda_run(["python"] + python_args)


def run_phi3(prompt: str, system: str = "") -> str:
    """Lance Phi-3-mini dans l'env NPU dedie."""
    # Priorite : modele NPU VitisAI > modele DirectML
    phi3 = os.environ.get("ONNXGENAI_NPU_MODEL_PATH", os.path.expanduser(r"~\Models\phi3-mini-npu-ryzenai"))
    if not __import__("pathlib").Path(phi3).exists():
        phi3 = os.environ.get(
            "ONNXGENAI_MODEL_PATH", os.path.expanduser("~/Models/phi3-mini-directml/directml/directml-int4-awq-block-128")
        )
    script = ROOT / "sandbox" / "_phi3_run.py"
    script.write_text(
        "import onnxruntime_genai as og, sys\n"
        f"m=og.Model(r'{phi3}')\n"
        "t=og.Tokenizer(m);s=t.create_stream()\n"
        f"full='<|system|>{system}<|end|><|user|>{prompt}<|end|><|assistant|>' if '{system}' else '<|user|>{prompt}<|end|><|assistant|>'\n"
        "p=og.GeneratorParams(m);p.set_search_options(max_length=512,temperature=0.1,do_sample=False)\n"
        "g=og.Generator(m,p);g.append_tokens(t.encode(full))\n"
        "out=[]\n"
        "while not g.is_done():\n"
        "    g.generate_next_token()\n"
        "    out.append(s.decode(g.get_next_tokens()[0]))\n"
        "print(''.join(out))\n",
        encoding="utf-8",
    )
    code, out, err = run_in_npu_env([str(script)])
    return out.strip() if code == 0 else f"[ERR] {err[:200]}"


if __name__ == "__main__":
    result = setup()
    print(json.dumps(result, indent=2))
