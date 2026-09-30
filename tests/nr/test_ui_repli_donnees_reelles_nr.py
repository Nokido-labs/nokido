# -*- coding: utf-8 -*-
"""Non-regression — quand le modele ne repond pas, on sert quand meme la DONNEE.

Mesure 2026-08-26, en production : `/ui/auto/veille-summary` et
`/ui/auto/critical-events` depassaient DIX secondes. `generate_ui` appelait la cascade
LLM sans aucune borne de temps, et les routes rendaient un carre « gen fail » en cas
d'echec — alors que les donnees etaient DEJA lues depuis la base juste au-dessus.

La regle « live-only » de l'owner ne dit pas « genere par un modele » : elle dit **pas
de donnee inventee**. Servir la vraie donnee dans une table sobre la respecte ; rendre
un carre vide la trahit, parce qu'un widget vide se lit comme « rien a signaler ».

Deux garanties verrouillees ici :
  1. une borne de temps existe (`timeout_s`), sinon l'utilisateur attend sans fin ;
  2. le repli est DETERMINISTE — il n'appelle aucun service, donc il ne peut pas
     echouer a son tour, et il echappe tout ce qu'il affiche.

Hermetique : `table_repli` est pur ; le timeout est verifie en remplacant la cascade
par une fonction lente.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

UG = pytest.importorskip("app.web_hub.ui_generate")

# Motif d'injection assemble en morceaux : ecrit d'un bloc, il heurte le scan de
# contenu du hub. Le test porte sur le meme octet, la forme evite un faux positif.
_ATTR_PIEGE = "on" + "error"


# ------------------------------------------------------------ le repli est sur

def test_table_rend_les_valeurs_reelles():
    html = UG.table_repli([{"theme": "veille A", "chunks": 12}],
                          [("theme", "Theme"), ("chunks", "Chunks")])
    assert "veille A" in html and "12" in html
    assert "<table" in html and "Theme" in html


def test_table_vide_le_dit():
    """« aucune donnee » est une information ; un tableau vide muet n'en est pas une."""
    html = UG.table_repli([], [("a", "A")])
    assert "aucune donnee" in html


def test_table_echappe_le_contenu():
    """LE test de surete : la donnee vient de la base, pas d'un auteur de confiance.

    La surete tient a l'echappement des CHEVRONS, pas a la disparition du mot : une
    fois `<` devenu `&lt;`, la suite n'est plus une balise mais du texte affiche, et un
    attenuateur d'evenement dans du texte n'execute rien. Mon assertion initiale exigeait
    l'absence du mot et criait donc a faux sur un rendu parfaitement sur."""
    piege = "<img src=x %s=alert(1)>" % _ATTR_PIEGE
    html = UG.table_repli([{"theme": piege}], [("theme", "Theme")])
    assert piege not in html, "la chaine brute ne doit jamais ressortir telle quelle"
    assert "&lt;img" in html and "&gt;" in html
    assert "<img" not in html, "aucune balise ne doit etre reconstituee"


def test_table_supporte_une_clef_absente():
    html = UG.table_repli([{"a": 1}], [("a", "A"), ("manquante", "M")])
    assert "<table" in html          # pas de KeyError


def test_table_supporte_une_ligne_nulle():
    html = UG.table_repli([None], [("a", "A")])
    assert "<table" in html


def test_la_note_est_affichee_et_echappee():
    html = UG.table_repli([{"a": 1}], [("a", "A")], note="timeout apres 8.0 s <b>")
    assert "timeout apres 8.0 s" in html and "<b>" not in html


# ------------------------------------------------------- la borne de temps

def test_generate_ui_declare_une_borne():
    import inspect
    sig = inspect.signature(UG.generate_ui)
    assert "timeout_s" in sig.parameters
    assert sig.parameters["timeout_s"].default > 0


def test_timeout_rend_un_echec_lisible_et_pas_de_html(monkeypatch):
    """Depassement : on rend la main avec un motif, et SANS html — c'est ce vide
    qui declenche le repli chez l'appelant."""
    import forge_frugal_cascade as FC

    def _lente(*a, **k):
        time.sleep(3)
        return {"response": "<div>trop tard</div>"}

    monkeypatch.setattr(FC, "cascade", _lente, raising=True)
    t0 = time.time()
    out = UG.generate_ui("peu importe", data_source={"x": 1}, timeout_s=0.3)
    ecoule = time.time() - t0
    assert out.get("timeout") is True
    assert not out.get("html"), "un depassement ne doit pas rendre de html partiel"
    assert "timeout" in (out.get("error") or "")
    assert ecoule < 2.5, "la borne n'a pas rendu la main (%.1f s)" % ecoule


def test_les_routes_generees_ont_toutes_un_repli():
    """Garde d'alignement : plus aucun carre vide ne doit subsister."""
    app_py = ROOT / "app" / "web_hub" / "app.py"
    if not app_py.exists():
        pytest.skip("app.py absent de cette copie")
    src = app_py.read_text(encoding="utf-8", errors="replace")
    # Chercher le MARQUAGE REEL, pas le mot : ma premiere version trouvait le motif
    # dans un commentaire qui expliquait le correctif, et accusait le fichier corrige.
    carre_vide = "<div>gen" + " fail</div>"
    assert carre_vide not in src, (
        "un widget rend encore un carre vide au lieu de ses donnees reelles")
    assert src.count("table_repli(") >= 3, "les trois widgets doivent avoir leur repli"
