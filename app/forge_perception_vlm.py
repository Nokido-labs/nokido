"""
forge_perception_vlm.py — Perception multimodale (VLM local via Ollama).

Transducteur physique→sémantique pour AMI LeCun.
Prend une image (screenshot/webcam/path) → JSON état structuré → 640D embedding.

Modèles supportés (Ollama) :
  - moondream (2B, ~1.7GB, rapide)
  - llava:7b (7B, plus précis)
  - qwen2-vl:2b (Qwen2-VL, excellent sur texte+UI)

Organe : Module de Perception (LeCun AMI) — Transducteur physique
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "CYAN"

import base64
import json
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).parent.parent

# Modèles VLM disponibles localement (ordre de préférence)
_VLM_MODELS = ["moondream", "qwen2-vl:2b", "llava:7b", "llava"]
_TEXT_DIM = 384  # forge_state_encoder output
_CLIP_DIM = 256  # projection visuelle (latent JEPA dim)
OUTPUT_DIM = _TEXT_DIM + _CLIP_DIM  # 640D final


# ---------------------------------------------------------------------------
# Détection modèle VLM disponible
# ---------------------------------------------------------------------------


def _detect_vlm_model() -> Optional[str]:
    """Retourne le premier modèle VLM disponible dans Ollama."""
    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        available = {m["name"].split(":")[0] for m in data.get("models", [])}
        for m in _VLM_MODELS:
            if m.split(":")[0] in available:
                return m
    except Exception:
        pass
    return None


_vlm_model_cache: Optional[str] = None


def get_vlm_model() -> Optional[str]:
    global _vlm_model_cache
    if _vlm_model_cache is None:
        _vlm_model_cache = _detect_vlm_model()
    return _vlm_model_cache


# ---------------------------------------------------------------------------
# Capture écran (Windows)
# ---------------------------------------------------------------------------


def capture_screen() -> Optional[bytes]:
    """Capture l'écran principal → bytes PNG."""
    try:
        import mss

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            import io
            from PIL import Image

            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
    except ImportError:
        pass

    # Fallback PowerShell
    try:
        script = (
            "[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
            "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
            "$g=[System.Drawing.Graphics]::FromImage($b);"
            "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
            "$b.Save('C:\\\\Temp\\\\forge_screen.png');"
        )
        subprocess.run(["powershell", "-Command", script], timeout=10, capture_output=True)
        p = Path("C:/Temp/forge_screen.png")
        if p.exists():
            return p.read_bytes()
    except Exception:
        pass
    return None


def _image_to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def _resize_for_vlm(image_bytes: bytes, max_size: int = 512) -> bytes:
    """Réduit l'image pour économiser tokens VLM."""
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return image_bytes


# ---------------------------------------------------------------------------
# Analyse VLM via Ollama
# ---------------------------------------------------------------------------


def analyze_image(
    image_bytes: bytes,
    prompt: str = (
        "Analyze this screen/image. Return JSON with keys: "
        "status (ok/warning/error), main_task (string), "
        "visible_elements (list of strings), errors (list), "
        "system_state (brief string). JSON only, no markdown."
    ),
    model: Optional[str] = None,
    timeout: int = 30,
) -> dict:
    """Envoie image au VLM Ollama → retourne JSON structuré."""
    model = model or get_vlm_model()
    if not model:
        return {
            "status": "error",
            "error": "no VLM model available in Ollama",
            "main_task": "",
            "visible_elements": [],
            "errors": [],
            "system_state": "unknown",
        }

    img_resized = _resize_for_vlm(image_bytes)
    img_b64 = _image_to_b64(img_resized)

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 256},
        }
    ).encode()

    try:
        import urllib.request

        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        raw = resp.get("response", "").strip()
        # Nettoyer markdown si présent
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ok", "main_task": raw[:200], "visible_elements": [], "errors": [], "system_state": raw[:100]}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:100],
            "main_task": "",
            "visible_elements": [],
            "errors": [],
            "system_state": "vlm_timeout",
        }


