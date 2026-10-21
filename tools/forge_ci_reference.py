"""tools/forge_ci_reference.py - CI de REFERENCE d'un sha, en UN etage par defaut.

POURQUOI (owner 2026-10-15 : « les accelerations CI oui bien sur »). Jusqu'ici chaque CI de
reference etait un script recopie par sha (32 copies `C:/tmp/corrections/ci_reference_<sha>.py`
le 15/10) qui jouait DEUX etages : `ci_local --reference SHA --no-tests --no-mutation` (les
gates), puis `--turbo` complet -- qui REJOUAIT toutes les gates, ui-acceptance compris
(5,5 min). Mesure du 15/10 : ~27 min, dont ~8 min de gates en double.
`ci_local` n'arrete rien sur une gate rouge (gates, mutation, pytest et UI s'enchainent, le
resume final juge) : l'etage 1 n'evitait que le cout des tests quand une gate est rouge. Un
seul etage rend le meme verdict ~8 min plus tot quand tout est vert ; `--deux-etages` garde
l'ancienne forme pour un lot a risque.

⚠️ AUCUNE CI de reference sans GO explicite de l'owner (regle du 14/10) : cet outil ne se
lance jamais de lui-meme.

Usage :
    run_job script=tools/forge_ci_reference.py script_args="--sha <SHA>"
    run_job script=tools/forge_ci_reference.py script_args="--sha <SHA> --deux-etages"
Journaux entiers : <dossier>/ci_<etage>_<sha>.txt ; lignes de verdict sur stdout.
"""
# nokido-compte: hors_ligne  -- cree un worktree git ; online = REFUS `.git/worktrees: Permission denied` (15/10)
from __future__ import annotations

__FORGE_COLOR__ = "qualite/ci-de-reference : certifie un sha en un etage"

import argparse
import contextlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOSSIER_DEFAUT = r"C:/tmp/corrections"
CLES = ("[preuve]", "Tous les gates", "FAIL (", "SUITE_", " failed", "CONFORME", "CAPTURED", "[turbo]",
        "[repris")


def plan(sha: str, deux_etages: bool = False) -> list:
    """[(etage, arguments de ci_local, delai_s)] -- la forme est testee sans rien lancer."""
    complete = ("complete", ["--reference", sha, "--turbo"], 7200)
    if not deux_etages:
        return [complete]
    return [("gates", ["--reference", sha, "--no-tests", "--no-mutation"], 3000), complete]


def jouer(etage: str, args: list, delai: int, sha: str, dossier: Path, executer=subprocess.run) -> int:
    r = executer([sys.executable, "tools/ci_local.py", *args], cwd=ROOT,
                 capture_output=True, text=True, errors="replace", timeout=delai)
    lignes = ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / ("ci_%s_%s.txt" % (etage, sha))).write_text("\n".join(lignes), encoding="utf-8")
    cles = [l for l in lignes if "[preuve]" in l or (any(k in l for k in CLES) and "ci_proof.json" not in l)]
    print("===== %s rc=%s (%d lignes)" % (etage, r.returncode, len(lignes)), flush=True)
    print("\n".join(x[:260] for x in cles[-40:]) or "(aucune ligne de verdict)", flush=True)
    return r.returncode


# Temoin « CI de reference EN COURS » (15/10) : la regle owner « aucune charge de ma part pendant une CI » (payee
# 2x le 29/09) n'etait qu'ecrite -- le 15/10, trois sessions pytest de l'agent ont tourne pendant la suite pure, et un
# worker xdist s'est ecrase (cause non etablie, chevauchement etabli). Le gate de capacites lit ce temoin et refuse
# la charge tant que le processus qui l'a pose VIT (pid + heure de creation : un pid reutilise ne compte pas).
TEMOIN_CI = ROOT / "sandbox" / "ci_reference_en_cours.json"


def poser_temoin(sha: str, chemin: Path = TEMOIN_CI) -> bool:
    import json
    import os
    import time
    try:
        import psutil
        cree = psutil.Process(os.getpid()).create_time()
    except Exception:  # noqa: BLE001  # muet-ok : sans heure de creation, le gate retombe sur l'age du temoin
        cree = None
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"pid": os.getpid(), "cree": cree, "sha": sha, "debut": time.time()}),
                          encoding="utf-8")
        return True
    except OSError as exc:
        print("[temoin] NON pose (%s) : le gate ne saura pas qu'une CI tourne" % type(exc).__name__, flush=True)
        return False


