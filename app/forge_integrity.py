# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_integrity.py — Capability-Based Security (Nokido v16.6)
==============================================================
Security by design — Edge-first, offline-capable, zéro dépendance circulaire.

Architecture "Capability Token" :
  La sentinel ne demande pas "Qui es-tu ?" mais "Montre-moi ton droit d'accès."
  Les permissions voyagent dans le token (signé HMAC-SHA256), pas en base.

Avantages Edge :
  - Validation offline instantanée (HMAC local, pas de réseau)
  - Interopérable : deux instances partageant la même clé acceptent les mêmes tokens
  - Audit-ready : le ring est dans le token, extrait à chaque action loggée
  - Non-bunkerisé : changer les droits = réémettre un token, pas modifier du code

Rings (niveaux d'intégrité, croissants = droits décroissants) :
  SYSTEM   (0) — Core Nokido, migrations DB
  DEV      (1) — Claude via MCP / session maintenance (token requis)
  TRUSTED  (2) — Workflows TUI (@audit, @ci, @workflow)
  COLLAB   (3) — Comité LLM / agents externes
  UNTRUSTED(4) — Inputs bruts / agents sans token

Scopes disponibles :
  "fs"      : ["read", "write", "exec"]
  "rag"     : ["query", "ingest", "admin"]
  "sql"     : ["read", "write"]
  "tasks"   : ["claim", "result", "create", "review"]
  "system"  : ["audit_view", "sentinel_bypass"]

Format token : "{payload_b64}.{hmac_hex}"
  payload = {"sub", "ring", "scopes", "exp", "iat", "jti"}

Usage :
  from forge_integrity import IntegrityRing, CapabilityToken, IntegrityManager
  from forge_integrity import is_at_least, RingContext

  mgr   = IntegrityManager(secret)
  token = mgr.create_manifest("claude", IntegrityRing.DEV,
                               scopes={"fs": ["*"], "rag": ["ingest", "query"]})
  ok, ctx = mgr.verify("fs", "write", token)
  if ok:
      # ctx est un RingContext prêt à l'emploi
      log_action(ctx.rag_author_tag(), ...)
"""


import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# Etats de la DEMANDE de signature TPM a l'emission. Trois, jamais deux :
# « pas demandee » et « demandee mais refusee » ne sont pas la meme chose, et
# ne se reparent pas pareil.
TPM_NOT_REQUESTED = "TPM_NOT_REQUESTED"
TPM_REQUESTED_SIGNED = "TPM_REQUESTED_SIGNED"
TPM_REQUESTED_FAILED = "TPM_REQUESTED_FAILED"


def _cause_echec_tpm() -> str:
    """Pourquoi la signature TPM n'a pas ete obtenue. Jamais « MANQUANTE ».

    Un jeton sans preuve parce que le compte ne peut pas OUVRIR la cle n'est
    pas un jeton qu'on a neglige de signer. Mesure du 2026-09-21 :
    `laforge-persona-sign` rend NTE_PERM depuis le compte du hub -- la cle
    EXISTE, l'acces est refuse. Classer cela « preuve manquante » enverrait
    chercher un emetteur fautif la ou il faut ouvrir un acces.
    """
    try:
        from nokido_agent.app.forge_persona_tpm import (
            etat_cle_tpm, _KEY_NAME)
        etat, code = etat_cle_tpm(_KEY_NAME)
        return "%s:0x%08X" % (etat, code & 0xFFFFFFFF)
    except Exception as e:  # noqa: BLE001
        return "NON_MESURABLE:%s" % type(e).__name__

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# IntegrityRing — enum ordonné
# ─────────────────────────────────────────────────────────────────────────────


class IntegrityRing(IntEnum):
    """
    Niveaux d'intégrité ordonnés.
    Règle : ring INFÉRIEUR = PLUS de droits (ring -1 > ring 0 > ring 4).
    Ne JAMAIS comparer avec == directement : utiliser is_at_least().

    Rings :
      MASTER    (-1) — Supercontrôleur absolu. Accès complet y compris
                        les actions destructrices et les overrides Sentinel.
                        Protégé par Time-Lock TTL 5min (MASTER_TTL_S=300).
                        Jamais transmis aux agents externes.
      SYSTEM    ( 0) — Core Nokido, migrations DB, nr_runner
      DEV       ( 1) — Claude via MCP / session maintenance (token requis)
      TRUSTED   ( 2) — Workflows TUI (@audit, @ci, @workflow)
      COLLAB    ( 3) — Comité LLM / agents externes
      UNTRUSTED ( 4) — Inputs bruts / agents sans token
    """

    MASTER = -1
    SYSTEM = 0
    DEV = 1
    TRUSTED = 2
    COLLAB = 3
    UNTRUSTED = 4

    def label(self) -> str:
        """Label."""
        return {-1: "MASTER", 0: "SYSTEM", 1: "DEV", 2: "TRUSTED", 3: "COLLAB", 4: "UNTRUSTED"}[int(self)]

    def consensus_level(self) -> str:
        """Niveau de confiance RAG pour les ingestions de ce ring."""
        return {-1: "sovereign", 0: "gold", 1: "gold", 2: "verified", 3: "draft", 4: "raw"}[int(self)]

    def default_scopes(self) -> Dict[str, List[str]]:
        """Scopes par défaut si aucun token n'est fourni (fallback conservateur)."""
        return {
            -1: {"fs": ["*"], "rag": ["*"], "sql": ["*"], "tasks": ["*"], "system": ["*"], "master": ["*"]},
            0: {"fs": ["*"], "rag": ["*"], "sql": ["*"], "tasks": ["*"], "system": ["*"]},
            1: {
                "fs": ["read", "write", "exec"],
                "rag": ["ingest", "query", "admin"],
                "sql": ["read"],
                "tasks": ["claim", "result", "create", "review"],
                "system": ["audit_view", "sentinel_bypass"],
            },
            2: {
                "fs": ["read", "write"],
                "rag": ["ingest", "query"],
                "sql": ["read"],
                "tasks": ["claim", "result", "create"],
            },
            3: {"rag": ["query", "ingest"], "sql": ["read"], "tasks": ["claim", "result"]},  # fs:read retiré: exige TRUSTED (cf SCOPE_REQUIRED_RING) -> grant mort sinon
            4: {},
        }[int(self)]


# Context:


def is_at_least(ring: "IntegrityRing", required: "IntegrityRing") -> bool:
    """
    Vrifie que `ring` possde au moins les droits de `required`.
    Rgle : ring <= required (les rings infrieurs ont PLUS de droits).

    Toujours utiliser cette fonction, jamais de comparaison == ou > directe.

    Exemples :
      is_at_least(DEV, TRUSTED)     True   DEV peut tout ce que TRUSTED peut
      is_at_least(COLLAB, TRUSTED)  False  COLLAB n'a pas les droits TRUSTED
      is_at_least(SYSTEM, DEV)      True   SYSTEM est plus privilgi que DEV
    """
    return int(ring) <= int(required)


# ─────────────────────────────────────────────────────────────────────────────
# Scopes — déclaration canonique
# ─────────────────────────────────────────────────────────────────────────────

# Actions valides par domaine (source de vérité unique)
SCOPE_ACTIONS: Dict[str, FrozenSet[str]] = {
    "fs": frozenset({"read", "write", "exec"}),
    "rag": frozenset({"query", "ingest", "admin"}),
    "sql": frozenset({"read", "write"}),
    "tasks": frozenset({"claim", "result", "create", "review"}),
    "system": frozenset({"audit_view", "sentinel_bypass"}),
    # Scope exclusif MASTER (-1) : actions destructrices et overrides
    "master": frozenset(
        {"purge_all", "rag_rollback", "sentinel_override", "cold_backup", "force_unlock", "ttl_bypass"}
    ),
}

# Ring minimum requis par scope+action (pour messages d'erreur explicites)
SCOPE_REQUIRED_RING: Dict[Tuple[str, str], IntegrityRing] = {
    ("fs", "read"): IntegrityRing.TRUSTED,  # Renforcé (ex-COLLAB)
    ("fs", "write"): IntegrityRing.TRUSTED,
    ("fs", "exec"): IntegrityRing.TRUSTED,
    ("rag", "query"): IntegrityRing.COLLAB,
    ("rag", "ingest"): IntegrityRing.COLLAB,
    ("rag", "admin"): IntegrityRing.DEV,
    ("sql", "read"): IntegrityRing.COLLAB,
    ("sql", "write"): IntegrityRing.SYSTEM,
    ("tasks", "claim"): IntegrityRing.COLLAB,
    ("tasks", "result"): IntegrityRing.COLLAB,
    ("tasks", "create"): IntegrityRing.TRUSTED,
    ("tasks", "review"): IntegrityRing.DEV,
    ("system", "audit_view"): IntegrityRing.DEV,
    ("system", "sentinel_bypass"): IntegrityRing.DEV,
    # Scope MASTER (-1) : actions destructrices -> exigent ring MASTER (audit 2026-06-15 :
    # absentes -> .get(default=TRUSTED) accordait ces actions dès le ring 2).
    ("master", "purge_all"): IntegrityRing.MASTER,
    ("master", "rag_rollback"): IntegrityRing.MASTER,
    ("master", "sentinel_override"): IntegrityRing.MASTER,
    ("master", "cold_backup"): IntegrityRing.MASTER,
    ("master", "force_unlock"): IntegrityRing.MASTER,
    ("master", "ttl_bypass"): IntegrityRing.MASTER,
}


def attenuer_ou_refuser(parent, demande: Dict[str, List[str]],
                        duration_s: Optional[float] = None):
    """Accorde une portee REDUITE, ou REFUSE en nommant ce qui depasse.

        REQUESTED != GRANTED — et l'ecart se DIT.

    `attenuate` seule fait l'intersection en SILENCE : une portee absente du
    pere rendait `{scope: []}`, c'est-a-dire un jeton qui pretend porter ce
    scope et n'autorise rien. Le demandeur ne l'apprenait qu'a l'usage, loin
    du point ou la decision a ete prise.

    Cette fonction ne reimplemente RIEN : elle interroge le pere
    (`portee_hors_du_pere`), refuse si l'ecart n'est pas vide, et delegue la
    reduction a `attenuate`. Un seul endroit sait restreindre.

    Leve `ValueError` en NOMMANT scopes et actions refuses -- un refus muet
    n'est pas instruisable.
    """
    hors = parent.portee_hors_du_pere(demande)
    if hors:
        detail = ", ".join("%s:%s" % (s, "/".join(a)) for s, a in sorted(hors.items()))
        raise ValueError(
            "portee demandee HORS de celle du porteur (refus, pas de reduction "
            "silencieuse) : %s" % detail)
    return parent.attenuate(demande, duration_s=duration_s)


def _scope_allows(user_scopes: Dict[str, List[str]], scope: str, action: str) -> bool:
    """
    Vérifie si les scopes du token autorisent scope+action.
    "*" dans la liste = toutes les actions de ce scope autorisées.
    """
    allowed = user_scopes.get(scope, [])
    return "*" in allowed or action in allowed


# ─────────────────────────────────────────────────────────────────────────────
# CapabilityToken — token signé HMAC-SHA256
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityToken:
    """
    Token de capacité auto-suffisant (payload + signature).
    Immutable — ne jamais modifier après création.

    Format sérialisé : "{payload_b64}.{hmac_hex_32}"
    payload JSON : {sub, ring, scopes, exp, iat, jti}
    """

    sub: str  # agent_id
    ring: IntegrityRing
    scopes: Dict[str, List[str]]  # {"fs": ["write"], "rag": ["*"]}
    exp: float  # expiration (unix timestamp)
    iat: float  # issued at
    jti: str  # ID unique (anti-replay)
    seq: int = 0  # Numéro de séquence croissant (révocation)
    # AUDIENCE (RFC 8707 « Resource Indicators », RFC 9068 §2.2, spec MCP 2026-07-28 :
    # « valider le token ET son audience »). Un bearer sans audience est rejouable vers
    # TOUTE ressource qui partage le secret : il prouve la possession, jamais la
    # destination. `aud` lie le token a la ressource pour laquelle il a ete emis.
    # Defaut "" = token LEGACY (emis avant ce champ) : accepte, mais `decode(audience=…)`
    # le REFUSE des qu'une audience est exigee -- on ne fait pas passer une absence
    # pour une correspondance.
    aud: str = ""
    # `iss` -- emetteur du jeton. RFC 9068 §2.2 (profil JWT des access tokens)
    # et RFC 9207, qui existe precisement pour qu'un client sache QUI a emis ce
    # qu'il recoit. Vide par defaut : on n'invente pas une identite d'emetteur,
    # elle est posee a l'emission. Un `iss` absent n'est pas un defaut tant
    # qu'il n'y a qu'un emetteur -- il le devient des le second (edge,
    # federation, second hub), et migrer un parc de jetons deja en circulation
    # coute plus cher que de le poser maintenant.
    iss: str = ""
    # CONFIRMATION DE POSSESSION (RFC 8705 §3.1, « certificate-bound access token »).
    # `cnf = {"x5t#S256": "<empreinte base64url du DER du certificat client>"}` lie le
    # token au certificat mTLS qui doit le presenter. Sans ce lien, un bearer vole
    # est rejouable depuis N'IMPORTE QUEL client : il prouve la connaissance du
    # secret, jamais l'identite du porteur. Defaut {} = token NON LIE (legacy) :
    # accepte tant que personne n'exige de lien, REFUSE des que `decode(...,
    # cert_thumbprint=…)` en demande un -- « pas de lien » n'est pas « le bon lien ».
    cnf: Dict[str, str] = field(default_factory=dict)
    # brain_worker stocke last_seq_seen[sub]
    # token rejeté si seq < last_seq_seen[sub]

    @classmethod
    def decode(cls, raw: str, secret: bytes, *, require_tpm: bool = False,
               audience: str | None = None,
               cert_thumbprint: str | None = None,
               dpop_jkt: str | None = None) -> "CapabilityToken":
        """
        Décode et valide un token sérialisé.
        Lève ValueError si signature invalide, TokenExpiredError si expiré.

        Format : "{payload_b64}.{hmac_hex}" ou, avec racine matérielle (AXE 8 PR-6),
        "{payload_b64}.{hmac_hex}.{tpm_sig_b64}". Le HMAC est toujours vérifié
        (interop offline) ; la signature TPM est vérifiée en plus si présente et si
        le TPM est disponible. require_tpm=True rejette tout token non signé-TPM.
        """
        parts = raw.split(".")
        if len(parts) == 2:
            payload_b64, sig = parts
            tpm_sig_b64 = None
        elif len(parts) == 3:
            payload_b64, sig, tpm_sig_b64 = parts
        else:
            raise ValueError("Format token invalide (attendu: payload.signature[.tpm])")

        # 1. Vérification HMAC constant-time (anti timing attack)
        expected_sig = hmac.new(
            secret,
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Signature HMAC invalide")

        # 1.bis Racine de confiance matérielle (TPM). Signe "{payload_b64}.{sig}".
        tpm_ok = False
        if tpm_sig_b64:
            try:
                from nokido_agent.app.forge_persona_tpm import tpm_available, verify_etat

                if tpm_available():
                    pad = "=" * (-len(tpm_sig_b64) % 4)
                    tpm_sig = base64.urlsafe_b64decode(tpm_sig_b64 + pad)
                    # TROIS ETATS, parce que deux faisaient accuser a tort.
                    # Mesure 2026-09-02 : la cle du TPM est une cle MACHINE ;
                    # depuis un compte de service elle n'est pas ouvrable, et
                    # l'ancien booleen traduisait ce refus d'ACCES en « token
                    # altéré ». Le hub acceptait le meme jeton (HTTP 200) : le
                    # jeton etait intact, c'est le verificateur qui etait
                    # aveugle. La DECISION est inchangee -- seul VALIDE passe,
                    # INVERIFIABLE refuse comme avant -- mais le message ne
                    # designe plus un coupable qu'il n'a pas constate.
                    _verdict, _raison = verify_etat(
                        f"{payload_b64}.{sig}".encode("ascii"), tpm_sig)
                    tpm_ok = _verdict == "VALIDE"
                    if _verdict == "INVALIDE":
                        raise ValueError("Signature TPM invalide (token altéré)")
                    if not tpm_ok:
                        raise ValueError(
                            "Signature TPM INVERIFIABLE dans ce contexte (%s) — "
                            "refus par prudence, mais ceci n'accuse PAS le token"
                            % _raison)
            except ValueError:
                raise
            except Exception:
                tpm_ok = False
        if require_tpm and not tpm_ok:
            raise ValueError("Token non signé-TPM rejeté (require_tpm)")

        # 2. Décodage payload
        try:
            # Padding base64 tolérant
            pad = "=" * (-len(payload_b64) % 4)
            raw_json = base64.urlsafe_b64decode(payload_b64 + pad)
            payload = json.loads(raw_json)
        except Exception as e:
            raise ValueError(f"Payload illisible: {e}")

        # 3. Expiration
        exp = float(payload.get("exp", 0))
        if time.time() > exp:
            raise TokenExpiredError(f"Token expiré depuis {int(time.time() - exp)}s")

        # 3.bis Ring/seq FAIL-CLOSED (audit 2026-06-15) : valeur inconnue/corrompue ->
        # UNTRUSTED / seq=0, jamais une ValueError brute ni un ring privilégié par accident.
        _iat = float(payload.get("iat", 0))
        try:
            _ring = IntegrityRing(int(payload.get("ring", 4)))
        except (ValueError, TypeError):
            _ring = IntegrityRing.UNTRUSTED
        try:
            _seq = int(payload.get("seq", 0))
        except (ValueError, TypeError):
            _seq = 0

        # 3.ter Time-Lock MASTER (audit 2026-06-15) : MASTER_TTL_S=300 documenté.
        # On impose une limite dure de 300s de durée de vie totale pour le ring MASTER.
        if _ring == IntegrityRing.MASTER and (exp - _iat) > 300:
            raise ValueError(f"Token MASTER TTL > 300s ({int(exp - _iat)}s) — Time-Lock violé")

        # 3.quater AUDIENCE (RFC 8707 / RFC 9068 / MCP 2026-07-28). Verifiee UNIQUEMENT
        # si l'appelant en exige une : un verificateur qui ne demande rien ne doit pas
        # se croire protege. Un token LEGACY (aud absent) est REFUSE des qu'une audience
        # est exigee -- « pas d'audience » n'est pas « la bonne audience ».
        _aud = str(payload.get("aud", ""))
        if audience is not None:
            if not _aud:
                raise ValueError(
                    "Token sans audience alors qu'une audience est exigee "
                    f"({audience!r}) — token legacy, a reemettre")
            if not hmac.compare_digest(_aud, audience):
                raise ValueError("Audience du token invalide pour cette ressource")

        # 3.quinquies CONFIRMATION DE POSSESSION (RFC 8705 §3.1). Meme discipline que
        # l'audience : verifiee UNIQUEMENT si l'appelant fournit l'empreinte du
        # certificat REELLEMENT presente au handshake. Un token sans `cnf` est REFUSE
        # des qu'un lien est exige : une absence ne vaut pas une correspondance.
        _cnf = payload.get("cnf") or {}
        if not isinstance(_cnf, dict):
            _cnf = {}
        if cert_thumbprint is not None:
            _lie = str(_cnf.get("x5t#S256", ""))
            if not _lie:
                raise ValueError(
                    "Token sans confirmation de possession (cnf.x5t#S256) alors "
                    "qu'un certificat client est exige — token non lie, a reemettre")
            if not hmac.compare_digest(_lie, cert_thumbprint):
                raise ValueError(
                    "Le token est lie a un AUTRE certificat que celui presente")
        elif _cnf.get("x5t#S256"):
            # VOLET SYMETRIQUE, RFC 8705 (ajoute le 2026-09-21), jumeau exact du
            # volet DPoP pose le meme jour quelques lignes plus bas.
            #
            # Le bloc ci-dessus ne compare le lien QUE si un certificat a ete
            # presente. Un jeton PORTEUR d'un `cnf.x5t#S256` circulant sur un
            # canal SANS certificat passait donc sans controle : le lien se
            # contournait EN NE LE PRESENTANT PAS. Un jeton lie au transport
            # qu'on accepte hors de ce transport n'est plus lie a rien.
            #
            # TAUX DE REFUS INDUIT : ZERO. Aucun appelant de production n'emet
            # de jeton portant `x5t#S256` -- meme mesure que pour `jkt`.
            #
            # `forge_cert_binding.verifier` n'est PAS affecte : il appelle
            # toujours `decode(..., cert_thumbprint=...)`, donc le `if`
            # ci-dessus, jamais cette branche.
            raise ValueError(
                "Token LIE a un certificat (cnf.x5t#S256) mais aucun certificat "
                "client n'a ete presente — presenter le certificat, ou utiliser "
                "decode_raw pour une lecture non verifiee")

        # 3.sexies MEME LIEN, AUTRE CANAL (RFC 9449 §6, DPoP). La RFC 8705
        # ci-dessus lie le token a un CERTIFICAT, donc elle suppose un canal
        # mTLS. Le corps n'en a pas sur le loopback, et un garde branche sur un
        # signal que personne n'emet ne protege rien. DPoP obtient le meme lien
        # au niveau applicatif : `cnf.jkt` porte l'empreinte RFC 7638 de la cle
        # publique dont le porteur doit prouver la possession a chaque requete.
        #
        # Meme discipline que l'audience et que le certificat : verifie
        # UNIQUEMENT si l'appelant fournit l'empreinte REELLEMENT prouvee. Une
        # absence de lien ne vaut jamais une correspondance -- et le refus dit
        # laquelle des deux formes manquait, parce que « non lie » et « lie a
        # autre chose » n'appellent pas le meme remede.
        if dpop_jkt is not None:
            _jkt = str(_cnf.get("jkt", ""))
            if not _jkt:
                raise ValueError(
                    "Token sans confirmation de possession (cnf.jkt) alors "
                    "qu'une preuve DPoP est exigee — token non lie, a reemettre")
            if not hmac.compare_digest(_jkt, dpop_jkt):
                raise ValueError(
                    "Le token est lie a une AUTRE cle que celle prouvee")
            # DECABLE le 2026-09-21, apres mesure. Ce point consultait le
            # ledger de cles (`forge_agent_keys`) pour TOUT `jkt`. C'etait un
            # DOMAINE TROP LARGE :
            #
            #   jkt = preuve de possession EPHEMERE  (DPoP generique, RFC 9449)
            #         -> le client genere sa cle, rien a enregistrer
            #   jkt = cle d'identite DURABLE geree   (TPM, ledger)
            #         -> statut ACTIVE/REVOKED pertinent
            #
            # `decode` ne recoit AUCUNE `credential_class` : il ne peut pas
            # distinguer les deux. Appliquer la politique de la seconde a la
            # premiere REFUSAIT un DPoP valide -- mesure par deux NR :
            # `test_jeton_lie_au_porteur_nr::test_le_bon_porteur_est_accepte`
            # rougissait, et il a RAISON dans son domaine.
            #
            # CE QUI RESTE, et c'est tout le binding P1 : `cnf.jkt` doit
            # correspondre a la cle prouvee (compare_digest ci-dessus), et un
            # jeton LIE sans preuve est refuse plus bas. Rien n'est affaibli
            # de ce qui etait deja consomme.
            #
            # CE QUI N'EST PAS SUPPRIME : `forge_agent_keys`, son ledger
            # persistant et ses 24 NR restent en place comme PRIMITIVE
            # PREPARATOIRE. Mesure du jour : `verify(dpop_jkt=...)` n'a AUCUN
            # appelant de production -- un seul appel dans tout le depot, celui
            # que ce cablage venait d'ecrire. On ne fabrique pas un
            # consommateur pour faire passer une CI.
            #
            # A REBRANCHER quand une classe de credential durable sera
            # effectivement TRANSPORTEE jusqu'a ce point de decision, et pas
            # avant. L'ordre juste est : emetteur -> provenance -> classe ->
            # politique. Ce cablage avait commence par la politique.
        elif _cnf.get("jkt"):
            # VOLET SYMETRIQUE, RFC 9449 §7.1 (ajoute le 2026-09-21).
            #
            # Le bloc ci-dessus ne verifiait le lien QUE si l'appelant fournit
            # une empreinte prouvee. Un jeton PORTEUR d'un `cnf.jkt` passait
            # donc sans aucune preuve des que l'appelant omettait `dpop_jkt` :
            # le lien se contournait EN NE LE PRESENTANT PAS. Un lien qu'on
            # peut ignorer ne lie rien, et « pas de lien » redevenait « bon
            # lien » -- exactement ce que le commentaire ci-dessus interdit.
            #
            # TAUX DE REFUS INDUIT MESURE : ZERO. Aucun jeton en circulation ne
            # porte `cnf.jkt`, car le seul appelant de production de
            # `login_agent` (forge_agent_credential) ne passe pas `dpop_jwk`.
            # Ce durcissement ne refuse donc aucun jeton existant -- precaution
            # du 2026-09-01 : ne jamais armer un refus sans mesurer son taux.
            #
            # PAS D'ECHAPPATOIRE ICI, et c'est voulu : lire un jeton SANS le
            # verifier a deja son chemin, `IntegrityManager.decode_raw`.
            raise ValueError(
                "Token LIE a une cle (cnf.jkt) mais aucune preuve de "
                "possession n'a ete fournie — presenter la preuve DPoP, ou "
                "utiliser decode_raw pour une lecture non verifiee")

        return cls(
            sub=str(payload.get("sub", "unknown")),
            ring=_ring,
            scopes=payload.get("scopes", {}),
            exp=exp,
            iat=_iat,
            jti=str(payload.get("jti", "")),
            seq=_seq,
            aud=_aud,
            iss=str(payload.get("iss", "")),
            cnf={str(k): str(v) for k, v in _cnf.items()},
        )

    def encode(self, secret: bytes, *, tpm_sign: bool = False,
               etat: Optional[dict] = None) -> str:
        """Sérialise le token. tpm_sign=True ajoute une signature matérielle TPM
        (AXE 8 PR-6) en 3e segment si le TPM est disponible — HMAC conservé pour
        interop offline. Best-effort : si TPM indispo, retombe sur HMAC seul."""
        payload = {
            "sub": self.sub,
            "ring": int(self.ring),
            "scopes": self.scopes,
            "exp": self.exp,
            "iat": self.iat,
            "jti": self.jti,
            "seq": self.seq,
        }
        # N'emettre `aud` que s'il est renseigne : un champ vide dans le payload
        # laisserait croire a une audience declaree. Et sans cette ligne, le champ
        # verifie au decodage n'aurait AUCUN emetteur -- le motif « garde branche sur
        # un signal que personne n'emet », deja paye deux fois.
        if self.aud:
            payload["aud"] = self.aud
        # `iss` -- RFC 9068 §2.2 (profil JWT des access tokens) et RFC 9207
        # (identification de l'emetteur, contre la confusion d'emetteur). Mesure
        # du 2026-09-02 : le claim etait ABSENT de tous les jetons emis. Sur un
        # deploiement local ca ne se voit pas ; des qu'un second emetteur
        # existe -- edge, federation, second hub -- un jeton devient
        # indiscernable de celui d'un autre. On l'emet DES MAINTENANT pour que
        # la verification ait un emetteur le jour ou elle sera exigee, plutot
        # que d'avoir a migrer un parc de jetons deja en circulation.
        if self.iss:
            payload["iss"] = self.iss
        # Meme raison pour `cnf` : sans emetteur, la verification du lien ci-dessus
        # n'aurait jamais rien a comparer et se lirait comme une protection active.
        if self.cnf:
            payload["cnf"] = self.cnf
        payload_b64 = (
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode("ascii")
        )
        sig = hmac.new(
            secret,
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        token = f"{payload_b64}.{sig}"
        if not tpm_sign:
            if etat is not None:
                etat.update({"tpm": TPM_NOT_REQUESTED, "cause": None})
            return token
        # `tpm_sign=True` etait une PREFERENCE best-effort : si la signature
        # echouait, le jeton partait SANS preuve et RIEN ne le disait. Mesure
        # du 2026-09-21 : `encode(tpm_sign=True)` rendait 2 segments au lieu
        # de 3, en silence. L'emetteur croyait produire un jeton signe
        # materiellement ; il produisait un jeton ordinaire -- et aucun
        # try/except de l'appelant ne pouvait le voir, faute d'erreur.
        #
        # REQUESTED != ACHIEVED. Le RETOUR ne change pas : on n'arme pas
        # `require_tpm` ici, et les 21 autres emetteurs (tpm_sign absent) ne
        # paient rien. Mais l'echec est desormais DIT, avec sa CAUSE.
        cause = "NON_MESURABLE"
        try:
            from nokido_agent.app.forge_persona_tpm import sign as _tpm_sign

            raw_sig = _tpm_sign(token.encode("ascii"))
            if raw_sig:
                tpm_b64 = base64.urlsafe_b64encode(raw_sig).rstrip(b"=").decode("ascii")
                if etat is not None:
                    etat.update({"tpm": TPM_REQUESTED_SIGNED, "cause": None})
                return f"{token}.{tpm_b64}"
            cause = _cause_echec_tpm()
        except Exception as e:  # noqa: BLE001
            cause = "ERREUR:%s" % type(e).__name__
        logger.warning(
            "[integrity] signature TPM DEMANDEE et NON OBTENUE (cause=%s) | "
            "consequence: ce jeton part SANS preuve materielle alors que son "
            "emetteur en a demande une — il serait refuse par tout "
            "verificateur exigeant le TPM", cause)
        if etat is not None:
            etat.update({"tpm": TPM_REQUESTED_FAILED, "cause": cause})
        return token

    def can(self, scope: str, action: str) -> bool:
        """Vérifie scope+action dans ce token."""
        return _scope_allows(self.scopes, scope, action)

    def portee_hors_du_pere(self, demande: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Ce que `demande` reclame et que CE jeton ne peut pas accorder.

        Rend {scope: [actions refusees]} -- vide si tout est couvert.
        Sert a DIRE l'ecart ; c'est `attenuer_ou_refuser` qui decide.
        """
        hors: Dict[str, List[str]] = {}
        for scope, actions in (demande or {}).items():
            permises = self.scopes.get(scope, [])
            if "*" in permises:
                continue
            refusees = [a for a in actions if a not in permises]
            if refusees:
                hors[scope] = refusees
        return hors

    def attenuate(self, new_scopes: Dict[str, List[str]], duration_s: Optional[float] = None) -> "CapabilityToken":
        """
        Crée un token dérivé avec des droits RÉDUITS (jamais étendus).
        Principe d'atténuation : un token fils ne peut pas avoir plus
        de droits que son parent.
        """
        # Intersection des scopes : on ne peut que restreindre
        attenuated: Dict[str, List[str]] = {}
        for scope, actions in new_scopes.items():
            parent_actions = self.scopes.get(scope, [])
            if "*" in parent_actions:
                attenuated[scope] = actions  # parent autorise tout
            else:
                # Intersection : seulement les actions que le parent permet
                allowed_parent = set(parent_actions)
                attenuated[scope] = [a for a in actions if a in allowed_parent or a == "*" and "*" in parent_actions]

        now = time.time()
        new_exp = min(
            self.exp,
            now + duration_s if duration_s else self.exp,
        )
        # Audit 2026-06-16 : Appliquer Time-Lock MASTER (300s) même sur les tokens atténués
        if self.ring == IntegrityRing.MASTER:
            new_exp = min(new_exp, self.iat + 300)

        return CapabilityToken(
            sub=self.sub,
            ring=self.ring,
            scopes=attenuated,
            exp=new_exp,
            iat=self.iat,  # On garde l'iat original pour que le Time-Lock (exp - iat) soit cohérent
            jti=secrets.token_hex(8),
            seq=self.seq,  # audit 2026-06-15 : seq manquant -> seq=0 -> token fils rejeté dès qu'une révocation existe
            # AUDIT 2026-09-22 : `iss` et `cnf` etaient PERDUS par l'attenuation.
            # Tous deux sont poses a l'emission depuis le 2026-09-02, et leur
            # disparition ne se voyait pas :
            #   `iss` (RFC 9068 §2.2) -- un jeton derive n'annoncait plus son
            #         emetteur ; invisible avec un hub unique, confusion
            #         d'emetteur des le second ;
            #   `cnf` (RFC 9449 §6) -- le lien au porteur tombait, donc le jeton
            #         fils redevenait un bearer rejouable depuis n'importe quel
            #         client. Pire : `decode` REFUSE un jeton sans `cnf` quand le
            #         lien est exige, donc l'attenuation pouvait rendre un jeton
            #         INUTILISABLE sans que rien ne le dise.
            #
            # Reduire une PORTEE ne doit dissoudre ni l'identite de l'emetteur,
            # ni le lien au porteur : ce sont des proprietes du jeton, pas des
            # droits.
            iss=self.iss,
            cnf=dict(self.cnf),
        )

    def ttl(self) -> float:
        """Secondes restantes avant expiration. Négatif = expiré."""
        return self.exp - time.time()

    def __repr__(self) -> str:
        """repr  ."""
        ttl = int(self.ttl())
        return f"CapabilityToken(sub={self.sub!r}, ring={self.ring.label()}, scopes={list(self.scopes)}, ttl={ttl}s)"


class TokenExpiredError(ValueError):
    """Token valide mais expiré."""

    pass


# ─────────────────────────────────────────────────────────────────────────────
# IntegrityManager — émission et vérification des tokens
# ─────────────────────────────────────────────────────────────────────────────


class IntegrityManager:
    """
    Autorité de confiance locale — émet et vérifie les tokens HMAC.
    Instancié avec le secret partagé (MCP_DEV_SECRET depuis Nokido.env).

    Usage brain_worker (démarrage) :
      mgr   = IntegrityManager.from_env()
      token = mgr.create_manifest("claude", IntegrityRing.DEV,
                                   scopes={"fs": ["*"], "rag": ["ingest"]})

    Usage sentinel (vérification) :
      ok, result = mgr.verify("fs", "write", token_str)
      if ok:
          ctx = result   # RingContext prêt à l'emploi
      else:
          reason = result  # str d'erreur
    """

    DEFAULT_DURATION = 8 * 3600  # 8h
    MASTER_TTL_S = 300           # 5 minutes max pour ring -1 (Time-Lock)

    def __init__(self, secret: str) -> None:
        """Initialise."""
        if not secret:
            raise ValueError("IntegrityManager requiert un secret non-vide")
        self._secret: bytes = secret.encode("utf-8")
        # P1 — Révocation par séquence
        # {agent_id: min_seq_required} — tout token avec seq < min est rejeté
        # Propagé via ZMQ PUB (TOPIC_LEDGER) dans brain_worker (future étape)
        self._revoked_seqs: Dict[str, int] = {}
        self._seq_counter: Dict[str, int] = {}  # {agent_id: last_issued_seq}
        # {agent_id: instant de revocation} -- tout jeton emis avant tombe.
        # Complete `_revoked_seqs`, qui dependait d'un compteur qu'un chemin
        # d'emission sur deux ne mettait pas a jour.
        self._revoked_after: Dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "IntegrityManager":
        """
        Charge le secret depuis MCP_DEV_SECRET (env ou Nokido.env).
        Génère un secret éphémère si absent (warn).
        """
        # IMPORT LOCAL EN TETE -- correction du 2026-09-02.
        # `get_secret` etait utilise ICI mais importe seulement plus bas dans la
        # meme fonction : Python le traite alors comme LOCAL partout, et le
        # premier usage levait `UnboundLocalError`. Consequence mesuree, et elle
        # est lourde : `get_manager()` echouait des qu'on l'appelait hors du
        # process du hub, donc TOUT le systeme CapabilityToken -- expiration,
        # revocation, anti-replay, binding -- etait inatteignable pour les
        # organes. Le mecanisme existait et ne pouvait servir a personne.
        # C'est le meme motif que le piege consigne le 2026-08-31 sur un autre
        # module : un import local vaut pour TOUTE la fonction, pas a partir de
        # sa ligne.
        try:
            from nokido_agent.app.forge_secrets import get_secret  # noqa: F811
        except Exception:  # noqa: BLE001
            def get_secret(_k):  # type: ignore[misc]
                # Coffre indisponible : on le DIT par le repli plutot que de
                # laisser une exception masquer la cause reelle plus bas.
                return ""

        # Le GUICHET seul (2b-2, 2026-09-28) : il lit le coffre reserve, le coffre machine
        # (incident 2026-06-20 : secret migre hors Nokido.env) PUIS `Nokido.env`. Le parseur
        # maison et le second appel identique qui suivaient lisaient un nom RESERVE hors du
        # guichet, ou refaisaient le meme appel.
        secret = get_secret("MCP_DEV_SECRET") or ""
        if not secret:
            secret = secrets.token_hex(32)
            logger.warning(
                "[integrity] MCP_DEV_SECRET absent — secret éphémère généré. "
                "Les tokens ne survivront pas au redémarrage du brain_worker."
            )
        return cls(secret)

    def create_manifest(
        self,
        agent_id: str,
        ring: IntegrityRing,
        scopes: Optional[Dict[str, List[str]]] = None,
        duration_s: int = DEFAULT_DURATION,
    ) -> str:
        """
        Émet un token de capacité signé.

        Args:
            agent_id:   Identifiant de l'agent (ex: "claude", "workflow:audit")
            ring:       Niveau d'intégrité (IntegrityRing.DEV, etc.)
            scopes:     Permissions explicites. Si None → scopes par défaut du ring.
            duration_s: Durée de validité en secondes (défaut 8h).

        Returns:
            Token sérialisé : "{payload_b64}.{hmac_hex}"
        """
        now = time.time()
        # Incrémenter le compteur de séquence pour cet agent
        self._seq_counter[agent_id] = self._seq_counter.get(agent_id, 0) + 1
        seq = self._seq_counter[agent_id]

        # Ring MASTER : TTL forcé à MASTER_TTL_S même si duration_s > MASTER_TTL_S
        # Protège contre les sessions MASTER (sudo) laissées ouvertes par erreur.
        effective_duration = duration_s
        if ring == IntegrityRing.MASTER:
            effective_duration = min(duration_s, self.MASTER_TTL_S)

        token = CapabilityToken(
            sub=agent_id,
            ring=ring,
            scopes=scopes if scopes is not None else ring.default_scopes(),
            exp=now + effective_duration,
            iat=now,
            jti=secrets.token_hex(8),  # anti-replay
            seq=seq,
            # Emetteur pose A L'EMISSION -- RFC 9068 §2.2 / RFC 9207. Il porte
            # l'identite de CETTE instance : plusieurs hubs (edge, federation)
            # emettraient sinon des jetons indiscernables. Reglable pour ne pas
            # figer un nom d'hote dans le code.
            # Cf. `forge_auth_tokens` : l'emetteur est PUBLIC (RFC 9068 §2.2),
            # il voyage en clair dans le jeton. Le nom `_TOKEN_ISS` faisait
            # crier la regle `cloud-secret-from-env` sur ce qui n'est pas un
            # secret, et un garde qui crie a faux finit desarme.
            iss=os.environ.get("LAFORGE_JWT_ISSUER", "nokido-hub-local"),
            # `aud` reste vide ici : declarer une audience qu'aucun verificateur
            # ne controle serait une garantie de facade. Elle se posera avec le
            # controle qui la lit, pas avant -- meme discipline que `cnf`.
        )
        serialized = token.encode(self._secret)

        if ring == IntegrityRing.MASTER:
            logger.warning(
                f"[integrity] ⚠ MASTER manifest émis: sub={agent_id!r} ttl={int(effective_duration)}s (forcé) scopes={list(token.scopes)}"
            )
        else:
            logger.info(
                f"[integrity] manifest émis: sub={agent_id!r} "
                f"ring={ring.label()} scopes={list(token.scopes)} "
                f"ttl={duration_s}s"
            )
        return serialized

    def create_master_token(
        self,
        agent_id: str = "MASTER_OVERRIDE",
    ) -> str:
        """
        Émet un token MASTER (ring=-1) avec TTL 5min forcé.
        Scopes complets y compris 'master' (purge_all, rollback, override...).
        À utiliser UNIQUEMENT depuis la TUI ou un appel nokido interne.
        Jamais transmis aux agents externes.
        """
        return self.create_manifest(
            agent_id=agent_id,
            ring=IntegrityRing.MASTER,
            scopes=IntegrityRing.MASTER.default_scopes(),
            duration_s=self.MASTER_TTL_S,
        )

    def is_master(self, token_str: str) -> bool:
        """
        Vérifie si le token est un token MASTER valide (ring=-1, non expiré).
        """
        try:
            token = CapabilityToken.decode(token_str, self._secret)
            return token.ring == IntegrityRing.MASTER and token.exp > time.time()
        except Exception:
            return False

    def require_master(
        self,
        token_str: str,
        action: str,
        sentinel_ok: bool = False,
    ) -> Tuple[bool, str]:
        """
        Exige un token MASTER pour une action privilégiée.

        Args:
            token_str  : token sérialisé à vérifier
            action     : action demandée (pour l'audit)
            sentinel_ok: si True, autorise aussi ring=SYSTEM (ring=0)

        Returns:
            (True, "") si autorisé, (False, raison) sinon.
        """
        try:
            token = CapabilityToken.decode(token_str, self._secret)
        except Exception as e:
            return False, f"Token invalide : {e}"

        if token.exp <= time.time():
            return False, "Token MASTER expiré (TTL 5min) — relancer @sudo"

        required_ring = IntegrityRing.SYSTEM if sentinel_ok else IntegrityRing.MASTER
        if not is_at_least(token.ring, required_ring):
            return False, (f"Action '{action}' réservée au MASTER — ring={token.ring.label()} insuffisant")

        # Vérifier le scope 'master' si l'action l'exige
        if action in (IntegrityRing.MASTER.default_scopes().get("master") or set()):
            master_scopes = token.scopes.get("master", [])
            if "*" not in master_scopes and action not in master_scopes:
                return False, f"Scope 'master:{action}' absent du token"

        logger.info(f"[integrity] MASTER action autorisée: {action} sub={token.sub}")
        return True, ""

    def verify(
        self,
        scope: str,
        action: str,
        token_str: str,
        dpop_jkt: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """
        Vérifie un token et l'autorisation scope+action.

        Returns:
            (True, RingContext)  si autorisé
            (False, str_reason)  si refusé
        """
        # 1. Décodage et validation cryptographique
        try:
            # `dpop_jkt` est l'empreinte de la cle dont l'APPELANT a deja prouve
            # la possession ; `verify` ne verifie aucune signature. Defaut None
            # = chemin bearer INCHANGE : aucune exigence TPM n'est ajoutee au
            # trafic non lie. Sans ce parametre, le chemin lie etait
            # inatteignable depuis `verify` et le cablage du ledger serait
            # reste decoratif -- le defaut que P4.3.4-C signalait.
            token = CapabilityToken.decode(token_str, self._secret,
                                           dpop_jkt=dpop_jkt)
        except TokenExpiredError as e:
            return False, f"Token expiré: {e}"
        except ValueError as e:
            return False, f"Token invalide: {e}"

        # 2. Vérification révocation par séquence (P1)
        # REVOCATION PAR INSTANT D'EMISSION -- ajoutee le 2026-09-02.
        # Le mecanisme par `seq` NE FONCTIONNAIT PAS, mesure : `login_agent`
        # emet un jeton `seq=1` sans incrementer `_seq_counter`, qui reste a 0 ;
        # `revoke()` posait donc `min_seq = 0 + 1 = 1`, et la comparaison
        # `token.seq(1) < min_seq(1)` est FAUSSE -- le jeton revoque restait
        # valide. Un garde present, appele, et sans effet.
        # Le temps ne depend d'aucun compteur tenu par un seul chemin
        # d'emission : tout jeton emis AVANT l'instant de revocation tombe,
        # quel que soit le module qui l'a cree.
        # La revocation vit en UN endroit (`_raison_revocation`, 2026-09-28) : le
        # renouvellement des jetons courts la lit aussi.
        _raison = self._raison_revocation(token)
        if _raison:
            return False, _raison

        # 3. Vérification scope+action dans les capacités du token
        if not token.can(scope, action):
            required = SCOPE_REQUIRED_RING.get((scope, action), IntegrityRing.TRUSTED)
            return False, (
                f"Action '{action}' non autorisée dans scope '{scope}' "
                f"(ring {token.ring.label()}, ring requis: {required.label()})"
            )

        # 3. Vérification ring minimum pour cette action
        required_ring = SCOPE_REQUIRED_RING.get((scope, action), IntegrityRing.TRUSTED)
        if not is_at_least(token.ring, required_ring):
            return False, (
                f"Ring insuffisant: {token.ring.label()} < {required_ring.label()} requis pour {scope}/{action}"
            )

        # 4. Succès → contexte d'exécution
        ctx = RingContext(
            ring=token.ring,
            agent_id=token.sub,
            session_id=token.jti,
            token=token,
        )
        return True, ctx

    def _raison_revocation(self, token: "CapabilityToken") -> str:
        """Motif de revocation d'un jeton deja DECODE, ou chaine vide.

        Source unique, lue par `verify` et par le renouvellement des jetons courts
        (`forge_auth_tokens.renouveler`, 2026-09-28) : deux copies de ce controle
        divergeraient, et un jeton revoque se renouvellerait en silence."""
        _apres = self._revoked_after.get(token.sub, 0.0)
        if _apres and float(getattr(token, "iat", 0.0)) <= _apres:
            return (f"Token révoqué : émis à {int(getattr(token, 'iat', 0))} "
                    f"≤ révocation à {int(_apres)}")
        min_seq = self._revoked_seqs.get(token.sub, 0)
        if token.seq < min_seq:
            return (f"Token révoqué : seq={token.seq} < min_seq={min_seq} "
                    f"pour agent '{token.sub}' — réémettre un nouveau manifest")
        return ""

    def revoke(self, agent_id: str, min_seq: Optional[int] = None) -> int:
        """
        Révoque tous les tokens de `agent_id` avec seq < min_seq.
        Si min_seq est None → utilise seq_courant+1 (révoque TOUT).

        Retourne le min_seq effectif appliqué.
        Propagation future : ZMQ PUB TOPIC_LEDGER
          pub_fn(TOPIC_LEDGER, {'revoke': agent_id, 'min_seq': min_seq})
        """
        if min_seq is None:
            min_seq = self._seq_counter.get(agent_id, 0) + 1
        self._revoked_seqs[agent_id] = max(self._revoked_seqs.get(agent_id, 0), min_seq)
        # Barriere TEMPORELLE, posee en meme temps : elle rend la revocation
        # effective meme quand `_seq_counter` n'a pas suivi l'emission -- ce qui
        # est le cas de `login_agent`. Sans elle, `revoke()` rendait un min_seq
        # d'apparence correcte sans rien revoquer du tout.
        self._revoked_after[agent_id] = max(
            self._revoked_after.get(agent_id, 0.0), time.time())
        logger.info(f"[integrity] revoke agent='{agent_id}' min_seq={self._revoked_seqs[agent_id]}")
        return self._revoked_seqs[agent_id]

    def revoke_status(self) -> Dict[str, int]:
        """Retourne la table de révocation {agent_id: min_seq_requis}."""
        return dict(self._revoked_seqs)

    def decode_raw(self, token_str: str) -> Optional[CapabilityToken]:
        """Décode un token sans vérifier de permission spécifique. None si invalide."""
        try:
            return CapabilityToken.decode(token_str, self._secret)
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# RingContext — contexte d'exécution porté par les appels
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RingContext:
    """
    Contexte d'intégrité porté d'un bout à l'autre d'un appel.
    Créé par IntegrityManager.verify() — ne jamais instancier directement
    sauf pour les contextes internes SYSTEM.

    Porté par :
      - Appels MCP (injecté depuis _get_agent_id + verify)
      - Ingestions RAG (enrichit le meta JSON)
      - Logs d'audit (traçabilité ring → consensus)
    """

    ring: IntegrityRing
    agent_id: str
    session_id: str = ""
    source_ip: str = ""
    token: Optional[CapabilityToken] = field(default=None, repr=False)
    created_at: float = field(default_factory=time.time)

    # ── Capacités dérivées du token ───────────────────────────────────────────

    def can(self, scope: str, action: str) -> bool:
        """
        Vérifie scope+action.
        Si un token est présent → vérification précise dans les scopes.
        Sinon (contexte SYSTEM interne) → basé uniquement sur le ring.
        """
        if self.token is not None:
            return self.token.can(scope, action)
        # Fallback sans token (appels internes SYSTEM)
        if not is_at_least(self.ring, IntegrityRing.TRUSTED):
            return False
        required = SCOPE_REQUIRED_RING.get((scope, action), IntegrityRing.TRUSTED)
        return is_at_least(self.ring, required)

    def assert_can(self, scope: str, action: str) -> None:
        """Lève PermissionError si l'action est interdite."""
        if not self.can(scope, action):
            required = SCOPE_REQUIRED_RING.get((scope, action), IntegrityRing.TRUSTED)
            raise PermissionError(
                f"Ring {self.ring.label()} ({self.agent_id}) refusé "
                f"pour '{scope}/{action}' — ring {required.label()} requis"
            )

    @property
    def bypass_sentinel(self) -> bool:
        """True si la sentinel passe en mode audit (log sans bloquer)."""
        return is_at_least(self.ring, IntegrityRing.DEV) and self.can("system", "sentinel_bypass")

    @property
    def rag_consensus(self) -> str:
        """Rag consensus."""
        return self.ring.consensus_level()

    # ── Signature RAG ─────────────────────────────────────────────────────────

    def rag_author_tag(self) -> str:
        """
        Tag auteur structuré pour rag_chunks.author.
        Format : "{ring_label}:{agent_id}:{session_id[:16]}"
        Exemple : "dev:claude:a3f9b2c1"
        """
        sid = (self.session_id or "nosession")[:16]
        return f"{self.ring.label().lower()}:{self.agent_id}:{sid}"

    def rag_meta_patch(self) -> Dict[str, Any]:
        """
        Patch JSON à merger dans rag_chunks.meta.
        Ajoute ring, consensus_level, ingested_by, ingested_at, ttl_remaining.
        """
        ttl = int(self.token.ttl()) if self.token else -1
        return {
            "ring": int(self.ring),
            "ring_label": self.ring.label(),
            "consensus_level": self.rag_consensus,
            "ingested_by": self.agent_id,
            "ingested_at": self.created_at,
            "token_ttl": ttl,
        }

    # ── Constructeurs nommés ──────────────────────────────────────────────────

    @classmethod
    def system(cls) -> "RingContext":
        """Contexte SYSTEM pour les appels internes Nokido (pas de token)."""
        return cls(ring=IntegrityRing.SYSTEM, agent_id="laforge")

    @classmethod
    def untrusted(cls, agent_id: str = "unknown") -> "RingContext":
        """Contexte UNTRUSTED pour les agents sans token valide."""
        return cls(ring=IntegrityRing.UNTRUSTED, agent_id=agent_id)

    def __repr__(self) -> str:
        """repr  ."""
        return f"RingContext(ring={self.ring.label()}, agent={self.agent_id!r}, session={self.session_id or '-'!r})"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers module-level pour compatibilité avec forge_mcp_security
# ─────────────────────────────────────────────────────────────────────────────


def resolve_ring_from_token(token_str: str, secret: str) -> IntegrityRing:
    """
    Résout le ring depuis un token sérialisé.
    Retourne UNTRUSTED si le token est invalide ou absent.
    """
    if not token_str or not secret:
        return IntegrityRing.UNTRUSTED
    try:
        token = CapabilityToken.decode(token_str, secret.encode())
        return token.ring
    except Exception:
        return IntegrityRing.UNTRUSTED


# Singleton manager — chargé depuis l'env au premier accès
_manager: Optional[IntegrityManager] = None


def get_manager() -> IntegrityManager:
    """Singleton IntegrityManager chargé depuis MCP_DEV_SECRET."""
    global _manager
    if _manager is None:
        _manager = IntegrityManager.from_env()
    return _manager


# ═══════════════════════════════════════════════════════════════════════════
# DÉCORATEURS SÉCURITÉ — Security by Design
# ═══════════════════════════════════════════════════════════════════════════

import functools
import asyncio as _asyncio


def require_ring(level: int, message: str = "") -> str:
    """
    Décorateur de sécurité — vérifie le ring actif avant d'exécuter.

    Usage:
        @require_ring(1)
        async def my_handler(app, ...):
            ...

        @require_ring(0, "Réservé RING_0")
        def sensitive_function(app, ...):
            ...

    Le premier argument de la fonction décorée doit être `app` (ou `self`)
    avec un attribut `guard` qui expose `active_ring`.
    """

    def decorator(func) -> str:
        """Decorator."""

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> str:
            """Async wrapper."""
            # Extraire l'objet app/self (premier arg)
            app = args[0] if args else None
            active = getattr(getattr(app, "guard", None), "active_ring", 0)
            if active > level:
                msg = message or f"Action réservée Ring≤{level} (actif: Ring{active})"
                # Log si possible
                try:
                    chat = app._chat_log() if hasattr(app, "_chat_log") else None
                    if chat:
                        chat.write(f"[red]🔒 {msg}[/]")
                except Exception:
                    pass
                return f"INTERDIT: {msg}"
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> str:
            """Sync wrapper."""
            app = args[0] if args else None
            active = getattr(getattr(app, "guard", None), "active_ring", 0)
            if active > level:
                msg = message or f"Action réservée Ring≤{level} (actif: Ring{active})"
                return f"INTERDIT: {msg}"
            return func(*args, **kwargs)

        if _asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def capability_required(*caps: str) -> str:
    """
    Décorateur — vérifie que les capabilities (HAS_X) sont disponibles.

    Usage:
        @capability_required("HAS_SNIF", "HAS_IDS")
        async def handle_scan(app, ...):
            ...
    """

    def decorator(func) -> str:
        """Decorator."""

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> str:
            """Async wrapper."""
            app = args[0] if args else None
            for cap in caps:
                # Chercher dans le module global ou dans app
                from nokido_agent.app import forge_capabilities as _fc

                if not _fc.check(cap):
                    return f"INDISPONIBLE: {cap} requis pour cette action"
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> str:
            """Sync wrapper."""
            for cap in caps:
                from nokido_agent.app import forge_capabilities as _fc

                if not _fc.check(cap):
                    return f"INDISPONIBLE: {cap} requis"
            return func(*args, **kwargs)

        if _asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Alias court
ring = require_ring
cap = capability_required
