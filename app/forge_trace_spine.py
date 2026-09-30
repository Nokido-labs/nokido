# -*- coding: utf-8 -*-
"""CONTRAT DE PROVENANCE des traces — l'etape qui doit preceder toute centralisation.

POURQUOI CE MODULE EXISTE
=========================
Audit mesure du 2026-08-23 : Nokido ecrit 60 sources de traces sur SIX formats
d'horloge, et 37 d'entre elles ne portent aucune cle causale. Mais la lacune la
plus couteuse n'est pas la variete des formats — c'est que DEUX SOURCES AU MEME
FORMAT peuvent avoir des REPERES OPPOSES :

    network_log        2026-08-23T19:32:10.238        ISO naif -> heure LOCALE
    event_bus_replay   2026-08-23T17:32:10.322988     ISO naif -> heure UTC

Preleves dans la meme seconde. Sept mille deux cents secondes d'ecart, aucune
difference visible, aucune erreur levee. Tout rapprochement temporel entre ces
deux familles est faux depuis toujours, et rien ne permet de s'en apercevoir.

CE N'EST PAS UNE CRAINTE THEORIQUE. Le meme jour, une sonde a conclu « le bus
n'annonce pas les defaillances » sur des traits decales de deux heures par rapport
a leurs etiquettes. Le negatif etait un artefact d'horloge. Centraliser ces
sources sans contrat n'aurait pas corrige l'erreur : il l'aurait GRAVEE dans le
journal canonique, ou plus rien ne la distinguerait d'une mesure.

TROIS ETATS, JAMAIS DEUX — applique a la provenance
==================================================
Le module de canaux impose deja : None = illisible, 0 = mesure nulle. Ici la meme
regle porte sur le TEMPS, et il y a trois etats et non deux :

    date                 -> horodatage resolu, repere connu
    non date             -> pas d'horodatage du tout
    date SANS REPERE     -> un horodatage existe mais on ignore dans quel repere

Le troisieme est le dangereux : il RESSEMBLE au premier. Un producteur qui ne
declare pas son repere est donc REFUSE a l'ingestion, jamais ingere au jugement.

CE QUE CE MODULE N'EST PAS
==========================
Il n'est pas la source de verite de l'ETAT. Les organes gardent le leur — le RAG,
le hub, la coagulation, le gestionnaire de ressources. La spine est la source de
verite des TRACES, c'est-a-dire de ce qui a ete observe et quand.

L'ecriture primaire est un JSONL append-only : pas de verrou, pas de contention,
et il survit a la mort du hub. `EVENT_SPEC.md` section Q4 l'avait deja tranche —
« jsonl append-only pour le replay log, SQLite pour une future indexation, hors du
chemin critique ». La regle vient de la : une ecriture SQLite verrouillee est
PERDUE si personne ne la reprend, et trente producteurs synchrones la garantissent.
"""
from __future__ import annotations

# INTEROCEPTION, et non observabilite : l'observabilite sert un humain qui REGARDE,
# l'interoception sert l'organisme qui SE REGULE. Anatomiquement, ce module est le
# premier relais commun des afferences viscerales — l'equivalent du noyau du
# tractus solitaire, ou convergent les fibres venues des organes avant tout etage
# superieur. Il RELAIE et NORMALISE, il ne memorise pas (la memoire est ailleurs)
# et il n'interprete pas (l'interpretation est corticale).
__FORGE_COLOR__ = "SN vegetatif/interoception"

import json
import os
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

_APP = os.path.dirname(os.path.abspath(__file__))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

_ROOT = Path(_APP).parent
JOURNAL = _ROOT / "sandbox" / "trace_spine.jsonl"

SCHEMA_VERSION = 1

# Formats d'horloge reconnus. `iso_naif` et `sql_naif` n'ont PAS de repere
# intrinseque : un producteur qui les emet DOIT declarer le sien.
FORMATS_SANS_REPERE = ("iso_naif", "sql_naif")
FORMATS = ("epoch_s", "epoch_ms", "iso_tz") + FORMATS_SANS_REPERE

REPERES = ("utc", "local")


