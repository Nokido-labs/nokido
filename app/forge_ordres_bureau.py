"""forge_ordres_bureau — ordres que le hub confie a la session de l'OWNER, apres son accord.

POURQUOI (demande owner 2026-09-26 : « le panneau appele par elicitation pour les taches de
redemarrage fullstack »). Redemarrer la stack complete, c'est `nokido_stop.ps1` puis
`nokido_start.ps1` : ils s'AUTO-ELEVENT (UAC) et relancent des composants dans la session
interactive. Le hub tourne sous un compte de service, sans bureau : il ne peut pas le faire
lui-meme, et `nokido_launcher._cli` le REFUSE depuis un tel compte (rc 3). Le tray, lui,
vit dans la session de l'owner.

LE CHEMIN
  1. un agent appelle `hub action=redemarrer_stack message=<raison>` ;
  2. le hub pose la question a l'owner par elicitation MCP (`forge_mcp_elicitation`) :
     le dialogue s'affiche chez l'owner, le modele ne le remplit pas ;
  3. SEULEMENT si l'etat est ACCEPTE, un ordre a usage UNIQUE est depose EN MEMOIRE du hub,
     avec une echeance courte ;
  4. le tray, authentifie par SON jeton (`TRAY`, ring 2), le prend (`hub action=ordre_bureau`)
     et lance `nokido_launcher.py --action restart` dans une console visible. L'UAC reste
     a valider : la confirmation par elicitation ne la remplace pas.

POURQUOI EN MEMOIRE ET PAS UN FICHIER (anti-doublon, 2026-09-26). `sandbox/hub_restart.trigger`
existe : un watcher SYSTEM relance le HUB SEUL, et tout processus qui ecrit dans `sandbox/`
le declenche. Ici l'ordre ne doit avoir qu'un auteur possible, la reponse ACCEPTE de
l'owner : un fichier se forge, un etat du processus hub ne s'atteint que par son code.

ETATS rendus a l'agent : ceux de `confirmer_owner` passent tels quels (REFUSE, ANNULE,
EXPIRE, INDISPONIBLE) et ne deposent RIEN ; ACCEPTE devient DEPOSE. REQUESTED != ACHIEVED :
l'ordre est depose, pas execute -- et le redemarrage coupe le hub qui l'a depose.
Cote tray : ORDRE (un ordre pris) · RIEN (aucun en attente) · REFUSE (consommateur non admis).

UNE SEULE INSTANCE : l'etat vit au niveau du module. Le registre importe
`nokido_agent.app.forge_ordres_bureau`, les tests `forge_ordres_bureau` : le module
s'enregistre sous les deux noms (meme motif que `forge_mcp_elicitation`).
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path

__FORGE_COLOR__ = "moteur/ordres confirmes par l'owner, executes dans sa session par le tray"

for _nom in ("forge_ordres_bureau", "nokido_agent.app.forge_ordres_bureau"):
    sys.modules.setdefault(_nom, sys.modules[__name__])

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "logs" / "ordres_bureau.jsonl"

#: Actions que l'owner peut confirmer, avec ce que le dialogue lui en dit. Chaque cle est
#: une action de `tools/nokido_launcher.py` (ACTIONS) : le tray n'invente rien.
ACTIONS = {
    "restart": ("Redemarrer la stack Nokido complete",
                "Stop puis start (~4 min, deux fenetres UAC a valider). Tous les services "
                "s'arretent et les clients MCP sont deconnectes le temps du redemarrage."),
    # Tailscale (owner 2026-09-29 : « tailscale par le tray »). Mesure : l'API locale de
    # Tailscale Windows ne repond qu'a l'utilisateur de la session (un compte de service recoit
    # 401 « already in use by DESKTOP-...\user ») -- seul le tray, dans cette session, le pilote.
    "tailscale-statut": ("Lire l'etat du Funnel Tailscale",
                         "Lecture seule : ecrit logs/tailscale_etat.json. Rien n'est ouvert ni ferme."),
    "funnel-ouvrir": ("OUVRIR le Funnel Tailscale vers le connecteur des pairs (:8793)",
                      "Expose le connecteur des pairs sur Internet (https://<machine>.ts.net) : "
                      "claude.ai et ChatGPT pourront s'y connecter (OAuth + quarantaine restent en place)."),
    "funnel-fermer": ("FERMER le Funnel Tailscale",
                      "Coupe l'acces de claude.ai et ChatGPT au connecteur des pairs."),
}
#: Ordres deposes SANS question : lecture seule, rien n'est expose ni coupe.
SANS_CONFIRMATION = frozenset({"tailscale-statut"})
#: Ordres executes DANS le hub apres ACCEPTE, jamais deposes (owner 2026-09-29 : « je ne vais pas
#: taper des commandes admin a chaque fois pour les communications »). Le dialogue d'elicitation,
#: dans le client de l'owner, remplace la console administrateur ; un agent ne peut pas y repondre.
ORDRES_HUB = {
    "pair-approuver": ("Approuver une tache ou un fait depose par un pair (claude.ai, ChatGPT)",
                       "Livre au destinataire local. Genre 'deliberer' : debat local, capsule renvoyee au pair."),
    "pair-repondre": ("Envoyer une reponse a un pair",
                      "Le texte ci-dessous SORT vers le cloud (claude.ai / ChatGPT)."),
}
PREUVE_S = 30.0                    # l'execution suit l'ACCEPTE dans le meme appel : 30 s suffisent
#: Qui peut PRENDRE un ordre : le tray (jeton propre, sujet prouve) et le panneau (MASTER).
CONSOMMATEURS = frozenset({"TRAY", "MASTER"})
ECHEANCE_S = 120.0                 # le tray interroge toutes les 10 s ; au-dela, il est absent

DEPOSE, ORDRE, RIEN, REFUSE = "DEPOSE", "ORDRE", "RIEN", "REFUSE"

_ORDRES: list = []
_PREUVES: dict = {}                # preuve -> (ordre, cible, echeance) ; en MEMOIRE du hub seulement
_VERROU = threading.Lock()


def _consigner(evenement: str, **champs) -> None:
    """Trace d'audit, une ligne JSON par evenement. Un journal illisible ne change pas la
    decision : il le DIT sur stderr au lieu de se taire."""
    ligne = dict(champs, ts=round(time.time(), 3), evenement=evenement)
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("[ordres_bureau] journal non ecrit (%s) : %s" % (type(exc).__name__, ligne),
              file=sys.stderr)


def _purger(maintenant: float) -> None:
    """Retire les ordres echus (appele sous verrou). Un ordre echu est TRACE : il n'a pas
    ete execute, et personne ne doit le croire en cours."""
    for o in [o for o in _ORDRES if o["echeance"] <= maintenant]:
        _ORDRES.remove(o)
        _consigner("echu", id=o["id"], action=o["action"], demandeur=o["demandeur"])


def deposer(action: str, demandeur: str, raison: str = "", maintenant: float | None = None) -> dict:
    """Depose un ordre a usage unique. N'est appele qu'apres un ACCEPTE de l'owner."""
    if action not in ACTIONS:
        raise ValueError("action non confirmable : %r (connues : %s)" % (action, ", ".join(ACTIONS)))
    t = time.time() if maintenant is None else maintenant
    ordre = {"id": "ordre-" + uuid.uuid4().hex[:12], "action": action,
             "demandeur": str(demandeur or "?"), "raison": str(raison or "")[:500],
             "depose_a": t, "echeance": t + ECHEANCE_S}
    with _VERROU:
        _purger(t)
        _ORDRES.append(ordre)
    _consigner("depose", id=ordre["id"], action=action, demandeur=ordre["demandeur"],
               raison=ordre["raison"])
    return dict(ordre)


