"""Pilote de cloture des veilles U1 -- enchaine les lots, borne par la CHARGE.

POURQUOI. 243 depots demandes jamais ingeres. `forge_veille_u1_run` traite UN lot
et rend la main : fermer le reste demanderait un aller-retour client par lot, pour
un travail que le corps sait faire seul. Ce pilote enchaine, et il porte la garde
que le lanceur n'a pas.

POURQUOI UNE GARDE, ET POURQUOI A HYSTERESIS. Un producteur sans garde de charge
fait accuser son consommateur : c'est le drain qui a mis la machine a 98 %, et
c'est l'embedder qui a ete ecarte. Un seuil UNIQUE pomperait -- reprise au dixieme
de point sous la barre. Les seuils sont ceux du corps (`forge_physiology.HIGH` /
`RELEASE`), LUS a chaque appel : les recopier ici les ferait diverger en silence.

CE QUE FAIT LE PILOTE QUAND LA CHARGE MONTE : il S'ARRETE, et il DIT pourquoi. Il
n'attend pas indefiniment -- un job qui dort sans borne est indistinguable d'un job
mort, et le reste du travail est de toute facon repris tel quel au lancement
suivant (`forge_veille_u1_run` note les depots TENTES, ils ne reviennent pas).

CE QU'IL NE FAIT PAS : il ne choisit pas les depots, il ne change pas la selection
de fichiers, il n'ecrit rien en base. Toute cette part appartient a la chaine
existante, qu'il se contente d'appeler.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

__FORGE_COLOR__ = "vegetatif/regulation-de-charge : pilote de cloture des veilles U1"

RACINE = Path(__file__).resolve().parent.parent
# ⚠️ RACINE d'abord, et c'est le correctif du 2026-09-12 : l'amorce n'inserait que
# `app/` et `tools/`, ce qui sert la convention d'import PLATE. Or la ligne
# suivante importe sous la forme NAMESPACEE (`nokido_agent.tools...`), qui exige
# la RACINE. Ce pilote de cloture U1 mourait donc en `ModuleNotFoundError: No
# module named 'nokido_agent'` des qu'on le lancait par son point d'entree — son
# voisin `forge_veille_u1_run.py` inserait ROOT et marchait, d'ou deux lanceurs
# du meme chantier dont un seul demarrait.
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from nokido_agent.tools import forge_physiology as ph  # noqa: E402

ILLISIBLE = "capteur RAM ILLISIBLE -- abstention (un capteur muet n'est pas un feu vert)"


def _resoudre(chemin):
    """Ancre un chemin RELATIF sur le depot, pas sur le repertoire courant.

    MESURE 2026-09-08 : le repertoire de travail d'un job detache est
    `<depot>/sandbox/workspace`. Le defaut de `--progress` etant relatif, le fichier
    de progres partait dans `sandbox/workspace/sandbox/` -- introuvable la ou tout le
    monde le cherche, donc un pilote qui travaille se lit comme un pilote muet.
    C'est EXACTEMENT le defaut corrige le meme jour dans `forge_job_watch_notify`, et
    je l'avais laisse dans mon propre outil : une correction qui ne balaie pas la
    famille laisse le piege en place ailleurs.
    """
    if not chemin:
        return chemin
    p = Path(chemin)
    return p if p.is_absolute() else (RACINE / p)


def garde(pct, en_pause: bool):
    """(continuer, motif). Les seuils sont LUS sur `forge_physiology` a chaque appel.

    Trois etats, jamais deux : au-dessus de HIGH on s'arrete, sous RELEASE on repart,
    ENTRE LES DEUX on conserve l'etat courant -- c'est exactement ce qui distingue
    une hysteresis d'un seuil, et ce qui empeche le pompage.
    """
    if pct is None:
        return False, ILLISIBLE
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return False, f"{ILLISIBLE} (valeur {pct!r})"
    if p >= ph.HIGH:
        return False, f"RAM {p:.1f}% >= HIGH {ph.HIGH} -- pause"
    if p <= ph.RELEASE:
        return True, ""
    if en_pause:
        return False, (f"RAM {p:.1f}% dans la bande [{ph.RELEASE}, {ph.HIGH}] -- "
                       "pause MAINTENUE (hysteresis)")
    return True, ""


def _ram_pct():
    """None = ILLISIBLE. Surtout pas 0.0 : un capteur muet rendu comme charge nulle
    ouvrirait le garde en silence."""
    try:
        import psutil

        return float(psutil.virtual_memory().percent)
    except Exception:  # noqa: BLE001 - l'illisibilite est une reponse, pas une panne
        return None


def _etat():
    """(total, traites, restants) -- le DENOMINATEUR, pris a la source existante."""
    from nokido_agent.tools import forge_veille_u1_run as u1

    absents, _motif = u1.charger_absents()
    if not absents:
        return (0, 0, 0)
    faits = u1.deja_faits()
    _cibles, restants = u1.construire_cibles(absents, faits, 1)
    total = len(absents)
    return (total, total - restants, restants)


def _lot(taille: int) -> int:
    """Un lot, en process. `forge_ingest_github_repo` signale ses refus par
    `SystemExit` (CLI reutilise en bibliotheque) : sans ce filet, un refus tuerait
    le pilote apres des minutes de telechargement."""
    from nokido_agent.tools import forge_veille_u1_run as u1

    argv = list(sys.argv)
    sys.argv = ["forge_veille_u1_run", "--limit", str(taille)]
    try:
        return int(u1.main() or 0)
    except SystemExit as exc:
        return int(getattr(exc, "code", 1) or 0)
    except Exception as exc:  # noqa: BLE001 - un lot en echec n'arrete pas la cloture
        print(f"[u1-boucle] lot en echec ({exc!r}) -- on poursuit", flush=True)
        return 1
    finally:
        sys.argv = argv


def _ecrire(progress, total, traites, restants, lots, motifs, etat):
    """Le journal du pilote ne LEVE jamais : un garde journalise APRES avoir agi."""
    if not progress:
        return
    try:
        Path(progress).write_text(json.dumps({
            "total": total, "traites": traites, "restants": restants,
            "lots_faits": lots, "motifs": motifs, "etat": etat, "ts": time.time(),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[u1-boucle] progres non ecrit ({exc!r})", flush=True)


def boucle(*, lancer_lot, lire_etat, taille_lot: int = 10, max_lots: int = 100,
           progress=None, lire_ram=None, dormir=None, repos_s: float = 15.0) -> dict:
    lire_ram = lire_ram or _ram_pct
    dormir = dormir or time.sleep

    en_pause = False
    lots = 0
    motifs: dict = {}
    total, traites, restants = lire_etat()
    _ecrire(progress, total, traites, restants, lots, motifs, "DEMARRE")
    etat = "EPUISE" if restants <= 0 else "EN_COURS"

    while lots < max_lots and restants > 0:
        ok, motif = garde(lire_ram(), en_pause)
        if motif:
            motifs[motif] = motifs.get(motif, 0) + 1
        en_pause = not ok
        if not ok:
            etat = "ARRETE_SUR_CHARGE"
            break
        lancer_lot(taille_lot)
        lots += 1
        total, traites, restants = lire_etat()
        _ecrire(progress, total, traites, restants, lots, motifs, "EN_COURS")
        if restants > 0 and lots < max_lots:
            dormir(repos_s)

    if etat == "EN_COURS":
        etat = "EPUISE" if restants <= 0 else "BORNE_MAX_LOTS"
    _ecrire(progress, total, traites, restants, lots, motifs, etat)
    return {"total": total, "traites": traites, "restants_final": restants,
            "lots_faits": lots, "motifs": motifs, "etat": etat}


def main() -> int:
    ap = argparse.ArgumentParser(prog="forge_veille_u1_boucle")
    ap.add_argument("--taille-lot", type=int, default=10)
    ap.add_argument("--max-lots", type=int, default=100,
                    help="borne DURE : un arret sur borne rend ce qui reste")
    ap.add_argument("--progress", default="sandbox/veille_u1_boucle.progress.json")
    ap.add_argument("--repos", type=float, default=15.0, help="pause entre lots (s)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    progres = _resoudre(a.progress)
    total, traites, restants = _etat()
    print("[u1-boucle] %d absents, %d traites, %d restants" % (total, traites, restants),
          flush=True)
    print("[u1-boucle] progres -> %s" % progres, flush=True)
    if a.dry_run:
        print("[u1-boucle] dry-run -- aucun lot lance", flush=True)
        return 0

    r = boucle(lancer_lot=_lot, lire_etat=_etat, taille_lot=a.taille_lot,
               max_lots=a.max_lots, progress=progres, repos_s=a.repos)
    print("[u1-boucle] " + json.dumps(r, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
