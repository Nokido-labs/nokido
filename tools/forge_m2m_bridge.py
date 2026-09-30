"""forge_m2m_bridge.py - passerelle M2M : lire le bus inter-agents, y emettre.

__FORGE_COLOR__ = "membrane/passerelle-m2m"

CE QUE CETTE PASSERELLE EST. Une seconde fenetre, a cote de celle de GitHub, qui
laisse un client externe LIRE ce que les agents se disent et EMETTRE des intents
vers eux. Elle partage le transport, l'autorite et le registre de revocation de la
premiere -- elle n'en cree aucun.

    habilitation  ->  forge_github_bridge.lire_capacite(...)   <- LA verification
    message       ->  forge_m2m_protocol.validate(...)         <- LE validateur

Ni l'une ni l'autre n'est recopiee ici. Une seconde implementation de
l'autorisation divergerait de la premiere, et c'est la plus permissive des deux
qui finirait par faire loi ; un second validateur d'intents accepterait un jour ce
que le premier refuse, et le bus cesserait d'etre un langage commun.

CE QU'ELLE NE PARTAGE PAS AVEC LA PASSERELLE GITHUB, ET POURQUOI. Son audience est
DISTINCTE : une habilitation GitHub ne peut pas emettre sur le bus, et une
habilitation M2M ne peut pas lire un depot. Deux fenetres, deux clefs -- sinon la
plus large des deux emporterait l'autre.

LE GARDE QUI COMPTE LE PLUS. L'emetteur d'un message n'est JAMAIS choisi par
l'appelant : il est lu dans le `sub` de l'habilitation presentee. Un bus ou l'on
choisit son identite n'authentifie personne, et un message signe « CLAUDE » par un
tiers vaut pire que pas de message du tout -- il sera cru.

TROIS AUTRES GARDES, chacun pour une panne precise :
  - destinataires en liste BLANCHE : un agent invente laisse un message que
    personne ne draine, et rien ne le signale ;
  - validation en mode ERREUR, pas avertissement : un intent hors dictionnaire est
    REFUSE, pas seulement signale -- sinon le dictionnaire n'est plus une regle ;
  - debit plafonne : un emetteur externe qui inonde le bus est une panne pour tous
    les autres agents, pas seulement pour lui.

CE QU'ELLE NE FAIT PAS. Elle n'assigne pas de taches, ne repond pas aux messages,
ne cree pas d'agent adressable. ChatGPT n'a aucune boucle autonome : lui ouvrir une
boite aux lettres reviendrait a y empiler des messages que personne ne lit -- le
defaut mesure le 31/08 sur le repondeur autonome, pris par l'autre bout.
"""

from __future__ import annotations

__FORGE_COLOR__ = "membrane/passerelle-m2m"

import importlib.util
import json
import logging
import os
import pathlib
import time
import uuid

_LOG = logging.getLogger("Nokido.M2MBridge")

RACINE = pathlib.Path(__file__).resolve().parent.parent

AUDIENCE = "nokido-m2m-bridge"
PORTEE_LECTURE = "m2m:read"
PORTEE_EMISSION = "m2m:write"
RESSOURCES = frozenset({"nokido:m2m"})

OPERATIONS = ("m2m_intents", "m2m_inbox", "m2m_notifier")
OPERATIONS_EMISSION = frozenset({"m2m_notifier"})

# Une lecture bornee : un message du bus porte un intent et un pointeur, pas un
# rapport. Au-dela, c'est que quelqu'un a mis le contenu dans le canal.
MESSAGES_MAX = 50
TAILLE_CHARGE_MAX = 4000

_EMISSIONS = {}   # sujet -> [horodatages], fenetre glissante en memoire