@dataclass(frozen=True)
class Provenance:
    """Contrat d'un producteur de traces. Tous les champs sont MESURES, pas supposes."""
    producteur: str
    organe: str
    horloge: str
    champ_ts: str
    repere: str | None = None          # requis si horloge sans repere intrinseque
    cles_causales: tuple = ()
    note: str = ""
    # Relations QUALIFIEES (2026-09-16). `cles_causales` reste pour la
    # compatibilite ascendante : c'est un tuple de NOMS, et un nom ne dit rien.
    relations: tuple = ()

    def __post_init__(self):
        if self.horloge not in FORMATS:
            raise ValueError("horloge inconnue %r pour %s" % (self.horloge, self.producteur))
        if self.horloge in FORMATS_SANS_REPERE and self.repere not in REPERES:
            raise ValueError(
                "%s emet du %s, qui n'a AUCUN repere intrinseque : le repere doit etre "
                "DECLARE ('utc' ou 'local'), pas devine" % (self.producteur, self.horloge))


# ---------------------------------------------------------------------------
# REGISTRE — chaque entree a ete MESUREE le 2026-08-23 en comparant le dernier
# horodatage de la source a l'instant present : le repere retenu est celui qui
# donne un ecart proche de zero. Une declaration invérifiable ne vaudrait rien.
# ---------------------------------------------------------------------------
REGISTRE: dict[str, Provenance] = {}


def declarer(p: Provenance) -> Provenance:
    REGISTRE[p.producteur] = p
    return p


# ---------------------------------------------------------------------------
# LE MEME CONTRAT, SUR L'AXE DE L'IDENTITE (2026-09-16)
#
# Ce module a deja appris la lecon sur le TEMPS : `horloge` dit le format,
# `repere` dit la semantique, et sans cette paire deux ISO naifs aux reperes
# opposes se fusionnaient silencieusement. L'identite n'avait PAS son
# equivalent -- `cles_causales` n'est qu'un tuple de NOMS.
#
# MESURE QUI L'IMPOSE, sur donnees reelles, six cles examinees :
#   corr_id        taille max 2, duree mediane 4 ms, 94,9 % inter-agent
#   correlation_id 99,7 % de SINGLETONS, duree jusqu'a 9,7 jours
#   session_id     362 groupes d'UNE ligne + UN groupe de 21 426, max 176 jours
#   sequence_id    37 761 distincts sur 42 027 -- quasi unique
#   prev_hash      chainage 20 245 / 20 245 = 100 %
#   parent_id      ne relie AUCUN groupe a un autre
#
# AUCUNE n'est une cle causale, et TROIS portent un nom qui ment sur leur
# fonction. Les unifier au motif que « corr_id » et « correlation_id » se
# ressemblent aurait joint des paires de 4 ms a des identifiants uniques
# etales sur dix jours. D'ou la regle que ce contrat rend EXECUTABLE :
#
#       le NOM d'un champ ne dit RIEN de sa semantique.
#
# Il n'y a donc PAS de cle causale universelle a canoniser : il y a plusieurs
# relations ORTHOGONALES qu'il serait dangereux de fusionner.
# ---------------------------------------------------------------------------

RELATIONS = frozenset({
    "correlation",             # quels evenements appartiennent au meme echange
    "message_identity",        # identifiant d'UN message
    "execution_identity",      # quelle instance / quel processus
    "parentage",               # par quoi l'appel est arrive (filiation d'appel)
    "causal_reason",           # POURQUOI -- la seule relation reellement causale
    "sequence",                # ordre declare
    "integrity_predecessor",   # chainage cryptographique
})

# Une relation n'est causale que si elle dit POURQUOI. `integrity_predecessor`
# prouve que A precede B et le signe ; il ne dit pas que A a CAUSE B. Et
# `parentage` dit PAR QUOI, pas POURQUOI. Les confondre fabriquerait de la
# causalite a partir d'une succession -- exactement ce que ce module refuse
# deja de faire avec les horodatages.
RELATIONS_CAUSALES = frozenset({"causal_reason"})

PORTEES = frozenset({
    "echange",    # un aller-retour requete/reponse
    "message",    # un message isole
    "session",    # une session applicative
    "action",     # une action du cycle de vie
    "chaine",     # une chaine d'integrite
    "process",    # la duree de vie d'un processus (un pid est RECYCLE)
    "inconnue",   # portee non mesuree -- se DIT, ne se devine pas
})

# Quatre etats, jamais deux. Une declaration jamais confrontee a sa source
# devient un mensonge : le registre annoncait `session_id` pour network_log
# alors que la base localisee porte `req_id`.
ETATS_RELATION = ("DECLARE", "OBSERVE", "NON_RESOLU", "CONTREDIT")


