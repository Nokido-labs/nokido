"""Non-regression : le classifieur du recensement du cablage des interfaces.

Le moteur (Playwright) n'est pas teste ici — il l'est par le gate ui-acceptance. Ce
fichier verrouille la partie PURE : comment un element interactif rendu devient un
verdict, et ce que le rapport en dit. Motif : un recensement qui classe « CABLE » un
bouton dont la route rend 404 ferait passer une tuile morte pour vivante — le contraire
exact de la doctrine live-only (owner 2026-08-21).
"""

from __future__ import annotations

import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(_RACINE / "tools"))

import forge_ui_nervous_census as census  # noqa: E402

PAGE = "http://127.0.0.1:7400/dashboard"


def _el(tag="button", role="button", name="Start", attrs=None, listeners=0, **k):
    base = {"i": 0, "tag": tag, "role": role, "name": name, "visible": True, "attrs": attrs or {},
            "listeners": listeners, "form_action": None, "form_method": None, "disabled": False,
            "input_type": None}
    base.update(k)
    return base


# ------------------------------------------------------------------- cibles

def test_un_lien_relatif_se_resout_sur_la_page():
    c = census._cible_de(_el("a", "link", "Postal", {"href": "/postal"}), PAGE)
    assert c == ("GET", "http://127.0.0.1:7400/postal", "href")


def test_une_ancre_ou_un_uri_script_nest_pas_une_route():
    assert census._cible_de(_el("a", "link", "haut", {"href": "#top"}), PAGE) is None
    assert census._cible_de(_el("a", "link", "x", {"href": "java" + "script:void(0)"}), PAGE) is None


def test_htmx_prime_sur_le_href():
    c = census._cible_de(_el("a", "link", "Restart", {"href": "/x", "hx-post": "/api/hub/restart"}), PAGE)
    assert c == ("POST", "http://127.0.0.1:7400/api/hub/restart", "htmx")


def test_un_bouton_submit_herite_de_son_formulaire():
    e = _el("button", "button", "Envoyer", {"type": "submit"}, form_action="/auth/login", form_method="post")
    assert census._cible_de(e, PAGE) == ("POST", "http://127.0.0.1:7400/auth/login", "form")


# ------------------------------------------------------------------ verdicts

def test_une_route_vivante_est_cablee_et_une_404_est_morte():
    e = _el("a", "link", "Postal", {"href": "/postal"})
    assert census.classer(e, 200, PAGE) == "CABLE"
    assert census.classer(e, 404, PAGE) == "MORT"
    assert census.classer(e, 500, PAGE) == "MORT"
    assert census.classer(e, None, PAGE) == "MORT", "injoignable = la cible ne repond pas"


def test_une_cible_externe_nest_jamais_un_mort():
    """Le sandbox du hub est hors ligne : 129 liens openrouter/huggingface y sortaient
    « injoignable » et donc MORT. Hors perimetre se dit hors perimetre."""
    e = _el("a", "link", "OpenRouter", {"href": "https://openrouter.ai/keys"})
    assert census.classer(e, "externe", PAGE) == "EXTERNE"
    assert census.classer(e, None, PAGE) == "MORT", "sans le marqueur, un injoignable reste un injoignable"


def test_une_cible_a_effet_nest_jamais_sondee():
    """/auth/logout accepte le GET : la sonde a deconnecte la session du recensement et
    toutes les pages suivantes sont sorties en 401. Le nom de la route suffit a
    s'abstenir — et l'abstention se dit PRUDENCE, pas MORT ni CABLE."""
    for chemin in ("/auth/logout", "/api/hub/restart", "/api/rag/purge", "/admin/kill/12"):
        assert census.DANGEREUX.search(chemin), chemin
    assert not census.DANGEREUX.search("/dashboard/diag")
    e = _el("a", "link", "Logout", {"href": "/auth/logout"})
    assert census.classer(e, "prudence", PAGE) == "PRUDENCE"


