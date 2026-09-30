# -*- coding: utf-8 -*-
"""forge_transient_executor.py — PREMIER executor deterministe de preuve.

Ce module n'est **pas** un worker generique, ni un routeur, ni un dispatcher de
capacites. Il en connait UNE, cablee en dur, et refuse tout le reste. Le nommer
autrement serait s'attribuer une generalite qui n'a pas ete mesuree.

POURQUOI IL EXISTE. GEN-3 avait porte un transient jusqu'a « admissible et
adressable ». Entre cette decision et une preuve de resultat, il manquait un
maillon : quelque chose qui EXECUTE. La mesure du 2026-09-17 a montre qu'aucun
dispatcher de capacite deterministe n'existe dans le depot --
`forge_metier_dispatch` route vers une persona LLM+KB, `forge_at_dispatch` est
couple a la TUI, `forge_call_dynamic` et `forge_dynamic_tools` ne sont pas des
modules. C'est un manque architectural REEL, consigne comme dette ; ce fichier
ne le comble pas, il l'enjambe le temps de prouver UNE boucle.

POURQUOI CETTE CAPACITE-LA. `forge_m2m_protocol.validate(channel, payload)` a
ete retenue sur mesure, pas par gout : deterministe, locale, sans LLM, sans
reseau, sans reservation, sans ecriture (0 `open(`, 0 `write`, 0 `INSERT`),
recalculable par un tiers depuis `config/m2m_intents.json`, et DEJA en
production -- ses appelants reels sont `forge_mcp_registry` (le hub, deux sites)
et `forge_postal`.

LE PIEGE QU'ELLE PORTE, et qui fait tout l'interet de GEN-4 : `validate` est
FAIL-OPEN. Catalogue illisible -> elle rend `M2M_OK` avec une note
`validator-error`. Un verificateur qui relirait le code rendu par l'executor
validerait donc une PANNE comme un succes. D'ou `verifier()`, qui ne regarde pas
ce que l'executor a repondu : il relit le catalogue et refait le controle.

Verrouille par tests/nr/test_transient_gen4_execution_nr.py.
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/transient-executor : premiere execution deterministe d'un transient admis"

import hashlib
import time
from typing import Any, Dict, Optional

# DEUX capacites, et toujours pas un registre : le registre des capacites
# deterministes reste une dette ASSUMEE et VISIBLE
# (bb:dette_inventaire_capacites_deterministes_2026_09_17). Cette table a deux
# entrees est le GERME du besoin, pas sa reponse -- elle sera remplacee le jour
# ou plusieurs capacites seront prouvees, pas avant.
CAPACITE = "m2m.validate"          # GEN-4, interne au Spine
CAPACITE_CENSUS = "census.organ"   # GEN-5, EXTERIEURE au Spine
CAPACITE_LLM = "llm.local"         # GEN-6, intelligence LOCALE et souveraine

_VERIFICATEUR = "nokido"


def capacite_de(transient: Optional[dict]) -> Optional[str]:
    """Rend la capacite designee par le transient, ou None. N'invente rien."""
    methode = str(((transient or {}).get("source") or {}).get("method") or "")
    if methode.startswith("m2m."):
        return CAPACITE
    if methode == CAPACITE_CENSUS:
        return CAPACITE_CENSUS
    if methode == CAPACITE_LLM:
        return CAPACITE_LLM
    return None


