"""NR — Veille des changelogs par flux natifs (releases.atom GitHub & JSON PyPI).

Demande owner 2026-10-17 : « a chaque mise a jour de claude je veux que tu check s'il y a du nouveau »
(dette bb:veille_composants_morte_et_changelogs_non_absorbes_20261017, tri bb:tri_collage_gemini_argon_veille_20261017).
SearXNG est aveugle (moteurs HTML bloques) : les changelogs doivent venir des flux faits pour les machines.

Ce test prouve :
1. Extraction depuis flux Atom et JSON PyPI fabriques.
2. Nouvelle version detectee et ingeree via _step_ingest / _step_store.
3. Version deja vue ignoree (deduplication par composant, version).
4. Flux illisible se DIT (composant + raison), jamais un faux « rien de neuf ».
5. Aucun appel reseau reel (flux 100 % locaux et fabriques).
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

import forge_cli_version_watch as W  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _tableau_noir_reel_interdit(monkeypatch):
    """Aucun test de ce module n'ecrit au VRAI tableau noir.

    Mesure 2026-10-17 15:58:53 : test_aucun_appel_reseau_reel (flux fabrique pour TOUTES les sources) passait par
    publier_fait_nouvelle_version -> apply_fact_sync de production : des faits « Composant ollama/deno/qdrant/lean4 :
    nouvelle version v1.19.4 (releases de opencode) » publies dans discovered_facts a chaque passage des NR.
    La publication avale ses exceptions (elle rend {'error': ...}) : un garde qui leverait serait muet, d'ou le RELEVE
    verifie en fin de test.
    """
    import nokido_agent.app.forge_swarm_blackboard as BB

    fuites = []
    monkeypatch.setattr(BB, "apply_fact_sync", lambda *a, **k: fuites.append(a[:2]) or {"ok": True, "fuite": True})
    yield
    assert not fuites, "publication au VRAI tableau noir depuis un test : %r" % (fuites[:3],)


ATOM_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en-US">
  <title>Release notes from opencode</title>
  <updated>2026-10-17T12:00:00Z</updated>
  <entry>
    <id>tag:github.com,2008:Repository/12345/v1.19.4</id>
    <updated>2026-10-17T12:00:00Z</updated>
    <link rel="alternate" type="text/html" href="https://github.com/anomalyco/opencode/releases/tag/v1.19.4"/>
    <title>v1.19.4</title>
    <content type="html">&lt;p&gt;Correctif multi-instances ACP et support des permissions fines.&lt;/p&gt;&lt;p&gt;Notes de version detaillees pour opencode version 1.19.4 avec nouvelles options de configuration.&lt;/p&gt;</content>
    <author><name>OpenCode Team</name></author>
  </entry>
</feed>
"""

PYPI_SAMPLE = json.dumps({
    "info": {
        "name": "crawl4ai",
        "version": "1.2.3",
        "summary": "Asynchronous Web Crawler & Scraper for LLMs with fit_markdown extraction",
        "description": "Crawl4AI version 1.2.3 release notes: introduction du filtrage fit_markdown avec reduction drastique des tokens de navigation et support natif de Playwright.",
        "release_url": "https://pypi.org/project/crawl4ai/1.2.3/",
        "project_url": "https://github.com/unclecode/crawl4ai",
    },
    "releases": {
        "1.2.3": []
    }
}).encode("utf-8")


