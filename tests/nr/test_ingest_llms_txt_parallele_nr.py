# -*- coding: utf-8 -*-
"""NR -- l'ingesteur llms.txt telecharge a plusieurs et ecrit SEUL, dans l'ordre (2026-10-01).

Mesure : 1,0 a 1,46 page/s sur les ingestions du jour, 14 chunks/s pour tailscale -- la
boucle attendait le reseau page apres page. Les GET partent en parallele ; l'ecrivain reste
unique (SQLite n'en admet qu'un) et valide DANS L'ORDRE de l'index ; le rendu HTML (un
navigateur) reste a un a la fois ; une relance ne re-ecrit rien (reprise sans perte ni doublon).
"""
import importlib.util
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


AIDE = _charger("aide_ingest_nr", ROOT / "tests" / "nr" / "test_ingest_llms_txt_version_courante_nr.py")
PAGES = [("p%d" % i, "https://doc.example/p%d.md" % i) for i in range(6)]
CORPS = {u: ("# Page %d\n\n" % i) + ("Contenu propre a la page numero %d du site. " % i) * 25
         for i, (_t, u) in enumerate(PAGES)}


def _servir(monkeypatch, m, echec=None):
    def urlopen(req, timeout=None):
        url = req.full_url
        if url == echec:
            raise OSError("reseau coupe")
        time.sleep(0.05 * (6 - int(url[-4])))  # les PREMIERES pages arrivent en DERNIER
        return AIDE._Reponse(CORPS[url].encode())
    monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)


def _ordre(base):
    return [s for (s,) in base.c.execute(
        "SELECT source FROM rag_chunks GROUP BY source ORDER BY MIN(rowid)")]


def test_paralleles_ecrit_dans_l_ordre_et_rend_le_meme_resultat(monkeypatch):
    m = AIDE._module()
    seq, par = AIDE._Base(), AIDE._Base()
    _servir(monkeypatch, m)
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: seq)
    r1 = m.ingerer(PAGES, "doc_nr", pause=0, timeout=5, paralleles=1)
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: par)
    r4 = m.ingerer(PAGES, "doc_nr", pause=0, timeout=5, paralleles=4)
    attendu = ["doc_nr:doc.example/p%d.md" % i for i in range(6)]
    assert _ordre(seq) == attendu and _ordre(par) == attendu
    assert r4["chunks_inseres"] == r1["chunks_inseres"] > 0 and r4["pages_ok"] == 6
    for cle in ("duree_s", "attente_reseau_s", "traitement_local_s", "paralleles"):
        assert cle in r4, cle
    assert r4["paralleles"] == 4


def test_une_relance_ne_reecrit_rien(monkeypatch):
    m = AIDE._module()
    base = AIDE._Base()
    _servir(monkeypatch, m)
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    m.ingerer(PAGES, "doc_nr", pause=0, timeout=5, paralleles=3)
    r = m.ingerer(PAGES, "doc_nr", pause=0, timeout=5, paralleles=3)
    assert r["pages_ok"] == 6 and r["chunks_inseres"] == 0 and r["anciens_retires"] == 0


def test_une_page_en_echec_n_arrete_pas_les_autres(monkeypatch):
    m = AIDE._module()
    base = AIDE._Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    # .md en echec -> repli sur le rendu HTML, lui aussi en echec ici
    monkeypatch.setattr(m, "crawl_url", lambda url, timeout=0: "")
    _servir(monkeypatch, m, echec=PAGES[2][1])
    r = m.ingerer(PAGES, "doc_nr", pause=0, timeout=5, paralleles=4)
    assert r["pages_ok"] == 5 and r["pages_ko"] == 1


def test_le_rendu_html_reste_a_un_a_la_fois(monkeypatch):
    m = AIDE._module()
    base = AIDE._Base()
    monkeypatch.setattr(m, "open_writer", lambda timeout=60.0: base)
    actifs, pic, verrou = [0], [0], threading.Lock()

    def crawl(url, timeout=0):
        with verrou:
            actifs[0] += 1
            pic[0] = max(pic[0], actifs[0])
        time.sleep(0.05)
        with verrou:
            actifs[0] -= 1
        return "# Rendu\n\n" + ("Texte rendu depuis le HTML de %s. " % url) * 20
    monkeypatch.setattr(m, "crawl_url", crawl)
    html = [("h%d" % i, "https://doc.example/h%d" % i) for i in range(5)]
    r = m.ingerer(html, "doc_nr", pause=0, timeout=5, paralleles=4)
    assert r["pages_ok"] == 5 and pic[0] == 1, "rendus HTML simultanes : %d" % pic[0]
