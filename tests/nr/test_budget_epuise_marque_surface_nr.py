"""NR 7/11 : un 402 « API budget exhausted » (Mistral) n'etait pas lu comme un quota.

Mesure : `_est_quota_epuise` rendait False, `classer_cause_echec` INCONNU, `_noter_indisponibilite` False : la surface
restait routable et recevait toutes les taches reaffectees, qui echouaient aussitot.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _chemin in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import forge_task_executor as T  # noqa: E402

RENDU_MISTRAL = ("Error: Client error '402 Payment Required' for url 'https://api.mistral.ai/v1/chat/completions' "
                 "API budget exhausted.")


def test_budget_epuise_est_un_quota_et_classe_quota():
    assert T._est_quota_epuise(RENDU_MISTRAL) is True
    assert T.classer_cause_echec(RENDU_MISTRAL) == "QUOTA"


def test_les_nr_ne_lisent_pas_le_registre_vivant():
    assert Path(T._FICHIER_INDISPO).name != "surfaces_indisponibles.json"


def test_mistral_402_payment_required_est_un_quota():
    # Mesure 9/11 : lots 07 et 09 du tri lot 5 rendus RIEN_PRODUIT avec ce texte, MISTRAL jamais marque indisponible,
    # le repli lui a passe 2 lots de plus. Un refus de paiement est un solde epuise.
    rendu = ("Reading API keys from the system keyring (set them as environment variables to skip this)\n"
             "Error: Client error '402 Payment Required' for url 'https://api.mistral.ai/v1/chat/completions'")
    assert T._est_quota_epuise(rendu) is True


def test_rendu_ordinaire_n_est_pas_un_quota():
    assert T._est_quota_epuise("le budget de tours est respecte") is False
