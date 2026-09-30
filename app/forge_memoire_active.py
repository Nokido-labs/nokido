#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memoire_active - la MEMOIRE DE TRAVAIL du corps, en strates.

POURQUOI CET ORGANE EXISTE (mesures 2026-08-25)

Le corps possede deja toutes ses memoires, et aucune ne sert le tour en cours.
`claude_session_start` choisit la memoire injectee UNE FOIS, a la minute zero, par
`ORDER BY rowid DESC LIMIT 4` : la recence d'INSERTION, pas la pertinence. Sur une
session de six heures passee de la RAM au watchdog puis a la CI, le payload memoire
n'a pas bouge d'un octet. `claude_inbox_tick` tourne a CHAQUE tour et n'injecte que
l'inbox et l'etat du hub. Et la zone `active_bugs` porte 29 faits - le registre des
dettes - que personne ne lit par tour.

Consequence mesuree le jour meme : un defaut diagnostique a 10 h a ete oublie
jusqu'a 22 h, DANS LA MEME SESSION, contexte intact. Ce n'etait pas une perte de
contexte, c'etait une obligation sans porteur. Aucune recherche semantique n'aurait
rattrape ca ; une dette ouverte, si.

CE QUE CET ORGANE N'EST PAS : un stock de plus. Il ne stocke RIEN, il COMPOSE.
Chaque strate delegue a l'organe qui possede deja la matiere.

LES STRATES, A L'IMAGE DU CORPS
  immediate       ce qui EXIGE quelque chose maintenant : les dettes ouvertes.
                  Deterministe, aucune recherche, donc aucun taux de rappel a subir.
  courte          la memoire d'enquete : sommes-nous deja passes par la ?
  longue          le rappel lexical sur le corpus consolide.
  introspective   ou vit le sujet dans le CODE.
  proprioceptive  l'etat du corps, avec la CONFIANCE qu'il s'accorde.

TROIS REGLES QUE CET ORGANE S'IMPOSE
  1. Une strate qui n'a PAS PU regarder le DIT (`non_vu`) ; jamais une liste vide
     silencieuse. « Je n'ai rien vu » n'est pas « il n'y a rien ».
  2. Ce qui est ECARTE par le budget est COMPTE et annonce.
  3. Chaque entree porte sa PROVENANCE et son AGE. Une memoire sans provenance ne
     peut pas etre refutee.

SALIENCE INVERSEE POUR LES DETTES : une observation vieillit, une dette s'aggrave.
La salience d'une dette ouverte CROIT donc avec l'age. On ne touche PAS a la
decroissance du blackboard, juste pour `discovered_facts` : la salience se calcule
A LA LECTURE, ce qui laisse le garde d'origine intact et rend le geste reversible.
Meme regle que la dette de sommeil du circadien, rendue ineffacable le meme jour.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

__FORGE_COLOR__ = "cognition/memoire-de-travail"

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ZONE_DETTES = "active_bugs"
STRATES = ("immediate", "courte", "longue", "introspective", "proprioceptive")

# Le hook par tour paie ce texte a CHAQUE tour, et l'historique est re-facture : une
# memoire genereuse coute plus cher que l'oubli qu'elle repare.
BUDGET_CHARS = int(os.environ.get("LAFORGE_MEMOIRE_BUDGET_CHARS", "2200"))

MARQUEUR_CLOS = "[CLOS"
# Prose heritee : les dettes anterieures a cet organe n'ont aucun etat structure, on
# les lit au mieux. Toute dette NOUVELLE porte `[CLOS ...]`, requetable.
_MOTS_CLOS = ("RESOLU", "RETRACTE", "_resolved", MARQUEUR_CLOS)


def _entree(texte, source, age_s=None, **extra):
    e = {"texte": texte, "source": source,
         "age_s": None if age_s is None else round(age_s)}
    e.update(extra)
    return e


def _est_close(cle: str, valeur: str) -> bool:
    hay = cle + " " + valeur[:400]
    return any(m in hay for m in _MOTS_CLOS)


def _faits(brut):
    """La zone a deux formes possibles selon l'appelant ; on accepte les deux.

    Ecrit une fois, utilise PARTOUT : la premiere version tolerait les deux formes
    dans le lecteur et pas dans le verificateur, qui levait donc `AttributeError`
    juste apres l'ecriture. Une meme donnee lue par deux chemins qui ne s'accordent
    pas, c'est le defaut que ce module traque ailleurs.
    """
    if isinstance(brut, dict):
        f = brut.get("facts")
        return f if isinstance(f, list) else None
    return brut if isinstance(brut, list) else None