def _charger(chemin: pathlib.Path, nom: str):
    """Charge un module PAR SON CHEMIN -- jamais par nom.

    Le processus que le relais demarre n'a pas forcement `tools/` ni `app/` dans
    son chemin de recherche, et un import par nom pourrait resoudre un homonyme.
    """
    if not chemin.exists():
        raise SystemExit("module introuvable : %s" % chemin)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    if spec is None or spec.loader is None:
        raise SystemExit("module illisible : %s" % chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PONT = _charger(RACINE / "tools" / "forge_github_bridge.py", "forge_github_bridge")
PROTOCOLE = _charger(RACINE / "app" / "forge_m2m_protocol.py", "forge_m2m_protocol")


def agents_autorises() -> frozenset:
    """Les destinataires admis. Liste BLANCHE, jamais noire.

    Un agent absent de cette liste recevrait un message que personne ne draine --
    et un message non drainé ne se distingue pas d'un message non envoye.
    """
    brut = (os.environ.get("NOKIDO_M2M_DESTINATAIRES")
            or "GEMINI,ANTIGRAVITY,CLAUDE").strip()
    return frozenset(x.strip().upper() for x in brut.split(",") if x.strip())


def plafond_par_heure() -> int:
    """Combien de messages un meme sujet peut emettre en une heure.

    La fenetre vit EN MEMOIRE : elle ne survit pas au redemarrage, et il faut le
    dire plutot que de laisser croire a une comptabilite durable. Elle suffit a ce
    qu'elle vise -- empecher une inondation continue -- et ne pretend pas a plus.
    """
    try:
        return max(1, int(os.environ.get("NOKIDO_M2M_PLAFOND_HORAIRE") or 20))
    except ValueError:
        return 20


def _debit_ok(sujet: str) -> bool:
    maintenant = time.time()
    vus = [t for t in _EMISSIONS.get(sujet, []) if t > maintenant - 3600]
    _EMISSIONS[sujet] = vus
    if len(vus) >= plafond_par_heure():
        return False
    vus.append(maintenant)
    return True


_DDP = None


def _chemins():
    """`forge_db_path`, charge UNE fois.

    Deux chargements du meme fichier donnent deux modules distincts, avec deux
    etats : l'un pourrait resoudre un chemin que l'autre ignore, et la divergence
    ne se verrait qu'au moment ou une ecriture part dans la mauvaise base.
    """
    global _DDP
    if _DDP is None:
        _DDP = _charger(RACINE / "app" / "forge_db_path.py", "forge_db_path")
    return _DDP


def chemin_du_bus() -> pathlib.Path:
    """Le bus, par l'interrupteur du corps -- jamais un chemin devine.

    `forge_db_path` porte la bascule : si elle change, cette passerelle suit sans
    qu'on y touche. Un chemin en dur ici divergerait le jour de la migration, et
    la passerelle ecrirait dans une base que plus personne ne lit.
    """
    return pathlib.Path(_chemins().m2m_path())


def _sujet(charge: dict) -> str:
    """L'emetteur REEL : celui de l'habilitation, jamais celui qu'on declare."""
    return str(charge.get("sub") or "").strip().upper() or "INCONNU"


# ------------------------------------------------------------------ operations

def _op_intents(args: dict, charge: dict) -> tuple:
    """Le dictionnaire des intents. Sans lui, un client compose a l'aveugle.

    On rend la description et les champs attendus, pas un schema invente : c'est le
    registre du corps qui fait foi, et il est deja la source unique.
    """
    catalogue = PROTOCOLE._load_catalog() or {}
    intents = catalogue.get("intents") or {}
    rendu = {}
    for nom, fiche in intents.items():
        rendu[nom] = {"category": fiche.get("category"),
                      "description": (fiche.get("description") or "")[:300],
                      "payload_schema": fiche.get("payload_schema") or {}}
    return True, {"version": catalogue.get("version"),
                  "regles": catalogue.get("schema_rules") or {},
                  "destinataires_autorises": sorted(agents_autorises()),
                  "intents": rendu}


def _op_inbox(args: dict, charge: dict) -> tuple:
    """Les derniers messages destines a un agent. LECTURE seule, bornee."""
    import sqlite3

    agent = str(args.get("agent") or "").strip().upper()
    if agent not in agents_autorises():
        return False, "agent hors de la liste autorisee"
    try:
        limite = int(args.get("limite") or 20)
    except (TypeError, ValueError):
        limite = 20
    limite = max(1, min(limite, MESSAGES_MAX))

    bus = chemin_du_bus()
    if not bus.exists():
        return False, "bus M2M introuvable"
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(bus).replace("\\", "/"),
                               uri=True, timeout=10)
        lignes = conn.execute(
            "SELECT id, from_agent, to_agent, method, payload, status, "
            "created_at, read_at FROM agent_messages "
            "WHERE UPPER(to_agent)=? ORDER BY id DESC LIMIT ?",
            (agent, limite)).fetchall()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, "lecture du bus refusee : %s" % type(exc).__name__

    messages = []
    for (ident, de, vers, methode, brut, statut, cree, lu) in lignes:
        texte = (brut or "")[:TAILLE_CHARGE_MAX]
        try:
            contenu = json.loads(texte)
        except Exception:  # noqa: BLE001
            contenu = {"_brut": texte[:400]}
        messages.append({"id": ident, "de": de, "vers": vers,
                         "methode": methode, "statut": statut,
                         "cree_le": cree, "lu_le": lu, "contenu": contenu})
    return True, {"agent": agent, "rendus": len(messages),
                  "plafond": limite, "messages": messages}


