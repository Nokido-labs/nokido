"""STRATEGIES DE RECHERCHE enfichables du banc d'amelioration (owner 29/10 : toutes les phases du take-home).

Declarees par cible dans config/bancs_amelioration.json, cle `strategies` :
  {"parametres": {nom: {min, max, init}}, "borne": {"commande": "..."}, "reaccord": N,
   "crochets": ["solveur_exact", "superopt"], "interdits": ["motif"], "plateau": K}
Tout est pur et injectable (evaluer / runner / sonde) : le juge reste gele, le module n'invente jamais de mesure.

Table phase du take-home -> strategie -> NR (tests/nr/test_banc_strategies_nr.py)
  ph.4  balayages de parametres            -> balayage()                      -> TestParametresBalayageBasin
  ph.11 basin-hopping (bruit VERIFIE)      -> basin_hopping(), verifier_bruit -> TestParametresBalayageBasin
  ph.3  bornes calculees, arret a la borne -> calculer_borne, passe_borne     -> TestBorne (BORNE_ATTEINTE)
  ph.7  reaccord dedie par variante        -> juger_variante()                -> TestReaccord
  ph.14 croisement de regions              -> croiser_meilleurs()             -> TestCroisement
  ph.10 impossibilite mesuree/prouvee      -> consigner_plateau/_infeasible   -> TestPlateauImpossible
  ph.10 superopt exacte z3 / ph.12 CP-SAT  -> crochet()                       -> TestCrochets
  ph.15 triche (specialisation graine)     -> controler_triche()              -> TestAntiTriche
  ph.1,2,5,6,8,9,13 (ordonnancement, reduction du travail, RCPSP, prologue, restructuration, politiques d'unite,
  LNS) restent le travail du generateur de patch ; leurs resultats passent par les memes juges et registre.
  ph.16/17 : discipline = juge gele, copie isolee, registre chaine, aucun commit (forge_banc_amelioration).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/strategies de recherche du banc : balayage, basin-hopping, bornes, reaccord, anti-triche"

import ast
import json
import os
import random
import subprocess
from pathlib import Path
from typing import Callable, Optional

CROCHETS = {"solveur_exact": "ortools", "superopt": "z3"}  # CP-SAT / z3 CEGIS


def _meilleur(a: float, b: float, sens: str) -> bool:
    return a > b if sens == "max" else a < b


def _banc():
    import forge_banc_amelioration as B  # import tardif : B importe ce module
    return B


# ------------------------------------------------------------------ (a) parametres, balayage, basin-hopping
def valider_parametres(parametres: dict) -> tuple:
    if not isinstance(parametres, dict) or not parametres:
        return False, "parametres vides"
    for nom, s in parametres.items():
        if not isinstance(s, dict) or not {"min", "max", "init"} <= set(s):
            return False, "%s : min, max, init requis" % nom
        if not s["min"] <= s["init"] <= s["max"]:
            return False, "%s : min <= init <= max requis" % nom
    return True, ""


def balayage(evaluer: Callable, parametres: dict, sens: str) -> dict:
    """Balayage coordonnee par coordonnee (phase 4) ; `evaluer(params) -> float | None`."""
    ok, motif = valider_parametres(parametres)
    if not ok:
        raise ValueError(motif)
    cur = {k: s["init"] for k, s in parametres.items()}
    best = evaluer(dict(cur))
    trace = [(dict(cur), best)]
    for k, s in parametres.items():
        entier = isinstance(s["min"], int) and isinstance(s["max"], int)
        vals = range(s["min"], s["max"] + 1) if entier else [
            s["min"] + (s["max"] - s["min"]) * j / 10 for j in range(11)]
        for v in vals:
            cand = {**cur, k: v}
            m = evaluer(dict(cand))
            trace.append((cand, m))
            if m is not None and (best is None or _meilleur(m, best, sens)):
                best, cur = m, cand
    return {"params": cur, "metrique": best, "trace": trace}


def basin_hopping(evaluer: Callable, parametres: dict, sens: str, n: int, graine: int, bruit: float,
                  borne: Optional[float] = None) -> dict:
    """Marche aleatoire a bruit gaussien graine (phase 11). bruit <= 0 = recherche INERTE : refuse."""
    if bruit is None or bruit <= 0:
        raise ValueError("bruit nul : recherche inerte (piege phase 11)")
    ok, motif = valider_parametres(parametres)
    if not ok:
        raise ValueError(motif)
    rng = random.Random(graine)
    cur = {k: s["init"] for k, s in parametres.items()}
    best = evaluer(dict(cur))
    traj = [tuple(sorted(cur.items()))]
    statut = "EN_COURS"
    for _ in range(n):
        if borne is not None and best is not None and borne_atteinte(best, borne, sens):
            statut = "BORNE_ATTEINTE"
            break
        cand = {}
        for k, s in parametres.items():
            v = cur[k] + rng.gauss(0, bruit * (s["max"] - s["min"]))
            if isinstance(s["init"], int):
                v = int(round(v))
            cand[k] = min(s["max"], max(s["min"], v))
        traj.append(tuple(sorted(cand.items())))
        m = evaluer(dict(cand))
        if m is not None and (best is None or not _meilleur(best, m, sens)):
            best, cur = m, cand
    else:
        if borne is not None and best is not None and borne_atteinte(best, borne, sens):
            statut = "BORNE_ATTEINTE"
    return {"params": cur, "metrique": best, "trajectoire": traj, "statut": statut, "graine": graine}


def verifier_bruit(evaluer: Callable, parametres: dict, sens: str, graines=(1, 2), n: int = 8,
                   bruit: float = 0.5) -> bool:
    """Le bruit est-il BRANCHE ? Deux graines doivent donner deux trajectoires differentes."""
    a = basin_hopping(evaluer, parametres, sens, n, graines[0], bruit)["trajectoire"]
    b = basin_hopping(evaluer, parametres, sens, n, graines[1], bruit)["trajectoire"]
    return a != b


# ------------------------------------------------------------------ (b) borne
def borne_atteinte(metrique: float, borne: float, sens: str) -> bool:
    return metrique <= borne if sens == "min" else metrique >= borne


def calculer_borne(commande: str, run: Optional[Callable] = None) -> Optional[float]:
    """Commande DETERMINISTE -> derniere ligne JSON {"borne": x} ou nombre nu ; illisible -> None."""
    try:
        out = (run or _run_defaut)(commande)
        ligne = out.strip().splitlines()[-1]
        try:
            d = json.loads(ligne)
        except ValueError:
            return None
        v = d.get("borne") if isinstance(d, dict) else d
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    except Exception:  # noqa: BLE001 -- pas de borne inventee
        return None


def _run_defaut(commande: str) -> str:
    import shlex
    import sys
    argv = [sys.executable if t == "python" else t for t in shlex.split(commande, posix=True)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=300, check=True).stdout


def passe_borne(nom: str, banc: dict, registre: Path, run: Optional[Callable] = None) -> Optional[dict]:
    """Si le meilleur prouve atteint la borne declaree : consigne BORNE_ATTEINTE (arret). Sinon None."""
    B = _banc()
    cfg = (banc.get("strategies") or {}).get("borne")
    if not cfg or not cfg.get("commande"):
        return None
    sens = banc["juge"]["sens"]
    best = B.meilleur_prouve(registre, sens)
    borne = calculer_borne(cfg["commande"], run)
    if best is None or borne is None or not borne_atteinte(best["metrique"], borne, sens):
        return None
    B.consigner_banc(registre, nom, "BORNE_ATTEINTE", best["metrique"], sens, "strategie:borne", "",
                     best["metrique"], "metrique %s atteint la borne %s : arret" % (best["metrique"], borne))
    return {"statut": "BORNE_ATTEINTE", "metrique": best["metrique"], "borne": borne}


# ------------------------------------------------------------------ (c) reaccord dedie
def juger_variante(variante, reaccorder: Callable, n_reaccord: int, meilleur: float, sens: str,
                   froide: Optional[float] = None) -> dict:
    """Une variante structurelle n'est jugee qu'APRES `n_reaccord` evals de reaccord (phase 7)."""
    if not isinstance(n_reaccord, int) or n_reaccord < 1:
        raise ValueError("reaccord obligatoire : n_reaccord >= 1 (jamais de jugement a froid)")
    m = reaccorder(variante, n_reaccord)
    if m is None:
        return {"verdict": "JUGE_ILLISIBLE", "metrique_froide": froide}
    v = "AMELIORE" if _meilleur(m, meilleur, sens) else ("EGAL" if m == meilleur else "REGRESSION")
    return {"verdict": v, "metrique": m, "metrique_froide": froide, "evals_reaccord": n_reaccord}


# ------------------------------------------------------------------ (d) croisement
def croiser_meilleurs(registre: Path, sens: str, croiser: Callable, evaluer: Callable) -> dict:
    """Croise les 2 meilleurs maillons PROUVES (phase 14 : strict x pre-XOR) et juge l'enfant."""
    B = _banc()
    liens = [d for d in B.lire_registre(registre) if d.get("statut") in B.PROUVES
             and isinstance(d.get("metrique"), (int, float))]
    liens.sort(key=lambda d: d["metrique"], reverse=(sens == "max"))
    if len(liens) < 2:
        return {"verdict": "NON_APPLICABLE", "motif": "moins de 2 maillons prouves"}
    enfant = croiser(liens[0], liens[1])
    m = evaluer(enfant)
    if m is None:
        return {"verdict": "JUGE_ILLISIBLE"}
    ref = liens[0]["metrique"]
    v = "AMELIORE" if _meilleur(m, ref, sens) else ("EGAL" if m == ref else "REGRESSION")
    return {"verdict": v, "metrique": m, "parents": [liens[0]["metrique"], liens[1]["metrique"]]}