def _fake_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS watch_jobs (
        id           TEXT PRIMARY KEY,
        theme        TEXT NOT NULL,
        idea_id      TEXT NOT NULL DEFAULT 'veille_active',
        step         TEXT NOT NULL DEFAULT 'keywords',
        status       TEXT NOT NULL DEFAULT 'pending',
        n_ingested   INTEGER DEFAULT 0,
        n_stored     INTEGER DEFAULT 0,
        updated_at   TEXT
    );
    CREATE TABLE IF NOT EXISTS rag_chunks (
        id          TEXT PRIMARY KEY,
        text        TEXT NOT NULL,
        source      TEXT NOT NULL,
        domain      TEXT DEFAULT 'general',
        role_hint   TEXT DEFAULT 'chat',
        author      TEXT DEFAULT '',
        ingested_at TEXT,
        created_at  TEXT,
        embedding   BLOB,
        sequence_id INTEGER,
        meta        TEXT DEFAULT '{}',
        hash        TEXT,
        canonical_id TEXT,
        embedding_model TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED);
    """)
    return conn


def test_extraire_notes_atom_fabrique():
    ver, url, notes = W.extraire_notes_atom(ATOM_SAMPLE)
    assert ver == "v1.19.4"
    assert url == "https://github.com/anomalyco/opencode/releases/tag/v1.19.4"
    assert "ACP" in notes


def test_extraire_notes_pypi_fabrique():
    ver, url, notes = W.extraire_notes_pypi(PYPI_SAMPLE)
    assert ver == "1.2.3"
    assert url == "https://pypi.org/project/crawl4ai/1.2.3/"
    assert "fit_markdown" in notes


def test_nouvelle_version_detectee_et_ingeree():
    """Prouve qu'une nouvelle version est détectée, ingérée dans la base et publiée."""
    conn = _fake_db()

    def _mock_urlopen(url):
        return io.BytesIO(ATOM_SAMPLE)

    publies = []

    def _enregistreur(cle, version, url):
        publies.append((cle, version, url))
        return {"ok": True}

    src_cfg = {
        "url": "https://github.com/anomalyco/opencode/releases.atom",
        "type": "atom",
        "domain": "opencode_docs",
    }

    res = W.traiter_flux_natif("opencode", src_cfg, etat_composant_precedent={}, conn=conn,
                               urlopen_fn=_mock_urlopen, publier_fn=_enregistreur)

    assert res["ok"] is True
    assert res["nouveau"] is True
    assert res["deja_vu"] is False
    assert res["version"] == "v1.19.4"
    assert "v1.19.4" in res["versions_vues"]
    assert res.get("ingere") and res["ingere"]["ok"] is True
    assert res["ingere"]["n_ingested"] >= 1

    # Vérification de la publication (couture injectee, pas le vrai tableau noir)
    assert publies == [("opencode", "v1.19.4", "https://github.com/anomalyco/opencode/releases/tag/v1.19.4")]

    # Vérification réelle dans rag_chunks
    rows = conn.execute("SELECT id, text, source, domain FROM rag_chunks WHERE role_hint LIKE '%opencode%'").fetchall()
    assert len(rows) >= 1
    assert "opencode" in rows[0][1].lower()


def test_version_deja_vue_ignoree():
    """Prouve qu'une version déjà enregistrée est ignorée sans ré-ingestion."""
    conn = _fake_db()

    def _mock_urlopen(url):
        return io.BytesIO(ATOM_SAMPLE)

    src_cfg = {
        "url": "https://github.com/anomalyco/opencode/releases.atom",
        "type": "atom",
        "domain": "opencode_docs",
    }

    etat_precedent = {
        "derniere_version": "v1.19.4",
        "versions_vues": ["v1.19.4"],
    }

    res = W.traiter_flux_natif("opencode", src_cfg, etat_composant_precedent=etat_precedent, conn=conn, urlopen_fn=_mock_urlopen)

    assert res["ok"] is True
    assert res["nouveau"] is False
    assert res["deja_vu"] is True
    assert res["version"] == "v1.19.4"
    assert res.get("ingere") is None

    # Aucune écriture dans la base
    count = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    assert count == 0