def en_attente(maintenant: float | None = None) -> list:
    """Lecture seule : les ordres non echus, sans les prendre."""
    t = time.time() if maintenant is None else maintenant
    with _VERROU:
        _purger(t)
        return [dict(o) for o in _ORDRES]


def prendre(consommateur: str, maintenant: float | None = None) -> dict:
    """Le tray prend le plus ancien ordre non echu. Usage UNIQUE : pris = retire."""
    qui = str(consommateur or "").upper().strip()
    if qui not in CONSOMMATEURS:
        _consigner("refus", consommateur=qui or "?")
        return {"etat": REFUSE,
                "raison": "%s ne peut pas prendre d'ordre (admis : %s)"
                          % (qui or "identite vide", ", ".join(sorted(CONSOMMATEURS)))}
    t = time.time() if maintenant is None else maintenant
    with _VERROU:
        _purger(t)
        if not _ORDRES:
            return {"etat": RIEN}
        ordre = _ORDRES.pop(0)
    _consigner("pris", id=ordre["id"], action=ordre["action"], consommateur=qui)
    return {"etat": ORDRE, "ordre": ordre}


async def redemarrer_stack(demandeur: str, raison: str = "", confirmer=None) -> dict:
    """Demande a l'owner, par elicitation, de redemarrer la stack ; depose l'ordre s'il accepte.

    `confirmer` : coroutine (action, detail) -> {"etat": ...} ; par defaut
    `forge_mcp_elicitation.confirmer_owner`. Injectable pour les tests."""
    if confirmer is None:
        from nokido_agent.app.forge_mcp_elicitation import confirmer_owner as confirmer
    titre, effet = ACTIONS["restart"]
    detail = "%s\nDemande par %s%s\nLe tray execute l'ordre ; sans tray actif, il expire en %d s." % (
        effet, demandeur or "?", (" : %s" % raison) if raison else "", int(ECHEANCE_S))
    r = await confirmer(titre, detail)
    etat = (r or {}).get("etat")
    if etat != "ACCEPTE":
        _consigner("non_depose", action="restart", demandeur=demandeur, etat=etat)
        return dict(r or {}, depose=False)
    ordre = deposer("restart", demandeur, raison)
    return {"etat": DEPOSE, "depose": True, "ordre": ordre["id"], "echeance_s": ECHEANCE_S,
            "note": "REQUESTED != ACHIEVED : le tray doit prendre l'ordre, puis l'UAC etre validee"}


