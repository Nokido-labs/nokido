"""NR — l'attribut `Secure` du cookie de session se DECLARE, il ne s'edite plus.

Revue de securite 2026-09-18, point 7. Le cookie `lf_session` posait
`secure=False` en LITTERAL. Ce n'etait pas une negligence — le webhub est servi
en HTTP sur le loopback, et un cookie `Secure` n'y serait jamais renvoye par le
navigateur : la session casserait. Le commentaire le disait, et il avait raison.

Le defaut est ailleurs, et il est reel : tel quel, poser un reverse proxy TLS
demande d'EDITER CE FICHIER. C'est exactement l'etape qu'on oublie, et l'oubli
ne se voit pas — un cookie de session sans `Secure` derriere du TLS voyage en
clair a la premiere requete HTTP.

La valeur est donc lue a chaque appel dans `LAFORGE_WEBHUB_TLS`, sur le patron
d'interrupteur global deja employe dans le corps (`forge_db_path.m2m_path`).

CE QUE CE TEST VERROUILLE, dans cet ordre :
  1. le defaut est INCHANGE — un durcissement qui casse la session locale serait
     un echec, pas une amelioration ;
  2. la bascule produit vraiment l'effet, sinon on aurait un interrupteur
     decoratif (« un mecanisme present mais non cable est une dette ») ;
  3. `httponly` et `samesite` survivent au changement — on ne troque pas une
     protection contre une autre.

Il passe par l'APPEL REEL et non par une lecture de source, parce que la
premiere ecriture de ce correctif utilisait `os.environ` alors que le module
importe la bibliotheque sous le nom `_os`. Un `NameError` que ni l'AST ni la
relecture ne voyaient : seul l'appel l'a leve.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

W = pytest.importorskip("app.web_hub.app", reason="webhub non importable dans cet environnement")

VARIABLE = "LAFORGE_WEBHUB_TLS"


class _ReponseTemoin:
    """Capture les arguments qui atteignent REELLEMENT `set_cookie`."""

    def __init__(self):
        self.vu = None

    def set_cookie(self, **kw):
        self.vu = kw


def _poser(monkeypatch, valeur):
    if valeur is None:
        monkeypatch.delenv(VARIABLE, raising=False)
    else:
        monkeypatch.setenv(VARIABLE, valeur)
    r = _ReponseTemoin()
    W._set_session_cookie(r, "jeton-de-test-sans-valeur-reelle", 60)
    assert r.vu is not None, "aucun cookie pose — la fonction est cassee"
    return r.vu


@pytest.mark.parametrize("valeur", [None, "", "0", "false", "no"])
def test_le_defaut_reste_non_secure_pour_le_loopback(monkeypatch, valeur):
    """Sans declaration, RIEN ne change : la session locale continue de marcher."""
    assert _poser(monkeypatch, valeur)["secure"] is False, (
        f"`secure` est passe a True sans declaration (valeur={valeur!r}) : la "
        "session du webhub en HTTP local serait cassee"
    )


@pytest.mark.parametrize("valeur", ["1", "true", "TRUE", "yes", "on", "ON"])
def test_la_declaration_produit_reellement_l_effet(monkeypatch, valeur):
    """Sans ceci, l'interrupteur serait decoratif — le cas le plus courant."""
    assert _poser(monkeypatch, valeur)["secure"] is True, (
        f"{VARIABLE}={valeur!r} ne pose pas `Secure` : l'interrupteur existe mais "
        "n'a aucun effet, c'est une dette de cablage et non une protection"
    )


@pytest.mark.parametrize("valeur", [None, "1"])
def test_les_autres_protections_survivent_a_la_bascule(monkeypatch, valeur):
    """On n'echange pas une protection contre une autre."""
    vu = _poser(monkeypatch, valeur)
    assert vu["httponly"] is True, "httponly perdu"
    assert str(vu["samesite"]).lower() == "lax", f"samesite perdu : {vu['samesite']!r}"


def test_la_valeur_est_relue_a_chaque_appel(monkeypatch):
    """MORSURE — une lecture figee a l'import rendrait la bascule inoperante
    jusqu'au redemarrage, et c'est precisement ce qu'on cherche a eviter."""
    avant = _poser(monkeypatch, None)["secure"]
    pendant = _poser(monkeypatch, "1")["secure"]
    apres = _poser(monkeypatch, "0")["secure"]
    assert (avant, pendant, apres) == (False, True, False), (
        f"la valeur n'est pas relue a chaque appel : {(avant, pendant, apres)}"
    )
