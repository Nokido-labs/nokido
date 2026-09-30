#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_videur.py — VIDEUR : couche identité × access-control (organe immunitaire).

Comble l'incohérence de ring exposée par forge_hub_gate (même appelant CLAUDE vu
ring 1 sur blackboard ET ring 4 sur ask : plusieurs chemins résolvaient le ring
DIFFÉREMMENT). Le videur = la SOURCE UNIQUE de résolution identité×ring, + capture
DYNAMIQUE de l'identité par requête (X-Agent-Name + token-hash + ring), LOG CRYPTÉ
(DPAPI), who-can-talk-to-whom, et GARDE-FOUS sur changement de ring (audit + annonce).

Directive user : « X-Agent-Name récupéré dynamiquement, loggé, identifié, crypté ».

ANTI-DUP : réutilise config/agent_identities.json (registre LIVE), win32crypt (DPAPI),
forge_postal (facteur/messager, Phase 2), le seed. N'invente PAS un nouveau registre.

Phase 1 (ce fichier) = résolution UNIFIÉE + capture+log crypté + policy + garde-fou ring,
testable (selftest, 0 dépendance hub). Phase 2 = wiring nokido_hub._resolve_ring (source
unique pour TOUS les chemins) + annonce facteur sur changement — reload requis.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/rbac : videur, identite x access-control"  # organe declare le 2026-09-06 (audit de raccordement)

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

_STORE = ROOT / "config" / "agent_identities.json"
_LOG = ROOT / "sandbox" / "videur_identity.log"   # entrées CRYPTÉES (DPAPI), 1 blob b64/ligne
_cache: dict = {"mtime": -1.0, "rings": {}, "meta": {}}

# SEED minimal (si store absent) — aligné sur nokido_hub._AGENT_RING.
_SEED_RING = {"CLAUDE": 1, "CLAUDE_CLI": 2, "CLAUDE_HOOK": 4, "GEMINI": 1, "GEMINI_HOOK": 4,
              "GEMINI_HEADLESS": 1, "GEMINI_DAEMON": 1,
              "ANTIGRAVITY": 1, "AGY": 1, "AGY_HEADLESS": 1, "AGY_DAEMON": 1, "AGY_HOOK": 4,
              "COPILOT": 3, "CLINE": 1, "BRIDGE": 1, "NETCFG": 1, "LLAMACPP": 3,
              # MASTER = le porteur du maitre qui se DECLARE maitre (contrat AUTH-2 du
              # 24/09) : les lanceurs du bureau de l'owner. Absent d'ici, il tombait au
              # defaut UNTRUSTED (4) -- se declarer honnetement coutait plus que prendre
              # le nom d'un organe. Decision owner 2026-09-26 : ring 2 (lecture du mode).
              # set_mode reste ring 0 ; la borne LAFORGE_MASTER_BORNE ne vise que
              # l'impersonation, jamais MASTER (NR test_maitre_porte_acteur_et_sujet_nr).
              "MASTER": 2}
# AGY (tous ses noms vivants) = ring 1, decision owner du 2026-08-13. Il manquait
# ENTIEREMENT de la graine : store illisible -> AGY retombait a UNTRUSTED(4) sans
# que rien ne le dise. GEMINI valait 3 ici et 1 dans le SSoT : c'est le MEME
# acteur qu'ANTIGRAVITY, la graine s'aligne. Regle : cette graine ne doit jamais
# contredire config/agent_identities.json.
# 2026-08-14 : NETCFG et LLAMACPP etaient les DEUX seules identites en ring 0 du
# registre. Un backend d'inference (LLAMACPP) et un agent d'equipement reseau
# (NETCFG) n'ont aucune raison de porter le ring MASTER : mesure sur 228 955
# appels journalises, chacun n'en a fait qu'UN, le 2026-07-30. Descendus a 1 et 3
# (directive owner : aucun client ne persiste en ring 0). La graine doit rester
# alignee sur config/agent_identities.json, sinon le ring 0 renait si le store
# est illisible.


def _load_store() -> dict:
    """Rings LIVE depuis agent_identities.json (reload mtime). Source unique."""
    try:
        if _STORE.exists():
            m = _STORE.stat().st_mtime
            if m != _cache["mtime"]:
                data = json.loads(_STORE.read_text("utf-8"))
                ag = data.get("agents", {})
                new_rings = {}
                new_meta = {}
                for k, v in ag.items():
                    if not isinstance(v, dict):
                        continue
                    k_up = k.upper()
                    try:
                        r = v.get("ring")
                        if r is not None:
                            new_rings[k_up] = int(r)
                        new_meta[k_up] = v
                    except (ValueError, TypeError):
                        # Log l'erreur mais continue pour les autres entrées
                        continue
                _cache["rings"] = new_rings
                _cache["meta"] = new_meta
                _cache["mtime"] = m
    except Exception:  # noqa: BLE001
        pass
    return _cache["rings"]


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()[:16]


import os as _os

_DEV_IS_ARMED_OVERRIDE = None  # hook test/inject -> callable()->(armed:bool, remaining:int)
_OWNER_AGENTS = frozenset(
    a.strip().upper()
    for a in _os.environ.get("LAFORGE_DEV_OWNER_AGENTS",
                             "CLAUDE,CLI_CLAUDE,user,MASTER_TOKEN").split(",")
    if a.strip()
)
# Cible d'élévation quand dev armé. Défaut DEV(1) = conservateur. Mettre 0 (SYSTEM) pour
# que l'armement débloque AUSSI les tools ring-0/visibilité (ex docker_action) à l'owner.
_RING_DEV = int(_os.environ.get("LAFORGE_DEV_ELEVATION_RING", "1"))

# FAIL-CLOSED (audit 2026-06-15) : identité inconnue = moindre privilège, jamais
# SYSTEM par omission ; header non authentifié plafonné non-privilégié (anti-spoof).
_UNTRUSTED_RING = 4
_HEADER_FLOOR_RING = 4


