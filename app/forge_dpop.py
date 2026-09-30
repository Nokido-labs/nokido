"""Preuve de possession applicative (DPoP, RFC 9449).

__FORGE_COLOR__ = "immunitaire/reconnaissance-du-soi"

POURQUOI CELUI-CI ET PAS LA RFC 8705. Le quatrieme durcissement demande de
LIER un jeton a son porteur, pour qu'un jeton vole ne serve a personne d'autre.
La RFC 8705 (certificate-bound access tokens) realise ce lien par mTLS : elle
suppose un canal TLS avec certificat CLIENT. Le corps n'en a pas aujourd'hui
sur `:8766`, et brancher un garde sur un signal que personne n'emet est le
motif exact qui a laisse le frein d'insuline inactif depuis son ecriture.
La RFC 9449 obtient le meme lien AU NIVEAU APPLICATIF, sans TLS : c'est donc
elle qui est implementee ici, et le choix est un choix, pas un repli.

CE QUE LA RFC EXIGE, et qui est verifie ici (§4.3, dans son ordre) :
  1. exactement UN en-tete DPoP ;
  2. une valeur qui est un JWT bien forme ;
  3. tous les champs requis presents ;
  4. `typ` vaut `dpop+jwt` ;
  5. `alg` est ASYMETRIQUE -- ni `none`, ni un MAC. Nokido signe ses jetons
     d'acces en HMAC ; la preuve, elle, ne le peut pas, et ce module ne
     propose aucun repli symetrique. Un repli qui viole la RFC serait pire
     qu'une absence de preuve, parce qu'il en aurait l'apparence ;
  6. la signature se verifie avec la cle publique portee par `jwk` ;
  7. `jwk` ne contient AUCUNE partie privee ;
  8. `htm` egale la methode HTTP ;
  9. `htu` egale l'URI, QUERY ET FRAGMENT RETIRES ;
 10. le nonce, quand le serveur en a fourni un ;
 11. `iat` tombe dans une fenetre courte ;
 12. `jti` n'a pas deja ete vu dans cette fenetre (anti-rejeu) ;
 13. `ath` egale le hachage du jeton d'acces presente.

TROIS ETATS, JAMAIS DEUX. `verifier()` rend LIEE / REFUSEE / INVERIFIABLE.
Confondre « je n'ai pas pu verifier » avec « c'est refuse » ferait tomber le
corps entier le jour ou la bibliotheque manque ; les confondre dans l'autre
sens laisserait passer ce qu'on n'a pas regarde. `est_lie()` repond de meme
par True / False / None, parce que la RFC §6 demande au serveur de ressources
de pouvoir dire DE FACON FIABLE si un jeton est lie -- et « je ne sais pas »
est une reponse fiable, contrairement a un `False` invente.

CE QUE CE MODULE NE FAIT PAS. Il ne s'arme pas tout seul : tant qu'aucun
appelant ne produit de preuve, aucun jeton n'est lie, et `couverture()` le dit
en clair plutot que de laisser croire a une protection. C'est la lecon du
garde dont personne n'emettait le signal.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `CleTpm` — Cle DPoP adossee au TPM, avec l'interface attendue par `creer_preuve`.
- `creer_preuve_tpm` — Preuve DPoP signee par la cle TPM de `agent_id`, liee a `jeton_acces` (ath).
- `decision_admin_tpm` — Verdict TPM d'un appel admin par un ORGANE. -> {autorise, etat, raison, applique}.
- `jkt_tpm_enregistre` — Empreinte (RFC 7638) de la cle TPM de l'agent, telle qu'ENREGISTREE au registre.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "ETATS",
    "ALGOS_INTERDITS",
    "b64u",
    "b64u_decode",
    "thumbprint",
    "cle_locale",
    "jwk_public",
    "hacher_jeton",
    "creer_preuve",
    "verifier",
    "est_lie",
    "couverture",
]

# Les trois etats. `INVERIFIABLE` n'est pas un refus : c'est l'aveu que
# l'instrument manque (bibliotheque absente, preuve illisible autrement que
# par sa faute). Un garde qui transforme son propre aveuglement en verdict
# fabrique des faux negatifs indetectables.
ETATS = ("LIEE", "REFUSEE", "INVERIFIABLE")

# RFC 9449 §4.2 : `alg` MUST NOT be `none` nor a MAC identifier.
ALGOS_INTERDITS = frozenset({"none", "HS256", "HS384", "HS512"})

_FENETRE_IAT_S = 300.0     # §11.1 : « a relatively brief period »
_MAX_JTI = 4096            # bornage memoire de l'anti-rejeu

_jti_vus: Dict[str, float] = {}
_verrou = threading.Lock()
_cle_locale: Any = None
_compteur = {"lie": 0, "refuse": 0, "inverifiable": 0, "sans_preuve": 0}


def b64u(donnees: bytes) -> str:
    """base64url SANS padding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(donnees).decode("ascii").rstrip("=")