def _age_reel(fait: dict) -> float:
    """Depuis QUAND cette dette court-elle, et non depuis quand on l'a retouchee.

    Defaut mesure a la mise en service (2026-08-25) : rafraichir une dette de 52
    jours avec la mesure du jour a remis son `age_days` a 0 - donc effacé sa
    CHRONICITE, c'est-a-dire exactement le signal que cet organe existe pour
    preserver. Une dette porte donc `depuis=<AAAA-MM-JJ>` dans son texte, et c'est
    cette date qui compte. A defaut, on retombe sur l'age du blackboard, qui reste
    juste pour une dette jamais retouchee.
    """
    val = str(fait.get("value") or "")
    marque = val.find("depuis=")
    if marque >= 0:
        brut = val[marque + 7:marque + 17]
        try:
            debut = datetime.fromisoformat(brut)
            return max(0.0, (datetime.now() - debut).total_seconds() / 86400.0)
        except Exception:  # noqa: BLE001 — date illisible : on retombe sur le registre
            pass
    return float(fait.get("age_days") or 0.0)


def salience_dette(age_jours: float, trust: float = 0.9) -> float:
    """Une dette CRIE de deux facons, comme une douleur.

    La decroissance du blackboard est juste pour une observation et fausse pour une
    obligation : on l'inverse. Mais une croissance PUREMENT monotone a un defaut
    mesure a la mise en service (2026-08-25) : les cinq dettes inscrites le jour meme
    se rangeaient DERNIERES, donc invisibles - le registre ne servait plus a ce pour
    quoi il venait d'etre construit.

    Le corps connait deux douleurs, et les deux se font entendre :
      AIGUE     forte a l'inscription, s'estompe en ~2 jours. C'est le signal frais,
                celui qu'on peut encore traiter a chaud.
      CHRONIQUE croit avec le temps non tenu. C'est la dette de 72 jours qui ne doit
                pas s'eteindre.
    On retient la plus forte des deux : le creux tombe donc au milieu, autour de deux
    a dix jours - exactement la zone ou une obligation se perd sans que personne ne
    la ressente. Le sur-ensemble est borne par `_FRAICHE_GARDE_SA_PLACE`, qui garantit
    qu'une inscription du jour est entendue meme derriere des dettes tres anciennes.
    """
    a = max(0.0, age_jours)
    aigue = math.exp(-a / 2.0)
    chronique = math.log1p(a) / 2.0
    return float(trust) * (1.0 + max(aigue, chronique))


def dettes_ouvertes(limit: int = 3):
    """Les obligations que le corps n'a pas tenues. Rend (entrees, non_vu)."""
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone
    except Exception as e:  # noqa: BLE001
        return [], "registre des dettes injoignable (%s)" % type(e).__name__
    try:
        brut = read_zone(ZONE_DETTES)
    except Exception as e:  # noqa: BLE001
        return [], "lecture de la zone refusee (%s)" % type(e).__name__
    faits = _faits(brut)
    if faits is None:
        return [], "forme inattendue de la zone (%s)" % type(brut).__name__

    ouvertes = []
    for f in faits:
        cle = str(f.get("key") or "")
        val = str(f.get("value") or "")
        if _est_close(cle, val):
            continue
        age_j = _age_reel(f)
        ouvertes.append({
            "cle": cle,
            "age_jours": round(age_j, 1),
            "salience": round(salience_dette(age_j, float(f.get("trust") or 0.9)), 3),
            # Apercu court VOULU : mesure du 2026-08-25, a 190 caracteres les cinq
            # dettes consommaient la totalite du budget du tour et faisaient sauter
            # 10 entrees des autres strates - dont les enquetes anterieures, la
            # matiere la plus utile. Une dette RECLAME ; elle n'affame pas le reste.
            "apercu": val.strip().replace("\n", " ")[:110],
        })
    ouvertes.sort(key=lambda d: -d["salience"])
    retenues = ouvertes[:limit]
    # Une place reservee a la plus FRAICHE : sans elle, une dette inscrite a l'instant
    # reste derriere les tres anciennes et n'est jamais lue. Une douleur aigue doit
    # etre entendue meme quand une douleur chronique hurle plus fort.
    if limit > 1 and ouvertes:
        fraiche = min(ouvertes, key=lambda d: d["age_jours"])
        if fraiche not in retenues:
            retenues = retenues[:limit - 1] + [fraiche]
    ecartees = len(ouvertes) - len(retenues)

    entrees = []
    for d in retenues:
        txt = "%s (%s j) - %s" % (d["cle"], d["age_jours"], d["apercu"])
        entrees.append(_entree(txt, "blackboard/active_bugs",
                               age_s=d["age_jours"] * 86400.0,
                               salience=d["salience"]))
    note = None
    if ecartees:
        note = "%d dette(s) ouverte(s) NON affichee(s) (budget %d)" % (ecartees, limit)
    return entrees, note


