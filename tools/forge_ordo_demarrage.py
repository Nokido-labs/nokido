"""forge_ordo_demarrage -- ordonnancement CP-SAT du DEMARRAGE de la pile sous budget RAM.

Transposition du takehome (modele indexe par le temps). Discipline : BORNE d'abord, juge
deterministe, preuve avant promotion. L'outil est en LECTURE SEULE sur la pile : il lit les
journaux du superviseur et services.toml, n'ecrit que son rapport sous docs/mesures/. Il ne
modifie pas services.toml, ne demarre ni n'arrete aucun service ; appliquer un ordre propose
est une decision de l'owner.

Etapes :
  (1) MESURE  -- par service lance au demarrage : duree jusqu'a pret, RSS en regime et en pic,
                 depuis les journaux des N derniers demarrages. Non mesurable = ILLISIBLE, jamais
                 estime.
  (2) BORNE   -- RAM si tout demarre au plus tot vs budget ; duree minimale = chemin critique.
  (3) MODELE  -- CP-SAT indexe par le temps : x[i,t] = « i demarre a t », dependances, somme RAM
                 <= budget a chaque instant, objectif lexicographique (garder le plus de services,
                 puis finir le plus tot).
  (4) JUGE    -- rejeu deterministe d'un plan sur les mesures (pic RAM, fin, violations) compare
                 au rejeu de l'ordre ACTUEL (vagues du superviseur) ; l'ecart entre l'ordre actuel
                 rejoue et l'ordre actuel OBSERVE est dit (erreur de modele).

Ce que les journaux donnent et ne donnent pas (dit, pas devine) :
  * « pret » = ligne superviseur `X: demarre — ...` ou `X: APPLICATION_UP sur /health`. Pour la
    plupart des services c'est la confirmation de spawn du superviseur (vitalite applicative
    NON MESUREE, le journal le dit lui-meme), pas une preuve applicative.
  * RSS en regime = lignes `Sleeping X (uptime Ns, rss N Mo)` de l'eviction. Le `cout presume`
    des lignes `Waking` est une recopie de cette valeur : non compte.
  * RSS en pic : aucun journal ne le donne -> ILLISIBLE pour tous ; le modele prend alors le
    regime comme demande pendant le demarrage (minorant, ecart dit).

OR-tools : a lancer sous LAFORGE_PYTHON (Python 3.12) -- sous 3.14 il plante en access
violation (mesure 27/10). Le module n'importe ortools qu'a l'interieur de `resoudre`.

CLI :
  resoudre --instance PATH|- --budget MO [--sans-report] [--temps-max S]   -> plan JSON (stdout)
  rapport  --racine DEPOT [--toml T] [--n 3] [--unite 0.5] [--ram-physique-mo N]
           [--reserve-mo N] [--sortie docs/mesures/demarrage_services_<date>.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

__FORGE_COLOR__ = "GREEN"

ILLISIBLE = "ILLISIBLE"
LAFORGE_PYTHON_DEFAUT = "%USERPROFILE%/miniforge3/python.exe"
RACINE_OUTIL = Path(__file__).resolve().parents[1]

# ------------------------------------------------------------------ (1) MESURE

_RE_LIGNE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] \[SUPERVISOR\] (.*)$")
_RE_BOOT = re.compile(r"LaForge-Master supervisor starting")
_RE_VAGUE_DEBUT = re.compile(r"marrage Vague Physiologique (\d+)")
_RE_VAGUE_STABLE = re.compile(r"Vague (\d+) stabilis")
_RE_STARTED = re.compile(r"^(\S+): started PID (\d+)")
_RE_PRET = re.compile(r"^(\S+): (?:demarre \u2014|demarre -|APPLICATION_UP)")
_RE_EXITED = re.compile(r"^(\S+): exited code=")
_RE_SLEEPING = re.compile(r"^Sleeping (\S+) \(uptime (\d+)s, rss (\d+) Mo\)")
_RE_RAM_SEUIL = re.compile(r"^RAM ([\d.]+)% > ([\d.]+)%")
_RE_RAM = re.compile(r"^RAM ([\d.]+)%")


def parser_journal(lignes: Iterable[str]) -> list[dict]:
    """Lignes brutes du journal maitre -> evenements types {ts, kind, svc, val}."""
    ev: list[dict] = []
    for brut in lignes:
        m = _RE_LIGNE.match(brut.rstrip("\r\n"))
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
        msg = m.group(2)
        if _RE_BOOT.search(msg):
            ev.append({"ts": ts, "kind": "boot", "svc": None, "val": None})
        elif (mm := _RE_VAGUE_DEBUT.search(msg)):
            ev.append({"ts": ts, "kind": "vague_debut", "svc": None, "val": int(mm.group(1))})
        elif (mm := _RE_VAGUE_STABLE.search(msg)):
            ev.append({"ts": ts, "kind": "vague_stable", "svc": None, "val": int(mm.group(1))})
        elif (mm := _RE_STARTED.match(msg)):
            ev.append({"ts": ts, "kind": "started", "svc": mm.group(1), "val": int(mm.group(2))})
        elif (mm := _RE_PRET.match(msg)):
            ev.append({"ts": ts, "kind": "pret", "svc": mm.group(1), "val": None})
        elif (mm := _RE_EXITED.match(msg)):
            ev.append({"ts": ts, "kind": "exited", "svc": mm.group(1), "val": None})
        elif (mm := _RE_SLEEPING.match(msg)):
            ev.append({"ts": ts, "kind": "sleeping", "svc": mm.group(1), "val": int(mm.group(3))})
        elif (mm := _RE_RAM_SEUIL.match(msg)):
            ev.append({"ts": ts, "kind": "ram", "svc": None,
                       "val": (float(mm.group(1)), float(mm.group(2)))})
        elif (mm := _RE_RAM.match(msg)):
            ev.append({"ts": ts, "kind": "ram", "svc": None, "val": (float(mm.group(1)), None)})
    return ev


def decouper_demarrages(ev: list[dict], n: int = 3) -> list[dict]:
    """Decoupe en fenetres [boot_i, boot_{i+1}) et rend les n dernieres."""
    idx = [i for i, e in enumerate(ev) if e["kind"] == "boot"]
    boots = []
    for k, i in enumerate(idx):
        j = idx[k + 1] if k + 1 < len(idx) else len(ev)
        boots.append({"debut": ev[i]["ts"], "evenements": ev[i:j]})
    return boots[-n:] if n > 0 else []


def _mediane(xs: list[float]):
    return statistics.median(xs) if xs else None


def mesurer_demarrage(boot: dict) -> dict:
    """Mesures d'UN demarrage. Phase de demarrage = [boot, derniere `Vague N stabilisee`]."""
    evs = boot["evenements"]
    vagues: list[dict] = []
    for e in evs:
        if e["kind"] == "vague_debut":
            vagues.append({"num": e["val"], "debut": e["ts"], "stable": None})
        elif e["kind"] == "vague_stable":
            for v in reversed(vagues):
                if v["num"] == e["val"] and v["stable"] is None:
                    v["stable"] = e["ts"]
                    break
    t0 = vagues[0]["debut"] if vagues else boot["debut"]
    stables = [v["stable"] for v in vagues if v["stable"] is not None]
    fin_vagues = max(stables) if stables else None
    limite = fin_vagues or (evs[-1]["ts"] if evs else boot["debut"])

    services: dict[str, dict] = {}
    for i, e in enumerate(evs):
        if e["kind"] != "started" or e["ts"] > limite or e["svc"] in services:
            continue
        pret = None
        for f in evs[i + 1:]:
            if f["svc"] != e["svc"]:
                continue
            if f["kind"] == "pret":
                pret = f["ts"]
                break
            if f["kind"] in ("started", "exited"):
                break
        services[e["svc"]] = {
            "lance_s": round((e["ts"] - t0).total_seconds(), 3),
            "pret_s": round((pret - t0).total_seconds(), 3) if pret else None,
            "duree_s": round((pret - e["ts"]).total_seconds(), 3) if pret else None,
            "rss_mo": [],
        }
    for e in evs:
        if e["kind"] == "sleeping" and e["svc"] in services:
            services[e["svc"]]["rss_mo"].append(e["val"])

    rams = [e["val"] for e in evs if e["kind"] == "ram"]
    seuils = [s for _, s in rams if s is not None]
    pression = [e["ts"] for e in evs if e["kind"] == "ram" and e["val"][1] is not None]

    gaps: list[float] = []
    stabs: list[float] = []
    for v in vagues:
        if v["stable"] is None:
            continue
        dans = [e for e in evs if v["debut"] <= e["ts"] <= v["stable"]]
        lances = sorted(e["ts"] for e in dans if e["kind"] == "started")
        gaps += [(b - a).total_seconds() for a, b in zip(lances, lances[1:])]
        derniers = [e["ts"] for e in dans if e["kind"] in ("started", "pret")]
        if derniers:
            stabs.append((v["stable"] - max(derniers)).total_seconds())

    return {
        "debut": boot["debut"].isoformat(sep=" "),
        "t0_vague1": t0.isoformat(sep=" "),
        "fin_vagues": fin_vagues.isoformat(sep=" ") if fin_vagues else None,
        "duree_observee_s": round((fin_vagues - t0).total_seconds(), 3) if fin_vagues else None,
        "vagues": [{"num": v["num"],
                    "debut_s": round((v["debut"] - t0).total_seconds(), 3),
                    "stable_s": round((v["stable"] - t0).total_seconds(), 3) if v["stable"] else None}
                   for v in vagues],
        "services": services,
        "seuil_eviction_pct": seuils[-1] if seuils else None,
        "ram_max_pct": max(r for r, _ in rams) if rams else None,
        "premiere_pression_s": round((min(pression) - t0).total_seconds(), 3) if pression else None,
        "evictions_sleeping": sum(1 for e in evs if e["kind"] == "sleeping"),
        "stagger_s": _mediane(gaps),
        "stab_s": _mediane(stabs),
    }