# ---------------------------------------------------------------------------
# demander_ordre (2026-09-29) : une porte GENERIQUE, pour ne plus toucher le registre critique
# ---------------------------------------------------------------------------

def emettre_preuve(ordre: str, cible: str, maintenant: float | None = None) -> str:
    """Preuve d'accord owner a usage UNIQUE, emise APRES un ACCEPTE. Elle ne vit qu'en memoire
    de ce processus : un autre processus qui importe ce module n'y voit qu'un registre vide."""
    t = time.time() if maintenant is None else maintenant
    preuve = "accord-" + uuid.uuid4().hex
    with _VERROU:
        for p in [p for p, v in _PREUVES.items() if v[2] <= t]:
            del _PREUVES[p]
        _PREUVES[preuve] = (ordre, str(cible), t + PREUVE_S)
    return preuve


def consommer_preuve(preuve: str, ordre: str, cible: str, maintenant: float | None = None) -> bool:
    """Vrai UNE fois, pour l'ordre ET la cible exacts, avant echeance. Retiree dans tous les cas."""
    t = time.time() if maintenant is None else maintenant
    with _VERROU:
        v = _PREUVES.pop(str(preuve or ""), None)
    ok = bool(v) and v[0] == ordre and v[1] == str(cible) and v[2] > t
    _consigner("preuve_consommee" if ok else "preuve_refusee", ordre=ordre, cible=str(cible)[:80])
    return ok


