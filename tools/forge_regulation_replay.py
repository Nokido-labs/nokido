# -*- coding: utf-8 -*-
"""Simulateur de REJEU de la regulation RAM de Nokido (GO owner 28/10) -- prealable a l'optimisation des seuils.

Un banc d'ordonnancement avait un simulateur exact ; Nokido n'en a pas. Ce module rejoue une FENETRE de
journal (vitaux, ordres au superviseur, audit du cycle de vie) en appelant le CODE EXISTANT de la regulation :

  * le tick Hamilton REEL (`forge_resource_manager._regulation_hamilton_tick`), qui appelle lui-meme
    `plan_hamilton`, `ordre_delestage`, `classe_hamilton`, `palier_pression_ram`, `regulation_hamilton_ram`,
    `gestes_observes` ;
  * le plancher RAM 60 s REEL (`_noter_ram_fenetre`), alimente echantillon par echantillon ;
  * le delai de grace Docker REEL (`forge_docker_keeper.delai_de_grace`).

Rien de cette logique n'est recopie ici : seules les ENTREES du tick (snapshot, registre, verdict, vetos, horloge,
etat des pauses) et ses SORTIES (ordres, hormone, audit) sont branchees sur le rejeu, le temps du rejeu, puis
restaurees. Les seuils sont INJECTES de la meme facon (attributs du module, variable d'environnement lue a l'appel).

AUCUN ETAT VIVANT : pas de get_snapshot, pas d'ordre superviseur, pas d'hormone, pas d'audit, pas de fichier d'etat
(l'etat des pauses vit en memoire). Le rejeu REFUSE de tourner dans un processus ou l'echantillonneur est vivant
(le hub) : les remplacements de module y toucheraient la regulation reelle.

BOUCLE OUVERTE (limite majeure, dite dans `cout`) : la RAM rejouee est celle OBSERVEE ; l'effet d'un sommeil
simule sur la RAM n'est pas modelise. Le modele du superviseur se borne a : SUSPENDRE retire le service du
registre, REPRENDRE l'y remet.

Usage (lecture seule, sortie JSON sur stdout) :
    python tools/forge_regulation_replay.py --racine <depot> --debut 2026-10-28T08:45:00Z --fin 2026-10-28T09:20:00Z
"""
from __future__ import annotations

__FORGE_COLOR__ = "regulation/rejeu : simulateur de rejeu de la regulation RAM sur journal, seuils injectes"

import argparse
import collections
import contextlib
import datetime as _dt
import hashlib
import io
import json
import logging
import os
import re
import statistics
import sys
import time as _time_reel
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_resource_manager as rm  # noqa: E402

log = logging.getLogger("forge_regulation_replay")

# Seuil injectable -> (genre, cible). "attr" : attribut du module lu a l'appel ; "env" : variable lue a l'appel.
SEUILS = {
    "seuil_sommeil": ("attr", "_SUPERVISOR_SLEEP_RAM_THRESHOLD"),
    "cible": ("attr", "_HAMILTON_CIBLE_PCT"),
    "gene_pct": ("attr", "_PALIER_GENE_PCT"),
    "critique_libre_gb": ("attr", "_CRITIQUE_LIBRE_GB"),
    "detresse_libre_gb": ("env", "LAFORGE_DETRESSE_LIBRE_GB"),
    "pause_max_s": ("attr", "_HAMILTON_PAUSE_MAX_S"),
    "calme_min_s": ("attr", "_HAMILTON_CALME_MIN_S"),
    "rechute_fenetre_s": ("attr", "_HAMILTON_RECHUTE_FENETRE_S"),
    "fenetre_ram_s": ("attr", "_RAM_FENETRE_S"),
    # 31/10 : reprise utile dans un budget RAM (0 = politique d'avant, pour rejouer une fenetre passee fidelement)
    "reprise_budget": ("env", "NOKIDO_HAMILTON_REPRISE_BUDGET"),
    "marge_reprise_pct": ("attr", "_HAMILTON_MARGE_REPRISE_PCT"),
    "poids_inconnu_mb": ("attr", "_HAMILTON_POIDS_INCONNU_MB"),
    # 7/11 : gardes anti-oscillation (0 / tres grand = politique d'avant, pour rejouer une fenetre passee fidelement)
    "gain_min_mb": ("attr", "_HAMILTON_GAIN_MIN_MB"),
    "reprise_lot": ("attr", "_HAMILTON_REPRISE_LOT"),
    "sommeil_min_s": ("attr", "_HAMILTON_SOMMEIL_MIN_S"),
}
GESTES_ORDONNES = ("SUSPENDRE", "REPRENDRE")
_RE_VERDICT = re.compile(r"pression (SOI|NON_SOI|NOYAU|INCERTAIN)\b")
_RE_TS_EPOCH = re.compile(r'\{"ts":\s*([0-9]+(?:\.[0-9]+)?)')
_RE_BESOIN = re.compile(r"pour (\d+) Mo a rendre")
_RE_CEDES = re.compile(r"(\d+) service\(s\) pour")


