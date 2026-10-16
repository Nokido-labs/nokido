#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_lean_verify -- l'organe de VERIFICATION formelle de Nokido : Lean juge, Nokido porte.

Decision owner du 15/10 : « Nokido des maintenant » -- Lean n'est pas l'affaire d'une session d'agent (AGY a ecrit
l'amorce `formel/`), c'est un organe du corps, deterministe, local, sans aucun token. Trois controles, dans l'ordre :

  1. SOURCES : aucun `sorry`, aucune declaration `axiom` dans `formel/**/*.lean` (commentaires ignores) ;
  2. BUILD : `lake build` doit reussir, et aucune declaration n'est signalee « uses 'sorry' » ;
  3. AXIOMES : chaque `#print axioms` de la sortie est lu ; un axiome hors de la liste BLANCHE du noyau
     (propext, Quot.sound, Classical.choice) refuse la preuve. Aucun theoreme lu = rien n'a ete verifie.

Trois verdicts, jamais deux : PROUVE · REFUSE · INCONNU. Lean introuvable ou inexecutable (mesure du 15/10 : le
compte du bac du hub, qui est celui de la CI, se voit REFUSER l'acces a ~/.elan de l'owner) = INCONNU, dit, jamais
un vert. La boucle de preuve qui produit les preuves est un autre organe (forge_lean_prove) ; celui-ci ne fait
que juger, et ne fait confiance a aucun agent.

Usage : LAFORGE_PYTHON tools/forge_lean_verify.py [--projet formel] [--json]   (rc 0 PROUVE, 1 REFUSE, 2 INCONNU)
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/preuve_formelle : juge Lean (lake build, sorry, axiomes par liste blanche), INCONNU sans Lean"

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AXIOMES_NOYAU = frozenset({"propext", "Quot.sound", "Classical.choice"})
_RE_AXIOMES = re.compile(r"'([^']+)' depends on axioms: \[([^\]]*)\]")
_RE_SANS_AXIOME = re.compile(r"'([^']+)' does not depend on any axioms")
_RE_SORRY_SIGNALE = re.compile(r"declaration uses 'sorry'")


def _sans_commentaires(source: str) -> str:
    source = re.sub(r"/-.*?-/", " ", source, flags=re.S)
    return "\n".join(ligne.split("--", 1)[0] for ligne in source.splitlines())


def controler_sources(projet: Path) -> list:
    """Fautes des sources : (fichier, motif). Le dossier de build `.lake` n'est pas lu."""
    fautes = []
    for f in sorted(projet.rglob("*.lean")):
        if ".lake" in f.parts:
            continue
        code = _sans_commentaires(f.read_text(encoding="utf-8", errors="replace"))
        if re.search(r"\bsorry\b", code):
            fautes.append((str(f.relative_to(projet)), "sorry"))
        if re.search(r"(?m)^\s*(?:private\s+|noncomputable\s+)*axiom\s", code):
            fautes.append((str(f.relative_to(projet)), "axiom declare"))
    return fautes


def lire_axiomes(sortie: str) -> dict:
    """{theoreme: [axiomes]} lus dans la sortie de `#print axioms`."""
    lus = {nom: [a.strip() for a in liste.split(",") if a.strip()] for nom, liste in _RE_AXIOMES.findall(sortie)}
    lus.update({nom: [] for nom in _RE_SANS_AXIOME.findall(sortie)})
    return lus


ELAN_HOME_NOKIDO = ROOT / "runtime" / "elan"


def _env_pour(lake: str) -> dict | None:
    """Une chaine de NOKIDO (`<depot>/runtime/elan/bin/lake`, posee par forge_lean_provision) se lance avec SON
    ELAN_HOME, deduit du chemin -- celle du depot courant comme celle du depot principal vue d'un worktree ;
    une autre chaine garde l'environnement courant."""
    p = Path(lake)
    if not (p.parent.name == "bin" and p.parent.parent.name == "elan" and p.parent.parent.parent.name == "runtime"):
        return None
    try:
        import forge_lean_provision
    except ImportError:
        from nokido_agent.tools import forge_lean_provision
    return forge_lean_provision.env_lean(p.parent.parent)


def _racine_principale() -> Path | None:
    """Racine du depot PRINCIPAL quand on tourne dans un worktree (CI de reference, preuve) : `runtime/` n'est pas
    versionne, il n'existe que la-bas. None si git est muet (dit par l'absence, jamais devine)."""
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "rev-parse", "--path-format=absolute",
                            "--git-common-dir"], capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    commun = (r.stdout or "").strip()
    return Path(commun).parent if r.returncode == 0 and commun else None


