#!/usr/bin/env python3
"""
forge_spike_router_lite.py — SpikeRouter runtime sans PyTorch
==============================================================
Utilise uniquement numpy pour l'inférence.
Charge les poids exportés depuis le modèle PyTorch.
Tourne dans Exegol sans dépendances lourdes.
"""

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

WEIGHTS_PATH = Path(__file__).parent.parent / "models" / "spike_router_weights.json"
# Fallback Exegol
if not WEIGHTS_PATH.exists():
    WEIGHTS_PATH = Path("/tmp/spike_router_weights.json")

FEATURE_NAMES = [
    "has_binary",
    "is_elf",
    "bits_64",
    "pie",
    "canary",
    "nx",
    "has_win_fn",
    "has_gets",
    "has_printf_plt",
    "has_puts_plt",
    "has_system",
    "has_source_c",
    "has_source_py",
    "has_eval_exec",
    "has_scanf",
    "has_dockerfile",
    "has_server_py",
    "has_solve_py",
    "has_libc",
    "has_pcap",
    "has_images",
    "has_enc_files",
    "has_key_file",
    "cat_pwn",
    "cat_crypto",
    "cat_rev",
    "cat_web",
    "cat_misc",
    "cat_forensics",
    "binary_size_kb",
    "file_count",
]


class SpikeRouterLite:
    """Inférence du SpikeRouter en numpy pur."""

    def __init__(self, weights_path=None):
        wp = Path(weights_path) if weights_path else WEIGHTS_PATH
        data = json.loads(wp.read_text())
        self.fc1_w = np.array(data["fc1_w"])
        self.fc1_b = np.array(data["fc1_b"])
        self.fc2_w = np.array(data["fc2_w"])
        self.fc2_b = np.array(data["fc2_b"])
        self.threshold = data["threshold"]
        self.strategies = data["strategies"]
        self.leak = 0.85
        self.steps = 6

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Forward pass numpy."""
        h = np.maximum(0, x @ self.fc1_w.T + self.fc1_b)  # ReLU
        activations = h @ self.fc2_w.T + self.fc2_b

        # Spiking simulation
        membrane = np.zeros_like(activations)
        spike_counts = np.zeros_like(activations)
        for _ in range(self.steps):
            membrane = self.leak * membrane + activations
            spikes = (membrane >= self.threshold).astype(float)
            spike_counts += spikes
            membrane *= 1 - spikes

        return activations, spike_counts

    def predict(self, features: dict) -> tuple[str, float]:
        """Prédit la stratégie à partir d'un dict de features."""
        x = np.array([features.get(f, 0.0) for f in FEATURE_NAMES], dtype=np.float32)
        _, spikes = self.forward(x)

        max_spike = spikes.max()
        best_idx = int(spikes.argmax())
        confidence = max_spike / self.steps

        if confidence < 0.15:
            return "skip", float(confidence)
        return self.strategies[best_idx], float(confidence)

    def predict_top_k(self, features: dict, k: int = 3) -> list[tuple[str, float]]:
        """Top-k stratégies."""
        x = np.array([features.get(f, 0.0) for f in FEATURE_NAMES], dtype=np.float32)
        _, spikes = self.forward(x)

        indices = np.argsort(-spikes)[:k]
        results = []
        for i in indices:
            conf = spikes[i] / self.steps
            if conf >= 0.1:
                results.append((self.strategies[i], round(float(conf), 3)))
        return results if results else [("skip", 0.0)]


