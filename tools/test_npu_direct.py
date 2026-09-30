# Configurer les chemins pour trouver onnxruntime et le modele

__FORGE_COLOR__ = "metabolisme/provider : sonde DirectML onnxruntime sur le modele NPU (manuel)"  # organe declare le 2026-09-06 (audit de raccordement)
model_path = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "models" / "npu" / "minilm_int8.onnx")

try:
    import numpy as np
    import onnxruntime as ort

    print(f"ONNX Runtime: {ort.__version__}")
    print(f"NumPy: {np.__version__}")
    print(f"Available Providers: {ort.get_available_providers()}")

    # Forcer DirectML (DmlExecutionProvider) pour la Radeon 780M
    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession(model_path, providers=providers)

    print(f"Session active provider: {session.get_providers()[0]}")

    if "DmlExecutionProvider" in session.get_providers():
        print("[SUCCESS] NPU/GPU Accel (DirectML) is WORKING!")
    else:
        print("[WARNING] Running on CPU fallback.")

except Exception as e:
    print(f"[ERROR] {e}")
