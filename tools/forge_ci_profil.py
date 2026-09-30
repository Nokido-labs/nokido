"""Profil et comparaison sequentiel/parallele de la suite pure de `ci_local`.

Demande owner du 2026-09-04 : la CI prend ~7 min et il faut l'accelerer. Avant de
paralleliser, il faut SAVOIR ou passe le temps — le meme jour, un seul test coutait
30 s a lui seul (un `LIKE` de prefixe qui balayait 24,9 Go). Paralleliser cela
n'aurait rien donne : on aurait reparti l'attente sur 8 coeurs sans la supprimer.

Deux modes, MEME selection de tests (celle de `ci_local.PURE_TESTS`, lue par AST
pour ne pas importer le module et declencher ses effets de bord) :

  --mode seq   run sequentiel + `--durations` : ou passe le temps
  --mode par   run parallele xdist            : combien on gagne, et a quel prix

Le rapport JSON porte le temps total, le nombre de tests et les echecs. Comparer les
deux modes sur le TEMPS ne suffit pas : un run parallele plus rapide mais qui ne joue
pas les memes tests, ou qui en fait echouer par contention, n'est pas une
optimisation — c'est une perte de couverture deguisee en gain.

Prealable connu (RULES_SHARED) : `ci_local` lance pytest avec
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 et une liste EXPLICITE de plugins. xdist doit donc
y etre ajoute par `-p xdist`, sinon `-n` est refuse. Et `--capture=no`, present dans
la CI, est incompatible avec xdist : le mode parallele ne le passe pas.

Anti-dup : la parallelisation elle-meme existe deja dans `tools/forge_turbo_runner.py`
(xdist, `cpu_count//2`, `--dist=loadscope`), simplement jamais cablee dans la CI. Ce
module-ci ne la reimplemente pas — il MESURE, sur la selection reelle de la CI, ce que
ce cablage rapporterait et ce qu'il casserait.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from multiprocessing import cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / "tools" / "ci_local.py"


def selection_pure() -> list[str]:
    """Lit `PURE_TESTS` de ci_local par AST — sans importer le module.

    L'importer executerait son en-tete (chemins, sondes, env) : on veut la LISTE,
    pas les effets de bord. Rend uniquement les fichiers presents sur le disque,
    comme le fait la CI, et le DIT si certains manquent.
    """
    arbre = ast.parse(CI.read_text(encoding="utf-8", errors="replace"))
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        for cible in noeud.targets:
            if isinstance(cible, ast.Name) and cible.id == "PURE_TESTS":
                brut = [e.value for e in noeud.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                presents = [t for t in brut if (ROOT / t).exists()]
                absents = [t for t in brut if not (ROOT / t).exists()]
                if absents:
                    print("[profil] %d declare(s) absent(s) du disque, non joue(s) : %s"
                          % (len(absents), absents))
                print("[profil] selection : %d fichiers presents / %d declares"
                      % (len(presents), len(brut)))
                return presents
    raise SystemExit("PURE_TESTS introuvable dans ci_local.py")


def _plugins() -> list[str]:
    import importlib.util as u

    out: list[str] = []
    for m in ("pytest_asyncio", "pytest_mock", "pytest_timeout"):
        if u.find_spec(m):
            out += ["-p", m]
    return out


def construire(mode: str, workers: int, tests: list[str], xml: Path,
               dist: str = "loadscope") -> list[str]:
    cmd = [sys.executable, "-m", "pytest", *tests, "-q", "--tb=short",
           "-p", "no:cacheprovider",
           "--basetemp=%s" % (ROOT / "sandbox" / "profil_basetemp"),
           "--junitxml=%s" % xml, *_plugins(), "--timeout=30"]
    if mode == "seq":
        # `--capture=no` reproduit la CI actuelle ; les durees sont l'objet du run.
        cmd += ["--capture=no", "--durations=40", "--durations-min=1.0"]
    else:
        # xdist EXIGE la capture : ne pas passer `--capture=no` ici. `loadscope`
        # regroupe par module, ce qui limite la contention entre tests partageant
        # une ressource — la contention SQLite est le risque principal ici.
        # `loadscope` repartit par CLASSE : les tests d'un meme fichier peuvent
        # atterrir dans des workers differents, donc le VOISINAGE change d'un run a
        # l'autre. Mesure 2026-09-04 : a arbre identique, deux runs successifs ont
        # rendu 38 puis 32 echecs -- un verdict qui bouge sans que le code bouge ne
        # peut pas garder une publication. `loadfile` garde un fichier entier dans un
        # seul worker : si la pollution est intra-fichier, elle devient deterministe.
        cmd += ["-p", "xdist", "-n", str(workers), "--dist=%s" % dist]
    return cmd


def bilan_junit(xml: Path) -> dict | None:
    """Le verdict se lit sur le rapport ECRIT, pas sur le rc (motif de ci_local)."""
    if not xml.exists():
        return None
    try:
        racine = ET.parse(xml).getroot()
    except ET.ParseError:
        return None
    suites = [racine] if racine.tag == "testsuite" else list(racine)
    tests = sum(int(s.get("tests", 0)) for s in suites)
    echecs = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skips = sum(int(s.get("skipped", 0)) for s in suites)
    return {"tests": tests, "echecs": echecs, "skips": skips}


def _collecter(mode: str, workers: int, tests: list[str]) -> tuple[set[str], str]:
    """Rend l'ENSEMBLE des identifiants collectes, sans executer un seul test.

    `--collect-only` est sur : il ne joue rien. C'est le seul moyen de separer un
    ecart de PERIMETRE (des tests que le mode parallele ne voit pas) d'un ecart de
    RESULTAT (des tests qui echouent une fois joues). Tant que le perimetre bouge,
    un gate parallele ne peut pas remplacer le gate sequentiel : il garderait autre
    chose que ce qu'on croit.
    """
    cmd = [sys.executable, "-m", "pytest", *tests, "-q", "--collect-only",
           "-p", "no:cacheprovider", *_plugins()]
    if mode == "par":
        cmd += ["-p", "xdist", "-n", str(workers), "--dist=loadscope"]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "app"),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")

    # Le format n'est PAS `chemin::test` : un `addopts` du pyproject annule le `-q`
    # et pytest rend un ARBRE indente (`<Module x.py>` / `<Function y>`). Mesure
    # 2026-09-04 : chercher « :: » y rendait 0 des deux cotes, ce qui se serait lu
    # comme « perimetres identiques » si le garde de collecte vide n'avait pas
    # refuse de conclure. On parse donc l'arbre, qui ne depend pas de `-q`.
    ids: set[str] = set()
    module = "?"
    for ligne in (r.stdout or "").splitlines():
        nu = ligne.strip()
        if nu.startswith("<Module "):
            module = nu[len("<Module "):].rstrip(">")
        elif nu.startswith("<Function ") or nu.startswith("<TestCaseFunction "):
            nom = nu.split(" ", 1)[1].rstrip(">")
            ids.add("%s::%s" % (module, nom))
        elif "::" in nu and not ligne.startswith(" "):
            ids.add(nu)          # format court, si un jour `-q` reprend le dessus
    diag = "rc=%s | stdout %d o | stderr: %s" % (
        r.returncode, len(r.stdout or ""), (r.stderr or "").strip()[-300:] or "(vide)")
    return ids, diag


def comparer_collecte(workers: int) -> int:
    """Compare les PERIMETRES collectes en sequentiel et en parallele."""
    tests = selection_pure()
    print("[collect] sequentiel...")
    a, err_a = _collecter("seq", 0, tests)
    print("[collect] parallele (%d workers)..." % workers)
    b, err_b = _collecter("par", workers, tests)

    print("\n===== PERIMETRE COLLECTE =====")
    print("sequentiel : %d" % len(a))
    print("parallele  : %d" % len(b))
    if not a or not b:
        # Une collecte VIDE n'est pas « aucun test » : c'est une collecte qui a
        # echoue. Le dire, plutot que de conclure a un ecart de perimetre.
        print("\nUNE COLLECTE EST VIDE — resultat NON concluant, pas un ecart.")
        print("  seq : %s" % err_a)
        print("  par : %s" % err_b)
        return 1

    seul_seq, seul_par = sorted(a - b), sorted(b - a)
    print("\nvus SEULEMENT en sequentiel : %d" % len(seul_seq))
    for t in seul_seq[:30]:
        print("   - " + t[:150])
    print("\nvus SEULEMENT en parallele  : %d" % len(seul_par))
    for t in seul_par[:30]:
        print("   + " + t[:150])
    if not seul_seq and not seul_par:
        print("\nPERIMETRES IDENTIQUES : l'ecart de comptage vient de l'EXECUTION "
              "(workers qui meurent), pas de la collecte.")
    rap = ROOT / "sandbox" / "profil_collect"
    rap.mkdir(parents=True, exist_ok=True)
    (rap / "rapport.json").write_text(json.dumps(
        {"seq": len(a), "par": len(b), "seul_seq": seul_seq, "seul_par": seul_par},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nrapport : %s" % (rap / "rapport.json"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("seq", "par", "collect"), default="seq")
    ap.add_argument("--dist", default="loadscope",
                    choices=("loadscope", "loadfile", "load", "no"),
                    help="strategie de repartition xdist (loadfile = un fichier par "
                         "worker, le plus deterministe)")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() // 2),
                    help="workers xdist (defaut cpu_count//2, comme forge_turbo_runner : "
                         "on laisse des coeurs aux services locaux)")
    a = ap.parse_args()

    if a.mode == "collect":
        return comparer_collecte(a.workers)

    tests = selection_pure()
    sortie = ROOT / "sandbox" / ("profil_%s" % a.mode)
    sortie.mkdir(parents=True, exist_ok=True)
    xml = sortie / "junit.xml"
    if xml.exists():
        xml.unlink()   # jamais juger sur le rapport du run precedent

    cmd = construire(a.mode, a.workers, tests, xml, a.dist)
    print("[profil] mode=%s workers=%s dist=%s"
          % (a.mode, a.workers if a.mode == "par" else "-",
             a.dist if a.mode == "par" else "-"))
    env = dict(os.environ, PYTHONPATH=str(ROOT / "app"),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONIOENCODING="utf-8")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    duree = time.time() - t0

    texte = (r.stdout or "") + (r.stderr or "")
    lentes = [ligne for ligne in texte.splitlines()
              if " call " in ligne or " setup " in ligne or " teardown " in ligne]
    bilan = bilan_junit(xml)

    rapport = {"mode": a.mode, "workers": a.workers if a.mode == "par" else None,
               "dist": a.dist if a.mode == "par" else None,
               "duree_s": round(duree, 1), "rc": r.returncode,
               "fichiers": len(tests), "junit": bilan,
               "lentes": lentes[:40]}
    (sortie / "rapport.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n===== PROFIL %s =====" % a.mode.upper())
    print("duree      : %.1f s" % duree)
    print("rc         : %s (indicatif — le verdict est le JUnit)" % r.returncode)
    print("junit      : %s"
          % (bilan if bilan else "ILLISIBLE — resultat NON concluant"))
    if lentes:
        print("\n--- phases les plus lentes ---")
        for ligne in lentes[:40]:
            print("  " + ligne.strip()[:150])
    else:
        print("\n(aucune phase au-dessus du seuil, ou --durations non demande)")
    print("\nrapport : %s" % (sortie / "rapport.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