def extract_features_light(ch_dir: str, category: str) -> dict:
    """Extraction de features sans pwntools (version légère pour triage rapide)."""
    ch = Path(ch_dir)
    f = dict.fromkeys(FEATURE_NAMES, 0.0)

    cat_map = {
        "pwn": "cat_pwn",
        "crypto": "cat_crypto",
        "rev": "cat_rev",
        "web": "cat_web",
        "misc": "cat_misc",
        "forensics": "cat_forensics",
    }
    if category in cat_map:
        f[cat_map[category]] = 1.0

    for p in ch.iterdir():
        if not p.is_file():
            continue
        nm, sx = p.name.lower(), p.suffix.lower()
        if sx in (".c", ".cpp", ".h"):
            f["has_source_c"] = 1.0
        if sx == ".py" and nm not in ("solve.py", "solver.py", "sol.py", "solution.py"):
            f["has_source_py"] = 1.0
        if nm in ("solve.py", "solver.py", "sol.py", "solution.py"):
            f["has_solve_py"] = 1.0
        if nm == "dockerfile":
            f["has_dockerfile"] = 1.0
        if nm in ("server.py", "chall.py"):
            f["has_server_py"] = 1.0
        if "libc" in nm:
            f["has_libc"] = 1.0
        if sx in (".pcap", ".pcapng"):
            f["has_pcap"] = 1.0
        if sx in (".png", ".jpg", ".bmp"):
            f["has_images"] = 1.0
        if sx == ".enc" or "encrypted" in nm:
            f["has_enc_files"] = 1.0
        if "key" in nm and sx in (".txt", ".bin", ""):
            f["has_key_file"] = 1.0

    # Détecter le binaire (sans pwntools — juste file headers)
    for p in ch.iterdir():
        if (
            p.is_file()
            and p.suffix
            not in {
                ".py",
                ".c",
                ".cpp",
                ".h",
                ".json",
                ".txt",
                ".md",
                ".yml",
                ".sh",
                ".so",
                ".zip",
                ".gz",
                ".pcap",
                ".pcapng",
                ".png",
                ".jpg",
                ".pdf",
                ".hex",
            }
            and p.name not in {"Makefile", "Dockerfile", "flag.txt", "README.md"}
            and p.stat().st_size > 500
        ):
            f["has_binary"] = 1.0
            f["binary_size_kb"] = min(p.stat().st_size / 100000.0, 1.0)
            # Lire le magic number ELF
            try:
                with open(str(p), "rb") as fp:
                    magic = fp.read(20)
                    if magic[:4] == b"\x7fELF":
                        f["is_elf"] = 1.0
                        f["bits_64"] = 1.0 if magic[4] == 2 else 0.0
            except OSError as exc:
                # Meme correction que app/forge_spike_router.py : un `except` NU
                # attrapait KeyboardInterrupt/SystemExit, et un binaire illisible
                # rendait un vecteur de features neutre sans laisser de trace.
                logger.debug(f"analyse ELF impossible {p}: {exc}")
            break

    return f


# ── API pour le runner CTF ─────────────────────────────────────

_router_instance = None


def get_router():
    global _router_instance
    if _router_instance is None:
        _router_instance = SpikeRouterLite()
    return _router_instance


def route(ch_dir: str, category: str) -> list[tuple[str, float]]:
    """Point d'entrée: retourne les stratégies ordonnées par confiance spike."""
    features = extract_features_light(ch_dir, category)
    return get_router().predict_top_k(features, k=3)


if __name__ == "__main__":
    router = SpikeRouterLite()

    tests = [
        (
            "PWN ret2win",
            {
                "has_binary": 1,
                "is_elf": 1,
                "bits_64": 1,
                "has_win_fn": 1,
                "has_gets": 1,
                "cat_pwn": 1,
            },
        ),
        (
            "PWN ret2libc",
            {
                "has_binary": 1,
                "is_elf": 1,
                "bits_64": 1,
                "has_puts_plt": 1,
                "has_libc": 1,
                "cat_pwn": 1,
            },
        ),
        ("Crypto XOR", {"has_enc_files": 1, "has_key_file": 1, "cat_crypto": 1}),
        ("Web Docker", {"has_dockerfile": 1, "has_server_py": 1, "cat_web": 1}),
        ("Forensics", {"has_pcap": 1, "cat_forensics": 1}),
        ("Unknown", {}),
    ]

    for name, feats in tests:
        strat, conf = router.predict(feats)
        print(f"{name:20s} → {strat:20s} conf={conf:.3f}")