def agreger(mesures: list[dict]) -> dict:
    """Par service : duree = mediane des demarrages mesures ; RSS regime = max des mesures."""
    noms = sorted({s for m in mesures for s in m["services"]})
    agr: dict[str, dict] = {}
    for s in noms:
        durees = [m["services"][s]["duree_s"] for m in mesures
                  if s in m["services"] and m["services"][s]["duree_s"] is not None]
        rss = [r for m in mesures if s in m["services"] for r in m["services"][s]["rss_mo"]]
        agr[s] = {
            "duree_s": round(statistics.median(durees), 3) if durees else ILLISIBLE,
            "durees_s": durees,
            "rss_regime_mo": max(rss) if rss else ILLISIBLE,
            "rss_mesures_mo": rss,
            "rss_pic_mo": ILLISIBLE,
            "vu_dans_n_demarrages": sum(1 for m in mesures if s in m["services"]),
        }
    return agr


def lire_services(chemin: Path) -> dict:
    """services.toml -> {nom: vague, deps (noms resolus par port), deps_orphelines, ...}."""
    import tomllib
    with open(chemin, "rb") as f:
        data = tomllib.load(f)
    svcs = data.get("service", [])
    porteur: dict[int, str] = {}
    for s in svcs:
        p = s.get("port")
        if p is None:
            continue
        if p not in porteur or (not s.get("disabled") and _disabled(svcs, porteur[p])):
            porteur[p] = s["name"]
    out: dict[str, dict] = {}
    for k, s in enumerate(svcs):
        deps, orph = [], []
        for p in s.get("deps") or []:
            prov = porteur.get(p)
            if prov is not None and prov != s["name"]:
                deps.append(prov)
            else:
                orph.append(p)
        out[s["name"]] = {
            "vague": int(s.get("wave", 99)),
            "port": s.get("port"),
            "deps": deps,
            "deps_orphelines": orph,
            "essentiel": bool(s.get("essential", False)),
            "disabled": bool(s.get("disabled", False)),
            "ordre": k,
        }
    return out


