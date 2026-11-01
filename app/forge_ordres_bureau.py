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
    # 31/10 (owner : « pourquoi un reboot full stack alors que tu parles du hub ? ») : le tray sait deja `restart-hub`
    # (menu « Restart HUB seul ») ; un correctif du seul hub ne redemarre plus toute la stack.
    "restart-hub": ("Redemarrer le HUB seul (:8766)",
                    "Le superviseur relance le seul hub ; les autres services et les executeurs restent en place."),
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
    # 31/10 (choix owner) : « audio-relancer » RETIRE des ordres deposables -- la fuite d'audiodg venait de l'APO Razer
    # 7.1 (desinstalle ; pente +1,1 handles/min) et le tray ne le porte plus (4ffc52ed2) : un ordre deposable que le
    # tray ignorerait expirerait sans effet. Recours manuel : action du panneau (nokido_launcher, UAC).
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

#: Commandes a TAPER par l'owner (owner 2026-10-16, option a) : deposees par un agent AUTHENTIFIE via demander_ordre,
#: copiees par le tray, jamais executees. A la difference des ordres (en memoire : eux s'executent), elles PERSISTENT
#: jusqu'a traitement, dans logs/ que les comptes sandbox ne peuvent pas ecrire (mesure : PermissionError sur
#: logs/mcp_service.log) -- un fichier de sandbox/ se forgerait.
COMMANDES = ROOT / "logs" / "commandes_owner.jsonl"

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


# SOLDE AU BOOT (31/10, choix owner « le hub notifie »). Mesure : ordre-a30d00a73512 (restart-hub, demande par CLAUDE)
# valide ~12:27, hub reparti 12:28:14 -- aucun compte rendu, le demandeur a du verifier seul (REQUESTED != ACHIEVED).
FENETRE_SOLDE_S = 3600.0
_REDEMARRAGES = ("restart", "restart-hub")


def _boite_du_demandeur(nom: str) -> str:
    """Boite que le demandeur RELEVE (agt_<boite> du registre, forge_videur.mailbox_de). Mesure 31/10 : le compte rendu
    d'ordre-39ab7300011c partait vers « CLAUDE » quand la boite relevee est « agt_claude » -- livre, jamais lu."""
    n = str(nom or "").strip()
    if n.lower().startswith("agt_"):
        return n.lower()
    try:
        try:
            from nokido_agent.app.forge_videur import mailbox_de
        except ImportError:  # repli checkout
            from forge_videur import mailbox_de
        boite = mailbox_de(n)
    except Exception:  # noqa: BLE001 - muet-ok : registre illisible, convention agt_<nom> ci-dessous
        boite = ""
    return boite or ("agt_" + n.lower())


def _notifier_demandeur(destinataire: str, message: str) -> bool:
    """Depose le compte rendu dans la boite que le demandeur releve (agent_messages : meme primitive que hub
    action=send ; boite resolue par le registre, _boite_du_demandeur)."""
    destinataire = _boite_du_demandeur(destinataire)
    try:
        import hashlib
        try:
            from nokido_agent.app.forge_db_path import open_m2m
        except ImportError:  # repli checkout
            from forge_db_path import open_m2m
        mid = hashlib.sha256(("HUB%s%s" % (destinataire, time.time())).encode()).hexdigest()[:16]
        conn = open_m2m(timeout=3)
        try:
            conn.execute("INSERT INTO agent_messages(id,from_agent,to_agent,correlation_id,method,payload,status) "
                         "VALUES(?,?,?,?,?,?,?)", (mid, "HUB", destinataire, mid, "ordre.atteint", message, "pending"))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001 - l'echec est DIT par l'appelant (notifie=False au journal)
        print("[ordres_bureau] compte rendu non depose pour %s (%s)" % (destinataire, type(exc).__name__),
              file=sys.stderr)
        return False


