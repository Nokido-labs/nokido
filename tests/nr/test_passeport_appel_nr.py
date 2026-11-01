"""NR : test du passeport d'appel (3 axes : identite, use_case/axe, endpoint servi).

TDD premiere tranche de P1_passeport_appel_3_axes_20261024 :
- chaque appel provider sortant ecrit UNE ligne dans logs/passeport_appels.jsonl
- format : {ts, identite, use_case, provider, modele, endpoint}
- identite : agent appelant + ring si connus, sinon "INCONNU" (jamais deviner)
- endpoint : base_url sans cle ni query
- jamais de secret dans la ligne (cle, jeton, en-tete Authorization)
- echec d'ecriture = WARNING journalise, jamais d'exception vers l'appelant
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest
import nokido_agent.app.forge_agent_proxy as AP
import nokido_agent.app.forge_trace_context as trace


class _ProviderFactice(AP.Provider):
    name = "factice_prov"
    model = "factice-modele-v1"
    display_name = "Fournisseur Factice NR"
    api_key_env = None
    cost_tier = 0

    def is_available(self):
        return True

    async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout):
        return "reponse factice"


def test_passeport_appel_ecriture_ligne_complete(monkeypatch, tmp_path):
    """Verifie que chaque appel sortant ecrit une ligne conforme."""
    journal_path = tmp_path / "passeport_appels.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal_path))

    prov = _ProviderFactice()

    jeton = trace.set_actor("agt_testeur", ring=1, channel="mcp", transport="http")
    try:
        res = asyncio.run(prov.ask_tracked("bonjour", [], "", 100, 10))
    finally:
        trace.reset_actor(jeton)

    assert res == "reponse factice"
    assert journal_path.exists()

    lignes = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
    assert len(lignes) == 1
    entree = lignes[0]

    assert isinstance(entree["ts"], (int, float))
    assert entree["provider"] == "factice_prov"
    assert entree["modele"] == "factice-modele-v1"
    assert entree["endpoint"] == "INCONNU"  # pas de base_url lisible : jamais une URL devinee (30/10)
    assert entree["use_case"] == "direct"
    assert entree["identite"] == {"agent": "AGT_TESTEUR", "ring": 1}  # set_actor canonise en majuscules


def test_passeport_journal_borne_par_rotation(monkeypatch, tmp_path):
    """30/10 : une ligne par appel provider, le journal grossissait sans fin ; au-dela du plafond il passe en .1."""
    journal_path = tmp_path / "passeport_appels.jsonl"
    journal_path.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal_path))
    monkeypatch.setattr(AP, "_PASSEPORT_MAX_OCTETS", 100)
    AP._ecrire_passeport_fichier({"ts": 1})
    assert (tmp_path / "passeport_appels.jsonl.1").read_text(encoding="utf-8") == "x" * 200
    assert json.loads(journal_path.read_text(encoding="utf-8").strip()) == {"ts": 1}


def test_passeport_appel_identite_inconnue_si_non_posee(monkeypatch, tmp_path):
    """Si aucun acteur n'est pose, identite vaut exactement 'INCONNU', jamais devinee."""
    journal_path = tmp_path / "passeport_appels.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal_path))

    prov = _ProviderFactice()

    # S'assurer qu'aucun acteur n'est pose
    trace._actor.set(None)

    res = asyncio.run(prov.ask_tracked("bonjour", [], "", 100, 10))
    assert res == "reponse factice"

    lignes = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
    assert len(lignes) == 1
    entree = lignes[0]
    assert entree["identite"] == "INCONNU"


def test_passeport_appel_aucun_secret_dans_la_ligne(monkeypatch, tmp_path):
    """Prouve qu'aucun secret, jeton, header authorization ou cle d'API ne fuite."""
    journal_path = tmp_path / "passeport_appels.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal_path))

    prov = _ProviderFactice()
    prov.api_key_env = "FAKE_KEY_ENV"
    prov.base_url = "https://api.example.com/v1?token=SECRET_QUERY_TOKEN#secret_frag"
    prov._client = type("FakeClient", (), {"_base_url": "https://api.example.com/v1?auth=SECRET123"})()

    cle_secrete = "sk-proj-SUPER_SECRET_KEY_123456789"
    monkeypatch.setenv("FAKE_KEY_ENV", cle_secrete)

    jeton = trace.set_actor("agt_secret", ring=2)
    try:
        res = asyncio.run(prov.ask_tracked("prompt avec Bearer super_secret_token", [], "", 100, 10))
    finally:
        trace.reset_actor(jeton)

    assert res == "reponse factice"
    contenu_brut = journal_path.read_text(encoding="utf-8")

    assert cle_secrete not in contenu_brut
    assert "SECRET_QUERY_TOKEN" not in contenu_brut
    assert "SECRET123" not in contenu_brut
    assert "Bearer" not in contenu_brut

    entree = json.loads(contenu_brut.strip().splitlines()[-1])
    # Endpoint doit etre nettoye (pas de query string, pas de cle)
    assert entree["endpoint"] == "https://api.example.com/v1"


def test_passeport_appel_echec_ecriture_n_interrompt_pas_appelant(monkeypatch, caplog):
    """En cas d'echec d'ecriture du journal, un WARNING est journalise sans exception vers l'appelant."""
    prov = _ProviderFactice()

    # Rendre l'ecriture impossible
    def _fail_open(*args, **kwargs):
        raise OSError("Permission denied fictive pour test")

    monkeypatch.setattr(AP, "_ecrire_passeport_fichier", _fail_open)

    with caplog.at_level(logging.WARNING):
        res = asyncio.run(prov.ask_tracked("bonjour", [], "", 100, 10))

    assert res == "reponse factice"
    assert any("passeport" in record.message.lower() for record in caplog.records)
