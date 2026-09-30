"""NR -- une page arXiv /abs/ est re-sourcee en /html/ : la veille ingere l'article, pas son resume.

Fiche docs/veilles/fiche_v3_memoire_2026-09-23.md, section DECISION : « CORRIGER la veille : re-sourcer
les articles arXiv en /html/ ». Mesure 26/09 : les veilles RSI de la soif passent par le repli academique
(OpenAlex puis arXiv) ; `_fetch` recuperait l'URL telle quelle -- une page /abs/ ne porte que le resume.
Le repli sur /abs/ reste, et il est DIT (un /html/ absent n'est pas un article vide).
"""
from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_research_agent as ra  # noqa: E402

LONG = "<html><body>" + ("texte integral de l'article " * 200) + "</body></html>"


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _servir(monkeypatch, pages: dict):
    vues = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        vues.append(url)
        if url not in pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Rep(pages[url].encode())

    monkeypatch.setattr(ra.urllib.request, "urlopen", urlopen)
    return vues


def test_une_page_abs_est_lue_en_html(monkeypatch):
    vues = _servir(monkeypatch, {"https://arxiv.org/html/2505.22954v2": LONG,
                                 "https://arxiv.org/abs/2505.22954v2": "<p>resume seul</p>"})
    texte = ra._fetch("https://arxiv.org/abs/2505.22954v2")
    assert vues[0] == "https://arxiv.org/html/2505.22954v2"
    assert "texte integral" in texte


def test_sans_version_html_on_retombe_sur_abs(monkeypatch):
    vues = _servir(monkeypatch, {"https://arxiv.org/abs/2505.22954": "<p>resume seul</p>"})
    texte = ra._fetch("https://arxiv.org/abs/2505.22954")
    assert vues == ["https://arxiv.org/html/2505.22954", "https://arxiv.org/abs/2505.22954"]
    assert "resume seul" in texte


def test_le_css_en_ligne_n_entre_pas_dans_le_texte(monkeypatch):
    # Preuve chemin reel 26/09 : l'article DGM en /html/ (236 328 car.) commencait par
    # « /* Banner pre-dismissal ... */ html[data-banner-dismissed] ... » -- les <style> passaient.
    _servir(monkeypatch, {"https://example.org/p": "<style>html[data-x] .ds { display: none; }</style>"
                                                   "<p>" + ("vrai contenu " * 50) + "</p>"})
    texte = ra._fetch("https://example.org/p")
    assert "display: none" not in texte and "vrai contenu" in texte


def test_une_autre_url_passe_inchangee(monkeypatch):
    vues = _servir(monkeypatch, {"https://example.org/doc": LONG})
    ra._fetch("https://example.org/doc")
    assert vues == ["https://example.org/doc"]
