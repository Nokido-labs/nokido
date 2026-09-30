# -*- coding: utf-8 -*-
"""forge_capability_consolidation.py — l'archeologie parle enfin a quelqu'un.

__FORGE_COLOR__ ci-dessous : memoire, pas qualite. Ce module n'analyse RIEN de neuf.

LE DEFAUT QU'IL CORRIGE (mesure 2026-08-28)
===========================================
Nokido possede huit phases d'archeologie : `forge_archaeology` (vestiges),
`forge_archaeology_enrich` (ce que faisait chacun, et lequel vaut d'etre repris),
`forge_constituent_archaeology` (fonctions et entrees de registre disparues),
`forge_capability_lineage` (apparu -> disparu -> reapparu), `forge_reachability_
ledger` (defini / reference / offert / PROUVE), `forge_capability_recovery`
(derniere version connue avant suppression). Elles fonctionnent.

Et pourtant rien n'est jamais recupere. Mesure : `sandbox/forgotten_capabilities.md`
contenait 1017 vestiges enrichis, dates de 12,7 JOURS, et AUCUN appelant hors du
chainage interne des phases entre elles. Le fichier dit lui-meme « analyse pure —
aucune reintegration automatique ». Personne ne l'avait ouvert.

C'est le motif deja paye trois fois ce jour-la : des LECTEURS sans ecrivain (la carte
du corps), un garde branche sur un signal que personne n'emet, et ici un ecrivain
sans LECTEUR. Un rapport que rien ne consulte a le meme effet qu'un rapport absent.

CE QUE FAIT CE MODULE
=====================
Il transforme un artefact dormant en OBLIGATION VISIBLE. `forge_memoire_active`
projette les dettes ouvertes a chaque tour d'agent : une capacite perdue inscrite
en dette se rappelle donc d'elle-meme, au lieu d'attendre qu'on pense a lire un
fichier. C'est le seul chainon qui manquait.

CE QU'IL REFUSE
===============
1. Il ne REINTEGRE rien. Regle owner, deja portee par `archaeology_enrich` : on
   PROPOSE avec preuve, la decision reste humaine. Il ouvre une dette, il n'ecrit
   pas une ligne de code applicatif.
2. Il n'ouvre pas 1017 dettes. Une avalanche d'obligations ne se lit pas mieux
   qu'un fichier de 1017 entrees — elle se lit MOINS bien, parce qu'elle noie les
   dettes vivantes. Plafond strict, et par vague.
3. Il ne rouvre pas ce qui est deja ouvert ou deja clos.

LE FILTRE QUI COMPTE : LA SUPPRESSION COLLATERALE
=================================================
Un vestige supprime par un commit qui le VISE ("retire le provider X") est une
DECISION : la reprendre serait desobeir. Un vestige emporte par un commit qui
parle d'autre chose ("cleanup 651 fichiers non-essentiels", "untrack cache/temp",
"supprime orphelins") est un DOMMAGE COLLATERAL : personne n'a jamais decide de
perdre cette capacite. Mesure : `forge_cerberus_x.py` — un moteur d'auto-patch
avec snapshot / apply / validate / ROLLBACK — a ete emporte le 2026-04-16 par un
« refacto(reorg): cleanup app/ + logs/ + sandbox/ ». Personne n'a decide ca.

C'est ce signal-la qu'on remonte en priorite.
"""

from __future__ import annotations

__FORGE_COLOR__ = "memoire/consolidation-retrospective"

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

VESTIGES_MD = ROOT / "sandbox" / "forgotten_capabilities.md"
PERIME_JOURS = 7.0
PLAFOND_DETTES = 5

# INTERDIT DE RAPATRIEMENT — decision owner, cf. CLAUDE.md : « Nokido est un cerveau
# agentique DEFENSIF. Le coeur ne porte aucune capacite offensive et n'en decrit
# aucune. Les composants de recherche securite vivent dans un depot prive separe. »
# Ces capacites n'ont PAS ete perdues : elles ont ete DEPORTEES, volontairement.
# Les proposer a la reintegration, c'est proposer de re-flaguer le coeur et de
# defaire une decision -- exactement l'inverse du travail de ce module. Mesure
# 2026-08-28 : mon premier classement remontait forge_ctf_runner, recon_master et
# forge_exegol_bridge, parce que la detection « collateral » lisait le NOM du
# fichier dans le commit et ratait « refactor(ctf): isolate CTF organ », qui EST une
# decision de domaine. On tranche donc sur le DOMAINE, avant tout autre filtre.
_OFFENSIF = re.compile(
    r"(^|/)(ctf|recon_silo|recon|redteam|red_team|exegol|offensive|exploit|pwn|"
    r"payload|c2\b)|_ctf|_exploit|_pwn|exegol|recon_master|pentest|redteam",
    re.IGNORECASE,
)
# NB : `forge_cerberus_x` (snapshot/apply/validate/ROLLBACK) n'est PAS offensif
# malgre son nom -- c'est un moteur d'auto-patch defensif. Ne pas l'ajouter ici.