def _disabled(svcs: list[dict], nom: str) -> bool:
    return any(s["name"] == nom and s.get("disabled") for s in svcs)


def construire_instance(sv: dict, agr: dict, unite_s: float = 0.5) -> dict:
    """Instance du modele : seuls les services a duree MESUREE entrent ; le reste est exclu et dit."""
    exclus: list[dict] = []
    ecarts: list[str] = []
    gardes: list[str] = []
    for nom in agr:
        if nom not in sv:
            exclus.append({"nom": nom, "raison": "absent de services.toml"})
        elif sv[nom]["disabled"]:
            exclus.append({"nom": nom, "raison": "disabled au toml (reveil a la demande pendant le boot)"})
        elif agr[nom]["duree_s"] == ILLISIBLE:
            exclus.append({"nom": nom, "raison": "duree jusqu'a pret ILLISIBLE (aucune ligne pret)"})
        else:
            gardes.append(nom)
    gardes.sort(key=lambda n: (sv[n]["vague"], sv[n]["ordre"]))
    garde_set = set(gardes)
    raison_exclu = {e["nom"]: e["raison"] for e in exclus}
    taches = []
    ram_illisible = []
    for nom in gardes:
        a = agr[nom]
        duree = max(1, math.ceil(a["duree_s"] / unite_s - 1e-9))
        mesuree = a["rss_regime_mo"] != ILLISIBLE
        ram = int(a["rss_regime_mo"]) if mesuree else 0
        if not mesuree:
            ram_illisible.append(nom)
        pic = int(a["rss_pic_mo"]) if a["rss_pic_mo"] != ILLISIBLE else ram
        deps = []
        for d in sv[nom]["deps"]:
            if d in garde_set:
                deps.append(d)
            else:
                ecarts.append(f"dependance {nom} -> {d} hors modele ({raison_exclu.get(d, 'non lance au demarrage')})")
        for p in sv[nom]["deps_orphelines"]:
            ecarts.append(f"dependance {nom} -> port {p} sans service porteur au toml (ignoree)")
        taches.append({"nom": nom, "duree": duree, "ram": ram, "pic": max(pic, ram),
                       "ram_mesuree": mesuree, "pic_mesure": a["rss_pic_mo"] != ILLISIBLE,
                       "essentiel": sv[nom]["essentiel"], "deps": deps,
                       "vague": sv[nom]["vague"], "ordre": sv[nom]["ordre"]})
    if exclus:
        ecarts.append(f"{len(exclus)} service(s) lance(s) au demarrage exclu(s) du modele (liste et raison : "
                      f"instance.exclus) ; ils occupent pourtant le superviseur et la RAM")
    if ram_illisible:
        ecarts.append(f"RSS regime ILLISIBLE pour {len(ram_illisible)} service(s) -> demande RAM 0 dans le "
                      f"modele (non contraint, la borne RAM est un MINORANT) : {', '.join(ram_illisible)}")
    if any(not t["pic_mesure"] for t in taches):
        ecarts.append("RSS en pic ILLISIBLE (aucun journal) -> demande pendant le demarrage = regime (minorant)")
    ecarts.append(f"durees arrondies au pas superieur de {unite_s} s")
    return {"unite_s": unite_s, "taches": taches, "exclus": exclus, "ecarts": ecarts}


