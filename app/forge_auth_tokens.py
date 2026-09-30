# -*- coding: utf-8 -*-
"""
forge_auth_tokens.py — Emitter and verifier for short-lived CapabilityTokens.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `renouveler` — Emet un jeton NEUF pour le porteur d'un jeton court encore valide.
- `traiter_renouvellement` — `POST /api/login/renouveler` : ECHANGE DE JETON, RFC 8693 §2.
"""
from __future__ import annotations

import os
import time
import secrets
import hmac
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from nokido_agent.app.forge_integrity import get_manager, CapabilityToken, IntegrityRing
from nokido_agent.app.forge_videur import _load_store, _SEED_RING

logger = logging.getLogger(__name__)

# Fallback agents list for token seeding if hub is not importable
def _agents_connus() -> list:
    """Identites dont on tente de charger le jeton : liste figee UNION registre.

    Le registre (`config/agent_identities.json`) est la source vivante ; la
    liste figee reste un PLANCHER, pour qu'un registre illisible ne fasse pas
    regresser ce qui marchait. Registre illisible -> on le DIT et on rend le
    plancher, plutot que de laisser croire a une couverture complete.
    """
    noms = list(_AGENT_LIST_FALLBACK)
    try:
        import json as _json
        from pathlib import Path as _P

        reg = _P(__file__).resolve().parent.parent / "config" / "agent_identities.json"
        agents = (_json.loads(reg.read_text(encoding="utf-8")) or {}).get("agents") or {}
        for n in agents:
            if n.upper() not in noms:
                noms.append(n.upper())
    except Exception as exc:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[auth_tokens] registre d'identites illisible (%s) : seules les %d "
            "identites figees sont chargees", type(exc).__name__, len(noms))
    return noms


_AGENT_LIST_FALLBACK = [
    "ZCODE",
    "CLAUDE",
    "GEMINI",
    "CODEX",
    "CLINE",
    "BRIDGE",
    "COLLAB_BROKER",
    "GEMINI_HEADLESS",
    "CLAUDE_CLI",
    "NETCFG",
    "TRAY",
    "SERVICES",
    "LLAMACPP",
    "CLAUDE_DESKTOP",
    "VSCODE",
    "LMSTUDIO",
    "ANTIGRAVITY",
    "TASK_EXECUTOR",
]

