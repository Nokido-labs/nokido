# -*- coding: utf-8 -*-
"""UI_ACCEPTANCE_WITNESS — rendre lisible ce qu'une campagne UI a reellement etabli.

POURQUOI CE MODULE EXISTE. Le 2026-09-09, le gate ui-acceptance a rendu « interface
injoignable » alors que :7400 repondait HTTP 401. Un seul mot recouvrait TROIS etats
distincts -- service absent, navigateur incapable de demarrer, application non
authentifiee. Cette agregation a coute trois changements de compte et deux
diagnostics annonces comme des causes avant d'avoir ete mesures.

Le temoin repond apres coup a quatre questions REFUTABLES :
    qu'a-t-on execute ?  qu'a-t-on PAS execute ?
    l'application a-t-elle vraiment ete jugee ?  combien de temps cela a pris ?

ANTI-DUP. On ne reinvente rien : `sandbox/ui_campaign/report.json` porte deja
`verdict`, `duree_s`, `route_en_cause`, `routes_non_jugees`, `couverture_clics`,
`pages` et `clicks`. Ce module AGREGE ce rapport avec ce que seul `ci_local` connait
(identite, selection) et avec les deux couches mesurees nulle part : transport et
navigateur. La duree vient du rapport et n'est jamais recalculee -- deux mesures de
la meme grandeur divergent le jour ou l'une est corrigee.

QUATRE INVARIANTS, qui sont quatre confusions payees :

    transport inconnu     != echec applicatif
    echec navigateur      != service injoignable
    absence de verdict    != PASS
    --only <gate>         != execution des autres gates

Le dernier est le moins intuitif : si l'exclusivite est violee, la duree mesuree ne
veut plus rien dire, et le temoin sort FAILED meme quand l'application repond PASS.
Un NR l'avait deja etabli -- « le bon gate s'execute » ne prouve pas « SEUL le bon
gate s'execute ».
"""

__FORGE_COLOR__ = "qualite/gate : temoin structure du contrat d acceptation UI"

# Le rapport de campagne parle son vocabulaire ; le temoin parle le sien. La table
# est explicite pour qu'un mot inconnu tombe sur UNKNOWN et non sur un cote sain.
_VERDICTS = {"CONFORME": "PASS", "VIOLE": "FAIL", "VIOLÉ": "FAIL",
             # ELARGI le 2026-09-16. La campagne rend desormais quatre etats de
             # defaut et non deux. Les ecraser tous sur UNKNOWN faisait ecrire du
             # MEME MOT « le gate n'a pas pu s'authentifier » et « je n'ai pas pu
             # lire le rapport de campagne » : le premier est une panne du GATE,
             # le second une panne de l'INSTRUMENT, et on ne repare pas la meme
             # chose. Ce n'est PAS une sortie de la liste blanche, c'est son
             # extension -- un mot hors de cette table tombe toujours sur UNKNOWN,
             # et aucun de ces trois-la n'est certifiant.
             "AUTH_FAILURE": "AUTH_FAILURE",
             "DEGRADE": "DEGRADE",
             "INDISPONIBLE": "INDISPONIBLE"}


def _tri(valeur):
    """Trois etats preserves : None reste None, le reste devient booleen.

    MESURE 2026-09-09, premier temoin reel (run 34390571371) : le temoin affichait
    `service_reachable: false` a cote de `verdict: PASS`, alors que 20 routes avaient
    ete chargees. La campagne n'avait simplement pas sonde le transport -- valeur
    `None` -- et `bool(None)` valant False, « pas mesure » devenait « mesure et
    negatif ». La confusion que ce module existe pour supprimer, reintroduite a
    l'etage suivant par une conversion de type.
    """
    return None if valeur is None else bool(valeur)


def _motif(transport: dict, browser: dict, verdict: str,
           route_en_cause, non_selected, degradees=()) -> str:
    """La raison NOMME la couche fautive, dans l'ordre ou les couches se traversent.

    L'ordre compte : un service injoignable explique un navigateur inutile, l'inverse
    est faux. Remonter la premiere couche en defaut evite d'accuser la suivante.
    """
    if non_selected:
        return ("exclusivite violee : %d gate(s) non demande(s) execute(s) — %s"
                % (len(non_selected), ", ".join(str(g) for g in non_selected)))
    if verdict == "FAIL":
        routes = ", ".join(str(r) for r in (route_en_cause or [])) or "route non nommee"
        return "contrat non tenu sur %s" % routes
    if verdict == "AUTH_FAILURE":
        return ("login du gate NON etabli : le service REPOND, on a vu le "
                "formulaire de login et non les pages demandees -- ni contrat "
                "tenu, ni contrat viole. Ce qui est a reparer est le login du "
                "GATE, pas le service")
    if verdict == "DEGRADE":
        noms = ", ".join(str(r) for r in (degradees or [])) or "route non nommee"
        return ("routes SERVIES mais en defaut sur page vide, mot d'erreur rendu, "
                "exception JS ou API >= 400 : %s" % noms)
    if verdict == "INDISPONIBLE":
        return ("le service a cesse de repondre pendant la passe : les routes "
                "restantes n'ont jamais ete servies, elles ne sont ni tenues ni "
                "violees")
    if verdict == "PASS":
        return ""
    # `is False` et non `not ...` : un transport NON MESURE ne doit pas faire
    # accuser le reseau. On ne designe une couche que si on l'a REGARDEE.
    if transport.get("service_reachable") is False:
        return ("service injoignable sur %s — aucune page n'a pu etre demandee"
                % (transport.get("endpoint") or ":7400"))
    if transport.get("http_status") in (401, 403):
        return ("authentification requise (HTTP %s) : le service REPOND, "
                "l'application n'a pas pu etre jugee" % transport.get("http_status"))
    if browser.get("launched") is False:
        return ("navigateur non lance (%s) alors que le service repond — couche "
                "navigateur, pas couche reseau"
                % (browser.get("executable") or "executable non nomme"))
    if browser.get("context_created") is False:
        return ("navigateur lance mais contexte non cree — le harnais meurt entre "
                "le demarrage et la premiere page")
    if transport.get("service_reachable") is None:
        return ("contrat non juge et transport NON MESURE — on ne sait pas si le "
                "service repondait, ce n'est pas la meme chose qu'un service absent")
    return "contrat non juge, cause non identifiee par le temoin"


