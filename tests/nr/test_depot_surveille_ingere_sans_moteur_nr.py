"""NR 2/11 -- le depot surveille (data/rag_files) n'ingerait RIEN hors de la TUI.

Mesure du 2/11 : SmoothE.pdf redepose par l'owner, NokidoIngestDaemon redemarre -- 15 min plus tard ni texte OCR, ni
refus journalise, ni fragment. `forge_auto_ingest_daemon.run_daemon` appelle `get_watcher()` SANS getter de moteur ;
`_scan` faisait alors `if rag_engine:` -> faux -> le fichier etait marque VU puis abandonne en silence. Et
`app_ctx().rag_engine` vaut None hors de la TUI ; `RAGEngine()` est interdit hors hub (charge toute la base).

Regle : sans moteur, le depot ingere par la voie CANONIQUE (MarkdownChunker -> ecrire_chunk, celle des veilles
rapides) ; un echec d'ingestion est DIT et le fichier n'est pas marque vu (il sera retente).
NR par le chemin REEL du demon : get_watcher() sans argument puis _scan().
"""
import types

import pytest

from nokido_agent.app import forge_hot_ingest as H

TEXTE = ("# Note owner\n\nModulo scheduling : ResMII, RecMII, iterative modulo scheduling de Rau. " * 8)


@pytest.fixture
def cadre(tmp_path, monkeypatch):
    depot = tmp_path / "rag_files"
    depot.mkdir()
    ecrits = []
    monkeypatch.setattr(H, "_RAG_DIR", depot)
    monkeypatch.setattr(H, "_watcher", None)
    monkeypatch.setattr(H, "_ecrire_fragments", lambda source, domain, frags: ecrits.append((source, frags)) or len(frags))
    monkeypatch.setattr(H, "_patch_source_meta", lambda *a, **k: 0)
    monkeypatch.setattr(H, "_enqueue_source_promotion", lambda *a, **k: None)
    monkeypatch.setattr(H, "_count_source_chunks", lambda *a, **k: 1)
    import nokido_agent.app.forge_app_context as AC
    monkeypatch.setattr(AC, "app_ctx", lambda: types.SimpleNamespace(rag_engine=None))
    return depot, ecrits


def test_le_demon_sans_moteur_ingere_par_la_voie_canonique(cadre):
    depot, ecrits = cadre
    w = H.get_watcher(rag_dir=depot)          # chemin reel du demon : aucun getter
    (depot / "note.md").write_text(TEXTE, encoding="utf-8")
    w._scan()
    assert ecrits, "fichier detecte mais rien ecrit : le puits muet est revenu"
    source, frags = ecrits[0]
    assert source == "note.md" and any("ResMII" in f for f in frags)
    assert "note.md" in w._seen


def test_un_echec_d_ingestion_est_dit_et_retente(cadre, monkeypatch):
    depot, _ = cadre
    journal = []

    def ko(*a, **k):
        raise OSError("base verrouillee")
    monkeypatch.setattr(H, "_ecrire_fragments", ko)
    w = H.HotFolderWatcher(rag_dir=depot, log_fn=journal.append)
    (depot / "note.md").write_text(TEXTE, encoding="utf-8")
    w._scan()
    assert "note.md" not in w._seen, "un echec ne doit pas marquer le fichier comme vu"
    assert any("note.md" in m and ("echec" in m.lower() or "non ingere" in m.lower()) for m in journal), journal


def test_hot_ingest_file_sans_moteur_utilise_l_ingereur_canonique(cadre):
    import asyncio

    depot, ecrits = cadre
    f = depot / "doc.md"
    f.write_text(TEXTE, encoding="utf-8")
    r = asyncio.run(H.hot_ingest_file(f, None, log_fn=lambda m: None))
    assert r["ok"], r
    assert ecrits and ecrits[0][0] == "doc.md"