# ------------------------------------------------------------------ (4) JUGE (rejeu deterministe)

def rejouer(inst: dict, debuts: dict, budget_mo) -> dict:
    """Rejoue un plan (debuts en unites) : violations de dependances, profil RAM, pic, fin."""
    t_by = {t["nom"]: t for t in inst["taches"]}
    presents = [t for t in inst["taches"] if t["nom"] in debuts]
    violations = []
    for t in presents:
        for d in t["deps"]:
            if d not in debuts:
                violations.append({"tache": t["nom"], "dep": d, "debut": debuts[t["nom"]], "dep_pret": None})
                continue
            pret = debuts[d] + t_by[d]["duree"]
            if debuts[t["nom"]] < pret:
                violations.append({"tache": t["nom"], "dep": d, "debut": debuts[t["nom"]], "dep_pret": pret})
    fin = max((debuts[t["nom"]] + t["duree"] for t in presents), default=0)
    profil = []
    for u in range(fin + 1):
        r = 0
        for t in presents:
            s = debuts[t["nom"]]
            if s <= u:
                r += t["pic"] if u < s + t["duree"] else t["ram"]
        profil.append(r)
    pic = max(profil) if profil else 0
    hors = sum(1 for r in profil if budget_mo is not None and r > budget_mo)
    return {"fin": fin, "pic_ram_mo": pic, "instants_hors_budget": hors, "violations_deps": violations,
            "reportes": sorted(t["nom"] for t in inst["taches"] if t["nom"] not in debuts), "profil": profil}