def _cnf_depuis_jwk(jwk: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """`cnf.jkt` a partir de la cle publique presentee, ou {} si aucune.

    Une empreinte incalculable ne devient PAS un lien vide en silence : elle
    remonte, parce qu'un jeton qu'on croit lie et qui ne l'est pas est pire
    qu'un jeton ouvertement non lie.
    """
    if not jwk:
        return {}
    from nokido_agent.app.forge_dpop import thumbprint

    return {"jkt": thumbprint(jwk)}


# Etape 2b-1 du correctif du coffre (2026-09-28). La cle HMAC persona est une cle
# LOGICIELLE partagee par tous les roles : la presenter ne prouve pas QUI signe, seulement
# qu'on a pu la lire. Tant qu'elle vivait dans un fichier lisible par les comptes bac a
# sable (et retombait sur le nom de machine), elle ouvrait n'importe quel ring. Pour les
# rings <= DEV, seule la signature TPM (cle materielle) connecte.
RING_MAX_TPM_EXIGE = IntegrityRing.DEV


def _ring_de(role_id: str) -> IntegrityRing:
    """Ring du role : registre du videur, puis semis, puis UNTRUSTED."""
    rings = _load_store()
    ring_val = rings.get(role_id, _SEED_RING.get(role_id, 4))
    try:
        return IntegrityRing(ring_val)
    except Exception:
        return IntegrityRing.UNTRUSTED


def login_agent(
    role_id: str,
    secret_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    signature: Optional[str] = None,
    agent_tokens: Optional[Dict[str, str]] = None,
    dpop_jwk: Optional[Dict[str, Any]] = None,
    scopes_demandes: Optional[Dict[str, List[str]]] = None
) -> str:
    """
    Authenticates an agent and returns a short-lived CapabilityToken (30-minute lease).
    
    Supports two login methods:
    1. role_id + secret_id (matching the identity's OWN token -- the master token is
       no longer an identity, step 2b-1 of the vault fix, 2026-09-28)
    2. role_id + timestamp + persona_signature (signed with the TPM key; the persona
       HMAC key is accepted only for rings above DEV)
    """
    role_id = role_id.upper().strip()
    
    # 1. Authenticate credentials
    authenticated = False
    
    if secret_id is not None:
        # Load agent tokens if not provided
        if agent_tokens is None:
            # Le jeton MAITRE n'est plus l'identifiant de l'owner ni de MASTER_TOKEN
            # (etape 2b-1 du correctif du coffre, 2026-09-28) : lisible par les
            # comptes bac a sable au coffre machine, il ouvrait ici un
            # CapabilityToken au nom de l'owner. Chaque identite se connecte avec
            # SON secret (`FORGE_TOKEN_<AGENT>`).
            #
            # Et le GUICHET seul, plus le module du hub (2026-09-28). Importer
            # `nokido_agent.tools.nokido_hub` depuis une bibliotheque chargeait le
            # hub ENTIER dans un process client, et dans les tests prenait les
            # jetons d'une AUTRE instance du hub deja chargee sous un autre nom :
            # 9 rouges du NR cycle de vie selon l'ordre des tests. Le hub lit ses
            # jetons a ce meme guichet (`_load_agent_tokens`) : meme source.
            tokens = {}
            try:
                from nokido_agent.app.forge_secrets import get_secret
                # UNION liste figee + REGISTRE VIVANT (2026-09-02).
                # La liste seule laissait sans jeton toute identite declaree
                # apres son ecriture : mesure du jour, `login_agent
                # ("STATE_ENCODER", ...)` rendait « Invalid credentials »
                # alors que le credential EXISTAIT au coffre -- l'agent
                # n'etait simplement pas dans le tuple. C'est le TROISIEME
                # endroit du corps ou une liste figee ignore le registre
                # (le chargeur du hub et le semeur de jetons avaient le
                # meme defaut, corriges le meme jour). Une identite
                # invisible du chargeur est une identite anonyme.
                for agent in _agents_connus():
                    val = get_secret(f"FORGE_TOKEN_{agent}")
                    if val:
                        tokens[agent] = val
            except Exception as exc:  # noqa: BLE001
                # Guichet illisible : aucune identite ne se connecte par secret,
                # et on le DIT -- « Invalid credentials » seul ne distinguerait
                # pas une panne du guichet d'un mauvais secret.
                logger.warning("[auth_tokens] guichet illisible (%s) : aucun jeton "
                               "d'agent charge", type(exc).__name__)
        else:
            tokens = agent_tokens
            
        # Match secret_id
        expected = tokens.get(role_id)
        # Aucun repli croise MASTER_TOKEN <-> owner : le secret d'une identite
        # n'ouvre jamais une autre identite (2b-1, 2026-09-28).
        if expected and hmac.compare_digest(secret_id.encode(), expected.encode()):
            authenticated = True
                
    elif signature is not None and timestamp is not None:
        # Check replay protection (5 minutes window)
        now = time.time()
        if abs(now - timestamp) > 300:
            raise ValueError("Timestamp skew too large (replay protection)")
            
        # Construct signed payload
        payload_bytes = f"{role_id}:{timestamp}".encode("utf-8")
        
        hmac_refuse = False
        # Verify signature
        try:
            import base64
            # The signature can be hex or base64
            try:
                sig_bytes = bytes.fromhex(signature)
            except ValueError:
                pad = "=" * (-len(signature) % 4)
                sig_bytes = base64.b64decode(signature + pad)
                
            from nokido_agent.app.forge_persona_tpm import verify as _tpm_verify, _hmac_key
            
            # Try TPM verify
            tpm_ok = _tpm_verify(payload_bytes, sig_bytes)
            if tpm_ok:
                authenticated = True
            elif int(_ring_de(role_id)) <= int(RING_MAX_TPM_EXIGE):
                # La cle n'est meme pas lue : aucune signature HMAC ne connecte ce ring.
                hmac_refuse = True
            else:
                # Try HMAC fallback verify
                expected_mac = hmac.new(_hmac_key(), payload_bytes, hashlib.sha256).digest()
                if hmac.compare_digest(sig_bytes, expected_mac):
                    authenticated = True
        except Exception as e:
            logger.warning(f"Signature verification error: {e}")
            raise ValueError(f"Signature verification failed: {e}")
        if hmac_refuse:
            raise ValueError(
                f"Connexion par HMAC persona refusee pour {role_id} (ring <= "
                f"{int(RING_MAX_TPM_EXIGE)}) : signature TPM exigee")
            
    else:
        raise ValueError("Either secret_id or signature+timestamp must be provided")
        
    if not authenticated:
        raise ValueError("Invalid credentials")
        
    # 2. Resolve ring
    ring = _ring_de(role_id)
        
    # 3. Create short-lived token
    mgr = get_manager()
    
    # Generate scopes
    scopes = ring.default_scopes()
    
    # SECOND CHEMIN D'EMISSION -- construction manuelle pour pouvoir signer TPM.
    # Il DIVERGEAIT de `create_manifest`, et les deux ecarts avaient un cout
    # mesure le 2026-09-02 :
    #   - `iss` absent (RFC 9068 §2.2, RFC 9207) : un jeton n'annoncait pas son
    #     emetteur, ce qui ne se voit pas avec un hub unique et devient une
    #     confusion d'emetteur des le second (edge, federation) ;
    #   - `seq=1` CODE EN DUR, sans passer par `_seq_counter` : `revoke()`
    #     posait alors `min_seq = 0+1 = 1` et la comparaison `seq(1) < 1` etait
    #     fausse -- la revocation n'annulait RIEN. Un garde appele et sans effet.
    # Le compteur est desormais avance ici aussi ; la barriere temporelle de
    # `revoke` rattrape de toute facon les chemins qui l'oublieraient.
    _seq = mgr._seq_counter.get(role_id, 0) + 1
    mgr._seq_counter[role_id] = _seq
    token = CapabilityToken(
        sub=role_id,
        ring=ring,
        scopes=scopes,
        exp=time.time() + 1800, # 30 minutes
        iat=time.time(),
        jti=secrets.token_hex(8),
        seq=_seq,
        # `LAFORGE_JWT_ISSUER` et non `..._TOKEN_ISS` : l'emetteur est PUBLIC
        # par construction (RFC 9068 §2.2, il voyage en clair dans le jeton).
        # L'ancien nom contenait `_TOKEN`, ce qui declenchait la regle
        # `cloud-secret-from-env` -- un garde qui crie sur ce qui n'est pas un
        # secret finit desarme, donc c'est le NOM qu'on corrige, pas le garde.
        iss=os.environ.get("LAFORGE_JWT_ISSUER", "nokido-hub-local"),
        # LIEN AU PORTEUR (RFC 9449 §6). Quand le demandeur presente la cle
        # publique dont il prouvera la possession, le jeton emis porte son
        # empreinte : un jeton vole devient alors inutilisable sans la cle
        # privee correspondante. Sans `dpop_jwk`, le jeton reste un bearer
        # ordinaire -- et `forge_dpop.est_lie()` le dira, plutot que de laisser
        # supposer une protection. Le lien est OPTIONNEL par construction :
        # l'imposer avant qu'un seul appelant sache le produire ne durcirait
        # rien, ca rendrait le corps muet.
        cnf=_cnf_depuis_jwk(dpop_jwk),
    )
    
    # PORTEE DEMANDEE (A1, 2026-09-22). Sans `scopes_demandes`, RIEN NE CHANGE :
    # le jeton porte les scopes du ring, exactement comme avant. Le defaut est
    # donc strictement retrocompatible -- aucun appelant existant n'est touche.
    #
    #     REQUESTED != GRANTED — et l'ecart se DIT, il ne se rattrape pas en
    #     silence. `attenuer_ou_refuser` LEVE quand la demande depasse ce que
    #     le porteur peut accorder, au lieu de rendre un jeton qui pretend
    #     porter un scope sans autoriser aucune action dedans.
    #
    # La reduction elle-meme n'est pas reecrite ici : `CapabilityToken.attenuate`
    # sait deja ne faire qu'intersecter, et preserve `sub`, `ring`, `seq` (donc
    # la revocation suit), `iss` et `cnf`. Un seul endroit du corps sait
    # restreindre une portee.
    #
    # CE QUE CECI NE FAIT PAS : rendre une route plus sure. Tant qu'aucune
    # decision d'autorisation ne LIT ces scopes, un jeton de portee reduite
    # n'est qu'un jeton mieux decrit. `/api/recon/run` et `/api/ctf/run` gardent
    # leur contrat d'entree inchange -- c'est la phase A2, et elle se mesure.
    if scopes_demandes is not None:
        from nokido_agent.app.forge_integrity import attenuer_ou_refuser
        token = attenuer_ou_refuser(token, scopes_demandes)

    # Encode with TPM signature if available
    serialized = token.encode(mgr._secret, tpm_sign=True)
    return serialized


# --- RENOUVELLEMENT DES JETONS COURTS (decision owner 2026-09-28) --------------------------
#
# Un service lance par le superviseur recoit un jeton COURT au lieu d'heriter du jeton
# maitre (plan : C:/tmp/plan_jeton_court_lanceur_2026-09-28.md, etape A). Il ne tient aucun
# secret statique : il prolonge son jeton en le PRESENTANT. Rien de tel n'existait --
# `CapabilityToken.attenuate` ne prolonge jamais, et c'est voulu.
RING_MIN_RENOUVELABLE = IntegrityRing.TRUSTED   # ring <= DEV : jamais par un jeton de lanceur
_HOTES_LOCAUX = ("127.0.0.1", "::1", "localhost")
# RFC 8693 §2.1 / §3 : l'echange de jeton, et le seul type de jeton echange ici.
GRANT_ECHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TYPE_JETON_ACCES = "urn:ietf:params:oauth:token-type:access_token"
_ENTETES_JETON = {"Cache-Control": "no-store", "Pragma": "no-cache"}   # RFC 6749 §5.1


def renouveler(jeton: str, dpop_jkt: Optional[str] = None) -> str:
    """Emet un jeton NEUF pour le porteur d'un jeton court encore valide.

    - expire, revoque ou forge -> ValueError ; la revocation est lue au MEME endroit que
      `verify` (`IntegrityManager._raison_revocation`) ;
    - ring <= DEV -> ValueError : l'owner ne passe jamais par un jeton de lanceur ;
    - jamais d'elevation : ring = le MOINS privilegie du jeton et du registre actuel ; une
      retrogradation reduit la portee a l'intersection ;
    - `sub`, `iss`, `aud`, `cnf` conserves ; `jti` neuf, `seq` avance, bail de 30 min.
    Un jeton lie (`cnf`) exige la preuve de possession (`dpop_jkt`), comme partout ailleurs.
    """
    from nokido_agent.app.forge_integrity import TokenExpiredError

    mgr = get_manager()
    try:
        courant = CapabilityToken.decode(jeton or "", mgr._secret, dpop_jkt=dpop_jkt)
    except TokenExpiredError as exc:
        raise ValueError(f"renouvellement refuse : jeton expire ({exc})") from None
    except ValueError as exc:
        raise ValueError(f"renouvellement refuse : jeton invalide ({exc})") from None
    raison = mgr._raison_revocation(courant)
    if raison:
        raise ValueError(f"renouvellement refuse : {raison}")
    if int(courant.ring) < int(RING_MIN_RENOUVELABLE):
        raise ValueError(
            f"renouvellement refuse : ring {courant.ring.label()} <= DEV -- l'owner ne "
            "passe jamais par un jeton de lanceur")
    ring = _ring_de(courant.sub)
    if int(ring) < int(courant.ring):
        ring = courant.ring          # le registre a promu : le jeton n'en herite pas
    if ring == courant.ring:
        scopes = courant.scopes
    else:                            # retrograde : la portee se reduit a l'intersection
        scopes = {p: [a for a in actions if a in (courant.scopes.get(p) or [])]
                  for p, actions in ring.default_scopes().items()}
        scopes = {p: a for p, a in scopes.items() if a}
    maintenant = time.time()
    _seq = mgr._seq_counter.get(courant.sub, 0) + 1
    mgr._seq_counter[courant.sub] = _seq
    neuf = CapabilityToken(
        sub=courant.sub, ring=ring, scopes=scopes,
        exp=maintenant + 1800, iat=maintenant, jti=secrets.token_hex(8), seq=_seq,
        aud=courant.aud, iss=courant.iss, cnf=dict(courant.cnf or {}))
    return neuf.encode(mgr._secret, tpm_sign=True)


def _erreur_oauth(statut: int, code: str, description: str):
    """Reponse d'erreur RFC 6749 §5.2 (codes etendus par RFC 8693 §2.2.2)."""
    return statut, {"error": code, "error_description": description}, dict(_ENTETES_JETON)


def traiter_renouvellement(hote_client: str, type_contenu: str,
                           corps: bytes) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """`POST /api/login/renouveler` : ECHANGE DE JETON, RFC 8693 §2 -- hors du hub pour etre
    testable sans lui. Rend (statut HTTP, corps JSON, en-tetes).

    Demande (RFC 8693 §2.1), corps `application/x-www-form-urlencoded` :
      grant_type=urn:ietf:params:oauth:grant-type:token-exchange
      subject_token=<jeton court courant>
      subject_token_type=urn:ietf:params:oauth:token-type:access_token
    Reponse (RFC 8693 §2.2.1) : `access_token`, `issued_token_type`, `token_type`,
    `expires_in`, et `Cache-Control: no-store` (RFC 6749 §5.1).

    Ce point ne fait QUE prolonger : `actor_token` (delegation), `audience`/`resource` et
    `scope` sont refuses en le disant, jamais ignores -- un parametre ignore ferait croire a
    une portee ou une audience qu'il n'accorde pas. La boucle locale seule est une politique
    LOCALE (le jeton ne voyage pas), hors RFC : 403. Aucune valeur de jeton dans une erreur.
    """
    if (hote_client or "") not in _HOTES_LOCAUX:
        return _erreur_oauth(403, "access_denied", "echange de jeton : boucle locale seulement")
    if (type_contenu or "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
        return _erreur_oauth(400, "invalid_request",
                             "corps attendu en application/x-www-form-urlencoded (RFC 8693 §2.1)")
    from urllib.parse import parse_qs

    try:
        champs = parse_qs((corps or b"").decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return _erreur_oauth(400, "invalid_request", "corps non UTF-8")
    if any(len(v) > 1 for v in champs.values()):     # RFC 6749 §3.2
        return _erreur_oauth(400, "invalid_request", "parametre repete")
    p = {k: v[0] for k, v in champs.items()}
    if not p.get("grant_type"):
        return _erreur_oauth(400, "invalid_request", "grant_type manquant")
    if p["grant_type"] != GRANT_ECHANGE:
        return _erreur_oauth(400, "unsupported_grant_type", "seul l'echange de jeton (RFC 8693)")
    if not p.get("subject_token") or not p.get("subject_token_type"):
        return _erreur_oauth(400, "invalid_request", "subject_token et subject_token_type requis")
    if p["subject_token_type"] != TYPE_JETON_ACCES or \
            p.get("requested_token_type") not in (None, "", TYPE_JETON_ACCES):
        return _erreur_oauth(400, "invalid_request", "seul le type access_token s'echange ici")
    if p.get("actor_token") or p.get("actor_token_type"):
        return _erreur_oauth(400, "invalid_request",
                             "delegation (actor_token) non prise en charge par ce point")
    if p.get("audience") or p.get("resource"):
        return _erreur_oauth(400, "invalid_target", "changement d'audience non pris en charge ici")
    if p.get("scope"):
        return _erreur_oauth(400, "invalid_scope", "reduction de portee non prise en charge ici")
    try:
        neuf = renouveler(p["subject_token"])
    except ValueError as exc:
        return _erreur_oauth(400, "invalid_grant", str(exc))
    # `token_type` Bearer (RFC 6750) : un jeton lie exige une preuve DPoP que ce point ne
    # verifie pas encore -- `renouveler` le refuse donc (invalid_grant), il ne l'emet pas
    # en le pretendant porteur.
    return 200, {"access_token": neuf, "issued_token_type": TYPE_JETON_ACCES,
                 "token_type": "Bearer", "expires_in": 1800}, dict(_ENTETES_JETON)
