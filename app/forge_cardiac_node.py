#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_cardiac_node.py — NOEUD SINUSAL : le corps n'a qu'UN rythme, et il descend.

DIRECTIVE OWNER (2026-09-03) : « le pouls doit emaner du coeur, son battement doit
eventuellement etre adaptatif en analogie a la regulation. »

CE QUI EXISTAIT, ET POURQUOI CE N'ETAIT PAS UN COEUR
====================================================
Sept organes portaient chacun leur propre horloge (`time.sleep(INTERVAL)`), soit sept
pacemakers independants qui derivent. Mesure du jour au journal du superviseur :
`forge_hebbian_linker` 765 relances « heartbeat stale », 2377 sorties de process --
un organe dont le cycle dure 6 h ne peut pas satisfaire un seuil de 600 s, et il
etait relance sans fin. Un corps ne resout pas ce probleme en donnant une montre a
chaque cellule : il impose un rythme depuis un point unique.

LES DEUX SENS, A NE PAS CONFONDRE
=================================
- DESCENDANT (ici) : la systole. Le coeur impose la cadence, les organes sont
  PERFUSES. C'est ce fichier, et c'est ce qui manquait.
- MONTANT (existant) : l'afference. L'organe temoigne de son etat -- `beat_daemon`
  pour le superviseur, `forge_organ_afferent` pour la moelle. On n'y touche pas.

Un organe lit `periode_s` et s'y accorde ; il ne la calcule plus.

CE QUE LE COEUR EST, ET CE QU'IL N'EST PAS (recadrage owner, 2026-09-03)
=======================================================================
Le cardiaque n'est PAS un troisieme systeme de coordination a cote du nerveux et de
l'hormonal. C'est un OSCILLATEUR et un MOTEUR DE TRANSPORT : il cree un debit, il
distribue les signaux des autres systemes, et **sa propre frequence est regulee par
eux**. Un coeur qui deciderait de son rythme serait un organe qui s'auto-prescrit.