def simuler_ordre_actuel(inst: dict, stagger: int, stab: int) -> dict:
    """Ordre ACTUEL du superviseur : vague w apres stabilisation de w-1 ; dans une vague, lancements
    espaces de `stagger` (ordre du toml), chacun attendant ses dependances pretes."""
    pret: dict[str, int] = {}
    debuts: dict[str, int] = {}
    t_w = 0
    for w in sorted({t["vague"] for t in inst["taches"]}):
        vague = sorted((t for t in inst["taches"] if t["vague"] == w), key=lambda t: t["ordre"])
        fin_w = t_w
        for k, t in enumerate(vague):
            lance = t_w + k * stagger
            for d in t["deps"]:
                if d in pret:
                    lance = max(lance, pret[d])
            debuts[t["nom"]] = lance
            pret[t["nom"]] = lance + t["duree"]
            fin_w = max(fin_w, pret[t["nom"]])
        t_w = fin_w + stab
    return debuts


def asap(inst: dict) -> dict:
    """Tout au plus tot (dependances seules, sans budget)."""
    t_by = {t["nom"]: t for t in inst["taches"]}
    debuts: dict[str, int] = {}

    def s(n: str, pile: tuple = ()) -> int:
        if n in debuts:
            return debuts[n]
        if n in pile:
            raise ValueError(f"cycle de dependances : {' -> '.join(pile + (n,))}")
        debuts[n] = max((s(d, pile + (n,)) + t_by[d]["duree"] for d in t_by[n]["deps"]), default=0)
        return debuts[n]

    for t in inst["taches"]:
        s(t["nom"])
    return debuts


def borne(inst: dict, budget_mo) -> dict:
    """(2) BORNE : RAM si tout demarre au plus tot ; duree minimale = chemin critique."""
    d = asap(inst)
    r = rejouer(inst, d, budget_mo)
    t_by = {t["nom"]: t for t in inst["taches"]}
    chemin: list[str] = []
    if inst["taches"]:
        n = max(t_by, key=lambda k: (d[k] + t_by[k]["duree"], -t_by[k]["ordre"]))
        while n:
            chemin.append(n)
            prev = [p for p in t_by[n]["deps"] if d[p] + t_by[p]["duree"] == d[n]]
            n = prev[0] if prev else None
    return {
        "ram_au_plus_tot_mo": r["pic_ram_mo"],
        "ram_regime_total_mo": sum(t["ram"] for t in inst["taches"]),
        "n_ram_non_mesuree": sum(1 for t in inst["taches"] if not t.get("ram_mesuree", True)),
        "budget_mo": budget_mo,
        "depasse_budget": (budget_mo is not None and r["pic_ram_mo"] > budget_mo),
        "chemin_critique_unites": r["fin"],
        "chemin_critique_s": round(r["fin"] * inst["unite_s"], 3),
        "chemin_critique": list(reversed(chemin)),
    }


def borne_pile(agr: dict, budget_mo) -> dict:
    """BORNE RAM sur TOUTE la pile lancee au demarrage (modelisee ou non) : somme des RSS regime
    mesurees. Les RSS ILLISIBLE n'y sont pas -> MINORANT des que l'une manque."""
    mes = {s: v["rss_regime_mo"] for s, v in agr.items() if v["rss_regime_mo"] != ILLISIBLE}
    total = sum(mes.values())
    n_ill = len(agr) - len(mes)
    return {"rss_regime_mesuree_mo": total, "n_services": len(agr), "n_rss_mesuree": len(mes),
            "n_rss_illisible": n_ill, "minorant": n_ill > 0, "budget_mo": budget_mo,
            "depasse_budget": (budget_mo is not None and total > budget_mo),
            "rss_par_service_mo": dict(sorted(mes.items(), key=lambda kv: -kv[1]))}


def juger(inst: dict, plan_debuts: dict, actuel_debuts: dict, budget_mo) -> dict:
    p = rejouer(inst, plan_debuts, budget_mo)
    a = rejouer(inst, actuel_debuts, budget_mo)
    p.pop("profil")
    a.pop("profil")
    return {"plan": p, "actuel": a, "gain_unites": a["fin"] - p["fin"],
            "gain_s": round((a["fin"] - p["fin"]) * inst["unite_s"], 3),
            "delta_pic_mo": a["pic_ram_mo"] - p["pic_ram_mo"],
            "comparable": not p["reportes"] and not a["reportes"]}


# ------------------------------------------------------------------ (3) MODELE CP-SAT

