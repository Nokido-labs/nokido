"""forge_oauth_clients.py - autorite des CLIENTS OAuth du hub (E3 du plan docs/PLAN_OAUTH_MCP_HUB_20261102.md).

Owner 2-3/11 : « le OAuth doit venir de Nokido, les clients sont interchangeables » ; « reste conforme RFC » ;
« pousser la chaine d'authentification jusqu'au TPM ».

POURQUOI UN MODULE A PART. `forge_oauth_route` porte les validateurs PURS (inscription, autorisation, PKCE) et les
metadonnees ; ici vit l'ETAT : clients inscrits, demandes en attente de consentement, codes a usage unique,
renouvellements tournants, revocations. Une seule autorite (le hub) : aucun autre emetteur n'est cree.

CE QUE L'ETAT CONTIENT -- ET CE QU'IL NE CONTIENT PAS. Les codes et les renouvellements sont gardes par EMPREINTE
(SHA-256) : le disque ne porte jamais de quoi les rejouer. Les jetons d'acces ne sont pas stockes : ils sont SIGNES
(JWS ES256, `forge_signature_hub`, cle TPM de l'identite declaree HUB) et se verifient par la cle publique.

Normes appliquees (NR tests/nr/test_oauth_e3_autorite_nr.py) :
  RFC 6749 §4.1.2/§4.1.3/§5.2 (code unique et court, rejeu = revocation, erreurs) ; RFC 7636 (PKCE) ;
  RFC 8707 (resource) ; RFC 9207 (`iss` dans la reponse d'autorisation) ; OAuth 2.1 §4.3.1 (renouvellement tournant,
  famille revoquee si un ancien resurgit) ; RFC 7009 (revocation, 200 meme inconnu) ; RFC 9068 (jeton d'acces JWT).
Le consentement (E4) passe par `accorder` / `refuser` ; ce module ne decide jamais seul d'accorder.
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/autorisation-clients-oauth : etat de l'autorite OAuth du hub (codes, renouvellements)"

import hashlib
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlencode

from app import forge_oauth_route as _R
from app import forge_signature_hub as _S

DUREE_DEMANDE_S = 600          # attente du consentement owner
DUREE_CODE_S = 300             # RFC 6749 §4.1.2 : courte
DUREE_ACCES_S = 3600
DUREE_RENOUVELLEMENT_S = 30 * 86400
# Owner 7/11 : aucune tolerance au rejeu, la fenetre de 30 s du 6/11 etait une faille. Un renouvellement deja tourne
# qui resurgit revoque la famille (OAuth 2.1). Le parallelisme passe par un profil et un client par slot.


def dossier_defaut() -> Path:
    """`racine_donnees()/sandbox/oauth_clients` (jamais derive de __file__ : paquet installe = donnees utilisateur)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        from app.forge_db_path import racine_donnees
    return racine_donnees() / "sandbox" / "oauth_clients"


def _h(secret: str) -> str:
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def _emettre_alerte(sujet: str, gravite: str, detail: str, emetteur: str) -> str:
    """Canal existant : forge_critical_events.alerter_owner, lu par `hub action=alertes`."""
    try:
        from nokido_agent.app import forge_critical_events as ce
    except ImportError:
        from app import forge_critical_events as ce
    return ce.alerter_owner(sujet, gravite, detail, emetteur)


