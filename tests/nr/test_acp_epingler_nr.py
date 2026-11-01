"""NR -- epingleur ACP : identite de l'ecouteur PROUVEE avant tout epinglage. Tout faux, tmp, aucun vrai keyring/reseau.

Regle : ILLISIBLE ou non prouve = REFUS (jamais un epinglage « au mieux »). --dry-run n'ecrit jamais.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acp_worker_faux as F  # noqa: E402,F401
import forge_acp_epingler as E  # noqa: E402


def _jwks():
    return json.dumps({"keys": [{"kty": "OKP", "crv": "Ed25519", "kid": F.KID, "x": F.H.b64url_encode(F.EPINGLE[F.KID])}]})


def _ident(pid=5150, cree=1000.0, user="user-PC\\user", service="NokidoMCP"):
    return {"pid": pid, "compte": user, "service": service, "cree": cree}


def _prouveur_ok(**kw):
    """Prouveur injecte : identite deja prouvee (les tests qui ne portent pas sur l'identite n'ouvrent jamais le reseau)."""
    ident = _ident(**kw)
    return lambda url: dict(ident)


def _prouveur_refus():
    def f(url):
        raise E.IdentiteNonProuvee("identite non prouvee")
    return f


def _reseau_hub(pid=5150):
    return lambda: [(pid, "127.0.0.1", 8766)]


def _proc_ok(user="user-PC\\user", cree=1000.0):
    return lambda pid: {"user": user, "cree": cree, "nom": "python.exe"}


def _inv_hub(service="NokidoMCP", preuve="superviseur"):
    return lambda pid: {"identite": service, "preuve": preuve}


# ---- tests de base (preuve d'identite injectee, jamais le reseau reel) ----

def test_color():
    assert E.__FORGE_COLOR__


def test_dry_run_n_ecrit_rien():
    ecrits = []
    kid, emp, ecrit, ident = E.epingler(http=lambda u: _jwks(),
                                        coffre=lambda n, v: ecrits.append((n, v)) or True,
                                        prouver=_prouveur_ok())
    assert kid == F.KID and ecrit is False and ecrits == []
    assert emp == F.H.empreinte(F.EPINGLE[F.KID])
    assert ident["service"] == "NokidoMCP"


def test_ecrire_epingle_lisible_par_le_worker(monkeypatch):
    ecrits = {}
    E.epingler(ecrire=True, http=lambda u: _jwks(), coffre=lambda n, v: ecrits.update({n: v}) or True,
               prouver=_prouveur_ok())
    monkeypatch.setattr(F.W, "_lire_coffre_personnel", lambda nom: ecrits.get(nom))
    assert F.W.epingle_coffre() == F.EPINGLE


def test_url_non_loopback_refusee():
    with pytest.raises(ValueError):
        E.epingler(url="http://evil.example:8766/x", http=lambda u: _jwks(), prouver=_prouveur_ok())


def test_reponse_sans_cle_refusee():
    with pytest.raises(ValueError):
        E.epingler(http=lambda u: "{}", prouver=_prouveur_ok())


# ---- identite de l'ecouteur : NR ----

def test_ecouteur_sous_compte_bac_a_sable_refuse():
    """Un processus d'un compte LaForgeSbx* qui lie 8766 n'est PAS le hub."""
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(), proc=_proc_ok(user="LaForgeSbxOffline"), inventaire=_inv_hub())


def test_ecouteur_pid_inconnu_du_superviseur_refuse():
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(), proc=_proc_ok(), inventaire=lambda pid: None)


def test_ecouteur_identifie_autre_service_refuse():
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(), proc=_proc_ok(), inventaire=_inv_hub(service="NokidoOllama"))


def test_ecouteur_identifie_sans_preuve_superviseur_refuse():
    """Un nom de service suppose (preuve « parent » ou « nom ») ne prouve rien : seule la preuve superviseur vaut."""
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(), proc=_proc_ok(), inventaire=_inv_hub(preuve="parent"))


def test_acces_au_processus_refuse_illisible_nest_pas_oui():
    """ILLISIBLE (acces refuse) ne vaut JAMAIS identite prouvee."""
    def proc_refuse(pid):
        raise PermissionError("acces refuse")
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(), proc=proc_refuse, inventaire=_inv_hub())


def test_table_reseau_illisible_refusee():
    def reseau_refuse():
        raise PermissionError("net_connections refuse")
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=reseau_refuse, proc=_proc_ok(), inventaire=_inv_hub())


def test_plusieurs_ecouteurs_refuses():
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=lambda: [(5150, "127.0.0.1", 8766), (6160, "127.0.0.1", 8766)],
                      proc=_proc_ok(), inventaire=_inv_hub())


def test_aucun_ecouteur_refuse():
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=lambda: [], proc=_proc_ok(), inventaire=_inv_hub())


def test_pid_recycle_pendant_la_preuve_refuse():
    """La date de creation change entre la lecture et la relecture : pid recycle -> refus."""
    cree = iter([1000.0, 2000.0])
    with pytest.raises(E.IdentiteNonProuvee):
        E.prouver_hub(reseau=_reseau_hub(),
                      proc=lambda pid: {"user": "user-PC\\user", "cree": next(cree), "nom": "python.exe"},
                      inventaire=_inv_hub())


def test_hub_prouve_donne_pid_compte_service():
    ident = E.prouver_hub(reseau=_reseau_hub(), proc=_proc_ok(), inventaire=_inv_hub())
    assert ident == {"pid": 5150, "compte": "user-PC\\user", "service": "NokidoMCP", "cree": 1000.0}


def test_epingle_permise_en_ecrire_si_hub_prouve():
    ecrits = {}
    _, _, ecrit, _ = E.epingler(ecrire=True, http=lambda u: _jwks(),
                                coffre=lambda n, v: ecrits.update({n: v}) or True,
                                prouver=_prouveur_ok())
    assert ecrit is True and E.H.EPINGLE_NOM in ecrits


def test_dry_run_n_ecrit_jamais_meme_identite_prouvee():
    ecrits = []
    _, _, ecrit, _ = E.epingler(ecrire=False, http=lambda u: _jwks(),
                                coffre=lambda n, v: ecrits.append(n) or True, prouver=_prouveur_ok())
    assert ecrit is False and ecrits == []


def test_identite_non_prouvee_refuse_sans_lire_ni_ecrire():
    ecrits, appels = [], []
    with pytest.raises(E.IdentiteNonProuvee):
        E.epingler(ecrire=True, http=lambda u: appels.append(u) or _jwks(),
                   coffre=lambda n, v: ecrits.append(n) or True, prouver=_prouveur_refus())
    assert ecrits == [] and appels == []


def test_ecouteur_change_entre_preuve_et_lecture_refuse():
    """Preuve avant ET apres la lecture de la cle : si le pid a change, rien n'est epingle."""
    pids = iter([5150, 6160])

    def prouver(url):
        return _ident(pid=next(pids))
    ecrits = []
    with pytest.raises(E.IdentiteNonProuvee):
        E.epingler(ecrire=True, http=lambda u: _jwks(), coffre=lambda n, v: ecrits.append(n) or True,
                   prouver=prouver)
    assert ecrits == []


def test_main_affiche_pid_compte_service_a_cote_de_lempreinte(capsys, monkeypatch):
    monkeypatch.setattr(E, "epingler",
                        lambda url, ecrire=False: ("kid1", "ab" * 32, False, _ident()))
    assert E.main([]) == 0
    out = capsys.readouterr().out
    assert "pid" in out and "5150" in out and "NokidoMCP" in out and "user" in out and "empreinte" in out
