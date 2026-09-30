"""NR -- JETON PROJETE (2026-09-28) : le lanceur garde vivant le jeton court du service.

Defaut mesure le jour meme sur RSSWatcher : le service ne renouvelait son jeton injecte que
s'il appelait le hub dans les 5 dernieres minutes du bail ; peu bavard, il le laissait
expirer et retombait sur le secret statique. Correctif sur le motif des jetons projetes de
comptes de service Kubernetes : le LANCEUR (SYSTEM, vivant tant que le service vit)
renouvelle le jeton PAR TPM avant expiration et l'ecrit dans un fichier lisible par le SEUL
compte du service ; le service relit ce fichier.

Contrats :
  1. racine `NokidoJetons` absente, ou dont le proprietaire n'est ni SYSTEM ni
     Administrateurs : pas de projection, et c'est dit (ProgramData laisse tout compte
     pre-creer un sous-dossier) ;
  2. le dossier du service recoit une DACL protegee : SYSTEM controle total, le compte du
     service en lecture, personne d'autre ; l'ecriture du jeton est atomique ;
  3. la boucle renouvelle quand il reste moins de 10 min, s'arrete quand le service meurt,
     et dit un refus sans jamais ecrire de jeton vide ;
  4. cote service : pres de l'expiration, le fichier projete est relu AVANT tout echange ;
     seul un jeton de la MEME identite et plus recent est adopte.
Aucune vraie valeur : jetons fabriques ici.
"""
from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IDENT = "SERVICE_NR_PROJETE"


def _faux_jeton(reste_s: float, sub: str = IDENT, marque: str = "a") -> str:
    charge = json.dumps({"sub": sub, "exp": time.time() + reste_s, "m": marque}).encode()
    return base64.urlsafe_b64encode(charge).rstrip(b"=").decode() + ".signature-de-test"


def _lanceur():
    spec = importlib.util.spec_from_file_location("nr_runas_projete", ROOT / "tools/forge_runas_launcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_racine_absente_ou_mal_possedee_pas_de_projection(tmp_path, monkeypatch):
    m = _lanceur()
    absente = m._racine_sure(tmp_path / "absente")
    monkeypatch.setattr(m, "_proprietaire", lambda chemin: "S-1-5-21-1-2-3-1009")
    (tmp_path / "piegee").mkdir()
    piegee = m._racine_sure(tmp_path / "piegee")
    monkeypatch.setattr(m, "_proprietaire", lambda chemin: "S-1-5-32-544")
    ok = (bool(absente), bool(piegee), m._racine_sure(tmp_path / "piegee"))
    assert ok == (True, True, "")


def test_le_dossier_du_service_est_restreint_et_l_ecriture_atomique(tmp_path, monkeypatch):
    m = _lanceur()
    commandes: list = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, **kw: commandes.append(cmd) or
                        type("R", (), {"returncode": 0})())
    dossier = tmp_path / "SERVICE-1"
    assert m._preparer_dossier(dossier, "LaForgeSbxOnline") is True
    cmd = " ".join(commandes[0])
    ok = ("/inheritance:r" in cmd, "*S-1-5-18:(OI)(CI)F" in cmd, "LaForgeSbxOnline:(OI)(CI)R" in cmd,
          cmd.count(":(") == 2)
    assert ok == (True, True, True, True)
    chemin = dossier / "jeton"
    m._ecrire_jeton(chemin, "jeton-a")
    m._ecrire_jeton(chemin, "jeton-b")
    ok = (chemin.read_text(encoding="ascii"), sorted(p.name for p in dossier.iterdir()))
    assert ok == ("jeton-b", ["jeton"])


def test_sans_compte_connu_pas_de_dossier(tmp_path):
    m = _lanceur()
    assert m._preparer_dossier(tmp_path / "X", None) is False


def test_la_boucle_renouvelle_avant_expiration_et_s_arrete_avec_le_service(tmp_path, monkeypatch, capsys):
    m = _lanceur()
    chemin = tmp_path / "jeton"
    emis: list = []
    reponses = iter([(0, _faux_jeton(1800, marque="neuf"), "TPM"), (3, "", "refus de test")])
    monkeypatch.setattr(m, "_emettre_jeton", lambda ident: emis.append(ident) or next(reponses))
    tours = iter([True, True, False])
    m._boucle_projection(IDENT, chemin, _faux_jeton(120, marque="vieux"), vivant=lambda: next(tours),
                         attendre=lambda s: None)
    capsys.readouterr()
    p = chemin.read_text().split(".")[0]
    ok = (emis, '"m": "neuf"' in base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)).decode())
    assert ok == ([IDENT], True)


def test_un_refus_de_renouvellement_n_ecrit_jamais_de_jeton_vide(tmp_path, monkeypatch, capsys):
    m = _lanceur()
    chemin = tmp_path / "jeton"
    m._ecrire_jeton(chemin, "jeton-en-place")
    monkeypatch.setattr(m, "_emettre_jeton", lambda ident: (4, "", "aucun chemin de preuve"))
    tours = iter([True, False])
    m._boucle_projection(IDENT, chemin, _faux_jeton(60), vivant=lambda: next(tours), attendre=lambda s: None)
    sortie = capsys.readouterr()
    ok = (chemin.read_text(encoding="ascii"), "REFUS" in sortie.err)
    assert ok == ("jeton-en-place", True)


@pytest.fixture
def cred(monkeypatch):
    c = importlib.import_module("nokido_agent.app.forge_agent_credential")

    def _vider():
        c.invalider()
        for etat in (c._INJECTES, c._ECHEC_RENOUVELLEMENT, c._ETAT):
            etat.clear()

    _vider()
    monkeypatch.setattr(c, "_statique", lambda agent: "")
    yield c
    _vider()


def test_le_service_relit_le_fichier_projete_avant_tout_echange(cred, tmp_path, monkeypatch):
    fichier = tmp_path / "jeton"
    frais = _faux_jeton(1790, marque="projete")
    fichier.write_text(frais, encoding="ascii")
    echanges: list = []
    monkeypatch.setattr(cred, "_renouveler_par_le_hub", lambda j: echanges.append(j) or "")
    monkeypatch.setenv("NOKIDO_IDENTITE", IDENT)
    monkeypatch.setenv("NOKIDO_JETON_COURT", _faux_jeton(120, marque="vieux"))
    monkeypatch.setenv("NOKIDO_JETON_FICHIER", str(fichier))
    ok = (cred.jeton_pour(IDENT) == frais, echanges, cred.etat()["detail"][IDENT]["mode"])
    assert ok == (True, [], "INJECTE_PROJETE")


def test_un_fichier_projete_d_une_autre_identite_n_est_jamais_adopte(cred, tmp_path, monkeypatch):
    fichier = tmp_path / "jeton"
    fichier.write_text(_faux_jeton(1790, sub="UNE_AUTRE_IDENTITE"), encoding="ascii")
    monkeypatch.setattr(cred, "_renouveler_par_le_hub", lambda j: "")
    vieux = _faux_jeton(120, marque="vieux")
    monkeypatch.setenv("NOKIDO_IDENTITE", IDENT)
    monkeypatch.setenv("NOKIDO_JETON_COURT", vieux)
    monkeypatch.setenv("NOKIDO_JETON_FICHIER", str(fichier))
    assert cred.jeton_pour(IDENT) == vieux