def _quarantaine():
    """tools/forge_pair_quarantaine.py (hors app/ : charge par chemin, meme motif que ses NR)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_pair_quarantaine_hub",
                                                  ROOT / "tools" / "forge_pair_quarantaine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resume_depot(ident: str) -> str:
    """Ce que l'owner lit AVANT d'accepter : provenance, genre, intent, debut du texte EXTERNE."""
    try:
        depot = next((d for d in _quarantaine().lister() if d.get("id") == ident), None)
    except Exception as exc:  # noqa: BLE001 -- le resume manque : le DIRE, ne pas accepter a l'aveugle
        return "Resume ILLISIBLE (%s) : refuser sauf certitude." % type(exc).__name__
    if not depot:
        return "AUCUN depot en quarantaine sous %s." % ident
    return "De %s -- %s, genre %s, intent %s, pour %s.\nTexte (donnee externe) : %s" % (
        depot.get("de"), depot.get("methode"), depot.get("genre") or "-", depot.get("intent"),
        depot.get("destinataire") or "-", str(depot.get("texte_externe") or "")[:400])


def _executer_hub(ordre: str, demandeur: str, cible: str, texte: str, pointeur: str) -> dict:
    q = _quarantaine()
    preuve = emettre_preuve(ordre, cible)
    if ordre == "pair-approuver":
        res = q.approuver(cible, preuve=preuve)
    else:
        res = q.repondre(cible, pointeur, "OK_DONE", texte, preuve=preuve)
    _consigner("execute_hub", ordre=ordre, cible=str(cible)[:80], demandeur=demandeur,
               ok=bool((res or {}).get("ok")))
    return {"etat": "EXECUTE" if (res or {}).get("ok") else "ECHEC", "ordre": ordre, "resultat": res}


async def demander_ordre(demandeur: str, ordre: str, raison: str = "", cible: str = "", texte: str = "",
                         pointeur: str = "", confirmer=None) -> dict:
    """Porte generique `hub action=demander_ordre ordre=<nom>`.

    - ordre du tray (ACTIONS) : question a l'owner par elicitation, ordre depose sur ACCEPTE ;
      SANS_CONFIRMATION (lecture seule) : depose sans question ;
    - ordre du hub (ORDRES_HUB) : question, puis execution ICI avec une preuve a usage unique ;
    - inconnu : REFUSE, et dit.
    """
    ordre = str(ordre or "").strip()
    if ordre == "restart":
        return await redemarrer_stack(demandeur, raison, confirmer)
    if ordre not in ACTIONS and ordre not in ORDRES_HUB:
        return {"etat": REFUSE, "raison": "ordre inconnu %r (connus : %s)"
                % (ordre, ", ".join(sorted(set(ACTIONS) | set(ORDRES_HUB))))}
    if ordre in ORDRES_HUB and not cible:
        return {"etat": REFUSE, "raison": "%s exige `cible` (id du depot, ou client du pair)" % ordre}
    if ordre == "pair-repondre" and not pointeur:
        return {"etat": REFUSE, "raison": "pair-repondre exige `pointeur` (M2M pointer_ref)"}
    if ordre in SANS_CONFIRMATION:
        o = deposer(ordre, demandeur, raison)
        return {"etat": DEPOSE, "depose": True, "ordre": o["id"], "echeance_s": ECHEANCE_S,
                "confirmation": "aucune (lecture seule)"}
    if confirmer is None:
        from nokido_agent.app.forge_mcp_elicitation import confirmer_owner as confirmer
    titre, effet = ACTIONS.get(ordre) or ORDRES_HUB[ordre]
    if ordre == "pair-approuver":
        corps = _resume_depot(cible)
    elif ordre == "pair-repondre":
        corps = "Vers PAIR:%s -- intent OK_DONE, pointeur %s\nTexte : %s" % (cible, pointeur, texte[:1000])
    else:
        corps = "Execute par le tray, dans ta session ; sans tray actif, l'ordre expire en %d s." % int(ECHEANCE_S)
    detail = "%s\n%s\nDemande par %s%s" % (effet, corps, demandeur or "?", (" : %s" % raison) if raison else "")
    r = await confirmer(titre, detail)
    etat = (r or {}).get("etat")
    if etat != "ACCEPTE":
        _consigner("non_depose", action=ordre, demandeur=demandeur, etat=etat)
        return dict(r or {}, depose=False)
    if ordre in ORDRES_HUB:
        return _executer_hub(ordre, demandeur, cible, texte, pointeur)
    o = deposer(ordre, demandeur, raison)
    return {"etat": DEPOSE, "depose": True, "ordre": o["id"], "echeance_s": ECHEANCE_S,
            "note": "REQUESTED != ACHIEVED : le tray doit prendre l'ordre"}
