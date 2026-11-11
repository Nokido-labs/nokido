"""NR -- la matrice ne mesure pas des CLIs morts/inconnus, et ne rend jamais INCONNU sans motif.

Mesure 2026-10-24 (`sandbox/matrice_modele_fournisseur.json`) : `--matrice --cli` a mesure 0/0 parce que
`CLI_PAR_DEFAUT = ("gemini_cli", "opencode")` — gemini_cli est un client MORT depuis le 04/07 (remplace par AGY)
et `opencode` n'est pas un fournisseur du proxy. Les couples `mammouth:*`, eux, etaient bien sondes en generation
mais restaient INCONNU : Mammouth rend 422 `ExceededBudget` (budget 0.0), un refus de SOLDE que le classement
ne nommait pas. Un INCONNU sans motif n'est jamais acceptable.

Pur : registre et sondes injectes, aucun reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as CENSUS  # noqa: E402
import forge_provider_catalogue as CATALOGUE  # noqa: E402


REGISTRE = [
    {"name": "gemini_cli", "available": True},
    {"name": "claude_cli", "available": True},
    {"name": "codex_cli", "available": True},
    {"name": "copilot_cli", "available": True},
    {"name": "agy_cli", "available": True},
    {"name": "groq", "available": True},
    {"name": "ollama", "available": True},
]


def _registre():
    return REGISTRE


def _noms_registre():
    return {fiche["name"] for fiche in REGISTRE}


def test_cli_defaut_derive_du_registre_sans_client_mort_ni_nom_inconnu():
    noms = CATALOGUE.cli_par_defaut(registry_fn=_registre)
    assert noms == ("agy_cli",)
    assert "gemini_cli" not in noms, "client mort depuis le 04/07"
    assert "opencode" not in noms, "nom inconnu du proxy"
    assert set(noms) <= _noms_registre(), "la liste par defaut doit venir du registre reel"
    assert not set(noms) & set(CENSUS.EXCLUS_PROXY), "aucun exclu du census par defaut"


def test_abonnements_owner_exclus_par_defaut_inclus_avec_drapeau():
    assert "claude_cli" not in CATALOGUE.cli_par_defaut(registry_fn=_registre)
    noms = CATALOGUE.cli_par_defaut(registry_fn=_registre, inclure_abonnements=True)
    assert {"agy_cli", "claude_cli", "codex_cli", "copilot_cli"} <= set(noms)
    assert "gemini_cli" not in noms, "un client mort reste exclu meme avec le drapeau abonnements"


def test_cli_indisponible_n_est_pas_mesure_par_defaut():
    registre = [{"name": "agy_cli", "available": False}, {"name": "claude_cli", "available": True}]
    assert CATALOGUE.cli_par_defaut(registry_fn=lambda: registre) == ()


def test_mammouth_budget_epuise_est_nomme_jamais_inconnu():
    appels = []

    def interroger(url, cle):
        return 200, ["glm-5", "qwen3-coder"], ""

    def sonder(url, cle, model_id):
        appels.append((url, model_id))
        return 422, ('{"error":{"message":"ExceededBudget: User=471007 over budget. '
                     'Spend=0.0, Budget=0.0","type":"budget_exceeded"}}'), 65

    matrice = CATALOGUE.construire_matrice(
        familles=("glm-5", "qwen3"),
        get_secret=lambda cle: "jeton" if cle == "MAMMOUTH_API_TOKEN" else "",
        interroger_fn=interroger,
        sonder_fn=sonder,
    )
    voies = [v for v in matrice["familles"]["glm-5"] if v["fournisseur"] == "mammouth"]
    assert voies, "Mammouth doit etre sonde en generation comme les autres"
    assert appels, "sonder_generation doit etre appele"
    for voie in voies:
        assert voie["etat"] == "SANS_SOLDE", voie
        assert voie.get("motif") == "budget_epuise", voie


def test_sonder_generation_mammouth_vise_chat_completions(monkeypatch):
    capture = {}

    class _Reponse:
        status = 200

        def read(self, _n=-1):
            return b'{"choices":[{"message":{"content":"OK"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _urlopen(req, timeout=None):
        capture["url"] = req.full_url
        return _Reponse()

    monkeypatch.setattr(CATALOGUE.urllib.request, "urlopen", _urlopen)
    code, detail, _ms = CATALOGUE.sonder_generation(
        "https://api.mammouth.ai/v1/models", "jeton", "glm-5")
    assert code == 200, detail
    assert capture["url"] == "https://api.mammouth.ai/v1/chat/completions"


def test_inconnu_porte_toujours_un_motif():
    def sonder(url, cle, model_id):
        return 503, "upstream connect error or disconnect/reset before headers", 63

    matrice = CATALOGUE.construire_matrice(
        familles=("glm-5",),
        get_secret=lambda cle: "jeton" if cle == "MAMMOUTH_API_TOKEN" else "",
        interroger_fn=lambda url, cle: (200, ["glm-5"], ""),
        sonder_fn=sonder,
    )
    voies = [v for v in matrice["familles"]["glm-5"] if v["fournisseur"] == "mammouth"]
    assert voies and voies[0]["etat"] == "INCONNU"
    assert voies[0].get("motif") == "service_indisponible_503"


def test_classement_garde_les_autres_422_hors_solde():
    assert CATALOGUE.classer_reponse(422, "invalid parameter: model") == "INCONNU"
    assert CATALOGUE.classer_reponse(422, '{"type":"budget_exceeded"}') == "SANS_SOLDE"
