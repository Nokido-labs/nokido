"""NR -- la categorie `general` de SearXNG porte des moteurs a API (decision owner 18/10 : « moteurs a API »).

Mesure du 18/10 (job_b454cffe65cb) : `general` = 0 resultat (brave « too many requests », duckduckgo/startpage
CAPTCHA, karmasearch access denied ; connu depuis le 27/09) alors que `it` (github, docker hub, mdn : 50 resultats) et
`science` (arxiv, google scholar, semantic scholar : 30) repondent. Nokido a 7 clients SearXNG distincts qui
n'interrogent que `general` : le seul point unique est la configuration, ecrite par le keeper. On n'y contourne aucun
CAPTCHA : on ajoute des moteurs a API officielle a la categorie generale.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import forge_searxng_keeper as k  # noqa: E402

BASE = ('use_default_settings: true\nserver:\n  secret_key: "%s"\n  limiter: false\nsearch:\n  formats:\n'
        "    - json\n" % ("b" * 64))


def test_les_moteurs_a_api_entrent_dans_general_sans_toucher_au_reste(tmp_path, monkeypatch):
    f = tmp_path / "settings.yml"
    f.write_text(BASE, encoding="utf-8")
    monkeypatch.setattr(k, "SETTINGS_FILE", f)
    assert k.ensure_engines_api()["ok"] is True
    txt = f.read_text(encoding="utf-8")
    assert txt.startswith(BASE), "le contenu existant (cle comprise) reste intact"
    for nom in ("github", "arxiv", "semantic scholar"):
        assert "name: %s" % nom in txt
    assert txt.count("general") >= 3


def test_idempotent(tmp_path, monkeypatch):
    f = tmp_path / "settings.yml"
    f.write_text(BASE, encoding="utf-8")
    monkeypatch.setattr(k, "SETTINGS_FILE", f)
    k.ensure_engines_api()
    une = f.read_text(encoding="utf-8")
    assert k.ensure_engines_api()["ok"] is True
    assert f.read_text(encoding="utf-8") == une
