"""NR -- le motif distingue MESURE et EXTRAPOLE (methode du takehome : n'est attribue a la mesure que ce qui a ete mesure).

Acceptation reelle 29/10 12 h 54 (job_88df8ba1b2f0) : moondream, nomic-embed-text et bge-m3, jamais bances, recevaient
num_gpu 0 avec le motif « mesure : prompt 3x plus lent » ; seuls qwen2.5-coder:1.5b et laforge-qwen l'ont ete
(banc_ollama_vulkan*_20261029). Le reglage reste (statu quo CPU), le motif ne ment plus."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

import forge_host_capabilities as H  # noqa: E402

IGPU = {"gpus": [{"name": "AMD Radeon 780M Graphics", "vram_gb": 8.0, "type": "integre"}]}
MODS = [{"nom": "qwen2.5-coder:1.5b", "taille_go": 0.92}, {"nom": "bge-m3:latest", "taille_go": 1.08}]


def test_modele_bance_motif_mesure():
    m = [x for x in H.regler_ollama(IGPU, MODS)["motifs"] if x.startswith("qwen2.5-coder:1.5b")]
    assert m and "mesure" in m[0] and "extrapol" not in m[0]


def test_modele_non_bance_motif_extrapole():
    p = H.regler_ollama(IGPU, MODS)
    assert p["num_gpu_par_modele"]["bge-m3:latest"] == 0  # reglage conserve (statu quo CPU)
    m = [x for x in p["motifs"] if x.startswith("bge-m3:latest")]
    assert m and "extrapol" in m[0] and "non mesure" in m[0]