# ---------------------------------------------------------------------------
# Entrée principale : scan_environment
# ---------------------------------------------------------------------------


def scan_environment(
    image_path: Optional[str] = None,
    capture: bool = True,
) -> dict:
    """
    Hub tool entry point.

    Args:
        image_path: chemin vers image (None = capture écran auto)
        capture:    si True et image_path=None, capture écran

    Returns dict JSON structuré prêt pour encode_state().
    """
    if image_path:
        image_bytes = Path(image_path).read_bytes()
    elif capture:
        image_bytes = capture_screen()
        if not image_bytes:
            return {"status": "error", "error": "screen capture failed", "system_state": "unknown"}
    else:
        return {"status": "error", "error": "no image source", "system_state": "unknown"}

    result = analyze_image(image_bytes)
    result["_source"] = "vlm_perception"
    result["_model"] = get_vlm_model() or "none"
    return result


# ---------------------------------------------------------------------------
# Embedding multimodal : 640D = CLIP(256) + text(384)
# ---------------------------------------------------------------------------


def _project_visual(image_desc: dict) -> np.ndarray:
    """Pseudo-CLIP : encode description visuelle en 256D via hash stable."""
    desc_str = json.dumps(image_desc, sort_keys=True)
    # Déterministe et rapide — vraie CLIP feature si transformers dispo
    try:
        from nokido_agent.app.forge_state_encoder import encode_state
        from nokido_agent.app.forge_world_model import get_jepa_model

        text_emb = encode_state(desc_str[:512])
        jepa = get_jepa_model()
        vis_emb = jepa.context_encode(text_emb)  # 384→256 projection
        return vis_emb
    except Exception:
        import hashlib

        h = int(hashlib.sha256(desc_str.encode()).hexdigest(), 16)
        rng = np.random.default_rng(h % (2**32))
        v = rng.standard_normal(256).astype("float32")
        return v / (np.linalg.norm(v) + 1e-8)


def encode_multimodal(
    text: str,
    image_bytes: Optional[bytes] = None,
    image_path: Optional[str] = None,
) -> np.ndarray:
    """
    640D = concat(visual_proj 256D, text_emb 384D).

    Si pas d'image → retourne text_emb padded à 640D.
    Compatible avec forge_state_encoder.encode_state() (drop-in upgrade).
    """
    from nokido_agent.app.forge_state_encoder import encode_state

    text_emb = encode_state(text).astype("float32")  # 384D

    if image_bytes is None and image_path:
        image_bytes = Path(image_path).read_bytes()

    if image_bytes is not None:
        vis_desc = analyze_image(image_bytes)
        vis_emb = _project_visual(vis_desc).astype("float32")  # 256D
    else:
        # Pad avec vecteur nul si pas d'image (backward compat)
        vis_emb = np.zeros(_CLIP_DIM, dtype="float32")

    combined = np.concatenate([vis_emb, text_emb])  # 640D
    norm = np.linalg.norm(combined)
    return combined / max(norm, 1e-8)


# ---------------------------------------------------------------------------
# Hub tool wrapper (appelé via /run action=python)
# ---------------------------------------------------------------------------


def hub_scan_environment(image_path: str = None) -> str:
    """Wrapper JSON string pour le hub. Retourne description de l'état écran."""
    result = scan_environment(image_path=image_path)
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    model = get_vlm_model()
    print(f"[perception_vlm] VLM model: {model or 'NONE (install moondream via ollama pull moondream)'}")
    if model:
        print("[perception_vlm] Testing screen capture...")
        state = scan_environment()
        print(json.dumps(state, indent=2, ensure_ascii=False))
        text_emb = encode_multimodal("hub status check")
        print(f"[perception_vlm] encode_multimodal (no image): shape={text_emb.shape}")
    else:
        print("[perception_vlm] Run: ollama pull moondream")
