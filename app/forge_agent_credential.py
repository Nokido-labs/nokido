"""Credential d'un organe : jeton COURT plutot que secret permanent.

__FORGE_COLOR__ = "immunitaire/cycle-de-vie-des-credentials"

CE QUE CE MODULE RESOUT, et il ne construit rien de neuf.

Les quatre durcissements reclames par la revue avant toute exposition --
expiration, revocation, anti-replay, binding -- EXISTENT deja dans
`forge_integrity.CapabilityToken` : `exp` avec `TokenExpiredError`, `jti`
anti-replay, `IntegrityManager.revoke(agent, min_seq)`, et `cnf` / `x5t#S256`
pour l'adossement au certificat. Ce qui manquait n'etait pas le mecanisme,
c'etait son CABLAGE : les organes portaient le credential STATIQUE
(`FORGE_TOKEN_<AGENT>`) directement sur le fil, et un secret sans expiration
vole reste valide indefiniment.

Le modele correct existe aussi -- `forge_auth_tokens.login_agent(role_id,
secret_id)` rend un CapabilityToken a bail 30 minutes. C'est le patron AppRole :

    credential STATIQUE  = ce qu'on POSSEDE, ne quitte jamais la machine
    jeton COURT          = ce qu'on PRESENTE, expire, revocable, trace

Ce module fait le pont, une fois pour tous les organes. Il ne remplace pas le
credential statique : il l'utilise pour obtenir un jeton court, et le renouvelle
avant expiration.

REPLI ASSUME ET DECLARE. Si l'echange echoue -- module absent, hub non demarre,
credential non provisionne -- on rend le credential STATIQUE plutot que rien :
un organe muet casse le corps, alors qu'un organe au credential long reste
authentifie et VISIBLE dans le journal (`via=bearer_derive`). Le repli est donc
une degradation NOMMEE, pas un echec silencieux, et `etat()` le rapporte.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `jeton_hub` — Jeton a presenter AU HUB pour l'identite `agent` (etape 2b-5, 2026-09-28).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

__all__ = ["jeton_pour", "jeton_hub", "etat", "invalider", "MARGE_RENOUVELLEMENT_S"]

# On renouvelle AVANT l'expiration : un jeton qui expire pendant le vol du
# reseau produirait un 401 aleatoire, impossible a diagnostiquer.
MARGE_RENOUVELLEMENT_S = 300.0

_VERROU = threading.Lock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_ETAT: Dict[str, Dict[str, Any]] = {}


def _statique(agent: str) -> str:
    """Le credential permanent au coffre. Jamais presente sur le fil si on peut
    l'eviter -- il sert a en obtenir un court."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("FORGE_TOKEN_%s" % agent.upper()) or ""
    except Exception:  # noqa: BLE001
        return ""


# Etape 2b-4 du correctif du coffre (2026-09-28). Le hub (SYSTEM) est le seul a VERIFIER
# les CapabilityToken ; les SIGNER ici, dans le process appelant, exigeait MCP_DEV_SECRET
# -- la cle qui fabrique un jeton de n'importe quel ring -- dans chaque organe hors hub.
# Hors SYSTEM, le jeton court est donc EMIS PAR LE HUB (`POST /api/login`, identifiant
# PROPRE de l'agent) ; sous SYSTEM (le hub lui-meme), il est signe ici : un appel HTTP du
# hub a lui-meme peut le bloquer.
_TRANSITION_DITE = {"locale": False}


def _sous_system() -> bool:
    """Le process tourne-t-il sous SYSTEM ? SID du JETON du process, jamais `USERNAME`.
    Illisible -> False : on ne suppose jamais SYSTEM, la voie du hub reste sure."""
    try:
        from nokido_agent.app import forge_machine_vault as mv

        return mv._sid_courant() == mv.RESERVE_COMPTE_SID
    except Exception:  # noqa: BLE001
        return False


def _url_login_du_hub() -> str:
    """`/api/login` du hub, LOOPBACK seulement : l'identifiant propre de l'agent ne quitte
    jamais la machine. Une URL de hub non locale est refusee ('')."""
    import os
    from urllib.parse import urlparse

    base = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766").rstrip("/")
    try:
        hote = (urlparse(base).hostname or "").lower()
    except ValueError:
        return ""
    return base + "/api/login" if hote in ("127.0.0.1", "localhost", "::1") else ""


