#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_regulation_learner.py — la boucle de regulation, cote APPRENTISSAGE.

Etape B du pivot metabolisme (2026-08-15). Aujourd'hui la regulation est
`etat -> regle -> action` (thermostat) : le corps evince a 75 % de RAM, reveille
a 65 %, mais n'APPREND PAS si sa reponse a bien marche. Ce module ferme la moitie
PERCEPTION -> OBSERVATION -> RENFORCEMENT de la boucle :

  episode de stress (RAM franchit le seuil d'eviction)
      -> issue REELLE mesuree dans la serie vitals (a-t-il recupere ? en combien ?)
      -> RECOMPENSE attribuee a la politique en vigueur
      -> ledger persistant + lecon rendue a la memoire commune
      -> derive d'efficacite detectee (le corps regule-t-il MIEUX ou MOINS BIEN ?)

PASSIF PAR CONSTRUCTION. Il n'AGIT pas, ne choisit aucune politique, ne change
aucun comportement vivant. Il BATIT le jeu de donnees (state, action, outcome)
dont le futur choix-de-politique aura besoin. Laisser l'organisme AGIR seul sur
sa regulation est une etape distincte, gatee, a decider par l'owner -- on ne
donne pas la main a un controleur qui n'a pas encore fait ses preuves.

REUTILISE la detection d'episode de forge_physiology (source unique) ; ajoute
l'attribution, la recompense, la persistance et la derive.

Usage :
    forge_regulation_learner.py            # apprend depuis la serie, met a jour le ledger
    forge_regulation_learner.py --json
    forge_regulation_learner.py --no-anchor   # n'ecrit pas de lecon (test/CI)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "sandbox", "regulation_ledger.jsonl")
POLITIQUE = "rules_v1"   # la politique implicite en vigueur (seuils 75/65). Le jour
#                          ou plusieurs coexistent, la recompense se cle par politique.


def _cible_baseline() -> float:
    """Cible de recuperation = reference GELEE (baseline physiologique), JAMAIS la
    mediane de la fenetre courante. Sinon la recompense serait circulaire : si le
    corps ralentit, sa propre reference glisse avec lui et 90 s passerait pour
    normal (defaut #2). On mesure l'ecart a la NORME figee, pas aux pairs du
    moment. Repli sur un plancher fixe -- jamais la fenetre."""
    try:
        sys.path.insert(0, ROOT)
        from nokido_agent.tools import forge_physiology as P
        with open(P.BASELINE, encoding="utf-8") as fh:
            v = json.load(fh).get("constantes", {}).get("recovery_time_p50_s")
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    except Exception:  # noqa: BLE001 - pas de baseline : plancher, jamais la fenetre
        pass
    return 120.0


def _bucket(ep: dict) -> str:
    """Etat physiologique GROSSIER au declenchement -- la cle d'apprentissage
    (etape #1 : quelle politique marche DANS QUEL ETAT). Grossier a dessein : trop
    fin, jamais deux episodes comparables."""
    ram, cpu = ep.get("ram_at_trigger"), ep.get("cpu_at_trigger")
    rb = "ram90+" if isinstance(ram, (int, float)) and ram >= 90 else "ram85-90"
    if not isinstance(cpu, (int, float)):
        cb = "cpu?"
    elif cpu >= 70:
        cb = "cpu_hi"
    elif cpu >= 30:
        cb = "cpu_mid"
    else:
        cb = "cpu_lo"
    return f"{rb}|{cb}"


def _recompense(ep: dict, cible_s: float) -> float:
    """0..1. Recupere ET pas plus lent que la NORME GELEE = 1 ; recupere mais plus
    lent = 0.5 ; jamais revenu a l'equilibre = 0. La cible venant de la baseline
    figee (pas des pairs), une degradation FAIT vraiment chuter la recompense."""
    if not ep.get("recovered"):
        return 0.0
    t = ep.get("recovery_s")
    if t is None:
        return 0.5
    return 1.0 if t <= cible_s else 0.5


def charger_ledger() -> list[dict]:
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER, encoding="utf-8", errors="replace") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if ligne:
                try:
                    out.append(json.loads(ligne))
                except json.JSONDecodeError:
                    continue
    return out