def trouver_lake() -> tuple:
    """(chemin de lake ou None, raison). NOKIDO_LEAN_BIN (dossier), puis la chaine de NOKIDO (runtime/elan),
    puis le PATH, puis ~/.elan/bin -- celle de l'owner, illisible par les comptes du hub (mesure 15/10)."""
    exe = "lake.exe" if os.name == "nt" else "lake"
    candidats = []
    if os.environ.get("NOKIDO_LEAN_BIN"):
        candidats.append(Path(os.environ["NOKIDO_LEAN_BIN"]) / exe)
    candidats.append(ELAN_HOME_NOKIDO / "bin" / exe)
    principale = _racine_principale()
    if principale is not None and principale.resolve() != ROOT.resolve():
        candidats.append(principale / "runtime" / "elan" / "bin" / exe)
    trouve = shutil.which("lake")
    if trouve:
        candidats.append(Path(trouve))
    candidats.append(Path.home() / ".elan" / "bin" / exe)
    raisons = []
    for c in candidats:
        if not c.exists():
            raisons.append("%s : absent" % c)
            continue
        try:
            r = subprocess.run([str(c), "--version"], capture_output=True, text=True, errors="replace", timeout=60,
                               env=_env_pour(str(c)))
        except (OSError, subprocess.SubprocessError) as exc:  # acces refuse, absent : on essaie le suivant, et on le DIT
            raisons.append("%s : %s" % (c, type(exc).__name__))
            continue
        if r.returncode == 0:
            return str(c), (r.stdout or "").strip()[:120]
        raisons.append("%s : rc %s" % (c, r.returncode))
    return None, "lake introuvable ou inexecutable -- " + " ; ".join(raisons)[:400]


def verifier(projet: Path = ROOT / "formel", lancer=None, lake=None) -> dict:
    """Verdict PROUVE / REFUSE / INCONNU, avec ses preuves. `lancer(cmd, cwd)` -> (rc, sortie) est injectable."""
    projet = Path(projet)
    if not projet.is_dir():
        return {"etat": "INCONNU", "raison": "projet Lean absent : %s" % projet}
    fautes = controler_sources(projet)
    if fautes:
        return {"etat": "REFUSE", "raison": "sources", "fautes": fautes}
    version = ""
    if lancer is None:
        if lake is None:
            lake, version = trouver_lake()
            if not lake:
                return {"etat": "INCONNU", "raison": version}

        def lancer(cmd, cwd):
            p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1800, env=_env_pour(cmd[0]))
            return p.returncode, (p.stdout or "") + (p.stderr or "")
    rc, sortie = lancer([lake or "lake", "build"], projet)
    if rc != 0:
        return {"etat": "REFUSE", "raison": "lake build rc %s" % rc, "sortie": sortie[-1500:]}
    if _RE_SORRY_SIGNALE.search(sortie):
        return {"etat": "REFUSE", "raison": "Lean signale une declaration qui utilise sorry"}
    theoremes = lire_axiomes(sortie)
    if not theoremes:
        return {"etat": "INCONNU", "raison": "build reussi mais AUCUN `#print axioms` lu : rien n'a ete verifie"}
    hors = {t: [a for a in ax if a not in AXIOMES_NOYAU] for t, ax in theoremes.items()}
    hors = {t: ax for t, ax in hors.items() if ax}
    if hors:
        return {"etat": "REFUSE", "raison": "axiome(s) hors liste blanche du noyau", "hors_liste": hors}
    return {"etat": "PROUVE", "theoremes": theoremes, "lake": version}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    projet = ROOT / "formel"
    if "--projet" in argv:
        projet = Path(argv[argv.index("--projet") + 1])
        if not projet.is_absolute():
            projet = ROOT / projet
    v = verifier(projet)
    if "--json" in argv:
        print(json.dumps(v, ensure_ascii=False, indent=2))
    else:
        print("[lean] %s -- %s" % (v["etat"], v.get("raison") or "%d theoreme(s) verifie(s)" % len(v["theoremes"])))
    return {"PROUVE": 0, "REFUSE": 1}.get(v["etat"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