def resoudre(inst: dict, budget_mo: int, report: bool = True, temps_max_s: float = 60.0) -> dict:
    """CP-SAT indexe par le temps. x[i,t] = i demarre a t ; b[i,t] = i demarre au plus tard a t.
    RAM(t) = sum_i ram_i*b[i,t] + (pic_i-ram_i)*(b[i,t]-b[i,t-d_i]) <= budget pour tout t.
    Objectif : (H+1) * nb_reportes + fin  (garder le plus de services, puis finir le plus tot)."""
    from ortools.sat.python import cp_model

    taches = inst["taches"]
    H = max(1, sum(t["duree"] for t in taches))
    m = cp_model.CpModel()
    x, b, pres, s = {}, {}, {}, {}
    for t in taches:
        n, d = t["nom"], t["duree"]
        x[n] = [m.NewBoolVar(f"x_{n}_{u}") for u in range(H - d + 1)]
        pres[n] = m.NewBoolVar(f"p_{n}")
        m.Add(sum(x[n]) == pres[n])
        if t["essentiel"] or not report:
            m.Add(pres[n] == 1)
        s[n] = m.NewIntVar(0, H, f"s_{n}")
        m.Add(s[n] == sum(u * v for u, v in enumerate(x[n])))
        b[n] = [m.NewBoolVar(f"b_{n}_{u}") for u in range(H + 1)]
        for u in range(H + 1):
            xu = x[n][u] if u < len(x[n]) else 0
            m.Add(b[n][u] == (b[n][u - 1] if u else 0) + xu)
    for t in taches:
        for d in t["deps"]:
            m.AddImplication(pres[t["nom"]], pres[d])
            dd = next(o["duree"] for o in taches if o["nom"] == d)
            m.Add(s[t["nom"]] >= s[d] + dd).OnlyEnforceIf(pres[t["nom"]])
    for u in range(H + 1):
        terme = []
        for t in taches:
            n = t["nom"]
            terme.append(t["ram"] * b[n][u])
            surplus = t["pic"] - t["ram"]
            if surplus > 0:
                avant = b[n][u - t["duree"]] if u - t["duree"] >= 0 else 0
                terme.append(surplus * (b[n][u] - avant))
        m.Add(sum(terme) <= int(budget_mo))
    fin = m.NewIntVar(0, H, "fin")
    for t in taches:
        m.Add(fin >= s[t["nom"]] + t["duree"]).OnlyEnforceIf(pres[t["nom"]])
    # Lexicographique : 1) nb de reportes, 2) fin, 3) somme des debuts (chacun au plus tot a fin egale).
    w_fin = len(taches) * H + 1
    w_rep = (H + 1) * w_fin
    m.Minimize(w_rep * sum(1 - pres[t["nom"]] for t in taches) + w_fin * fin + sum(s.values()))

    sol = cp_model.CpSolver()
    sol.parameters.num_search_workers = 1
    sol.parameters.random_seed = 0
    sol.parameters.max_time_in_seconds = float(temps_max_s)
    st = sol.Solve(m)
    statut = sol.StatusName(st)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"statut": statut, "debuts": {}, "reportes": [], "fin": None, "vagues": [],
                "horizon": H, "unite_s": inst["unite_s"], "budget_mo": budget_mo}
    debuts = {t["nom"]: sol.Value(s[t["nom"]]) for t in taches if sol.Value(pres[t["nom"]])}
    ordre = {t["nom"]: t["ordre"] for t in taches}
    vagues = [sorted((n for n, v in debuts.items() if v == u), key=lambda n: ordre[n])
              for u in sorted(set(debuts.values()))]
    return {"statut": statut, "debuts": debuts,
            "reportes": sorted(t["nom"] for t in taches if t["nom"] not in debuts),
            "fin": sol.Value(fin), "vagues": vagues, "debuts_vagues": sorted(set(debuts.values())),
            "horizon": H, "unite_s": inst["unite_s"], "budget_mo": budget_mo}


# ------------------------------------------------------------------ rapport (lecture des journaux reels)

