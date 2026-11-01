"""NR -- une base d'API qui finit deja par /models ne produit plus /models/models ni /models/chat/completions.

Trouve par OPENCODE_DEFAUT2 (docs/enquetes/glm_voie_gratuite_20261027.md) : plusieurs entrees de SURFACES finissent
par /models, et catalogue() / _completer() ajoutaient le suffixe -> mesures faussees sur ces fournisseurs.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "tools"))

import forge_free_tier_census as ftc  # noqa: E402


def _capturer(monkeypatch):
    vues = []

    class R(io.BytesIO):
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def faux(req, timeout=None):
        vues.append(req.full_url)
        return R(json.dumps({"data": [], "choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(ftc.urllib.request, "urlopen", faux)
    return vues


def test_catalogue_sans_double_models(monkeypatch):
    vues = _capturer(monkeypatch)
    ftc.catalogue("https://api.exemple.test/v1/models", "factice")
    ftc.catalogue("https://api.exemple.test/v1/models/", "factice")
    ftc.catalogue("https://api.exemple.test/v1", "factice")
    assert vues == ["https://api.exemple.test/v1/models"] * 3


def test_generation_sans_double_models(monkeypatch):
    vues = _capturer(monkeypatch)
    ftc._completer("https://api.exemple.test/v1/models", "factice", "m", False, max_tokens=8)
    assert vues == ["https://api.exemple.test/v1/chat/completions"]