def construire(obs: dict) -> dict:
    """Observations -> UI_ACCEPTANCE_WITNESS normalise, avec son verdict `final`.

    Fonction PURE : elle ne lit ni fichier ni reseau, ce qui la rend testable sur
    donnees synthetiques AVANT la campagne qu'elle mesure. Un temoin ecrit apres
    coup se decouvre illisible pendant le run qu'il devait eclairer.
    """
    obs = obs or {}
    identity = dict(obs.get("identity") or {})
    selection = dict(obs.get("selection") or {})
    transport = dict(obs.get("transport") or {})
    browser = dict(obs.get("browser") or {})
    report = dict(obs.get("report") or {})
    timing = dict(obs.get("timing") or {})

    non_selected = list(selection.get("non_selected_gates_executed") or [])
    verdict = _VERDICTS.get(str(report.get("verdict") or "").upper(), "UNKNOWN")
    route_en_cause = list(report.get("route_en_cause") or [])
    degradees = list(report.get("routes_degradees") or [])
    raison = _motif(transport, browser, verdict, route_en_cause, non_selected,
                    degradees)

    # ORDRE DES REGLES, et il n'est pas commutatif : l'exclusivite se juge AVANT
    # l'application. Une campagne verte obtenue pendant que d'autres gates tournaient
    # ne prouve pas ce qu'elle pretend -- sa duree est celle d'autre chose.
    # L'IDENTITE EST UNE CONDITION DE LA CERTIFICATION. Mesure du 2026-09-09 : le
    # premier temoin reel a rendu `PROVEN` avec `tested_sha: null` -- il certifiait
    # sans dire QUOI. Un certificat anonyme n'est pas un certificat. Le manque ne
    # MASQUE pas un contrat viole pour autant : FAILED se juge avant.
    sha = identity.get("tested_sha")
    if non_selected:
        final = "FAILED"
    elif verdict == "FAIL":
        final = "FAILED"
    elif verdict in ("AUTH_FAILURE", "DEGRADE", "INDISPONIBLE"):
        # Rendus TELS QUELS, apres FAILED et jamais avant : un contrat viole se
        # juge en premier. Les ecraser sur UNKNOWN jetterait la seule information
        # qui dit QUOI reparer ; les ranger du cote sain serait pire, aucun des
        # trois n'est certifiant.
        final = verdict
    elif verdict == "PASS" and not sha:
        final = "UNKNOWN"
        raison = ("contrat tenu mais sha NON RENSEIGNE : le temoin ne dit pas sur "
                  "quel etat il porte, il ne certifie donc rien")
    elif verdict == "PASS":
        final = "PROVEN"
    else:
        final = "UNKNOWN"

    return {
        "identity": {
            "tested_sha": identity.get("tested_sha"),
            "run_id": identity.get("run_id"),
        },
        "selection": {
            "requested": selection.get("requested"),
            "selected": list(selection.get("selected") or []),
            "non_selected_gates_executed": non_selected,
            "unexpected_gate_executions": len(non_selected),
        },
        "transport": {
            "endpoint": transport.get("endpoint"),
            "service_reachable": _tri(transport.get("service_reachable")),
            "http_status": transport.get("http_status"),
        },
        "browser": {
            "executable": browser.get("executable"),
            "launched": _tri(browser.get("launched")),
            "context_created": _tri(browser.get("context_created")),
        },
        "application": {
            "verdict": verdict,
            "reason": raison,
            "route_en_cause": route_en_cause,
            "routes_non_jugees": list(report.get("routes_non_jugees") or []),
            "couverture": report.get("couverture_clics"),
        },
        "timing": {
            # La duree vient du RAPPORT : la recalculer ici ferait deux mesures de la
            # meme grandeur, qui divergeraient au premier correctif de l'une.
            "duration_s": report.get("duree_s"),
            "started": timing.get("started"),
            "finished": timing.get("finished"),
        },
        "final": final,
    }