def _echanger_par_le_hub(agent: str, secret: str) -> str:
    url = _url_login_du_hub()
    if not url:
        return ""
    import json
    import urllib.request

    corps = json.dumps({"role_id": agent.upper(), "secret_id": secret}).encode("utf-8")
    req = urllib.request.Request(url, data=corps, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as rep:
            d = json.loads(rep.read().decode("utf-8", "replace") or "{}")
        return str(d.get("token") or "")
    except Exception:  # noqa: BLE001 -- injoignable ou refus : '' et la transition le dit
        return ""


def _echanger_localement(agent: str, secret: str) -> str:
    from nokido_agent.app.forge_auth_tokens import login_agent

    return login_agent(agent.upper(), secret_id=secret) or ""


def _echanger(agent: str, secret: str) -> tuple:
    """(jeton_court, expire_dans_s) ou ('', 0) si l'echange n'aboutit pas.

    Rend TOUJOURS un couple : l'appelant ne doit pas avoir a distinguer une
    exception d'un refus.
    """
    try:
        if _sous_system():
            brut = _echanger_localement(agent, secret)
        else:
            brut = _echanger_par_le_hub(agent, secret)
            if not brut:
                # TRANSITION jusqu'a 2b-6 : signature locale, qui exige MCP_DEV_SECRET
                # lisible ici. Dite une fois par process.
                if not _TRANSITION_DITE["locale"]:
                    _TRANSITION_DITE["locale"] = True
                    import logging

                    logging.getLogger(__name__).warning(
                        "[agent_credential] jeton court non obtenu du hub : signature "
                        "LOCALE en TRANSITION (fermeture = etape 2b-6)")
                brut = _echanger_localement(agent, secret)
        if not brut:
            return "", 0.0
        # Duree lue sur le jeton lui-meme, jamais supposee : si la politique du
        # hub raccourcit le bail, on doit renouveler plus tot, pas plus tard.
        reste = _reste_du_jeton(brut)
        return brut, reste
    except Exception:  # noqa: BLE001
        return "", 0.0


def _reste_du_jeton(brut: str) -> float:
    """Secondes restantes lues DANS le jeton. 0.0 si illisible.

    On ne se fie pas a une duree codee en dur cote client : c'est l'emetteur
    qui decide, et une desynchronisation ferait presenter un jeton mort.
    """
    try:
        import base64
        import json

        p = brut.split(".")[0]
        payload = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        return max(0.0, float(payload.get("exp", 0)) - time.time())
    except Exception:  # noqa: BLE001
        return 0.0


_MAITRE_TRANSITION_DITE: set = set()


# --- JETON COURT INJECTE PAR LE SUPERVISEUR (decision owner 2026-09-28) -------------------
#
# Le superviseur (LocalSystem) passait a chaque enfant tout son environnement, jeton maitre
# compris. Il injecte desormais un jeton COURT pour l'identite du service
# (plan : C:/tmp/plan_jeton_court_lanceur_2026-09-28.md, etape C). Le service ne tient
# aucun secret statique : il prolonge ce jeton par un ECHANGE DE JETON RFC 8693.
ENV_JETON_INJECTE = "NOKIDO_JETON_COURT"
ENV_IDENTITE_INJECTEE = "NOKIDO_IDENTITE"
_GRANT_ECHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"        # RFC 8693 §2.1
_TYPE_JETON_ACCES = "urn:ietf:params:oauth:token-type:access_token"      # RFC 8693 §3
_INJECTES: Dict[str, str] = {}
_ECHEC_RENOUVELLEMENT: Dict[str, float] = {}
_PAUSE_APRES_ECHEC_S = 30.0
# Jeton PROJETE (2026-09-28, motif Kubernetes) : le lanceur, vivant tant que le service vit,
# renouvelle le jeton par TPM et l'ecrit dans ce fichier, lisible par le seul compte du
# service (`tools/forge_runas_launcher.py`). Le chemin n'est pas un secret.
ENV_JETON_FICHIER = "NOKIDO_JETON_FICHIER"


def _sujet_du_jeton(brut: str) -> str:
    """`sub` lu dans la charge du jeton (non verifiee : le HUB verifie la signature ; ici on
    evite seulement d'adopter le jeton d'une autre identite)."""
    try:
        import base64
        import json

        p = brut.split(".")[0]
        return str(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("sub") or "").upper()
    except Exception:  # noqa: BLE001
        return ""


def _jeton_projete(agent: str) -> str:
    """Le jeton du fichier projete, s'il appartient a CETTE identite ; sinon ''."""
    import os

    chemin = os.environ.get(ENV_JETON_FICHIER)
    if not chemin:
        return ""
    try:
        with open(chemin, encoding="ascii") as f:
            brut = f.read().strip()
    except OSError:
        return ""
    return brut if brut and _sujet_du_jeton(brut) == agent.upper() else ""


def _jeton_injecte(agent: str) -> str:
    """Jeton court injecte par le lanceur pour CETTE identite, ou ''.

    Lu une fois puis RETIRE de l'environnement : les processus que ce service lance n'en
    heritent pas (chacun recoit le sien de son propre lanceur). Jamais prete a une autre
    identite que celle que le lanceur a nommee ; sans identite nommee, il n'est pas garde."""
    import os

    brut = os.environ.pop(ENV_JETON_INJECTE, None)
    if brut:
        ident = (os.environ.get(ENV_IDENTITE_INJECTEE) or "").upper().strip()
        if ident:
            _INJECTES[ident] = brut.strip()
    return _INJECTES.get(agent.upper(), "")


def _url_renouvellement_du_hub() -> str:
    """Point d'echange de jeton du hub, LOOPBACK seulement (comme `/api/login`)."""
    base = _url_login_du_hub()
    return base + "/renouveler" if base else ""


def _renouveler_par_le_hub(jeton: str) -> str:
    """Echange de jeton RFC 8693 §2.1 : le jeton courant contre un neuf. '' si refus."""
    url = _url_renouvellement_du_hub()
    if not url or not jeton:
        return ""
    import json
    import urllib.request
    from urllib.parse import urlencode

    corps = urlencode({"grant_type": _GRANT_ECHANGE, "subject_token": jeton,
                       "subject_token_type": _TYPE_JETON_ACCES}).encode("ascii")
    req = urllib.request.Request(url, data=corps, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=5) as rep:
            d = json.loads(rep.read().decode("utf-8", "replace") or "{}")
        return str(d.get("access_token") or "")
    except Exception:  # noqa: BLE001 -- refus (4xx) ou injoignable : '' et l'etat le dit
        return ""


def _servir_injecte(cle: str) -> str:
    """Le jeton injecte de `cle`, renouvele si besoin ; '' s'il n'y en a pas ou plus.
    Appele sous `_VERROU`."""
    injecte = _jeton_injecte(cle)
    if not injecte:
        return ""
    reste = _reste_du_jeton(injecte)
    mode = "INJECTE"
    if reste <= MARGE_RENOUVELLEMENT_S:
        # Le fichier projete D'ABORD : le lanceur l'a peut-etre deja renouvele par TPM --
        # aucun appel reseau, aucun echange.
        projete = _jeton_projete(cle)
        if projete and _reste_du_jeton(projete) > reste:
            _INJECTES[cle] = injecte = projete
            reste = _reste_du_jeton(projete)
            mode = "INJECTE_PROJETE"
    if 0 < reste <= MARGE_RENOUVELLEMENT_S and \
            time.time() - _ECHEC_RENOUVELLEMENT.get(cle, 0.0) > _PAUSE_APRES_ECHEC_S:
        neuf = _renouveler_par_le_hub(injecte)
        if neuf and _reste_du_jeton(neuf) > reste:
            _INJECTES[cle] = injecte = neuf
            reste = _reste_du_jeton(neuf)
            mode = "INJECTE_RENOUVELE"
            _ECHEC_RENOUVELLEMENT.pop(cle, None)
        else:
            _ECHEC_RENOUVELLEMENT[cle] = time.time()
            mode = "INJECTE_NON_RENOUVELE"
    if reste <= 0:
        # Expire : rien n'est invente. Le superviseur relance le service avec un jeton neuf.
        _INJECTES.pop(cle, None)
        _ETAT[cle] = {"mode": "INJECTE_EXPIRE", "motif": "jeton du lanceur expire et non "
                      "renouvele -- aucun repli sur un secret statique ni sur le maitre",
                      "ts": time.time()}
        return ""
    if reste > MARGE_RENOUVELLEMENT_S:
        _CACHE[cle] = {"jeton": injecte, "expire_a": time.time() + reste}
    _ETAT[cle] = {"mode": mode, "expire_dans_s": round(reste),
                  "motif": "jeton court injecte par le lanceur, renouvele par echange RFC 8693",
                  "ts": time.time()}
    return injecte


def jeton_hub(agent: str) -> str:
    """Jeton a presenter AU HUB pour l'identite `agent` (etape 2b-5, 2026-09-28).

    Une brique pour tous les clients du hub, au lieu de dizaines de lectures du maitre :
      - identite provisionnee -> SON jeton (court si possible, statique sinon) ;
      - identite NON provisionnee -> le MAITRE, en TRANSITION jusqu'a la fermeture 2b-6 :
        mode `MAITRE_TRANSITION` dans `etat()`, dit une fois par identite ;
      - ni l'un ni l'autre -> '' : le hub repondra 401, refus lisible.
    Contrat AUTH-2 (2026-09-24) inchange : le maitre reste le canal des lanceurs de
    l'owner tant que son identifiant propre n'est pas scelle sous son compte. Des que
    `FORGE_TOKEN_<AGENT>` est provisionne (et charge par le hub), le client quitte le
    maitre seul.
    """
    propre = jeton_pour(agent)
    if propre:
        return propre
    try:
        from nokido_agent.app.forge_secrets import get_secret

        maitre = get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:  # noqa: BLE001
        maitre = ""
    if not maitre:
        return ""
    cle = agent.upper()
    with _VERROU:
        _ETAT[cle] = {"mode": "MAITRE_TRANSITION",
                      "motif": ("identite propre non provisionnee : jeton MAITRE presente "
                                "(fermeture = etape 2b-6)"),
                      "ts": time.time()}
        premiere = cle not in _MAITRE_TRANSITION_DITE
        _MAITRE_TRANSITION_DITE.add(cle)
    if premiere:
        import logging

        logging.getLogger(__name__).warning(
            "[agent_credential] %s : identite propre non provisionnee, jeton MAITRE en "
            "TRANSITION (fermeture = etape 2b-6)", cle)
    return maitre


def jeton_pour(agent: str) -> str:
    """Jeton a presenter pour cet organe. Court si possible, statique sinon.

    Thread-safe : plusieurs requetes concurrentes ne doivent pas declencher
    autant d'echanges -- le hub verrait une rafale de logins pour rien.
    """
    cle = agent.upper()
    with _VERROU:
        entree = _CACHE.get(cle)
        if entree and entree["expire_a"] - time.time() > MARGE_RENOUVELLEMENT_S:
            return entree["jeton"]

        # Jeton injecte par le lanceur d'abord (2026-09-28) : aucun secret statique a lire.
        injecte = _servir_injecte(cle)
        if injecte:
            return injecte
        if _ETAT.get(cle, {}).get("mode") == "INJECTE_EXPIRE":
            return ""

        secret = _statique(cle)
        if not secret:
            _ETAT[cle] = {"mode": "AUCUN", "motif": "credential statique absent du "
                          "coffre : cet organe ne peut pas s'authentifier",
                          "ts": time.time()}
            return ""

        court, reste = _echanger(cle, secret)
        if court and reste > MARGE_RENOUVELLEMENT_S:
            _CACHE[cle] = {"jeton": court, "expire_a": time.time() + reste}
            _ETAT[cle] = {"mode": "COURT", "expire_dans_s": round(reste),
                          "motif": "jeton a bail, expirable et revocable",
                          "ts": time.time()}
            return court

        # REPLI DECLARE : le credential long part sur le fil. C'est une
        # degradation, elle est nommee, et `etat()` la rapporte -- de sorte
        # qu'un organe reste au credential permanent se VOIT, au lieu de
        # passer pour un organe durci.
        _ETAT[cle] = {
            "mode": "STATIQUE_REPLI",
            "motif": ("echange impossible (hub non demarre, ou bail trop court : "
                      "%ss) -- credential PERMANENT presente, sans expiration ni "
                      "revocation" % round(reste)),
            "ts": time.time(),
        }
        return secret


def invalider(agent: Optional[str] = None) -> int:
    """Oublie le jeton en cache. Sans argument : tous.

    A appeler apres une revocation cote hub, sinon l'organe continuerait de
    presenter un jeton que le hub refuse deja -- la revocation serait juste,
    et l'organe la decouvrirait par une rafale de 401.
    """
    with _VERROU:
        if agent:
            return 1 if _CACHE.pop(agent.upper(), None) else 0
        n = len(_CACHE)
        _CACHE.clear()
        return n


def etat() -> Dict[str, Any]:
    """Quel organe presente quoi. Sert a MESURER le durcissement reel.

    `courts` / `replis` / `aucun` : sans ces trois compteurs, « les organes sont
    durcis » ne se distingue pas de « le durcissement echoue en silence ».
    """
    with _VERROU:
        detail = {k: dict(v) for k, v in _ETAT.items()}
    modes = [v.get("mode") for v in detail.values()]
    return {
        "organes": len(detail),
        "courts": modes.count("COURT"),
        "replis": modes.count("STATIQUE_REPLI"),
        "aucun": modes.count("AUCUN"),
        # 2b-5 : clients qui vivent encore du MAITRE faute d'identite provisionnee.
        "maitre_transition": modes.count("MAITRE_TRANSITION"),
        # 2026-09-28 : organes servis par le jeton court de leur LANCEUR, et ceux dont il a
        # expire sans renouvellement (le superviseur doit les relancer).
        "injectes": sum(1 for m in modes if m in ("INJECTE", "INJECTE_RENOUVELE",
                                                  "INJECTE_PROJETE", "INJECTE_NON_RENOUVELE")),
        "injectes_expires": modes.count("INJECTE_EXPIRE"),
        "detail": detail,
        "avertissement": (
            "Un organe en STATIQUE_REPLI presente un credential PERMANENT : ni "
            "expiration, ni revocation. C'est la situation d'avant le "
            "durcissement, et elle doit se voir plutot que de se confondre avec "
            "un organe protege."
        ),
    }
