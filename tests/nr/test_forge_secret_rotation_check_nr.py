"""Un verdict rassurant doit etre MERITE, jamais fabrique par une liste vide.

Regression du 2026-08-29 : `_git` de l'audit rend une CHAINE, pas un tuple
(rc, out, err). Un test `_git(...)[0] == 0` comparait donc le premier CARACTERE
a 0 -- toujours faux. Aucune ref retenue, rien scanne, et le module a repondu
« PROPRE » alors que 20 secrets venaient d'etre mesures. Faux negatif du cote le
plus cher : il aurait dit a l'owner qu'il n'y avait rien a faire.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_secret_rotation_check as frc  # noqa: E402


def test_historique_illisible_ne_donne_jamais_un_verdict_rassurant(monkeypatch):
    def _casse():
        raise RuntimeError("aucune ref publiable resolvable")

    monkeypatch.setattr(frc, "empreintes_historiques", _casse)
    r = frc.verifier()
    assert r["verdict"] == "INDETERMINE"
    assert r["verdict"] not in ("PROPRE", "ROTATIONNE")


def test_correspondance_rend_VIVANT(monkeypatch):
    """Une cle de l'historique encore en service = breche ouverte, pas un detail."""
    monkeypatch.setattr(frc, "empreintes_historiques", lambda: {"abc123": ["LaForge.env"]})
    monkeypatch.setattr(frc, "empreintes_en_service",
                        lambda: ({"abc123": ["coffre:GOOGLE_API_KEY"]}, []))
    r = frc.verifier()
    assert r["verdict"] == "VIVANT"
    assert r["encore_vivants"][0]["empreinte"] == "abc123"


def test_aucune_correspondance_rend_ROTATIONNE(monkeypatch):
    monkeypatch.setattr(frc, "empreintes_historiques", lambda: {"aaa": ["x"]})
    monkeypatch.setattr(frc, "empreintes_en_service", lambda: ({"bbb": ["y"]}, []))
    assert frc.verifier()["verdict"] == "ROTATIONNE"


def test_aucun_secret_en_service_lu_est_INDETERMINE(monkeypatch):
    """Ne pas avoir pu lire les secrets courants n'autorise aucune conclusion."""
    monkeypatch.setattr(frc, "empreintes_historiques", lambda: {"aaa": ["x"]})
    monkeypatch.setattr(frc, "empreintes_en_service", lambda: ({}, ["coffre KO"]))
    assert frc.verifier()["verdict"] == "INDETERMINE"


def test_l_empreinte_ne_restitue_pas_la_valeur():
    """On compare des empreintes tronquees : ni la valeur ni sa longueur ne
    doivent transparaitre dans ce qui sera affiche ou journalise."""
    e = frc._empreinte("valeur-secrete-quelconque-de-longueur-variable")
    assert len(e) == 12 and all(c in "0123456789abcdef" for c in e)
    assert "valeur" not in e


def test_empreintes_stables_et_discriminantes():
    assert frc._empreinte("a") == frc._empreinte(b"a")
    assert frc._empreinte("a") != frc._empreinte("b")


def test_panne_reseau_n_est_JAMAIS_une_revocation(monkeypatch):
    """La propriete la plus dangereuse de cette sonde : conclure « revoquee »
    parce qu'on n'a pas pu demander reviendrait a declarer close une breche
    ouverte, et a laisser une cle vivante dans un historique publie."""
    import urllib.request

    def _tombe(*a, **k):
        raise OSError("reseau injoignable")

    monkeypatch.setattr(urllib.request, "urlopen", _tombe)
    etat, detail = frc._sonder("openai", "peu-importe")
    assert etat == "INDETERMINE" and etat != "REVOQUEE"


def test_401_est_une_revocation(monkeypatch):
    import urllib.error
    import urllib.request

    def _refuse(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    assert frc._sonder("openai", "x")[0] == "REVOQUEE"


def test_400_avec_motif_explicite_est_une_revocation(monkeypatch):
    """Google refuse une cle morte en 400, motif dans le corps : sans le lire,
    on rendait INDETERMINE et l'owner rotationnait pour rien."""
    import io
    import urllib.error
    import urllib.request

    def _quatrecent(*a, **k):
        raise urllib.error.HTTPError(
            "u", 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"API key not valid"}}'))

    monkeypatch.setattr(urllib.request, "urlopen", _quatrecent)
    assert frc._sonder("google_api", "x")[0] == "REVOQUEE"


def test_400_sans_motif_reste_INDETERMINE(monkeypatch):
    """Un 400 peut venir d'une requete mal formee : ne rien conclure."""
    import io
    import urllib.error
    import urllib.request

    def _quatrecent(*a, **k):
        raise urllib.error.HTTPError("u", 400, "Bad Request", {},
                                     io.BytesIO(b'{"error":"quota"}'))

    monkeypatch.setattr(urllib.request, "urlopen", _quatrecent)
    assert frc._sonder("google_api", "x")[0] == "INDETERMINE"


def test_type_sans_sonde_ne_conclut_pas():
    assert frc._sonder("type_inconnu", "x")[0] == "INDETERMINE"
