"""NR - un /models PUBLIC ne prouve pas une cle, et ne la rearme jamais (15/10).

Mesure du 15/10 : SambaNova et OpenRouter servent /models SANS cle (HTTP 200). La cle SambaNova
obtenait 200 sur /models et 401 invalid_api_key a la generation ; en `--rearmer`, le catalogue
l'aurait REARMEE dans la rotation (« un 200 sur /models est la preuve que la cle vit »).
Reseau, coffre et rotation sont simules.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_provider_catalogue as C  # noqa: E402
from nokido_agent.app import forge_key_rotation, forge_secrets  # noqa: E402


def _banc(monkeypatch, etiquette):
    marques = []
    monkeypatch.setattr(C, "FOURNISSEURS", [(etiquette, "X_API_KEY", "https://api.exemple.test/v1/models")])
    monkeypatch.setattr(C, "interroger", lambda url, cle: (200, ["m1"], ""))
    monkeypatch.setattr(C, "modeles_cables", lambda: {})
    monkeypatch.setattr(forge_secrets, "get_secret", lambda k: "cle-factice-abcd")
    monkeypatch.setattr(forge_key_rotation, "mark", lambda *a, **k: marques.append(a))
    monkeypatch.setattr(sys, "argv", ["forge_provider_catalogue.py", "--rearmer"])
    return marques


def test_models_public_ne_rearme_pas_et_le_dit(monkeypatch, capsys):
    marques = _banc(monkeypatch, "sambanova")
    assert C.main() == 0
    assert marques == []
    assert "ne prouve PAS" in capsys.readouterr().out


def test_models_protege_rearme_toujours(monkeypatch):
    marques = _banc(monkeypatch, "groq")
    assert C.main() == 0
    assert len(marques) == 1 and marques[0][2] == "ok"


def test_la_liste_des_publics_est_mesuree():
    assert C.MODELS_PUBLIC == {"sambanova", "openrouter"}