def etat_llm_local() -> Dict[str, Any]:
    """Etat REEL du cerveau local, en DECLARANT le besoin au passage.

    ERREUR PAYEE le 2026-09-17 : avoir sonde un port et conclu « indisponible ».
    Ces backends sont ON-DEMAND -- ils s'eteignent sous regulation et se
    reveillent sur intention (`llama.wanted`, TTL 900 s). Un port ferme n'est
    donc pas une absence, c'est une VEILLE, et la regle owner est explicite :
    Nokido s'autoregule, on DECLARE le besoin, on n'attend pas. Les intentions
    trouvees ce jour-la dataient de 11,5 jours : personne ne declarait plus rien.

    Rend trois choses SEPAREES, parce que les confondre est le motif meme de la
    constitution : `port_ouvert` (TRANSPORT), `genere` (CAPACITE), et le detail.
    `genere` vaut None quand la question n'a pas pu etre posee -- jamais False
    par defaut, ce qui fabriquerait une panne.
    """
    detail = []
    sert = False
    try:
        import forge_llm_ondemand as _od
        st = _od.status() or {}
        llama = st.get("llama") or {}
        sert = bool(llama.get("sert"))
        if not sert:
            # DECLARER, pas attendre. L'intention a un TTL : la reposer est le
            # geste prevu, pas un contournement.
            _od.poser_intention("llama")
            detail.append("intention posee (llama.wanted) ; service en veille")
        else:
            detail.append("llama-server sert")
    except Exception as e:  # noqa: BLE001
        detail.append("etat on-demand illisible: %s" % str(e)[:60])
        return {"port_ouvert": None, "genere": None, "detail": "; ".join(detail)}

    if not sert:
        # Le port n'est pas ouvert ET l'intention vient d'etre posee : on ne
        # peut pas encore savoir s'il generera. `genere` reste None.
        return {"port_ouvert": False, "genere": None, "detail": "; ".join(detail)}

    # Le service sert : reste a PROUVER qu'un modele repond. Un port qui repond
    # ne prouve pas qu'un modele est charge -- piege paye le 2026-09-07, ou
    # `/api/tags` listait 16 modeles sans aucun runner.
    import json as _j
    import urllib.request as _u
    corps = _j.dumps({"prompt": "OK", "n_predict": 4, "temperature": 0}).encode()
    req = _u.Request("http://127.0.0.1:8091/completion", data=corps,
                     method="POST", headers={"Content-Type": "application/json"})
    try:
        with _u.urlopen(req, timeout=20) as r:
            _ = r.read(400)
        detail.append("generation prouvee")
        return {"port_ouvert": True, "genere": True, "detail": "; ".join(detail)}
    except Exception as e:  # noqa: BLE001
        detail.append("generation refusee: %s" % str(e)[:60])
        return {"port_ouvert": True, "genere": False, "detail": "; ".join(detail)}


def _organe_declare(fname: str) -> Optional[str]:
    """Relit la declaration d'organe a la SOURCE, pour verifier independamment.

    Emprunte la MEME fenetre (`HEAD_CHARS`) et la MEME regex (`DECL_RE`) que le
    lecteur : une verification qui lirait autrement ne verifierait pas la meme
    chose. RULES_SHARED le dit explicitement, apres trois formes payees le
    2026-09-06 -- declaration hors fenetre, mention prise pour une declaration,
    homonyme lu a la place du bon fichier.
    """
    try:
        import forge_module_census as _mc
        with open(fname, encoding="utf-8", errors="replace") as fh:
            tete = fh.read(int(getattr(_mc, "HEAD_CHARS", 12000)))
        m = _mc.DECL_RE.search(tete)
        if not m:
            return None
        brut = next((g for g in reversed(m.groups() or ()) if g), None) or m.group(0)
        brut = str(brut).strip()
        # La regex capture jusqu'a 90 caracteres : la valeur est suivie du
        # commentaire de fin de ligne. On coupe au guillemet FERMANT, sinon le
        # commentaire (« # organe declare le ... ») entre dans la valeur.
        for q in ("\"", "'"):
            if brut.startswith(q):
                fin = brut.find(q, 1)
                return brut[1:fin] if fin > 0 else brut[1:]
        return brut.split("#")[0].strip()
    except Exception:  # noqa: BLE001
        return None


