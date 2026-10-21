"""NR 18/10 -- veille PyPI : texte enrichi de METADONNEES REELLES (P2_veille_pypi_resume_trop_court_20261018).

Rejeu C06 : 4 releases PyPI rejetees par l'ingestion (process_document : MIN_CHUNK_CHARS = 80) -- le texte
« paquet version: resume » d'une ligne est trop court. Contrat : le texte ajoute les metadonnees que l'API PyPI
fournit (Python requis, date de publication, liens du projet : changelog, sources) -- aucun rembourrage invente ;
sans metadonnees, seule la premiere ligne (l'ingestion refusera, et c'est juste). Meme texte pour la veille normale
(fetch_pypi_release) et pour le rejeu.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_rss_watcher as rw  # noqa: E402

INFO = {"summary": "The lightning-fast ASGI server.", "requires_python": ">=3.9",
        "project_urls": {"Changelog": "https://www.uvicorn.org/release-notes",
                         "Source": "https://github.com/encode/uvicorn"}}


def test_texte_enrichi_de_metadonnees_reelles():
    t = rw._texte_pypi("uvicorn", "0.53.0", INFO, "2026-09-01T10:00:00Z")
    assert t.splitlines()[0] == "uvicorn 0.53.0: The lightning-fast ASGI server."
    for attendu in (">=3.9", "2026-09-01", "https://www.uvicorn.org/release-notes", "https://github.com/encode/uvicorn"):
        assert attendu in t
    assert len(t) >= 80


def test_sans_metadonnees_rien_n_est_invente():
    assert rw._texte_pypi("x", "1.0", {"summary": "court"}, "") == "x 1.0: court"


def test_la_veille_normale_porte_le_texte(monkeypatch):
    corps = {"info": dict(INFO, version="0.53.0"),
             "releases": {"0.53.0": [{"upload_time_iso_8601": "2099-01-01T00:00:00Z"}]}}
    monkeypatch.setattr(rw, "_get", lambda url, **k: json.dumps(corps))
    monkeypatch.setattr(rw, "SINCE_DAYS", 10 ** 6)
    rel = rw.fetch_pypi_release("uvicorn")
    assert rel and rel["texte"].startswith("uvicorn 0.53.0: ") and "github.com/encode/uvicorn" in rel["texte"]


def test_le_rejeu_ingere_le_texte_enrichi(monkeypatch):
    vus = []
    monkeypatch.setattr(rw, "_load_state", lambda: {"seen": []})
    monkeypatch.setattr(rw, "_save_state", lambda s: None)
    monkeypatch.setattr(rw, "_mark_seen", lambda s, uid: None)
    monkeypatch.setattr(rw, "_deja_en_base", lambda *a, **k: False)
    monkeypatch.setattr(rw, "_release_pypi_version",
                        lambda pkg, ver: {"texte": "TEXTE ENRICHI " * 10, "url": "https://pypi.org/project/x/1/"})
    monkeypatch.setattr(rw, "_ingest", lambda **k: vus.append(k["text"]) or (rw.INSERE, 1, "ok"))
    rw.rejouer(["pypi:x:1"], dry_run=False)
    assert vus == ["TEXTE ENRICHI " * 10]
