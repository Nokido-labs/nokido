from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_phi3_npu
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_phi3_npu.py
======================
Phi-3-mini via ONNX GenAI RyzenAI — NPU XDNA AMD Phoenix.
Utilise graph_capture pour activer le vrai NPU (pas juste DirectML iGPU).
Monitoring : tok/s loggé + SetConsoleTitle pour visibilité Windows.
"""

import warnings as _warn, logging as _log_ort

_warn.filterwarnings("ignore", message=".*TryGraphCapture.*")
_warn.filterwarnings("ignore", category=DeprecationWarning, module="onnxruntime")
_log_ort.getLogger("onnxruntime").setLevel(_log_ort.ERROR)
import os, time, threading, ctypes
from pathlib import Path

PHI3_PATH = os.environ.get(
    "ONNXGENAI_MODEL_PATH", os.path.expanduser("~/Models/phi3-mini-directml/directml/directml-int4-awq-block-128")
)
MAX_TOKENS = int(get_secret("ONNXGENAI_MAX_TOKENS") or "2048")
TEMPERATURE = float(os.environ.get("ONNXGENAI_TEMPERATURE", "0.1"))

# Chemins DLL SDK AMD RyzenAI
_RYZEN = Path(r"C:/Program Files/RyzenAI/1.7.0")
_DEPLOY = _RYZEN / "deployment"
_ORT_BIN = _RYZEN / "onnxruntime" / "bin"

_model = None
_tokenizer = None
_lock = threading.Lock()
_stats = {"calls": 0, "tokens_total": 0, "ms_total": 0, "last_toks": 0, "last_ms": 0, "device": "?"}


def _add_dll_paths() -> None:
    """Ajoute les DLL AMD au chemin pour activer VitisAI EP."""
    for d in [_DEPLOY, _ORT_BIN]:
        if d.exists():
            try:
                os.add_dll_directory(str(d))
            except Exception:
                pass
    # Ajouter aussi au PATH
    extra = str(_DEPLOY) + ";" + str(_ORT_BIN)
    os.environ["PATH"] = extra + ";" + os.environ.get("PATH", "")
    os.environ["XLNX_VART_FIRMWARE"] = str(_RYZEN / "voe-4.0-win_amd64" / "xclbins")


def _load() -> bool:
    """Load."""
    global _model, _tokenizer
    if _model is not None:
        return True
    if not Path(PHI3_PATH).exists():
        print(f"[NPU] Modele introuvable: {PHI3_PATH}")
        return False
    _add_dll_paths()
    try:
        import onnxruntime_genai as og

        t0 = time.time()
        _model = og.Model(PHI3_PATH)
        _tokenizer = og.Tokenizer(_model)
        elapsed = int((time.time() - t0) * 1000)
        dev = getattr(_model, "device_type", "?")
        _stats["device"] = dev
        # Titre console visible dans moniteur Windows
        try:
            ctypes.windll.kernel32.SetConsoleTitleW(f"Nokido NPU [{dev}] pret")
        except Exception:
            pass
        print(f"[NPU] Phi-3-mini {dev} charge en {elapsed}ms")
        return True
    except Exception as e:
        print(f"[NPU] Erreur chargement: {e}")
        return False


def is_available() -> bool:
    """Is available."""
    return Path(PHI3_PATH).exists()


def get_stats() -> dict:
    """Get stats."""
    s = dict(_stats)
    if s["last_ms"] > 0:
        s["last_toks_per_sec"] = round(s["last_toks"] / (s["last_ms"] / 1000), 1)
    return s


def generate(prompt: str, system: str = "", max_tokens: int = 0) -> str:
    """
    Generation NPU/DirectML avec graph_capture pour maximiser
    l utilisation du XDNA.
    tok/s affiche en temps reel dans le titre de la console Windows.
    """
    with _lock:
        if not _load():
            return "[ERR] Phi-3 NPU non disponible"
        try:
            import onnxruntime_genai as og

            # Format Phi-3 chat
            full = (
                f"<|system|>{system}<|end|><|user|>{prompt}<|end|><|assistant|>"
                if system
                else f"<|user|>{prompt}<|end|><|assistant|>"
            )
            tokens = _tokenizer.encode(full)
            n_toks = max_tokens or MAX_TOKENS
            params = og.GeneratorParams(_model)
            params.set_search_options(
                max_length=n_toks,
                temperature=TEMPERATURE,
                do_sample=False,
            )
            # graph_capture : active le NPU XDNA pour le batch
            try:
                params.try_graph_capture_with_max_batch_size(1)
            except Exception:
                pass

            t0 = time.time()
            gen = og.Generator(_model, params)
            gen.append_tokens(tokens)

            stream = _tokenizer.create_stream()
            output = []
            tok_count = 0

            while not gen.is_done():
                gen.generate_next_token()
                piece = stream.decode(gen.get_next_tokens()[0])
                output.append(piece)
                tok_count += 1
                # Mettre a jour le titre console toutes les 10 tokens
                if tok_count % 10 == 0:
                    elapsed_now = max(1, int((time.time() - t0) * 1000))
                    tps = round(tok_count / (elapsed_now / 1000), 1)
                    try:
                        ctypes.windll.kernel32.SetConsoleTitleW(
                            f"Nokido NPU [{_stats['device']}] inferring... {tok_count} tok | {tps} tok/s"
                        )
                    except Exception:
                        pass

            result = "".join(output).strip()
            elapsed = int((time.time() - t0) * 1000)
            tps = round(tok_count / max(elapsed / 1000, 0.001), 1)

            _stats["calls"] += 1
            _stats["tokens_total"] += tok_count
            _stats["ms_total"] += elapsed
            _stats["last_toks"] = tok_count
            _stats["last_ms"] = elapsed

            # Titre final
            try:
                ctypes.windll.kernel32.SetConsoleTitleW(
                    f"Nokido NPU [{_stats['device']}] done | {tok_count}tok {elapsed}ms {tps}tok/s"
                )
            except Exception:
                pass

            print(f"[NPU] {_stats['device']} | {elapsed}ms | {tok_count} tokens | {tps} tok/s")
            return result

        except Exception as e:
            print(f"[NPU] ERR: {e}")
            return f"[ERR] NPU: {e}"


def purge() -> None:
    """Purge."""
    global _model, _tokenizer
    import gc

    with _lock:
        _model = _tokenizer = None
        gc.collect()
        print("[NPU] Phi-3 purge RAM")