@dataclass
class Relation:
    """Une relation entre evenements, QUALIFIEE par mesure et non par son nom."""

    champ: str
    relation: str
    portee: str
    etat: str = "DECLARE"
    mesure: str = ""

    def __post_init__(self):
        if self.relation not in RELATIONS:
            raise ValueError(
                "relation inconnue %r pour le champ %r : le vocabulaire est FERME, "
                "sinon n'importe quel nom passerait pour une semantique"
                % (self.relation, self.champ))
        if self.portee not in PORTEES:
            raise ValueError(
                "portee inconnue %r pour le champ %r : une portee se MESURE "
                "(cardinalite, duree, agents), elle ne se devine pas"
                % (self.portee, self.champ))
        if self.etat not in ETATS_RELATION:
            raise ValueError("etat inconnu %r pour le champ %r" % (self.etat, self.champ))


def est_causale(r: Relation) -> bool:
    """Vrai seulement si la relation dit POURQUOI."""
    return r.relation in RELATIONS_CAUSALES


def compatibles(a: Relation, b: Relation) -> tuple:
    """(joignables, motif). Le refus est la valeur par defaut, et il est DIT.

    Trois conditions, dans cet ordre : les deux relations doivent avoir ete
    OBSERVEES, porter le MEME role, et couvrir la MEME portee. Une seule qui
    manque et la jointure produirait une correspondance fausse -- pas une
    erreur bruyante, un resultat plausible et faux.
    """
    for r in (a, b):
        if r.etat != "OBSERVE":
            return False, ("%s est a l'etat %s : une relation jamais MESUREE ne "
                           "se joint a rien" % (r.champ, r.etat))
    if a.relation != b.relation:
        return False, ("roles differents : %s est %s, %s est %s -- des noms voisins "
                       "ne font pas une semantique commune"
                       % (a.champ, a.relation, b.champ, b.relation))
    if a.portee != b.portee:
        return False, ("portee differente : %s couvre %s, %s couvre %s"
                       % (a.champ, a.portee, b.champ, b.portee))
    return True, ""


declarer(Provenance("network_log", "SNC/hub", "iso_naif", "ts", repere="local",
                    cles_causales=("session_id",),
                    note="SEULE source naive en heure LOCALE ; 236k lignes sur 721 h"))
declarer(Provenance("event_bus_replay", "SNC/bus", "iso_naif", "ts", repere="utc",
                    cles_causales=("corr_id", "parent_id"),
                    note="seule source portant corr_id ET parent_id"))
declarer(Provenance("inspector_log", "SN vegetatif", "sql_naif", "ts", repere="utc"))
declarer(Provenance("agent_messages", "SNC/postal", "sql_naif", "created_at", repere="utc",
                    cles_causales=("correlation_id",)))
declarer(Provenance("coagulation_events", "immunitaire", "iso_naif", "ts_detected", repere="utc",
                    note="brèches de heartbeat de worker ; les flaps de SERVICE ne passent pas ici"))
declarer(Provenance("coagulation_log", "immunitaire", "iso_tz", "ts",
                    note="escalades de flap de service ; 5555 sur 677 h"))
declarer(Provenance("lifecycle_actions", "SN vegetatif", "iso_tz", "ts",
                    note="772 h ; actions dominantes REACTIVES a la RAM, cf garde anti-fuite"))
declarer(Provenance("promcp_tool_metrics", "SNC/hub", "epoch_s", "ts",
                    note="latence et octets PAR APPEL ; plafond porte a 50k le 2026-08-23"))
declarer(Provenance("hub_blackbox", "observabilite", "epoch_s", "ts",
                    note="observateur EXTERNE du hub ; l'append n'est pas monotone"))
declarer(Provenance("vitals_history", "regulation", "epoch_s", "ts",
                    note="35 canaux depuis le 2026-08-23, dont 17 evenementiels"))
declarer(Provenance("event_log", "observabilite", "iso_tz", "timecode",
                    cles_causales=("session_id", "sequence_id", "prev_hash"),
                    note="chaine par hash ; 3616 h mais 0,2 evt/min"))


