"""NR -- jeton court injecte par le superviseur (decision owner 2026-09-28), etape B :
l'AUXILIAIRE que le superviseur appelle, sous SYSTEM, pour obtenir le jeton court d'une
identite avant de lancer le service.

Consigne owner du meme jour : « n'oublie pas le TPM dans la chaine si possible ». Le lanceur
prouve qu'il lance l'identite X par une assertion `X:horodatage` SIGNEE PAR LA CLE TPM
(ECDSA P-256, non exportable) -- chemin que `login_agent` verifie deja, fenetre anti-rejeu de
5 min. Aucun secret statique n'est alors lu.

Contrats :
  1. hors SYSTEM : refus (rc 2), rien sur stdout ;
  2. identite inconnue du registre ou ring <= DEV : refus (rc 3) -- l'owner ne passe jamais
     par le lanceur ;
  3. chemin TPM d'abord : assertion signee par `sign(..., creer=False)` (le lanceur ne
     fabrique JAMAIS de cle en passant), envoyee sans aucun secret ;
  4. TPM indisponible : secret statique de l'identite echange au hub, et c'est DIT ;
  5. ni l'un ni l'autre : refus (rc 4) -- jamais le maitre, jamais un jeton invente ;
  6. stdout ne porte QUE le jeton ; stderr dit le chemin, jamais une valeur.
"""
from __future__ import annotations

import importlib
import importlib.util
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IDENT = "SERVICE_NR_LANCEUR"
JETON = "jeton-court-de-test-lanceur"


def _outil():
    spec = importlib.util.spec_from_file_location("nr_jeton_lanceur", ROOT / "tools/forge_jeton_lanceur.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def banc(monkeypatch):
    at = importlib.import_module("nokido_agent.app.forge_auth_tokens")
    fi = importlib.import_module("nokido_agent.app.forge_integrity")
    cred = importlib.import_module("nokido_agent.app.forge_agent_credential")
    tpm = importlib.import_module("nokido_agent.app.forge_persona_tpm")
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    o = _outil()
    registre = {IDENT: fi.IntegrityRing.COLLAB}
    monkeypatch.setattr(at, "_agents_connus", lambda: list(registre))
    monkeypatch.setattr(at, "_ring_de", lambda r: registre.get(r.upper(), fi.IntegrityRing.UNTRUSTED))
    monkeypatch.setattr(cred, "_sous_system", lambda: True)
    signes: list = []
    monkeypatch.setattr(tpm, "sign", lambda payload, nom=None, creer=True:
                        signes.append((payload, nom, creer)) or b"\x0a\x0b")
    envoyes: list = []
    monkeypatch.setattr(o, "_login_par_le_hub", lambda corps: envoyes.append(corps) or JETON)
    statiques: list = []
    monkeypatch.setattr(cred, "_statique", lambda agent: statiques.append(agent) or "")
    monkeypatch.setattr(cred, "_echanger_par_le_hub", lambda agent, s: "")
    lus: list = []

    def _guichet_enregistreur(k, required=False):
        lus.append(k)            # rien n'est lu pour de vrai : on enregistre la DEMANDE
        return None

    monkeypatch.setattr(fs, "get_secret", _guichet_enregistreur)
    return o, registre, fi, cred, tpm, signes, envoyes, statiques, lus


def test_hors_system_il_refuse(banc, monkeypatch, capsys):
    o, _r, _fi, cred, *_ = banc
    monkeypatch.setattr(cred, "_sous_system", lambda: False)
    rc = o.main([IDENT])
    sortie = capsys.readouterr()
    assert (rc, sortie.out) == (2, "")


def test_identite_inconnue_ou_ring_owner_refusee(banc, capsys):
    o, registre, fi, *_ = banc
    rc_inconnu = o.main(["IDENTITE_ABSENTE_DU_REGISTRE"])
    registre[IDENT] = fi.IntegrityRing.DEV
    rc_owner = o.main([IDENT])
    sortie = capsys.readouterr()
    assert (rc_inconnu, rc_owner, sortie.out) == (3, 3, "")


def test_le_chemin_tpm_signe_une_assertion_sans_aucun_secret(banc, capsys):
    o, _r, _fi, _cred, _tpm, signes, envoyes, statiques, _lus = banc
    rc = o.main([IDENT])
    sortie = capsys.readouterr()
    assert (rc, sortie.out) == (0, JETON + "\n")
    payload, nom, creer = signes[0]
    corps = envoyes[0]
    ident, horodatage = payload.decode().split(":", 1)
    forme = (ident, nom, creer, corps.get("role_id"), corps.get("signature"),
             "secret_id" in corps, abs(float(horodatage) - time.time()) < 60,
             float(corps.get("timestamp")) == float(horodatage))
    assert forme == (IDENT, None, False, IDENT, "0a0b", False, True, True)
    assert statiques == []
    assert "TPM" in sortie.err and JETON not in sortie.err


def test_sans_tpm_le_secret_statique_sert_et_c_est_dit(banc, monkeypatch, capsys):
    o, _r, _fi, cred, tpm, *_ = banc
    monkeypatch.setattr(tpm, "sign", lambda payload, nom=None, creer=True: None)
    monkeypatch.setattr(cred, "_statique", lambda agent: "statique-de-test")
    monkeypatch.setattr(cred, "_echanger_par_le_hub", lambda agent, s: JETON)
    rc = o.main([IDENT])
    sortie = capsys.readouterr()
    assert (rc, sortie.out) == (0, JETON + "\n")
    assert "statique" in sortie.err.lower() and "statique-de-test" not in sortie.err


def test_ni_tpm_ni_statique_refus_et_jamais_le_maitre(banc, monkeypatch, capsys):
    o, _r, _fi, _cred, tpm, _s, _e, _st, lus = banc
    monkeypatch.setattr(tpm, "sign", lambda payload, nom=None, creer=True: None)
    rc = o.main([IDENT])
    sortie = capsys.readouterr()
    assert (rc, sortie.out) == (4, "")
    assert "FORGE_MCP_TOKEN" not in lus