def executer(transient: dict, admission: dict) -> Dict[str, Any]:
    """Execute la capacite si le transient est ADMIS. Sinon, ne l'execute pas.

    L'identite d'execution derive du `source_call_id` : deux observations du
    MEME appel partagent donc une execution. Ce n'est pas un `dedupe()` global
    -- deux appels legitimes distincts gardent deux executions, parce qu'ils
    portent deux identifiants de source distincts.
    """
    t = transient or {}
    base = {
        "transient_id": t.get("id"),
        "source_call_id": t.get("source_call_id"),
        "correlation_id": t.get("correlation_id"),
        "destination": (admission or {}).get("destination"),
        "capability": None,
        "result": None,
    }

    if (admission or {}).get("decision") != "ACCEPTED":
        # OBSERVE n'est pas ACCEPTE, et ACCEPTE n'est pas EXECUTE.
        return {**base, "status": "NOT_DISPATCHED",
                "reason": (admission or {}).get("reason") or "transient non admis"}

    capacite = capacite_de(t)
    if capacite is None:
        return {**base, "status": "NO_CAPABILITY",
                "reason": "aucune capacite connue pour la methode %r ; ce module "
                          "n'en porte qu'une, et n'en devine aucune"
                          % ((t.get("source") or {}).get("method"))}

    charge = t.get("payload") or {}

    # L'identite d'execution vient de la SOURCE, pas de l'horloge.
    graine = str(t.get("source_call_id") or t.get("id") or "")
    execution_id = "E-" + hashlib.sha256(graine.encode("utf-8")).hexdigest()[:16]

    if capacite == CAPACITE_LLM:
        etat = etat_llm_local()
        if not etat.get("genere"):
            # PROVIDER_UNAVAILABLE n'est PAS un echec de la tache : un echec de
            # transport ne dit RIEN de ce qui etait demande. Et aucune bascule
            # cloud : le premier chemin reste souverain.
            return {**base, "status": "PROVIDER_UNAVAILABLE",
                    "capability": capacite,
                    "execution_id": "E-" + hashlib.sha256(
                        str(t.get("source_call_id") or t.get("id") or "").encode()
                    ).hexdigest()[:16],
                    "provider_state": etat,
                    "reason": "cerveau local indisponible : %s" % etat.get("detail")}

    debut = time.perf_counter()
    if capacite == CAPACITE_LLM:
        import json as _j
        import urllib.request as _u
        invite = str((charge or {}).get("prompt") or "")
        corps = _j.dumps({"prompt": invite, "n_predict": 128,
                          "temperature": 0}).encode()
        req = _u.Request("http://127.0.0.1:8091/completion", data=corps,
                         method="POST", headers={"Content-Type": "application/json"})
        with _u.urlopen(req, timeout=60) as r:
            brut = _j.loads(r.read().decode("utf-8", "replace"))
        resultat = {"texte": brut.get("content"), "modele": brut.get("model"),
                    "tokens": (brut.get("tokens_predicted")
                               or (brut.get("timings") or {}).get("predicted_n"))}
        extra = {"payload": charge, "provider_state": {"genere": True}}
    elif capacite == CAPACITE:
        from forge_m2m_protocol import validate  # local : rien au chargement
        canal = str(charge.get("channel") or "")
        message = charge.get("message")
        resultat = validate(canal, message)
        extra = {"channel": canal, "payload": message}
    else:
        # `organ` DOIT recevoir le chemin : appelee avec le seul nom, elle rend
        # « ? non classe » faute de pouvoir lire la declaration du fichier, et
        # ce « non classe » serait un ARTEFACT D'APPEL, pas une mesure.
        import forge_module_census as _mc
        module = str(charge.get("module") or "")
        fname = charge.get("fname")
        relpath = charge.get("relpath")
        resultat = {"module": module, "fname": fname, "relpath": relpath,
                    "organe": _mc.organ(module, fname, relpath)}
        extra = {"payload": charge}
    ecoule_ms = (time.perf_counter() - debut) * 1000.0

    return {
        **base,
        "status": "COMPLETED",
        "capability": capacite,
        "execution_id": execution_id,
        "result": resultat,
        "elapsed_ms": round(ecoule_ms, 3),
        **extra,
    }