# ---------------------------------------------------------------------------
def normaliser_ts(valeur, prov: Provenance) -> tuple[float | None, str]:
    """Rend (epoch_utc, raison). `None` avec la RAISON quand on ne peut pas dater.

    Ne devine JAMAIS un repere : c'est le contrat qui le porte."""
    if valeur is None or valeur == "":
        return None, "non date (aucun horodatage)"
    if prov.horloge in ("epoch_s", "epoch_ms"):
        try:
            f = float(valeur)
        except (TypeError, ValueError):
            return None, "horloge %s attendue, valeur non numerique %r" % (prov.horloge, str(valeur)[:24])
        return (f / 1000.0 if prov.horloge == "epoch_ms" else f), ""
    try:
        d = datetime.fromisoformat(str(valeur)[:26].replace("Z", "+00:00"))
    except Exception:
        return None, "horodatage illisible %r" % (str(valeur)[:28],)
    if d.tzinfo is not None:
        return d.timestamp(), ""
    if prov.repere == "utc":
        return d.replace(tzinfo=timezone.utc).timestamp(), ""
    if prov.repere == "local":
        return d.timestamp(), ""       # naif -> local, ce que fait Python par defaut
    return None, "date SANS REPERE : le producteur n'a pas declare utc/local"


def verifier(prov: Provenance, horodatage_recent, tolerance_s: float = 900.0) -> tuple[bool, str]:
    """Confronte la DECLARATION au REEL en comparant un horodatage frais au present.

    C'est ce qui separe un contrat d'une bonne intention : un repere mal declare
    produit un ecart d'exactement 3600 ou 7200 s, immediatement visible ici, alors
    qu'il resterait invisible pendant des mois dans un journal centralise."""
    ts, raison = normaliser_ts(horodatage_recent, prov)
    if ts is None:
        return False, raison
    ecart = ts - time.time()
    if abs(ecart) <= tolerance_s:
        return True, "ecart %+.0f s" % ecart
    return False, ("ecart %+.0f s (%.1f h) — repere probablement FAUX ; un decalage "
                   "proche d'un multiple de 3600 s trahit un utc/local inverse"
                   % (ecart, ecart / 3600.0))


# ---------------------------------------------------------------------------
# RELATIONS MESUREES le 2026-09-16, attachees APRES declaration pour ne pas
# reecrire les entrees du registre. Chaque `mesure` porte le chiffre qui fonde
# la qualification : sans lui, l'etat resterait DECLARE.
# ---------------------------------------------------------------------------
_RELATIONS_MESUREES = {
    "event_bus_replay": (
        Relation("corr_id", "correlation", "echange", "OBSERVE",
                 "3689 groupes, taille max 2, duree mediane 0,004 s, 94,9 % inter-agent"),
        Relation("parent_id", "parentage", "inconnue", "NON_RESOLU",
                 "present sur 43,6 % mais ne relie AUCUN groupe a un autre"),
    ),
    "agent_messages": (
        Relation("correlation_id", "message_identity", "message", "OBSERVE",
                 "21 871 groupes, 99,7 % de singletons, duree max 9,7 jours"),
    ),
    "event_log": (
        Relation("session_id", "correlation", "session", "OBSERVE",
                 "713 groupes dont UN de 21 426 lignes (moitie de la table), max 176 j "
                 "-- session degenere, inexploitable en l'etat"),
        Relation("sequence_id", "message_identity", "message", "OBSERVE",
                 "37 761 distincts sur 42 027 : quasi unique, n'ordonne rien de collectif"),
        Relation("prev_hash", "integrity_predecessor", "chaine", "OBSERVE",
                 "20 245 predecesseurs, 20 245 retrouves = 100 % -- integrite, PAS causalite"),
    ),
    "lifecycle_actions": (
        Relation("reason", "causal_reason", "action", "OBSERVE",
                 "cause en clair emise depuis toujours, ignoree du registre jusqu'ici"),
        Relation("callers", "parentage", "action", "OBSERVE",
                 "pile d'appel du producteur de l'action"),
        Relation("by", "execution_identity", "process", "OBSERVE",
                 "porte le pid -- correlation COURTE, un pid est recycle par l'OS"),
    ),
    "network_log": (
        Relation("session_id", "correlation", "inconnue", "CONTREDIT",
                 "declare au registre, INTROUVABLE a la source : sandbox/network_log.db "
                 "porte bridge_logs (ts, method, tool, latency_ms, status, req_id) sans "
                 "cette colonne. Reserve : table peut-etre ailleurs -- NON TROUVEE ICI, "
                 "jamais inexistante"),
    ),
    # vitals_history reste VOLONTAIREMENT sans relation causale : c'est un
    # echantillonneur PERIODIQUE, declenche par la cadence et non par une action.
    # Lui attacher une cause FABRIQUERAIT une appartenance. Un NR l'interdit.
}
# `Provenance` est FROZEN, et c'est voulu : un contrat qu'on peut modifier apres
# coup n'est plus un contrat. On RECONSTRUIT donc l'entree au lieu de la muter,
# puis on la redeclare par le meme chemin que toutes les autres.
for _nom, _rels in _RELATIONS_MESUREES.items():
    if _nom in REGISTRE:
        declarer(replace(REGISTRE[_nom], relations=_rels))