def apprendre(fenetre: int = 5760, anchor: bool = True) -> dict:
    """Lit la serie, attribue une recompense a chaque episode NOUVEAU, met a jour
    le ledger, et mesure la derive d'efficacite (recent vs ancien)."""
    sys.path.insert(0, ROOT)
    from nokido_agent.tools import forge_physiology as P

    rows = P._lire_serie(fenetre)
    episodes = P.recovery_episodes(rows) if len(rows) >= 4 else []

    # #2 : cible GELEE (baseline physiologique), pas la mediane de la fenetre.
    cible_s = _cible_baseline()

    connus = {e.get("t0") for e in charger_ledger()}
    # #1 : chaque episode porte son ETAT (bucket) -> le ledger devient
    # etat -> politique -> resultat, substrat du futur choix-de-politique.
    nouveaux = [{**ep, "politique": POLITIQUE, "bucket": _bucket(ep),
                 "recompense": _recompense(ep, cible_s)}
                for ep in episodes if ep.get("t0") not in connus]
    if nouveaux:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            for e in nouveaux:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    # La valeur apprise et la derive se calculent TOUJOURS depuis le ledger, meme
    # si la fenetre courante n'a rien ajoute : l'apprentissage PERSISTE entre les
    # runs. Ne pas les reporter parce que le moment present est calme reviendrait
    # a oublier ce que le corps a deja appris.
    ledger = charger_ledger()
    recompenses = [e.get("recompense", 0.0) for e in ledger if "recompense" in e]
    valeur = round(statistics.mean(recompenses), 3) if recompenses else None
    derive = None
    if len(recompenses) >= 6:
        moitie = len(recompenses) // 2
        ancien = statistics.mean(recompenses[:moitie])
        recent = statistics.mean(recompenses[moitie:])
        derive = round(recent - ancien, 3)

    # #1 : valeur apprise PAR ETAT. Aujourd'hui une seule politique -> c'est
    # l'efficacite de rules_v1 selon l'etat. La COMPARAISON entre politiques (A vs
    # B dans le meme etat) attend que plusieurs politiques existent -- c'est la
    # moitie ACT, gatee. Ici on batit deja la table etat -> valeur.
    par_etat: dict = {}
    for e in ledger:
        if "recompense" not in e:
            continue
        k = e.get("bucket") or _bucket(e)
        d = par_etat.setdefault(k, {"n": 0, "somme": 0.0})
        d["n"] += 1
        d["somme"] += e.get("recompense", 0.0)
    par_etat = {k: {"n": v["n"], "valeur": round(v["somme"] / v["n"], 3)}
                for k, v in sorted(par_etat.items())}

    if not ledger and not episodes:
        etat = "INDETERMINE" if len(rows) < 4 else "AUCUN_EPISODE"
        return {"etat": etat,
                "raison": ("serie vitals trop courte" if len(rows) < 4
                           else "aucun stress RAM et ledger vide — rien a apprendre")}

    rapport = {
        "etat": "APPRIS",
        "politique": POLITIQUE,
        "episodes_fenetre": len(episodes),
        "nouveaux_au_ledger": len(nouveaux),
        "ledger_total": len(ledger),
        "cible_recovery_s": round(cible_s, 1),   # NORME gelee (baseline), pas la fenetre
        "valeur_apprise": valeur,       # 0..1 : efficacite moyenne de la politique
        "derive_efficacite": derive,    # >0 s'ameliore, <0 se degrade, None si trop tot
        "par_etat": par_etat,           # etat -> {n, valeur} : quelle efficacite DANS QUEL ETAT
    }

    if anchor and nouveaux:
        try:
            sys.path.insert(0, ROOT)
            from nokido_agent.app.forge_self_correction import anchor_solution
            anchor_solution(
                problem="Efficacite de la regulation RAM (politique %s)" % POLITIQUE,
                solution=("valeur apprise %s sur %d episodes ; derive %s ; cible %ss"
                          % (valeur, len(ledger), derive, round(cible_s, 1))),
                example="LAFORGE_PYTHON tools/forge_regulation_learner.py",
                domain="systeme",
            )
            rapport["lecon_ancree"] = True
        except Exception as e:  # noqa: BLE001 - anchor best-effort, jamais bloquant
            rapport["anchor_err"] = f"{type(e).__name__}: {e}"[:120]
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description="Apprentissage passif de la regulation")
    ap.add_argument("--window", type=int, default=5760)
    ap.add_argument("--no-anchor", action="store_true", help="n'ecrit pas de lecon")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rap = apprendre(a.window, anchor=not a.no_anchor)
    if a.json:
        print(json.dumps(rap, ensure_ascii=False, indent=2))
        return 0
    print(f"[regulation-learner] {rap['etat']}")
    for cle in ("politique", "episodes_fenetre", "nouveaux_au_ledger", "ledger_total",
                "cible_recovery_s", "valeur_apprise", "derive_efficacite"):
        if cle in rap:
            print(f"   {cle:<22} {rap[cle]}")
    for etat, v in (rap.get("par_etat") or {}).items():
        print(f"   etat {etat:<16} valeur {v['valeur']} (n={v['n']})")
    if rap.get("derive_efficacite") is not None and rap["derive_efficacite"] < -0.1:
        print("   ⚠ la regulation se DEGRADE (valeur recente < ancienne) — "
              "regression metabolique")
    if rap.get("raison"):
        print(f"   {rap['raison']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