# ------------------------------------------------------------------ (e) plateau / impossibilite
def consigner_plateau(registre: Path, cible: str, historique: list, k: int, sens: str) -> Optional[dict]:
    """k derniers essais sans gain sur le meilleur d'avant -> IMPOSSIBLE_MESURE (jamais « prouve »)."""
    h = [x for x in historique if isinstance(x, (int, float))]
    if k < 1 or len(h) <= k:
        return None
    avant, derniers = h[:-k], h[-k:]
    best = max(avant) if sens == "max" else min(avant)
    if any(_meilleur(x, best, sens) for x in derniers):
        return None
    return _banc().consigner_banc(registre, cible, "IMPOSSIBLE_MESURE", best, sens, "strategie:plateau", "", best,
                                  "plateau : %d essais sans gain sous %s (mesure, pas preuve)" % (k, best))


def consigner_infeasible(registre: Path, cible: str, motif: str) -> dict:
    if not motif or not str(motif).strip():
        raise ValueError("motif obligatoire : INFEASIBLE sans motif n'est pas une preuve")
    return _banc().consigner_banc(registre, cible, "INFEASIBLE", None, "min", "strategie:solveur", "", None,
                                  str(motif)[:300])


# ------------------------------------------------------------------ (f) crochets solveurs
def _sonde_defaut(python: str, module: str) -> bool:
    try:
        return subprocess.run([python, "-c", "import " + module], capture_output=True, timeout=60).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def crochet(nom: str, python: Optional[str] = None, sonde: Optional[Callable] = None) -> dict:
    """solveur_exact (CP-SAT/ortools) et superopt (z3) : APPLICABLE si installe dans LAFORGE_PYTHON, sinon dit."""
    if nom not in CROCHETS:
        raise ValueError("crochet inconnu %r (attendus %s)" % (nom, sorted(CROCHETS)))
    py = python or os.environ.get("LAFORGE_PYTHON") or "python"
    mod = CROCHETS[nom]
    if (sonde or _sonde_defaut)(py, mod):
        return {"crochet": nom, "statut": "APPLICABLE", "module": mod}
    return {"crochet": nom, "statut": "NON_APPLICABLE", "module": mod,
            "motif": "module %s absent de %s" % (mod, py)}