def ingerer(producteur: str, brut: dict, kind: str = "mesure") -> tuple[dict | None, str]:
    """Rend (evenement canonique, raison de refus). Un producteur NON DECLARE est
    refuse : l'ingerer au jugement reviendrait a inventer sa provenance."""
    prov = REGISTRE.get(producteur)
    if prov is None:
        return None, ("producteur non declare : %r. Le declarer via `declarer(Provenance(...))` "
                      "AVANT d'ingerer -- une provenance devinee est une provenance fausse"
                      % producteur)
    ts, raison = normaliser_ts(brut.get(prov.champ_ts), prov)
    if ts is None:
        return None, raison
    evt = {
        "schema": SCHEMA_VERSION,
        "ts": round(ts, 6),                       # TOUJOURS epoch UTC, un seul repere
        "ts_source": brut.get(prov.champ_ts),     # la valeur d'origine, pour l'audit
        "producteur": prov.producteur,
        "organe": prov.organe,
        "horloge_source": prov.horloge,
        "repere_source": prov.repere or "intrinseque",
        "kind": kind,
        "data": {k: v for k, v in brut.items() if k != prov.champ_ts},
    }
    for cle in prov.cles_causales:
        if brut.get(cle):
            evt[cle] = brut[cle]
    # Les champs des relations QUALIFIEES sont hisses au meme niveau : une
    # relation declaree dont le champ resterait enfoui dans `data` ne serait
    # joignable par personne, donc la declaration n'aurait aucun effet.
    for _r in prov.relations:
        if brut.get(_r.champ) and _r.champ not in evt:
            evt[_r.champ] = brut[_r.champ]
    return evt, ""


def ecrire(evt: dict, journal: Path | None = None) -> bool:
    """Ecriture PRIMAIRE : append-only, sans verrou, survivant a la mort du hub.

    SQLite n'est qu'un index DERIVE, construit hors du chemin critique — trente
    producteurs ecrivant en synchrone dans une base recreeraient la contention
    qu'une ecriture perdue paye deja ailleurs dans le corps."""
    p = journal or JOURNAL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
        return True
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("Nokido.Spine").warning(
            "[spine] ecriture REFUSEE pour %s | consequence: cette trace est perdue, "
            "et une trace perdue ne se distingue pas d'un evenement qui n'a pas eu lieu",
            evt.get("producteur"))
        return False


# ---------------------------------------------------------------------------
# AFFERENCES — les adaptateurs qui raccordent un producteur existant au relais.
#
# Un nerf transporte le PRESENT, pas l'archive : un adaptateur nouvellement
# raccorde demarre a l'instant, il ne rejoue pas des mois d'historique. Rejouer
# est un acte DELIBERE (`depuis=`), pas un effet de bord du branchement — sans
# quoi le premier tick ingererait 236 000 lignes et noierait le relais.
#
# La position est persistee : sans elle, chaque tick relirait tout, et un relais
# qui coute plus cher que ce qu'il transporte n'est pas viable.
# ---------------------------------------------------------------------------
POSITIONS = _ROOT / "sandbox" / "trace_spine_positions.json"


