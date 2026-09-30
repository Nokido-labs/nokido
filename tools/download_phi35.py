"""
Télécharge Phi-3.5-mini-instruct-onnx (variante DirectML) depuis HuggingFace.
Lance : python tools/download_phi35.py
"""

__FORGE_COLOR__ = "metabolisme/provider : telecharge Phi-3.5-mini ONNX (DirectML)"  # organe declare le 2026-09-06 (audit de raccordement)

from pathlib import Path

MODEL_DIR = Path(__import__("os").path.expanduser("~/Models/phi3.5-mini-directml"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

try:
    from huggingface_hub import snapshot_download

    print("Téléchargement en cours (environ 2.3 GB)...")
    path = snapshot_download(
        repo_id="microsoft/Phi-3.5-mini-instruct-onnx",
        allow_patterns=["directml/*"],
        local_dir=str(MODEL_DIR),
    )
    print(f"OK téléchargement terminé : {path}")

    # Test rapide
    import onnxruntime_genai as og

    model_path = str(MODEL_DIR / "directml")
    print(f"Test chargement modèle : {model_path}")
    m = og.Model(model_path)
    print(f"OK modèle chargé : {type(m)}")

except ImportError as e:
    print(f"FAIL import : {e}")
    print("Installe : pip install huggingface_hub onnxruntime-genai-directml")
except Exception as e:
    print(f"FAIL : {e}")
