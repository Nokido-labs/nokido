# -*- coding: utf-8 -*-
"""NR juge deterministe : reglage GPU automatique d'Ollama (mesures de reference 516c027bd, banc 29/10)."""
import json

from app import forge_host_capabilities as hc

MODELES = [
    {"nom": "qwen2.5-coder:1.5b", "taille_go": 1.0},
    {"nom": "laforge-qwen", "taille_go": 1.1},
    {"nom": "deepseek-coder:6.7b", "taille_go": 3.8},
]
GO = 1024 ** 3


def _ps(*gpus):
    return json.dumps(list(gpus))


def test_a_8700g_780m_qwmemorysize_8go():
    sortie = _ps({"Name": "AMD Radeon(TM) 780M Graphics", "AdapterRAM": 4293918720, "QwMemorySize": 8 * GO,
                  "DriverVersion": "32.0", "VideoProcessor": "AMD Radeon Graphics Processor"})
    gpus = hc._gpus_depuis_json(sortie)
    assert gpus[0]["type"] == "integre"
    assert gpus[0]["vram_gb"] == 8.0
    assert gpus[0]["memoire_source"] == "qwMemorySize"
    r = hc.regler_ollama({"gpus": gpus}, MODELES)
    assert r["env"]["OLLAMA_IGPU_ENABLE"] == "1"
    assert r["env"]["OLLAMA_GPU_OVERHEAD"] == str(GO)
    assert r["env"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert r["num_gpu_par_modele"] == {"qwen2.5-coder:1.5b": 0, "laforge-qwen": 0}
    assert "deepseek-coder:6.7b" not in r["num_gpu_par_modele"]
    assert r["motifs"]


def test_b_nvidia_dedie_pas_d_igpu_enable():
    sortie = _ps({"Name": "NVIDIA GeForce RTX 3060", "AdapterRAM": 4293918720, "QwMemorySize": 12 * GO})
    gpus = hc._gpus_depuis_json(sortie)
    assert gpus[0]["type"] == "dedie"
    r = hc.regler_ollama({"gpus": gpus}, MODELES)
    assert "OLLAMA_IGPU_ENABLE" not in r["env"]
    assert r["num_gpu_par_modele"] == {}
    assert any("non mesure, defaut Ollama" in m for m in r["motifs"])


def test_c_aucun_gpu():
    r = hc.regler_ollama({"gpus": []}, MODELES)
    assert r["env"] == {} and r["num_gpu_par_modele"] == {}
    assert r["motifs"]


def test_d_adapterram_seul_plafonne():
    sortie = _ps({"Name": "AMD Radeon(TM) 780M Graphics", "AdapterRAM": 4293918720})
    gpus = hc._gpus_depuis_json(sortie)
    assert gpus[0]["memoire_source"] == "plafonnee_4go"
    assert gpus[0]["vram_gb"] == 4.0


def test_e_indecidable_inconnu_aucun_reglage():
    sortie = _ps({"Name": "Microsoft Basic Display Adapter", "AdapterRAM": 0})
    gpus = hc._gpus_depuis_json(sortie)
    assert gpus[0]["type"] == "inconnu"
    r = hc.regler_ollama({"gpus": gpus}, MODELES)
    assert r["env"] == {} and r["num_gpu_par_modele"] == {}
    assert any("inconnu" in m for m in r["motifs"])


def test_classes_connues():
    assert hc._classer_gpu("Intel(R) UHD Graphics 770", 0) == "integre"
    assert hc._classer_gpu("Intel(R) Arc(TM) A770 Graphics", 16.0) == "dedie"
    assert hc._classer_gpu("AMD Radeon RX 7900 XT", 20.0) == "dedie"