def _positions() -> dict:
    try:
        return json.loads(POSITIONS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  # muet-ok : absence de fichier au premier
        # raccordement ; le dict vide fait demarrer chaque nerf au present, ce qui
        # est le comportement voulu et non une perte.
        return {}


def _ecrire_positions(p: dict) -> None:
    try:
        POSITIONS.parent.mkdir(parents=True, exist_ok=True)
        tmp = POSITIONS.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        tmp.replace(POSITIONS)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("Nokido.Spine").warning(
            "[spine] positions NON persistees | consequence: le prochain tick "
            "relira depuis le present et le segment courant sera perdu")


def afferent_jsonl(producteur: str, chemin: Path, pos: dict,
                   plafond: int = 5000) -> tuple[list, str]:
    """Afference sur un flux append-only. Lit ce qui a ete AJOUTE depuis le dernier
    passage. Un fichier qui RETRECIT (rotation) remet la position au present plutot
    que de rejouer : un pic fantome de plusieurs milliers d'evenements serait pire
    qu'un trou assume."""
    cle = "jsonl:" + producteur
    try:
        taille = chemin.stat().st_size
    except Exception as e:  # noqa: BLE001
        return [], "flux absent (%s)" % type(e).__name__
    depart = pos.get(cle)
    if depart is None or depart > taille:
        pos[cle] = taille
        return [], ("raccordement au present" if depart is None
                    else "flux tronque ou tourne — position remise au present")
    if depart == taille:
        return [], ""
    try:
        with open(chemin, "rb") as fh:
            fh.seek(depart)
            brut = fh.read(min(taille - depart, 8_000_000))
    except Exception as e:  # noqa: BLE001
        return [], "lecture impossible (%s)" % type(e).__name__
    pos[cle] = depart + len(brut)
    out = []
    for b in brut.split(b"\n"):
        b = b.strip()
        if not b or len(out) >= plafond:
            continue
        try:
            out.append(json.loads(b.decode("utf-8", "replace")))
        except Exception:  # noqa: BLE001  # muet-ok : derniere ligne partielle,
            # la position s'arrete apres elle et le prochain passage la relira.
            continue
    return out, ""


def afferent_sqlite(producteur: str, table: str, pos: dict,
                    plafond: int = 5000) -> tuple[list, str]:
    """Afference sur une table. Progresse par `rowid`, qui est l'ordre d'INSERTION —
    et non par l'horodatage, qui peut etre non monotone (mesure : hub_blackbox)."""
    chemin = _ROOT / "RAG" / "embeddings.db"
    if not chemin.exists():
        return [], "base absente"
    cle = "sql:" + producteur
    try:
        import sqlite3

        con = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=0.5)
        try:
            dernier = con.execute("SELECT MAX(rowid) FROM %s" % table).fetchone()[0] or 0
            depart = pos.get(cle)
            if depart is None or depart > dernier:
                pos[cle] = dernier
                return [], ("raccordement au present" if depart is None
                            else "table reinitialisee — position remise au present")
            cur = con.execute(
                "SELECT rowid, * FROM %s WHERE rowid > ? ORDER BY rowid LIMIT ?"
                % table, (depart, plafond))
            noms = [d[0] for d in cur.description]
            brut = cur.fetchall()
            lignes = [dict(zip(noms, r)) for r in brut]
            # PROGRESSER PAR POSITION, PAS PAR NOM (mesure 2026-08-25). L'ancienne
            # forme faisait `lignes[-1]["rowid"]` et levait `KeyError: 'rowid'` des le
            # premier passage REEL : SQLite ne garantit pas que la colonne rendue pour
            # l'expression `rowid` s'appelle « rowid » — une colonne `INTEGER PRIMARY
            # KEY` en est l'alias, et un homonyme venant du `*` l'ecrase dans le dict.
            # Consequence mesuree : `collecter()` levait, donc AUCUN nerf n'aboutissait,
            # donc la moelle ne recevait rien — un appareil juste, rendu inerte par une
            # ligne. On a demande le rowid EN PREMIER : c'est `r[0]`, sans ambiguite.
            dernier_lu = brut[-1][0] if brut else None
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return [], "table illisible (%s: %s)" % (type(e).__name__, str(e)[:60])
    if lignes and dernier_lu is not None:
        pos[cle] = dernier_lu
    return lignes, ""


# Nerf -> (type d'afference, cible). Seuls les producteurs SOUS CONTRAT figurent
# ici : un nerf qui aboutirait sans provenance declaree serait refuse a l'ingestion.
AFFERENCES = {
    "network_log": ("sqlite", "network_log"),
    "promcp_tool_metrics": ("sqlite", "promcp_tool_metrics"),
    "inspector_log": ("sqlite", "inspector_log"),
    "hub_blackbox": ("jsonl", "sandbox/hub_blackbox.jsonl"),
    "lifecycle_actions": ("jsonl", "sandbox/lifecycle_actions.jsonl"),
    "event_bus_replay": ("jsonl", "sandbox/event_bus_replay.jsonl"),
    "vitals_history": ("jsonl", "sandbox/vitals_history.jsonl"),
}


