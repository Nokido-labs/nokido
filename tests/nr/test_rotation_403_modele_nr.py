"""NR — un 403 imputable au MODELE ne doit pas degrader la CLE.

Mesure 2026-09-03 : `mistral-large-latest` rend
  {"type":"tier_not_allowed","message":"This model is not available in your
   subscription tier","code":"1910"}
alors que `mistral-small-latest` repond 200 **avec la meme cle**. Or
`mark_http` mappait tout 403 vers `mark(..., "bad")` : un seul appel au modele
hors souscription evinçait le provider entier.

Deux fautes distinctes derriere le meme code HTTP :
  - cle revoquee / invalide          -> la CLE est mauvaise
  - modele hors souscription/absent  -> la cle est SAINE, le modele est interdit

Les confondre condamne ce qui marche — exactement ce que l'owner a interdit le
meme jour (« n'enterre rien »), applique aux credentials.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _rotation(monkeypatch):
    chemin = ROOT / "app" / "forge_key_rotation.py"
    if not chemin.exists():
        pytest.skip("forge_key_rotation absent")
    sys.path.insert(0, str(ROOT / "app"))
    spec = importlib.util.spec_from_file_location("forge_key_rotation_nr", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vus = []
    monkeypatch.setattr(mod, "mark",
                        lambda env, key, etat, raison="": vus.append((env, etat, raison)))
    return mod, vus


def test_403_tier_not_allowed_ne_degrade_pas_la_cle(monkeypatch):
    mod, vus = _rotation(monkeypatch)
    mod.mark_http("MISTRAL_API_KEY", "k", 403,
                  '{"type":"tier_not_allowed","message":"This model is not '
                  'available in your subscription tier"}')
    assert vus == [], "la cle a ete degradee alors que le 403 accuse le modele"


def test_403_sans_marqueur_degrade_bien_la_cle(monkeypatch):
    """Contre-epreuve : un vrai 403 de credential doit TOUJOURS mordre.

    Sans elle, une regle trop large rendrait le garde inoffensif et on croirait
    la cle protegee alors qu'elle ne serait plus jamais signalee.
    """
    mod, vus = _rotation(monkeypatch)
    mod.mark_http("MISTRAL_API_KEY", "k", 403, "Forbidden: invalid api key")
    assert vus and vus[0][1] == "bad", "un 403 de credential doit degrader la cle"


def test_401_degrade_toujours(monkeypatch):
    mod, vus = _rotation(monkeypatch)
    mod.mark_http("X", "k", 401, "tier_not_allowed")
    assert vus and vus[0][1] == "bad", (
        "un 401 est une faute d'AUTHENTIFICATION : le marqueur modele ne doit pas "
        "l'innocenter")


def test_429_reste_un_quota(monkeypatch):
    mod, vus = _rotation(monkeypatch)
    mod.mark_http("X", "k", 429)
    assert vus and vus[0][1] == "quota"


def test_appel_sans_detail_reste_compatible(monkeypatch):
    """Les appelants historiques passent 3 arguments : ils ne doivent pas casser."""
    mod, vus = _rotation(monkeypatch)
    mod.mark_http("X", "k", 200)
    assert vus and vus[0][1] == "ok"


def test_le_proxy_transmet_bien_le_detail():
    """Un garde sans emetteur ne garde rien : l'appelant DOIT passer le corps."""
    src = (ROOT / "app" / "forge_agent_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("mark_http(")
    assert i > 0, "forge_agent_proxy n'appelle plus mark_http"
    extrait = src[i:i + 400]
    assert "e.status_code," in extrait, (
        "mark_http est appele sans 4e argument : la protection ne s'appliquera "
        "jamais en production")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
