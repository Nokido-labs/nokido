# -*- coding: utf-8 -*-
"""La generation d'interface doit NOMMER sa panne, jamais rendre un vide muet.

Mesure 2026-08-30 en production : /ui/auto/services-status et
/ui/auto/critical-events affichaient « rendu simple : generation indisponible ».
Ce texte est le defaut de `app.py` (`result.get("error") or "generation
indisponible"`) : il apparait quand `generate_ui` rend `html` vide SANS `error`.
Ni le timeout ni l'import n'etaient en cause -- c'etait le chemin de succes qui
rendait un vide sans motif, donc une panne indiagnosticable.

Deux causes OPPOSEES produisent ce vide, et les confondre envoie chercher le
defaut du mauvais cote : le modele n'a rien rendu, ou nous avons tout retire au
nettoyage. Ces tests fixent les deux, sans joindre aucun modele.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _fausse_cascade(monkeypatch, reponse: str, modele: str = "modele-test"):
    """Remplace le module que `generate_ui` importe DANS la fonction."""
    mod = types.ModuleType("forge_frugal_cascade")
    mod.cascade = lambda *_a, **_kw: {"response": reponse, "model_used": modele,
                                      "confidence": 0.9, "latency_ms": 12.0}
    monkeypatch.setitem(sys.modules, "forge_frugal_cascade", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_frugal_cascade", mod)


def test_reponse_vide_du_modele_est_nommee(monkeypatch):
    """Le modele repond mais ne produit rien : l'erreur doit le DIRE et citer le modele."""
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "")
    r = generate_ui("un widget", data_source={"a": 1})
    assert r["html"] == ""
    assert "VIDE" in r["error"] and "modele-test" in r["error"]


def test_fences_seules_comptent_comme_reponse_vide(monkeypatch):
    """Un modele qui ne rend que des delimiteurs markdown n'a rien produit."""
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "```html\n\n```")
    r = generate_ui("un widget")
    assert r["html"] == "" and "VIDE" in r["error"]


def test_sortie_entierement_neutralisee_est_distinguee_de_la_reponse_vide(monkeypatch):
    """Cause INVERSE : le modele a produit, c'est le nettoyage qui a tout retire.

    L'erreur doit designer le nettoyage et chiffrer ce qui avait ete produit,
    sinon on irait accuser le fournisseur pour un defaut qui est chez nous.
    """
    import app.web_hub.ui_generate as ug

    _fausse_cascade(monkeypatch, "<div>du vrai contenu genere</div>")
    monkeypatch.setattr(ug, "_sanitize_html", lambda _s: "")
    r = ug.generate_ui("un widget")
    assert r["html"] == ""
    assert "neutralisee" in r["error"] and "0 conserve" in r["error"]
    assert "VIDE" not in r["error"]


def test_cascade_entierement_en_echec_nomme_les_tiers_essayes(monkeypatch):
    """AUCUN tier n'a repondu : le message doit porter le DENOMINATEUR.

    Mesure en production 2026-08-30, apres le premier correctif : la page disait
    « le modele modele non nomme a rendu une reponse VIDE ». Le modele n'etait pas
    « non nomme » -- il n'y en avait AUCUN, `cascade` ayant rendu son dict par
    defaut. Elle tenait pourtant `tiers_tried` sous la main : c'est la difference
    entre « repare le modele X » et « aucun de tes N modeles ne repond ».
    """
    from app.web_hub.ui_generate import generate_ui

    mod = types.ModuleType("forge_frugal_cascade")
    mod.cascade = lambda *_a, **_kw: {"response": None, "model_used": None,
                                      "confidence": 0.0, "latency_ms": 42.0,
                                      "tiers_tried": ["local-qwen", "groq-8b", "groq-70b"]}
    monkeypatch.setitem(sys.modules, "forge_frugal_cascade", mod)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_frugal_cascade", mod)

    r = generate_ui("un widget")
    assert r["html"] == ""
    assert "aucun des 3 tiers" in r["error"]
    assert "groq-70b" in r["error"], "les tiers doivent etre NOMMES, pas seulement comptes"
    assert r["tiers_tried"] == ["local-qwen", "groq-8b", "groq-70b"]


def test_generation_normale_ne_regresse_pas(monkeypatch):
    """Le chemin nominal reste sans erreur : les gardes n'ont pas ferme la porte."""
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "<div>tableau des services</div>")
    r = generate_ui("un widget")
    assert not r.get("error")
    assert "tableau des services" in r["html"]


# ---------------------------------------------------------------------------
# UNE REPONSE QUI N'EST PAS DU HTML N'EST PAS UN RENDU (mesure 2026-09-16)
#
# Cinq appels IDENTIQUES a /ui/auto/veille-summary, session etablie par le
# formulaire, trois comportements :
#
#   appels 2 et 3 : html=3047 c, 12 <tr>          -> tableau correct
#   appel 4       : « rendu simple : timeout apres 25.0 s », 16 <tr> -> REPLI OK
#   appels 1 et 5 : html=17 c = « User Safety: safe »                -> SERVI TEL QUEL
#
# « User Safety: safe » est la reponse d'un garde-fou du MODELE, pas une
# interface. Elle etait servie comme du HTML parce que le garde de `app.py`
# teste `if not result.get("html")` : une chaine NON VIDE le satisfait. Le repli
# existait, fonctionnait (l'appel 4 le prouve) et n'etait simplement pas
# atteint -- l'existence d'un mecanisme n'est pas son effet reel.
#
# C'est aussi l'explication COMPLETE de l'intermittence qui faisait varier le
# verdict du gate UI d'une passe a l'autre : la reponse du modele varie, donc la
# page varie, sans qu'une ligne de code ait bouge.
#
# Le critere est STRUCTUREL et non devinable : un rendu d'interface contient au
# moins une balise. On ne juge NI la longueur, NI le contenu, NI le nombre de
# lignes -- ces trois-la dependraient des donnees et fermeraient la porte a des
# rendus legitimes.
# ---------------------------------------------------------------------------


def test_une_reponse_SANS_balise_n_est_pas_un_rendu(monkeypatch):
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "User Safety: safe")
    r = generate_ui("un widget")
    assert r["html"] == "", (
        "la reponse du garde-fou du modele est servie comme une interface : "
        "la page affiche « User Safety: safe » a la place de ses donnees"
    )
    assert r.get("error"), "un vide sans motif est une panne indiagnosticable"
    assert "User Safety" in r["error"], (
        "la panne doit NOMMER ce qui a ete rendu, sinon on cherchera du cote "
        "du timeout ou de la base, comme je l'ai fait"
    )


def test_l_extrait_de_la_reponse_hors_format_est_BORNE(monkeypatch):
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "z" * 5000)
    r = generate_ui("un widget")
    assert r["html"] == ""
    assert len(r["error"]) < 400, (
        "une reponse hors format de 5000 caracteres remonterait entiere dans "
        "le motif, puis dans les journaux"
    )


def test_un_html_entoure_de_texte_reste_un_rendu(monkeypatch):
    from app.web_hub.ui_generate import generate_ui

    _fausse_cascade(monkeypatch, "Voici :\n<table><tr><td>a</td></tr></table>")
    r = generate_ui("un widget")
    assert "<table>" in r["html"], (
        "le garde est trop strict : un modele qui preface son rendu d'une "
        "phrase verrait sa page refusee, et on aurait echange un faux vert "
        "contre un faux rouge"
    )