def est_executeur(service: str) -> bool:
    return "TaskExecutor" in str(service)


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(float(t), _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _epoch(iso: str) -> float:
    return _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------------------------------------------------------
# Lecture du journal (lecture seule ; toute ligne illisible est COMPTEE, jamais avalee)
# ---------------------------------------------------------------------------------------------------------------

def _lire_vitaux(chemin: Path, t0: float, t1: float, rejets: collections.Counter) -> list:
    out = []
    if not chemin.exists():
        rejets[chemin.name + " (absent)"] += 1
        return out
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            m = _RE_TS_EPOCH.match(ligne)
            if not m:
                rejets[chemin.name] += 1
                continue
            ts = float(m.group(1))
            if ts < t0 or ts > t1:
                continue
            try:
                d = json.loads(ligne)
            except ValueError:
                rejets[chemin.name] += 1
                continue
            out.append({"ts": ts, "ram_pct": d.get("ram_pct"), "ram_free_gb": d.get("ram_free_gb"),
                        "ram_used_gb": d.get("ram_used_gb")})
    out.sort(key=lambda s: s["ts"])
    return out


def _lire_jsonl_iso(chemin: Path, t0: float, t1: float, rejets: collections.Counter) -> list:
    out = []
    if not chemin.exists():
        rejets[chemin.name + " (absent)"] += 1
        return out
    with open(chemin, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            if not ligne.strip():
                continue
            try:
                d = json.loads(ligne)
                ts = _epoch(d["ts"])
            except (ValueError, KeyError, TypeError):
                rejets[chemin.name] += 1
                continue
            if t0 <= ts <= t1:
                d["_t"] = ts
                out.append(d)
    out.sort(key=lambda d: d["_t"])
    return out


def _geste_d_un_ordre(chemin: str) -> tuple:
    """(geste, service) d'un ordre RESOURCE_MANAGER au superviseur, sinon (None, None)."""
    parties = [p for p in str(chemin).split("/") if p]
    if len(parties) >= 3 and parties[0] == "supervisor":
        if parties[1] == "sleep":
            return "SUSPENDRE", parties[2]
        if parties[1] == "wake":
            return "REPRENDRE", parties[2]
        if parties[1:3] == ["service", "start"] and len(parties) >= 4:
            return "REPRENDRE", parties[3]  # route de reveil actuelle (_url_reveil)
    return None, None


def lire_fenetre(racine, t0: float, t1: float, marge_avant_s: float = 120.0) -> dict:
    """Lit la fenetre [t0, t1] (UTC epoch) du journal de `racine`. Lecture seule.

    Rend vitaux (avec `marge_avant_s` d'amorce pour le plancher), decisions journalisees (ordres RESOURCE_MANAGER,
    hors evictions reconnues par l'audit), evictions, verdicts d'attribution lus dans les motifs, evenements
    Docker, refus de sommeil (vetos), motifs Hamilton, et le compte des lignes rejetees par fichier."""
    racine = Path(racine)
    sb = racine / "sandbox"
    rejets: collections.Counter = collections.Counter()
    vitaux = _lire_vitaux(sb / "vitals_history.jsonl", t0 - marge_avant_s, t1, rejets)
    ordres = _lire_jsonl_iso(sb / "supervisor_ordres.jsonl", t0, t1, rejets)
    audit = _lire_jsonl_iso(sb / "lifecycle_actions.jsonl", t0 - marge_avant_s, t1 + 60.0, rejets)

    def _cible(d):
        return str((d.get("extra") or {}).get("target") or d.get("target") or "")

    evict_sleep = [(d["_t"], _cible(d)) for d in audit if d.get("domain") == "service" and d.get("action") == "sleep"]
    signatures = [(d["_t"], str(d.get("reason") or "")) for d in audit if d.get("action") == "hamilton_arme"]
    decisions, hors_hamilton = [], []
    for o in ordres:
        if o.get("agent_declare") != "RESOURCE_MANAGER":
            continue
        geste, svc = _geste_d_un_ordre(o.get("chemin", ""))
        if not geste:
            continue
        ev = {"ts": o["_t"], "iso": _iso(o["_t"]), "service": svc, "geste": geste, "chemin": o.get("chemin")}
        if geste == "SUSPENDRE" and any(s == svc and abs(t - o["_t"]) <= 20.0 for t, s in evict_sleep):
            ev["origine"] = "eviction auditee (request_resources, non simulee)"
            hors_hamilton.append(ev)
            continue
        if geste == "SUSPENDRE":
            # Signature du tick : le tick Hamilton audite APRES ses ordres. Si le premier audit Hamilton qui suit
            # (<= 120 s) n'annonce aucun service cede, ce sommeil vient d'un autre chemin (eviction cumulee...).
            # Aucun audit dans les 120 s : non attribuable -> garde comme decision Hamilton (prudent : compte contre
            # la fidelite, jamais pour).
            suivant = next(((t, m) for t, m in signatures if 0.0 <= t - o["_t"] <= 120.0), None)
            if suivant is not None:
                n = _RE_CEDES.search(suivant[1])
                if not n or int(n.group(1)) == 0:
                    ev["origine"] = "autre chemin que le tick Hamilton (audit Hamilton suivant %s : %s)" % (
                        _iso(suivant[0]), suivant[1][:80])
                    hors_hamilton.append(ev)
                    continue
        decisions.append(ev)
    verdicts, docker, refus, hamilton = [], [], [], []
    for d in audit:
        raison = str(d.get("reason") or "")
        if d.get("action") in ("hamilton_arme", "pression_hors_corps"):
            m = _RE_VERDICT.search(raison)
            if m:
                verdicts.append((d["_t"], m.group(1), d.get("action")))
        if d.get("action") == "hamilton_arme":
            hamilton.append({"ts": d["_t"], "iso": _iso(d["_t"]), "motif": raison})
        if d.get("domain") == "docker" and d.get("action") in ("want", "release", "start"):
            docker.append({"ts": d["_t"], "action": d.get("action"), "motif": raison[:160]})
        if d.get("action") == "sleep_refused":
            refus.append({"ts": d["_t"], "service": _cible(d), "motif": raison[:160]})
    return {"racine": str(racine), "t0": t0, "t1": t1, "vitaux": vitaux, "decisions_journal": decisions,
            "hors_hamilton_journal": hors_hamilton, "verdicts": verdicts, "docker": docker, "refus_sommeil": refus,
            "hamilton_journal": hamilton, "rejets": dict(rejets),
            "phase_journal": int(decisions[0]["ts"]) if decisions else None}


# ---------------------------------------------------------------------------------------------------------------
# Bac de rejeu : branche les entrees/sorties du tick reel, injecte les seuils, restaure tout
# ---------------------------------------------------------------------------------------------------------------

class _Horloge:
    """Remplace le module `time` de forge_resource_manager le temps du rejeu : time() rend l'heure simulee."""

    def __init__(self, t: float):
        self.t = float(t)

    def time(self) -> float:
        return self.t

    def __getattr__(self, nom):
        return getattr(_time_reel, nom)


class _EtatEnMemoire:
    """Tient lieu de sandbox/hamilton_pauses_ram.json : l'etat des pauses ne touche jamais le disque."""

    def __init__(self, etat: dict | None):
        self.texte = json.dumps(etat) if etat else None
        self.parent = self

    def exists(self) -> bool:
        return self.texte is not None

    def read_text(self, encoding=None) -> str:
        return self.texte or "{}"

    def write_text(self, texte, encoding=None) -> int:
        self.texte = texte
        return len(texte)

    def mkdir(self, parents=False, exist_ok=False) -> None:
        return None


def seuils_actuels() -> dict:
    out = {}
    for nom, (genre, cible) in SEUILS.items():
        if genre == "attr":
            out[nom] = float(getattr(rm, cible))
        else:
            brut = os.environ.get(cible)
            out[nom] = float(brut) if brut is not None else "defaut du code (%s non pose)" % cible
    return out


@contextlib.contextmanager
def _bac(remplacements: dict, seuils: dict):
    """Pose remplacements + seuils sur le module, et RESTAURE tout en sortie (meme sur exception)."""
    if getattr(rm, "_SAMPLER_THREAD", None) is not None and rm._SAMPLER_THREAD.is_alive():
        raise RuntimeError("rejeu REFUSE : l'echantillonneur de forge_resource_manager vit dans ce processus "
                           "(hub ?) -- remplacer ses attributs toucherait la regulation reelle")
    inconnus = set(seuils) - set(SEUILS)
    if inconnus:
        raise ValueError("seuil(s) inconnu(s) : %s (connus : %s)" % (sorted(inconnus), sorted(SEUILS)))
    absent = object()
    sauves, env_sauves = {}, {}
    try:
        for nom, val in remplacements.items():
            sauves[nom] = getattr(rm, nom, absent)
            setattr(rm, nom, val)
        for nom, val in seuils.items():
            genre, cible = SEUILS[nom]
            if genre == "attr":
                if cible not in sauves:
                    sauves[cible] = getattr(rm, cible, absent)
                setattr(rm, cible, float(val))
            else:
                env_sauves[cible] = os.environ.get(cible)
                os.environ[cible] = str(float(val))
        yield
    finally:
        for nom, val in sauves.items():
            if val is absent:
                delattr(rm, nom)
            else:
                setattr(rm, nom, val)
        for cible, val in env_sauves.items():
            if val is None:
                os.environ.pop(cible, None)
            else:
                os.environ[cible] = val


def _verdict_au(t: float, verdicts: list, defaut: str, fenetre_s: float, maintien_s: float = 0.0) -> tuple:
    """Verdict d'attribution au tick : journalise a +/- fenetre_s ; sinon, SUR DEMANDE (maintien_s > 0), le dernier
    verdict journalise s'il a moins de maintien_s ; sinon le defaut (hypothese, dite par la source)."""
    proches = [(abs(ts - t), v) for ts, v, _src in verdicts if abs(ts - t) <= fenetre_s]
    if proches:
        return min(proches)[1], "journal"
    if maintien_s > 0:
        avant = [(ts, v) for ts, v, _src in verdicts if 0.0 <= t - ts <= maintien_s]
        if avant:
            return max(avant)[1], "maintien du verdict journalise a %s" % _iso(max(avant)[0])
    return defaut, "defaut (verdict d'attribution non journalise a ce tick)"


def _policy_id() -> str:
    try:
        return "forge_resource_manager@" + hashlib.sha1(Path(rm.__file__).read_bytes()).hexdigest()[:10]
    except OSError as e:
        return "forge_resource_manager@ILLISIBLE(%s)" % type(e).__name__


def rejouer(fen: dict, toml=None, seuils: dict | None = None, phase_ts: float | None = None,
            periode_s: float = 60.0, latence_s: float = 3.0, vivants=None, rss_mb: dict | None = None,
            vetos: dict | None = None, verdict_defaut: str = "SOI", verdict_fenetre_s: float = 60.0,
            etat_initial: dict | None = None, verdict_maintien_s: float = 0.0, demandes: dict | None = None) -> dict:
    """Rejoue les ticks Hamilton sur la fenetre `fen` (cf lire_fenetre) avec des seuils injectes.

    Ticks : phase_ts + k*periode_s dans [t0, t1] (cadence reelle : >= 60 s, thread lance par le sampler ; les
    ticks SANS geste ne sont pas journalises -- la phase est donc un parametre, par defaut le premier ordre
    journalise). Snapshot du tick = dernier echantillon de vitaux <= tick - latence_s, plancher 60 s calcule par
    `_noter_ram_fenetre` reel sur les echantillons rejoues. Registre = `vivants` (defaut : services du TOML non
    `disabled` -- le registre reel n'est PAS journalise), modele superviseur SUSPENDRE->retire / REPRENDRE->remis.
    rss_mb : {service: Mo} (defaut : ILLISIBLE -> None, comme une memoire privee illisible)."""
    seuils = dict(seuils or {})
    rss_mb = dict(rss_mb or {})
    vetos = dict(vetos or {})
    # 31/10 : la demande d'un service (taches de son agent) n'est PAS journalisee -- le rejeu ne lit jamais le tasks.db
    # vivant (une fenetre passee jugee avec la file d'aujourd'hui) ; defaut INCONNU (None), sinon {service: bool}.
    demandes = dict(demandes or {})
    t0, t1 = float(fen["t0"]), float(fen["t1"])
    echantillons = [s for s in fen["vitaux"] if s.get("ram_pct") is not None]
    horloge = _Horloge(t0)
    etat = _EtatEnMemoire(etat_initial)
    capture = {"ordres": [], "paliers": [], "audits": []}
    registre_courant: dict = {}
    verdict_courant = [verdict_defaut]
    fenetre_ram: collections.deque = collections.deque(maxlen=256)
    snapshot: dict = {}
    remplacements = {
        "time": horloge,
        "_SNAPSHOT": snapshot,
        "_RAM_FENETRE": fenetre_ram,
        "_HAMILTON_ETAT_RAM_PATH": etat,
        "_dernier_palier_publie": [None, 0.0],
        "_registre_corps": lambda: dict(registre_courant),
        "_memoire_privee_mb": lambda pid: rss_mb.get(next((s for s, p in registre_courant.items() if p == pid), "")),
        "attribuer_pression": lambda *a, **k: {"verdict": verdict_courant[0], "raison": "rejeu"},
        "vetos_sommeil_actifs": lambda maintenant=None: dict(vetos),
        "_demande_du_service": lambda svc: demandes.get(svc),
        # 7/11 : plan_hamilton epargne un executeur dont la file est en vol en lisant le tasks.db VIVANT -- une
        # fenetre passee jugee avec la file d'aujourd'hui (mesure : le rejeu du 28/10 n'endormait plus que
        # l'executeur generique des qu'une tache tournait). Le travail en vol n'est pas journalise : oisif.
        "_travail_en_vol": lambda svc: [],
        "publier_palier_pression": lambda palier: capture["paliers"].append(palier) or True,
        "_ordre_superviseur": lambda svc, geste: capture["ordres"].append((svc, geste)),
        "_audit_lifecycle": lambda action, domain, reason="", **extra: capture["audits"].append(reason),
    }
    if toml is not None:
        remplacements["_SERVICES_TOML"] = Path(toml)
    ticks, decisions = [], []
    ticks_illisibles = 0
    with _bac(remplacements, seuils):
        seuils_effectifs = seuils_actuels()
        decl = rm._services_du_toml()
        if decl is None:
            raise RuntimeError("services.toml ILLISIBLE (%s) : aucun plan rejouable" % rm._SERVICES_TOML)
        if vivants is None:
            vivants = [n for n, d in decl.items() if not d.get("disabled")]
        en_vie = set(vivants)
        endormis: set = set()
        if not echantillons:
            raise RuntimeError("aucun echantillon de vitaux dans la fenetre : rien a rejouer")
        debut = max(t0, echantillons[0]["ts"] + latence_s)
        phase = float(phase_ts) if phase_ts is not None else debut + periode_s
        k0 = -int((phase - debut) // periode_s) if phase > debut else 0
        k = k0
        i_ech = 0
        while True:
            t = phase + k * periode_s
            k += 1
            if t > t1:
                break
            if t < debut:
                continue
            # alimente le plancher 60 s REEL avec les echantillons disponibles a ce tick
            dernier = None
            while i_ech < len(echantillons) and echantillons[i_ech]["ts"] <= t - latence_s:
                s = echantillons[i_ech]
                i_ech += 1
                used, pct = s.get("ram_used_gb"), s.get("ram_pct")
                snap = {"ts": s["ts"], "ram_pct": pct, "ram_free_gb": s.get("ram_free_gb"),
                        "ram_total_gb": (float(used) / float(pct) * 100.0) if used and pct else None}
                rm._noter_ram_fenetre(snap)
                dernier = snap
            if dernier is not None:
                snapshot.clear()
                snapshot.update(dernier)
            if not snapshot:
                continue
            horloge.t = t
            registre_courant.clear()
            registre_courant.update({svc: 10000 + i for i, svc in enumerate(sorted(en_vie))})
            verdict_courant[0], source_verdict = _verdict_au(t, fen.get("verdicts") or [], verdict_defaut,
                                                             verdict_fenetre_s, verdict_maintien_s)
            capture["ordres"].clear()
            capture["paliers"].clear()
            rm._dernier_palier_publie[:] = [None, 0.0]  # publie a chaque tick : le palier du tick est capture
            r = rm._regulation_hamilton_tick()
            motif = str(r.get("motif"))
            if "ILLISIBLE" in motif:
                ticks_illisibles += 1
                log.warning("[rejeu] tick %s : %s", _iso(t), motif)
            for svc, geste in capture["ordres"]:
                if geste == "SUSPENDRE":
                    en_vie.discard(svc)
                    endormis.add(svc)
                elif geste == "REPRENDRE":
                    en_vie.add(svc)
                    endormis.discard(svc)
                if geste in GESTES_ORDONNES:
                    decisions.append({"ts": t, "iso": _iso(t), "service": svc, "geste": geste, "motif": motif,
                                      "ram_decision": snapshot.get("ram_pct_plancher_60s", snapshot.get("ram_pct")),
                                      "palier": capture["paliers"][-1] if capture["paliers"] else "NON_PUBLIE"})
            ticks.append({"ts": t, "iso": _iso(t), "echantillon_age_s": round(t - float(snapshot["ts"]), 1),
                          "ram_instant": snapshot.get("ram_pct"),
                          "ram_decision": snapshot.get("ram_pct_plancher_60s", snapshot.get("ram_pct")),
                          "couverture_s": snapshot.get("ram_fenetre_couverture_s"),
                          "libre_gb": snapshot.get("ram_free_gb"), "total_gb": snapshot.get("ram_total_gb"),
                          "palier": capture["paliers"][-1] if capture["paliers"] else "NON_PUBLIE",
                          "verdict": verdict_courant[0], "source_verdict": source_verdict, "motif": motif,
                          "gestes": dict(r.get("gestes") or {}), "n_choisis": len(r.get("choisis") or []),
                          "vivants": sorted(en_vie), "endormis": sorted(endormis)})
    return {"t0": t0, "t1": t1, "ticks": ticks, "decisions": decisions, "seuils": seuils_effectifs,
            "ticks_illisibles": ticks_illisibles, "policy_id": _policy_id(),
            "parametres": {"phase_ts": phase, "periode_s": periode_s, "latence_s": latence_s,
                           "verdict_defaut": verdict_defaut, "verdict_fenetre_s": verdict_fenetre_s,
                           "verdict_maintien_s": verdict_maintien_s,
                           "toml": str(toml) if toml is not None else str(rm._SERVICES_TOML),
                           "vivants_initiaux": len(vivants), "rss_mb_fournis": len(rss_mb),
                           "vetos_fournis": sorted(vetos)}}


# ---------------------------------------------------------------------------------------------------------------
# Fidelite : concordance rejeu / journal, chaque ecart nomme
# ---------------------------------------------------------------------------------------------------------------

def _cause(ev: dict, cote: str, fen: dict | None) -> tuple:
    """(code, cause probable) d'une decision non appariee. PROBABLE : l'explication definitive est dans le rapport."""
    svc, geste = ev["service"], ev["geste"]
    refus = [r for r in (fen or {}).get("refus_sommeil", []) if r["service"] == svc and abs(r["ts"] - ev["ts"]) <= 900]
    if cote == "absent_du_journal":
        if geste == "SUSPENDRE" and refus:
            return "VETO_TEMOIGNE", ("veto de sommeil probable (sleep_refused a %s ; historique des vetos ILLISIBLE, "
                                     "rejeu sans veto)" % _iso(refus[0]["ts"]))
        if geste == "SUSPENDRE":
            return "SOMMEIL_EN_TROP", ("le rejeu endort un service que le reel n'a pas endormi : registre reel ou "
                                       "intention au tick (ILLISIBLES), verdict suppose, ou plancher reconstruit "
                                       "au-dessus du reel (vitaux a 15 s, sampler a 3 s)")
        return "REPRISE_EN_TROP", "reprise simulee sans reprise journalisee : sommeil reel absent ou calme decale"
    if geste == "SUSPENDRE":
        return "PRESSION_NON_VUE", ("le rejeu n'a pas vu la pression a ce tick : plancher reconstruit sous le seuil, "
                                    "verdict non SOI, ou service hors du registre simule")
    return "REPRISE_NON_REPRODUITE", "reprise journalisee non reproduite : sommeil non simule, ou calme decale"


def concordance(rejeu: list, journal: list, tolerance_s: float = 45.0, filtre=None, fen: dict | None = None) -> dict:
    """Apparie les decisions (service, geste) du rejeu et du journal a +/- tolerance_s (glouton, ordre chronologique).

    concordance = 2*apparies / (n_rejeu + n_journal) (1.0 si les deux sont vides) ; precision, rappel ;
    chaque decision non appariee porte sa cause probable."""
    garder = filtre or (lambda svc: True)
    rj = sorted([d for d in rejeu if d["geste"] in GESTES_ORDONNES and garder(d["service"])], key=lambda d: d["ts"])
    jn = sorted([d for d in journal if d["geste"] in GESTES_ORDONNES and garder(d["service"])], key=lambda d: d["ts"])
    libres = list(range(len(rj)))
    apparies, absents_rejeu = [], []
    for j in jn:
        meilleur = None
        for i in libres:
            r = rj[i]
            if r["service"] == j["service"] and r["geste"] == j["geste"] and abs(r["ts"] - j["ts"]) <= tolerance_s:
                if meilleur is None or abs(r["ts"] - j["ts"]) < abs(rj[meilleur]["ts"] - j["ts"]):
                    meilleur = i
        if meilleur is None:
            code, cause = _cause(j, "absent_du_rejeu", fen)
            absents_rejeu.append(dict(j, code=code, cause=cause))
        else:
            libres.remove(meilleur)
            apparies.append({"service": j["service"], "geste": j["geste"], "ts_journal": j["ts"],
                             "ts_rejeu": rj[meilleur]["ts"], "delta_s": round(rj[meilleur]["ts"] - j["ts"], 1)})
    absents_journal = []
    for i in libres:
        code, cause = _cause(rj[i], "absent_du_journal", fen)
        absents_journal.append(dict(rj[i], code=code, cause=cause))
    n_r, n_j, m = len(rj), len(jn), len(apparies)
    return {"n_rejeu": n_r, "n_journal": n_j, "n_apparies": m,
            "concordance": 1.0 if n_r + n_j == 0 else round(2.0 * m / (n_r + n_j), 4),
            "precision": round(m / n_r, 4) if n_r else None, "rappel": round(m / n_j, 4) if n_j else None,
            "tolerance_s": tolerance_s, "apparies": apparies, "absents_du_rejeu": absents_rejeu,
            "absents_du_journal": absents_journal}


def ram_impliquee(motif: str, total_gb: float, cible_pct: float) -> float | None:
    """RAM de decision IMPLIQUEE par un motif Hamilton journalise (« pour N Mo a rendre ») : controle du signal."""
    m = _RE_BESOIN.search(str(motif))
    if not m or not total_gb:
        return None
    return round(float(cible_pct) + float(m.group(1)) / (float(total_gb) * 1024.0) * 100.0, 2)


# ---------------------------------------------------------------------------------------------------------------
# Inventaire des signaux d'entree : ce qui est journalise, a quelle cadence ; le reste est ILLISIBLE
# ---------------------------------------------------------------------------------------------------------------

def inventorier_signaux(racine, t0: float, t1: float, fen: dict | None = None) -> list:
    fen = fen or lire_fenetre(racine, t0, t1)
    sb = Path(racine) / "sandbox"
    vit = [s["ts"] for s in fen["vitaux"] if t0 <= s["ts"] <= t1]
    ecarts = [b - a for a, b in zip(vit, vit[1:])]
    cad = round(statistics.median(ecarts), 1) if ecarts else None
    sans_couv = round(max(ecarts), 1) if ecarts else None
    n_intents = 0
    chemin_audit = sb / "lifecycle_actions.jsonl"
    intents_note = "non lu"
    if chemin_audit.exists():
        intents_note = "dict « intents actifs » dans les motifs docker pause_skipped (seulement quand le keeper " \
                       "tente une pause)"
        with open(chemin_audit, encoding="utf-8", errors="replace") as f:
            for ligne in f:
                if "intents actifs" in ligne:
                    try:
                        if t0 <= _epoch(json.loads(ligne)["ts"]) <= t1:
                            n_intents += 1
                    except (ValueError, KeyError, TypeError) as e:
                        log.debug("[inventaire] ligne d'intentions illisible (%s)", type(e).__name__)
    S = "sandbox/"
    return [
        {"signal": "ram_pct", "source": S + "vitals_history.jsonl", "statut": "PARTIEL", "cadence_s": cad, "n": len(vit),
         "note": "echantillonneur a %.0f s, serie journalisee a ~15 s (1 echantillon sur 5) ; plus grand trou %s s"
                 % (rm._SAMPLE_INTERVAL_S, sans_couv)},
        {"signal": "ram_free_gb", "source": S + "vitals_history.jsonl", "statut": "PARTIEL", "cadence_s": cad,
         "n": len(vit), "note": "meme serie que ram_pct"},
        {"signal": "ram_total_gb", "source": "derive used/pct", "statut": "PARTIEL", "cadence_s": cad, "n": len(vit),
         "note": "non journalise, derive de ram_used_gb / ram_pct (arrondis a 0,1 %)"},
        {"signal": "ram_pct_plancher_60s", "source": S + "resource_state.json", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "instantane ecrase ; RECONSTRUIT par _noter_ram_fenetre sur la serie a 15 s"},
        {"signal": "palier_pression_ram", "source": "hormone NORADRENALINE_PRESSION_RAM", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "emis en hormone, pas journalise en serie ; RECALCULE par palier_pression_ram"},
        {"signal": "verdict_attribution", "source": S + "lifecycle_actions.jsonl", "statut": "PARTIEL",
         "cadence_s": None, "n": len(fen["verdicts"]),
         "note": "seulement dans les motifs hamilton_arme (ticks avec geste) et pression_hors_corps"},
        {"signal": "registre_vivants", "source": "superviseur /status", "statut": "ILLISIBLE", "cadence_s": None,
         "n": 0, "note": "non journalise : le rejeu suppose vivants = TOML non disabled, puis modele les sommeils"},
        {"signal": "rss_par_service", "source": "_memoire_privee_mb", "statut": "ILLISIBLE", "cadence_s": None,
         "n": 0, "note": "non journalise (le motif Hamilton n'en donne que la SOMME « Mo vises »)"},
        {"signal": "vetos_sommeil", "source": S + "veto_sommeil/", "statut": "ILLISIBLE", "cadence_s": None,
         "n": len(fen["refus_sommeil"]), "note": "fichiers courants seulement ; n = refus sleep_refused qui en temoignent"},
        {"signal": "intentions_actives", "source": S + "lifecycle_actions.jsonl", "statut": "PARTIEL",
         "cadence_s": None, "n": n_intents, "note": intents_note},
        {"signal": "etat_pauses_hamilton", "source": S + "hamilton_pauses_ram.json", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "instantane ecrase ; le rejeu part d'un etat vide"},
        {"signal": "tick_hamilton", "source": S + "lifecycle_actions.jsonl", "statut": "PARTIEL", "cadence_s": None,
         "n": len(fen["hamilton_journal"]),
         "note": "audit seulement quand un geste existe ; gestes tronques a 200 car. ; ticks sans geste invisibles"},
        {"signal": "ordres_superviseur", "source": S + "supervisor_ordres.jsonl", "statut": "LU", "cadence_s": None,
         "n": len(fen["decisions_journal"]) + len(fen["hors_hamilton_journal"]),
         "note": "SUSPENDRE/REPRENDRE delivres (REQUESTED) ; MAINTENIR_PAUSE et ARRETER ne sont pas des ordres ; "
                 "l'ordre ne dit PAS quel chemin l'a emis (attribution par l'audit Hamilton suivant)"},
        {"signal": "sommeils_hors_hamilton", "source": S + "supervisor_ordres.jsonl + lifecycle", "statut": "PARTIEL",
         "cadence_s": None, "n": len(fen["hors_hamilton_journal"]),
         "note": "eviction auditee ou ordre non signe par le tick Hamilton suivant : non simules par ce rejeu"},
        {"signal": "reveils_des_evinces", "source": S + "regulation_evinces.json", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "registre courant seulement ; reveils visibles comme service/start"},
        {"signal": "palier_memoire_hub", "source": S + "hub_mem_palier.json", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "instantane ecrase par mem_watchdog, aucune serie"},
        {"signal": "docker_want_release", "source": S + "lifecycle_actions.jsonl", "statut": "LU", "cadence_s": None,
         "n": len(fen["docker"]), "note": "intentions docker (watch_jobs en base) : historique ILLISIBLE"},
        {"signal": "services_toml_a_l_epoque", "source": "proxy_deno/core/services.toml", "statut": "ILLISIBLE",
         "cadence_s": None, "n": 0, "note": "seule la version courante est lue (classes Hamilton du jour)"},
    ]


# ---------------------------------------------------------------------------------------------------------------
# Docker : delai de grace REEL du keeper, importe sans effet de bord journal
# ---------------------------------------------------------------------------------------------------------------

_KEEPER = None
KEEPER_IMPORT_DIT = ""


def _keeper():
    """Importe forge_docker_keeper SANS lui laisser brancher son journal fichier ni basicConfig sur le root."""
    global _KEEPER, KEEPER_IMPORT_DIT
    if _KEEPER is not None:
        return _KEEPER
    import logging.handlers as _lh

    racine = logging.getLogger()
    avant = list(racine.handlers)
    vrai = _lh.RotatingFileHandler

    class _JournalRefuse(vrai):
        def __init__(self, *a, **k):
            raise OSError("rejeu : journal fichier du keeper non ouvert (lecture seule)")

    tampon = io.StringIO()
    _lh.RotatingFileHandler = _JournalRefuse
    try:
        with contextlib.redirect_stdout(tampon):
            from nokido_agent.tools import forge_docker_keeper as k
    finally:
        _lh.RotatingFileHandler = vrai
        for h in list(racine.handlers):
            if h not in avant:
                racine.removeHandler(h)
                h.close()
    KEEPER_IMPORT_DIT = tampon.getvalue().strip()
    _KEEPER = k
    return k


def delai_docker(palier, intentions=None) -> float:
    """Delai de grace Docker (s) par la fonction REELLE du keeper. intentions None = historique ILLISIBLE."""
    return float(_keeper().delai_de_grace(intentions, palier))


# ---------------------------------------------------------------------------------------------------------------
# Fonction de cout (exposee pour une recherche de seuils ULTERIEURE -- aucune optimisation ici)
# ---------------------------------------------------------------------------------------------------------------

POIDS_DEFAUT = {"temps_endormi_executeurs_s": 1.0 / 3600.0, "pics_ram_s": 1.0 / 60.0, "arrets_docker": 1.0}


def cout(r: dict, fen: dict, poids: dict | None = None) -> dict:
    """Cout d'un rejeu : heures d'executeurs endormis + minutes de pression GENE+ sans rien de cede + arrets Docker
    non rattrapes par la grace. Composantes rendues brutes ; `total` = somme ponderee (poids en parametre)."""
    p = dict(POIDS_DEFAUT, **(poids or {}))
    t_fin = float(r["t1"])
    debut: dict = {}
    endormi = 0.0
    for d in sorted(r["decisions"], key=lambda d: d["ts"]):
        if not est_executeur(d["service"]):
            continue
        if d["geste"] == "SUSPENDRE" and d["service"] not in debut:
            debut[d["service"]] = d["ts"]
        elif d["geste"] == "REPRENDRE" and d["service"] in debut:
            endormi += d["ts"] - debut.pop(d["service"])
    endormi += sum(t_fin - t for t in debut.values())
    periode = float(r["parametres"]["periode_s"])
    pics = sum(periode for t in r["ticks"] if t["palier"] in ("GENE", "DETRESSE", "CRITIQUE") and not t["endormis"])
    wants = sorted(e["ts"] for e in fen.get("docker", []) if e["action"] == "want")
    arrets, detail = 0, []
    for e in fen.get("docker", []):
        if e["action"] != "release":
            continue
        avant = [t for t in r["ticks"] if t["ts"] <= e["ts"]]
        palier = avant[-1]["palier"] if avant else "INCONNU"
        grace = delai_docker(palier)
        rattrape = any(e["ts"] < w <= e["ts"] + grace for w in wants)
        arrets += 0 if rattrape else 1
        detail.append({"iso": _iso(e["ts"]), "palier": palier, "grace_s": grace, "rattrape": rattrape})
    comp = {"temps_endormi_executeurs_s": round(endormi, 1), "pics_ram_s": round(pics, 1), "arrets_docker": arrets}
    return {"composantes": comp, "poids": p, "total": round(sum(p[k] * v for k, v in comp.items()), 4),
            "docker_detail": detail,
            "limites": ["BOUCLE OUVERTE : la RAM est celle observee ; un sommeil simule ne la fait pas baisser, "
                        "pics_ram_s mesure la pression GENE+ sans cession, pas une RAM contrefactuelle",
                        "arrets_docker : contrefactuel (grace reelle appliquee aux releases journalises, intentions "
                        "docker ILLISIBLES -> base sans extension)",
                        "registre, vetos, rss par service : ILLISIBLES (cf inventorier_signaux)"]}


# ---------------------------------------------------------------------------------------------------------------
# Point d'entree (lecture seule, JSON sur stdout)
# ---------------------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--racine", default=str(ROOT))
    ap.add_argument("--debut", required=True, help="ISO UTC, ex. 2026-10-28T08:45:00Z")
    ap.add_argument("--fin", required=True)
    ap.add_argument("--toml", default=None)
    ap.add_argument("--seuil", action="append", default=[], help="nom=valeur (cf SEUILS), repetable")
    ap.add_argument("--tolerance", type=float, default=45.0)
    ap.add_argument("--phase", default="journal", help="'journal' (1er ordre journalise) ou epoch")
    ap.add_argument("--verdict-maintien", type=float, default=0.0,
                    help="s : maintient le dernier verdict journalise (0 = defaut SOI hors fenetre de 60 s)")
    a = ap.parse_args(argv)
    t0, t1 = _epoch(a.debut), _epoch(a.fin)
    fen = lire_fenetre(a.racine, t0, t1)
    seuils = {}
    for s in a.seuil:
        nom, _, val = s.partition("=")
        seuils[nom.strip()] = float(val)
    phase = fen["phase_journal"] if a.phase == "journal" else float(a.phase)
    r = rejouer(fen, toml=a.toml, seuils=seuils, phase_ts=phase, verdict_maintien_s=a.verdict_maintien)
    out = {"seuils": r["seuils"], "parametres": r["parametres"], "policy_id": r["policy_id"],
           "rejets": fen["rejets"], "ticks_illisibles": r["ticks_illisibles"],
           "concordance_tout": {k: v for k, v in concordance(r["decisions"], fen["decisions_journal"], a.tolerance,
                                                             fen=fen).items()},
           "concordance_executeurs": concordance(r["decisions"], fen["decisions_journal"], a.tolerance,
                                                 filtre=est_executeur, fen=fen),
           "cout": cout(r, fen), "decisions": r["decisions"],
           "ticks": [{k: v for k, v in t.items() if k not in ("vivants",)} for t in r["ticks"]],
           "inventaire": inventorier_signaux(a.racine, t0, t1, fen=fen)}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