def ouvrir_dette(cle: str, quoi: str, auteur: str = "CLAUDE",
                 depuis: str = "") -> dict:
    """Enregistre une obligation. Une phrase ne reclame rien ; une dette, si.

    `depuis` (AAAA-MM-JJ) date le DEBUT de la dette et non sa derniere retouche :
    reactualiser un constat ancien ne doit pas rajeunir la dette. Omis, la dette
    commence aujourd'hui.
    """
    from nokido_agent.app.forge_swarm_blackboard import _write_fact  # noqa: PLC2701

    horodate = datetime.now().isoformat(timespec="seconds")
    origine = (depuis or datetime.now().date().isoformat())[:10]
    val = "[OUVERT %s depuis=%s] %s" % (horodate, origine, quoi)
    _write_fact(ZONE_DETTES, cle, val, "obligation", worker_id=auteur, trust=0.9)
    return _verifier_inscription(cle, "OUVERT")


def _verifier_inscription(cle: str, attendu: str) -> dict:
    """Une ecriture qui ne rend RIEN ne prouve rien.

    Mesure du 2026-08-25 : `_write_fact` rend `None`, donc `ouvrir_dette` rendait
    `None` et l'appelant ne pouvait pas distinguer l'ecriture reussie du silence.
    C'est le defaut meme que cet organe est cense combattre, dans le code qui le
    combat. On RELIT donc la zone - meme exigence que la post-condition posee sur le
    watchdog le meme jour : une commande acceptee n'est pas un effet obtenu.
    """
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "raison": "relecture impossible (%s)" % type(e).__name__}
    try:
        faits = _faits(read_zone(ZONE_DETTES))
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "raison": "relecture refusee (%s)" % type(e).__name__}
    if faits is None:
        return {"ok": None, "raison": "forme de zone inattendue a la relecture"}
    for f in faits:
        if str(f.get("key")) == cle:
            present = attendu in str(f.get("value") or "")
            return {"ok": present, "cle": cle,
                    "raison": None if present else "ecrit mais etat inattendu"}
    return {"ok": False, "cle": cle, "raison": "absente de la zone apres ecriture"}


def clore_dette(cle: str, preuve: str, auteur: str = "CLAUDE") -> dict:
    """Clot une obligation - avec sa PREUVE, jamais sur declaration seule.

    Meme exigence que la post-condition posee sur le watchdog le meme jour : une
    commande acceptee n'est pas un effet obtenu.
    """
    from nokido_agent.app.forge_swarm_blackboard import _write_fact  # noqa: PLC2701

    if not str(preuve).strip():
        return {"ok": False, "cle": cle, "raison": "cloture SANS preuve refusee"}
    horodate = datetime.now().isoformat(timespec="seconds")
    val = "%s %s] preuve=%s" % (MARQUEUR_CLOS, horodate, preuve)
    _write_fact(ZONE_DETTES, cle, val, "obligation", worker_id=auteur, trust=1.0)
    return _verifier_inscription(cle, MARQUEUR_CLOS)


def _courte(intention: str, limit: int = 3):
    """Memoire d'enquete : sommes-nous deja passes par ce symptome ?

    `demander(terme, index, limite)` attend UN terme et un index DEJA construit. Lui
    passer la phrase entiere ne matche rien - mesure du 2026-08-25, ma premiere
    version rendait `TypeError` a chaque tour. On lit donc l'index persiste (le
    reconstruire couterait un balayage de transcripts par tour) et on interroge les
    jetons les plus porteurs de l'intention, un par un.
    """
    if not intention.strip():
        return [], "aucune intention fournie"
    try:
        from nokido_agent.tools.forge_symptom_index import INDEX, demander
    except Exception as e:  # noqa: BLE001
        return [], "index des symptomes injoignable (%s)" % type(e).__name__
    try:
        idx = json.loads(Path(INDEX).read_text(encoding="utf-8"))
        age_s = time.time() - Path(INDEX).stat().st_mtime
    except Exception as e:  # noqa: BLE001
        return [], "index d'enquetes non construit (%s)" % type(e).__name__

    vus = []
    deja = set()
    for terme in sorted(_mots(intention), key=len, reverse=True)[:4]:
        if len(terme) < 5:
            continue
        try:
            for s in demander(terme, idx, limite=2):
                cle = str(s.get("session"))
                if cle in deja:
                    continue
                deja.add(cle)
                vus.append(_entree(
                    "%s (%s) sur '%s' - %s piege(s)" % (
                        cle[:8], s.get("date"), terme, s.get("n_pieges")),
                    "symptom_index", age_s=age_s))
        except Exception as e:  # noqa: BLE001
            return vus, "interrogation en echec sur '%s' (%s)" % (
                terme, type(e).__name__)
        if len(vus) >= limit:
            break
    if not vus:
        return [], "aucune enquete anterieure sur ces termes"
    return vus[:limit], None


