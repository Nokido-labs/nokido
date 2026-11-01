"""NR 31/10 (accord owner) -- une lecture observee du coffre NOMME sa chaine d'appel (fichier:fonction, jamais une valeur).

Mesure 31/10 : NokidoRSSWatcher lit FORGE_TOKEN_SERVICES via forge_hub_client a chaque demarrage, alors que son lanceur
lui injecte un jeton RSS_WATCHER ; le repli au chargement n'est PAS le chemin emprunte (aucune ligne de diagnostic) ->
l'appelant reel est ILLISIBLE. Le journal portait `module` (le lecteur direct) mais pas QUI l'appelait.
"""
from __future__ import annotations

import json

from nokido_agent.app import forge_secrets as S


def appelant_temoin_cof1():
    S._journaliser_observation("FORGE_TOKEN_TEMOIN", "LaForgeSbxOffline", "aurait_refuse:bac_ring_le_3")


def test_la_pile_nomme_l_appelant_sans_valeur(monkeypatch, tmp_path):
    j = tmp_path / "obs.jsonl"
    monkeypatch.setattr(S, "_JOURNAL_OBSERVATIONS", j)
    monkeypatch.setattr(S, "_DEJA_JOURNALISE", set())
    appelant_temoin_cof1()
    rec = json.loads(j.read_text(encoding="utf-8").splitlines()[-1])
    assert isinstance(rec.get("pile"), list) and rec["pile"]
    assert any("appelant_temoin_cof1" in maillon for maillon in rec["pile"])
    assert all(":" in maillon and " " not in maillon for maillon in rec["pile"])  # fichier:fonction, rien d'autre
    assert not any("forge_secrets.py" in maillon for maillon in rec["pile"])     # le guichet lui-meme n'est pas un appelant