def test_les_pages_alias_sont_comptees_une_fois():
    a = {"url": "/llm_dashboard/", "titre": "LLM", "elements": [{"role": "button", "name": "Copy", "verdict": "JS_OPAQUE"}]}
    b = {"url": "/llm-dashboard", "titre": "LLM", "elements": [{"role": "button", "name": "Copy", "verdict": "JS_OPAQUE"}]}
    c = {"url": "/autre", "titre": "Autre", "elements": [{"role": "link", "name": "x", "verdict": "CABLE"}]}
    vide1 = {"url": "/v1", "titre": "", "elements": []}
    vide2 = {"url": "/v2", "titre": "", "elements": []}
    uniques = census.pages_uniques([a, b, c, vide1, vide2])
    assert [p["url"] for p in uniques] == ["/llm_dashboard/", "/autre", "/v1", "/v2"], "les pages vides ne sont pas des doublons entre elles"
    assert b["doublon_de"] == "/llm_dashboard/"


def test_un_401_est_cable_mais_hors_de_portee():
    assert census.classer(_el("a", "link", "Admin", {"href": "/admin"}), 401, PAGE) == "CABLE_AUTH"


def test_un_405_sur_une_route_post_prouve_quelle_existe():
    e = _el("button", "button", "Restart", {"hx-post": "/api/hub/restart"})
    assert census.classer(e, 405, PAGE) == "CABLE"
    # mais un 405 sur un simple lien GET n'est pas une preuve de vie
    assert census.classer(_el("a", "link", "x", {"href": "/x"}), 405, PAGE) == "MORT"


def test_un_404_sur_une_route_non_get_est_incertain_pas_mort():
    """Mesure 2026-08-26 : /api/opsec/set (hub Deno) est declare POST et rend 404 au GET.
    La sonde ne sait pas trancher — elle le dit, elle n'invente pas un mort."""
    e = _el("button", "button", "Kill switch", {"hx-post": "/api/opsec/set"})
    assert census.classer(e, 404, PAGE) == "INCERTAIN"
    assert census.classer(_el("a", "link", "x", {"href": "/x"}), 404, PAGE) == "MORT", "un lien GET en 404 reste mort"


def test_un_gestionnaire_sans_cible_est_opaque_pas_visuel():
    assert census.classer(_el(attrs={"@click": "open()"}), "non_sonde", PAGE) == "JS_OPAQUE"
    assert census.classer(_el(listeners=2), "non_sonde", PAGE) == "JS_OPAQUE"
    assert census.classer(_el(attrs={"onclick": "go()"}), "non_sonde", PAGE) == "JS_OPAQUE"


def test_un_bouton_sans_rien_est_du_decor():
    assert census.classer(_el(), "non_sonde", PAGE) == "VISUEL"


def test_un_champ_est_un_controle_pas_une_action():
    assert census.classer(_el("input", "textbox", "Provider", input_type="text"), "non_sonde", PAGE) == "CONTROLE"
    assert census.classer(_el("select", "combobox", "Modele"), "non_sonde", PAGE) == "CONTROLE"
    # un input type=submit est un bouton, pas un controle
    e = _el("input", "button", "Go", input_type="submit", form_action="/run", form_method="post")
    assert census.classer(e, 200, PAGE) == "CABLE"


# ---------------------------------------------------------- invisibilite agent

def test_un_element_sans_nom_ou_sans_role_est_invisible_a_lagent():
    assert census.invisible_agent(_el(name="")) is True
    assert census.invisible_agent(_el(role=None, name="Start")) is True
    assert census.invisible_agent(_el(tag="div", role="generic", name="Start")) is True
    assert census.invisible_agent(_el(role="button", name="Start")) is False


# ------------------------------------------------------------------ resume

def test_le_resume_compte_chaque_verdict_et_les_caches():
    els = [
        {"verdict": "CABLE", "invisible_agent": False, "visible": True},
        {"verdict": "MORT", "invisible_agent": True, "visible": True},
        {"verdict": "VISUEL", "invisible_agent": False, "visible": False},
    ]
    r = census.resumer(els)
    assert r["total"] == 3 and r["CABLE"] == 1 and r["MORT"] == 1 and r["VISUEL"] == 1
    assert r["invisible_agent"] == 1 and r["caches"] == 1