def collecter(journal: Path | None = None) -> dict:
    """Un passage du relais : draine chaque afference, normalise, ecrit.

    Rend un rapport PAR NERF, refus compris. Un relais qui ne dirait pas ce qu'il
    a refuse laisserait croire a une couverture qu'il n'a pas."""
    pos = _positions()
    rapport = {"ingeres": 0, "refuses": 0, "par_nerf": {}}
    for producteur, (genre, cible) in AFFERENCES.items():
        if producteur not in REGISTRE:
            rapport["par_nerf"][producteur] = {"refus": "hors contrat de provenance"}
            continue
        if genre == "jsonl":
            lignes, note = afferent_jsonl(producteur, _ROOT / cible, pos)
        else:
            lignes, note = afferent_sqlite(producteur, cible, pos)
        n_ok = 0
        motifs: dict = {}
        for brut in lignes:
            evt, raison = ingerer(producteur, brut)
            if evt is None:
                motifs[raison[:60]] = motifs.get(raison[:60], 0) + 1
                continue
            if ecrire(evt, journal):
                n_ok += 1
        rapport["ingeres"] += n_ok
        rapport["refuses"] += sum(motifs.values())
        rapport["par_nerf"][producteur] = {
            "lus": len(lignes), "ingeres": n_ok,
            "refuses": sum(motifs.values()) or 0,
            **({"motifs": motifs} if motifs else {}),
            **({"note": note} if note else {}),
        }
    _ecrire_positions(pos)
    return rapport


# ---------------------------------------------------------------------------
# VUES — lecture RETROSPECTIVE des sources a travers le contrat.
#
# La spine ne transporte que le present (regle du nerf), elle n'a donc pas
# d'historique a offrir. Mais le contrat, lui, sait normaliser n'importe quel
# horodatage de n'importe quelle source. `relire()` applique cette normalisation
# a l'existant : c'est ce qui permet de FUSIONNER plusieurs sources dans un repere
# unique et DEMONTRABLE, au lieu de l'alignement par accident qui a produit un
# faux negatif le 2026-08-23.
# ---------------------------------------------------------------------------
def relire(producteur: str, depuis: float | None = None, jusqu: float | None = None,
           plafond: int = 400_000) -> tuple[list, dict]:
    """Relit une source HISTORIQUE et rend ses evenements canoniques, tries.

    Rend (evenements, rapport). Le rapport publie ce qui a ete ECARTE et pourquoi :
    une vue qui tairait ses rejets ferait surestimer la couverture, et c'est
    exactement le defaut que le contrat existe pour empecher."""
    prov = REGISTRE.get(producteur)
    if prov is None:
        return [], {"refus": "producteur non declare : %r" % producteur}
    genre_cible = AFFERENCES.get(producteur)
    if genre_cible is None:
        return [], {"refus": "aucune afference declaree pour %r" % producteur}
    genre, cible = genre_cible

    brut: list = []
    archives_lues = 0
    if genre == "jsonl":
        chemin = _ROOT / cible
        # Les ARCHIVES comptent. `event_bus_replay` archive au-dela de 5 Mo vers
        # `<stem>.<horodatage>.jsonl` : ne relire que le fichier courant reviendrait
        # a preserver l'histoire sur le disque tout en la rendant invisible aux vues,
        # ce qui n'est pas mieux que de l'avoir jetee.
        fichiers = sorted(chemin.parent.glob(chemin.stem + ".*.jsonl")) + [chemin]
        for f in fichiers:
            if not f.exists():
                continue
            if f is not chemin:
                archives_lues += 1
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for ligne in fh:
                        ligne = ligne.strip()
                        if not ligne or len(brut) >= plafond:
                            continue
                        try:
                            brut.append(json.loads(ligne))
                        except Exception:  # noqa: BLE001  # muet-ok : ligne
                            # partielle, comptee comme illisible dans le rapport.
                            brut.append(None)
            except Exception as e:  # noqa: BLE001
                if f is chemin and not brut:
                    return [], {"refus": "flux illisible (%s)" % type(e).__name__}
    else:
        chemin_db = _ROOT / "RAG" / "embeddings.db"
        try:
            import sqlite3

            con = sqlite3.connect("file:%s?mode=ro" % chemin_db.as_posix(), uri=True, timeout=20)
            try:
                cur = con.execute("SELECT * FROM %s LIMIT ?" % cible, (plafond,))
                noms = [d[0] for d in cur.description]
                brut = [dict(zip(noms, r)) for r in cur.fetchall()]
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            return [], {"refus": "table illisible (%s)" % type(e).__name__}

    out, illisibles, hors_fenetre = [], 0, 0
    for d in brut:
        if not isinstance(d, dict):
            illisibles += 1
            continue
        evt, raison = ingerer(producteur, d)
        if evt is None:
            illisibles += 1
            continue
        if (depuis is not None and evt["ts"] < depuis) or (jusqu is not None and evt["ts"] > jusqu):
            hors_fenetre += 1
            continue
        out.append(evt)
    out.sort(key=lambda e: e["ts"])
    rapport = {
        "producteur": producteur, "lus": len(brut), "retenus": len(out),
        "illisibles": illisibles, "hors_fenetre": hors_fenetre,
        "horloge": prov.horloge, "repere": prov.repere or "intrinseque",
    }
    if archives_lues:
        rapport["archives_relues"] = archives_lues
    if out:
        rapport["etendue_h"] = round((out[-1]["ts"] - out[0]["ts"]) / 3600.0, 1)
    return out, rapport