def _verifier_census(r: dict, ev) -> Dict[str, Any]:
    """Preuve independante pour `census.organ` -- avec ses limites DECLAREES.

    `organ()` dispose de QUATRE filets (carte explicite, mot-cle du nom,
    dossier, imports, puis declaration). Un verificateur qui ne relit que la
    DECLARATION ne peut donc trancher que lorsqu'elle existe. Sans elle, il ne
    peut pas reconstruire le raisonnement : `UNKNOWN` est alors la seule reponse
    honnete, et « je ne peux pas verifier » n'est pas « c'est faux ».
    """
    res = r.get("result") or {}
    fname = res.get("fname")
    rendu = str(res.get("organe") or "")
    declare = _organe_declare(fname) if fname else None

    if not declare:
        return {"etat": ev.UNKNOWN, "verifie_par": _VERIFICATEUR,
                "motif": "aucune declaration d'organe lisible a la source : la "
                         "verification independante ne peut pas trancher",
                "recalcul": "declaration absente",
                "accord_avec_executor": None,
                "execution_id": r.get("execution_id"),
                "correlation_id": r.get("correlation_id")}

    mot = declare.split("/")[0].split(":")[0].strip().lower()
    concorde = bool(mot) and mot in rendu.lower()

    # DIVERGENCE MESUREE le 2026-09-17 : `forge_m2m_protocol` DECLARE « snc/... »
    # et le census le classe « Cognition/Agentique/Raisonnement ». Ce n'est pas
    # une erreur -- la declaration est le DERNIER filet du census (carte, nom,
    # dossier, imports, puis declaration), donc un filet anterieur l'emporte
    # legitimement. Mais personne ne signalait l'ecart.
    #
    # REJETER serait faux : les deux sources ont raison chacune dans son ordre.
    # L'etat juste existe deja dans la couche a preuves -- CONTESTED, « deux
    # solutions prouvees : un contradicteur doit trancher, pas la majorite ».
    # On construit donc DEUX tentatives, une par observateur, au lieu d'ecraser
    # l'une des deux.
    tentatives = [ev.Tentative(
        modele="deterministe:%s" % CAPACITE_CENSUS,
        solution_id=rendu or "SANS_ORGANE",
        test_ok=True,
        preuves=["classement rendu par le census"],
        strategie="census_quatre_filets",
        erreur=None,
        transport_ok=True,
    )]
    if not concorde:
        tentatives.append(ev.Tentative(
            modele="deterministe:declaration_source",
            solution_id=declare,
            test_ok=True,
            preuves=["declaration relue a la source: %s" % declare[:80]],
            strategie="lecture_declaration",
            erreur=None,
            transport_ok=True,
        ))
    else:
        tentatives[0] = ev.Tentative(
            modele="deterministe:%s" % CAPACITE_CENSUS,
            solution_id=rendu or "SANS_ORGANE",
            test_ok=True,
            preuves=["declaration relue a la source: %s" % declare[:80],
                     "classement rendu par le census"],
            strategie="lecture_declaration",
            erreur=None,
            transport_ok=True,
        )
    verdict = ev.arbitrer(tentatives, min_voix=1, exiger_preuve=True)
    return {
        "etat": verdict.etat,
        "verifie_par": _VERIFICATEUR,
        "motif": verdict.motif or ("declaration %r concorde avec %r" % (mot, rendu)),
        "recalcul": "declaration relue a la source : %s" % declare[:80],
        "accord_avec_executor": concorde,
        "execution_id": r.get("execution_id"),
        "correlation_id": r.get("correlation_id"),
    }