def _longue(intention: str, limit: int = 3):
    """Rappel lexical sur le corpus consolide.

    Taux de rappel MESURE le 2026-08-25 : 1 sujet sur 3 rend quelque chose. On ne
    fabrique donc pas de faux signal - une strate vide se declare vide, et l'appelant
    sait que le silence vient du corpus et non d'une panne.
    """
    if not intention.strip():
        return [], "aucune intention fournie"
    try:
        from nokido_agent.app.forge_keeper_base import find
    except Exception as e:  # noqa: BLE001
        return [], "rappel lexical injoignable (%s)" % type(e).__name__
    try:
        hits = find(intention, limit=limit) or []
    except Exception as e:  # noqa: BLE001
        return [], "rappel lexical en echec (%s)" % type(e).__name__
    sortie = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        apercu = str(h.get("preview") or "").strip()[:150]
        if not apercu:
            # Un rappel sans contenu occupe du budget sans rien dire. Mesure du
            # 2026-08-25 : `find` rend parfois une entree sans `preview`, qui
            # s'affichait « [?] » et volait la place d'une strate utile.
            continue
        sortie.append(_entree("[%s] %s" % (h.get("source") or "?", apercu),
                              "keeper/find"))
    if not sortie:
        # Regle 1 de cet organe, appliquee a lui-meme : une strate vide qui se TAIT
        # disparait du rendu, et son silence devient indiscernable d'une panne. Ma
        # premiere version faisait exactement ca (mesure 2026-08-25).
        return [], "aucun rappel sur ces termes (corpus, pas panne)"
    return sortie, None


def _mots(texte: str):
    bas = "".join(c if c.isalnum() else " " for c in texte.lower())
    return [m for m in bas.split() if m]


def _paires(data):
    """La carte a connu deux formes ; on accepte les deux au lieu d'en imposer une."""
    if isinstance(data, dict):
        for organe, v in data.items():
            if isinstance(v, list):
                yield organe, v
            elif isinstance(v, dict):
                yield organe, list(v.keys())
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item.get("organe", "?"), [item.get("module", "?")]


def _introspective(intention: str, limit: int = 4):
    """Ou vit le sujet dans le CODE - la vue du corps sur son propre tissu.

    On lit la carte organe->module deja produite par le recensement plutot que de
    balayer le disque : un balayage a chaque tour couterait le prix d'un audit pour
    rendre le service d'un rappel.
    """
    if not intention.strip():
        return [], "aucune intention fournie"
    carte = SANDBOX / "workspace" / "organ_map_full.json"
    try:
        data = json.loads(carte.read_text(encoding="utf-8"))
        age_s = time.time() - carte.stat().st_mtime
    except Exception as e:  # noqa: BLE001
        return [], "carte du corps illisible (%s)" % type(e).__name__
    mots = [m for m in _mots(intention) if len(m) >= 4]
    if not mots:
        return [], "intention sans mot exploitable"
    trouves = []
    for organe, modules in _paires(data):
        for mod in modules:
            if any(m in str(mod).lower() for m in mots):
                trouves.append((str(mod), str(organe)))
    vus = [_entree("%s - organe %s" % (mod, org), "census/organ_map", age_s=age_s)
           for mod, org in trouves[:limit]]
    note = None
    if age_s > 86400:
        note = "carte du corps vieille de %.1f j (recensement a relancer)" % (
            age_s / 86400)
    if not vus and not note:
        note = "aucun module ne porte ces mots"
    return vus, note