#: Les `via` qui attestent une identite PROUVEE — caracterisation POSITIVE.
#: Une liste des via « interdits » serait une liste noire : tout nouveau canal
#: y manquerait par defaut, et manquer y signifierait « autorise ».
_VIAS_PROUVEES = ("token", "reverse_token", "master_token")


def _identite_prouvee(via: str) -> bool:
    """Vrai si `via` atteste une identite VERIFIEE, pas seulement DECLAREE.

    `delegated:<nom>` en fait partie : le delegateur a prouve SA propre
    identite avec SON jeton derive, et la borne `ring_min_delegue` est
    re-appliquee APRES l'elevation, en derniere instruction.
    """
    v = str(via or "")
    return v in _VIAS_PROUVEES or v.startswith("delegated:")


def _maybe_elevate(agent: str, ring: int, local: bool,
                   via: str = "header") -> int:
    """Reco #1 (2026-06-14) : câble l'armement dev-mode au ring de requête. Sans ça,
    forge_dev_mode.arm() ne débloque QUE le sandbox-bypass, pas la visibilité/RBAC des
    tools -> owner bloqué malgré dev armé. Garde-fous : LOCAL only · agent OWNER-allowlist
    · jamais demote · fail-safe (toute erreur -> ring inchangé, l'auth ne casse JAMAIS)."""
    try:
        # PROVENANCE D'ABORD — ajoute le 2026-09-12 apres mesure.
        # Cette fonction s'execute APRES le plancher anti-spoof et ne
        # consultait que trois conditions : connexion locale, nom dans une
        # allowlist de quatre entrees, dev arme. Jamais la PROVENANCE. Mesure :
        # `X-Agent-Name: CLAUDE` SANS aucun jeton, en local, dev arme, rendait
        # ring 1 — avec `via` valant toujours `header`, c'est-a-dire que le
        # verdict portait lui-meme la preuve qu'il ne devait pas accorder ce
        # ring. Le plancher etait pose, puis franchi apres coup.
        #
        # C'est la faute DEJA corrigee dans ce module pour la borne de
        # delegation — deplacee en derniere instruction « pour que la propriete
        # devienne structurelle au lieu d'etre vraie par coincidence ». Le
        # raisonnement n'avait pas ete reporte ici.
        #
        # Le defaut du parametre est `header`, donc NON PROUVE : un appelant
        # qui oublierait de transmettre la provenance n'obtient pas
        # d'elevation. Fail-closed sur l'omission.
        # Fige par tests/test_antispoof_survit_a_l_elevation.py
        if not _identite_prouvee(via):
            return ring
        if not local or not agent or agent.upper() not in _OWNER_AGENTS:
            return ring
        fn = _DEV_IS_ARMED_OVERRIDE
        if fn is None:
            from nokido_agent.tools.forge_dev_mode import is_armed as fn
        armed, _rem = fn()
        if armed and int(ring) > _RING_DEV:
            return _RING_DEV
        return ring
    except Exception:  # noqa: BLE001
        return ring


_BOITE_CACHE: dict = {"mtime": 0.0, "index": {}}


def _index_boites() -> dict:
    """alias -> BOÎTE de l'acteur, depuis le registre (schéma >= 2), cache mtime."""
    try:
        m = _STORE.stat().st_mtime
        if m != _BOITE_CACHE["mtime"]:
            reg = json.loads(_STORE.read_text(encoding="utf-8"))
            idx = {}
            for nom, e in (reg.get("agents") or {}).items():
                boite = str(e.get("mailbox") or e.get("actor") or nom).upper()
                idx[nom.upper()] = boite
                for a in e.get("aliases") or []:
                    idx[str(a).upper()] = boite
            _BOITE_CACHE.update({"mtime": m, "index": idx})
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.videur").warning(
            "[videur] index des boites ILLISIBLE (%s: %s) | consequence: le "
            "courrier retombe sur le nom brut, donc deux noms du meme acteur "
            "redonnent deux boites (mesure 2026-08-14 : 98 + 43 + 9 messages "
            "d'un SEUL acteur repartis sur trois boites)",
            type(e).__name__, str(e)[:90])
    return _BOITE_CACHE["index"]


def cli_agents() -> set:
    """Noms (UPPER) des agents kind=cli_agent — les clients M2M, registre LIVE.

    Source unique pour « qui est un CLI capable de M2M » : le registre
    config/agent_identities.json (reload mtime). Permet a la messagerie
    (routage _to_map, surface [HOOK:INBOX], broadcast) de suivre AUTOMATIQUEMENT
    tout nouveau CLI declare par l'owner (mammouth, zcode, roo, vibe, sixth,
    vscode...) sans redeploiement ni liste figee a maintenir a deux endroits.
    """
    _load_store()  # garantit le cache a jour (reload mtime)
    return {k for k, v in _cache.get("meta", {}).items()
            if isinstance(v, dict) and v.get("kind") == "cli_agent"}


def mailbox_de(nom: str) -> str:
    """Boite 'agt_<mailbox>' pour un alias/nom (routage M2M) ; '' si inconnu.

    Reutilise _index_boites() (alias -> BOITE de l'acteur) : deux noms d'un
    meme acteur retombent sur la MEME boite (cf. mesure 2026-08-14).
    """
    b = _index_boites().get((nom or "").upper())
    return f"agt_{b.lower()}" if b else ""


def canonical(nom: str) -> str:
    """Nom d'agent -> BOÎTE de l'acteur qui le possède.

    `agt_gemini`, `AGY`, `GEMINI_RELAY`, `WORKER_CODE` désignent tous la boîte
    `ANTIGRAVITY`. Une surface (hook, relais, exécuteur) n'a PAS de boîte
    propre : son courrier appartient à l'acteur qu'elle sert.
    """
    n = (nom or "").upper().strip()
    return _index_boites().get(n, n)


