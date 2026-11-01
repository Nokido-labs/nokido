"""NR -- ollama_cloud : seuls 7 modeles sont gratuits (compte FREE, owner 24/10). Aucun reseau, aucune cle."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_provider_catalogue as C  # noqa: E402

LISTE = {"beam", "gemma4:31b", "gpt-oss:120b", "gpt-oss:20b", "nemotron-3-nano:30b",
         "nemotron-3-super", "nemotron-3-ultra"}


def test_liste_free_exacte():
    assert set(C.OLLAMA_CLOUD_FREE) == LISTE


def test_palier():
    assert C.palier_ollama_cloud("gpt-oss:120b") == "FREE"
    assert C.palier_ollama_cloud("gpt-oss:120b-cloud") == "FREE"
    assert C.palier_ollama_cloud("kimi-k2:1t") == "HORS_PALIER"
    assert C.palier_ollama_cloud("deepseek-v3.1:671b") == "HORS_PALIER"


def test_matrice_ne_sonde_que_le_free_et_marque_hors_palier():
    sondes = []

    def sonder(url, cle, mid):
        sondes.append(mid)
        return 200, "", 10.0

    def interroger(url, cle):
        return 200, ["gpt-oss:120b", "gpt-oss:20b", "kimi-k2:1t", "qwen3:480b"], ""

    m = C.construire_matrice(familles=("gpt-oss", "gpt-oss-120b", "kimi-k2", "qwen3"),
                             get_secret=lambda n: "x" if n == "OLLAMA_API_KEY" else "",
                             interroger_fn=interroger, sonder_fn=sonder)
    assert "kimi-k2:1t" not in sondes and "qwen3:480b" not in sondes
    assert "gpt-oss:120b" in sondes
    assert m["hors_palier"]["ollama_cloud"] == ["kimi-k2:1t", "qwen3:480b"]


def test_cle_lue_par_coffre_pas_environ(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "depuis-environ")
    vus = []

    def gs(n):
        vus.append(n)
        return ""

    m = C.construire_matrice(get_secret=gs, interroger_fn=lambda u, c: (_ for _ in ()).throw(AssertionError()))
    assert "OLLAMA_API_KEY" in vus
    assert m["fournisseurs"]["ollama_cloud"] == "CLE_ABSENTE"