def b64u_decode(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def thumbprint(jwk: Dict[str, Any]) -> str:
    """Empreinte SHA-256 d'une JWK (RFC 7638), telle que `cnf.jkt` l'attend.

    La RFC impose : SEULS les membres requis, tries lexicographiquement, JSON
    sans espace superflu. Ajouter `use` ou `kid` changerait l'empreinte et le
    lien ne se retrouverait plus -- d'ou la construction explicite ci-dessous
    plutot qu'une serialisation de l'objet entier.
    """
    kty = jwk.get("kty")
    if kty == "EC":
        requis = {"crv": jwk["crv"], "kty": "EC", "x": jwk["x"], "y": jwk["y"]}
    elif kty == "RSA":
        requis = {"e": jwk["e"], "kty": "RSA", "n": jwk["n"]}
    elif kty == "OKP":
        requis = {"crv": jwk["crv"], "kty": "OKP", "x": jwk["x"]}
    else:
        raise ValueError("kty non supporte pour l'empreinte : %r" % (kty,))
    canonique = json.dumps(requis, sort_keys=True, separators=(",", ":"))
    return b64u(hashlib.sha256(canonique.encode("utf-8")).digest())


def cle_locale():
    """Cle privee P-256 de CE processus, generee au premier besoin.

    Elle n'est volontairement PAS persistee : dans le modele DPoP, le client
    presente sa cle publique au moment de l'echange et le jeton emis porte son
    empreinte. Une cle qui vit le temps du processus lie donc le jeton au
    processus, ce qui est exactement l'effet recherche -- et supprime le
    probleme de garder un secret asymetrique au repos.
    """
    global _cle_locale
    with _verrou:
        if _cle_locale is None:
            from cryptography.hazmat.primitives.asymmetric import ec

            _cle_locale = ec.generate_private_key(ec.SECP256R1())
        return _cle_locale


def jwk_public(cle=None) -> Dict[str, str]:
    """JWK publique (EC P-256). NE CONTIENT AUCUNE PARTIE PRIVEE (§4.2)."""
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401

    cle = cle or cle_locale()
    nombres = cle.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64u(nombres.x.to_bytes(32, "big")),
        "y": b64u(nombres.y.to_bytes(32, "big")),
    }


def hacher_jeton(jeton_acces: str) -> str:
    """`ath` : base64url(SHA-256(ASCII(jeton))) -- RFC 9449 §4.2."""
    return b64u(hashlib.sha256(jeton_acces.encode("ascii")).digest())


def _uri_normalisee(uri: str) -> str:
    """`htu` : l'URI SANS query ni fragment (§4.3 point 9)."""
    return uri.split("#", 1)[0].split("?", 1)[0]


