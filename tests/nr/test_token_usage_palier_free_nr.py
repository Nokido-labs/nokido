"""NR -- un fournisseur de palier GRATUIT par construction (suffixe « _free ») est compte FREE, pas UNKNOWN_PRICING.

Mesure du 24/10 (token_usage) : mistral_free (76 appels), openrouter_free (57) -> tous « tarif_inconnu », ce qui
noie la mesure du cout par surface. Seul le suffixe _free est une preuve de gratuite : groq, cerebras, etc. restent
UNKNOWN_PRICING tant qu'aucune mesure ne dit le contraire (un compte peut etre payant).
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_token_monitor as T  # noqa: E402


def _kind(tmp_path, monkeypatch, provider):
    db = tmp_path / "usage.db"
    monkeypatch.setattr(T, "DB", db)
    T.log_call("nr", provider, "un-modele", 10, 5, 1.0, alerter=False)
    return sqlite3.connect(str(db)).execute("SELECT cost_kind, cost_usd FROM token_usage").fetchone()


def test_suffixe_free_est_gratuit(tmp_path, monkeypatch):
    assert _kind(tmp_path, monkeypatch, "mistral_free") == ("FREE", 0.0)


def test_fournisseur_sans_preuve_de_gratuite_reste_inconnu(tmp_path, monkeypatch):
    kind, usd = _kind(tmp_path, monkeypatch, "cerebras")
    assert kind == "UNKNOWN_PRICING" and usd is None