Le code respecte cette hierarchie : `PERIODE_INTRINSEQUE_S` est le rythme PROPRE du
noeud sinusal (il bat meme denerve — c'est un fait physiologique, pas une metaphore),
et `innervation()` rend la MODULATION que le nerveux et l'hormonal lui imposent :

    frein (parasympathique)  <--  rythme intrinseque  -->  accelerateur (sympathique)

Les entrees de cette modulation sont des signaux QUE LE CORPS PRODUIT DEJA (pression
memoire, hormones chronotropes) : on ne fabrique pas un capteur de plus. Si aucune
n'est lisible, le coeur retombe sur son rythme intrinseque -- exactement ce que fait
un coeur denerve, et surtout pas sur une valeur inventee.

BORNE QUI N'EST PAS NEGOCIABLE : `PERIODE_MAX_S` reste SOUS le plus court seuil du
superviseur (90 s, tier `fast`). Une bradycardie qui franchirait ce seuil ferait
declarer figes TOUS les organes perfuses d'un coup -- le rythme adaptatif deviendrait
une panne systemique. L'adaptation joue donc entre 15 s et 45 s, jamais au-dela.

SI LE COEUR S'ARRETE : les organes ne meurent pas. `forge_heartbeat.Cadence` bascule
sur un RYTHME D'ECHAPPEMENT (le noeud auriculo-ventriculaire prend le relais quand le
sinusal defaille) et le DECLARE dans son afference, pour qu'un arret cardiaque se voie
au lieu de se deviner.
"""
from __future__ import annotations

__FORGE_COLOR__ = "regulation/noeud-sinusal"

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_APP = str(Path(__file__).resolve().parent)
# ⚠️ LA RACINE AVEC `app/`, et pas seulement `app/`. Lance PAR CHEMIN — c'est
# ainsi que services.toml demarre ce noeud — `sys.path[0]` vaut le dossier du
# SCRIPT. Sans la racine, `from nokido_agent.app.forge_heartbeat import
# beat_daemon` leve `ModuleNotFoundError` et le coeur meurt en ecrivant son
# pouls, c'est-a-dire APRES avoir bat.
#
# Mesure du 2026-09-20 : mort depuis le 2026-09-10 06:45 (pid 16396 disparu),
# `cardiac_pulse.json` frais mais `.heartbeat` fige a 10,4 jours. Un organe qui
# travaille et dont le temoin ne bouge pas est le cas le plus trompeur qui soit.
for _p in (str(ROOT), _APP):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PULSE = ROOT / "sandbox" / "cardiac_pulse.json"

# Bornes du rythme. PERIODE_MAX_S < 90 s (stale_degraded du tier `fast`) : voir la
# docstring, c'est la contrainte dure et non un reglage.
PERIODE_MIN_S = 15.0          # tachycardie maximale (sympathique a fond)
PERIODE_MAX_S = 45.0          # bradycardie maximale TOLERABLE (frein vagal maximal)

# Rythme PROPRE du noeud sinusal : ce qu'il bat sans aucune innervation. Il n'est ni
# le minimum ni le maximum -- un coeur denerve bat PLUS VITE qu'un coeur au repos,
# parce que le frein vagal domine en permanence chez le sujet eveille. C'est aussi le
# rythme de repli quand aucune modulation n'est lisible.
PERIODE_INTRINSEQUE_S = 30.0
# HORMONES CHRONOTROPES, et leur poids. Toutes les hormones n'agissent PAS sur la
# frequence cardiaque -- c'est la mesure du 2026-09-03 qui a impose ce filtre : en
# prenant le MAX de toutes, le coeur se calait sur `TSH_VECTORIZATION` (0,972, TTL
# 4 h) et battait a sa periode MINIMALE en permanence. Une valeur saturee pendant
# quatre heures n'est pas une tension, c'est une constante : le rythme n'aurait rien
# regule du tout, il aurait juste coute cher.
#
# L'adrenaline est le chronotrope+ direct (TTL 180 s ici, la bonne echelle de temps).
# Le cortisol n'accelere pas le coeur, il est PERMISSIF : il potentialise, d'ou un
# poids reduit. TSH et insuline pilotent le metabolisme basal, sur des heures --
# elles n'ont rien a faire dans une boucle cardiaque.
CHRONOTROPES = {"adrenaline": 1.0, "CORTISOL_FRUSTRATION": 0.5}


def innervation() -> tuple:
    """MODULATION imposee au coeur par le nerveux et l'hormonal, dans [0,1].

    0 = frein dominant (repos), 1 = accelerateur a fond (effort). Le coeur ne decide
    pas de cette valeur : il la subit. Elle est lue sur les signaux que les autres
    systemes emettent deja.

    Trois etats, jamais deux : une source illisible ne vaut PAS une tension nulle --
    elle est nommee dans la raison, et le coeur garde alors le rythme de repos plutot
    que d'accelerer ou de ralentir sur une mesure qu'il n'a pas.
    """
    # AUCUNE LECTURE DIRECTE DE L'ETAT DE LA MACHINE ICI (arbitrage owner 2026-09-03).
    # La premiere version lisait `psutil.virtual_memory()` : le coeur constatait
    # lui-meme la pression et en deduisait qu'il devait accelerer. C'est un organe qui
    # se prescrit sa propre frequence. La charge memoire est une information pour le
    # systeme de REGULATION ; celui-ci la traduit en hormone, et c'est l'hormone qui
    # module le coeur. Un seul chemin, et il descend.
    parts, raisons = [], []
    try:
        from nokido_agent.app import forge_endocrine as FE  # type: ignore

        retenues, vues = [], 0
        for r in FE.scan():
            vues += 1
            poids = CHRONOTROPES.get(str(getattr(r, "name", "")))
            if poids is None:
                continue
            retenues.append((str(getattr(r, "name", "")),
                             poids * float(getattr(r, "level", 0.0) or 0.0)))
        if retenues:
            parts.append(min(1.0, max(v for _, v in retenues)))
            # On imprime le DENOMINATEUR : sans lui, « 0 hormone retenue » ne se
            # distingue pas de « je n'ai pas pu regarder ».
            raisons.append("chronotropes %d/%d retenues (%s)" % (
                len(retenues), vues,
                ", ".join("%s=%.2f" % (n, v) for n, v in sorted(retenues, key=lambda x: -x[1]))))
        else:
            raisons.append("aucun chronotrope actif (%d hormones vues)" % vues)
    except Exception as e:  # noqa: BLE001
        raisons.append("endocrine ILLISIBLE(%s)" % type(e).__name__)
    if not parts:
        # DENERVE : aucune modulation lisible. On ne rend PAS 0.0, qui serait « frein
        # maximal » — une absence de signal deviendrait une bradycardie decidee sur
        # rien. On rend None, et l'appelant retombe sur le rythme intrinseque.
        return None, "DENERVE : aucune source lisible (" + ", ".join(raisons) + ")"
    return min(1.0, max(parts)), ", ".join(raisons)


def periode_pour(modulation) -> float:
    """Rythme intrinseque module par l'innervation.

    `None` (denerve) rend le rythme PROPRE du noeud, pas une extremite : c'est la
    difference entre « personne ne me commande » et « on me commande de ralentir ».
    """
    if modulation is None:
        return PERIODE_INTRINSEQUE_S
    t = min(1.0, max(0.0, float(modulation)))
    return round(PERIODE_MAX_S - t * (PERIODE_MAX_S - PERIODE_MIN_S), 1)


def systole(tick: int) -> dict:
    """Un battement : mesure la tension, en deduit la periode, publie.

    La periode publiee vaut pour l'intervalle QUI SUIT : un organe qui lit ce pouls
    sait combien de temps dormir avant le prochain.
    """
    modulation, raison = innervation()
    p = periode_pour(modulation)
    etat = {"tick": tick, "ts": round(time.time(), 1),
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "periode_s": p,
            "modulation": None if modulation is None else round(modulation, 3),
            "denerve": modulation is None, "raison": raison,
            "pid": os.getpid(),
            "bornes_s": [PERIODE_MIN_S, PERIODE_MAX_S]}
    tmp = PULSE.with_suffix(".json.tmp")
    PULSE.parent.mkdir(parents=True, exist_ok=True)
    # Ecriture atomique : un organe qui lirait un fichier a moitie ecrit conclurait a
    # un arret cardiaque et basculerait en echappement pour rien.
    tmp.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PULSE)
    return etat


def lire(max_age_s: float | None = None) -> dict | None:
    """Le dernier battement, ou None si le coeur ne bat pas / n'est pas lisible.

    `None` signifie « je ne peux pas m'accorder », pas « le coeur est mort » : l'appelant
    bascule en rythme d'echappement et le DECLARE, il n'affirme rien sur la cause.
    """
    try:
        d = json.loads(PULSE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  # muet-ok : l'absence de pouls EST la reponse,
        # rendue par le None ci-dessous ; l'appelant la traite explicitement.
        return None
    if not isinstance(d, dict) or "periode_s" not in d:
        return None
    if max_age_s is None:
        # Un pouls est perime au-dela de trois battements manques -- la meme regle
        # qu'un moniteur cardiaque, qui n'alarme pas sur un battement isole.
        max_age_s = 3.0 * float(d.get("periode_s") or PERIODE_MAX_S)
    if (time.time() - float(d.get("ts") or 0.0)) > max_age_s:
        return None
    return d


def boucle(rounds: int = 0) -> int:
    """Bat jusqu'a l'arret. `rounds > 0` borne le nombre de battements (tests)."""
    tick = 0
    print("[coeur] noeud sinusal — bornes %.0f..%.0f s -> %s"
          % (PERIODE_MIN_S, PERIODE_MAX_S, PULSE), flush=True)
    while True:
        tick += 1
        etat = systole(tick)
        # Le coeur temoigne AUSSI vers le superviseur : l'organe qui donne le rythme
        # doit etre juge par le meme contrat que ceux qu'il perfuse, sinon il s'exempte
        # de la regle qu'il impose.
        try:
            from nokido_agent.app.forge_heartbeat import beat_daemon

            beat_daemon("cardiac_node", tick=tick, periode_s=etat["periode_s"],
                        modulation=etat["modulation"], denerve=etat["denerve"])
        except Exception as e:  # noqa: BLE001
            print("[coeur] afference NON emise (%s) — le superviseur ne me voit pas"
                  % type(e).__name__, flush=True)
        if rounds and tick >= rounds:
            return 0
        time.sleep(etat["periode_s"])


def _main() -> int:
    ap = argparse.ArgumentParser(description="Noeud sinusal Nokido (rythme du corps)")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--rounds", type=int, default=0)
    a = ap.parse_args()
    if a.once:
        print(json.dumps(systole(1), ensure_ascii=False, indent=1))
        return 0
    if not a.daemon:
        ap.error("--daemon ou --once requis")
    return boucle(rounds=a.rounds)


if __name__ == "__main__":
    sys.exit(_main())
