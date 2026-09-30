"""tools/forge_couverture_perimetre.py — DEUX metriques de couverture, jamais fusionnees.

Arbitrage owner du 2026-09-08 :

  1. `perimetre non vide` — le gain gate PEUT se prononcer sur ce module (au moins un
     test a jouer). Objectif 100 %, atteignable par generation de tests d'appui.
  2. `couverture prouvee`  — au moins un test EXERCE reellement le comportement, ecrit
     a la main. JAMAIS optimisee automatiquement, reservee a l'audit.

La separation est un INVARIANT, pas une preference de presentation. Un systeme qui
publie ses scores et optimise dessus tombe sous Goodhart par construction (entree P1
du dossier de veille) : generer un test d'import par module ferait passer la couverture
de 18,5 % a ~100 % en une nuit sans que rien ne soit mieux teste. C'est pourquoi ce
module n'expose AUCUN score agrege — il n'y a rien a additionner, et le NR l'exige.

Un test d'appui se DECLARE (marqueur `GENERE-APPUI` dans ses premieres lignes), il ne
se devine pas. Meme principe que `__FORGE_COLOR__` pour les organes : le filet
« deviner depuis le contenu » a deja ete essaye ailleurs dans ce depot puis RETIRE,
parce qu'une etiquette inventee se propage et devient indistinguable d'une mesure.

Usage :
  run action=run_job script=tools/forge_couverture_perimetre.py
  (lecture seule ; aucun test lance, aucun reseau)
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/audit : mesure la couverture de mesure, en deux metriques disjointes"

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# Dossiers hors perimetre : ni corps vivant, ni code a regresser.
DOSSIERS_HORS = ("_attic", "legacy", "__pycache__", ".git", "sandbox", "node_modules")

# Marqueur qu'un test d'appui GENERE doit porter pour etre reconnu comme tel.
MARQUEUR_APPUI = "GENERE-APPUI"

# CRITERE D'ECARTEMENT — declaratif, donc relisible et contestable.
#
# Volontairement ETROIT. Mesure du 2026-09-08 : un premier critere « jetables » avait
# avale 80 modules LEGITIMES (`app/collab_modes/_core.py`, `app/_internal/*`) parce
# qu'il ecartait tout basename prefixe `_`. Un module interne n'est pas un dechet.
ECARTES = [
    {"genre": "prefixe_nom", "valeur": "tmp_",
     "motif": "fichier de travail jetable (117 mesures le 2026-09-08 : tmp_arxiv_test, tmp_ask_capture...)"},
    {"genre": "prefixe_chemin", "valeur": "app/backups/",
     "motif": "snapshot date, pas un module vivant (auto_boot_2026...)"},
    {"genre": "nom_exact", "valeur": "__init__.py",
     "motif": "fichier de paquet : pas une unite de comportement a regresser"},
]


def est_ecarte(rel: str) -> bool:
    """Ce module sort-il du denominateur ? Applique ECARTES, rien d'autre."""
    r = str(rel).replace("\\", "/")
    nom = r.rsplit("/", 1)[-1]
    for regle in ECARTES:
        g, v = regle["genre"], regle["valeur"]
        if g == "prefixe_nom" and nom.startswith(v):
            return True
        if g == "prefixe_chemin" and r.startswith(v):
            return True
        if g == "nom_exact" and nom == v:
            return True
    return False


def _parcourir(base: Path) -> list[Path]:
    out: list[Path] = []
    if not base.is_dir():
        return out
    for racine, dossiers, fichiers in os.walk(base):
        dossiers[:] = [d for d in dossiers if d not in DOSSIERS_HORS and not d.startswith(".")]
        out += [Path(racine) / f for f in fichiers if f.endswith(".py")]
    return out


_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", re.M)


def _index_tests(racine: Path):
    """{module_importe: [chemins de test]} + l'ensemble des tests d'appui declares."""
    par_module: dict[str, list[str]] = {}
    appuis: set[str] = set()
    for t in _parcourir(racine / "tests"):
        rel = str(t.relative_to(racine)).replace("\\", "/")
        try:
            txt = t.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # illisible : compte comme absent, et le rapport le dira
        if MARQUEUR_APPUI in txt[:2000]:
            appuis.add(rel)
        for m in _IMPORT.finditer(txt):
            nom = (m.group(1) or m.group(2)).split(".")[0]
            par_module.setdefault(nom, []).append(rel)
    return par_module, appuis


def mesurer_couverture(racine=None) -> dict:
    """Rend les DEUX metriques, leur denominateur, et ce qui a ete ecarte — NOMME."""
    r = Path(racine) if racine is not None else ROOT
    modules = _parcourir(r / "app") + _parcourir(r / "tools")
    rels = [str(p.relative_to(r)).replace("\\", "/") for p in modules]
    ecartes_nommes = [x for x in rels if est_ecarte(x)]
    retenus = [x for x in rels if not est_ecarte(x)]

    par_module, appuis = _index_tests(r)
    from nokido_agent.app.forge_mutation_judge import perimetre_mesure_detail

    avec_perimetre, avec_preuve, sans_perimetre = [], [], []
    for rel in retenus:
        stem = rel.rsplit("/", 1)[-1][:-3]
        d = perimetre_mesure_detail(rel, racine=r)
        tests = list(d["retenus"]) + [t for t in par_module.get(stem, []) if t not in d["retenus"]]
        if not tests:
            sans_perimetre.append(rel)
            continue
        avec_perimetre.append(rel)
        if any(t not in appuis for t in tests):
            avec_preuve.append(rel)

    n = len(retenus) or 1
    return {
        "modules_vus": len(rels),
        "ecartes": len(ecartes_nommes),
        "ecartes_nommes": ecartes_nommes,
        "denominateur": len(retenus),
        # Deux blocs SEPARES. Aucune cle "score" : il n'y a rien a agreger, et un
        # agregat serait precisement la cible que Goodhart vise.
        "perimetre_non_vide": {"n": len(avec_perimetre),
                               "part": round(100.0 * len(avec_perimetre) / n, 1)},
        "couverture_prouvee": {"n": len(avec_preuve),
                               "part": round(100.0 * len(avec_preuve) / n, 1)},
        "sans_perimetre": sans_perimetre,
    }


def main() -> int:
    r = mesurer_couverture()
    print("modules vus        : %d" % r["modules_vus"])
    print("ecartes            : %d  (%s)" % (r["ecartes"],
                                             " ; ".join(e["motif"][:60] for e in ECARTES)))
    print("DENOMINATEUR       : %d" % r["denominateur"])
    print("perimetre non vide : %d  (%.1f %%)  <- le gain gate peut se prononcer"
          % (r["perimetre_non_vide"]["n"], r["perimetre_non_vide"]["part"]))
    print("couverture prouvee : %d  (%.1f %%)  <- audit seulement, jamais optimisee"
          % (r["couverture_prouvee"]["n"], r["couverture_prouvee"]["part"]))
    print("sans perimetre     : %d modules" % len(r["sans_perimetre"]))
    sortie = ROOT / "sandbox" / "couverture_perimetre.json"
    try:
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print("rapport : %s" % sortie)
    except OSError as e:
        print("rapport NON ecrit (%s: %s) — la mesure ci-dessus reste valide" % (type(e).__name__, e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
