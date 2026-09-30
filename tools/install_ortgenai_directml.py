"""
tools/install_ortgenai_directml.py — Install OnnxRuntime-GenAI with DirectML backend
for AMD Radeon iGPU (ryzen-ai). Checks, installs, and verifies provider availability.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_PYTHON = __import__("os").path.expanduser("~/miniforge3/python.exe")
WHL_FILENAME = "onnxruntime_genai_directml_ryzenai-0.11.2.whl"
WHL_SEARCH_DIRS = [
    Path.home() / "Downloads",
    Path(__import__("os").path.expanduser("~/Downloads")),
    Path(__file__).parent,
    Path(str(__import__("pathlib").Path(__file__).resolve().parents[2])),
]


def find_whl() -> Path:
    for d in WHL_SEARCH_DIRS:
        p = d / WHL_FILENAME
        if p.exists():
            print(f"Found: {p}")
            return p
    user_path = input(f"Enter full path to {WHL_FILENAME}: ").strip().strip('"')
    p = Path(user_path)
    if not p.exists():
        sys.exit(f"Not found: {p}")
    return p


def install_ort_genai(whl_path: Path) -> bool:
    print(f"Installing {whl_path.name} ...")
    steps = ["Preparing", "Installing", "Verifying"]
    for step in tqdm(steps, desc="install", unit="step"):
        if step == "Installing":
            r = subprocess.run(
                [LAFORGE_PYTHON, "-m", "pip", "install", str(whl_path), "--no-deps", "-q"],
                capture_output=True,
                text=True,
            errors="replace")
            if r.returncode != 0:
                print(f"[FAIL] {r.stderr[:500]}", file=sys.stderr)
                return False
    return True


def verify_directml() -> bool:
    print("\nVerifying DirectML installation...")
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        print(f"ORT providers: {providers}")
        has_dml = "DmlExecutionProvider" in providers
        print(f"DirectML: {'✓ available' if has_dml else '✗ not detected'}")
        return has_dml
    except ImportError:
        pass

    try:
        import onnxruntime_genai as ort_genai

        print(f"onnxruntime_genai version: {ort_genai.__version__}")
        return True
    except ImportError as e:
        print(f"[FAIL] onnxruntime_genai not importable: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    already = importlib.util.find_spec("onnxruntime_genai") is not None
    if already:
        print("onnxruntime_genai already installed.")
    else:
        whl = find_whl()
        ok = install_ort_genai(whl)
        if not ok:
            sys.exit(1)

    verify_directml()