def valider_strategies(cfg: dict) -> tuple:
    if not isinstance(cfg, dict):
        return False, "strategies doit etre un objet"
    if "parametres" in cfg:
        ok, motif = valider_parametres(cfg["parametres"])
        if not ok:
            return False, motif
    for c in cfg.get("crochets", []):
        if c not in CROCHETS:
            return False, "crochet inconnu %r" % (c,)
    if "reaccord" in cfg and not (isinstance(cfg["reaccord"], int) and cfg["reaccord"] >= 1):
        return False, "reaccord >= 1 requis"
    return True, ""


# ------------------------------------------------------------------ (g) anti-triche
def controler_triche(source: str, banc: dict) -> Optional[str]:
    """Refus d'un candidat dont une CHAINE designe une donnee du juge (graine, corpus, empreintes, interdits)."""
    jetons = {Path(e).name.lower() for e in (banc.get("juge") or {}).get("empreintes", [])}
    jetons |= {str(x).lower() for x in (banc.get("strategies") or {}).get("interdits", [])}
    jetons.discard("")
    if not jetons:
        return None
    try:
        chaines = [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str)]
    except SyntaxError:
        chaines = [source]
    for c in chaines:
        for j in jetons:
            if j in c.lower():
                return "triche : le candidat designe une donnee du juge (%s)" % j
    return None
