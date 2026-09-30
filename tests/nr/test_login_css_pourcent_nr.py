"""Non-regression : la page de connexion ne sert pas de CSS invalide.

DEFAUT MESURE le 2026-09-09, en instruisant « l'interface web ne marche pas ».

La page servie par `render_login` contient trois fois `width: 100%%`. Le double
pourcent est un ECHAPPEMENT de gabarit `%`-format -- sauf que ce module n'emploie
QUE des f-strings : le `%%` n'est donc jamais reduit, il part tel quel dans la
reponse HTTP. Un navigateur ne connait pas `100%%` : il JETTE la declaration.

Ce que ca casse, mesure sur la page reelle : `.box` (le cadre du formulaire),
`input[type=password]` et `button` perdent tous les trois leur largeur. La page
reste utilisable -- ce n'etait PAS la cause de la page noire signalee, et il faut
le dire -- mais elle s'affiche mal, et c'est le seul defaut CERTAIN trouve sur ce
chemin.

POURQUOI UN NR ET PAS UNE SIMPLE CORRECTION : le residu vient d'une migration de
gabarit. Rien n'empeche la prochaine migration de le reintroduire, et personne ne
le verrait -- une regle CSS jetee ne leve aucune erreur, ni au serveur, ni au
navigateur. C'est un echec SILENCIEUX, donc il lui faut un temoin.

PORTEE DECLAREE : ce test lit la SORTIE de la fonction, pas sa source. Un `%%`
present dans un COMMENTAIRE du module ne le fait pas echouer -- et c'est voulu :
`launcher_html` en porte un dans une phrase en prose, qui n'a rien d'un defaut.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app", RACINE / "app" / "web_hub"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from web_hub.login_html import render_login  # noqa: E402


def _page() -> str:
    return render_login(version="test", error="", redirect_to="/")


def test_la_page_ne_contient_aucun_double_pourcent():
    """Un `%%` servi tel quel est du CSS que le navigateur jette en silence."""
    h = _page()
    restes = re.findall(r"[^\n]*%%[^\n]*", h)
    assert not restes, (
        "la page de connexion sert %d declaration(s) avec un double pourcent, "
        "jetee(s) par le navigateur : %r" % (len(restes), restes[:3]))


def test_les_trois_largeurs_sont_du_CSS_VALIDE():
    """Les trois regles concretes qui perdaient leur largeur."""
    h = _page()
    assert h.count("width: 100%;") >= 3, (
        "les declarations de largeur ne sont pas valides : "
        "%d occurrence(s) de `width: 100%%;` trouvee(s)" % h.count("width: 100%;"))


def test_la_page_reste_un_formulaire_UTILISABLE():
    """Garde anti-remede-pire-que-le-mal : on corrige du CSS, pas la page."""
    h = _page()
    for attendu in ('<form', 'action="/auth/login"', 'name="admin_token"',
                    'type="submit"'):
        assert attendu in h, f"la page de connexion a perdu {attendu!r}"


def test_le_champ_de_redirection_transporte_bien_sa_cible():
    """`redirect_to` doit revenir dans le formulaire, sinon la connexion renvoie
    l'utilisateur ailleurs que la ou il allait."""
    h = render_login(version="test", error="", redirect_to="/design/ui_kits/hub/index.html")
    assert "/design/ui_kits/hub/index.html" in h, (
        "la cible de redirection est perdue : apres connexion l'utilisateur "
        "n'arrivera pas sur la page demandee")
