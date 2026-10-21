"""NR 18/10 -- consentement OAuth du connecteur des pairs : journal + etat des demandes (decision owner 18/10).

Rapport 55ec0a688 : la reconnexion ChatGPT web echoue EN SILENCE -- aucun journal d'organe pair (logs/ et
sandbox/ verifies), consentement de 300 s en loopback, aucun etat des demandes. Contrat : chaque evenement du
consentement (demande creee, consentie, expiree/inconnue, code errone) ajoute UNE ligne JSONL ; JAMAIS le code
d'appariement, le code d'autorisation ni l'identifiant complet de la demande ; l'etat des demandes en attente est
ecrit pour le tray et lisible par `--demandes` (le point d'entree reel) ; un journal non inscriptible ne casse
jamais le flux OAuth.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_bridge_oauth as O  # noqa: E402

CLIENT = types.SimpleNamespace(client_id="chatgpt-x", client_name="ChatGPT")
PARAMS = types.SimpleNamespace(scopes=None, code_challenge="c", redirect_uri="https://x.test/cb",
                               redirect_uri_provided_explicitly=True, resource=None, state="s")


def _autorite(tmp_path, monkeypatch, journal=None):
    monkeypatch.setattr(O, "JOURNAL_CONSENTEMENT", journal or tmp_path / "j.jsonl")
    monkeypatch.setattr(O, "ETAT_DEMANDES", tmp_path / "etat.json")
    monkeypatch.delenv("NOKIDO_BRIDGE_OAUTH_CLIENTS", raising=False)
    return O.AutoriteLocale()


def _journal(tmp_path):
    return [json.loads(l) for l in (tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()]


def test_creation_puis_consentement_journalises_sans_secret(tmp_path, monkeypatch):
    a = _autorite(tmp_path, monkeypatch)
    ident = asyncio.run(a.authorize(CLIENT, PARAMS)).split("demande=")[1]
    etat = json.loads((tmp_path / "etat.json").read_text(encoding="utf-8"))
    assert len(etat["demandes"]) == 1 and 0 < etat["demandes"][0]["expire_dans_s"] <= O.DUREE_CODE_S
    retour = a.accorder(ident)
    code = retour.split("code=")[1].split("&")[0]
    evenements = [e["evenement"] for e in _journal(tmp_path)]
    assert evenements == ["demande_creee", "consentie"]
    brut = (tmp_path / "j.jsonl").read_text(encoding="utf-8") + (tmp_path / "etat.json").read_text(encoding="utf-8")
    assert ident not in brut and code not in brut, "ni identifiant complet ni code d'autorisation"
    assert json.loads((tmp_path / "etat.json").read_text(encoding="utf-8"))["demandes"] == []


def test_expiration_et_code_errone_journalises(tmp_path, monkeypatch):
    a = _autorite(tmp_path, monkeypatch)
    ident = asyncio.run(a.authorize(CLIENT, PARAMS)).split("demande=")[1]
    a.journaliser_consentement("code_errone", client_id=CLIENT.client_id, demande=ident)
    a._demandes[ident]["expire"] = 0
    assert a.demande(ident) is None
    assert [e["evenement"] for e in _journal(tmp_path)] == ["demande_creee", "code_errone", "demande_expiree"]
    assert ident not in (tmp_path / "j.jsonl").read_text(encoding="utf-8")


def test_journal_non_inscriptible_ne_casse_pas_le_flux(tmp_path, monkeypatch):
    dossier = tmp_path / "pas_un_fichier"
    dossier.mkdir()
    a = _autorite(tmp_path, monkeypatch, journal=dossier)
    assert "demande=" in asyncio.run(a.authorize(CLIENT, PARAMS))


def test_drapeau_demandes_traverse_le_point_d_entree(tmp_path):
    etat = tmp_path / "etat.json"
    etat.write_text(json.dumps({"ecrit_le": "x", "demandes": [{"client_id": "chatgpt-x", "demande": "abc123",
                                                                 "expire_dans_s": 42}]}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_bridge_oauth.py"), "--demandes"],
                       capture_output=True, text=True, errors="replace", timeout=60,
                       env={**os.environ, "NOKIDO_PAIR_ETAT_DEMANDES": str(etat)})
    assert r.returncode == 0, r.stderr[-600:]
    assert json.loads(r.stdout[r.stdout.index("{"):])["demandes"][0]["expire_dans_s"] == 42
