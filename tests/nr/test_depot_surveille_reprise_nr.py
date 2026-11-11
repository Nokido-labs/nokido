"""NR 2/11 (choix owner « activer + corriger la reprise ») -- un depot fait pendant un ARRET est ingere au redemarrage.

Avant : `_init_seen` marquait TOUS les fichiers presents comme vus au demarrage ; un fichier depose pendant que le
service etait arrete n'etait donc jamais ingere, en silence. Desormais une memoire persistante (nom -> taille) dit ce
qui a vraiment ete traite. Premier demarrage sans memoire : amorce (les presents sont reputes traites, comme avant),
pour ne pas reingerer tout l'historique du dossier.
"""
import json
import types

import pytest

from nokido_agent.app import forge_hot_ingest as H

TEXTE = "# Note\n\n" + "Iterative modulo scheduling, ResMII et RecMII. " * 20


@pytest.fixture
def cadre(tmp_path, monkeypatch):
    depot = tmp_path / "rag_files"
    depot.mkdir()
    ecrits = []
    monkeypatch.setattr(H, "_ecrire_fragments", lambda s, d, f: ecrits.append(s) or len(f))
    monkeypatch.setattr(H, "_patch_source_meta", lambda *a, **k: 0)
    monkeypatch.setattr(H, "_enqueue_source_promotion", lambda *a, **k: None)
    monkeypatch.setattr(H, "_count_source_chunks", lambda *a, **k: 1)
    import nokido_agent.app.forge_app_context as AC
    monkeypatch.setattr(AC, "app_ctx", lambda: types.SimpleNamespace(rag_engine=None))
    return depot, ecrits


def test_depot_pendant_l_arret_ingere_au_redemarrage(cadre):
    depot, ecrits = cadre
    (depot / "a.md").write_text(TEXTE, encoding="utf-8")
    w1 = H.HotFolderWatcher(rag_dir=depot, log_fn=lambda m: None)   # amorce : a.md repute traite
    (depot / "b.md").write_text(TEXTE + " b", encoding="utf-8")
    w1._scan()
    assert ecrits == ["b.md"]
    # arret du service ; c.md depose pendant l'arret
    (depot / "c.md").write_text(TEXTE + " c", encoding="utf-8")
    w2 = H.HotFolderWatcher(rag_dir=depot, log_fn=lambda m: None)
    w2._scan()
    assert ecrits == ["b.md", "c.md"], "le depot fait pendant l'arret doit etre ingere, et rien d'autre"


def test_amorce_sans_memoire_ne_reingere_pas_l_historique(cadre):
    depot, ecrits = cadre
    for n in ("x.md", "y.md"):
        (depot / n).write_text(TEXTE + n, encoding="utf-8")
    w = H.HotFolderWatcher(rag_dir=depot, log_fn=lambda m: None)
    w._scan()
    assert ecrits == []
    memo = json.loads(w._memo_path.read_text(encoding="utf-8"))
    assert set(memo) == {"x.md", "y.md"}


def test_la_memoire_ne_va_pas_dans_le_vrai_sandbox_pour_un_autre_dossier(cadre):
    depot, _ = cadre
    w = H.HotFolderWatcher(rag_dir=depot, log_fn=lambda m: None)
    assert str(w._memo_path).startswith(str(depot.parent))


def test_un_test_qui_remplace_RAG_DIR_n_ecrit_pas_la_vraie_memoire(cadre, monkeypatch):
    # PAYE le 2/11 : les NR remplacaient _RAG_DIR par un dossier temporaire ; le chemin de la memoire comparait a ce
    # _RAG_DIR remplace et ecrivait dans le VRAI sandbox/hot_folder_vus.json (noms de test dans la memoire du service).
    depot, _ = cadre
    monkeypatch.setattr(H, "_RAG_DIR", depot)
    w = H.HotFolderWatcher(rag_dir=depot, log_fn=lambda m: None)
    assert str(w._memo_path).startswith(str(depot.parent)), w._memo_path


def test_le_motif_ocr_nomme_le_module_manquant(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    wr = pypdf.PdfWriter()
    wr.add_blank_page(width=612, height=792)
    p = tmp_path / "scan.pdf"
    with open(p, "wb") as f:
        wr.write(f)

    def ko(path):
        raise ModuleNotFoundError("No module named 'cv2'")
    monkeypatch.setattr(H, "_ocr_pdf", ko)
    v = H.analyser_avant_ingestion(p)
    assert not v["ok"] and "cv2" in v["motif"], v