def fusionner(producteurs: list, depuis: float | None = None,
              jusqu: float | None = None) -> tuple[list, dict]:
    """Fusionne plusieurs sources dans un REPERE UNIQUE, et le prouve.

    Le rapport porte, pour chaque source, son format d'horloge d'origine et son
    repere : c'est la seule facon de montrer que la fusion est legitime plutot que
    de l'affirmer. Deux sources ISO naives aux reperes opposes se fusionnaient
    silencieusement avant ce contrat."""
    tout: list = []
    rapports = {}
    for p in producteurs:
        evts, r = relire(p, depuis, jusqu)
        rapports[p] = r
        tout.extend(evts)
    tout.sort(key=lambda e: e["ts"])
    return tout, {"sources": rapports, "total": len(tout),
                  "reperes_fusionnes": sorted({"%s/%s" % (r.get("horloge"), r.get("repere"))
                                               for r in rapports.values() if r.get("horloge")})}


def etat_du_contrat() -> dict:
    """Ce que le contrat couvre, et ce qu'il ne couvre pas — a publier, pas a taire."""
    sans_causal = [p.producteur for p in REGISTRE.values() if not p.cles_causales]
    naifs = [p.producteur for p in REGISTRE.values() if p.horloge in FORMATS_SANS_REPERE]
    # `sans_cle_causale` lit l'ANCIEN tuple de noms et reste publie pour la
    # compatibilite. Seul, il annonce `lifecycle_actions` comme depourvu alors
    # qu'il porte trois relations OBSERVEES : un auto-diagnostic trompeur est
    # precisement le faux calme que ce contrat corrige.
    sans_rel = [p.producteur for p in REGISTRE.values() if not p.relations]
    contredites = ["%s.%s" % (p.producteur, r.champ)
                   for p in REGISTRE.values() for r in p.relations
                   if r.etat == "CONTREDIT"]
    non_resolues = ["%s.%s" % (p.producteur, r.champ)
                    for p in REGISTRE.values() for r in p.relations
                    if r.etat == "NON_RESOLU"]
    causales = ["%s.%s" % (p.producteur, r.champ)
                for p in REGISTRE.values() for r in p.relations if est_causale(r)]
    return {
        "producteurs_declares": len(REGISTRE),
        "sources_auditees_2026_08_23": 60,
        "horloges_naives_a_repere_declare": naifs,
        "sans_cle_causale": sans_causal,
        "relations_declarees": sum(len(p.relations) for p in REGISTRE.values()),
        "sans_relation_qualifiee": sans_rel,
        "relations_causales": causales,
        "relations_contredites": contredites,
        "relations_non_resolues": non_resolues,
        "note": ("60 sources ont ete auditees, %d sont sous contrat. Les autres ne "
                 "sont PAS ingerables en l'etat : ce n'est pas un oubli, c'est le "
                 "refus par defaut." % len(REGISTRE)),
    }


if __name__ == "__main__":
    print(json.dumps(etat_du_contrat(), ensure_ascii=False, indent=2))
