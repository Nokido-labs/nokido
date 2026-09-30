"""Realisations REELLES : ce qui relie une capacite a une route gouvernee.

Le graphe de capacites dit ce qu'un skill EXIGE et PRODUIT. Ce module dit
comment Nokido l'execute effectivement, et surtout comment il OBSERVE l'etat
resultant.

DEUX FONCTIONS PAR CAPACITE, JAMAIS UNE
---------------------------------------
`agir` fait l'appel. `observer` interroge l'etat du monde APRES. Le verdict se
lit sur la seconde, et elle ne relit jamais la sortie de la premiere : un
observateur qui lit ce que l'action a retourne mesure l'intention, pas l'etat.

C'est la meme regle que « le verdict d'un push se lit sur le distant, jamais
sur le code de retour » — un push Nokido sort en rc=1 apres avoir publie, et
`job_status` dit `running` apres un kill externe.

PORTEE : deux capacites reliees, en LECTURE SEULE.
Les 49 heartbeats de `sandbox/` sont un etat reel, courant et observable, et
les lire ne change rien. Aucune capacite a effet irreversible n'est cablee
ici : faire tourner un `netcfg deploy` sur un equipement pour pouvoir ecrire
« E2E PASS » transformerait une demonstration en incident. L'irreversibilite
reste une propriete gouvernee, pas une etape de preuve.
"""

from __future__ import annotations

import os
import pathlib
import time

import forge_skill_capability_graph as cg
import forge_skill_execution as ex

__FORGE_COLOR__ = "cognition/skill-realisations : cablage des capacites vers les routes gouvernees"

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Au-dela, un pouls est considere FIGE. Valeur volontairement large : la
# question ici est « sait-on dans quel etat il est », pas « faut-il agir ».
# Aucun seuil de DECISION n'est pose sans distribution du signal.
SEUIL_FIGE_S = 900

# Etats a partir desquels on considere savoir. Tout le reste — y compris
# l'illisible — laisse le fait NON produit : « je n'ai pas pu voir » ne se
# range jamais du cote de ce qu'on sait.
ETATS_CONNUS = ("VIVANT", "FIGE", "DISABLED_BY_POLICY", "DECLARE_ACTIF")


def _dossier_pouls() -> pathlib.Path:
    """Resolu a CHAQUE appel, jamais fige a l'import.

    Une constante calculee au chargement ne se redirige pas : le module est
    charge sous deux noms unifies par le finder, et `importlib.reload` rend
    l'objet DEJA charge. Paye le 2026-09-10 puis a nouveau le 2026-09-12 —
    meme principe que l'interrupteur `m2m.switch`.
    """
    surcharge = os.environ.get("LAFORGE_POULS_DIR")
    return pathlib.Path(surcharge) if surcharge else (ROOT / "sandbox")


def _chemin_heartbeat(service: str) -> pathlib.Path:
    return _dossier_pouls() / ("%s.heartbeat" % service)


def _sonder(contexte: dict) -> dict:
    """Lit l'age du pouls d'un service. Trois etats, jamais deux.

    ILLISIBLE n'est pas MORT : sous un compte sans droits, une lecture qui
    echoue ressemble a une absence. On le distingue, et l'etat « on ne sait
    pas » ne produira aucun fait — donc aucune etape ne s'appuiera dessus.
    """
    service = contexte.get("service") or "hub"
    p = _chemin_heartbeat(service)
    try:
        age = time.time() - p.stat().st_mtime
    except Exception as exc:  # noqa: BLE001
        contexte["etat_consommateur"] = None
        contexte["etat_motif"] = "ILLISIBLE (%s)" % type(exc).__name__
        return {"lu": False}
    etat = "FIGE" if age > SEUIL_FIGE_S else "VIVANT"
    contexte["etat_consommateur"] = etat
    contexte["age_pouls_s"] = round(age, 1)
    contexte["etat_motif"] = "pouls de %s : %.0f s" % (service, age)
    return {"lu": True}


def _observer_etat(contexte: dict) -> set:
    """Le fait n'est acquis que si un etat a REELLEMENT ete determine."""
    if contexte.get("etat_consommateur") in ETATS_CONNUS:
        return {cg.Fait("etat_consommateur_connu")}
    return set()


def _fichier_services() -> pathlib.Path:
    surcharge = os.environ.get("LAFORGE_SERVICES_TOML")
    if surcharge:
        return pathlib.Path(surcharge)
    return ROOT / "proxy_deno" / "core" / "services.toml"