def _op_notifier(args: dict, charge: dict) -> tuple:
    """Emet un message sur le bus. L'emetteur vient de l'habilitation."""
    destinataire = str(args.get("destinataire") or "").strip().upper()
    if destinataire not in agents_autorises():
        return False, "destinataire hors de la liste autorisee"

    sujet = _sujet(charge)
    if not _debit_ok(sujet):
        return False, ("plafond d'emission atteint (%d par heure) : le bus est "
                       "partage, une inondation est une panne pour tous"
                       % plafond_par_heure())

    charge_utile = args.get("message")
    if isinstance(charge_utile, str):
        try:
            charge_utile = json.loads(charge_utile)
        except Exception:  # noqa: BLE001
            return False, "message illisible : un objet JSON est attendu"
    if not isinstance(charge_utile, dict):
        return False, "message absent ou de forme inattendue"

    verdict = PROTOCOLE.validate("notify", charge_utile)
    code = (verdict or {}).get("code")
    if code != "M2M_OK":
        # Mode ERREUR, quel que soit le reglage du corps : ce canal est ouvert a
        # un tiers, et un avertissement ne protege personne.
        return False, "message refuse par le protocole (%s) : %s" % (
            code, "; ".join((verdict or {}).get("violations") or [])[:300])

    bus = chemin_du_bus()
    identifiant = "ext_%s" % uuid.uuid4().hex[:12]
    ddp = _chemins()

    # POURQUOI PAS `write_retry`, ALORS QUE LA REGLE LE RECOMMANDE. Elle ouvre
    # elle-meme sa connexion par `open_writer(timeout=...)` et ne transmet AUCUN
    # chemin : elle ecrirait donc dans la base par defaut, pas dans le bus. Sur un
    # depot de message, la panne serait silencieuse -- le message partirait dans la
    # mauvaise base et personne ne le verrait manquer. `open_writer(path=...)`
    # porte deja l'essentiel du motif prouve : autocommit, WAL, busy_timeout.
    # La reprise sur verrou reste a gagner : elle suppose que `write_retry`
    # accepte un chemin, ce qui est un correctif a porter chez elle, pas ici.
    try:
        conn = ddp.open_writer(path=str(bus))
        try:
            conn.execute(
                "INSERT INTO agent_messages (id, from_agent, to_agent, "
                "correlation_id, method, payload, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (identifiant, sujet, destinataire, identifiant, "notify",
                 json.dumps(charge_utile, ensure_ascii=False), "pending",
                 time.strftime("%Y-%m-%d %H:%M:%S")))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return False, "ecriture sur le bus refusee : %s: %s" % (
            type(exc).__name__, str(exc)[:160])

    _LOG.info("[m2m] %s -> %s : %s", sujet, destinataire,
              charge_utile.get("intent"))
    return True, {"id": identifiant, "de": sujet, "vers": destinataire,
                  "intent": charge_utile.get("intent"),
                  "note": "depose sur le bus ; sa LECTURE depend du drain du "
                          "destinataire, elle n'est pas garantie par ce depot"}


_ROUTES = {"m2m_intents": _op_intents,
           "m2m_inbox": _op_inbox,
           "m2m_notifier": _op_notifier}


def traiter(operation: str, args: dict, capacite: str) -> tuple:
    """L'UNIQUE porte. Rend (succes, resultat|motif).

    La portee exigee depend de l'operation : lire demande `m2m:read`, emettre
    demande `m2m:write`. Une habilitation d'emission peut lire -- ecrire sans
    pouvoir relire ce qu'on ecrit n'aurait pas de sens -- mais l'inverse est
    refuse, et c'est la tout l'objet d'avoir deux portees.
    """
    if not isinstance(operation, str) or operation not in OPERATIONS:
        return False, "operation inconnue"
    portees = ((PORTEE_EMISSION,) if operation in OPERATIONS_EMISSION
               else (PORTEE_LECTURE, PORTEE_EMISSION))
    lecture, motif = PONT.lire_capacite(capacite, audience=AUDIENCE,
                                        portees=portees, ressources=RESSOURCES)
    if lecture is None:
        return False, motif
    return _ROUTES[operation](args if isinstance(args, dict) else {}, lecture)