def _der_vers_jws(signature: bytes) -> bytes:
    """ES256 attend R||S sur 64 octets ; `cryptography` produit du DER.

    Piege classique et silencieux : une signature DER passee telle quelle est
    syntaxiquement une signature, et elle echoue a la verification chez tout
    tiers conforme. La conversion est obligatoire, pas cosmetique.
    """
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
    )

    r, s = decode_dss_signature(signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _jws_vers_der(signature: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.utils import (
        encode_dss_signature,
    )

    if len(signature) != 64:
        raise ValueError("signature ES256 de longueur %d, attendu 64"
                         % len(signature))
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    return encode_dss_signature(r, s)


# ─── Preuve DPoP ADOSSEE AU TPM (2026-09-24, chantier d'authentification) ────────────
# `creer_preuve` signait avec une cle LOGICIELLE. Ici la cle est la cle TPM MACHINE de
# l'agent : la privee ne quitte jamais le TPM ; `NCryptSignHash` rend deja r||s sur 64
# octets, le format JWS ES256.
#
# INVARIANT (sentinelle test_tpm_isolation_nest_pas_non_exportabilite_nr) : `sign_as`
# signe au nom de QUI ON LUI DIT. L'AUTORISATION se fait donc ICI, AVANT : seul le
# porteur du credential PROPRE de l'agent (FORGE_TOKEN_<AGENT>, compare en temps
# constant au coffre) obtient sa signature. Le maitre n'ouvre PAS la cle d'un organe
# (AUTH-2). Limite DITE : un process qui peut lire ce credential au coffre peut signer
# -- attribution forte, pas isolation inter-process (cles MACHINE).


def _porteur_autorise(agent_id: str, jeton_acces: Optional[str]) -> bool:
    """Vrai si `jeton_acces` EST le credential propre de `agent_id` (temps constant)."""
    if not jeton_acces or not agent_id:
        return False
    try:
        import hmac

        from nokido_agent.app.forge_m2m_protocol import _resoudre_agent
        from nokido_agent.app.forge_secrets import get_secret

        canon, _surface = _resoudre_agent(agent_id)
        attendu = get_secret("FORGE_TOKEN_%s" % canon) if canon else ""
    except Exception:  # noqa: BLE001 -- coffre ou registre illisible : REFUS, jamais ouverture
        return False
    return bool(attendu) and hmac.compare_digest(str(jeton_acces), str(attendu))


class CleTpm:
    """Cle DPoP adossee au TPM, avec l'interface attendue par `creer_preuve`
    (`sign(donnees, algo) -> DER`, `public_key()`). Construite SEULEMENT pour le porteur
    du credential propre de l'agent."""

    def __init__(self, agent_id: str, jeton_acces: Optional[str]):
        if not _porteur_autorise(agent_id, jeton_acces):
            raise PermissionError(
                "signature TPM refusee : l'appelant ne porte pas le credential PROPRE "
                "de %s" % str(agent_id)[:40])
        from nokido_agent.app import forge_persona_tpm as _tpm

        jwk, raison = _tpm.cle_publique_jwk_agent(agent_id)
        if not jwk:
            raise RuntimeError("cle TPM de %s inutilisable : %s" % (agent_id, raison))
        self.agent_id, self._jwk, self._tpm = agent_id, jwk, _tpm

    def sign(self, donnees: bytes, _algo=None) -> bytes:
        brut = self._tpm.sign_as(self.agent_id, donnees)
        if not brut or len(brut) != 64:
            raise RuntimeError("signature TPM refusee ou de forme inattendue")
        return _jws_vers_der(brut)

    def public_key(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64u_decode(self._jwk["x"]), "big"),
            int.from_bytes(b64u_decode(self._jwk["y"]), "big"),
            ec.SECP256R1()).public_key()

    @property
    def jkt(self) -> str:
        return thumbprint(self._jwk)


def creer_preuve_tpm(agent_id: str, methode: str, uri: str, jeton_acces: str,
                     nonce: Optional[str] = None) -> str:
    """Preuve DPoP signee par la cle TPM de `agent_id`, liee a `jeton_acces` (ath)."""
    return creer_preuve(methode, uri, jeton_acces, nonce, cle=CleTpm(agent_id, jeton_acces))


def jkt_tpm_enregistre(agent_id: str) -> Optional[str]:
    """Empreinte (RFC 7638) de la cle TPM de l'agent, telle qu'ENREGISTREE au registre
    d'identite au provisionnement. La provenance s'ETABLIT par le registre ; elle ne se
    DECLARE jamais par le client (piege nomme par l'owner le 21/09). None = non enregistree."""
    try:
        from pathlib import Path

        from nokido_agent.app.forge_m2m_protocol import _resoudre_agent

        canon, _surface = _resoudre_agent(agent_id)
        reg = json.loads((Path(__file__).resolve().parents[1] / "config"
                          / "agent_identities.json").read_text(encoding="utf-8"))
        return ((reg.get("agents") or {}).get(canon) or {}).get("tpm_jkt") or None
    except Exception:  # noqa: BLE001 -- registre illisible : aucune empreinte, donc aucune preuve LIEE
        return None


# ─── Politique des routes d'ADMINISTRATION (2026-09-24) ──────────────────────────────
# Operation sensible -> garantie forte : un ORGANE qui franchit une route admin avec son
# credential propre doit aussi PROUVER la possession de sa cle TPM (DPoP, empreinte
# ENREGISTREE au registre). OBSERVATION par defaut (on journalise ce qui serait refuse,
# pour mesurer le bruit avant d'armer) ; APPLIQUE si LAFORGE_ADMIN_TPM_ENFORCE=1 dans
# l'environnement du hub -- geste owner, jamais un fichier a portee de l'agent.
_JOURNAL_ADMIN = None


def _journal_admin_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "sandbox" / "authz_tpm_admin.jsonl"


def _journaliser_preuve_admin(trace: Dict[str, Any]) -> None:
    try:
        p = _journal_admin_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > 5_000_000:
            p.replace(p.with_suffix(".jsonl.1"))
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  # muet-ok : un journal ne casse jamais une decision
        pass


def decision_admin_tpm(preuve: str, methode: str, chemin: str, agent: str,
                       jeton: str, environ=None) -> Dict[str, Any]:
    """Verdict TPM d'un appel admin par un ORGANE. -> {autorise, etat, raison, applique}.

    `chemin` vient de scope['path'] (CVE-2026-48710 : jamais de l'URL reconstruite depuis
    Host). Les alias de boucle locale sont essayes : l'`htu` signe par le client doit
    correspondre a l'un d'eux. En mode APPLIQUE, tout ce qui n'est pas LIEE est refuse
    (UNKNOWN = DENY) ; en OBSERVATION, rien n'est refuse mais TOUT est journalise.
    """
    import os
    env = os.environ if environ is None else environ
    applique = (env.get("LAFORGE_ADMIN_TPM_ENFORCE") or "").strip() == "1"
    jkt = jkt_tpm_enregistre(agent)
    if not jkt:
        etat, raison = "NON_ENREGISTRE", "aucune empreinte TPM enregistree pour %s" % agent
    elif not preuve:
        etat, raison = "INVERIFIABLE", "aucune preuve presentee"
    else:
        etat, raison = "REFUSEE", "aucun alias de boucle locale ne correspond"
        for hote in ("127.0.0.1", "localhost"):
            etat, raison = verifier(preuve, methode, "http://%s:8766%s" % (hote, chemin),
                                    jeton, jkt_attendu=jkt)
            if etat == "LIEE" or "htu" not in raison:
                break
    autorise = etat == "LIEE" or not applique
    _journaliser_preuve_admin({"ts": time.time(), "agent": agent, "methode": methode,
                               "chemin": chemin, "etat": etat, "raison": raison,
                               "applique": applique, "autorise": autorise})
    return {"autorise": autorise, "etat": etat, "raison": raison, "applique": applique}


def creer_preuve(methode: str, uri: str, jeton_acces: Optional[str] = None,
                 nonce: Optional[str] = None, cle=None) -> str:
    """Preuve DPoP pour cette requete precise (§4.2).

    Seuls la METHODE et l'URI sont couverts : c'est le choix de la RFC, qui
    signe « juste assez » de la requete pour prouver la possession sans
    dependre de details de transport que les intermediaires reecrivent.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    cle = cle or cle_locale()
    entete = {"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk_public(cle)}
    charge: Dict[str, Any] = {
        "jti": secrets.token_urlsafe(16),
        "htm": methode.upper(),
        "htu": _uri_normalisee(uri),
        "iat": int(time.time()),
    }
    if jeton_acces:
        charge["ath"] = hacher_jeton(jeton_acces)
    if nonce:
        charge["nonce"] = nonce
    signe = "%s.%s" % (
        b64u(json.dumps(entete, separators=(",", ":")).encode()),
        b64u(json.dumps(charge, separators=(",", ":")).encode()),
    )
    brut = cle.sign(signe.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    return "%s.%s" % (signe, b64u(_der_vers_jws(brut)))


def _oublier_vieux_jti(maintenant: float) -> None:
    perimes = [j for j, t in _jti_vus.items()
               if maintenant - t > _FENETRE_IAT_S]
    for j in perimes:
        _jti_vus.pop(j, None)
    if len(_jti_vus) > _MAX_JTI:
        for j in sorted(_jti_vus, key=_jti_vus.get)[:len(_jti_vus) - _MAX_JTI]:
            _jti_vus.pop(j, None)


def verifier(preuve: str, methode: str, uri: str,
             jeton_acces: Optional[str] = None,
             jkt_attendu: Optional[str] = None,
             nonce_attendu: Optional[str] = None) -> Tuple[str, str]:
    """Verifie une preuve DPoP. Rend (etat, raison) -- etat dans ETATS.

    La raison est destinee aux journaux : elle ne contient JAMAIS le jeton
    d'acces ni la preuve, seulement ce qui a tranche.
    """
    maintenant = time.time()
    if not preuve:
        _compteur["sans_preuve"] += 1
        return "INVERIFIABLE", "aucune preuve presentee"
    try:
        from cryptography.hazmat.primitives import hashes  # noqa: F401
    except Exception as exc:  # instrument absent != preuve invalide
        _compteur["inverifiable"] += 1
        return "INVERIFIABLE", "bibliotheque absente (%s)" % type(exc).__name__

    def _refus(raison: str) -> Tuple[str, str]:
        _compteur["refuse"] += 1
        return "REFUSEE", raison

    parts = preuve.split(".")
    if len(parts) != 3:
        return _refus("JWT malforme : %d segments" % len(parts))
    try:
        entete = json.loads(b64u_decode(parts[0]))
        charge = json.loads(b64u_decode(parts[1]))
        signature = b64u_decode(parts[2])
    except Exception as exc:
        return _refus("segments illisibles (%s)" % type(exc).__name__)
    if not isinstance(entete, dict) or not isinstance(charge, dict):
        return _refus("entete ou charge n'est pas un objet")

    if entete.get("typ") != "dpop+jwt":
        return _refus("typ=%r, attendu dpop+jwt" % (entete.get("typ"),))
    alg = entete.get("alg")
    if alg in ALGOS_INTERDITS or not alg:
        return _refus("alg=%r interdit : la preuve doit etre asymetrique" % (alg,))
    if alg != "ES256":
        return _refus("alg=%r non supporte par cette implementation" % (alg,))

    jwk = entete.get("jwk")
    if not isinstance(jwk, dict):
        return _refus("jwk absente de l'entete")
    # §4.2 : la JWK NE DOIT PAS porter de partie privee. `d` est le scalaire
    # prive EC ; les membres RSA prives sont refuses de la meme facon.
    privees = {"d", "p", "q", "dp", "dq", "qi", "k"} & set(jwk)
    if privees:
        return _refus("jwk porte une partie privee : %s" % sorted(privees))

    for champ in ("jti", "htm", "htu", "iat"):
        if champ not in charge:
            return _refus("champ requis absent : %s" % champ)

    if str(charge["htm"]).upper() != methode.upper():
        return _refus("htm ne correspond pas a la methode")
    if _uri_normalisee(str(charge["htu"])) != _uri_normalisee(uri):
        return _refus("htu ne correspond pas a l'URI")

    try:
        iat = float(charge["iat"])
    except Exception:
        return _refus("iat illisible")
    if abs(maintenant - iat) > _FENETRE_IAT_S:
        return _refus("iat hors fenetre (%.0f s d'ecart)" % (maintenant - iat))

    if nonce_attendu is not None and charge.get("nonce") != nonce_attendu:
        return _refus("nonce absent ou different de celui fourni")

    if jeton_acces:
        attendu = hacher_jeton(jeton_acces)
        if charge.get("ath") != attendu:
            return _refus("ath ne correspond pas au jeton presente")
    elif "ath" in charge:
        return _refus("ath presente sans jeton d'acces")

    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        pub = ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64u_decode(jwk["x"]), "big"),
            int.from_bytes(b64u_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        ).public_key()
        pub.verify(_jws_vers_der(signature),
                   ("%s.%s" % (parts[0], parts[1])).encode("ascii"),
                   ec.ECDSA(hashes.SHA256()))
    except Exception as exc:
        return _refus("signature invalide (%s)" % type(exc).__name__)

    # Anti-rejeu APRES la signature : un `jti` ne doit etre consomme que s'il
    # provient d'une preuve authentique, sinon n'importe qui pourrait brûler
    # les identifiants d'un tiers en envoyant des preuves forgees.
    with _verrou:
        _oublier_vieux_jti(maintenant)
        if charge["jti"] in _jti_vus:
            return _refus("jti deja vu : rejeu")
        _jti_vus[charge["jti"]] = maintenant

    if jkt_attendu is not None:
        try:
            reel = thumbprint(jwk)
        except Exception as exc:
            _compteur["inverifiable"] += 1
            return "INVERIFIABLE", "empreinte incalculable (%s)" % type(exc).__name__
        if reel != jkt_attendu:
            return _refus("la cle ne correspond pas au cnf.jkt du jeton")

    _compteur["lie"] += 1
    return "LIEE", "preuve valide"


def est_lie(charge_jeton: Any) -> Optional[bool]:
    """Ce jeton est-il lie a une cle ? True / False / None (RFC 9449 §6).

    None n'est pas une commodite : c'est le cas ou la charge n'est pas
    lisible. Repondre `False` la-dessus reviendrait a affirmer une absence
    qu'on n'a pas pu constater.
    """
    if charge_jeton is None:
        return None
    cnf = None
    if isinstance(charge_jeton, dict):
        cnf = charge_jeton.get("cnf")
    else:
        cnf = getattr(charge_jeton, "cnf", None)
        if cnf is None and not hasattr(charge_jeton, "__dict__"):
            return None
    if cnf is None:
        return False
    if isinstance(cnf, dict) and cnf.get("jkt"):
        return True
    return False


def couverture() -> Dict[str, Any]:
    """Etat REEL du lien, pour ne pas confondre un mecanisme et son effet.

    Tant que `lie` vaut 0, aucune requete n'est liee : le module existe, il ne
    protege encore rien. C'est precisement ce qu'un audit doit pouvoir lire.
    """
    total = sum(_compteur.values())
    return {
        "verifications": total,
        **dict(_compteur),
        "arme": _compteur["lie"] > 0,
        "avertissement": (
            "Aucune preuve valide observee : le mecanisme est present mais SANS "
            "EFFET. Un mecanisme non cable est une dette de cablage, jamais une "
            "securite." if _compteur["lie"] == 0 else ""),
    }
