"""forge_epistemic_daemon.py — la SOIF DE CONNAISSANCE, cablee sur les vraies requetes.

Boucle metacognitive demandee par l'owner : Nokido detecte ses LACUNES -> emet un
ressenti (M2M) -> veille approfondie -> integration. Les briques existaient, mortes :
  * forge_epistemic_veille : gap -> ressenti (critical_event + CORTISOL_EPISTEMIC) +
    veille_on_gap (research_agent). Ecrit, jamais appele.
  * forge_veille_digest : integration biblio -> suggestions (repare le 24-07).
  * query_log : trace des recherches RAG reelles.
Ce daemon est le DECLENCHEUR manquant : il lit les requetes reellement posees au RAG,
mesure leur couverture, et sur un gap CERTAIN emet le ressenti + propose au blackboard.

DETECTION FIABLE, PAS un capteur menteur. Le score de pertinence (rerank) chevauche
dans la zone grise : `coverage_dense` rend gap=True SEULEMENT sous un plancher calibre,
gap=None (abstention) au milieu. Mesure 25-07 : zero faux positif sur le jeu calibre.
On ne veille que sur la CERTITUDE — rater un gap (soif muette) coute moins qu'une
veille sur du bruit.

La veille effective (research_agent, lourde) est DESARMEE par defaut
(LAFORGE_EPISTEMIC_AUTO_VEILLE=1 pour armer), avec un cap strict par cycle : par
defaut le daemon DETECTE + RESSENT + PROPOSE, l'execution reste une decision.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/reasoning epistemique, soif de connaissance (think)"  # declare le 2026-09-06 (audit : REGULE sans organe)

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import db_path  # noqa: E402
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402

HEARTBEAT = ROOT / "sandbox" / "epistemic_daemon.heartbeat"
AUTO_VEILLE = os.environ.get("LAFORGE_EPISTEMIC_AUTO_VEILLE", "0") == "1"
MAX_VEILLES_CYCLE = int(os.environ.get("LAFORGE_EPISTEMIC_MAX_VEILLE", "1"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS epistemic_seen (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT,
    verdict TEXT,
    score REAL,
    seen_at REAL
);
"""


# Un compteur qui AVANCE dans le libelle est de l'ETAT (« depuis combien de
# temps »), jamais du SUJET (« de quoi »). Le laisser dans la cle de memoire
# donne un hash NEUF a chaque cycle : l'organe re-pose eternellement la meme
# question sans jamais se souvenir de l'avoir posee.
# MESURE 2026-07-27 (diagnostic AGY, verifie en base) : la question
# « Workers daemon morts heartbeat stale : ['rss_watcher'] (chronique depuis N
# cycles) » figure ~10 fois dans epistemic_seen sous DIX hash differents, toutes
# en indetermine_abstention — dense + rerank rejoues a chaque cycle pour rien.
# Le texte STOCKE garde son compteur (il informe) ; seule la CLE l'ignore.
_VOLATILE = re.compile(r"depuis\s+\d+\s+cycles?", re.I)

# Refractaire par SUJET d'intention (48 h). Borne basse proposee par AGY le
# 27-07 et retenue : un sujet traite se tait le temps qu'une veille ou un
# travail humain puisse le combler, puis redevient exigible s'il est encore le
# moins couvert. Trop court = harcelement ; definitif = amnesie.
_INTENTION_TTL_S = float(os.environ.get("LAFORGE_EPISTEMIC_INTENTION_TTL_S", 48 * 3600))

# ── EXAMEN EXTEROCEPTIF A LA DEMANDE (owner 2026-09-30) ─────────────────────────
# Mesure du jour : 22/22 cycles BLOQUE_PAR_DEPENDANCE, en ALTERNANCE reranker / dense.
# L'examen a besoin de l'embedder (:8099) ET du reranker (:8100) dans le MEME cycle ;
# la soif ne reclamait que le reranker (rien pour le dense), le keeper allumait UN
# pilier puis l'eteignait « INUTILE » 15 min plus tard (TTL de l'intention = intervalle
# de la soif), pendant que le cycle suivant reclamait l'autre : 1,4 a 3,2 Go reveilles
# toutes les 15 min pour ZERO examen.
# Decision owner : l'examen (~4,6 Go de piliers) ne part plus a heure fixe. Il part sur
# un SEUIL de besoin, a la MAIN (--examiner), ou au plus tard apres EXAMEN_MAX_AGE_S ;
# il reclame ses piliers ENSEMBLE et attend (borne) qu'ils repondent. Sous pression RAM
# le keeper ne les demarre pas : l'examen est DIFFERE, rien n'a ete allume, donc rien
# que l'autoregulation doive couper. L'interoception (soin) ne coute rien : elle garde
# son rythme.
SEUIL_EXAMEN = int(os.environ.get("LAFORGE_EPISTEMIC_SEUIL_EXAMEN", "10"))
EXAMEN_MAX_AGE_S = float(os.environ.get("LAFORGE_EPISTEMIC_EXAMEN_MAX_AGE_S", 24 * 3600))
ATTENTE_PILIERS_S = float(os.environ.get("LAFORGE_EPISTEMIC_ATTENTE_PILIERS_S", "180"))
DEMANDE_TTL_S = 6 * 3600
_PILIERS_EXAMEN = (("embed.wanted", "http://127.0.0.1:8099/health"),
                   ("rerank.wanted", "http://127.0.0.1:8100/health"),
                   (None, "http://127.0.0.1:6333/readyz"))   # Qdrant : service permanent


def _norm(q: str) -> str:
    return _VOLATILE.sub("depuis N cycles", " ".join((q or "").lower().split()))[:200]


