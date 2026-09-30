# -*- coding: utf-8 -*-
"""NR — forge_docs_port_annotate : on teste l'EFFET, pas l'import.

Un document qui cite `:5557` sans dire qu'il est arrete depuis le 2026-06-03 envoie
son lecteur sur un service mort. L'outil annote ces pages sans reecrire leur corps.
Ces tests verrouillent les quatre proprietes dont depend cette garantie :

1. un port arrete cite SANS signal est detecte ;
2. le meme port cite AVEC son etat ne l'est pas (sinon l'outil crie a faux et se
   fait desarmer) ;
3. l'annotation est idempotente — relancer ne duplique pas l'encadre ;
4. le dry-run n'ECRIT rien, et le corps d'origine est preserve mot pour mot.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_docs_port_annotate import (  # noqa: E402
    MARQUEUR,
    PORTS_ARRETES,
    ports_muets,
    traiter,
)


def _page(tmp_path: Path, corps: str) -> Path:
    p = tmp_path / "page.md"
    p.write_text(corps, encoding="utf-8")
    return p


def test_port_arrete_cite_sans_signal_est_detecte():
    lignes = ["# Topologie", "", "L'embedder ecoute sur :5557 et repond en 1024D."]
    assert ports_muets(lignes) == ["5557"]


def test_port_arrete_cite_AVEC_son_etat_n_est_pas_signale():
    lignes = ["# Topologie", "",
              "brain_worker :5557 est DESACTIVE depuis le 2026-06-03 (OOM).",
              "L'embedder vivant est :8099."]
    assert ports_muets(lignes) == [], "un doc honnete ne doit pas etre annote"


def test_le_signal_compte_meme_a_quatre_lignes_de_distance():
    lignes = ["# T", "", "brain_worker :5557", "", "", "", "Ce service est arrete."]
    assert ports_muets(lignes) == []


def test_un_port_vivant_n_est_jamais_annote():
    assert "8766" not in PORTS_ARRETES
    assert ports_muets(["# T", "", "Le hub ecoute sur :8766."]) == []


def test_annotation_inseree_apres_le_titre_et_corps_preserve(tmp_path):
    corps = "# Inventaire\n\nLe worker ecoute sur :5557.\n"
    p = _page(tmp_path, corps)
    etat, muets = traiter(p, apply=True)
    assert etat == "annote" and muets == ["5557"]
    lignes = p.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "# Inventaire", "le titre H1 doit rester en premiere ligne"
    assert MARQUEUR in lignes[:6], "l'encadre doit suivre immediatement le titre"
    assert "Le worker ecoute sur :5557." in p.read_text(encoding="utf-8"), (
        "le corps d'origine ne doit pas etre reecrit"
    )
    assert "2026-06-03" in p.read_text(encoding="utf-8"), "la date d'arret doit etre donnee"


def test_annotation_idempotente(tmp_path):
    p = _page(tmp_path, "# I\n\n:5557\n")
    assert traiter(p, apply=True)[0] == "annote"
    avant = p.read_text(encoding="utf-8")
    assert traiter(p, apply=True)[0] == "deja", "une seconde passe ne doit rien refaire"
    assert p.read_text(encoding="utf-8") == avant, "le fichier ne doit pas bouger"


def test_dry_run_n_ecrit_rien(tmp_path):
    corps = "# I\n\n:5557\n"
    p = _page(tmp_path, corps)
    etat, muets = traiter(p, apply=False)
    assert etat == "annote" and muets == ["5557"]
    assert p.read_text(encoding="utf-8") == corps, "le dry-run a ecrit dans le fichier"


def test_sans_titre_h1_l_encadre_va_en_tete(tmp_path):
    p = _page(tmp_path, "Note libre.\n\n:8100 sert au rerank.\n")
    assert traiter(p, apply=True)[0] == "annote"
    assert MARQUEUR in p.read_text(encoding="utf-8").splitlines()[:4]