def lignes_derniers_demarrages(dossier: Path, n: int) -> tuple[list[str], list[str]]:
    """Remonte les journaux maitres (courant puis rotations, du plus recent au plus ancien)
    jusqu'a contenir n lignes de demarrage. Rend (lignes, fichiers lus)."""
    rot = sorted(p for p in dossier.glob("laforge-master-2*.log") if "-err-" not in p.name)
    fichiers = rot + [dossier / "laforge-master.log"]
    lues: list[list[str]] = []
    noms: list[str] = []
    boots = 0
    for p in reversed(fichiers):
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            ls = f.readlines()
        lues.insert(0, ls)
        noms.insert(0, p.name)
        boots += sum(1 for l in ls if "LaForge-Master supervisor starting" in l)
        if boots >= n:
            break
    return [l for ls in lues for l in ls], noms


def ram_physique_mo() -> tuple[int | None, str]:
    """RAM physique par GlobalMemoryStatusEx (mesure, pas estimation). Echec -> (None, raison)."""
    if os.name != "nt":
        return None, "ILLISIBLE : GlobalMemoryStatusEx indisponible hors Windows"
    import ctypes

    class _MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    ms = _MS()
    ms.dwLength = ctypes.sizeof(_MS)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
        return None, f"ILLISIBLE : GlobalMemoryStatusEx a echoue (err {ctypes.GetLastError()})"
    return int(ms.ullTotalPhys // (1024 * 1024)), "GlobalMemoryStatusEx.ullTotalPhys"


def _resoudre_isole(inst: dict, budget: int, temps_max_s: float) -> dict:
    """Le solveur tourne sous LAFORGE_PYTHON (3.12) dans un sous-processus : sous 3.14 OR-tools
    plante en access violation, ce qui emporterait le processus appelant."""
    py = os.environ.get("LAFORGE_PYTHON", LAFORGE_PYTHON_DEFAUT)
    r = subprocess.run([py, str(Path(__file__).resolve()), "resoudre", "--instance", "-",
                        "--budget", str(budget), "--temps-max", str(temps_max_s)],
                       input=json.dumps(inst), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=temps_max_s + 120)
    if r.returncode != 0:
        raise RuntimeError(f"solveur CP-SAT en echec (rc={r.returncode}) : {r.stderr[-1500:]}")
    return json.loads(r.stdout)


def rapport(racine: Path, toml: Path, n: int, unite_s: float, phys_mo: int | None,
            reserve_mo: int | None, temps_max_s: float) -> dict:
    lignes, fichiers = lignes_derniers_demarrages(racine / "logs" / "supervisor", n)
    boots = decouper_demarrages(parser_journal(lignes), n=n)
    mesures = [mesurer_demarrage(b) for b in boots]
    agr = agreger(mesures)
    sv = lire_services(toml)
    inst = construire_instance(sv, agr, unite_s)

    if phys_mo is None:
        phys_mo, src_phys = ram_physique_mo()
    else:
        src_phys = "argument --ram-physique-mo"
    seuils = [m["seuil_eviction_pct"] for m in mesures if m["seuil_eviction_pct"] is not None]
    seuil = max(seuils) if seuils else None
    if phys_mo is None:
        budget, src_budget = None, f"ILLISIBLE ({src_phys})"
    elif reserve_mo is not None:
        budget, src_budget = phys_mo - reserve_mo, f"RAM physique - reserve {reserve_mo} Mo (argument)"
    elif seuil is not None:
        budget = int(phys_mo * seuil / 100)
        src_budget = f"RAM physique x seuil d'eviction {seuil}% lu au journal (reserve = {100 - seuil}%)"
    else:
        budget, src_budget = None, "ILLISIBLE : ni --reserve-mo ni seuil d'eviction au journal"

    b = borne(inst, budget)
    stags = [m["stagger_s"] for m in mesures if m["stagger_s"] is not None]
    stabs = [m["stab_s"] for m in mesures if m["stab_s"] is not None]
    stagger_s = statistics.median(stags) if stags else 0.0
    stab_s = statistics.median(stabs) if stabs else 0.0
    ecarts = list(inst["ecarts"])
    if not stags:
        ecarts.append("espacement intra-vague ILLISIBLE -> 0 dans la simulation de l'ordre actuel")
    if not stabs:
        ecarts.append("delai de stabilisation ILLISIBLE -> 0 dans la simulation de l'ordre actuel")
    actuel = simuler_ordre_actuel(inst, round(stagger_s / unite_s), round(stab_s / unite_s))
    obs = [m["duree_observee_s"] for m in mesures if m["duree_observee_s"] is not None]

    if budget is None:
        plan = {"statut": "BUDGET_ILLISIBLE", "debuts": {}, "reportes": [], "fin": None, "vagues": []}
        jug = None
    else:
        plan = _resoudre_isole(inst, budget, temps_max_s)
        jug = juger(inst, plan["debuts"], actuel, budget) if plan["debuts"] else None
    sim_actuel_s = round(rejouer(inst, actuel, budget)["fin"] * unite_s, 3)
    return {
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "outil": "tools/forge_ordo_demarrage.py",
        "sources": {"journaux": fichiers, "toml": str(toml),
                    "non_consultes": "journaux par service logs/supervisor/<Service>.log (aucune ligne pret/RSS "
                                     "exploitable reperee ; le journal maitre porte started/pret/Sleeping)"},
        "mesures": {"demarrages": [{k: v for k, v in m.items() if k != "services"}
                                   | {"n_services_lances": len(m["services"]),
                                      "n_pret_mesure": sum(1 for x in m["services"].values()
                                                           if x["duree_s"] is not None)}
                                   for m in mesures],
                    "par_service": agr},
        "borne_pile": borne_pile(agr, budget),
        "budget": {"ram_physique_mo": phys_mo, "source_ram_physique": src_phys, "seuil_eviction_pct": seuil,
                   "budget_mo": budget, "source_budget": src_budget,
                   "ram_hors_pile_mo": ILLISIBLE,
                   "note": "la RAM consommee hors pile (OS, Docker/WSL, modeles charges, navigateurs) n'est dans "
                           "aucun journal : le budget reel de la pile est INFERIEUR d'un montant non mesure"},
        "instance": inst,
        "borne": b,
        "ordre_actuel": {"stagger_s": stagger_s, "stab_s": stab_s, "debuts": actuel,
                         "fin_simulee_s": sim_actuel_s, "fin_observee_s": obs,
                         "erreur_modele_s": (round(sim_actuel_s - statistics.median(obs), 3) if obs else ILLISIBLE)},
        "plan": plan,
        "juge": jug,
        "ecarts": ecarts,
    }


def _tableau(r: dict) -> str:
    out = ["| Service | Duree pret (s) | Mesures duree | RSS regime (Mo) | RSS pic |",
           "|---|---|---|---|---|"]
    for s, v in sorted(r["mesures"]["par_service"].items()):
        out.append(f"| {s} | {v['duree_s']} | {v['durees_s']} | {v['rss_regime_mo']} | {v['rss_pic_mo']} |")
    return "\n".join(out)


def _sortie_autorisee(p: Path) -> Path:
    p = p.resolve()
    base = (RACINE_OUTIL / "docs" / "mesures").resolve()
    if base not in p.parents:
        raise SystemExit(f"refus : l'outil n'ecrit que sous {base} (demande : {p})")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resoudre")
    r.add_argument("--instance", required=True)
    r.add_argument("--budget", type=int, required=True)
    r.add_argument("--sans-report", action="store_true")
    r.add_argument("--temps-max", type=float, default=60.0)
    g = sub.add_parser("rapport")
    g.add_argument("--racine", type=Path, required=True)
    g.add_argument("--toml", type=Path, default=RACINE_OUTIL / "proxy_deno" / "core" / "services.toml")
    g.add_argument("--n", type=int, default=3)
    g.add_argument("--unite", type=float, default=0.5)
    g.add_argument("--ram-physique-mo", type=int, default=None)
    g.add_argument("--reserve-mo", type=int, default=None)
    g.add_argument("--temps-max", type=float, default=60.0)
    g.add_argument("--sortie", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "resoudre":
        texte = sys.stdin.read() if a.instance == "-" else Path(a.instance).read_text(encoding="utf-8")
        plan = resoudre(json.loads(texte), a.budget, report=not a.sans_report, temps_max_s=a.temps_max)
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return 0
    res = rapport(a.racine, a.toml, a.n, a.unite, a.ram_physique_mo, a.reserve_mo, a.temps_max)
    if a.sortie:
        dest = _sortie_autorisee(a.sortie)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"ecrit : {dest}")
    print(_tableau(res))
    print(json.dumps({k: res[k] for k in ("budget", "borne", "ordre_actuel", "juge")},
                     ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"plan_statut": res["plan"]["statut"], "plan_fin": res["plan"].get("fin"),
                      "reportes": res["plan"].get("reportes"), "vagues": res["plan"].get("vagues")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