def _beat(msg: str) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`). L'ecriture maison
    # n'inscrivait aucun `pid` : le pouls attestait d'une vie sans dire QUI la porte,
    # donc aucune autorite ne pouvait lui etre attribuee. `beat_daemon` ne leve
    # jamais et constate l'emission au passage.
    from nokido_agent.app.forge_heartbeat import beat_daemon

    beat_daemon("epistemic_daemon", note=msg)


def _propose_gap(query: str, cov: dict) -> None:
    """Emet le ressenti (feel_gap) et propose le gap au blackboard (M2M)."""
    try:
        ev.feel_gap(domain="reference", query=query)  # critical_event + CORTISOL_EPISTEMIC
    except Exception:  # noqa: BLE001 - le ressenti ne doit pas tuer le daemon
        pass
    try:
        sys.path.insert(0, str(ROOT))
        import asyncio

        from nokido_agent.app.forge_swarm_blackboard import apply_fact

        # `forge_blackboard` n'a JAMAIS existe (le reel est forge_swarm_blackboard) et
        # l'ImportError tombait dans un except muet : AUCUN gap n'a jamais atteint le
        # tableau noir. Sa fonction est ASYNC, son parametre est `zone`, et son ACL est
        # par RING -- la zone discovered_facts exige ring<=2 alors que le defaut est 4,
        # donc sans ce ring l'ecriture repart en {"error": "ACL..."} sans rien lever.
        h = hashlib.md5(query.encode()).hexdigest()[:12]
        _r = asyncio.run(apply_fact(
            "discovered_facts",
            f"GAP de connaissance mesure (rerank {cov.get('score')}) sur: {query[:150]}",
            category="knowledge_gap", trust=0.7,
            key=f"gap_{h}",
            source="epistemic_daemon", ring=2))
        if not _r.get("ok"):
            print(f"[epistemic] gap NON propose au blackboard : {_r}", flush=True)
    except Exception as e:  # noqa: BLE001 - ne tue pas le daemon, mais NE SE TAIT PAS
        print(f"[epistemic] blackboard indisponible ({type(e).__name__}: {e})", flush=True)


# ── Afférence INTÉROCEPTIVE ──────────────────────────────────────────────────
# La soif ne lisait QUE `query_log` : ce qu'on a DEMANDÉ au RAG. Afférence
# purement extéroceptive, donc muette dès que personne ne demande rien. Mesuré le
# 2026-07-26 : 147 requêtes au total, toutes déjà dans `epistemic_seen`, et un
# heartbeat « examinees 0, gaps 0, veilles 0 » à chaque cycle. L'organe n'était
# pas mort, il était À SEC.
#
# En physiologie, l'allocation de réparation ne suit pas ce qu'on a regardé : elle
# suit ce qui FAIT MAL — l'inflammation se localise sur la lésion. Il manquait donc
# l'intéroception : les signaux de détresse que le corps publie déjà et que
# personne ne consommait (`health_diagnostic.json`, 5 lacunes, score 50).
#
# On reste sous la MÊME discipline de certitude : ces questions passent par
# `coverage_dense`, qui s'abstient dans la zone grise. Et on ne convertit qu'un
# sous-ensemble : une lacune n'est une question que si elle porte sur un MÉCANISME
# apprenable. « 1067 hash dupliqués » est un arriéré, pas une ignorance ;
# « effecteur en échec » ou « heartbeat mort » en est une.
# DEUX VOIES DISTINCTES, demandé par l'owner — et la distinction est clinique.
#
#   SOIN (self-care)  : il manque une ACTION. Un worker mort, un service DOWN, une
#                       saturation. On ne lit pas un article sur un `rss_watcher`
#                       mort, on le relance. Analogue : inflammation -> réparation.
#   SOIF (épistémique) : il manque un SAVOIR. Comment tel organe doit être régulé,
#                       pourquoi tel effecteur échoue. Analogue : exploration.
#
# Discriminateur : une plaie unique relève du SOIN ; une plaie qui ne guérit PAS
# malgré le traitement cesse d'être un problème de soin et devient un problème de
# DIAGNOSTIC. Un défaut est donc promu en question de connaissance quand il
# PERSISTE — aigu vers soin, chronique vers soif. Mesuré le 2026-07-26 : 4 593
# tentatives d'unload identiques échouées faute d'avoir compris qu'un compte ne
# peut pas terminer le process d'un autre. C'était une ignorance déguisée en panne.
_CARE_MARKERS = ("heartbeat", "stale", "mort", "DOWN", "échec", "echec", "satur", "RAM",
                 # 2026-09-25 : les examens des autres organes (forge_health_diagnostic._lignes_examens).
                 # Sans ces mots, une regression de capacite restait dans un rapport que personne ne lit.
                 "PÉRIMÉ", "REGRESSION", "ERREUR_OUTIL")
_KNOW_MARKERS = ("zone_morte", "régulation", "regulation", "effecteur",
                 "autorégulation", "autoregulation")
_CHRONIC_AFTER = 3  # cycles de persistance avant promotion soin -> soif

# GRADATION NOCICEPTIVE. Le rapport de santé marquait DÉJÀ la gravité — ❌ critique,
# ⚠ alerte, ~ mineur — et personne ne la lisait : un `rss_watcher` mort et une RAM
# saturée partaient avec la même priorité et la même trust=0.7.
# Or un nocicepteur qui ne gradue pas ne protège rien. La douleur EST une échelle :
# c'est ce qui fait qu'on retire la main du feu avant de soigner une écharde.
# Vocabulaire aligné sur `forge_viable_system.algedonic_to_police`, qui escalade vers
# S5 sur "high" et "critical" — inventer un mot ici rendrait l'escalade muette.
_SEV_BY_MARK = {"❌": "critical", "⚠": "medium", "~": "low"}
_SEV_ORDER = ("low", "medium", "high", "critical")


def _sev_bump(sev: str, steps: int = 1) -> str:
    """Une plaie qui ne guérit pas s'AGGRAVE : la chronicité monte d'un cran.

    C'est le même fait clinique que la promotion soin -> soif, vu sous l'angle de
    l'intensité : ce qui dure cesse d'être bénin.
    """
    try:
        return _SEV_ORDER[min(len(_SEV_ORDER) - 1, _SEV_ORDER.index(sev) + steps)]
    except ValueError:
        return sev


def _interoceptive_split(limit: int = 8) -> dict:
    """Sépare SOIN (défaut à réparer) et SOIF (mécanisme à comprendre).

    Rend {"soif": [questions], "soin": [défauts]}, jamais d'exception : une
    afférence qui casse son organe est pire qu'une afférence absente.

    Les compteurs de persistance vivent dans `sandbox/self_care_state.json`. Un
    défaut ABSENT du cycle courant voit son compteur effacé : une lésion guérie se
    remet à zéro, sinon un incident ancien resterait « chronique » à vie et
    déclencherait une veille sur un problème résolu.
    """
    import hashlib as _h
    import json as _json
    import re as _re
    from pathlib import Path as _P

    base = _P(__file__).resolve().parent.parent / "sandbox"
    try:
        d = _json.loads((base / "health_diagnostic.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return {"soif": [], "soin": []}
    try:
        counters = _json.loads((base / "self_care_state.json").read_text(
            encoding="utf-8", errors="replace"))
        if not isinstance(counters, dict):
            counters = {}
    except Exception:  # noqa: BLE001
        counters = {}

    soif, soin, live = [], [], {}
    for g in (d.get("gaps") or []):
        g = str(g)
        clean = _re.sub(r"\s+", " ", _re.sub(r"[^\w\s:'\-\.\[\]]", " ", g)).strip()
        if len(clean) <= 8:
            continue
        sig = _h.sha256(clean.encode()).hexdigest()[:12]
        n = int(counters.get(sig, 0)) + 1
        live[sig] = n
        is_know = any(m in g for m in _KNOW_MARKERS)
        is_care = any(m in g for m in _CARE_MARKERS)
        if is_know or (is_care and n >= _CHRONIC_AFTER):
            why = "mécanisme" if is_know else f"chronique depuis {n} cycles"
            soif.append("regulation Nokido — %s (%s)" % (clean[:170], why))
        # Le SOIN continue PENDANT le diagnostic : une plaie chronique reste une
        # plaie. Promouvoir un défaut en question de connaissance n'annule pas le
        # besoin de le réparer — les deux voies sont simultanées, pas exclusives.
        # (Première écriture de ce bloc : un `elif` faisait disparaître le soin dès
        # la promotion, c'est-à-dire au moment précis où le patient va le plus mal.)
        if is_care:
            sev = "low"
            for _mark, _s in _SEV_BY_MARK.items():
                if _mark in g:
                    sev = _s
                    break
            if n >= _CHRONIC_AFTER:
                sev = _sev_bump(sev)
            soin.append({"fault": clean[:180], "cycles": n, "sig": sig, "severity": sev})
    try:
        (base / "self_care_state.json").write_text(
            _json.dumps(live, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    # LE PLUS GRAVE D'ABORD. Sans ce tri, l'ordre de traitement était celui du
    # rapport, c'est-à-dire arbitraire : une blessure sérieuse pouvait attendre
    # derrière une petite gêne.
    soin.sort(key=lambda x: (-_SEV_ORDER.index(x["severity"]), -x["cycles"]))
    return {"soif": soif[:limit], "soin": soin[:limit]}


def _propose_care(item: dict) -> None:
    """Route un défaut vers le SOIN, à une intensité PROPORTIONNELLE à sa gravité.

    - high / critical -> canal ALGÉDONIQUE : `forge_critical_events.persist` puis
      `algedonic_to_police`, qui escalade vers S5. En VSM le signal algédonique
      SAUTE les niveaux — exactement comme une douleur vive court-circuite la
      délibération : on retire la main avant d'analyser.
    - medium / low -> proposition au tableau noir, voie lente et délibérative,
      chemin éprouvé de `_propose_gap` (zone discovered_facts, ring=2 obligatoire)
      avec `category="self_care"` pour ne pas se confondre avec une lacune de
      connaissance dans le flux.

    On n'émet PAS de nouvelle hormone : le vocabulaire endocrinien en place n'a pas
    de terme pour « blessure », et en inventer un le rendrait illisible par les
    récepteurs existants. La douleur passe par le canal qui a déjà des lecteurs.

    Dans tous les cas on PROPOSE : l'exécution du remède reste à l'organe de
    remédiation.
    """
    sev = item.get("severity", "low")
    if sev in ("high", "critical"):
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_critical_events import persist
            from nokido_agent.app.forge_viable_system import algedonic_to_police

            rid = persist("self_care", sev, {"fault": item["fault"],
                                             "cycles": item["cycles"],
                                             "source": "epistemic_daemon"})
            verdict = algedonic_to_police({"severity": sev})
            print(f"[epistemic] DOULEUR {sev} persistee id={rid} -> algedonique {verdict}",
                  flush=True)
            return
        except Exception as e:  # noqa: BLE001 - on retombe sur la voie lente
            print(f"[epistemic] canal algedonique indisponible "
                  f"({type(e).__name__}: {e}) -> voie lente", flush=True)
    try:
        sys.path.insert(0, str(ROOT))
        import asyncio

        from nokido_agent.app.forge_swarm_blackboard import apply_fact

        _r = asyncio.run(apply_fact(
            "discovered_facts",
            f"SOIN requis [{sev}] (persistant {item['cycles']} cycle(s)) : {item['fault']}",
            category="self_care", trust=0.6 if sev == "low" else 0.75,
            key=f"self_care_{item['sig']}",
            source="epistemic_daemon", ring=2))
        if not _r.get("ok"):
            print(f"[epistemic] soin NON propose au blackboard : {_r}", flush=True)
    except Exception as e:  # noqa: BLE001 - ne tue pas le daemon, mais NE SE TAIT PAS
        print(f"[epistemic] blackboard indisponible ({type(e).__name__}: {e})", flush=True)


def _intentional_split(limit: int = 6) -> list:
    """Ce que Nokido VEUT FAIRE — la source la plus pertinente, et la derniere branchee.

    LECON MESUREE (25-07) : un score de couverture bas mesure la DISTANCE au
    savoir, PAS la pertinence. Chiffres : « flash attention 3 », vrai manque
    utile, scorait -9.05 contre des ancres de domaine, PLUS BAS que « alpagas »
    a -8.8. Le detecteur seul ne distingue donc pas « je devrais apprendre ca »
    de « ca ne me concerne pas ». La pertinence vient de l'INTENTION.

    D'ou cette troisieme source, a cote de l'exteroception (query_log, ce qu'on
    nous demande) et de l'interoception (nos propres douleurs) : ce que le corps
    VISE, lu dans le SSoT roadmap — jalon suivant, blocages, priorites.

    Elle a une propriete que les deux autres n'ont pas : ses questions sont
    ON-DOMAINE PAR CONSTRUCTION. Une couverture basse y designe donc un manque
    REEL et actionnable, sans avoir besoin du filtre hors-variete (seuil ~0.76
    mesure le 25-07) qui reste, lui, necessaire pour le query_log arbitraire.

    Ne leve jamais : sans SSoT lisible, l'organe garde ses deux autres sources.
    """
    out: list = []
    try:
        import json as _j

        d = _j.loads((ROOT / "docs" / "roadmap_state.json").read_text(encoding="utf-8"))
        cibles = []
        if d.get("next_milestone"):
            cibles.append(("vise", d["next_milestone"]))
        for b in (d.get("blockers") or [])[:3]:
            cibles.append(("bute sur", b))
        for niveau in ("P0", "P1", "P2"):
            for it in ((d.get("roadmap") or {}).get(niveau) or [])[:2]:
                cibles.append((niveau, it))
        for tag, txt in cibles:
            t = " ".join(str(txt).split())
            if not t or t.startswith("…"):
                continue  # ligne de plafond d'affichage, pas un objectif
            out.append(f"Nokido {tag} : {t[:160]}")
    except Exception:  # noqa: BLE001
        return []
    return out[:limit]


_MODULE_CITE = re.compile(r"\b((?:forge|nokido)_[a-z0-9_]+)\b", re.I)
# Seules demandes EXPLICITES de savoir exterieur qui justifient une veille web sur une intention.
_EXTERNE_EXPLICITE = ("etat de l'art", "état de l'art", "veille sur", "litterature", "littérature",
                      "specification", "spécification", "rfc ", "http://", "https://")


def _manque_interne(q: str) -> list:
    """Preuves qu'un objectif d'INTENTION est un manque INTERNE (vide = veille web legitime).

    RECIDIVE du 2026-09-25 16:58 : le critere « cite un module » laissait passer mon propre fait P0
    (« la soif n est PAS morte, elle est BLOQUEE ») -- veille web, « REUSSIE, ingerees 10 » sur
    « epistemologie dependance ». Les intentions viennent de la ROADMAP de Nokido
    (_intentional_split) : du travail interne PAR CONSTRUCTION. Interne par defaut, donc ; externe
    seulement sur demande explicite de savoir exterieur. Dans le doute, s'abstenir : rater une veille
    se rattrape, une pollution du corpus vivant se paie a chaque recherche.
    """
    modules = _modules_du_depot_cites(q)
    if modules:
        return modules
    ql = " ".join((q or "").lower().split()) + " "
    if any(m in ql for m in _EXTERNE_EXPLICITE):
        return []
    return ["item de roadmap sans demande de savoir externe"]


def _modules_du_depot_cites(q: str) -> list:
    """Modules DU DEPOT que cite un objectif -- s'il en cite, le manque est INTERNE.

    MESURE 2026-09-25 (epreuve owner « comme un vrai medecin ») : le manque de rang 1 etait l'item
    NEXT de la roadmap, une autopsie de forge_acp_* / forge_a2a_*. Envoye en veille WEB, il a rendu
    « REUSSIE, ingerees 9 » -- et 35 chunks arXiv sur les mesons B et Navier-Stokes-« P1 » sont
    entres dans la base vivante. Le web ne documente pas le code de Nokido : ce manque-la se traite
    par enquete de code, et une veille n'y ajoute que du bruit. Seul un nom qui EXISTE sous app/ ou
    tools/ compte : citer un module imaginaire ne prouve rien.
    """
    vus: list = []
    for nom in _MODULE_CITE.findall(q or ""):
        nom = nom.lower()
        if nom in vus:
            continue
        for dossier in ("app", "tools"):
            try:
                if (ROOT / dossier / (nom + ".py")).is_file():
                    vus.append(nom)
                    break
            except OSError:  # muet-ok : dossier illisible = nom NON prouve interne, la veille reste possible
                continue
    return vus


def _demande_manuelle() -> Path:
    return ROOT / "sandbox" / "soif_examen.wanted"


def _marque_dernier_examen() -> Path:
    return ROOT / "sandbox" / "soif_dernier_examen"


def _decision_examen(besoin: int):
    """Motif de l'examen exteroceptif, ou None : on attend. Trois declencheurs.

    Une date ILLISIBLE ne declenche rien (on ne reveille pas 4,6 Go sur une mesure
    manquee) ; une marque ABSENTE declenche : aucun examen n'a jamais ete enregistre."""
    now = time.time()
    try:
        if now - _demande_manuelle().stat().st_mtime < DEMANDE_TTL_S:
            return "demande manuelle"
    except FileNotFoundError:
        pass    # muet-ok : demande absente = aucune demande, c'est l'etat nominal
    except OSError as e:
        _journal(f"demande manuelle ILLISIBLE ({type(e).__name__}) -- ignoree")
    if besoin >= SEUIL_EXAMEN:
        return f"seuil : {besoin} question(s) en attente >= {SEUIL_EXAMEN}"
    try:
        age = now - _marque_dernier_examen().stat().st_mtime
    except FileNotFoundError:
        return "aucun examen enregistre"
    except OSError as e:
        _journal(f"date du dernier examen ILLISIBLE ({type(e).__name__}) -- pas d'examen sur echeance")
        return None
    if age >= EXAMEN_MAX_AGE_S:
        return f"echeance : dernier examen il y a {age / 3600:.0f} h"
    return None


def _reveiller_piliers(attente_s=None):
    """(prets, detail) : reclame les piliers de l'examen ENSEMBLE, puis attend (borne).

    Le keeper passe environ toutes les 30 s et ne demarre rien au-dessus de son seuil
    RAM : des piliers muets a l'echeance veulent dire DIFFERE par la regulation."""
    import urllib.request as _u

    attente_s = ATTENTE_PILIERS_S if attente_s is None else attente_s
    try:
        from nokido_agent.app.forge_embed_router import declare_wanted

        poses = {f: bool(declare_wanted(f, motif="soif epistemique : examen exteroceptif"))
                 for f, _ in _PILIERS_EXAMEN if f}
    except Exception as e:  # noqa: BLE001 - l'intention non posee se DIT dans le detail
        poses = {"intention": "NON POSEE (%s)" % type(e).__name__}

    def _repond(url: str) -> bool:
        try:
            with _u.urlopen(url, timeout=3) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001 - muet-ok : un pilier muet est l'objet meme de l'attente
            return False

    fin = time.time() + attente_s
    while True:
        muets = [u.split("/")[2] for _, u in _PILIERS_EXAMEN if not _repond(u)]
        if not muets:
            return True, f"piliers prets (intentions : {poses})"
        if time.time() >= fin:
            return False, (f"piliers muets apres {attente_s:.0f} s : {', '.join(muets)} "
                           f"(intentions : {poses})")
        _beat(f"examen : attente des piliers ({', '.join(muets)})")
        time.sleep(10)


def run_once(conn: sqlite3.Connection) -> dict:
    conn.executescript(_SCHEMA)
    seen = {r[0] for r in conn.execute("SELECT query_hash FROM epistemic_seen")}
    rows = conn.execute(
        "SELECT DISTINCT query_text FROM query_log "
        "WHERE query_text IS NOT NULL AND length(query_text) > 8 "
        "ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()

    # L'intéroception S'AJOUTE à l'extéroception : le corps se pose aussi les
    # questions que ses propres douleurs soulèvent, et pas seulement celles qu'on
    # lui a posées. La déduplication par `epistemic_seen` reste en vigueur — une
    # même douleur ne relance donc pas une veille à chaque cycle (période
    # réfractaire : la cascade de re-tentatives identiques est une pathologie
    # nommée dans la grille, pas une vertu).
    _split = _interoceptive_split()
    _intention = _intentional_split()
    rows = list(rows) + [(q,) for q in _split["soif"]]
    for _item in _split["soin"]:
        _propose_care(_item)

    # PORTE DE L'EXAMEN (owner 2026-09-30) : l'interoception ci-dessus a tourne ; ce qui
    # suit reveille ~4,6 Go de piliers et n'a lieu que sur declencheur.
    besoin = sum(1 for (qt,) in rows
                 if hashlib.sha256(_norm(qt).encode()).hexdigest()[:16] not in seen)
    motif = _decision_examen(besoin)
    _sans_examen = {"examinees": 0, "gaps": 0, "veilles": 0, "hors_variete_ignores": 0,
                    "soif_intero": len(_split["soif"]), "soif_intention": len(_intention),
                    "intention_gap": None, "soin": len(_split["soin"]), "abstentions": {}}
    if motif is None:
        return dict(_sans_examen, examen=f"EN_ATTENTE : {besoin}/{SEUIL_EXAMEN} question(s) "
                                          f"en attente, ni demande ni echeance")
    prets, detail = _reveiller_piliers()
    if not prets:
        return dict(_sans_examen, examen=f"DIFFERE_PAR_REGULATION ({motif}) : {detail}")
    examen = f"FAIT ({motif})"

    examinees = gaps = veilles = hors_variete = 0
    # Abstentions PAR DEPENDANCE (2026-09-25) : un cycle qui n'examine rien parce qu'un
    # pilier est muet doit pouvoir le DIRE -- sinon il se confond avec un cycle sans
    # question, et l'organe passe pour mort (lecture fausse du 25/09 au matin).
    abstentions: dict = {}
    for (qt,) in rows:
        h = hashlib.sha256(_norm(qt).encode()).hexdigest()[:16]
        if h in seen:
            continue
        cov = ev.coverage_dense(qt)
        if not cov.get("ok"):
            _dep = cov.get("dependance") or "inconnue"
            abstentions[_dep] = abstentions.get(_dep, 0) + 1
            continue  # service muet -> on ne marque PAS vu (re-essai plus tard)
        examinees += 1
        conn.execute(
            "INSERT OR REPLACE INTO epistemic_seen VALUES (?,?,?,?,?)",
            (h, qt[:200], cov.get("verdict"), cov.get("score"), time.time()))
        conn.commit()
        if cov.get("gap") is True:
            # DESARME tant que le filtre hors-variete n'existe pas (AGY, 27-07,
            # et mesure concordante) : sur ces sources ARBITRAIRES, le seuil
            # absolu ne selectionne QUE du hors-sujet — blanquette -5.65 et
            # alpagas -8.68 franchissaient le plancher, System 3 etoile non.
            # Proposer ces "manques" polluerait le tableau noir de sujets qui ne
            # concernent pas Nokido. On COMPTE et on TRACE, on ne propose pas.
            hors_variete += 1
            continue
        if False:  # pragma: no cover — chemin conserve, re-arme avec le filtre PCA
            gaps += 1
            _propose_gap(qt, cov)
            if AUTO_VEILLE and veilles < MAX_VEILLES_CYCLE:
                try:
                    spec = ev.veille_on_gap(qt, domain="reference", run_now=True, max_rounds=2)
                    veilles += 1
                    print(f"[epistemic] VEILLE lancee sur gap: {qt[:60]} -> {str(spec)[:80]}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[epistemic] veille KO: {e}", flush=True)
    # ── INTENTION : decision par RANG, pas par seuil absolu ────────────────────
    # MESURE 2026-07-27 qui impose cette separation, et qui INVERSE l'intuition :
    #   hors-sujet « blanquette de veau »   -> -5.65  gap_certain
    #   hors-sujet « elevage d alpagas »    -> -8.68  gap_certain
    #   on-domaine NON su  (System 3 etoile)-> -1.45  abstention
    #   on-domaine SU      (governed_edit)  -> -0.67  abstention
    # Le plancher absolu a -5 ne selectionne donc QUE du hors-sujet : arme tel
    # quel, l'organe serait parti en veille sur la blanquette. C'est la lecon
    # « distance != pertinence » verifiee a hauteur de seuil — le plus distant du
    # corpus, c'est ce qui n'a rien a y faire.
    # Pour les questions d'INTENTION, on-domaine PAR CONSTRUCTION, le seuil
    # absolu n'a aucun sens : toutes vivent dans la bande on-domaine. Ce qui
    # compte est RELATIF — la moins couverte de ce que le corps VISE est ce
    # qu'il lui manque. Une seule par cycle : c'est un choix, pas une liste.
    # Garde : une intention qui tomberait SOUS le plancher est suspecte (elle se
    # comporte comme du hors-sujet), on l'ecarte plutot que de la suivre.
    intention_gap = None
    if _intention:
        notes = []
        for q in _intention:
            c = ev.coverage_dense(q)
            if c.get("ok") and c.get("score") is not None:
                notes.append((float(c["score"]), q, c))
            elif not c.get("ok"):
                _dep = c.get("dependance") or "inconnue"
                abstentions[_dep] = abstentions.get(_dep, 0) + 1
        plancher = getattr(ev, "_COVERAGE_GAP_FLOOR", -5.0)
        notes = [t for t in notes if t[0] > plancher]
        if notes:
            notes.sort(key=lambda t: t[0])
            score, q, cov = notes[0]
            h = hashlib.sha256(_norm(q).encode()).hexdigest()[:16]
            # REFRACTAIRE A DUREE, pas blocage definitif (correction d'AGY, 27-07,
            # retenue) : ma premiere version dedupliquait pour toujours, donc un
            # manque JAMAIS comble ne pouvait plus jamais etre souleve. Un sujet
            # traite se tait 48 h, puis redevient exigible s'il est encore le
            # moins couvert — l'oubli calibre est ce qui distingue une periode
            # refractaire d'une amnesie.
            _row = conn.execute(
                "SELECT seen_at FROM epistemic_seen WHERE query_hash=?", (h,)).fetchone()
            _recent = bool(_row and (time.time() - float(_row[0] or 0)) < _INTENTION_TTL_S)
            conn.execute("INSERT OR REPLACE INTO epistemic_seen VALUES (?,?,?,?,?)",
                         (h, q[:200], "gap_intention_rang", score, time.time()))
            conn.commit()
            _internes = _manque_interne(q)
            intention_gap = {"query": q, "score": score,
                             "sur": len(notes), "deja_vu": _recent,
                             "traitement": "INTERNE" if _internes else "VEILLE"}
            if not _recent:
                gaps += 1
                _propose_gap(q, dict(cov, verdict="gap_intention_rang"))
                _journal(f"gap INTENTION (rang 1/{len(notes)}, score {score}): {q[:120]}")
                if _internes:
                    # Le diagnostic choisit le remede (cf. _manque_interne) : on NOMME le bon
                    # traitement au lieu d'appliquer le seul dont on dispose.
                    _journal("veille NON lancee : manque INTERNE (preuves : %s) -- le web "
                             "ne documente pas le code de Nokido ; traitement = enquete de code "
                             "(introspect / forge_deep_explore), pas une veille" % ", ".join(_internes[:6]))
                elif AUTO_VEILLE and veilles < MAX_VEILLES_CYCLE:
                    try:
                        _spec = ev.veille_on_gap(q, domain="reference", run_now=True, max_rounds=2)
                        veilles += 1
                        _journal(f"veille lancee sur gap INTENTION: {q[:100]}")
                        _journal(f"veille ISSUE : {_issue_veille(_spec)}")
                    except Exception as e:  # noqa: BLE001
                        _journal(f"veille INTENTION KO: {type(e).__name__}: {e}")
            # PASSE A BLANC (decision owner 27-07, prealable a l'armement) : tant que la
            # veille auto n'est pas armee, on ECRIT ce qui SERAIT parti, avec de quoi en
            # juger — objectif exact, rang, score. Sans cette trace, decider d'armer
            # reviendrait a juger sur piece une veille que personne n'a jamais vue.
            # HORS du `if not _recent` (correction du meme jour, trouvee dans le LOG) :
            # imbriquee dedans, la trace se taisait des le 2e cycle, donc precisement
            # quand le manque PERSISTE — le cas qui merite le plus d'etre vu. On note
            # `deja_vu` au lieu de se taire. Le compteur `veilles` reste a zero : rien
            # n'est lance, rien n'est consomme.
            if not AUTO_VEILLE and not _internes:   # un manque interne ne SERAIT pas parti non plus
                _journal(
                    "veille A BLANC (NON lancee) — objectif: %s | domaine=reference "
                    "max_rounds=2 | rang 1/%d score %.3f | deja_vu=%s"
                    % (q[:160], len(notes), score, _recent))

    _res = {"examinees": examinees, "gaps": gaps, "veilles": veilles,
            "hors_variete_ignores": hors_variete,
            "soif_intero": len(_split["soif"]), "soif_intention": len(_intention),
            "intention_gap": intention_gap, "soin": len(_split["soin"]),
            "abstentions": abstentions, "examen": examen}
    # Examen tenu (piliers prets) : l'echeance repart de maintenant et la demande
    # manuelle est CONSOMMEE -- laissee, elle redeclencherait 4,6 Go a chaque cycle.
    try:
        _m = _marque_dernier_examen()
        _m.parent.mkdir(parents=True, exist_ok=True)
        _m.write_text(str(time.time()), encoding="utf-8")
        _demande_manuelle().unlink(missing_ok=True)
    except OSError as e:
        _journal(f"examen FAIT mais marque non ecrite ({type(e).__name__}) -- "
                 f"l'echeance pourrait redeclencher trop tot")

    # ── SÉRIE PERSISTÉE (2026-07-29) ────────────────────────────────────────
    # Sans elle, « la boucle de curiosité APPREND-elle ? » est indécidable. Le cycle
    # était journalisé en TEXTE : lisible par un humain, mais ni requêtable ni
    # comparable — personne ne pouvait donc dire si les gaps se REFERMENT. Mesure du
    # jour qui l'a rendu criant : 98 watch_jobs, 2540 chunks ingérés pour 210 retenus
    # (8,3 %), dont 23 jobs à rétention NULLE après avoir ingéré un millier de chunks.
    # Le compte de jobs ne dit pas si le manque diminue ; seule une série le dit.
    #
    # On réutilise l'appareil FEP déjà en place (`active_inference_signals`, Welford
    # incrémental + surprise) plutôt que d'ouvrir une n-ième table : `observe_signal`
    # répond exactement à « cette valeur est-elle normale ICI, MAINTENANT ».
    #
    # Ce qui devient enfin lisible :
    #   epistemic_gaps qui BAISSE       -> les veilles referment ce qu'elles ouvrent
    #   top_gap_score qui remonte vers 0 -> le manque de rang 1 se comble
    #   un z élevé                       -> dérive, SANS avoir eu à fixer un seuil
    #
    # Le score du gap de rang 1 est resté à -3.914 sur tous les cycles observés, avec
    # `deja_vu: True` : le corps redit le même manque sans que rien ne bouge. C'est
    # précisément ce qu'une série rend visible au lieu de le laisser dans un log.
    try:
        from nokido_agent.app.forge_active_inference import observe_signal

        observe_signal("epistemic_gaps", "global", float(gaps))
        observe_signal("epistemic_veilles", "global", float(veilles))
        _sc = (intention_gap or {}).get("score") if isinstance(intention_gap, dict) else None
        if isinstance(_sc, (int, float)):
            observe_signal("epistemic_top_gap_score", "global", float(_sc))
    except Exception as _e:  # noqa: BLE001 — la mesure ne casse JAMAIS le cycle
        _journal(f"serie non persistee: {type(_e).__name__}: {str(_e)[:80]}")

    return _res


def _journal(msg: str) -> None:
    """Trace sur DISQUE. Sans elle, la mort de l'organe ne laisse RIEN.

    Mesure 2026-07-27 : le service etait `stopped`, heartbeat vieux de 1h51, et
    AUCUN fichier de journal n'existait dans logs/ — impossible de savoir de quoi
    il etait mort. La sortie standard d'un service supervise ne suffit pas : elle
    n'est pas conservee. Un organe qui meurt doit pouvoir dire pourquoi.
    """
    ligne = "%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    # DEUX destinations, dans cet ordre. Le depot appartient au compte du
    # service ; un autre compte s'y voit REFUSER l'ecriture (mesure 2026-07-27 :
    # depuis le bac a sable, rien n'etait ecrit et le `except` avalait le refus
    # — l'instrumentation aurait ete aveugle la ou elle doit voir). C:/tmp est le
    # terrain commun lisible et inscriptible par tous les comptes : la trace y
    # survit quel que soit celui qui fait tourner l'organe.
    for p in (ROOT / "logs" / "epistemic_daemon.log", Path(r"C:/tmp/epistemic_daemon.log")):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(ligne)
            return
        except OSError:
            continue  # journal indisponible ne doit JAMAIS tuer l'organe


def _issue_veille(spec) -> str:
    """Une ligne qui dit l'ISSUE d'une veille, pas son lancement : REUSSIE / SANS EFFET / ECHEC.

    MESURE 2026-09-25 16:01 : le journal disait « veille lancee » et le resultat de veille_on_gap
    etait ignore -- impossible de savoir si le traitement avait agi (REQUESTED != ACHIEVED)."""
    if not isinstance(spec, dict):
        return "ECHEC -- retour illisible (%s)" % type(spec).__name__
    if not spec.get("ok"):
        return "ECHEC -- %s" % str(spec.get("error") or "sans motif")[:160]
    r = spec.get("result") or {}
    faits = "trouvees %s, ingerees %s, synthese %s, fournisseur %s" % (
        r.get("found"), r.get("ingested"), "OK" if r.get("synthesis_ok") else "KO", r.get("llm_provider"))
    erreurs = "; ".join(str(e)[:60] for e in (r.get("search_errors") or [])[:3])
    if not r.get("ingested") and not r.get("synthesis_ok"):
        return "SANS EFFET -- %s%s" % (faits, (" | erreurs : " + erreurs) if erreurs else "")
    return "REUSSIE -- %s%s" % (faits, (" | erreurs : " + erreurs) if erreurs else "")


def _transition_blocage(etat, res):
    """(nouvel_etat, ligne|None) : le journal dit les TRANSITIONS de blocage, sans bruit.

    Un cycle qui n'examine rien parce qu'un pilier est muet ne se taisait pas moins qu'un
    cycle sans question : l'organe passait pour mort (25/09). On ecrit a l'ENTREE dans un
    blocage (ou quand la dependance en cause change), puis a la SORTIE -- rien tant que
    l'etat tient, pour ne pas noyer le journal d'une ligne toutes les 15 min."""
    if not str(res.get("examen") or "FAIT").startswith("FAIT"):
        # Cycle SANS examen (en attente, ou differe par la regulation) : il ne dit rien
        # des dependances -- ni blocage, ni deblocage. Sans ce garde, le premier cycle
        # en attente ecrivait « DEBLOQUE -- examen repris » alors qu'aucun examen
        # n'avait lieu.
        return etat, None
    ab = res.get("abstentions") or {}
    sig = ", ".join(sorted(ab)) if (not res.get("examinees") and ab) else None
    if sig == etat:
        return etat, None
    if sig:
        return sig, ("BLOQUE_PAR_DEPENDANCE %s (%d abstention(s) ce cycle) -- l'organe VIT, "
                     "il ne peut pas examiner" % (sig, sum(ab.values())))
    return None, "DEBLOQUE (etait : %s) -- examen repris" % etat


def run(interval: int, once: bool) -> int:
    conn = sqlite3.connect(db_path(), timeout=60)
    print(f"[epistemic] soif de connaissance — auto_veille={AUTO_VEILLE} cap={MAX_VEILLES_CYCLE}", flush=True)
    _journal(f"demarrage — auto_veille={AUTO_VEILLE} cap={MAX_VEILLES_CYCLE} interval={interval}")
    echecs = 0
    etat_blocage = None
    etat_examen = None

    def _dormir(total: float) -> None:
        # Dormir par tranches en BATTANT : le heartbeat dit VIVANT, pas productif.
        # Mesure 2026-07-31 (laforge-master.log) : beat 1x/cycle + sleep(900) d'un
        # bloc > seuil 600 s du tier normal -> SIGTERM superviseur a chaque tour
        # (~630 s), organe flappant depuis le 29/07, jamais arrive a son 2e cycle.
        fin = time.time() + total
        while True:
            reste = fin - time.time()
            if reste <= 0:
                return
            time.sleep(min(60.0, reste))
            _beat(f"dormant — prochain cycle dans {int(max(0, fin - time.time()))}s")

    while True:
        # GARDE DE BOUCLE : la moindre exception d'un cycle sortait de `while` et
        # TUAIT le processus — definitivement, et en silence. Or les dependances
        # de cet organe (embedder 8099, reranker 8100, Qdrant 6333) sont
        # on-demand et s'endorment sous pression RAM PAR CONCEPTION : la
        # regulation du corps pouvait donc tuer sa propre soif d'apprendre.
        # Un cycle rate est un incident, pas une raison de mourir.
        try:
            r = run_once(conn)
            if echecs:
                _journal(f"retabli apres {echecs} cycle(s) en echec")
            echecs = 0
        except Exception as exc:  # noqa: BLE001
            import traceback as _tb

            echecs += 1
            _journal(f"cycle KO #{echecs} {type(exc).__name__}: {exc}\n{_tb.format_exc()}")
            _beat(f"cycle KO #{echecs} ({type(exc).__name__}) — organe vivant, reprise au prochain tour")
            try:  # la connexion peut etre la victime : on la renouvelle
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = sqlite3.connect(db_path(), timeout=60)
            if once:
                return 4
            # Recul croissant plafonne : ne pas marteler une dependance endormie.
            _dormir(min(max(60, interval) * min(echecs, 4), 3600))
            continue
        etat_blocage, _ligne_blocage = _transition_blocage(etat_blocage, r)
        if _ligne_blocage:
            _journal(_ligne_blocage)
        # Le journal dit chaque examen FAIT et chaque ENTREE en attente ou en report,
        # pas la repetition d'une attente toutes les 15 min.
        _ex = str(r.get("examen") or "")
        _genre = _ex.split(" ", 1)[0]
        if _ex and (_genre == "FAIT" or _genre != etat_examen):
            _journal(f"examen {_ex}")
        etat_examen = _genre or etat_examen
        _beat(f"examinees {r['examinees']} (soif intero {r.get('soif_intero', 0)}), "
          f"gaps {r['gaps']}, veilles {r['veilles']}, soin {r.get('soin', 0)}"
          + (f", BLOQUE {etat_blocage}" if etat_blocage else "")
          + (f", examen {_genre}" if _genre else ""))
        if r["examinees"] or r["gaps"]:
            print(f"[epistemic] cycle: {r}", flush=True)
            _journal(f"cycle: {r}")
        if once:
            conn.close()
            print(f"[epistemic] once: {r}", flush=True)
            return 0
        _dormir(max(60, interval))


def main() -> int:
    ap = argparse.ArgumentParser(description="Soif de connaissance : detecte les gaps RAG et propose/veille")
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--examiner", action="store_true",
                    help="demande MANUELLE d'un examen exteroceptif : pose "
                         "sandbox/soif_examen.wanted (valable 6 h) et rend la main ; "
                         "le demon l'execute a son prochain cycle")
    a = ap.parse_args()
    if a.examiner:
        p = _demande_manuelle()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()), encoding="utf-8")
        print(f"[epistemic] examen demande : {p} (valable {DEMANDE_TTL_S // 3600} h, "
              f"execute au prochain cycle du demon)", flush=True)
        return 0
    return run(a.interval, a.once)


if __name__ == "__main__":
    sys.exit(main())