def verifier(resultat: dict) -> Dict[str, Any]:
    """Preuve INDEPENDANTE : relit la source de verite et refait le controle.

    Ne lit JAMAIS `resultat["result"]["code"]` pour en deduire son verdict --
    ce serait recopier l'executor, et `validate` etant fail-open, ce serait
    valider une panne. Le code rendu ne sert qu'a detecter une DISCORDANCE.
    """
    r = resultat or {}
    if r.get("status") == "PROVIDER_UNAVAILABLE":
        import forge_swarm_evidence as _ev
        return {"etat": _ev.UNKNOWN, "verifie_par": _VERIFICATEUR,
                "motif": "fournisseur indisponible : un echec de transport ne "
                         "dit RIEN de la tache, elle n'a pas ete tentee",
                "recalcul": "non applicable",
                "accord_avec_executor": None,
                "execution_id": r.get("execution_id"),
                "correlation_id": r.get("correlation_id")}
    if r.get("status") != "COMPLETED":
        return {"etat": "UNKNOWN", "verifie_par": _VERIFICATEUR,
                "motif": "rien a verifier : statut %r" % r.get("status")}

    import forge_swarm_evidence as ev
    if r.get("capability") == CAPACITE_CENSUS:
        return _verifier_census(r, ev)
    if r.get("capability") == CAPACITE_LLM:
        # Un texte de modele n'est pas verifiable par recalcul : sans critere
        # deterministe attache a la tache, UNKNOWN est la reponse correcte.
        # Fabriquer une preuve parce que le modele a repondu serait exactement
        # ce que la couche a preuves refuse.
        return {"etat": ev.UNKNOWN, "verifie_par": _VERIFICATEUR,
                "motif": "sortie de modele non verifiable par recalcul ; "
                         "aucune preuve deterministe attachee a cette tache",
                "recalcul": "aucun critere deterministe",
                "accord_avec_executor": None,
                "execution_id": r.get("execution_id"),
                "correlation_id": r.get("correlation_id")}

    from forge_m2m_protocol import _load_catalog
    cat = _load_catalog() or {}
    intents = cat.get("intents") or {}
    regles = cat.get("schema_rules") or {}
    if not intents or not regles:
        # La source de verite ne permet plus de conclure. S'abstenir est ici une
        # reussite : c'est exactement ce que `validate` NE fait pas (fail-open).
        return {"etat": ev.UNKNOWN, "verifie_par": _VERIFICATEUR,
                "motif": "catalogue illisible ou vide : la verification "
                         "independante est impossible, on s'abstient"}

    charge = r.get("payload")
    canal = r.get("channel") or ""
    requis = (regles.get("required_fields_by_channel") or {}).get(canal, [])
    alias = set(regles.get("intent_field_aliases") or ("intent", "intent_code"))

    # --- LE RECALCUL, fait ici et nulle part ailleurs ---------------------
    # PIEGE PAYE EN RUNTIME le 2026-09-17, invisible aux tests : cette branche
    # rendait « payload non structure -> invalide » pour TOUT non-dict. Or le
    # contrat TOLERE la prose courte (`prose_max_words`, code `M2M_OK_PROSE`),
    # regle legacy encore utilisee par des pairs. Le verificateur etait donc
    # PLUS STRICT que le contrat qu'il verifie, et rejetait du valide : sur 4
    # messages M2M reels, 2 sortaient REJECTED a tort. Un verificateur applique
    # la regle ECRITE, jamais la sienne -- sinon il ne prouve que son opinion.
    if not isinstance(charge, dict):
        mots = len([m for m in str(charge or "").split() if m.strip()])
        maxi = int(regles.get("prose_max_words", 15))
        if charge is None:
            valide, pourquoi = False, "payload vide"
        elif mots <= maxi:
            valide, pourquoi = True, ("prose de %d mots <= %d : toleree par le "
                                      "contrat" % (mots, maxi))
        else:
            valide, pourquoi = False, ("prose de %d mots > %d" % (mots, maxi))
    else:
        code_intent = ""
        for a in alias:
            if charge.get(a):
                code_intent = str(charge[a])
                break
        manquants = [c for c in requis if c not in alias and c not in charge]
        if not code_intent:
            valide, pourquoi = False, "aucun intent"
        elif code_intent not in intents:
            valide, pourquoi = False, "intent %r hors dictionnaire" % code_intent
        elif manquants:
            valide, pourquoi = False, "champs requis manquants: %s" % ", ".join(manquants)
        else:
            valide, pourquoi = True, "intent au dictionnaire et champs requis presents"

    # Le code de l'executor ne FONDE pas le verdict ; il sert a reperer un
    # desaccord entre ce qui a ete rendu et ce que la source de verite dit.
    code_rendu = str(((r.get("result") or {}).get("code")) or "")
    accord = (valide and code_rendu in ("M2M_OK", "M2M_OK_PROSE")) or \
             ((not valide) and (code_rendu.startswith("M2M_ERR")
                                or code_rendu == "M2M_WARN_PROSE"))

    tentative = ev.Tentative(
        modele="deterministe:%s" % (r.get("capability") or CAPACITE),
        solution_id=code_rendu or "SANS_CODE",
        test_ok=bool(valide),
        preuves=["recalcul_catalogue:%s" % pourquoi],
        strategie="validation_contrat",
        erreur=None,
        transport_ok=True,
    )
    # min_voix=1 : la redondance de voix existe pour contrer la VARIANCE DES
    # MODELES. Un calcul deterministe n'en a pas -- une execution plus une
    # verification independante suffisent. `arbitrer` n'est pas modifie ;
    # c'est son parametre prevu, et le NR fige ce choix.
    verdict = ev.arbitrer([tentative], min_voix=1, exiger_preuve=True)

    return {
        "etat": verdict.etat,
        "verifie_par": _VERIFICATEUR,
        "motif": verdict.motif or pourquoi,
        "recalcul": pourquoi,
        "accord_avec_executor": accord,
        "execution_id": r.get("execution_id"),
        "correlation_id": r.get("correlation_id"),
    }
