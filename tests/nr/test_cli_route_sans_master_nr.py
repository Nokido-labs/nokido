"""Revue du 6/11 : jeton court indisponible = arret. Jamais de repli sur MASTER_TOKEN dans l'environnement d'un CLI enfant."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_cli_route as r  # noqa: E402


def test_pas_de_repli_sur_le_coffre_si_le_jeton_court_echoue(monkeypatch):
    from nokido_agent.app import forge_integrity, forge_secrets

    def panne():
        raise RuntimeError("manager indisponible")

    lus = []
    monkeypatch.setattr(forge_integrity, "get_manager", panne)
    monkeypatch.setattr(forge_secrets, "get_secret", lambda nom, *a, **k: lus.append(nom) or "valeur-du-coffre")
    assert r._obtenir_jeton_auth("claude") is None
    assert lus == [], "aucun secret lu en repli"


def test_le_source_ne_cite_plus_le_jeton_maitre():
    assert "MASTER_TOKEN\")" not in (ROOT / "tools" / "forge_cli_route.py").read_text(encoding="utf-8")
