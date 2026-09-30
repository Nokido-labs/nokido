"""NR — la reference des modules sort en PAIRE EN/FR, depuis la meme collecte.

Owner 2026-09-29 : « pourquoi 20-Modules-Reference.md n'est pas traduit en fr ? ». Toutes
les pages du wiki vont par paire `X.md` / `X.fr.md`, sauf la seule GENEREE : Home.fr.md
envoyait le lecteur francophone vers un habillage francais sans accents, sous un titre
anglais.

Ce que ces tests verrouillent :
- l'habillage est localise, les DEFINITIONS ne le sont pas (une traduction serait une
  seconde source, qui divergerait du code) ;
- les deux pages portent la MEME empreinte : le gate `--check` juge l'une ET l'autre ;
- la page FR se DERIVE de `OUT` : substituer `OUT` isole les deux ecritures ;
- la note « Mise à jour » est celle de `forge_docs_datation`, a la meme place : la
  datation relit la page generee INCHANGEE au lieu de la reecrire.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_wiki_modules as W  # noqa: E402

H = "2026-09-16T21:30:00Z"
_FICHES = [
    {"chemin": "tools/a.py", "nom": "a", "doc": "Fait a, sans accent traduit.", "publics": ["f"], "loc": 1200},
    {"chemin": "app/b.py", "nom": "b", "doc": "", "publics": ["g"], "loc": 20},
]


def test_la_page_fr_a_un_habillage_francais_et_pointe_vers_l_anglaise():
    page = W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang="fr")
    assert "# 20 — Référence des modules" in page
    assert "Page GÉNÉRÉE" in page
    assert "> Mise à jour : 2026-09-16" in page
    assert "[English](20-Modules-Reference.md) · **Français**" in page
    assert "## Modules sans docstring — trous mesurés" in page
    assert "resource: repo://docs/wiki/20-Modules-Reference.fr.md" in page
    assert "## non classé" in page
    assert "1 200 lignes" in page


def test_la_page_en_a_un_habillage_anglais_et_pointe_vers_la_francaise():
    page = W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang="en")
    assert "# 20 — Modules Reference" in page
    assert "GENERATED page" in page
    assert "> Updated: 2026-09-16" in page
    assert "**English** · [Français](20-Modules-Reference.fr.md)" in page
    assert "Mise à jour" not in page and "Page GENEREE" not in page
    assert "resource: repo://docs/wiki/20-Modules-Reference.md" in page
    assert "1,200 lines" in page


def test_les_definitions_ne_sont_pas_traduites():
    for lang in ("en", "fr"):
        page = W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang=lang)
        assert "| Fait a, sans accent traduit. |" in page, lang


def test_une_langue_inconnue_est_refusee_et_non_devinee():
    with pytest.raises(KeyError):
        W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang="de")


def test_les_deux_pages_ont_la_meme_empreinte_donc_le_meme_verdict():
    emp = W.empreinte_du_corpus(_FICHES)
    autre = W.empreinte_du_corpus([dict(_FICHES[0], doc="Fait a, autrement."), _FICHES[1]])
    for lang in ("en", "fr"):
        page = W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang=lang)
        assert W.etat_de_fraicheur(page, "2222222222", empreinte_actuelle=emp) == "FRAIS", lang
        assert W.etat_de_fraicheur(page, "2222222222", empreinte_actuelle=autre) == "PERIME", lang


def test_la_page_fr_se_derive_de_OUT():
    assert W.cible_fr(Path("x") / "20-Modules-Reference.md") == Path("x") / "20-Modules-Reference.fr.md"
    assert W.cible_fr(W.OUT).name == W.NOM_FR and W.OUT.name == W.NOM_EN


def test_la_generation_ecrit_la_paire_et_annote_les_deux(tmp_path, monkeypatch):
    """Chemin reel (`main`), cibles substituees : la page FR suit `OUT` et recoit, elle
    aussi, la note des ports arretes -- elle cite les memes docstrings."""
    monkeypatch.setattr(W, "OUT", tmp_path / "20-Modules-Reference.md")
    monkeypatch.setattr(W, "CARDS", tmp_path / "forge_card_summaries.json")
    monkeypatch.setattr(W, "collecter", lambda: [
        {"chemin": "app/brain_worker.py", "nom": "brain_worker",
         "doc": "Worker ZMQ sur :5557.", "publics": [], "loc": 10}])
    monkeypatch.setattr(W, "organes", lambda: {})
    assert W.main([]) == 0
    en = (tmp_path / "20-Modules-Reference.md").read_text(encoding="utf-8")
    fr = (tmp_path / "20-Modules-Reference.fr.md").read_text(encoding="utf-8")
    assert "Modules Reference" in en and "Référence des modules" in fr
    for texte in (en, fr):
        assert "ports-arretes" in texte
        assert "Worker ZMQ sur :5557." in texte


def test_check_juge_aussi_la_page_fr(tmp_path, monkeypatch):
    """Une jumelle FR perimee sous une page EN fraiche : le gate doit le dire (rc=1)."""
    monkeypatch.setattr(W, "OUT", tmp_path / "20-Modules-Reference.md")
    monkeypatch.setattr(W, "collecter", lambda: list(_FICHES))
    monkeypatch.setattr(W, "sha_du_depot", lambda *a, **k: "2222222222")
    W.OUT.write_text(W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang="en"),
                     encoding="utf-8")
    vieille = [dict(_FICHES[0], doc="Fait a, autrement."), _FICHES[1]]
    W.cible_fr(W.OUT).write_text(W.rendre(vieille, {}, sha="1111111111", horodatage=H, lang="fr"),
                                 encoding="utf-8")
    assert W.verifier() == 1
    W.cible_fr(W.OUT).write_text(W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang="fr"),
                                 encoding="utf-8")
    assert W.verifier() == 0


def test_la_datation_relit_la_page_generee_inchangee(tmp_path):
    """Deux producteurs, un fichier : si la note du generateur n'etait pas celle de la
    datation, a la meme place, `forge_docs_datation --apply` la reecrirait a chaque passage."""
    import forge_docs_datation as D
    for lang, nom in (("en", "20-Modules-Reference.md"), ("fr", "20-Modules-Reference.fr.md")):
        p = tmp_path / nom
        p.write_text(W.rendre(_FICHES, {}, sha="1111111111", horodatage=H, lang=lang),
                     encoding="utf-8")
        etat, iso = D.traiter(p, apply=False, racine=tmp_path)
        assert (etat, iso) == ("INCHANGEE", "2026-09-16"), (lang, etat, iso)
