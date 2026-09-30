# -*- coding: utf-8 -*-
"""NR - tools/forge_organ_declare (2026-09-06).

Contrats :
  1. une declaration hors du lexique des organes est REFUSEE (le census ne la
     lirait pas : c'est le cas mesure de 'ssot/gate-consumer') ;
  2. l'insertion suit `from __future__` quand il existe, sinon le docstring, sinon
     les commentaires de tete — et le fichier reste parsable ;
  3. dry-run n'ecrit rien ; un module deja declare n'est pas touche ;
  4. une MENTION de la marque (regex ou comparaison dans un lecteur de
     declarations, cas mesure de forge_wiki_modules) n'est pas une declaration :
     on insere, on ne plante pas (AttributeError du 2026-09-06, lot 2b entier
     tombe sur un seul module) ;
  5. l'ecrivain lit la MEME fenetre et la MEME regex que le lecteur (census) : une
     mention en commentaire n'est jamais « reformulee » (l'outil a clobbere son propre
     commentaire le 2026-09-06), et une declaration qui tomberait hors de la fenetre
     lue (docstring tres longue) est REFUSEE en le disant, jamais ecrite invisible.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

od = pytest.importorskip("forge_organ_declare")


def _module(tmp_path, nom, texte):
    p = tmp_path / nom
    p.write_text(texte, encoding="utf-8")
    return p


def _rel(p: Path) -> str:
    # declarer() prend un chemin relatif a ROOT : on passe par un chemin absolu
    # via un ROOT redirige dans les tests.
    return str(p)


@pytest.fixture
def root_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "ROOT", tmp_path)
    return tmp_path


def test_une_declaration_hors_lexique_est_refusee(root_tmp):
    _module(root_tmp, "forge_x.py", '"""doc"""\nimport os\n')
    r = od.declarer("forge_x.py", "ssot/gate-consumer", appliquer=False)
    assert r["etat"] == "REFUSE_HORS_LEXIQUE", r


def test_une_declaration_du_lexique_est_reconnue_et_placee_apres_future(root_tmp):
    p = _module(root_tmp, "forge_y.py", '"""doc"""\nfrom __future__ import annotations\n\nimport os\n')
    r = od.declarer("forge_y.py", "immunitaire/guard du journal", appliquer=True, jour="2026-09-06")
    assert r["etat"] == "ECRIT" and "Immunitaire" in r["organe"], r
    src = p.read_text(encoding="utf-8")
    ast.parse(src)
    lignes = src.splitlines()
    i_fut = next(i for i, l in enumerate(lignes) if l.startswith("from __future__"))
    i_dec = next(i for i, l in enumerate(lignes) if l.startswith("__FORGE_COLOR__"))
    assert i_dec > i_fut, "la declaration doit suivre from __future__ (premiere instruction)"


def test_sans_future_la_declaration_suit_le_docstring(root_tmp):
    p = _module(root_tmp, "forge_z.py", '#!/usr/bin/env python\n"""doc\nsur deux lignes\n"""\nimport os\n')
    r = od.declarer("forge_z.py", "memoire/memory des lecons", appliquer=True, jour="2026-09-06")
    assert r["etat"] == "ECRIT", r
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert isinstance(tree.body[0], ast.Expr), "le docstring reste la premiere expression"
    assert isinstance(tree.body[1], ast.Assign) and tree.body[1].targets[0].id == "__FORGE_COLOR__"


def test_reformuler_remplace_une_declaration_illisible_en_gardant_sa_forme(root_tmp):
    p = _module(root_tmp, "forge_v.py", '"""FORGE INTELLIGENCE v3 [GREEN]"""\n__FORGE_COLOR__ = "GREEN"\nimport os\n')
    r0 = od.declarer("forge_v.py", "memoire/rag : scanner", appliquer=False)
    assert r0["etat"] == "DEJA_DECLARE_ILLISIBLE" and r0["existante"] == '"GREEN"', "sans --reformuler, l'illisible est DITE"
    r = od.declarer("forge_v.py", "memoire/rag : scanner", appliquer=True, reformuler=True)
    assert r["etat"] == "REFORMULE", r
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assign = next(n for n in tree.body if isinstance(n, ast.Assign))
    assert assign.value.value == "memoire/rag : scanner", "la forme citee est conservee, la valeur remplacee"
    assert od.organe_reconnu(assign.value.value) is not None


def test_reformuler_ne_touche_pas_une_declaration_lisible(root_tmp):
    p = _module(root_tmp, "forge_u.py", '"""doc"""\n__FORGE_COLOR__ = "immunitaire/guard"\nimport os\n')
    avant = p.read_text(encoding="utf-8")
    r = od.declarer("forge_u.py", "memoire/rag : autre", appliquer=True, reformuler=True)
    assert r["etat"] == "DEJA_DECLARE" and p.read_text(encoding="utf-8") == avant


def test_une_mention_de_la_marque_n_est_pas_une_declaration(root_tmp):
    p = _module(root_tmp, "forge_lecteur.py",
                '"""lit les declarations"""\nimport ast\n'
                'def organe(c):\n    return c.id == "__FORGE_COLOR__"\n')
    r = od.declarer("forge_lecteur.py", "observabilite/anatomy : lecteur", appliquer=True,
                    jour="2026-09-06", reformuler=True)
    assert r["etat"] == "ECRIT", r
    tree = ast.parse(p.read_text(encoding="utf-8"))
    assigns = [n for n in tree.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "__FORGE_COLOR__"]
    assert len(assigns) == 1, "une seule declaration, inseree malgre la mention"


def test_reformuler_vise_la_declaration_ancree_jamais_une_mention(root_tmp):
    p = _module(root_tmp, "forge_t.py",
                '"""doc"""\n# ancien en-tete : __FORGE_COLOR__ = "GREEN", a reformuler\nimport os\n')
    r = od.declarer("forge_t.py", "memoire/rag : t", appliquer=True, jour="2026-09-06", reformuler=True)
    assert r["etat"] == "ECRIT", r
    src = p.read_text(encoding="utf-8")
    assert '# ancien en-tete : __FORGE_COLOR__ = "GREEN", a reformuler' in src, "le commentaire reste intact"
    assert src.count("__FORGE_COLOR__") == 2, "une declaration inseree, la mention laissee"


def test_une_declaration_hors_de_la_fenetre_du_census_est_refusee(root_tmp):
    long_doc = '"""' + ("x" * 90 + "\n") * 140 + '"""\n'      # ~12 700 chars > HEAD_CHARS
    p = _module(root_tmp, "forge_long.py", long_doc + "import os\n")
    avant = p.read_text(encoding="utf-8")
    r = od.declarer("forge_long.py", "memoire/rag : long", appliquer=True, jour="2026-09-06")
    assert r["etat"] == "HORS_TETE", r
    assert p.read_text(encoding="utf-8") == avant, "rien n'est ecrit quand le census ne le lirait pas"


def test_dry_run_n_ecrit_rien_et_deja_declare_est_respecte(root_tmp):
    p = _module(root_tmp, "forge_w.py", '"""doc"""\nimport os\n')
    avant = p.read_text(encoding="utf-8")
    r = od.declarer("forge_w.py", "vegetatif/heartbeat", appliquer=False)
    assert r["etat"] == "DRY_RUN" and p.read_text(encoding="utf-8") == avant
    p.write_text('"""doc"""\n__FORGE_COLOR__ = "vegetatif/heartbeat"\nimport os\n', encoding="utf-8")
    assert od.declarer("forge_w.py", "cognition/agent", appliquer=True)["etat"] == "DEJA_DECLARE"
