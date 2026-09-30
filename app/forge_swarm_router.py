"""
forge_swarm_router.py — SERVING : Couche de routage Swarm (intelligence x cadre).

Ce module est le point d'entrée pour router une sous-tâche au sein du Swarm.
Conformément à la vision "Accès instantané avec le bon cadre sur qui sert la bonne intelligence" :
1. CADRE (Police) : Consulte `forge_videur.authorize` pour valider l'identité × capacité (ring).
2. SERVING (Intelligence) : Fédère `forge_llm_router.router_call` pour obtenir la réponse
   sans réinventer l'orchestration LLM de bas niveau.
"""

from typing import Any, Dict, Optional

from nokido_agent.app.forge_videur import authorize
from nokido_agent.app.forge_llm_router import router_call

def route_subtask(
    agent_cible: str,
    task_prompt: str,
    tool_vise: Optional[str] = None,
    token: str = "",
    local: bool = True,
    use_case: str = "general",
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Route une sous-tâche vers l'agent cible après vérification immunitaire (Videur).
    
    Args:
        agent_cible: Le nom de l'agent (ex: "CLAUDE", "GEMINI", "NETCFG").
        task_prompt: La description de la tâche à accomplir.
        tool_vise: L'outil MCP ou la capacité requise (ex: "run", "write").
        token: Le token d'authentification pour le Videur.
        local: Si la requête provient du réseau local (True par défaut).
        use_case: Le cas d'usage pour le routeur LLM (ex: "fast", "reasoning").
        **kwargs: Arguments supplémentaires passés au routeur LLM (max_tokens, etc.).
        
    Returns:
        dict avec status ("ok" ou "error"), result ou reason, et les metadonnées de sécurité.
    """
    # 1. AUTORITÉ / CADRE (Police)
    auth_result = authorize(agent=agent_cible, token=token, local=local, tool=tool_vise)
    
    if not auth_result.get("allow", False):
        return {
            "status": "error",
            "reason": f"Videur a refusé l'accès: {auth_result.get('reason', 'non autorisé')}",
            "security_context": auth_result
        }
    
    # 1.bis PARTAGE / EGRESS (politique) -- « ai-je le droit de donner CETTE
    # information a CE cerveau ? ». Le Videur vient de valider QUI parle ; personne
    # ne demandait OU la donnee avait le droit d'aller. Le SemanticFirewall redige le
    # contenu et la SovereignMembrane l'aliase : aucun des deux ne decide la
    # DESTINATION.
    # MODE SHADOW par defaut : la decision est calculee et rendue, JAMAIS appliquee,
    # tant qu'aucun appelant ne declare sa classe de donnee. Armer d'emblee refuserait
    # tout appel existant -- l'erreur exacte payee sur le M2M le 2026-09-01.
    # Le contexte est un OBJET, plus un champ perdu dans `**kwargs` : un champ libre
    # s'oublie en silence, un contexte declare se voit -- a la lecture comme au test
    # AST. Les anciennes cles restent acceptees le temps que les appelants migrent,
    # mais elles construisent alors un contexte explicite plutot que de flotter.
    _ctx = kwargs.pop("context", None)
    if _ctx is None:
        _classe = kwargs.pop("data_class", None)
        _collab = kwargs.pop("collaboration", None)
        _audience = kwargs.pop("audience", None)
        if any(x is not None for x in (_classe, _collab, _audience)):
            from nokido_agent.app.forge_share_policy import SwarmRequestContext as _Ctx, INCONNU as _INC

            _ctx = _Ctx(identity=agent_cible or _INC,
                        audience=tuple(_audience or ()),
                        data_class=_classe or _INC,
                        collaboration=_collab or _INC)
    else:
        for _vieux in ("data_class", "collaboration", "audience"):
            kwargs.pop(_vieux, None)
    partage = None
    try:
        from nokido_agent.app.forge_share_policy import applique as _applique
        from nokido_agent.app.forge_share_policy import preflight_contexte as _preflight

        partage = _preflight(_ctx)
        if _applique(partage):
            return {
                "status": "error",
                "reason": "politique de partage: %s" % partage.get("raison", ""),
                "security_context": auth_result,
                "partage": partage,
            }
    except Exception as e:  # noqa: BLE001
        # TROISIEME ETAT : politique INDISPONIBLE. En shadow on continue en le
        # DISANT ; on ne fabrique pas un « autorise » a partir d'une panne.
        partage = {"decision": "UNKNOWN", "raison": "politique indisponible: %s" % e}

    # 2. INTELLIGENCE / SERVING (Routeur LLM existant)
    # L'identité et la capacité sont validées, on sert l'intelligence.
    try:
        llm_response = router_call(
            prompt=task_prompt,
            use_case=use_case,
            context=_ctx,
            **kwargs
        )

        # LIRE LE VERDICT DE L'APPELE. `router_call` rend `{ok: False, error: ...}` quand
        # aucun provider n'a repondu ; cette fonction renvoyait quand meme `status: ok`
        # avec un texte vide, et l'aval traitait donc un ECHEC comme une reponse. Meme
        # famille que « rc=0 ne prouve rien » : ici on ne lisait meme pas le champ.
        if llm_response.get("ok") is False:
            return {
                "status": "error",
                "reason": llm_response.get("error") or "appel LLM en echec",
                "security_context": auth_result,
                "provider_used": llm_response.get("provider"),
                # Distingue « plus personne d'autre a interroger » d'une panne.
                "diversite_epuisee": bool(llm_response.get("diversite_epuisee")),
                "partage": partage,
            }

        return {
            "status": "ok",
            "result": llm_response.get("text", llm_response.get("response", str(llm_response))),
            "security_context": auth_result,
            "provider_used": llm_response.get("provider", "unknown"),
            # COUT CONSERVE (2026-08-26). `router_call` rend deja `elapsed_ms` et
            # `tokens` (forge_llm_router, docstring L967) : cette fonction les
            # JETAIT. Consequence mesuree : aucune trace de ce que coute un fanout,
            # donc aucun gain ajuste au cout calculable en aval -- une mesure
            # produite a la source et perdue par son appelant.
            "elapsed_ms": float(llm_response.get("elapsed_ms") or 0.0),
            "tokens": int(llm_response.get("tokens") or 0),
            "model": llm_response.get("model", ""),
            # La decision de partage voyage AVEC la reponse : sans elle, impossible
            # de mesurer plus tard combien d'appels seraient refuses une fois armes.
            "partage": partage,
        }
    except Exception as e:
        return {
            "status": "error",
            "reason": f"Erreur lors du routing LLM: {str(e)}",
            "security_context": auth_result
        }


# ==========================================================================
# COUCHE SWARM A PREUVES (2026-08-20)
# --------------------------------------------------------------------------
# `route_subtask` ci-dessus fait du routage LLM single-shot AUTORISE : une
# demande, un provider, une reponse traitee comme un verdict. C'est le bon
# executant, ce n'est pas une intelligence collective.
#
# Cette couche ne le remplace pas -- elle l'appelle N fois sous des ANGLES
# differents, classe ce qui revient, et laisse des preuves deterministes
# trancher. Les LLM PROPOSENT ; les tests, l'AST et les invariants DECIDENT.
# ==========================================================================

import hashlib
import re as _re

from nokido_agent.app.forge_swarm_evidence import (
    Tentative, arbitrer, classer_erreur, strategie_reprise,
    SECURITY_REJECTION,
)

# Angles d'attaque. Le meme modele interroge sous deux angles differents
# apporte plus qu'un second modele repetant le premier : c'est la diversite qui
# fait la valeur d'un fanout, pas le nombre d'appels.
ANGLES = {
    "minimal": "Corrige au plus juste, sans elargir la portee.",
    "cause_racine": "Ne corrige pas le symptome : identifie la cause racine.",
    "contrat": "Verifie d'abord le contrat/l'API attendue, puis corrige.",
    "regression": "Cherche ce qui a change recemment et a pu introduire cela.",
    "adversaire": "Cherche pourquoi la solution evidente serait FAUSSE ici.",
}

# Politiques. `fanout` est un PLAFOND d'appels, `min_voix` le seuil de voix
# INDEPENDANTES exige pour conclure -- les deux ne se confondent pas : cinq
# appels au meme modele restent une seule voix.
POLITIQUES = {
    "simple":    {"fanout": 1, "min_voix": 1, "exiger_preuve": False},
    "incertain": {"fanout": 2, "min_voix": 2, "exiger_preuve": False},
    "important": {"fanout": 3, "min_voix": 2, "exiger_preuve": True},
    "critique":  {"fanout": 5, "min_voix": 2, "exiger_preuve": True},
}

MODES = ("single", "hedged", "quorum", "adversarial")

_MODE_PAR_POLITIQUE = {"simple": "single", "incertain": "hedged",
                       "important": "quorum", "critique": "adversarial"}


def _angles_pour(mode: str, fanout: int) -> list:
    if mode == "single":
        return ["minimal"]
    if mode == "adversarial":
        ordre = ["minimal", "cause_racine", "contrat", "adversaire", "regression"]
    else:
        ordre = ["minimal", "cause_racine", "contrat", "regression", "adversaire"]
    return ordre[:max(1, fanout)]


def _empreinte(texte: str) -> str:
    """Identifie une SOLUTION, pas un texte : deux reponses equivalentes a la
    ponctuation et aux blancs pres doivent partager leur soutien."""
    noyau = _re.sub(r"\s+", " ", (texte or "")).strip().lower()
    if not noyau:
        return ""
    return hashlib.sha256(noyau.encode("utf-8", "replace")).hexdigest()[:16]


def score_de(t) -> float | None:
    """Score d'une tentative : la PREUVE, jamais un juge.

    1.0 = le verificateur deterministe a valide · 0.0 = il a refuse ·
    None = NON MESURE. Le troisieme etat n'est pas une politesse : sans lui, un
    fanout dont aucune tentative n'a ete verifiee rendrait « 0 % » au lieu de
    « je n'ai pas regarde », et le gain se lirait comme une degradation.
    """
    return None if t.test_ok is None else (1.0 if t.test_ok else 0.0)


def cout_de(tentatives: list) -> dict:
    """Ce que ce fanout a coute. `tokens_mesures` est le DENOMINATEUR : un
    backend local qui ne rend pas d'usage laisse `tokens` a 0, et un total de 0
    sur 5 appels ne veut pas dire « gratuit »."""
    tokens = sum(int(getattr(t, "tokens", 0) or 0) for t in tentatives)
    mesures = sum(1 for t in tentatives if int(getattr(t, "tokens", 0) or 0) > 0)
    return {
        "appels": len(tentatives),
        "tokens": tokens,
        "tokens_mesures": mesures,
        "tokens_inconnus": len(tentatives) - mesures,
        "latence_ms": round(sum(float(getattr(t, "latence_ms", 0.0) or 0.0)
                                for t in tentatives), 1),
        "tokens_par_appel": round(tokens / mesures, 1) if mesures else None,
    }


def gain_collectif(tentatives: list, solution_retenue: str = "") -> dict:
    """Ce que le collectif apporte -- et ce qu'il retire -- SANS appel de plus.

    Un fanout PORTE SES PROPRES BASELINES : chaque tentative est un agent seul,
    deja paye. Relancer la tache en `single` pour obtenir un `best_single`
    doublerait la facture pour une information qu'on tient deja.

    DEUX baselines, parce qu'une seule ment dans un sens ou dans l'autre :

      * `oracle` = la MEILLEURE tentative. Comme l'arbitrage choisit PARMI les
        tentatives, le collectif ne peut jamais la depasser : `gain_vs_oracle`
        est donc <= 0 et mesure le REGRET -- ce qu'on perd en choisissant mal.
        Strictement negatif = la cooperation a DEGRADE le resultat. C'est le cas
        negatif que la litterature dit central et que personne ne mesure chez soi.
      * `moyen` = l'esperance d'un agent tire au hasard, c'est-a-dire ce qu'on
        aurait eu SANS savoir lequel appeler. `gain_vs_moyen` mesure alors
        l'apport reel de la selection.

    Comparer au seul `oracle` fait toujours perdre le collectif ; au seul
    `moyen`, toujours gagner. Les deux ensemble disent la verite.
    """
    scores = [(t, score_de(t)) for t in tentatives if getattr(t, "utilisable", False)]
    mesures = [s for _, s in scores if s is not None]
    out = {
        "tentatives": len(tentatives),
        "mesurees": len(mesures),
        "non_mesurees": len(tentatives) - len(mesures),
        "oracle": None, "moyen": None, "collectif": None,
        "gain_vs_oracle": None, "gain_vs_moyen": None,
        "degrade": None, "gain_ajuste_par_ktokens": None, "raison": "",
        # Une tache CONTESTEE n'est pas une tache non mesuree : le collectif a
        # trouve -- parfois deux fois -- mais n'a rien livre. Confondre les deux
        # ferait passer un exces de prudence pour une cecite. Mesure 2026-08-26 :
        # sur 3 taches reelles, 2 sont sorties CONTESTED avec les DEUX tentatives
        # prouvees, et tombaient dans le seau « non mesuree ».
        "livre": None, "score_si_livre": None,
    }
    if not mesures:
        out["raison"] = ("aucun verificateur deterministe n'a tranche : rien n'est "
                         "mesure, et rien n'est donc affirme")
        return out
    oracle, moyen = max(mesures), sum(mesures) / len(mesures)
    retenue = next((s for t, s in scores if t.solution_id == solution_retenue), None)
    out.update({"oracle": oracle, "moyen": round(moyen, 4), "collectif": retenue,
                "livre": retenue is not None, "score_si_livre": oracle})
    if retenue is None:
        # TROIS cas, parce que deux les ecraseraient : le collectif peut avoir trouve
        # DEUX fois (et refuser de departager), avoir trouve UNE fois (et manquer de
        # voix pour conclure), ou n'avoir rien trouve du tout. Ces trois-la appellent
        # des gestes opposes -- arbitrer, elargir la diversite, chercher ailleurs.
        prouvees = len({t.solution_id for t, s in scores if s == 1.0})
        if prouvees >= 2:
            out["raison"] = (
                "CONTESTEE : %d solutions prouvees s'opposent, aucune livree — le "
                "collectif a trouve mais n'a pas tranche. Cout de prudence, pas "
                "cecite : a compter separement des taches non mesurees." % prouvees)
        elif prouvees == 1:
            out["raison"] = (
                "NON LIVREE : une solution etait prouvee et n'a pas ete retenue — "
                "typiquement le seuil de voix independantes n'est pas atteint. Le "
                "defaut est du cote de la DIVERSITE, pas de la reponse.")
        else:
            out["raison"] = ("aucune solution retenue, ou retenue sans mesure : le "
                             "collectif ne se compare a rien")
        return out
    out["gain_vs_oracle"] = round(retenue - oracle, 4)
    out["gain_vs_moyen"] = round(retenue - moyen, 4)
    out["degrade"] = retenue < oracle
    surcout = sum(int(getattr(t, "tokens", 0) or 0) for t in tentatives)
    mesures_tok = sum(1 for t in tentatives if int(getattr(t, "tokens", 0) or 0) > 0)
    if mesures_tok and len(tentatives) > 1:
        # Surcout = ce que le fanout ajoute a UN appel moyen, jamais le total.
        supp = surcout - (surcout / mesures_tok)
        if supp > 0:
            out["gain_ajuste_par_ktokens"] = round(out["gain_vs_moyen"] / (supp / 1000.0), 4)
        else:
            out["raison"] = "surcout nul : un seul appel a produit"
    else:
        out["raison"] = ("cout en tokens non mesure par le backend : le gain brut "
                         "reste valide, son rapport au cout ne l'est pas")
    return out


def route_swarm(agent_cible: str, task_prompt: str, politique: str = "important",
                mode: str = "", token: str = "", tool_vise=None, local: bool = True,
                use_case: str = "general", verificateur=None,
                **kwargs: Any) -> Dict[str, Any]:
    """Interroge plusieurs fois sous des angles differents, puis ARBITRE.

    `verificateur(texte) -> (test_ok, preuves)` est la porte deterministe. Sans
    elle, aucune solution ne peut etre PROUVEE : le verdict plafonne alors a
    UNKNOWN/abstain, ce qui est le comportement voulu -- un swarm sans preuve
    ne doit pas conclure, il doit le dire.

    Retour : le verdict, plus la trace de CHAQUE tentative. Un provider qui
    tombe ne casse plus la tache ; un provider qui repond ne devient plus la
    verite.
    """
    if politique not in POLITIQUES:
        return {"status": "error", "reason": "politique inconnue: %s" % politique}
    cfg = POLITIQUES[politique]
    mode = mode or _MODE_PAR_POLITIQUE[politique]
    if mode not in MODES:
        return {"status": "error", "reason": "mode inconnu: %s" % mode}

    tentatives = []
    # DIVERSITE DE MODELE (2026-08-26). Un angle nouveau pose a la MEME intelligence ne
    # produit pas une seconde voix : `groupe_independance` compte par famille de modele.
    # On demande donc explicitement un autre provider a chaque tour. `single` n'exclut
    # rien -- il ne cherche pas de second avis, il veut le meilleur.
    entendus: list = []
    for angle in _angles_pour(mode, cfg["fanout"]):
        prompt = "%s\n\n[ANGLE IMPOSE] %s" % (task_prompt, ANGLES[angle])
        appel = dict(kwargs)
        if mode != "single" and entendus:
            appel["exclure"] = tuple(entendus)
        rep = route_subtask(agent_cible=agent_cible, task_prompt=prompt,
                            tool_vise=tool_vise, token=token, local=local,
                            use_case=use_case, **appel)
        if rep.get("provider_used") and rep.get("provider_used") not in entendus:
            entendus.append(rep["provider_used"])

        if rep.get("status") != "ok":
            motif = rep.get("reason", "")
            if rep.get("diversite_epuisee"):
                # Ce n'est pas une panne : il n'y a plus d'autre intelligence a
                # interroger. Insister ferait re-signer la meme voix.
                tentatives.append(Tentative(
                    strategie=angle, erreur="diversite epuisee apres %d modele(s)"
                    % len(entendus), transport_ok=False))
                break
            classe = classer_erreur(motif)
            tentatives.append(Tentative(
                provider=rep.get("provider_used", ""), modele=rep.get("provider_used", ""),
                strategie=angle, erreur=motif, transport_ok=False))
            # Un refus de sûrete arrete le fanout : insister reviendrait a
            # chercher le provider qui accepte ce qu'un garde a refuse.
            if classe == SECURITY_REJECTION:
                break
            if not strategie_reprise(classe)["autre_provider"]:
                break
            continue

        texte = rep.get("result", "")
        test_ok, preuves = (None, [])
        if verificateur is not None:
            try:
                test_ok, preuves = verificateur(texte)
            except Exception as exc:               # la porte elle-meme a echoue
                test_ok, preuves = None, []
                tentatives.append(Tentative(strategie=angle, modele="verificateur",
                                            erreur="verificateur HS: %s" % exc,
                                            transport_ok=False))
        tentatives.append(Tentative(
            provider=rep.get("provider_used", ""),
            # Le MODELE, pas le provider : `groupe_independance` compte les voix par
            # famille de modele. Confondre les deux ferait passer deux modeles
            # differents d'un meme provider pour une seule voix -- et deux appels au
            # meme modele via deux providers pour deux voix.
            modele=rep.get("model") or rep.get("provider_used", ""),
            strategie=angle, sortie=texte, solution_id=_empreinte(texte),
            test_ok=test_ok, preuves=list(preuves), format_ok=bool(texte.strip()),
            latence_ms=float(rep.get("elapsed_ms") or 0.0),
            tokens=int(rep.get("tokens") or 0)))

    v = arbitrer(tentatives, min_voix=cfg["min_voix"], exiger_preuve=cfg["exiger_preuve"])
    gagnante = next((t.sortie for t in tentatives if t.solution_id == v.solution), None)
    return {
        "status": "ok" if v.action == "accept" else "pending",
        "etat": v.etat, "action": v.action, "motif": v.motif,
        "result": gagnante,
        "voix_independantes": v.voix_independantes,
        "preuves_deterministes": v.preuves_deterministes,
        "mode": mode, "politique": politique,
        "modeles_entendus": entendus,
        "cout": cout_de(tentatives),
        "gain": gain_collectif(tentatives, v.solution),
        "tentatives": [
            {"angle": t.strategie, "provider": t.provider, "modele": t.modele,
             "erreur": t.erreur, "classe": t.classe_erreur, "test_ok": t.test_ok,
             "tokens": t.tokens, "latence_ms": t.latence_ms}
            for t in tentatives],
    }
