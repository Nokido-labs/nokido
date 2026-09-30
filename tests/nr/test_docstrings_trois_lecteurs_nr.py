"""NR — wiki, fiches RAG et introspect lisent les docstrings avec UNE regle, et correctement.

Mesure du 2026-09-29 (pilote docstrings) :
- 181 modules comptes « sans docstring » en avaient une vraie derriere l'en-tete machine
  `FORGE INTELLIGENCE [BLUE] / DATE: ... | VER: ...` ; le wiki les comptait non documentes,
  introspect affichait « DATE:... » en resume, les fiches RAG portaient « FORGE INTELLIGENCE » en DOC ;
- la fiche ne gardait que la 1re ligne de la docstring (top 10 : 20 % contre 32,5 % avec la docstring
  entiere) ;
- un resume automatique au sha perime etait ecarte en silence : 19 fiches sur 20 sans description.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_module_cards as MC  # noqa: E402
import forge_wiki_modules as W  # noqa: E402

DOC_ENTETE = ('"""\nFORGE INTELLIGENCE [BLUE]\nDATE:2026-06-02 | VER:v_x_1\n\n'
              "Chemin canonique de la base, resolu en realpath. Detail de la seconde phrase.\n\n"
              'Ligne plus loin : DATE: reste du contenu ici.\n"""\nfrom __future__ import annotations\n'
              "def f():\n    return 1\n")


def test_l_entete_machine_est_retire_et_le_texte_garde():
    doc = "FORGE INTELLIGENCE [BLUE]\nDATE:2026-06-02 | VER:v_x\n\nVrai texte.\nDATE: au milieu, garde."
    assert W.sans_entete_machine(doc) == "Vrai texte.\nDATE: au milieu, garde."
    assert W.sans_entete_machine("FORGE INTELLIGENCE [RED]\nDATE:2026-01-01") == ""


def test_le_wiki_et_la_definition_lisent_la_vraie_premiere_phrase():
    assert W.definition_du_module(DOC_ENTETE, "forge_x.py") == "Chemin canonique de la base, resolu en realpath"
    assert W.definition_du_module("x = 1\n", "forge_x.py") == ""


def test_la_fiche_porte_la_docstring_entiere_sans_entete(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    p = tmp_path / "app" / "forge_x.py"
    p.write_text(DOC_ENTETE, encoding="utf-8")
    monkeypatch.setattr(MC, "ROOT", tmp_path)
    monkeypatch.setattr(MC, "_SUMM", {})
    carte = MC.card_for(p)
    assert carte["doc"].startswith("Chemin canonique"), carte["doc"]
    assert "seconde phrase" in carte["doc"] and "FORGE INTELLIGENCE" not in carte["doc"]


def test_un_resume_perime_est_garde_et_marque(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    p = tmp_path / "app" / "forge_y.py"
    p.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(MC, "ROOT", tmp_path)
    monkeypatch.setattr(MC, "_SUMM", {"app/forge_y.py": {"sha": "0000", "summary": "Resume automatique."}})
    carte = MC.card_for(p)
    assert carte.get("summary") == "Resume automatique." and carte.get("summary_perimee") is True
    assert "DEF: [perimee] Resume automatique." in MC.card_text(carte)


def test_introspect_resume_par_la_meme_regle():
    import forge_introspect as I
    assert I._definition(DOC_ENTETE, "forge_x.py") == "Chemin canonique de la base, resolu en realpath"
    assert I._definition("from __future__ import annotations\nx = 1\n", "forge_z.py") == "(sans docstring)"