# LISTE BLANCHE des `via` qui PROUVENT le sujet. Jamais une liste noire : une
# valeur inattendue — un `via` ajoute demain — tomberait du cote prouve par
# simple absence de la liste de refus, et heriterait d'une confiance que
# personne ne lui a donnee.
#
#   `token` / `reverse_token`  le porteur CORRESPOND au nom : preuve.
#   `capability_token`         signe et verifie, `sub` porte le sujet.
#   `header`                   DECLARATIF — deja plafonne par l'anti-spoof.
#   `master_token`             possession du maitre, PAS identite du sujet
#                              (mesure 2026-09-21 : 21 647 appels, 100 %
#                              impersonation, le porteur prend le nom d'un organe).
#   `delegated:*`              A agit POUR B ; A est prouve, B ne l'est pas.
#   `repli_legacy` / inconnu   n'ont jamais calcule de preuve.
_VIA_PROUVES = frozenset({"token", "reverse_token", "capability_token"})


def peut_consommer_boite(agent_id: str, *, sujet: str | None,
                         sujet_prouve: bool = False) -> dict:
    """OWNERSHIP — ce sujet possède-t-il la boîte `agent_id` ?

    Axe DISTINCT de `authorize`, qui décide identité×CAPACITÉ (ring d'un tool).
    Consommer une boîte n'est pas une capacité : c'est une PROPRIÉTÉ.
    `CONTROL != OWNERSHIP` — pouvoir appeler une route n'autorise pas à prendre
    le courrier d'un autre.

    Motif : `GET /inbox/{agent_id}` fait `_INBOX.pop()`, qui RETIRE le message.
    Qui connaît un `agent_id` intercepte le courrier de cet agent, qui ne le
    recevra jamais. Classée LECTURE par sa méthode, c'est une MUTATION par son
    effet.

    Fonction PURE : ne consomme rien, ne journalise rien, n'a pas d'effet.
    Retourne {allow, reason, boite}. `reason` est TOUJOURS renseignée — un
    refus muet n'est pas instruisable.

    Deux replis, mesurés le 2026-09-22, que cette décision ferme :

    1. `canonical` retombe sur le NOM BRUT pour un inconnu. Comparer deux
       canonicalisations laisserait `FOO` demander `/inbox/FOO` : l'égalité
       serait vraie sans qu'aucune identité existe. On exige donc que les DEUX
       noms soient CONNUS du registre — l'appartenance précède la comparaison.
    2. `_index_boites` avale son erreur et peut rendre un index vide : tout
       retomberait sur le nom brut et la comparaison deviendrait permissive
       AU MOMENT où le registre tombe. Un index muet est un UNKNOWN, et
       `UNKNOWN = REFUSE`.

    `sujet_prouve` sépare l'identité DÉCLARÉE de l'identité AUTHENTIFIÉE :
    un en-tête `X-Agent-Name` est une affirmation de l'appelant, pas une preuve.
    L'appelant doit avoir été authentifié par son porteur AVANT cet appel.
    """
    if not sujet_prouve:
        return {"allow": False, "boite": None,
                "reason": "identite DECLAREE, non prouvee — un en-tete n'authentifie pas"}
    cible = (agent_id or "").upper().strip()
    qui = (sujet or "").upper().strip()
    if not cible or not qui:
        return {"allow": False, "boite": None,
                "reason": "agent_id ou sujet ABSENT"}
    index = _index_boites()
    if not index:
        return {"allow": False, "boite": None,
                "reason": "index des boites ILLISIBLE ou vide — on refuse plutot "
                          "que de retomber sur le nom brut"}
    if cible not in index:
        return {"allow": False, "boite": None,
                "reason": "boite '%s' INCONNUE du registre — pas d'auto-autorisation "
                          "par repli sur le nom brut" % cible}
    if qui not in index:
        return {"allow": False, "boite": None,
                "reason": "sujet '%s' INCONNU du registre" % qui}
    boite_cible, boite_sujet = index[cible], index[qui]
    if boite_cible != boite_sujet:
        return {"allow": False, "boite": boite_cible,
                "reason": "la boite '%s' appartient a %s, le sujet sert %s"
                          % (cible, boite_cible, boite_sujet)}
    return {"allow": True, "boite": boite_cible,
            "reason": "sujet prouve et boite '%s' possedee par %s"
                      % (cible, boite_cible)}


def alias_de(boite: str) -> list:
    """Tous les noms qui routent vers cette boîte — pour la LECTURE, afin que
    le courrier déposé sous un ancien nom reste relevable sans migration."""
    b = canonical(boite)
    return sorted({b} | {k for k, v in _index_boites().items() if v == b})