def test_le_rapport_nomme_les_morts_et_les_opaques_et_le_manifeste():
    s = {"surface": "web_hub", "base": "http://127.0.0.1:7400", "socket": "accepte", "login": "ok",
         "resume": {"pages": 1, "total": 2, "CABLE": 0, "MORT": 1, "JS_OPAQUE": 1},
         "pages": [{"url": "http://127.0.0.1:7400/", "elements": [
             {"role": "link", "name": "Vieux", "verdict": "MORT", "invisible_agent": False, "visible": True,
              "cible": {"methode": "GET", "url": "http://127.0.0.1:7400/mort"}, "statut": 404, "erreur": None,
              "attrs": {}, "tag": "a"},
             {"role": "button", "name": "Ouvrir", "verdict": "JS_OPAQUE", "invisible_agent": False, "visible": True,
              "cible": None, "statut": "non_sonde", "erreur": None, "attrs": {"@click": "x"}, "tag": "button"},
         ]}]}
    md = census._rapport([s], {"dashboard": "live"}, "test")
    assert "MORT" in md and "/mort" in md and "404" in md
    assert "JS_OPAQUE" in md and "Ouvrir" in md
    assert "| web_hub | accepte | ok |" in md and "live" in md


# ---------------------------------------------------------- parseur statique

HTML = """<html><head><title> Nokido  Hub </title></head><body>
<a href="/postal">Postal</a>
<a href="#top"><span>Haut</span></a>
<button hx-post="/api/hub/restart">Restart hub</button>
<form action="/auth/login" method="post">
  <label for="tok">Jeton admin</label><input id="tok" name="admin_token" type="password">
  <input type="hidden" name="redirect_to" value="/">
  <button type="submit">Entrer</button>
</form>
<div role="button" @click="open()">Ouvrir</div>
<button></button>
<select name="modele"><option>a</option></select>
</body></html>"""


def test_le_parseur_statique_lit_noms_cibles_et_formulaires():
    ex = census._Extracteur()
    ex.feed(HTML)
    els = {e["name"]: e for e in ex.finir()}
    assert " ".join(ex.titre.split()) == "Nokido Hub"
    assert els["Postal"]["tag"] == "a" and els["Postal"]["role"] == "link"
    assert els["Haut"]["attrs"]["href"] == "#top"
    assert els["Restart hub"]["attrs"]["hx-post"] == "/api/hub/restart"
    assert els["Jeton admin"]["tag"] == "input", "le label for=id nomme le champ"
    assert els["Entrer"]["form_action"] == "/auth/login" and els["Entrer"]["form_method"] == "post"
    assert els["Ouvrir"]["role"] == "button" and "@click" in els["Ouvrir"]["attrs"]
    caches = [e for e in ex.elements if e["tag"] == "input" and e["input_type"] == "hidden"]
    assert caches and caches[0]["role"] is None and caches[0]["visible"] is False


def test_le_parseur_statique_alimente_le_meme_classifieur():
    ex = census._Extracteur()
    ex.feed(HTML)
    els = {e["name"]: e for e in ex.finir()}
    page = "http://127.0.0.1:7400/"
    assert census.classer(els["Postal"], 200, page) == "CABLE"
    assert census.classer(els["Restart hub"], 405, page) == "CABLE"
    assert census.classer(els["Entrer"], 405, page) == "CABLE"
    assert census.classer(els["Ouvrir"], "non_sonde", page) == "JS_OPAQUE"
    bouton_vide = next(e for e in ex.elements if e["tag"] == "button" and not e["name"])
    assert census.classer(bouton_vide, "non_sonde", page) == "VISUEL"
    assert census.invisible_agent(bouton_vide) is True
    selecteur = next(e for e in ex.elements if e["tag"] == "select")
    assert census.classer(selecteur, "non_sonde", page) == "CONTROLE"
    assert census.classer(els["Haut"], "non_sonde", page) == "VISUEL", "une ancre n'est pas une route"


def test_une_surface_injoignable_est_dite_injoignable_pas_vide():
    s = {"surface": "graph", "base": "http://127.0.0.1:7474", "socket": "expire", "login": None,
         "resume": {"injoignable": "expire"}, "pages": []}
    md = census._rapport([s], {}, "test")
    assert "| graph | expire |" in md
    c = census._contrat([s])
    assert c["surfaces"]["graph"]["socket"] == "expire" and c["surfaces"]["graph"]["pages"] == {}