def solder_redemarrages(boot_ts: float, notifier=None, journal: Path | None = None) -> list:
    """Au boot du hub : les ordres restart / restart-hub PRIS par le tray dans l'heure avant ce boot, ni soldes ni
    refuses, sont ATTEINTS -- « atteint » consigne avec la preuve (heure de boot, pid), demandeur prevenu (M2M
    OK_DONE, pointer_ref ordre:<id>). Idempotent ; un echec de notification est consigne (notifie=False) et dit."""
    import os
    j = journal or JOURNAL
    try:
        lignes = j.read_text(encoding="utf-8").splitlines()[-2000:]
    except FileNotFoundError:
        return []  # aucun journal = aucun ordre jamais consigne : un vrai NON
    except OSError as exc:
        print("[ordres_bureau] journal ILLISIBLE (%s) : solde des redemarrages impossible" % type(exc).__name__,
              file=sys.stderr)
        return []
    par_id: dict = {}
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:  # muet-ok : ligne illisible ignoree ici, recents() la compte et l'affiche au tray
            continue
        if isinstance(e, dict) and e.get("id"):
            par_id.setdefault(e["id"], []).append(e)
    notifier = notifier or _notifier_demandeur
    soldes = []
    for ident, evts in par_id.items():
        noms = [str(e.get("evenement") or "").lower() for e in evts]
        pris = [e for e in evts if e.get("evenement") == "pris" and e.get("action") in _REDEMARRAGES]
        if not pris or "atteint" in noms or any(("refus" in n) or ("annul" in n) or n in ("non", "decline")
                                                for n in noms):
            continue
        t_pris = float(pris[-1].get("ts") or 0.0)
        if not boot_ts - FENETRE_SOLDE_S <= t_pris <= boot_ts:
            continue
        action = pris[-1].get("action")
        demandeur = str(next((e.get("demandeur") for e in evts if e.get("evenement") == "depose"), "") or "")
        preuve = {"boot_hub_ts": boot_ts, "pid": os.getpid()}
        message = json.dumps({"intent": "OK_DONE", "pointer_ref": "ordre:%s" % ident, "action": action,
                              "preuve": preuve}, ensure_ascii=False)
        notifie = bool(notifier(demandeur, message)) if demandeur and demandeur != "?" else False
        _consigner("atteint", id=ident, action=action, demandeur=demandeur, preuve=preuve, notifie=notifie)
        if not notifie:
            print("[ordres_bureau] %s atteint, demandeur %s NON prevenu" % (ident, demandeur or "?"), file=sys.stderr)
        soldes.append({"id": ident, "action": action, "demandeur": demandeur, "notifie": notifie})
    return soldes


def deposer(action: str, demandeur: str, raison: str = "", maintenant: float | None = None,
            a_valider: bool = False) -> dict:
    """Depose un ordre a usage unique. N'est appele qu'apres un ACCEPTE de l'owner, OU marque `a_valider` : le tray
    fait alors monter une fenetre de validation et n'execute que sur le Oui de l'owner (owner 30/10)."""
    if action not in ACTIONS:
        raise ValueError("action non confirmable : %r (connues : %s)" % (action, ", ".join(ACTIONS)))
    t = time.time() if maintenant is None else maintenant
    ordre = {"id": "ordre-" + uuid.uuid4().hex[:12], "action": action,
             "demandeur": str(demandeur or "?"), "raison": str(raison or "")[:500],
             "depose_a": t, "echeance": t + ECHEANCE_S}
    if a_valider:
        ordre["a_valider"] = True
    with _VERROU:
        _purger(t)
        _ORDRES.append(ordre)
    _consigner("depose", id=ordre["id"], action=action, demandeur=ordre["demandeur"],
               raison=ordre["raison"])
    return dict(ordre)


