"""tools/forge_kpi_methode.py - KPI des methodes de dev, mesures et jamais devines.

POURQUOI (decision owner 16/10 : « c'est la mesure qui devra decider de l'adoption des meilleures methodes de dev
selon les cibles » ; SSoT roadmap_p1_methode_dev_par_couches_20261016, piste 6 First Pass Yield). Sans instrument,
« TDD ameliore la qualite » reste une opinion. Deux mesures, chacune avec son denominateur :

* CI de reference au premier passage : verdict de chaque journal `ci_complete_<sha>.txt` (forge_ci_reference),
  regroupe en LOTS (passages consecutifs jusqu'au premier VERT inclus) ; FPY = lots verts du premier coup / lots clos.
* RED cites : part des commits fix/feat dont le corps cite le RED observe (« RED observe ») -- la trace que le test
  a ete vu rouge avant le code (methode TDD imposee par l'owner le 16/10).

Liste BLANCHE (constitution) : n'est VERT que ce qui est PROUVE vert sur tous ses champs. Un journal sans ligne de
preuve, ou une preuve a laquelle il manque un champ, est ILLISIBLE -- ni vert ni rouge, et compte a part.
Limite DITE : un journal par sha ; une relance du meme sha ecrase la precedente, les passages sont SOUS-comptes.

Usage : LAFORGE_PYTHON tools/forge_kpi_methode.py [--journaux C:/tmp/corrections] [--depuis 2026-10-01] [--sortie f]
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/mesure-des-methodes : premier passage de la CI de reference, RED cites"

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAUX_DEFAUT = r"C:/tmp/corrections"
SORTIE_DEFAUT = ROOT / "sandbox" / "workspace" / "kpi_methode.json"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LISTING = re.compile(r"^\s*\d+\s*\|")          # code recopie dans le journal : jamais un verdict
_PREUVE = re.compile(r"^\s*\[preuve\] sha=\S+")
_ZEROS = ("echecs", "erreurs", "timeouts", "blocs_sans_preuve", "declares_absents")
_CORRECTIF = re.compile(r"^(fix|feat)(\(|:)")
_RED = re.compile(r"\bred\s+observ", re.IGNORECASE)


def verdict_journal(texte: str) -> str:
    """VERT / ROUGE / ILLISIBLE d'un journal de CI de reference (derniere ligne de preuve fait foi)."""
    lignes = [_ANSI.sub("", ligne) for ligne in texte.splitlines()]
    lignes = [ligne for ligne in lignes if not _LISTING.match(ligne)]
    idx = [i for i, ligne in enumerate(lignes) if _PREUVE.match(ligne)]
    if not idx:
        return "ILLISIBLE"
    champs = dict(re.findall(r"(\w+)=(\S+)", lignes[idx[-1]]))
    if "etat" not in champs or any(k not in champs for k in _ZEROS):
        return "ILLISIBLE"
    sain = champs["etat"] == "SUITE_COMPLETE" and all(champs[k] == "0" for k in _ZEROS)
    gates = any("Tous les gates bloquants passent" in ligne for ligne in lignes[idx[-1] + 1:])
    return "VERT" if sain and gates else "ROUGE"


def lots_premier_passage(verdicts: list) -> dict:
    """Lots = passages consecutifs jusqu'au premier VERT inclus ; un ILLISIBLE ne compte ni pour ni contre."""
    lots_clos = verts1 = illisibles = 0
    courant = 0
    for v in verdicts:
        if v == "ILLISIBLE":
            illisibles += 1
            continue
        courant += 1
        if v == "VERT":
            lots_clos += 1
            verts1 += courant == 1
            courant = 0
    return {"lots_clos": lots_clos, "verts_premier_passage": verts1, "lot_ouvert": 1 if courant else 0,
            "illisibles": illisibles}


def part_red_cite(commits: list) -> dict:
    """commits = [(sujet, corps)] ; correctif = sujet fix/feat ; red_cite = corps qui cite le RED observe."""
    correctifs = [(s, b) for s, b in commits if _CORRECTIF.match(s or "")]
    return {"correctifs": len(correctifs), "red_cite": sum(1 for _, b in correctifs if _RED.search(b or ""))}


def _commits(depuis: str) -> list:
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "log", "--since=%s" % depuis,
                        "--format=%s%x1f%b%x1e", "alpha"], capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise RuntimeError("git log illisible (rc=%s) : %s" % (r.returncode, (r.stderr or "")[:200]))
    out = []
    for bloc in r.stdout.split("\x1e"):
        if "\x1f" in bloc:
            sujet, corps = bloc.split("\x1f", 1)
            out.append((sujet.strip(), corps.strip()))
    return out


def _valeur(args: list, nom: str, defaut: str) -> str:
    return args[args.index(nom) + 1] if nom in args and args.index(nom) + 1 < len(args) else defaut


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dossier = Path(_valeur(args, "--journaux", JOURNAUX_DEFAUT))
    depuis = _valeur(args, "--depuis", "2026-10-01")
    sortie = Path(_valeur(args, "--sortie", str(SORTIE_DEFAUT)))
    journaux = sorted(dossier.glob("ci_complete_*.txt"), key=lambda p: p.stat().st_mtime) if dossier.exists() else []
    passages = []
    for p in journaux:
        try:
            v = verdict_journal(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            v = "ILLISIBLE"
        passages.append({"journal": p.name, "verdict": v,
                         "date": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()[:16]})
    verdicts = [x["verdict"] for x in passages]
    ci = {"passages": len(passages), "verts": verdicts.count("VERT"), "rouges": verdicts.count("ROUGE"),
          **lots_premier_passage(verdicts)}
    try:
        red = {**part_red_cite(_commits(depuis)), "depuis": depuis}
    except RuntimeError as exc:
        red = {"illisible": str(exc)}
    rapport = {"genere": datetime.now(timezone.utc).isoformat(timespec="seconds"), "journaux": str(dossier),
               "ci": ci, "red": red, "detail": passages,
               "limite": "un journal par sha : une relance du meme sha ecrase la precedente (passages sous-comptes)"}
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    fpy = ("%d/%d" % (ci["verts_premier_passage"], ci["lots_clos"])) if ci["lots_clos"] else "aucun lot clos"
    print("BILAN kpi_methode : CI de reference %d passages (%d verts, %d rouges, %d illisibles) ; lots verts au "
          "1er passage %s ; correctifs citant leur RED %s ; rapport %s"
          % (ci["passages"], ci["verts"], ci["rouges"], ci["illisibles"], fpy,
             ("%d/%d depuis %s" % (red["red_cite"], red["correctifs"], depuis)) if "correctifs" in red
             else "ILLISIBLE", sortie), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