def test_flux_illisible_se_dit_jamais_rien_de_neuf():
    """Un flux en erreur doit être explicité (composant + raison), jamais tu sous silence."""
    def _mock_urlopen_ko(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    src_cfg = {
        "url": "https://github.com/inexistant/repo/releases.atom",
        "type": "atom",
        "domain": "test_docs",
    }

    res = W.traiter_flux_natif("inexistant", src_cfg, etat_composant_precedent={}, urlopen_fn=_mock_urlopen_ko)

    assert res["ok"] is False
    assert res["illisible"] is True
    assert "inexistant" in res["erreur"]
    assert "HTTPError" in res["erreur"] or "404" in res["erreur"]

    # Test avec XML corrompu
    def _mock_urlopen_corrompu(url):
        return io.BytesIO(b"<non_ferme")

    res_corrupt = W.traiter_flux_natif("corrompu", src_cfg, etat_composant_precedent={}, urlopen_fn=_mock_urlopen_corrompu)
    assert res_corrupt["ok"] is False
    assert res_corrupt["illisible"] is True
    assert "corrompu" in res_corrupt["erreur"]


def test_composants_suivis_couverture_flux_natifs():
    """Prouve que la liste des composants suivis (Claude Code, Codex, Vibe, OpenCode, crawl4ai, mcp, lean4...) est couverte."""
    attendus = ["claude_code", "openai", "mistral_vibe", "opencode", "crawl4ai", "mcp", "lean4"]
    for c in attendus:
        assert c in W.SOURCES_NATIVES, f"Composant manquant dans SOURCES_NATIVES: {c}"
        cfg = W.SOURCES_NATIVES[c]
        assert "url" in cfg and cfg["url"].startswith("https://")
        if cfg["type"] == "atom":
            assert cfg["url"].endswith("releases.atom")
        elif cfg["type"] == "pypi":
            assert cfg["url"].endswith("json") and "/pypi/" in cfg["url"]


def test_aucun_appel_reseau_reel(monkeypatch):
    """Prouve que le traitement complet fonctionne sans aucun appel réseau réel."""
    def _fail_network(*args, **kwargs):
        raise AssertionError("Appel reseau non autorise en test !")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_network)

    def _bouchon(url):
        if "releases.atom" in url:
            return io.BytesIO(ATOM_SAMPLE)
        return io.BytesIO(PYPI_SAMPLE)

    conn = _fake_db()
    publies = []

    def _enregistreur(cle, version, url):
        publies.append((cle, version, url))
        return {"ok": True}

    res, chang = W.traiter_toutes_sources_natives(avant={}, conn=conn, urlopen_fn=_bouchon,
                                                  publier_fn=_enregistreur)
    assert len(res) >= len(W.SOURCES_NATIVES)
    assert all(r["ok"] for r in res.values())
    assert any("opencode" in c for c in chang)

    # Chaque source en nouvelle version publie via la couture injectee (une publication par composant)
    assert sorted(c for c, _v, _u in publies) == sorted(W.SOURCES_NATIVES)


def test_la_publication_passe_par_la_couture_injectee():
    """La publication d'une nouvelle version est une COUTURE injectable (publier_fn), comme la lecture (urlopen_fn) et
    l'ingestion (conn) : sans elle, un test ne peut eprouver le chemin non dry_run qu'en ecrivant au vrai tableau noir."""
    publies = []

    def _bouchon(url):
        if "releases.atom" in url:
            return io.BytesIO(ATOM_SAMPLE)
        return io.BytesIO(PYPI_SAMPLE)

    res, _chang = W.traiter_toutes_sources_natives(
        avant={}, conn=_fake_db(), urlopen_fn=_bouchon,
        publier_fn=lambda cle, version, url: publies.append((cle, version, url)) or {"ok": True})
    assert all(r["ok"] for r in res.values())
    assert sorted(c for c, _v, _u in publies) == sorted(W.SOURCES_NATIVES)

    r1 = W.traiter_flux_natif(
        "opencode", {"url": "https://github.com/anomalyco/opencode/releases.atom", "type": "atom"},
        etat_composant_precedent={}, conn=_fake_db(), urlopen_fn=_bouchon,
        publier_fn=lambda *a: publies.append(a) or {"ok": True})
    assert r1["nouveau"] is True
    assert publies[-1][0] == "opencode"