def recents(n: int = 8, journal: Path | None = None) -> list:
    """Lecture SEULE des n derniers evenements du journal (depose, pris, execute_hub, refuse...) : ce que le tray
    affiche (demande owner 15/10 : « les ordres ne s'affichent pas »). La file en attente vit en memoire du hub,
    illisible hors de lui ; le journal, lui, est le temoin partage. Ligne illisible : comptee, jamais inventee."""
    j = journal or JOURNAL
    try:
        lignes = j.read_text(encoding="utf-8").splitlines()[-max(1, n) * 3:]
    except FileNotFoundError:
        return []                      # aucun journal = aucun ordre jamais consigne : un vrai NON
    except OSError as exc:
        # Revue AGY 15/10 : `except OSError: return []` faisait afficher « aucun ordre » au tray pour un journal
        # verrouille ou refuse -- un INCONNU deguise en NON.
        return [{"evenement": "JOURNAL ILLISIBLE (%s)" % type(exc).__name__}]
    out = []
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:
            out.append({"evenement": "ILLISIBLE"})
            continue
        out.append({k: e.get(k) for k in ("ts", "evenement", "id", "action", "ordre", "demandeur", "consommateur",
                                          "cible", "ok") if e.get(k) is not None})
    return out[-n:]


def en_attente(maintenant: float | None = None) -> list:
    """Lecture seule : les ordres non echus, sans les prendre."""
    t = time.time() if maintenant is None else maintenant
    with _VERROU:
        _purger(t)
        return [dict(o) for o in _ORDRES]


def _evenements_commandes() -> list:
    try:
        lignes = COMMANDES.read_text(encoding="utf-8").splitlines()
    except OSError:  # muet-ok : aucun journal = aucune commande en attente
        return []
    evts = []
    for ligne in lignes:
        try:
            evts.append(json.loads(ligne))
        except ValueError:  # muet-ok : ligne tronquee (ecriture interrompue) = evenement absent, les autres valent
            continue
    return evts


def commandes_en_attente() -> list:
    evts = _evenements_commandes()
    traitees = {e.get("id") for e in evts if e.get("evt") in ("faite", "annulee")}
    return [e for e in evts if e.get("evt") == "depose" and e.get("id") not in traitees]


def texte_caviarde(texte: str) -> bool:
    """Le texte porte-t-il un marqueur de caviardage ([BASE64_SUSPECT_1], [PATH_WIN_1]...) ? Vecu 16/10 : relevee par
    le hub, dont la sortie est caviardee pour les clients cloud, une commande arrivait alteree au presse-papier de
    l'owner. Un texte ainsi altere ne se copie JAMAIS."""
    return bool(RE_JETON_CAVIARDAGE.search(str(texte or "")))


# Jeton de caviardage du pare-feu semantique. Partage avec le pre-commit (tools/forge_git_gate.py::_RE_JETON,
# copie verrouillee par tests/nr/test_gate_jetons_caviardage_nr.py) : un seul vocabulaire.
RE_JETON_CAVIARDAGE = __import__("re").compile(r"\[[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_\d+\]")


def _prete_pour_powershell(texte: str) -> str:
    """Le terminal de l'owner est PowerShell : un chemin CITE en tete suivi d'arguments y est une ParserError sans
    l'operateur d'appel `&` (vecu 16/10)."""
    t = str(texte or "").strip()
    return "& " + t if t.startswith('"') else t


def deposer_commande(demandeur: str, texte: str, raison: str = "") -> dict:
    c = {"evt": "depose", "id": "cmd-" + uuid.uuid4().hex[:12], "texte": _prete_pour_powershell(texte),
         "raison": str(raison or "")[:500], "demandeur": str(demandeur or "?"), "depose_a": time.time()}
    with _VERROU:
        COMMANDES.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMANDES, "a", encoding="utf-8") as f:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return c


