"""NR -- `--proposer` lit les modeles par l'API HTTP d'Ollama et DIT quand la liste est illisible.

Acceptation reelle 29/10 12 h 53 (job_c88988aa13ec) : materiel juste (780M integre 8,0 Go, qwMemorySize), mais
`num_gpu_par_modele` VIDE et AUCUN motif : `ollama list` n'est pas executable par le compte du bac a sable (WinError 5
mesure). Faux urlopen, aucune vraie API, aucun vrai GPU."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

import forge_host_capabilities as H  # noqa: E402

GO = 2 ** 30
TAGS = {"models": [{"name": "qwen2.5-coder:1.5b", "size": int(0.92 * GO)},
                   {"name": "laforge-qwen:latest", "size": int(0.92 * GO)},
                   {"name": "deepseek-coder:6.7b", "size": int(3.56 * GO)}]}
IGPU = {"gpus": [{"name": "AMD Radeon 780M Graphics", "vram_gb": 8.0, "type": "integre", "memoire_source": "qwMemorySize"}]}


class _Rep:
    def __init__(self, corps):
        self.corps = corps

    def read(self):
        return json.dumps(self.corps).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_modeles_lus_par_api(monkeypatch):
    """/api/tags -> noms et tailles en Go, source « api »."""
    monkeypatch.setattr(H.urllib.request, "urlopen", lambda *a, **k: _Rep(TAGS))
    r = H._modeles_ollama()
    assert r["source"] == "api" and {m["nom"] for m in r["modeles"]} >= {"qwen2.5-coder:1.5b", "deepseek-coder:6.7b"}


def test_liste_illisible_est_dite(monkeypatch):
    """API et CLI injoignables -> source « illisible » + motif, jamais une liste vide silencieuse."""
    def boum(*_a, **_k):
        raise OSError("refuse")

    monkeypatch.setattr(H.urllib.request, "urlopen", boum)
    monkeypatch.setattr(H.shutil, "which", lambda _n: None)
    r = H._modeles_ollama()
    assert r["source"] == "illisible" and r["modeles"] == [] and r["motif"]


def test_proposer_reproduit_le_reglage_mesure(monkeypatch):
    """Acceptation (machine 29/10) : IGPU_ENABLE=1, num_gpu 0 pour les deux 1.5B, rien pour le 6.7B."""
    monkeypatch.setattr(H.urllib.request, "urlopen", lambda *a, **k: _Rep(TAGS))
    p = H.proposer(IGPU)["proposition"]
    assert p["env"]["OLLAMA_IGPU_ENABLE"] == "1"
    assert p["num_gpu_par_modele"] == {"qwen2.5-coder:1.5b": 0, "laforge-qwen:latest": 0}


def test_proposer_liste_illisible_motif(monkeypatch):
    """Liste illisible -> le motif figure dans la proposition."""
    monkeypatch.setattr(H.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(H.shutil, "which", lambda _n: None)
    p = H.proposer(IGPU)["proposition"]
    assert any("illisible" in m for m in p["motifs"])