class AutoriteClientsHub:
    def __init__(self, dossier, signataire, ressource: str, emetteur: str,
                 horloge: Callable[[], float] = time.time, ressources_annexes: Optional[Dict[str, Any]] = None):
        self._d = Path(dossier)
        self._d.mkdir(parents=True, exist_ok=True)
        self._sig = signataire
        self._res = ressource
        # Lot P1 (3/11) : ressources servies par d'AUTRES serveurs (pont des pairs) -> {url: portees}. Le hub ne
        # verifie jamais leurs jetons pour lui-meme (verifier_acces sans `ressource` = audience du hub seule).
        self._ressources = {ressource: {_R.PORTEE_HUB}}
        self._ressources.update({str(r): set(p) for r, p in (ressources_annexes or {}).items()})
        self._iss = emetteur.rstrip("/")
        self._t = horloge
        self._verrou = threading.Lock()
        self._clients: Dict[str, Dict[str, Any]] = self._lire("clients.json", {})
        self._renouv: Dict[str, Dict[str, Any]] = self._lire("renouvellements.json", {})
        self._renouv_utilises: Dict[str, str] = self._lire("renouvellements_utilises.json", {})
        self._familles_revoquees = set(self._lire("familles_revoquees.json", []))
        self._jti_revoques: Dict[str, float] = self._lire("jti_revoques.json", {})
        self._demandes: Dict[str, Dict[str, Any]] = {}
        self._codes: Dict[str, Dict[str, Any]] = {}

    # ── persistance (ecriture atomique) ──────────────────────────────────────────────────────────────────────
    def _lire(self, nom: str, defaut):
        p = self._d / nom
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return defaut
        except (OSError, ValueError) as exc:
            # ILLISIBLE n'est pas VIDE : on refuse de repartir d'un etat vide qui rouvrirait des acces revoques
            raise RuntimeError("etat OAuth illisible (%s : %s)" % (nom, type(exc).__name__)) from exc

    def _ecrire(self, nom: str, valeur) -> None:
        p = self._d / nom
        tmp = p.with_name("%s.%d.tmp" % (nom, os.getpid()))
        tmp.write_text(json.dumps(valeur, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def _persister(self) -> None:
        self._ecrire("renouvellements.json", self._renouv)
        self._ecrire("renouvellements_utilises.json", self._renouv_utilises)
        self._ecrire("familles_revoquees.json", sorted(self._familles_revoquees))
        self._ecrire("jti_revoques.json", self._jti_revoques)

    # ── inscription (RFC 7591) ───────────────────────────────────────────────────────────────────────────────
    def inscrire(self, meta: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        client, err = _R.valider_inscription(meta)
        if err:
            return None, err
        with self._verrou:
            self._clients[client["client_id"]] = client
            self._ecrire("clients.json", self._clients)
        return client, None

    def client(self, client_id: str) -> Optional[Dict[str, Any]]:
        return self._clients.get(client_id)

    # ── autorisation + consentement ──────────────────────────────────────────────────────────────────────────
    def _redirection(self, uri: str, params: Dict[str, Any]) -> str:
        q = {k: v for k, v in params.items() if v is not None}
        q["iss"] = self._iss                                   # RFC 9207 §2
        return uri + ("&" if "?" in uri else "?") + urlencode(q)

    def demander_autorisation(self, params: Dict[str, Any]):
        """-> (id_demande, None, True, None) ou (None, code, peut_rediriger, url_d_erreur_ou_None)."""
        demande, err, peut = _R.valider_autorisation(params, self._clients, self._ressources)
        if err:
            url = self._redirection(params["redirect_uri"], {"error": err, "state": params.get("state")}) \
                if peut else None
            return None, err, peut, url
        ident = secrets.token_urlsafe(16)
        demande.update(etat="en_attente_consentement", cree=self._t())
        with self._verrou:
            self._demandes[ident] = demande
        return ident, None, True, None

    def demande(self, ident: str) -> Optional[Dict[str, Any]]:
        return self._demandes.get(ident)

    def _prendre_demande(self, ident: str) -> Dict[str, Any]:
        with self._verrou:
            d = self._demandes.pop(ident, None)
        if d is None or self._t() - d["cree"] > DUREE_DEMANDE_S:
            raise ValueError("demande d'autorisation inconnue ou expiree")
        return d

    def accorder(self, ident: str, identite: str, ring: int) -> str:
        """Consentement owner ACCORDE : code a usage unique (300 s) lie au client, a la redirection, au PKCE."""
        d = self._prendre_demande(ident)
        code = secrets.token_urlsafe(32)
        with self._verrou:
            self._codes[_h(code)] = dict(d, identite=identite, ring=int(ring), exp=self._t() + DUREE_CODE_S,
                                         utilise=False, famille=None)
        return self._redirection(d["redirect_uri"], {"code": code, "state": d.get("state")})

    def refuser(self, ident: str) -> str:
        d = self._prendre_demande(ident)
        return self._redirection(d["redirect_uri"], {"error": "access_denied", "state": d.get("state")})

    # ── point de jeton (RFC 6749 §3.2) ───────────────────────────────────────────────────────────────────────
    @staticmethod
    def _err(code: str, desc: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
        corps = {"error": code}
        if desc:
            corps["error_description"] = desc
        return 400, corps

    def jeton(self, form: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        flot = form.get("grant_type")
        if flot == "authorization_code":
            return self._par_code(form)
        if flot == "refresh_token":
            return self._par_renouvellement(form)
        return self._err("unsupported_grant_type")

    def _par_code(self, f: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if not all(f.get(k) for k in ("code", "redirect_uri", "client_id", "code_verifier")):
            return self._err("invalid_request", "code, redirect_uri, client_id et code_verifier sont requis")
        with self._verrou:
            rec = self._codes.get(_h(f["code"]))
            if rec is None:
                return self._err("invalid_grant")
            if rec["utilise"]:
                # RFC 6749 §4.1.2 : un code rejoue revoque les jetons emis a partir de lui
                if rec.get("famille"):
                    self._familles_revoquees.add(rec["famille"])
                    self._persister()
                return self._err("invalid_grant", "code deja utilise")
            if self._t() > rec["exp"]:
                return self._err("invalid_grant", "code expire")
            if f["client_id"] != rec["client_id"] or f["redirect_uri"] != rec["redirect_uri"]:
                return self._err("invalid_grant")
            if not _R.verifier_pkce(f["code_verifier"], rec["code_challenge"]):
                return self._err("invalid_grant", "verifier PKCE invalide")
            if f.get("resource", rec["resource"]) != rec["resource"]:
                return self._err("invalid_target")
            rec["utilise"] = True
            rec["famille"] = secrets.token_urlsafe(9)
            return 200, self._emettre(rec, rec["famille"])

    def _emettre(self, rec: Dict[str, Any], famille: str) -> Dict[str, Any]:
        """Jeton d'acces JWS ES256 (RFC 9068) + renouvellement tournant (empreinte seule sur disque)."""
        maintenant = int(self._t())
        charge = {"iss": self._iss, "sub": rec["identite"], "aud": rec["resource"], "client_id": rec["client_id"],
                  "scope": rec["scope"], "ring": rec["ring"], "iat": maintenant, "exp": maintenant + DUREE_ACCES_S,
                  "jti": secrets.token_urlsafe(12), "fam": famille}
        acces = _S.emettre_jws(charge, self._sig)
        suite = secrets.token_urlsafe(32)
        self._renouv[_h(suite)] = {"client_id": rec["client_id"], "identite": rec["identite"], "ring": rec["ring"],
                                   "scope": rec["scope"], "resource": rec["resource"], "famille": famille,
                                   "exp": maintenant + DUREE_RENOUVELLEMENT_S}
        self._persister()
        return {"access_token": acces, "token_type": "Bearer", "expires_in": DUREE_ACCES_S,
                "refresh_token": suite, "scope": rec["scope"]}

    def _signaler_revocation(self, client_id: str) -> None:
        """Alerte a la chute d'une famille : le nom du client, jamais un jeton ni une empreinte. 6/11 : AGY a tourne
        3 h 35 sans le hub sans que rien ne le dise. Une panne de l'alerte ne casse jamais l'OAuth. Seul le vrai magasin
        alerte : le 6/11 a 15:19, les NR ont envoye a l'owner une revocation du client de fixture « VS Code »."""
        if Path(self._d).resolve() != Path(dossier_defaut()).resolve():
            return
        nom = str((self._clients.get(client_id) or {}).get("client_name") or "client inconnu")[:80]
        try:
            _emettre_alerte("oauth:famille_revoquee:" + nom, "high",
                            "famille OAuth revoquee (renouvellement rejoue) pour le client %s : "
                            "il perd le hub jusqu'a sa reautorisation" % nom, "forge_oauth_clients")
        except Exception as exc:  # noqa: BLE001 - muet-ok : dit sur stderr, l'OAuth doit repondre
            print("[oauth] alerte de revocation non emise : %s" % type(exc).__name__, file=sys.stderr)

    def _par_renouvellement(self, f: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if not f.get("refresh_token") or not f.get("client_id"):
            return self._err("invalid_request", "refresh_token et client_id sont requis")
        h = _h(f["refresh_token"])
        with self._verrou:
            rec = self._renouv.get(h)
            if rec is None:
                famille = self._renouv_utilises.get(h)
                if famille:
                    # OAuth 2.1 §4.3.1 : un renouvellement deja tourne qui resurgit = fuite ; toute la famille tombe
                    self._familles_revoquees.add(famille)
                    self._persister()
                    self._signaler_revocation(f["client_id"])
                return self._err("invalid_grant")
            if rec["famille"] in self._familles_revoquees or self._t() > rec["exp"] \
                    or f["client_id"] != rec["client_id"]:
                return self._err("invalid_grant")
            demandees = set((f.get("scope") or rec["scope"]).split())
            if not demandees <= set(rec["scope"].split()):
                return self._err("invalid_scope")
            del self._renouv[h]
            self._renouv_utilises[h] = rec["famille"]
            return 200, self._emettre(dict(rec, scope=" ".join(sorted(demandees))), rec["famille"])

    # ── revocation (RFC 7009) et verification (E5) ───────────────────────────────────────────────────────────
    def revoquer(self, f: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        jeton = f.get("token")
        if not jeton:
            return self._err("invalid_request", "token requis")
        with self._verrou:
            rec = self._renouv.get(_h(jeton))
            if rec is not None:
                if rec["client_id"] == f.get("client_id"):
                    # RFC 7009 §2.1 : revoquer le renouvellement invalide aussi les acces du meme octroi
                    self._familles_revoquees.add(rec["famille"])
                    self._renouv.pop(_h(jeton), None)
                    self._persister()
                return 200, {}
            charge, _motif = _S.verifier_jws(jeton, self._cles())
            if charge and charge.get("client_id") == f.get("client_id") and charge.get("jti"):
                self._jti_revoques[charge["jti"]] = charge.get("exp", 0)
                self._persister()
        return 200, {}                                   # §2.2 : jeton inconnu ou invalide -> 200 aussi

    def revoquer_client(self, client_id: str) -> Dict[str, Any]:
        """3/11 (owner « fais revoquer_client ») : coupe un CLIENT entier -- toutes ses familles de jetons revoquees
        (tout jeton d'acces existant refuse a l'appel suivant, renouvellements morts), inscription retiree, codes et
        demandes en attente purges. Politique du serveur d'autorisation (RFC 7009 §2.2 ; retrait d'inscription admis
        par RFC 7591/7592). Declenche par une DECISION owner au tray (forge_ordres_bureau), jamais par une route.
        NR : tests/nr/test_oauth_revoquer_client_nr.py
        """
        with self._verrou:
            if client_id not in self._clients:
                return {"ok": False, "raison": "client inconnu : %s" % str(client_id)[:40]}
            familles = {r["famille"] for r in self._renouv.values() if r.get("client_id") == client_id}
            familles |= {r["famille"] for r in self._codes.values()
                         if r.get("client_id") == client_id and r.get("famille")}
            retires = [h for h, r in self._renouv.items() if r.get("client_id") == client_id]
            for h in retires:
                del self._renouv[h]
            self._familles_revoquees |= familles
            for h in [h for h, r in self._codes.items() if r.get("client_id") == client_id]:
                del self._codes[h]
            for i in [i for i, d in self._demandes.items() if d.get("client_id") == client_id]:
                del self._demandes[i]
            del self._clients[client_id]
            self._ecrire("clients.json", self._clients)
            self._persister()
        return {"ok": True, "client_id": client_id, "familles_revoquees": len(familles),
                "renouvellements_retires": len(retires), "inscription_retiree": True}

    def _cles(self) -> Dict[str, Dict[str, Any]]:
        return {self._sig.kid: self._sig.jwk_publique()}

    def verifier_acces(self, jeton: str, ressource: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """`ressource` absente = le hub lui-meme. Un serveur annexe (pont) passe SA ressource, qui doit etre declaree."""
        attendue = self._res if ressource is None else ressource
        if attendue not in self._ressources:
            return None, "ressource non declaree (RFC 8707)"
        charge, motif = _S.verifier_jws(jeton, self._cles())
        if motif:
            return None, motif
        if charge.get("iss") != self._iss:
            return None, "emetteur non reconnu"
        if charge.get("aud") != attendue:
            return None, "audience hors ressource (RFC 8707)"
        if self._t() >= charge.get("exp", 0):
            return None, "jeton expire"
        if charge.get("jti") in self._jti_revoques:
            return None, "jeton revoque"
        if charge.get("fam") in self._familles_revoquees:
            return None, "octroi revoque"
        return charge, None

    def jwks(self) -> Dict[str, Any]:
        """RFC 7517 : jeu de cles publiques (kid = empreinte RFC 7638), sans aucune partie privee."""
        return {"keys": [dict(self._sig.jwk_publique(), kid=self._sig.kid, alg=_S.ALG, use="sig")]}
