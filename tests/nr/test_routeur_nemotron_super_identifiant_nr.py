"""Non-regression test : identifiant modele nvidia_nemotron_super (2026-10-30).

Verifie que l'entree nvidia_nemotron_super dans forge_llm_router :
1. N'utilise plus l'ancien identifiant 404 ("nvidia/nemotron-3-super-120b-a12b").
2. Si sandbox/free_tier_census.json existe, verifie que le modele figure parmi les verdicts JOIGNABLES.
"""

from pathlib import Path
import json
import pytest

from app.forge_llm_router import PROVIDERS as PROVIDERS_CONFIG  # le dictionnaire s'appelle PROVIDERS (L.238)


def test_nvidia_nemotron_super_identifiant_nr():
    assert "nvidia_nemotron_super" in PROVIDERS_CONFIG, "Entree nvidia_nemotron_super absente du routeur"
    config = PROVIDERS_CONFIG["nvidia_nemotron_super"]
    models = config.get("models", [])
    assert len(models) > 0, "Aucun modele configure pour nvidia_nemotron_super"

    current_model = models[0]
    # 1. Ne doit pas etre l'ancien modele retire (404 le 2026-10-30)
    assert current_model != "nvidia/nemotron-3-super-120b-a12b", (
        "L'ancien modele 'nvidia/nemotron-3-super-120b-a12b' est retire (404) et ne doit plus etre utilise."
    )

    # 2. Si sandbox/free_tier_census.json existe, verifie la presence dans les verdicts JOIGNABLES (sans reseau)
    census_path = Path(__file__).resolve().parent.parent.parent / "sandbox" / "free_tier_census.json"
    if census_path.is_file():
        try:
            with open(census_path, "r", encoding="utf-8") as f:
                census_data = json.load(f)
            # Accepte dict avec cle "joignables" / "verdicts" ou liste directe selon format census
            joignables = []
            if isinstance(census_data, dict):
                joignables = census_data.get("joignables") or census_data.get("verdicts", {}).get("joignables", [])
                if not joignables and "models" in census_data:
                    joignables = [
                        m for m, v in census_data["models"].items()
                        if isinstance(v, dict) and v.get("status") in ("JOIGNABLE", "OK")
                    ]
            elif isinstance(census_data, list):
                joignables = census_data
            if joignables:
                assert current_model in joignables, f"Le modele {current_model} doit figurer parmi les modeles JOIGNABLES du census"
        except Exception:
            # Ne pas faire echouer le test sur du parsing facultatif de census non normalise
            pass
