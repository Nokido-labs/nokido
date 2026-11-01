"""NR 28/10 (recette reelle) : un keyring INDISPONIBLE n'est pas une epingle ABSENTE.

Mesure : le worker ACP tourne sous l'env `nokido_services`, ou le module `keyring` manque. `_keyring_get` avalait
l'ImportError et rendait None ; le worker repondait « aucune cle publique epinglee » alors que l'epingle etait
ecrite au coffre personnel de l'owner. UNKNOWN n'est pas NO : le refus doit dire ILLISIBLE et pourquoi.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_worker as W  # noqa: E402


def test_keyring_absent_est_illisible(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)   # import keyring -> ImportError
    assert W.epingle_coffre() is None
    assert "ILLISIBLE" in W.raison_epingle() and "keyring" in W.raison_epingle()


def test_epingle_absente_est_dite_absente(monkeypatch):
    monkeypatch.setattr(W, "_lire_coffre_personnel", lambda nom: None)
    assert W.epingle_coffre() is None
    assert "ABSENTE" in W.raison_epingle()
