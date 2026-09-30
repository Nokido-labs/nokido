"""forge_cert_binding.py -- lier l'identite de TRANSPORT a l'identite APPLICATIVE.

Le mTLS prouve une chose et une seule : *ce client possede la cle privee de ce
certificat* (RFC 8705). Il ne dit RIEN de « ce certificat correspond bien a l'agent
VIBE de Nokido ». Ce module est le chainon manquant : il compare, pour une meme
requete, ce que dit le certificat, ce que dit le token, et ce que declare l'appelant.

Chaine verifiee (chaque maillon rend un etat, jamais un booleen) :

    certificat presente ──┬── EKU = clientAuth ?
                          ├── periode de validite courante ?
                          ├── SAN = urn:nokido:agent:<AGENT> ?
                          └── empreinte SHA-256
                                    │
    token ────────────────┬── signature + expiration        │
                          ├── sub == agent du certificat    │
                          ├── aud == ressource attendue     │
                          └── cnf.x5t#S256 ═════════════════╯  (RFC 8705 §3.1)

    X-Agent-Name ─────────── purement DECLARATIF : il ne peut que CONTREDIRE,
                             jamais etablir. L'identite retenue vient du certificat.

DEUX REGLES QUI NE SE NEGOCIENT PAS :

1. **Ce module ne valide PAS la chaine de certification.** C'est le handshake TLS
   qui l'a faite, en amont, avec `CERT_REQUIRED` + la CA. Ce module recoit un
   certificat DEJA verifie. Le dire ici evite de croire qu'appeler `verifier()` sur
   un certificat quelconque prouverait quoi que ce soit : hors d'un handshake mTLS
   reussi, `cert_der` n'est qu'une suite d'octets fournie par le pair.
2. **Trois etats, jamais deux.** Un controle qui n'a pas pu etre mene rend `UNKNOWN`
   (dependance absente, champ illisible), et `UNKNOWN` ne vaut JAMAIS `ALLOW` :
   la decision globale est alors `REFUSE`, en nommant le controle aveugle.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/liaison-certificat-identite"

import base64
import datetime as _dt
import hashlib
import hmac
from typing import Any, Dict, Optional

PREFIXE_SAN = "urn:nokido:agent:"

OK = "OK"
KO = "KO"
UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# Empreinte (RFC 8705 §3.1 : SHA-256 du DER, base64url SANS remplissage)
# --------------------------------------------------------------------------- #

def thumbprint(cert_der: bytes) -> str:
    """Empreinte `x5t#S256` du certificat, telle que RFC 8705 la definit.

    Le calcul porte sur le DER, jamais sur le PEM : deux encodages du meme
    certificat donneraient deux empreintes differentes, et le lien casserait sans
    que rien ne soit compromis.
    """
    if not cert_der:
        raise ValueError("empreinte demandee sur un certificat vide")
    return base64.urlsafe_b64encode(hashlib.sha256(cert_der).digest()).rstrip(b"=").decode("ascii")


def _crypto():
    try:
        from cryptography import x509  # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------- #
# Lecture du certificat
# --------------------------------------------------------------------------- #

def inspecter(cert_der: bytes) -> Dict[str, Any]:
    """Extrait agent / EKU / validite du certificat. Chaque champ porte son etat."""
    res: Dict[str, Any] = {"agent": "", "san": UNKNOWN, "eku": UNKNOWN,
                           "validite": UNKNOWN, "empreinte": ""}
    if not cert_der:
        res.update({"san": KO, "eku": KO, "validite": KO})
        return res
    res["empreinte"] = thumbprint(cert_der)
    if not _crypto():
        # Dependance absente : on ne SAIT pas. On ne repond surtout pas OK.
        return res

    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID

    try:
        cert = x509.load_der_x509_certificate(cert_der)
    except Exception as e:  # noqa: BLE001
        res.update({"san": KO, "eku": KO, "validite": KO, "erreur": str(e)[:120]})
        return res

    # SAN : c'est LUI qui porte l'identite d'agent, pas le CN (le CN n'est pas
    # normalise et RFC 9525 a retire son usage pour l'identification).
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        uris = san.get_values_for_type(x509.UniformResourceIdentifier)
        agent = ""
        for u in uris:
            if u.startswith(PREFIXE_SAN):
                agent = u[len(PREFIXE_SAN):]
                break
        res["agent"] = agent
        res["san"] = OK if agent else KO
    except x509.ExtensionNotFound:
        res["san"] = KO

    # EKU : un certificat SERVEUR ne doit pas pouvoir servir de certificat CLIENT.
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        res["eku"] = OK if ExtendedKeyUsageOID.CLIENT_AUTH in eku else KO
    except x509.ExtensionNotFound:
        # Absence d'EKU = usage non restreint. C'est permissif, donc on le REFUSE
        # ici plutot que de l'accepter en silence.
        res["eku"] = KO

    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        debut = cert.not_valid_before_utc
        fin = cert.not_valid_after_utc
    except AttributeError:  # cryptography ancien : naive UTC
        debut = cert.not_valid_before.replace(tzinfo=_dt.timezone.utc)
        fin = cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)
    res["validite"] = OK if debut <= now <= fin else KO
    res["expire_le"] = fin.isoformat()
    return res


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #

def verifier(cert_der: Optional[bytes], token_raw: Optional[str], secret: Optional[bytes],
             *, audience: Optional[str] = None, agent_declare: Optional[str] = None,
             exiger_mtls: bool = True, revoques: Optional[set] = None) -> Dict[str, Any]:
    """Rend {decision, agent, raison, controles}.

    `decision` vaut ALLOW seulement si TOUS les controles menes valent OK. Un seul
    KO ou UNKNOWN donne REFUSE, et `raison` nomme le maillon fautif -- un refus qui
    ne dit pas ce qui a manque est ininterpretable, donc il se fait desarmer.
    """
    ctl: Dict[str, str] = {}

    # --- 1. certificat ------------------------------------------------------
    if not cert_der:
        ctl["cert_present"] = KO if exiger_mtls else UNKNOWN
        return {"decision": "REFUSE", "agent": "", "controles": ctl,
                "raison": "aucun certificat client presente"
                          if exiger_mtls else
                          "aucun certificat et aucune exigence : identite NON ETABLIE"}
    ctl["cert_present"] = OK

    vu = inspecter(cert_der)
    ctl["cert_eku_clientauth"] = vu["eku"]
    ctl["cert_validite"] = vu["validite"]
    ctl["cert_san_agent"] = vu["san"]
    agent = vu["agent"]

    if revoques and vu["empreinte"] in revoques:
        ctl["cert_non_revoque"] = KO
        return {"decision": "REFUSE", "agent": agent, "controles": ctl,
                "raison": "certificat revoque"}
    # Sans liste de revocation fournie, on ne SAIT pas : on le declare, on ne
    # transforme pas ce silence en « non revoque ».
    ctl["cert_non_revoque"] = OK if revoques is not None else UNKNOWN

    # --- 2. token -----------------------------------------------------------
    if not token_raw or secret is None:
        ctl["token_present"] = KO
        return {"decision": "REFUSE", "agent": agent, "controles": ctl,
                "raison": "certificat valide mais AUCUN token : le transport est "
                          "authentifie, l'appelant ne l'est pas"}
    ctl["token_present"] = OK

    try:
        from nokido_agent.app.forge_integrity import CapabilityToken
    except ImportError as e:
        ctl["token_valide"] = UNKNOWN
        return {"decision": "REFUSE", "agent": agent, "controles": ctl,
                "raison": "verificateur de token indisponible : %s" % e}

    try:
        tok = CapabilityToken.decode(token_raw, secret, audience=audience,
                                     cert_thumbprint=vu["empreinte"])
    except Exception as e:  # noqa: BLE001 -- le message porte le maillon fautif
        msg = str(e)
        ctl["token_valide"] = KO
        if "confirmation de possession" in msg:
            ctl["token_lie_au_cert"] = KO
        elif "AUTRE certificat" in msg:
            ctl["token_lie_au_cert"] = KO
        elif "udience" in msg:
            ctl["token_audience"] = KO
        return {"decision": "REFUSE", "agent": agent, "controles": ctl,
                "raison": msg[:200]}
    ctl["token_valide"] = OK
    ctl["token_lie_au_cert"] = OK          # decode() l'a compare, sinon il aurait leve
    ctl["token_audience"] = OK if audience is not None else UNKNOWN

    # --- 3. le token parle-t-il du MEME agent que le certificat ? -----------
    ctl["sub_egale_cert"] = OK if (agent and hmac.compare_digest(tok.sub, agent)) else KO

    # --- 4. l'entete declarative ne peut que CONTREDIRE ----------------------
    if agent_declare:
        ctl["entete_coherente"] = OK if hmac.compare_digest(agent_declare, agent) else KO
    else:
        ctl["entete_coherente"] = UNKNOWN

    # --- decision ------------------------------------------------------------
    # UNKNOWN est tolere UNIQUEMENT sur les controles qu'on n'a pas DEMANDES
    # (revocation sans liste, audience non exigee, entete absente). Partout
    # ailleurs, ne pas savoir vaut refuser.
    tolerables = {"cert_non_revoque", "token_audience", "entete_coherente"}
    fautifs = [k for k, v in ctl.items()
               if v == KO or (v == UNKNOWN and k not in tolerables)]
    if fautifs:
        return {"decision": "REFUSE", "agent": agent, "controles": ctl,
                "raison": "controle(s) en echec : %s" % ", ".join(sorted(fautifs))}
    return {"decision": "ALLOW", "agent": agent, "controles": ctl,
            "raison": "certificat, token et audience concordent"}
