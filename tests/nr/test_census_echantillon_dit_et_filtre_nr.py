# -*- coding: utf-8 -*-
"""NR — le census n'échantillonne pas de modèle non chat, et un fournisseur qu'il ne sonde pas est DIT.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de l'echantillonnage du census free tier"

CE QUI A ÉTÉ PAYÉ (21/10, doute owner fondé). La passe par défaut annonçait « 6 échantillons joignables » :
deepinfra sondé sur `Qwen/Qwen3-ASR-0.6B` (reconnaissance vocale : _INADAPTES n'excluait ni asr ni speech ni audio
ni ocr), et SambaNova (6 modèles déclarés, 0 gratuit annoncé, 0 prix non publié) JAMAIS sondé, sans une ligne pour
le dire -- absent du registre comme s'il n'existait pas. Contrat (tools/forge_free_tier_census.py) :
  - _INADAPTES écarte aussi asr / speech / audio / ocr / transcri ;
  - un fournisseur dont le catalogue répond mais qui n'a AUCUN candidat est inscrit `etat: NON_SONDE` avec sa
    raison (décomptes), et imprimé « NON SONDE ».
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ft(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location("ft_echantillon_nr", ROOT / "tools" / "forge_free_tier_census.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ft_echantillon_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def test_les_modeles_non_chat_sont_ecartes(monkeypatch):
    ft = _ft(monkeypatch)
    for nom in ("Qwen/Qwen3-ASR-0.6B", "nvidia/Nemotron-3.5-ASR-Streaming", "x/speech-to-text", "y/audio-large",
                "z/deepseek-ocr", "w/transcriber-1b"):
        assert any(mot in nom.lower() for mot in ft._INADAPTES), "non-chat non ecarte : %s" % nom
    assert not any(mot in "meta-llama/llama-3.1-8b-instruct" for mot in ft._INADAPTES)


def test_un_fournisseur_sans_candidat_est_dit_non_sonde(monkeypatch, tmp_path, capsys):
    ft = _ft(monkeypatch)
    monkeypatch.setattr(ft, "SORTIE", tmp_path / "census.json")
    monkeypatch.setattr(ft, "SURFACES", [("sambanova", None, "https://api.example/v1")])
    monkeypatch.setattr(ft, "catalogue", lambda base, cle: (200, [{"id": "Meta-Llama-3.3-70B-Instruct"}], {}))
    monkeypatch.setattr(ft, "est_gratuit", lambda m, etiquette: False)
    sondes = []
    monkeypatch.setattr(ft, "joignable", lambda base, cle, modele: sondes.append(modele) or (True, ""))
    monkeypatch.setattr(sys, "argv", ["forge_free_tier_census.py"])
    assert ft.main() == 0
    doc = json.loads((tmp_path / "census.json").read_text(encoding="utf-8"))
    entree = [f for f in doc["fournisseurs"] if f["fournisseur"] == "sambanova"][0]
    assert entree.get("etat") == "NON_SONDE" and entree.get("raison"), entree
    assert sondes == []
    assert "NON SONDE" in capsys.readouterr().out