def marquer_commande(consommateur: str, cid: str, extrait_retour: str = "") -> dict:
    """Le tray (ou le panneau) marque une commande TRAITEE ; un agent ne la fait pas disparaitre a la place de l'owner,
    SAUF sur le retour que l'owner lui a colle (consigne owner 19/10, ancree) : l'extrait est la preuve, et la trace dit
    « faite par l'owner, rapportee par <agent> »."""
    qui = str(consommateur or "").upper().strip()
    extrait = str(extrait_retour or "").strip()
    if qui not in CONSOMMATEURS and not extrait:
        return {"etat": REFUSE, "raison": "%s ne peut pas marquer une commande sans le retour colle par l'owner "
                "(admis sans preuve : %s)" % (qui or "identite vide", ", ".join(sorted(CONSOMMATEURS)))}
    if cid not in {c.get("id") for c in commandes_en_attente()}:
        return {"etat": REFUSE, "raison": "commande %r inconnue ou deja traitee" % cid}
    evt = {"evt": "faite", "id": cid, "par": qui, "ts": time.time()}
    if qui not in CONSOMMATEURS:
        # L'extrait vient du terminal de l'owner : meme scanner de secrets que le depot, FAIL-CLOSED (rien conserve
        # si secret detecte ou scanner indisponible -- seule la longueur reste).
        try:
            from nokido_agent.tools.forge_governed_edit import _scan_secrets
            garde = "" if _scan_secrets(extrait) else extrait[:300]
        except Exception:  # noqa: BLE001 - muet-ok : scanner indisponible = extrait non conserve, longueur dite
            garde = ""
        evt.update(par="OWNER", rapporte_par=qui, extrait_retour=garde or "[non conserve, %d car.]" % len(extrait))
    with _VERROU:
        with open(COMMANDES, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    return {"etat": "FAITE", "commande": cid}


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


async def redemarrer_stack(demandeur: str, raison: str = "", confirmer=None, demandeur_prouve: bool = False,
                           action: str = "restart") -> dict:
    """Demande a l'owner, par elicitation, de redemarrer la stack (ou le hub seul : action=restart-hub) ; depose
    l'ordre s'il accepte.

    `confirmer` : coroutine (action, detail) -> {"etat": ...} ; par defaut
    `forge_mcp_elicitation.confirmer_owner`. Injectable pour les tests."""
    if action not in ("restart", "restart-hub"):
        return {"etat": REFUSE, "raison": "action de redemarrage inconnue %r" % action}
    titre, effet = ACTIONS[action]
    detail = "%s\nDemande par %s%s\nLe tray execute l'ordre ; sans tray actif, il expire en %d s." % (
        effet, demandeur or "?", (" : %s" % raison) if raison else "", int(ECHEANCE_S))
    if demandeur_prouve and _surface_de(demandeur) == "interactive":
        # Owner 30/10 : « tu fais juste monter une fenetre de validation pour valider l'ordre ». Avant : A_DEMANDER
        # (question + commande a coller ; l'elicitation MCP, elle, expirait sans s'afficher le 19/10). L'ordre est
        # DEPOSE marque a_valider : le tray ouvre une fenetre Oui/Non au premier plan, rien ne s'execute sans le Oui.
        ordre = deposer(action, demandeur, raison, a_valider=True)
        return {"etat": DEPOSE, "depose": True, "a_valider": True, "ordre": ordre["id"], "echeance_s": ECHEANCE_S,
                "note": "fenetre de validation au tray : l'ordre ne s'execute que sur le Oui de l'owner ; "
                        "REQUESTED != ACHIEVED (puis UAC)"}
    if confirmer is None:
        from nokido_agent.app.forge_mcp_elicitation import confirmer_owner as confirmer
    r = await confirmer(titre, detail)
    etat = (r or {}).get("etat")
    if etat != "ACCEPTE":
        _consigner("non_depose", action=action, demandeur=demandeur, etat=etat)
        return dict(r or {}, depose=False)
    ordre = deposer(action, demandeur, raison)
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


def _surface_de(agent: str):
    """`surface` declaree (interactive / autonomous / internal) au registre des identites ; None si illisible --
    jamais « interactive » par defaut : un registre muet garde le dialogue."""
    try:
        from nokido_agent.app import forge_videur as _v
        _v._load_store()
        return ((_v._cache.get("meta") or {}).get(str(agent or "").upper()) or {}).get("surface")
    except Exception:  # noqa: BLE001 - illisible = None, et le dialogue reste la regle
        return None


# Ordres de COMMANDE du tray (cycle : deposer -> l'owner lance la commande -> commande-faite avec l'extrait de son retour).
ORDRES_COMMANDES = ("commande-deposer", "commandes-en-attente", "commande-faite")


async def demander_ordre(demandeur: str, ordre: str, raison: str = "", cible: str = "", texte: str = "",
                         pointeur: str = "", confirmer=None, demandeur_prouve: bool = False) -> dict:
    """Porte generique `hub action=demander_ordre ordre=<nom>`.

    - ordre du tray (ACTIONS) : question a l'owner par elicitation, ordre depose sur ACCEPTE ;
      SANS_CONFIRMATION (lecture seule) : depose sans question ;
    - ordre du hub (ORDRES_HUB) : question, puis execution ICI avec une preuve a usage unique ;
    - inconnu : REFUSE, et dit.
    """
    ordre = str(ordre or "").strip()
    if ordre in ("restart", "restart-hub"):
        return await redemarrer_stack(demandeur, raison, confirmer, demandeur_prouve=demandeur_prouve, action=ordre)
    if ordre == "commande-deposer":
        # Une commande transite par le tray et le presse-papier : un secret y serait expose. Meme scanner que
        # governed_edit ; FAIL-CLOSED (scanner indisponible = refus dit).
        try:
            from nokido_agent.tools.forge_governed_edit import _scan_secrets
            fuites = _scan_secrets(str(texte))
        except Exception as e:  # noqa: BLE001
            return {"etat": REFUSE, "raison": "scan de secrets indisponible (%s) : depot refuse" % type(e).__name__}
        if fuites:
            _consigner("commande_refusee", demandeur=demandeur, motifs=len(fuites))
            return {"etat": REFUSE, "raison": "la commande porte un secret (%d motif(s)) : jamais par le presse-papier"
                    % len(fuites)}
        return {"etat": DEPOSE, "commande": deposer_commande(demandeur, texte, raison)["id"]}
    if ordre == "commandes-en-attente":
        return {"etat": "LISTE", "commandes": commandes_en_attente()}
    if ordre == "commande-faite":
        return marquer_commande(demandeur, cible, extrait_retour=texte)  # texte = extrait du retour colle par l'owner
    if ordre not in ACTIONS and ordre not in ORDRES_HUB:
        # Les ordres de COMMANDE (traites plus haut) sont listes aussi (21/10) : sans eux, la route du tray
        # n'etait connue que de la memoire d'un agent, jamais d'une installation neuve.
        return {"etat": REFUSE, "raison": "ordre inconnu %r (connus : %s)"
                % (ordre, ", ".join(sorted(set(ACTIONS) | set(ORDRES_HUB) | set(ORDRES_COMMANDES))))}
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
    if demandeur_prouve and _surface_de(demandeur) == "interactive" and ordre == "restart":
        # Owner 30/10 : pour le restart, une fenetre de validation au tray (meme chemin que redemarrer_stack).
        o = deposer("restart", demandeur, raison, a_valider=True)
        return {"etat": DEPOSE, "depose": True, "a_valider": True, "ordre": o["id"], "echeance_s": ECHEANCE_S,
                "note": "fenetre de validation au tray : l'ordre ne s'execute que sur le Oui de l'owner"}
    if demandeur_prouve and _surface_de(demandeur) == "interactive":
        # Owner 17/10 : la demande admin monte dans le CLI PILOTE (identite prouvee par son jeton, carte AGY
        # job_04ab2eb5) -- la question se pose dans SA session ; l'accord de l'owner reste le geste qu'il lance.
        return {"etat": "A_DEMANDER", "a_demander_dans_la_session": True, "depose": False,
                "question": "%s\n%s" % (titre, detail), "commande": _commande_de_repli(ordre, cible, texte, pointeur)}
    r = await confirmer(titre, detail)
    etat = (r or {}).get("etat")
    if etat != "ACCEPTE":
        _consigner("non_depose", action=ordre, demandeur=demandeur, etat=etat)
        rep = dict(r or {}, depose=False)
        if etat in ("EXPIRE", "INDISPONIBLE"):
            # Repli PERSISTANT (19/10 : pair-approuver, dialogue expire a 120 s, rien depose) : la COMMANDE que
            # l'owner lancera lui-meme -- son geste reste l'accord ; jamais un ordre executable sans ACCEPTE.
            cmd = _commande_de_repli(ordre, cible, texte, pointeur)
            try:
                from nokido_agent.tools.forge_governed_edit import _scan_secrets
                fuites = _scan_secrets(cmd) if cmd else []
            except Exception as e:  # noqa: BLE001 - scanner indisponible : rien n'est depose, et c'est dit
                fuites = ["scanner indisponible (%s)" % type(e).__name__]
            if cmd and not fuites:
                rep["repli_commande"] = deposer_commande(demandeur, cmd, "dialogue %s : %s" % (etat, titre))["id"]
            elif cmd:
                rep["repli_refuse"] = "%d motif(s) de secret ou scanner indisponible" % len(fuites)
        return rep
    if ordre in ORDRES_HUB:
        return _executer_hub(ordre, demandeur, cible, texte, pointeur)
    o = deposer(ordre, demandeur, raison)
    return {"etat": DEPOSE, "depose": True, "ordre": o["id"], "echeance_s": ECHEANCE_S,
            "note": "REQUESTED != ACHIEVED : le tray doit prendre l'ordre"}


def _commande_de_repli(ordre: str, cible: str = "", texte: str = "", pointeur: str = "") -> str | None:
    """La commande console qui fait, par la main de l'owner, ce que le dialogue n'a pas pu faire accepter."""
    racine = Path(__file__).resolve().parent.parent
    try:
        from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON as py
    except Exception:  # noqa: BLE001  # muet-ok : repli sur l'interpreteur courant, nomme dans la commande
        py = sys.executable
    outils = racine / "tools"
    if ordre == "pair-approuver" and cible:
        return '"%s" "%s" --approuver %s' % (py, outils / "forge_pair_quarantaine.py", cible)
    if ordre == "pair-repondre" and cible and pointeur:
        return '"%s" "%s" --repondre %s --pointer %s --texte "%s"' % (
            py, outils / "forge_pair_quarantaine.py", cible, pointeur, str(texte).replace('"', "'")[:1000])
    if ordre in ACTIONS:
        return '"%s" "%s" --action %s' % (py, outils / "nokido_launcher.py", ordre)
    return None


# Remèdes hors corps (fuites de handles)
# 31/10 (choix owner) : audiodg n'a plus de remede DEPOSABLE (ordre retire, cf. ACTIONS) -- sa fuite reste DETECTEE et
# signalee par fuyards_hors_corps, sans remede invente. Le mecanisme reste pour un futur remede {processus: ordre}.
REMEDES_HORS_CORPS: dict = {}


def remede_hors_corps(fuyard: dict) -> str | None:
    if not isinstance(fuyard, dict):
        return None
    name = fuyard.get("name")
    if not name:
        return None
    for k, v in REMEDES_HORS_CORPS.items():
        if k.lower() == str(name).lower():
            return v
    return None


def proposer_remedes(fuyards: list) -> list:
    props = []
    if not isinstance(fuyards, list):
        return props
    for f in fuyards:
        if not isinstance(f, dict):
            continue
        nom = f.get("name") or ""
        ordre_nom = None
        for k, v in REMEDES_HORS_CORPS.items():
            if k.lower() == str(nom).lower():
                ordre_nom = v
                break
        if not ordre_nom:
            continue
        props.append({
            "intent": "NEED_HUMAN_APPROVAL",
            "pointer_ref": f"ordre:{ordre_nom}",
            "confidence": 0.9,
            "fuyard": nom,
            "pid": f.get("pid"),
            "handles": f.get("handles"),
            "pente_min": f.get("pente_min"),
        })
    return props
