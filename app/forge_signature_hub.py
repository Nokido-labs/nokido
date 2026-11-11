"""forge_signature_hub.py - signature des jetons emis par le hub : JWS compact ES256, cle TPM ou logicielle.

E9 du plan docs/PLAN_OAUTH_MCP_HUB_20261102.md. Owner 2/11 : « passe de HMAC a ECDSA pour TPM ; si un algo plus
fort existe utilise-le, mais pense a la compatibilite Linux et macOS » ; « reste conforme RFC ».

POURQUOI ES256 (et pas Ed25519 ni ES384). Seule courbe COMMUNE au TPM 2.0 Windows (fournisseur CNG « Microsoft
Platform Crypto Provider »), au TPM 2.0 Linux et a la Secure Enclave de macOS : P-256. Ed25519 n'existe dans aucun
de ces composants ; P-384 est optionnel selon la puce et absent de la Secure Enclave. L'en-tete porte `alg` et `kid`
(empreinte RFC 7638) : une puce P-384 pourra signer en ES384 plus tard sans casser les verificateurs.

POURQUOI PAS UN NOUVEAU MECANISME TPM. La cle materielle est celle de `forge_persona_tpm` (`sign` rend deja R||S sur
64 octets, le format JWS ES256 ; `cle_publique_jwk` exporte la publique). Ce module n'ajoute que l'enveloppe JWS
(RFC 7515), la verification par cle publique (logicielle, donc multi-OS) et le repli logiciel DIT.

REPLI LOGICIEL (Linux, macOS, pas de TPM, compte sans acces). Cle P-256 generee une fois et gardee AU COFFRE
(`forge_secrets`), jamais dans un fichier. L'origine est exposee (`origine` = tpm | logiciel) : un repli silencieux
ferait croire a une racine materielle qui n'existe pas.

VERIFICATION STRICTE (RFC 8725 §2.1, BCP JWT) : `alg` doit valoir EXACTEMENT ES256 -- `none`, `HS256` (cle publique
prise pour secret HMAC) et tout autre algorithme sont refuses avant meme de lire la signature.
NR : tests/nr/test_signature_hub_es256_nr.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/signature-hub : jetons du hub en JWS ES256, cle TPM (forge_persona_tpm) ou coffre"

import base64
import hashlib
import json
import logging
from typing import Callable, Optional

_LOG = logging.getLogger("Nokido.SignatureHub")

ALG = "ES256"
TYP = "at+jwt"                       # RFC 9068 §2.1 : jeton d'acces OAuth au format JWT
_PREFIXE_COFFRE = "NOKIDO_HUB_SIGNATURE_"


def _b64u(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _b64u_dec(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def empreinte_jwk(jwk: dict) -> str:
    """RFC 7638 §3.2 : SHA-256 du JSON canonique des membres requis (crv, kty, x, y) pour une cle EC."""
    canon = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":"), sort_keys=True)
    return _b64u(hashlib.sha256(canon.encode("utf-8")).digest())


class SignataireHub:
    """Signe R||S (64 octets) ; `origine` dit d'ou vient la cle."""

    def __init__(self, origine: str, jwk: dict, signer: Callable[[bytes], Optional[bytes]]):
        self.origine = origine
        self._jwk = dict(jwk)
        self._signer = signer
        self.kid = empreinte_jwk(self._jwk)

    def jwk_publique(self) -> dict:
        """JWK publique nue (kty, crv, x, y) -- jamais de partie privee."""
        return dict(self._jwk)

    def signer(self, octets: bytes) -> bytes:
        sig = self._signer(octets)
        if not sig or len(sig) != 64:
            raise RuntimeError("signature %s indisponible ou mal formee (%s octets)"
                               % (self.origine, len(sig) if sig else 0))
        return sig