def retirer_temoin(chemin: Path = TEMOIN_CI) -> None:
    try:
        chemin.unlink(missing_ok=True)
    except OSError as exc:
        print("[temoin] NON retire (%s) : le gate le jugera perime par le pid" % type(exc).__name__, flush=True)


IDENTITE = "CI_REFERENCE"


def _bail(sha: str):
    """Bail de priorite au hub sous l'identite PROPRE de la CI (decision owner 16/10, forme a).

    Mesure 16/10 : bail ARME depuis le 14/10, jamais pris -- la CI, son client prevu, ne le demandait pas.
    Arme, il exige ring <= 3 : CI_REFERENCE est ring 2, jeton FORGE_TOKEN_CI_REFERENCE au coffre. Ne leve
    jamais : une regulation injoignable se DIT et la CI continue sans priorite."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_resource_manager import bail_priorite
    except Exception as e:  # noqa: BLE001
        return contextlib.nullcontext({"ok": False, "error": "REGULATION_INDISPONIBLE(%s)" % type(e).__name__})
    return bail_priorite("CI de reference %s" % sha, classe="court", ttl_s=3600.0, agent=IDENTITE)


def _dire_bail(res) -> str:
    res = res or {}
    b = res.get("bail") or {}
    if b.get("id"):
        # Le bail porte `mode` (ARME | OBSERVATION) ; absent = INCONNU, jamais range d'un cote par defaut.
        return "PRIS %s (%s)" % (b["id"], b.get("mode") or "mode INCONNU")
    return "NON PRIS (%s) -- la CI continue sans priorite" % (res.get("error") or res.get("detail") or "?")


def main(argv=None, executer=subprocess.run, bail=None) -> int:
    ap = argparse.ArgumentParser(description="CI de reference d'un sha (un etage par defaut)")
    ap.add_argument("--sha", required=True, help="sha a certifier (celui qu'on poussera)")
    ap.add_argument("--deux-etages", action="store_true",
                    help="gates seules d'abord ; la suite complete seulement si elles sont vertes")
    ap.add_argument("--dossier", default=DOSSIER_DEFAUT, help="ou ecrire les journaux entiers")
    a = ap.parse_args(argv)
    sha = (a.sha or "").strip()
    if not sha:
        print("REFUS : --sha vide -- une reference certifie un sha NOMME, jamais l'arbre courant", flush=True)
        return 2
    dossier = Path(a.dossier)
    ch = executer([sys.executable, "tools/forge_changelog.py", "--check", "--jusqua", sha], cwd=ROOT,
                  capture_output=True, text=True, errors="replace", timeout=120)
    print("changelog --check rc=%s : %s" % (ch.returncode, ((ch.stdout or ch.stderr) or "").strip()[:200]),
          flush=True)
    etapes = plan(sha, a.deux_etages)
    print("forme : %s" % (" puis ".join(e for e, _a, _d in etapes)), flush=True)
    rc = 0
    reelle = executer is subprocess.run   # un test qui simule l'executeur ne pose pas de temoin dans le depot
    if reelle:
        poser_temoin(sha)
    if bail is None:
        # Seule une execution REELLE demande le bail : un test qui simule l'executeur n'endort jamais
        # un service du poste.
        bail = _bail if reelle else (lambda _sha: contextlib.nullcontext({"ok": False, "error": "SIMULE"}))
    try:
        with bail(sha) as pris:
            print("bail de priorite : %s" % _dire_bail(pris), flush=True)
            for etage, args, delai in etapes:
                rc = jouer(etage, args, delai, sha, dossier, executer)
                if rc != 0 and etage != "complete":
                    print("GATES ROUGES : suite complete NON lancee", flush=True)
                    return rc
            return rc
    finally:
        if reelle:
            retirer_temoin()


if __name__ == "__main__":
    for _flux in (sys.stdout, sys.stderr):
        if hasattr(_flux, "reconfigure"):
            _flux.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
