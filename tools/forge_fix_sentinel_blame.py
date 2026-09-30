#!/usr/bin/env python3
"""forge_fix_sentinel_blame.py — QUI a supprime chaque correctif perdu.

La sentinelle dit CE QUI manque. Elle ne dit pas QUI l'a retire : sans cela on
ne peut ni juger si la suppression etait assumee, ni voir qu'UN SEUL commit a
emporte dix mecanismes sans rapport entre eux — le motif le plus couteux
observe sur ce depot (cf. `3aec1500`, un revert Docker qui a aussi tue le
garde de `ensure_service`).

Methode : pour chaque ancre perdue, `git log -S<ancre> -- <fichier>` (pickaxe)
liste les commits ou sa presence a CHANGE. Le plus recent l'a supprimee, le
plus ancien l'avait introduite. Aucune heuristique de message n'intervient la —
seul le contenu decide.

Le sujet du commit tueur sert uniquement a CLASSER (revert / refactor / autre),
jamais a conclure : un commit intitule "refactor" peut parfaitement perdre un
correctif, et c'est precisement ce qu'on cherche.

Sortie : sandbox/fix_sentinel_blame.json + rapport groupe par commit tueur.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sandbox" / "fix_sentinel_history.json"
OUT = ROOT / "sandbox" / "fix_sentinel_blame.json"


def _git(*args: str, timeout: int = 60) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "-c", "safe.directory=*", *args],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    return r.stdout or ""


def _classe(sujet: str) -> str:
    s = sujet.lower().strip()
    if re.match(r"revert\b|revert\(", s):
        return "REVERT"
    if s.startswith("refactor"):
        return "REFACTOR"
    if s.startswith("chore") or "rename" in s or "migration" in s:
        return "CHORE"
    return "AUTRE"


def _fonction(fichier: str) -> str:
    """Regroupe par FONCTIONNALITE, pas par fichier : c'est la question posee."""
    n = Path(fichier).stem.replace("forge_", "")
    return {
        "docker_keeper": "docker", "ensure_service": "docker",
        "llama_proxy": "llamacpp", "llamacpp": "llamacpp",
        "rag_engine": "rag", "rag_store": "rag", "rebuild_local": "rag",
        "auto_compact": "rag",
        "ssh": "acces distant", "app": "web hub", "server": "recon",
        "orchestrator": "orchestration", "autonomous_loops": "autonomie",
        "ghost_router": "routage llm", "collab_modes": "routage llm",
        "services_view": "ui desktop",
    }.get(n, n)


def main() -> int:
    if not SRC.exists():
        print(f"[blame] absent : {SRC} — lancer forge_fix_sentinel_job d'abord")
        return 2

    perdus = json.load(open(SRC, encoding="utf-8"))["perdus"]
    lignes, par_tueur = [], {}

    for p in perdus:
        brut = _git("log", "--format=%h|%ad|%s", "--date=short",
                    "-S", p["ancre"], "--", p["fichier"]).strip().splitlines()
        if not brut:
            continue
        sha, date, sujet = (brut[0].split("|", 2) + ["", ""])[:3]
        e = {
            "ancre": p["ancre"], "fichier": p["fichier"],
            "fonction": _fonction(p["fichier"]),
            "introduit_par": p["sha"], "introduit_le": p["date"][:10],
            "supprime_par": sha, "supprime_le": date,
            "sujet_suppression": sujet, "classe": _classe(sujet),
        }
        lignes.append(e)
        par_tueur.setdefault(sha, {"sujet": sujet, "date": date,
                                   "classe": _classe(sujet), "victimes": []})
        par_tueur[sha]["victimes"].append(f"{e['fonction']}:{p['ancre']}")

    classement = sorted(par_tueur.items(), key=lambda kv: -len(kv[1]["victimes"]))
    OUT.write_text(json.dumps({"lignes": lignes, "par_tueur": par_tueur},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[blame] {len(lignes)} pertes attribuees, "
          f"{len(par_tueur)} commit(s) responsable(s)\n")
    for sha, d in classement:
        fonctions = sorted({v.split(":")[0] for v in d["victimes"]})
        print(f"  {sha} {d['date']} [{d['classe']:8s}] {len(d['victimes']):2d} perte(s) "
              f"sur {len(fonctions)} fonctionnalite(s) : {', '.join(fonctions)}")
        print(f"      {d['sujet'][:100]}")
        # Le signal qui compte : un commit qui touche PLUSIEURS fonctionnalites
        # sans rapport a deborde de son intention annoncee.
        if len(fonctions) > 1:
            print(f"      /!\\ DEBORDEMENT : intention annoncee sur un sujet, "
                  f"degats sur {len(fonctions)}")
    print(f"\n[blame] -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