def _signataire_logiciel(nom_cle: str, lire, ecrire) -> SignataireHub:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    nom = _PREFIXE_COFFRE + nom_cle.upper().replace("-", "_")
    pem = lire(nom)
    if pem:
        cle = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    else:
        cle = ec.generate_private_key(ec.SECP256R1())
        ecrire(nom, cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()).decode("ascii"))
        _LOG.warning("[signature-hub] cle LOGICIELLE P-256 creee au coffre (%s) : aucune racine materielle", nom)
    pub = cle.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": _b64u(pub.x.to_bytes(32, "big")), "y": _b64u(pub.y.to_bytes(32, "big"))}

    def signer(octets: bytes) -> bytes:
        r, s = decode_dss_signature(cle.sign(octets, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return SignataireHub("logiciel", jwk, signer)


def _module_tpm():
    """La couche TPM existante (point d'injection des tests)."""
    from nokido_agent.app import forge_persona_tpm as T
    return T


def _fabrique_cle_tpm(identite: str):
    """Cle TPM de l'identite DECLAREE, par `forge_dpop.CleTpm` -- construite SEULEMENT pour le porteur du credential
    PROPRE de l'identite (`_porteur_autorise`, temps constant au coffre), sinon PermissionError.

    3/11 : contrat de la sentinelle test_tpm_isolation_nest_pas_non_exportabilite_nr -- la non-exportabilite d'une
    cle TPM n'est PAS une isolation entre appelants ; l'autorisation precede la signature. Ce module ne touche donc
    jamais la signature TPM brute lui-meme. Creation et droits de la cle : gestes admin de forge_tpm_agent_keys.
    """
    from nokido_agent.app import forge_dpop as _dp
    from nokido_agent.app.forge_secrets import get_secret

    # magasin MACHINE : la cle de l'identite y vit (creee par forge_tpm_agent_keys --create, admin) ; choisi PAR APPEL,
    # jamais par la variable globale (qui basculerait les autres cles du hub multitache)
    return _dp.CleTpm(identite, get_secret("FORGE_TOKEN_%s" % identite), machine=True)


def _signataire_tpm_identite(identite: str) -> Optional[SignataireHub]:
    """Signataire adosse a la cle TPM de l'identite declaree (DER de CleTpm reconverti en R||S pour ES256)."""
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    T = _module_tpm()
    if not T.tpm_available():
        return None
    cle = _fabrique_cle_tpm(identite)              # leve si l'appelant ne porte pas le credential de l'identite
    pub = cle.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "x": _b64u(pub.x.to_bytes(32, "big")), "y": _b64u(pub.y.to_bytes(32, "big"))}

    def signer(octets: bytes) -> bytes:
        r, s = decode_dss_signature(cle.sign(octets))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    return SignataireHub("tpm", jwk, signer)


def _signataire_tpm(nom_cle: str) -> Optional[SignataireHub]:
    T = _module_tpm()

    if not T.tpm_available():
        return None
    if T.sign(b"amorce", nom=nom_cle, creer=True) is None:       # cree la cle persistee si absente
        return None
    jwk, raison = T.cle_publique_jwk(nom_cle)
    if jwk is None:
        _LOG.warning("[signature-hub] cle TPM %s : publique non exportable (%s)", nom_cle, raison)
        return None
    return SignataireHub("tpm", jwk, lambda octets: T.sign(octets, nom=nom_cle, creer=False))


def obtenir_signataire(nom_cle: Optional[str] = None, tpm: Optional[bool] = None,
                       lire: Optional[Callable] = None, ecrire: Optional[Callable] = None,
                       identite: Optional[str] = None) -> SignataireHub:
    """tpm=None : TPM si disponible, sinon repli logiciel DIT ; tpm=True : TPM exige ; tpm=False : logiciel.

    PRODUCTION : `identite="HUB"` (cle de l'identite declaree, jamais creee par le hub). `nom_cle` : cle UTILISATEUR
    libre, reservee aux mesures et aux tests (creee a la volee dans le magasin du compte appelant).
    """
    if identite is None and nom_cle is None:
        identite = "HUB"
    etiquette = identite or nom_cle
    if tpm is not False:
        t = None
        try:
            t = _signataire_tpm_identite(identite) if identite else _signataire_tpm(nom_cle)
        except Exception as exc:  # noqa: BLE001 - dit, puis repli ou refus
            _LOG.warning("[signature-hub] TPM illisible (%s)", type(exc).__name__)
        if t is not None:
            return t
        if tpm is True:
            raise RuntimeError("signature TPM exigee mais indisponible pour ce compte (%s)" % etiquette)
        _LOG.warning("[signature-hub] TPM indisponible : repli sur une cle LOGICIELLE au coffre (%s)", etiquette)
    if lire is None or ecrire is None:
        from nokido_agent.app.forge_secrets import get_secret, set_secret
        lire, ecrire = lire or get_secret, ecrire or set_secret
    return _signataire_logiciel(etiquette, lire, ecrire)


def emettre_jws(charge: dict, signataire: SignataireHub) -> str:
    """JWS compact (RFC 7515 §7.1), en-tete {alg: ES256, typ: at+jwt, kid}."""
    entete = {"alg": ALG, "typ": TYP, "kid": signataire.kid}
    entree = _b64u(json.dumps(entete, separators=(",", ":")).encode()) + "." + \
        _b64u(json.dumps(charge, separators=(",", ":"), sort_keys=True).encode())
    return entree + "." + _b64u(signataire.signer(entree.encode("ascii")))


def verifier_jws(jeton: str, jwks: dict) -> tuple:
    """(charge, None) ou (None, motif). `jwks` : {kid: jwk publique}. alg EXACTEMENT ES256 (RFC 8725 §2.1)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    if not isinstance(jeton, str) or jeton.count(".") != 2:
        return None, "jeton mal forme"
    e64, c64, s64 = jeton.split(".")
    try:
        entete = json.loads(_b64u_dec(e64))
    except Exception:  # noqa: BLE001
        return None, "en-tete illisible"
    if not isinstance(entete, dict) or entete.get("alg") != ALG:
        return None, "alg refuse (%r) : ES256 exige" % (entete.get("alg") if isinstance(entete, dict) else None)
    jwk = jwks.get(entete.get("kid"))
    if not jwk:
        return None, "kid inconnu"
    try:
        sig = _b64u_dec(s64)
    except Exception:  # noqa: BLE001
        return None, "signature illisible"
    if len(sig) != 64:
        return None, "signature ES256 de %d octets (64 attendus)" % len(sig)
    try:
        pub = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64u_dec(jwk["x"]), "big"),
                                            int.from_bytes(_b64u_dec(jwk["y"]), "big"),
                                            ec.SECP256R1()).public_key()
        pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                   (e64 + "." + c64).encode("ascii"), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return None, "signature invalide"
    except Exception as exc:  # noqa: BLE001
        return None, "verification impossible (%s)" % type(exc).__name__
    try:
        charge = json.loads(_b64u_dec(c64))
    except Exception:  # noqa: BLE001
        return None, "charge illisible"
    return (charge, None) if isinstance(charge, dict) else (None, "charge inattendue")
