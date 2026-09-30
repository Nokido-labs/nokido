# -*- coding: utf-8 -*-
"""NR — les PRODUCTEURS alimentent le temoin, sinon il agrege du vide.

`forge_ui_temoin.construire` sait separer transport, navigateur et applicatif. Encore
faut-il que quelqu'un MESURE ces trois couches : un temoin complet nourri de `None`
rend UNKNOWN sans savoir pourquoi, ce qui est exactement l'etat qu'il devait supprimer.

LE DEFAUT, LU DANS LA SOURCE le 2026-09-09 (`_service_repond`) :

    r = opener.open(BASE + "/health", timeout=timeout)
    return getattr(r, "status", 200) == 200
    except Exception:            # « injoignable EST la reponse »
        return False

`urlopen` LEVE `HTTPError` sur un 401. Le `except` l'attrape, la sonde rend False, et
la campagne imprime « interface injoignable » — alors que le service a repondu. C'est
la confusion transport/applicatif inscrite dans l'instrument, et elle a coute trois
changements de compte le jour meme. La sonde perd aussi le code HTTP, donc personne en
aval ne peut distinguer 401 de 500 de connexion refusee.

CE QUE CE FICHIER EXIGE, et rien de plus :
  - une sonde qui rend (joignable, http_status) et pour qui 4xx/5xx = JOIGNABLE ;
  - des observations de navigateur (executable, launched, context_created) tenues par
    la campagne et relisibles ;
  - un rapport qui EMBARQUE ces observations, sinon elles meurent avec le process.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent


def _camp():
    import importlib  # noqa: PLC0415
    chemin = str(RACINE / "tools")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    return importlib.import_module("forge_ui_campaign")


class _Rep:
    def __init__(self, status):
        self.status = status


class _Opener:
    """Faux opener : `open` rend une reponse, ou leve comme urllib le fait vraiment."""

    def __init__(self, effet):
        self._effet = effet

    def open(self, *a, **k):
        if isinstance(self._effet, Exception):
            raise self._effet
        return self._effet


def _patch_opener(monkeypatch, effet):
    import urllib.request  # noqa: PLC0415
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *a, **k: _Opener(effet), raising=True)


# --- transport --------------------------------------------------------------

def test_la_sonde_rend_le_statut_et_pas_seulement_un_booleen(monkeypatch):
    m = _camp()
    assert hasattr(m, "sonder_service"), (
        "la sonde doit rendre (joignable, http_status) : un booleen seul ne permet "
        "pas de distinguer 401 de 500 ni de connexion refusee")
    _patch_opener(monkeypatch, _Rep(200))
    joignable, statut = m.sonder_service(timeout=0.1)
    assert joignable is True and statut == 200


def test_un_401_est_JOIGNABLE(monkeypatch):
    """LE defaut. `HTTPError` est une REPONSE du serveur, pas une absence de serveur."""
    import urllib.error  # noqa: PLC0415
    m = _camp()
    err = urllib.error.HTTPError(
        "http://127.0.0.1:7400/health", 401, "Unauthorized", {}, None)
    _patch_opener(monkeypatch, err)
    joignable, statut = m.sonder_service(timeout=0.1)
    assert joignable is True, (
        "un service qui repond 401 REPOND : le declarer injoignable envoie chercher "
        "la panne dans le reseau alors qu'elle est dans l'authentification")
    assert statut == 401


def test_un_500_est_JOIGNABLE_aussi(monkeypatch):
    import urllib.error  # noqa: PLC0415
    m = _camp()
    err = urllib.error.HTTPError("http://x/health", 500, "err", {}, None)
    _patch_opener(monkeypatch, err)
    joignable, statut = m.sonder_service(timeout=0.1)
    assert joignable is True and statut == 500


def test_une_connexion_refusee_est_INJOIGNABLE(monkeypatch):
    """Contre-epreuve : sans elle, la sonde dirait « joignable » sur tout."""
    import urllib.error  # noqa: PLC0415
    m = _camp()
    _patch_opener(monkeypatch, urllib.error.URLError("connexion refusee"))
    joignable, statut = m.sonder_service(timeout=0.1)
    assert joignable is False
    assert statut is None, "aucun statut n'a ete rendu : ne pas en inventer un"


def test_l_ancien_predicat_booleen_reste_disponible(monkeypatch):
    """On ETEND, on ne casse pas : les appelants existants gardent leur contrat."""
    m = _camp()
    _patch_opener(monkeypatch, _Rep(200))
    assert m._service_repond(timeout=0.1) is True


# --- navigateur -------------------------------------------------------------

def test_les_observations_de_navigateur_sont_tenues_et_relisibles():
    m = _camp()
    assert hasattr(m, "noter_browser") and hasattr(m, "observations"), (
        "sans observation tenue, `browser.launched` reste None et le temoin ne peut "
        "pas distinguer « pas de navigateur » de « navigateur qui ne demarre pas »")
    m.noter_browser(executable="C:/nokido/ms-playwright/firefox-1532",
                    launched=True, context_created=False)
    obs = m.observations()
    assert obs["browser"]["executable"].endswith("firefox-1532")
    assert obs["browser"]["launched"] is True
    assert obs["browser"]["context_created"] is False


def test_les_observations_partent_d_un_etat_NON_MESURE():
    """Un defaut a False ferait passer « pas encore mesure » pour « a echoue »."""
    m = _camp()
    m.reinitialiser_observations()
    obs = m.observations()
    assert obs["browser"]["launched"] is None, (
        "None = pas mesure ; False = mesure et negatif. Les confondre fabrique des "
        "pannes qui n'ont pas eu lieu")
    assert obs["transport"]["service_reachable"] is None


def test_noter_transport_conserve_le_statut():
    m = _camp()
    m.reinitialiser_observations()
    m.noter_transport(service_reachable=True, http_status=401,
                      endpoint="http://127.0.0.1:7400")
    obs = m.observations()
    assert obs["transport"] == {"service_reachable": True, "http_status": 401,
                                "endpoint": "http://127.0.0.1:7400"}


# --- le rapport doit EMBARQUER les observations -----------------------------

def test_le_rapport_embarque_les_observations():
    """Sinon elles meurent avec le process et le temoin n'a rien a lire."""
    src = (RACINE / "tools" / "forge_ui_campaign.py").read_text(
        encoding="utf-8", errors="replace")
    assert "observations()" in src, (
        "les trois sorties report.json/verdict.json doivent embarquer "
        "`observations()` — y compris les chemins INDISPONIBLE, qui sont "
        "precisement ceux ou la cause doit etre lisible")
