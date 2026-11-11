"""NR 2/11 — E9 du plan OAuth MCP : signature des jetons du hub en ES256 (owner : « passe de HMAC a ECDSA pour TPM,
plus fort si possible, compat Linux et macOS »).

Contrat (RFC 7515 JWS compact, RFC 7518 §3.4 ES256 = R||S sur 64 octets, RFC 7638 kid = empreinte JWK, RFC 9068
typ at+jwt) :
  * aller-retour signe/verifie avec la source LOGICIELLE (cle P-256 au coffre : Linux, macOS, pas de TPM) ;
  * charge alteree, kid inconnu, signature tronquee -> refus ;
  * confusion d'algorithme refusee : `alg: none`, `alg: HS256` (cle publique prise pour secret), tout alg != ES256 ;
  * la source est DITE (tpm | logiciel), jamais silencieuse ;
  * la source TPM n'est exercee que si NOKIDO_TEST_TPM=1 (aucune cle creee par la suite de tests).
"""
import base64
import json
import os

import pytest

from app import forge_signature_hub as S


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()


@pytest.fixture
def logiciel(monkeypatch):
    coffre = {}
    return S.obtenir_signataire(nom_cle="nokido-hub-test", tpm=False,
                                lire=coffre.get, ecrire=coffre.__setitem__)


def test_source_dite_et_kid_empreinte(logiciel):
    assert logiciel.origine == "logiciel"
    jwk = logiciel.jwk_publique()
    assert jwk["kty"] == "EC" and jwk["crv"] == "P-256" and "d" not in jwk
    assert logiciel.kid == S.empreinte_jwk(jwk)


def test_cle_logicielle_persistee_au_coffre():
    coffre = {}
    a = S.obtenir_signataire(nom_cle="k", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    b = S.obtenir_signataire(nom_cle="k", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    assert a.kid == b.kid and len(coffre) == 1


def test_aller_retour(logiciel):
    j = S.emettre_jws({"sub": "client-x", "aud": "nokido-hub"}, logiciel)
    entete = json.loads(base64.urlsafe_b64decode(j.split(".")[0] + "=="))
    assert entete == {"alg": "ES256", "typ": "at+jwt", "kid": logiciel.kid}
    charge, motif = S.verifier_jws(j, {logiciel.kid: logiciel.jwk_publique()})
    assert motif is None and charge["sub"] == "client-x"


def test_charge_alteree_refusee(logiciel):
    e, c, s = S.emettre_jws({"sub": "a"}, logiciel).split(".")
    falsifie = ".".join([e, _b64({"sub": "admin"}), s])
    assert S.verifier_jws(falsifie, {logiciel.kid: logiciel.jwk_publique()})[0] is None


def test_kid_inconnu_et_signature_tronquee(logiciel):
    j = S.emettre_jws({"sub": "a"}, logiciel)
    assert S.verifier_jws(j, {})[0] is None
    e, c, s = j.split(".")
    assert S.verifier_jws(".".join([e, c, s[:20]]), {logiciel.kid: logiciel.jwk_publique()})[0] is None


@pytest.mark.parametrize("alg", ["none", "HS256", "ES384", "RS256", "es256"])
def test_confusion_d_algorithme_refusee(logiciel, alg):
    j = S.emettre_jws({"sub": "a"}, logiciel)
    _, c, s = j.split(".")
    e = _b64({"alg": alg, "typ": "at+jwt", "kid": logiciel.kid})
    sig = "" if alg == "none" else s
    charge, motif = S.verifier_jws(".".join([e, c, sig]), {logiciel.kid: logiciel.jwk_publique()})
    assert charge is None and "alg" in motif


def _vraie_cle_logicielle():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def test_par_identite_la_cle_tpm_passe_par_CleTpm_autorisee(monkeypatch):
    # 3/11 : la cle du hub est celle de l'identite DECLAREE `HUB`, obtenue par forge_dpop.CleTpm -- construite
    # SEULEMENT pour le porteur du credential propre de HUB (_porteur_autorise), contrat de la sentinelle
    # test_tpm_isolation_nest_pas_non_exportabilite_nr. forge_signature_hub n'appelle jamais sign_as lui-meme.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    privee = _vraie_cle_logicielle()
    demandes = []

    class FausseCleTpm:                    # interface de forge_dpop.CleTpm : sign -> DER, public_key()
        def sign(self, donnees, _algo=None):
            return privee.sign(donnees, ec.ECDSA(hashes.SHA256()))

        def public_key(self):
            return privee.public_key()

    import types
    monkeypatch.setattr(S, "_module_tpm", lambda: types.SimpleNamespace(tpm_available=lambda: True))
    monkeypatch.setattr(S, "_fabrique_cle_tpm", lambda ident: demandes.append(ident) or FausseCleTpm())
    t = S.obtenir_signataire(identite="HUB", tpm=True)
    assert t.origine == "tpm" and demandes == ["HUB"]
    j = S.emettre_jws({"sub": "x"}, t)
    assert S.verifier_jws(j, {t.kid: t.jwk_publique()})[1] is None        # DER reconverti en R||S


def test_le_signataire_n_appelle_jamais_sign_as_directement():
    from pathlib import Path
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "sign_as(" not in src and "CleTpm(" in src


def test_par_identite_cle_tpm_refusee_repli_logiciel_dit(monkeypatch):
    def refus(ident):
        raise PermissionError("signature TPM refusee : l'appelant ne porte pas le credential PROPRE de HUB")
    import types
    monkeypatch.setattr(S, "_module_tpm", lambda: types.SimpleNamespace(tpm_available=lambda: True))
    monkeypatch.setattr(S, "_fabrique_cle_tpm", refus)
    coffre = {}
    t = S.obtenir_signataire(identite="HUB", lire=coffre.get, ecrire=coffre.__setitem__)
    assert t.origine == "logiciel" and list(coffre) == ["NOKIDO_HUB_SIGNATURE_HUB"]
    with pytest.raises(RuntimeError):
        S.obtenir_signataire(identite="HUB", tpm=True, lire=coffre.get, ecrire=coffre.__setitem__)


@pytest.mark.skipif(os.environ.get("NOKIDO_TEST_TPM") != "1", reason="source TPM exercee seulement sur demande")
def test_source_tpm_aller_retour():
    t = S.obtenir_signataire(nom_cle="nokido-hub-test-tpm", tpm=True)
    assert t.origine == "tpm"
    j = S.emettre_jws({"sub": "tpm"}, t)
    assert S.verifier_jws(j, {t.kid: t.jwk_publique()})[1] is None
