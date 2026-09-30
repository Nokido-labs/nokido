"""NR -- la sonde tool-call mesure les modeles DESIGNES et FUSIONNE leur verdict au rapport.

MESURE du 2026-09-25 : opencode derriere la passerelle recevait « HTTP 413 : Request too large
for model openai/gpt-oss-20b ... tokens per minute (TPM): Limit 8000, Requested 25631 ». Groq
gratuit ne peut pas porter un agent (prompt + schemas d'outils ~25 k jetons par tour). Les seuls
modeles mesures `APPELLE` etaient les petits : la sonde ne testait que les 3 plus petits de chaque
fournisseur. `--modeles fournisseur/modele,...` mesure ceux qu'on designe (les forts) ; le
rapport garde les autres verdicts -- une mesure ciblee n'efface pas le reste de la liste blanche.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.tools import forge_tool_call_probe as sonde  # noqa: E402


def test_une_limite_de_debit_n_est_pas_un_refus(monkeypatch):
    """MESURE 2026-09-25 : 4 modeles Mistral mesures d'affilee -> HTTP 429 « Rate limit exceeded »,
    classes REFUSE. Un 429 ne dit RIEN de la capacite d'appeler un outil : NON_MESURE."""
    import io
    import urllib.error

    def _leve(*a, **k):
        raise urllib.error.HTTPError("https://x", 429, "Too Many Requests", {},
                                     io.BytesIO(b'{"message":"Rate limit exceeded"}'))

    monkeypatch.setattr(sonde.urllib.request, "urlopen", _leve)
    fiche = sonde.interroger("https://api.mistral.ai/v1", "cle", "mistral-small-latest")
    assert fiche["etat"] == "NON_MESURE", fiche


def test_fusion_remplace_le_meme_modele_et_garde_les_autres():
    anciens = [
        {"fournisseur": "groq", "modele": "openai/gpt-oss-20b", "etat": "APPELLE"},
        {"fournisseur": "mistral", "modele": "mistral-small-latest", "etat": "NON_MESURE"},
    ]
    nouveaux = [{"fournisseur": "mistral", "modele": "mistral-small-latest", "etat": "APPELLE"}]
    fusion = sonde.fusionner(anciens, nouveaux)
    assert {(r["fournisseur"], r["modele"]): r["etat"] for r in fusion} == {
        ("groq", "openai/gpt-oss-20b"): "APPELLE",
        ("mistral", "mistral-small-latest"): "APPELLE",
    }


def test_modeles_designes_mesures_et_fusionnes(tmp_path, monkeypatch):
    rapport = tmp_path / "tool_call_probe.json"
    rapport.write_text(json.dumps({"resultats": [
        {"fournisseur": "groq", "modele": "openai/gpt-oss-20b", "etat": "APPELLE", "motif": "x"}]}),
        encoding="utf-8")
    monkeypatch.setattr(sonde, "SORTIE", rapport)
    vus = []

    def _interroger(base, cle, modele):
        vus.append((base, modele))
        return {"etat": "APPELLE", "motif": "numero='CMD-4711'"}

    monkeypatch.setattr(sonde, "interroger", _interroger)
    monkeypatch.setattr(sonde, "_cle", lambda nom: "cle-test")
    rc = sonde.main(["--modeles", "mistral/mistral-small-latest,inconnu/x"])
    assert rc == 0
    assert vus == [("https://api.mistral.ai/v1", "mistral-small-latest")]  # fournisseur inconnu : saute, dit
    verdicts = {(r["fournisseur"], r["modele"]): r["etat"]
                for r in json.loads(rapport.read_text(encoding="utf-8"))["resultats"]}
    assert verdicts == {("groq", "openai/gpt-oss-20b"): "APPELLE",
                        ("mistral", "mistral-small-latest"): "APPELLE"}