def est_offensif(chemin: str) -> bool:
    """Domaine offensif deporte en depot prive : JAMAIS remonte a la reintegration."""
    return bool(_OFFENSIF.search(chemin.replace("\\", "/")))


# Motifs de commit qui parlent d'AUTRE CHOSE que du fichier emporte.
_COLLATERAL = re.compile(
    r"(cleanup|clean\b|untrack|orphelin|non-essential|non essentiel|reorg|"
    r"consolidate|refacto|refactor|menage|elagage|gitignore|move|deplace)",
    re.IGNORECASE,
)


def _age_jours(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 86400.0 if p.exists() else float("inf")


def lire_vestiges(chemin: Path | None = None) -> list[dict]:
    """Parse le rapport enrichi. Rend [] si absent — sans inventer."""
    p = chemin or VESTIGES_MD
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8", errors="replace")
    out = []
    motif = re.compile(
        r"^## (?P<cible>\S+)\s+\(DELETED, score (?P<score>[\d.]+)\)\n"
        r"- supprime le (?P<date>\S+) — « (?P<commit>[^»]*)»\n"
        r"- (?P<stats>[^\n]*)\n"
        r"(?:- intention : (?P<intention>[^\n]*)\n)?"
        r"(?:- symboles : (?P<symboles>[^\n]*))?",
        re.M,
    )
    for m in motif.finditer(txt):
        d = m.groupdict()
        loc = re.search(r"(\d+) LOC", d.get("stats") or "")
        d["loc"] = int(loc.group(1)) if loc else 0
        d["score"] = float(d["score"])
        _, _, d["chemin"] = d["cible"].partition(":")
        out.append(d)
    return out


def encore_absent(vestige: dict) -> bool:
    """Le fichier est-il TOUJOURS absent, ici ou sous un autre dossier ?

    Trois etats evites : on ne conclut pas « perdu » sur la seule absence a son
    ancien chemin — un module deplace dans app/ ou tools/ est VIVANT, et le
    signaler perdu ferait crier le rapport a faux."""
    rel = vestige["chemin"]
    if (ROOT / rel).exists():
        return False
    base = os.path.basename(rel)
    return not any((ROOT / d / base).exists() for d in ("app", "tools", "sandbox", "tests"))


def collateral(vestige: dict) -> bool:
    """Le commit qui l'a emporte parlait-il d'autre chose ?"""
    commit = vestige.get("commit") or ""
    base = os.path.basename(vestige["chemin"]).replace(".py", "")
    if base and base.lower() in commit.lower():
        return False  # le commit NOMME le fichier : c'est une decision
    return bool(_COLLATERAL.search(commit))


# Silos peripheriques : un outil de CTF ou une UI streamlit perdue ne remet pas en
# cause le fonctionnement du corps ; un module de app/ ou tools/ si. A valeur egale,
# le coeur passe devant — sinon le classement remonte le plus GROS, pas le plus utile.
_SILOS = ("ctf/", "recon_silo/", "streamlit_ui/", "benchmarks/", "forge_desktop/")


def _est_coeur(chemin: str) -> bool:
    c = chemin.replace("\\", "/")
    return not any(s in c for s in _SILOS)


def candidats(vestiges: list[dict] | None = None) -> list[dict]:
    """Vestiges encore absents, DEDUPLIQUES, tries par ce qui compte.

    Trois corrections apportees apres le premier essai reel (2026-08-28) :

    - DEDUPLICATION par cle de dette. Le meme fichier apparait sous plusieurs
      depots (`nokido:` et `nokido-redteam:` portent le meme `forge_ctf_runner`) :
      sans cela, la meme capacite consommait deux places du plafond.
    - le VOLUME n'est pas la valeur. Trier par LOC remontait un runner CTF de 708
      lignes devant `forge_cerberus_x` (221 lignes) — or celui-ci porte
      snapshot/apply/validate/ROLLBACK, c'est-a-dire exactement la capacite de
      rollback de mutation qui manque au corps aujourd'hui.
    - le SCORE du rapport vaut 1.0 pour tous les candidats retenus : il ne
      discrimine rien et ne peut pas servir de cle de tri.

    Ordre retenu : ce qu'un TEST PROUVAIT d'abord, puis le collateral (personne
    n'a DECIDE de le perdre), puis le coeur avant les silos, le volume departageant
    en dernier.

    La PREUVE passe devant depuis le 2026-08-29. `forge_reachability_ledger` produit
    l'etat `HISTORICALLY_PROVEN` -- disparu, mais un test le citait, donc la capacite
    a REELLEMENT fonctionne -- et cet etat n'avait qu'un seul consommateur : le module
    qui l'emet. 155 capacites demontrees attendaient dans un rapport que personne ne
    lisait. Entre deux vestiges, celui dont l'usage est prouve vaut mieux qu'un dont
    on ignore s'il a jamais tourne.
    """
    v = vestiges if vestiges is not None else lire_vestiges()
    retenus, vus = [], set()
    for x in v:
        # Le domaine offensif est ECARTE d'entree : il est deporte par decision, pas
        # perdu par accident. Le remonter serait defaire l'isolement du coeur.
        if est_offensif(x["chemin"]) or est_offensif(x.get("intention") or ""):
            continue
        if not encore_absent(x):
            continue
        cle = _cle_dette(x)
        if cle in vus:
            continue
        vus.add(cle)
        x["collateral"] = collateral(x)
        x["coeur"] = _est_coeur(x["chemin"])
        x["prouve"] = _fut_prouve(x["chemin"])
        retenus.append(x)
    return sorted(retenus, key=lambda x: (not x["prouve"], not x["collateral"],
                                          not x["coeur"], -x["loc"]))


def _noms_historiquement_prouves(chemin: Path | None = None) -> set:
    """Constituants que `forge_reachability_ledger` classe HISTORICALLY_PROVEN.

    La cle est `fiches` -- une liste de {nom, depot, vivant, etat, preuve}. Une
    premiere version lisait `constituants`/`entrees` : elle rendait ZERO nom, donc
    la priorite a la preuve etait un cablage MORT, l'ironie exacte de ce module.
    Verifie depuis : 155 noms, dont 9 modules.

    GRANULARITE : les fiches portent des SYMBOLES (`get_proxy_url`, `handle_diag`),
    pas des chemins. Le recoupement avec un vestige -- qui est un FICHIER -- ne vaut
    donc que pour les noms de MODULE (`forge_events`, `forge_arbitrator`...). C'est
    un signal partiel, et il est traite comme tel : il fait REMONTER un candidat,
    il n'en ecarte aucun.

    Absent ou illisible -> ensemble VIDE et repli sur l'ordre precedent : on ne
    bloque pas la consolidation faute de registre, mais on ne pretend pas non plus
    qu'aucune capacite n'etait prouvee.
    """
    p = chemin or (ROOT / "sandbox" / "reachability.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:  # noqa: BLE001
        sys.stderr.write("[consolidation] registre d'atteignabilite illisible (%s) : "
                         "la preuve ne departage pas ce passage\n" % type(e).__name__)
        return set()
    fiches = data.get("fiches") if isinstance(data, dict) else data
    if not isinstance(fiches, list):
        sys.stderr.write("[consolidation] registre au format inattendu : "
                         "la preuve ne departage pas ce passage\n")
        return set()
    return {str(e["nom"]) for e in fiches
            if isinstance(e, dict) and e.get("etat") == "HISTORICALLY_PROVEN"
            and e.get("nom")}


_PROUVES_CACHE = None


def _fut_prouve(chemin: str) -> bool:
    """True si un test citait ce constituant avant sa disparition."""
    global _PROUVES_CACHE
    if _PROUVES_CACHE is None:
        _PROUVES_CACHE = _noms_historiquement_prouves()
    if not _PROUVES_CACHE:
        return False
    base = Path(str(chemin)).stem
    return base in _PROUVES_CACHE


def _cle_dette(vestige: dict) -> str:
    base = os.path.basename(vestige["chemin"]).replace(".py", "").replace("-", "_")
    return "capacite_perdue_%s" % re.sub(r"[^a-z0-9_]", "_", base.lower())


def consolider(plafond: int = PLAFOND_DETTES, dry_run: bool = True) -> dict:
    """Ouvre une dette pour les meilleures capacites encore absentes.

    `dry_run=True` par defaut : ce module inscrit des OBLIGATIONS dans la memoire
    active, ce qui pese sur tous les tours suivants. On regarde avant d'ecrire.
    """
    try:
        _artefact = str(VESTIGES_MD.relative_to(ROOT))
    except ValueError:
        # VESTIGES_MD peut etre reconfigure hors du depot (runner CI: basetemp
        # sous RUNNER_TEMP, hors checkout) -- ne pas planter, se rabattre sur le nom.
        _artefact = VESTIGES_MD.name
    rapport = {
        "artefact": _artefact,
        "age_jours": round(_age_jours(VESTIGES_MD), 1),
        "perime": _age_jours(VESTIGES_MD) > PERIME_JOURS,
        "dry_run": dry_run,
    }
    if not VESTIGES_MD.exists():
        rapport["erreur"] = (
            "aucun rapport de vestiges : lancer d'abord forge_archaeology puis "
            "forge_archaeology_enrich — sans eux ce module n'a rien a consommer")
        return rapport

    tous = lire_vestiges()
    cands = candidats(tous)
    # Le rapport enrichi est un TOP, pas un inventaire : son en-tete annonce
    # ~1017 vestiges et n'en DETAILLE qu'une vingtaine. Nommer le champ
    # « vestiges_lus » laisserait croire qu'on a tout vu.
    entete = re.search(r"_(\d+) vestiges", VESTIGES_MD.read_text(encoding="utf-8", errors="replace"))
    rapport.update({
        "vestiges_detailles_dans_le_rapport": len(tous),
        "vestiges_annonces_par_l_entete": int(entete.group(1)) if entete else None,
        "encore_absents": len(cands),
        "collateraux": sum(1 for c in cands if c["collateral"]),
        "au_coeur": sum(1 for c in cands if c["coeur"]),
    })
    if rapport["perime"]:
        rapport["avertissement"] = (
            "rapport vieux de %.1f j : des capacites peuvent avoir ete reprises "
            "depuis. Regenerer avant d'agir." % rapport["age_jours"])

    deja = set()
    try:
        from nokido_agent.app import forge_memoire_active as mem

        for d in mem.dettes_ouvertes(limit=200) or []:
            if isinstance(d, dict):
                deja.add(str(d.get("texte", "")).split(" ")[0])
    except Exception as exc:  # noqa: BLE001 - memoire indisponible : on le DIT
        mem = None
        rapport["memoire_indisponible"] = "%s: %s" % (type(exc).__name__, exc)

    ouvertes, proposees = [], []
    for c in cands[:plafond]:
        cle = _cle_dette(c)
        if cle in deja:
            continue
        texte = (
            "CAPACITE PERDUE, encore absente au %s. `%s` (%d LOC, score %.1f) a "
            "disparu le %s, emporte par un commit qui parlait d'AUTRE CHOSE : « %s ». "
            "%sIntention d'origine : %s. Symboles : %s. "
            "RECUPERER LA DERNIERE VERSION : "
            "`run action=trusted_script path=tools/forge_capability_recovery.py "
            "script_args=\"--fichier %s\"` — puis DECIDER : reintegrer, adapter, ou "
            "clore en disant pourquoi cette capacite n'est plus voulue. Aucune "
            "reintegration automatique (regle owner)."
        ) % (
            time.strftime("%Y-%m-%d"), c["chemin"], c["loc"], c["score"], c["date"],
            (c.get("commit") or "").strip()[:120],
            "SUPPRESSION COLLATERALE : personne n'a decide de perdre cette capacite. "
            if c["collateral"] else "",
            (c.get("intention") or "inconnue")[:120],
            (c.get("symboles") or "")[:160],
            c["chemin"],
        )
        proposees.append({"cle": cle, "chemin": c["chemin"], "loc": c["loc"],
                          "collateral": c["collateral"], "coeur": c["coeur"]})
        if not dry_run and mem is not None:
            try:
                mem.ouvrir_dette(cle, texte, auteur="CONSOLIDATION")
                ouvertes.append(cle)
            except Exception as exc:  # noqa: BLE001
                rapport.setdefault("echecs", []).append("%s: %s" % (cle, exc))

    rapport["proposees"] = proposees
    rapport["ouvertes"] = ouvertes
    return rapport


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Consolidation retrospective des capacites")
    ap.add_argument("--ecrire", action="store_true",
                    help="ouvre reellement les dettes (defaut : dry-run)")
    ap.add_argument("--plafond", type=int, default=PLAFOND_DETTES)
    a = ap.parse_args()
    r = consolider(plafond=a.plafond, dry_run=not a.ecrire)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