def _sonder_declaration(contexte: dict) -> dict:
    """SECOND observateur du meme fait, par un chemin independant.

    Mesure du 2026-09-12 : 6 services declarent un pouls dont le fichier est
    ABSENT et portent `disabled = true`. Le heartbeat ne peut rien en dire ;
    la declaration, si — et elle rend DISABLED_BY_POLICY, pas « mort ».
    Sans ce chemin, un pouls manquant se lirait comme une panne et on
    enverrait quelqu'un reparer un CHOIX.

    L'appariement service <-> pouls se fait par la DECLARATION (`heartbeat`
    du TOML), jamais par une convention de nommage devinee : les services
    s'appellent `NokidoSelfPatcher` et leurs pouls `self_patcher.heartbeat`.
    Deviner l'un depuis l'autre m'a fait compter 89 services « sans pouls »
    alors que 51 en declarent un.
    """
    import tomllib  # noqa: PLC0415

    service = contexte.get("service") or ""
    try:
        doc = tomllib.loads(_fichier_services().read_text(
            encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        contexte["etat_consommateur"] = None
        contexte["etat_motif"] = "declaration ILLISIBLE (%s)" % type(exc).__name__
        return {"lu": False}

    cible = "%s.heartbeat" % service
    for s in doc.get("service", []):
        hb = str(s.get("heartbeat") or "")
        if not (hb.endswith(cible) or str(s.get("name", "")).lower() == service.lower()):
            continue
        if s.get("disabled") is True:
            contexte["etat_consommateur"] = "DISABLED_BY_POLICY"
            contexte["etat_motif"] = ("%s est declare `disabled = true` dans "
                                      "services.toml" % s.get("name"))
        else:
            contexte["etat_consommateur"] = "DECLARE_ACTIF"
            contexte["etat_motif"] = ("%s est declare actif dans services.toml "
                                      "mais n'a pas ecrit de pouls" % s.get("name"))
        return {"lu": True}

    contexte["etat_consommateur"] = None
    contexte["etat_motif"] = ("aucune declaration pour '%s' : NON DECLARE et sans "
                              "pouls — indetermine, pas absent" % service)
    return {"lu": False}


def _conclure(contexte: dict) -> dict:
    """Mecanise la checklist du skill forge-workflow-autopsy.

    Le skill documente : consommateur mort -> backlog silencieux ; consommateur
    vivant -> chercher en aval (vocabulaire producteur/consommateur, backlog,
    dependance, angle mort du health-check). On applique CETTE procedure,
    on n'en invente pas une autre.
    """
    etat = contexte.get("etat_consommateur")
    if etat == "FIGE":
        contexte["diagnostic"] = (
            "consommateur FIGE (%s) — piste 1 de la checklist : le producteur "
            "ecrit, le drain est mort, le backlog s'empile en silence"
            % contexte.get("etat_motif", "age inconnu"))
    elif etat == "VIVANT":
        contexte["diagnostic"] = (
            "consommateur VIVANT (%s) — la piste 1 est ecartee ; suivre la "
            "piste 2 : vocabulaire producteur/consommateur, puis backlog par "
            "statut" % contexte.get("etat_motif", "age inconnu"))
    elif etat == "DISABLED_BY_POLICY":
        # DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE. Confondre les deux, c'est
        # envoyer quelqu'un reparer un CHOIX — invariant de la constitution.
        contexte["diagnostic"] = (
            "consommateur COUPE PAR POLITIQUE (%s) — ce n'est PAS une panne : "
            "rien a reparer, le pouls absent est la consequence d'une decision"
            % contexte.get("etat_motif", "motif inconnu"))
    elif etat == "DECLARE_ACTIF":
        contexte["diagnostic"] = (
            "consommateur DECLARE ACTIF mais SANS POULS (%s) — il n'a "
            "vraisemblablement jamais demarre : verifier ses dependances avant "
            "de conclure a une mort" % contexte.get("etat_motif", "motif inconnu"))
    else:
        # Pas de diagnostic sur un etat inconnu : une conclusion tiree d'une
        # source qui se tait est precisement la faute a eviter.
        contexte.pop("diagnostic", None)
    return {"conclu": "diagnostic" in contexte}


def _observer_diagnostic(contexte: dict) -> set:
    if contexte.get("diagnostic"):
        return {cg.Fait("diagnostic_pipeline_rendu")}
    return set()


REALISATIONS: dict[str, ex.Realisation] = {
    "forge-workflow-autopsy::sonder_consommateur": ex.Realisation(
        mode=ex.NOKIDO_NATIF,
        transport="fichier:sandbox/<service>.heartbeat",
        agir=_sonder,
        observer=_observer_etat,
    ),
    "forge-hub::sonder_service_declare": ex.Realisation(
        mode=ex.NOKIDO_NATIF,
        transport="fichier:proxy_deno/core/services.toml",
        agir=_sonder_declaration,
        observer=_observer_etat,
    ),
    "forge-workflow-autopsy::conclure_cause": ex.Realisation(
        mode=ex.NOKIDO_NATIF,
        transport="regle:checklist forge-workflow-autopsy",
        agir=_conclure,
        observer=_observer_diagnostic,
    ),
}