def _proprioceptive(limit: int = 4):
    """L'etat du corps ici et maintenant, AVEC la confiance qu'il s'accorde.

    Le score seul serait trompeur : il a valu 32 puis 57 le meme jour, dont 25 points
    d'angles morts du diagnostic lui-meme. On rend donc score ET confiance ensemble -
    un consommateur qui lit l'un sans l'autre traite une estimation comme une mesure.
    """
    p = SANDBOX / "health_diagnostic.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        age_s = time.time() - p.stat().st_mtime
    except Exception as e:  # noqa: BLE001
        return [], "bilan de sante illisible (%s)" % type(e).__name__
    conf = d.get("confiance")
    suffixe = "" if conf is None else ", confiance %d%%" % round(float(conf) * 100)
    entrees = [_entree("score %s/100%s" % (d.get("score"), suffixe),
                       "health_diagnostic", age_s=age_s)]
    for g in [g for g in (d.get("gaps") or []) if str(g).startswith("❌")][:limit - 1]:
        entrees.append(_entree(str(g)[:190], "health_diagnostic", age_s=age_s))
    note = None
    if age_s > 1800:
        note = "bilan vieux de %.0f min - l'organe de diagnostic bat-il ?" % (age_s / 60)
    return entrees, note


def _taille(proj: dict) -> int:
    return sum(len(e.get("texte", ""))
               for lst in proj["strates"].values() for e in lst)


def projeter(intention: str = "", budget_chars: int = BUDGET_CHARS,
             strates=STRATES) -> dict:
    """Projette, pour CE tour, ce que le corps sait d'utile.

    Rend un objet STRUCTURE et non un bloc de texte : le fait reste separe de son
    interpretation, et un consommateur peut ponderer au lieu de tout lire a plat.
    Le rendu textuel est un service (`rendre`), pas la donnee.
    """
    t0 = time.perf_counter()
    out = {"intention": intention[:200], "strates": {}, "non_vu": {}, "ecarte": 0}
    producteurs = {
        "immediate": lambda: dettes_ouvertes(),
        "courte": lambda: _courte(intention),
        "longue": lambda: _longue(intention),
        "introspective": lambda: _introspective(intention),
        "proprioceptive": lambda: _proprioceptive(),
    }
    for nom in strates:
        prod = producteurs.get(nom)
        if prod is None:
            out["non_vu"][nom] = "strate inconnue"
            continue
        try:
            entrees, note = prod()
        except Exception as e:  # noqa: BLE001
            out["strates"][nom] = []
            out["non_vu"][nom] = "strate en echec (%s)" % type(e).__name__
            continue
        out["strates"][nom] = entrees
        if note:
            out["non_vu"][nom] = note

    # On coupe par les strates les MOINS exigeantes d'abord : une dette ouverte
    # reclame, un rappel lexical propose. Et ce qui saute est COMPTE.
    # `immediate` en DERNIER : c'est la seule strate qui reclame une action, elle ne
    # cede qu'apres tout le reste. Mais elle cede : sans cela, un budget trop etroit
    # sortirait silencieusement hors des clous au lieu de le declarer.
    ordre_sacrifice = ("longue", "introspective", "courte", "proprioceptive",
                       "immediate")
    while _taille(out) > budget_chars:
        for nom in ordre_sacrifice:
            lst = out["strates"].get(nom)
            if lst:
                lst.pop()
                out["ecarte"] += 1
                break
        else:
            break
    out["cout_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


_TITRES = {
    "immediate": "DETTES OUVERTES (elles reclament)",
    "courte": "DEJA VU (memoire d'enquete)",
    "longue": "RAPPEL",
    "introspective": "DANS LE CODE",
    "proprioceptive": "ETAT DU CORPS",
}


def rendre(proj: dict) -> str:
    """Rendu texte pour un canal par tour. Compact, et il DIT ce qu'il n'a pas vu."""
    lignes = []
    for nom in STRATES:
        entrees = proj["strates"].get(nom) or []
        note = proj["non_vu"].get(nom)
        if not entrees and not note:
            continue
        lignes.append("[memoire:%s] %s" % (nom, _TITRES.get(nom, nom)))
        for e in entrees:
            lignes.append("  - %s" % e["texte"])
        if note:
            lignes.append("  ? %s" % note)
    ecarte = proj.get("ecarte") or 0
    if ecarte:
        lignes.append("[memoire] %d entree(s) ecartee(s) par le budget" % ecarte)
    return "\n".join(lignes)


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Projection de la memoire de travail")
    ap.add_argument("intention", nargs="*", help="sujet du tour")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    proj = projeter(" ".join(a.intention))
    print(json.dumps(proj, ensure_ascii=False, indent=1) if a.json else rendre(proj))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