def _delegation_de(nom: str) -> dict:
    """Regle d'act-as d'un agent, ou {} s'il n'en a AUCUNE.

    ATTENTION AU NOM : ce n'est PAS un token exchange (RFC 8693). Le droit
    d'agir pour autrui vient d'une table declarative, aucun jeton n'est emis.
    Ce que nous empruntons a la RFC, c'est sa SEMANTIQUE -- l'acteur reste
    distinct du sujet -- pas son protocole. Cinq revues independantes ont
    qualifie l'appellation d'origine de trompeuse.

    Lue au registre vivant (`config/agent_identities.json`), champ `delegation`.
    Le defaut est l'absence de droit : un agent ne delegue que si le registre
    l'y autorise EXPLICITEMENT, jamais parce que son jeton est valide.

    Registre illisible -> {} : on refuse la delegation plutot que de l'accorder
    sur une lecture ratee. Fail-closed, comme le ring.
    """
    try:
        import json as _json
        from pathlib import Path as _P

        chemin = _P(__file__).resolve().parent.parent / "config" / "agent_identities.json"
        agents = (_json.loads(chemin.read_text(encoding="utf-8")) or {}).get("agents") or {}
        regle = (agents.get(nom) or {}).get("delegation") or {}
        return regle if isinstance(regle, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def resolve_identity(agent_hdr: str, token: str = "", local: bool = True,
                     agent_tokens: dict | None = None, hub_token: str = "") -> dict:
    """SOURCE UNIQUE identité×ring. Déterministe — TOUS les chemins doivent l'appeler
    (vs les résolutions divergentes actuelles). Renvoie {agent, ring, channel, via}.

    - token == derived(agent) -> identité forte.
    - sinon reverse: token -> agent (anti-ring-4-fantôme : on retrouve le VRAI agent).
    - sinon master token -> garde l'agent_hdr (ring mappé), jamais ring 0 par défaut.
    """
    rings = _load_store()
    agent = (agent_hdr or "").upper().strip()
    via = "header"
    agent_tokens = agent_tokens or {}
    import hmac as _h

    # 1. header présent + token correspondant à CET agent -> identité forte (token).
    #    (manquait : un agent légitime porteur de token gardait via=header donc se
    #    faisait plafonner par l'anti-spoof §5.)
    if agent and token and agent_tokens:
        _tok = agent_tokens.get(agent)
        if _tok:
            try:
                if _h.compare_digest(token.encode(), str(_tok).encode()):
                    via = "token"
            except Exception:  # noqa: BLE001
                pass

    # 2. reverse-résolution token->agent SI header absent (anti ring-4 fantôme).
    if not agent and token:
        for name, tok in agent_tokens.items():
            try:
                if _h.compare_digest(token.encode(), str(tok).encode()):
                    agent, via = name.upper(), "reverse_token"
                    break
            except Exception:  # noqa: BLE001
                pass

    # 3. ring depuis la source unique. FAIL-CLOSED (audit 2026-06-15) : défaut
    #    inconnu = UNTRUSTED(4), JAMAIS ring 0 (même local). Une identité inconnue
    #    n'obtient pas SYSTEM par omission.
    # 2bis. ACT-AS REGISTRATION -- 2026-09-02.
    #
    # NOMMAGE CORRIGE apres consultation de cinq avis independants, unanimes :
    # parler d'« esprit RFC 8693 » etait TROMPEUR. La RFC 8693 est un TOKEN
    # EXCHANGE -- un client presente un `subject_token` et un `actor_token` a
    # une autorite qui EMET un nouveau jeton. Ici rien n'est echange ni emis :
    # le droit vient d'une TABLE, le credential reste le meme. La formulation
    # juste est « act-as sans artifact » : la semantique de delegation de la
    # RFC (sujet distinct de l'acteur, cf. les champs `sujet`/`acteur` rendus
    # plus bas) sans jeton signe, sans `aud`, sans `exp`, sans `iss`.
    # Invoquer une RFC qu'on n'implemente pas est une fausse garantie : un
    # relecteur en deduirait une chaine d'audit signee et une revocation
    # atomique qui n'existent pas.
    #
    # Probleme resolu : une passerelle qui relaie des clients (OPENAI_PROXY sur
    # :7777) devait porter le jeton MAITRE pour que le nom du client reel soit
    # conserve. C'est le CONFUSED DEPUTY : toute requete atteignant la
    # passerelle choisissait son identite ET heritait de son ring, jusqu'a
    # l'administration du hub. Le privilege de deleguer est desormais CONFINE
    # ici, dans la source de verite, au lieu d'etre eparpille sous forme de
    # jetons maitres dans les modules peripheriques.
    #
    # Le delegateur prouve SA propre identite avec SON jeton derive ; le
    # registre lui accorde le droit de DECLARER un autre nom. Deux bornes, et
    # elles sont le coeur du dispositif :
    #   - `ring_min_delegue` : le ring accorde ne descend jamais sous ce
    #     plancher. Une passerelle compromise peut donc usurper une identite
    #     mais JAMAIS obtenir l'administration (ring 0), hors d'atteinte de
    #     toute delegation.
    #   - `via = "delegated:<delegateur>"` : la trace nomme QUI a delegue. Sans
    #     ca on rouvrirait l'angle mort qu'on vient de fermer -- un appel
    #     delegue indiscernable d'une authentification directe.
    delegue_par = ""
    refus_hors_local = False
    if agent and token and agent_tokens:
        for _nom_del, _tok_del in agent_tokens.items():
            if not _tok_del or _nom_del.upper() == agent:
                continue
            try:
                if not _h.compare_digest(token.encode(), str(_tok_del).encode()):
                    continue
            except Exception:  # noqa: BLE001
                continue
            _regle = _delegation_de(_nom_del.upper())
            if not _regle:
                # Porteur d'un jeton derive declarant un AUTRE nom sans droit de
                # delegation : on n'accorde rien, l'anti-spoof le plafonne plus
                # bas. C'est le defaut, et il reste strict.
                break
            # PORTEE DE LA DELEGATION -- ajoutee le 2026-09-02 dans la
            # perspective EDGE. Mesure du jour : `local=True` et `local=False`
            # rendaient exactement le meme resultat, donc une passerelle
            # joignable de l'exterieur aurait delegue depuis n'importe ou.
            # Ce qui est acceptable entre deux processus d'une meme machine ne
            # l'est pas a travers un reseau : le defaut est donc LOCAL SEUL, et
            # l'ouvrir est une decision qui se declare au registre
            # (`delegation.hors_local: true`), pas un effet de bord.
            if not local and not _regle.get("hors_local"):
                # REFUS + PLANCHER. Le `via` documente la cause, mais il ne
                # suffit pas : l'anti-spoof ne plafonne que `via == "header"`,
                # si bien qu'un `via` explicite laissait passer le ring de
                # l'agent DECLARE. Refuser la delegation tout en accordant le
                # privilege serait pire que ne rien faire -- defaut trouve par
                # mesure dans le tour meme ou cette borne a ete ecrite.
                via = "delegation_refusee_hors_local"
                refus_hors_local = True
                break
            delegue_par = _nom_del.upper()
            via = "delegated:%s" % delegue_par
            break

    default = _UNTRUSTED_RING
    ring = rings.get(agent, _SEED_RING.get(agent, default)) if agent else default

    # Plancher de delegation : meme en agissant POUR un agent privilegie, une
    # passerelle ne franchit pas cette borne. C'est ce qui distingue la
    # delegation du passe-partout qu'elle remplace.
    if delegue_par:
        _plancher = _delegation_de(delegue_par).get("ring_min_delegue", 1)
        try:
            _plancher = int(_plancher)
        except (TypeError, ValueError):
            _plancher = 1          # illisible -> le plus strict, jamais l'inverse
        if ring < _plancher:
            ring = _plancher

    # 4. master token : garde l'agent identifié + son ring mappé (jamais downgrade fantôme)
    if hub_token and token and agent:
        try:
            if _h.compare_digest(token.encode(), str(hub_token).encode()):
                via = "master_token"
        except Exception:  # noqa: BLE001
            pass

    # 5. ANTI-SPOOF HEADER (audit 2026-06-15) : un ring privilégié exige un token
    #    VÉRIFIÉ. via=header (X-Agent-Name non authentifié) -> plancher non-privilégié.
    #    Empêche `X-Agent-Name=CLAUDE` sans token d'obtenir le ring de CLAUDE.
    if via == "header" and int(ring) < _HEADER_FLOOR_RING:
        ring = _HEADER_FLOOR_RING

    # Delegation refusee hors local : meme plancher que l'anti-spoof. Le nom
    # declare n'est adosse a rien de recevable ici, il ne doit donc rien ouvrir.
    if refus_hors_local and int(ring) < _HEADER_FLOOR_RING:
        ring = _HEADER_FLOOR_RING

    # Reco #1 : élévation dev-mode -> ring (owner local, fail-safe). cf _maybe_elevate.
    ring = _maybe_elevate(agent, int(ring), local, via)

    # BORNE DE DELEGATION, RE-APPLIQUEE EN DERNIER (revue du 2026-09-02).
    # Elle etait posee avant l'anti-spoof et avant `_maybe_elevate` : toute
    # elevation ulterieure la franchissait. Mesure du jour : le contournement
    # n'existait PAS -- mais uniquement parce que `_RING_DEV` vaut 1, exactement
    # la borne. Une egalite fortuite entre deux constantes independantes : que
    # l'une bouge, et la borne saute sans qu'aucun test ne rougisse.
    # Le clamp est donc la DERNIERE instruction avant le retour, et la propriete
    # « une delegation n'atteint jamais l'administration » devient structurelle
    # au lieu d'etre vraie par coincidence.
    if delegue_par:
        _p = _delegation_de(delegue_par).get("ring_min_delegue", 1)
        try:
            _p = int(_p)
        except (TypeError, ValueError):
            _p = 1
        if int(ring) < _p:
            ring = _p

    meta = _cache["meta"].get(agent, {})
    sortie = {"agent": agent or "UNKNOWN", "ring": int(ring), "via": via,
              "channel": meta.get("channel", "HTTP_DIRECT"),
              "transport": meta.get("transport", "http"), "token_h": _token_hash(token)}
    # PREUVE DU SUJET, posee A LA SOURCE -- la ou `via` vient d'etre decide.
    # Elle etait CALCULEE ici puis PERDUE : seul le cas `master_token` la posait,
    # et `_resolve_ring` ne rend que `(ring, agent)`. Un appelant qui en a besoin
    # devait donc la re-deriver de `(ring, agent)` -- c'est-a-dire reconstruire
    # une information deja etablie, a partir de champs qui ne la portent pas.
    #
    #     ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE
    #
    # Le champ est desormais TOUJOURS present, pour TOUS les chemins.
    sortie["sujet_prouve"] = via in _VIA_PROUVES

    # ACTEUR EXPLICITE -- conformite RFC 8693, lue a la source (RFC en base).
    # La RFC distingue nettement deux semantiques :
    #   IMPERSONATION : A devient B, indiscernable -- « A is impersonating B » ;
    #   DELEGATION    : « principal A still has its own identity separate from
    #                    B [...] any actions taken are being taken by A
    #                    representing B », porte par le claim `act`.
    # Notre dispositif faisait de l'IMPERSONATION en se disant delegation :
    # `agent` valait B et l'identite de A ne survivait que dans `via`, un champ
    # de TRACE qu'aucun consommateur n'inspecte pour decider. Un lecteur du
    # verdict voyait CLAUDE sans savoir qu'une passerelle agissait derriere.
    # `acteur` rend donc A structurellement present a cote de B, comme `act`.
    if delegue_par:
        sortie["acteur"] = delegue_par
        sortie["sujet"] = agent or "UNKNOWN"
    # PORTEUR DU MAITRE -- 2026-09-21, mandat owner « durcir master token ».
    #
    # MESURE QUI L'EXIGE, prise avant d'ecrire une ligne : 21 647 appels
    # `via=master_token`, `as_master` = 0, IMPERSONATION 100 %. Le porteur ne
    # s'annonce JAMAIS comme MASTER -- il prend le nom d'un organe
    # (POST_COMMIT 14 478, WEBHUB 6 418, SUPERVISOR 490, CLAUDE 36) et recoit
    # LE RING DE CET ORGANE, parce que l'etape 4 ne change que le `via` quand
    # le ring a deja ete calcule a l'etape 3 depuis le nom DECLARE.
    #
    # Meme lecture de la RFC 8693 que la delegation juste au-dessus : l'acteur
    # reste structurellement present a cote du sujet, au lieu de survivre dans
    # un `via` que personne n'inspecte pour decider. La difference est DITE :
    # ici le sujet vient d'un EN-TETE que rien n'authentifie.
    #
    #     AUTHENTIFIE_SOUS_CONDITION != PROUVE_AUTHENTIFIE
    #
    # L'ECART DE RING EST EXPOSE, JAMAIS APPLIQUE. L'anti-spoof §5 ne teste que
    # `via == "header"` : passer en `master_token` DESARME le plafond au lieu
    # de l'appliquer. Le corriger ferait chuter 7 112 appels sur 21 647 (33 %),
    # dont le superviseur et le webhub -- ce serait le `m2m_mode=error` arme a
    # 100 % de refus le meme soir. `ring_si_borne` permet donc de COMPTER
    # l'impact sur trafic reel ; l'armement est une decision d'AUTORITE, et
    # elle appartient a l'owner.
    #
    # `elif` et non `if` : la delegation a un plancher (`ring_min_delegue`),
    # pas le maitre. Laisser le maitre ecraser l'acteur d'une delegation
    # remplacerait un dispositif BORNE par un dispositif qui ne l'est pas.
    elif via == "master_token" and agent not in ("MASTER", "MASTER_TOKEN"):
        sortie["acteur"] = "classe:porteur_maitre"
        sortie["sujet"] = agent or "UNKNOWN"
        sortie["sujet_prouve"] = False
        sortie["ring_si_borne"] = _HEADER_FLOOR_RING
        # ARMEMENT (2026-09-24, cloture du chantier d'authentification) -- geste OWNER.
        # Mesure qui le rend possible : impersonation par le maitre +0 entre T1 (15:49)
        # et T2 (16:24), et `ecart_si_borne` = 36 declassements, tous WEBHUB HISTORIQUES
        # (WEBHUB porte son jeton propre depuis). L'interrupteur est lu A CHAQUE APPEL
        # et vit dans l'environnement du service hub (services.toml) : hors de portee
        # de ce qu'il contraint. Absent ou != "1" : observation, comme avant.
        if _os.environ.get("LAFORGE_MASTER_BORNE") == "1" and int(sortie["ring"]) < _HEADER_FLOOR_RING:
            sortie["ring"] = _HEADER_FLOOR_RING
            sortie["borne_appliquee"] = True
    return sortie


_TOOL_RING_OVERRIDE = None  # hook test/inject -> callable(tool)->int


def _tool_needed_ring(tool: str) -> int:
    """Ring requis d'un tool — SOURCE UNIQUE. Délègue à la 'Règle d'Or'
    forge_mcp_registry._get_ring_needed (DB forge_tools -> fallback). Centralisé ici pour
    que Police / /mcp / router de serving en dérivent, au lieu de maps locales divergentes."""
    if _TOOL_RING_OVERRIDE is not None:
        return int(_TOOL_RING_OVERRIDE(tool))
    from nokido_agent.app.forge_mcp_registry import get_registry

    return int(get_registry()._get_ring_needed(tool, {}))


def authorize(agent: str, token: str = "", local: bool = True, tool: str | None = None,
              agent_tokens: dict | None = None, hub_token: str = "") -> dict:
    """POLICE — décision UNIQUE identité×capacité×périmètre. Compose resolve_identity (ring,
    source unique identité) + _tool_needed_ring (ring requis du tool, source unique capacité).
    Destiné à être l'UNIQUE point consulté par TOUS les chemins (REST, /mcp, router de serving
    Gemini). Renvoie l'identité + {tool, needed_ring, allow, reason}. Fail-CLOSED : capacité
    indéterminée -> allow=False."""
    ident = resolve_identity(agent, token, local, agent_tokens, hub_token)
    out = dict(ident)
    out.update({"tool": tool, "needed_ring": None, "allow": True, "reason": "aucun tool"})
    if tool is None:
        return out
    try:
        needed = _tool_needed_ring(tool)
    except Exception as e:  # noqa: BLE001 — fail-closed
        out.update({"allow": False, "reason": f"capacite indeterminee: {e}"})
        return out
    ring = int(ident.get("ring", 4))
    out["needed_ring"] = needed
    out["allow"] = ring <= needed
    out["reason"] = f"ring {ring} {'<=' if out['allow'] else '>'} requis {needed}"
    # RSP observe (warn-only, gate reconcilie trust-aware) : pour les tools d'exec, croise le
    # verdict au plancher de confinement RSP. N'ALTERE PAS la decision authz ; log SEULEMENT
    # un exec untrusted qui devrait etre isole (cross-check du routing gVisor). 0 fichier critical.
    try:
        if ring >= 4 and tool in ("run", "run_job", "execute", "oracle_python_repl"):
            from nokido_agent.tools.forge_rsp_gate import gate as _rsp_gate
            _trust = "trusted" if ring < 4 else "untrusted"
            _rv = _rsp_gate("execute_code", sandbox="local", network=False, ring=ring, trust=_trust)
            if not _rv.get("ok"):
                import logging as _lg
                _lg.getLogger("forge_videur").warning(
                    f"[RSP][observe] {agent} ring={ring} tool={tool} -> {_rv.get('reason')} "
                    f"(verifier routage gVisor de l'exec untrusted)")
    except Exception:
        pass
    return out


def _encrypt(plaintext: str) -> bytes:
    """DPAPI (USER scope, flags=0 — seul le compte du hub déchiffre, + confidentiel
    qu'en machine) si dispo, sinon base64 marqué dégradé (le token est DÉJÀ hashé).
    Confidentialité ; la NON-RÉPUDIATION est assurée par la chaîne HMAC (cf _append_audit)."""
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(plaintext.encode("utf-8"), "videur", None, None, None, 0)
        return b"DPAPI:" + base64.b64encode(blob)
    except Exception:  # noqa: BLE001
        # Fallback honnête : on marque que c'est du clair encodé
        return b"DEGRADED_B64:" + base64.b64encode(plaintext.encode("utf-8"))


def _decrypt(b64_msg: bytes) -> str:
    if b"|" in b64_msg:  # strip la chaîne HMAC de non-répudiation (format blob|chain)
        b64_msg = b64_msg.rsplit(b"|", 1)[0]
    if b64_msg.startswith(b"DEGRADED_B64:"):
        raw = base64.b64decode(b64_msg[13:])
        return raw.decode("utf-8", "replace")
    
    # Compatibilité avec l'ancien format PLAIN:
    if b64_msg.startswith(b"PLAIN:"):
        return b64_msg[6:].decode("utf-8", "replace")

    try:
        import win32crypt
        payload = b64_msg
        if payload.startswith(b"DPAPI:"):
            payload = payload[6:]
        raw = base64.b64decode(payload)
        _d, plain = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
        return plain.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"[decrypt err: {e}]"


_HMAC_KEY_FILE = ROOT / "sandbox" / ".videur_hmac.key"
_hmac_key_cache: bytes | None = None


def _hmac_key() -> bytes:
    """Clé HMAC machine-locale (non-répudiation). Créée 1x atomique (O_EXCL, 0o600),
    DPAPI-protégée si dispo. La chaîne HMAC rend tamper/suppression/réordre détectables."""
    global _hmac_key_cache
    if _hmac_key_cache is not None:
        return _hmac_key_cache
    try:
        if _HMAC_KEY_FILE.exists():
            raw = _HMAC_KEY_FILE.read_bytes()
            if raw.startswith(b"DPAPI:"):
                try:
                    import win32crypt
                    _d, key = win32crypt.CryptUnprotectData(base64.b64decode(raw[6:]), None, None, None, 0)
                    _hmac_key_cache = key
                    return key
                except Exception:  # noqa: BLE001
                    pass
            _hmac_key_cache = raw  # dégradé : clé en clair
            return raw
    except Exception:  # noqa: BLE001
        pass
    key = _os.urandom(32)
    blob = key
    try:
        import win32crypt
        blob = b"DPAPI:" + base64.b64encode(win32crypt.CryptProtectData(key, "videur_hmac", None, None, None, 0))
    except Exception:  # noqa: BLE001
        pass
    try:
        _HMAC_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = _os.open(str(_HMAC_KEY_FILE), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o600)
        try:
            _os.write(fd, blob)
        finally:
            _os.close(fd)
    except FileExistsError:  # course : créée entre-temps -> relire la vraie clé
        try:
            raw = _HMAC_KEY_FILE.read_bytes()
            if raw.startswith(b"DPAPI:"):
                import win32crypt
                _d, key = win32crypt.CryptUnprotectData(base64.b64decode(raw[6:]), None, None, None, 0)
            else:
                key = raw
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    _hmac_key_cache = key
    return key


def _last_chain() -> str:
    """Dernier hash de chaîne (pour chaîner la prochaine entrée). '' si vide/legacy.
    Lit seulement la fin du fichier (borné, pas tout le log)."""
    try:
        if not _LOG.exists():
            return ""
        sz = _LOG.stat().st_size
        with open(_LOG, "rb") as f:
            f.seek(max(0, sz - 4096))
            tail = f.read().splitlines()
        for line in reversed(tail):
            if b"|" in line:
                return line.rsplit(b"|", 1)[1].decode("ascii", "replace")
            if line.strip():
                return ""  # entrée legacy non chaînée
    except Exception:  # noqa: BLE001
        pass
    return ""


def _stamp_rec(rec: dict) -> dict:
    """Date l'entrée AVANT chiffrement, via l'autorité unique des timecodes.

    Pourquoi DEDANS et pas en préfixe de ligne : le fichier est une chaîne HMAC
    `blob|chain`, et `_last_chain()` extrait le maillon par `rsplit(b"|", 1)`.
    Un champ ajouté en clair après le chaînon casserait la vérification, et un
    préfixe casserait le calcul du HMAC. L'horodatage appartient donc au dict
    chiffré — la non-répudiation le couvre alors comme le reste de l'entrée.

    N'écrase jamais un `ts` déjà posé par l'appelant.
    """
    try:
        from nokido_agent.app.forge_timecode import stamp_row

        return stamp_row(rec)
    except Exception:  # noqa: BLE001
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        if not rec.get("ts"):
            rec = dict(rec)
            rec["ts"] = _dt.now(tz=_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return rec


def _append_audit(rec: dict) -> None:
    """Entrée d'audit CHIFFRÉE (confidentialité) + CHAÎNÉE HMAC (non-répudiation) :
    tamper/suppression/réordonnancement détectables via verify_log()."""
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        blob = _encrypt(json.dumps(_stamp_rec(rec), ensure_ascii=False))
        prev = _last_chain()
        chain = hmac.new(_hmac_key(), prev.encode() + blob, hashlib.sha256).hexdigest()
        with open(_LOG, "ab") as f:
            f.write(blob + b"|" + chain.encode("ascii") + b"\n")
    except Exception:  # noqa: BLE001
        pass


def capture(identity: dict, tool: str, extra: dict | None = None) -> None:
    """Capture DYNAMIQUE + LOG de l'identité par requête. Token JAMAIS en clair (hash).
    Entrée chiffrée (DPAPI) + chaînée HMAC -> traçabilité non-répudiable (cf verify_log).

    `extra` : champs additionnels de contexte (ex. la décision du gate, l'action
    d'un tool multiplexé). Ils sont posés EN PREMIER, donc les champs canoniques
    priment : un appelant ne peut pas falsifier agent/ring/token_h/tool par ce
    biais. Sans ce paramètre, l'entrée ne disait que QUI se présente, jamais ce
    qu'il obtenait — insuffisant pour auditer l'écriture et l'exécution.
    """
    rec = dict(extra or {})
    rec.update({"ts": round(time.time(), 1), "agent": identity.get("agent"),
                "ring": identity.get("ring"), "via": identity.get("via"),
                "tool": tool, "token_h": identity.get("token_h")})
    _append_audit(rec)
    # VUE AGREGEE (observation seule). Le journal ci-dessus est chiffre en DPAPI
    # USER scope et appartient au compte OWNER : mesure 2026-09-02, le compte de
    # service ne peut pas le dechiffrer -- frontiere voulue, pas panne. Aucune
    # statistique ne peut donc etre construite en RELISANT ce fichier depuis le
    # corps ; elle doit naitre ici, au moment de l'observation.
    # Best-effort strict : la vue ne decide rien et ne casse jamais l'auth.
    try:
        from nokido_agent.app.forge_videur_audit import noter as _noter_vue

        _noter_vue(identity, tool, extra)
    except Exception:  # noqa: BLE001  # muet-ok : une vue ne casse jamais l'auth
        pass


def can_talk(src_ring: int, tool_ring_needed: int) -> bool:
    """Grille déterministe : un agent (src_ring) peut appeler un tool de ring requis
    tool_ring_needed SSI src_ring <= tool_ring_needed (ring bas = plus de droits)."""
    return int(src_ring) <= int(tool_ring_needed)


def propose_ring_change(agent: str, new_ring: int, by_ring: int, reason: str = "") -> dict:
    """GARDE-FOU : un changement de ring exige by_ring <= 1 (MASTER/SYSTEM). Audité.
    Phase 2 : annonce via facteur (forge_postal) aux agents affectés + user.
    Renvoie {ok, reason}. NE modifie PAS le store ici (Phase 2 applique après annonce)."""
    if int(by_ring) > 1:
        return {"ok": False, "reason": f"refusé : changement de ring exige ring<=1 (demandeur ring {by_ring})"}
    rec = {"ts": round(time.time(), 1), "action": "ring_change_proposed",
           "agent": agent, "new_ring": int(new_ring), "by_ring": int(by_ring), "reason": reason}
    _append_audit(rec)
    return {"ok": True, "reason": "proposé+audité (annonce facteur en Phase 2)"}


def verify_log() -> dict:
    """Re-vérifie la chaîne HMAC du log d'audit (non-répudiation) : détecte
    tamper/suppression/réordonnancement. Renvoie {ok, lines, broken_at}."""
    try:
        lines = [l for l in _LOG.read_bytes().splitlines() if l.strip()] if _LOG.exists() else []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "lines": 0, "broken_at": -1, "error": str(e)}
    key = _hmac_key()
    prev = ""
    for idx, line in enumerate(lines):
        if b"|" not in line:
            continue  # entrée legacy non chaînée -> ignorée (compat)
        blob, chain = line.rsplit(b"|", 1)
        chain_s = chain.decode("ascii", "replace")
        expect = hmac.new(key, prev.encode() + blob, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, chain_s):
            return {"ok": False, "lines": len(lines), "broken_at": idx}
        prev = chain_s
    return {"ok": True, "lines": len(lines), "broken_at": -1}


def _selftest() -> int:
    ok = 0
    total = 0
    fake_tokens = {"CLAUDE": "tokCLAUDE", "TRAY": "tokTRAY"}

    def chk(cond, label):
        nonlocal ok, total
        total += 1
        ok += bool(cond)
        print(f"  [{'OK' if cond else 'FAIL'}] {label}")

    # 1. identité forte par header
    i = resolve_identity("CLAUDE", "tokCLAUDE", local=True, agent_tokens=fake_tokens)
    chk(i["agent"] == "CLAUDE" and i["ring"] in (1, 0), f"header CLAUDE -> ring {i['ring']} via {i['via']}")
    # 2. reverse-token (header absent) retrouve le VRAI agent (anti-ring-4-fantôme)
    i2 = resolve_identity("", "tokCLAUDE", local=True, agent_tokens=fake_tokens)
    chk(i2["agent"] == "CLAUDE" and i2["via"] == "reverse_token", f"reverse-token -> {i2['agent']} via {i2['via']}")
    # 3. token jamais en clair
    chk(len(i["token_h"]) == 16 and "tokCLAUDE" not in i["token_h"], "token hashé (pas en clair)")
    # 4. can_talk (grille)
    chk(can_talk(1, 3) and not can_talk(4, 3), "can_talk: ring1<=3 OK, ring4<=3 NON")
    # 5. garde-fou changement de ring
    chk(not propose_ring_change("CLAUDE", 0, by_ring=4)["ok"], "ring-change par ring4 -> REFUSÉ")
    chk(propose_ring_change("CLAUDE", 3, by_ring=1)["ok"], "ring-change par ring1 -> proposé+audité")
    # 6. capture+log crypté roundtrip
    capture(i, "ask")
    try:
        last = _LOG.read_bytes().splitlines()[-1]
        dec = _decrypt(last)
        chk("ask" in dec and "tokCLAUDE" not in dec, "log crypté roundtrip (token absent en clair)")
    except Exception as e:  # noqa: BLE001
        chk(False, f"log roundtrip err: {e}")
    # 7. non-répudiation : chaîne HMAC valide, puis tamper -> détecté
    chk(verify_log().get("ok") is True, "chaîne HMAC valide après capture")
    try:
        _orig = _LOG.read_bytes()
        _lines = _orig.splitlines()
        if _lines:
            _blob, _chain = _lines[-1].rsplit(b"|", 1)
            _lines[-1] = _encrypt(json.dumps({"ts": 0, "agent": "EVIL", "tool": "pwn"})) + b"|" + _chain
            _LOG.write_bytes(b"\n".join(_lines) + b"\n")
            chk(verify_log().get("ok") is False, "tamper d'une entrée -> chaîne CASSÉE (détecté)")
        _LOG.write_bytes(_orig)  # restaure l'état d'origine
    except Exception as e:  # noqa: BLE001
        chk(False, f"tamper test err: {e}")

    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
