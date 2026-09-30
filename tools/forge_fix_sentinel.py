# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/correctifs-perdus"
SENTINELLE DES CORRECTIFS PERDUS — un fix commite, puis annule sans que
personne ne le voie.

LE MOTIF, MESURE TROIS FOIS LE MEME JOUR (2026-08-14)
=====================================================
L'owner signale « Docker demarre et crash, ENCORE ». Diagnostic :

  43dbf555  fix(docker): daemon off par design n'est pas une panne
  fe9f323d  fix(docker): periode refractaire sur le force-recycle
     -> tous deux emportes par 3aec1500 « revert(docker): abandon pivot
        dockerd-WSL », qui a annule PLUS que son objet.
  0a880f22  avait desarme DOCKER_KEEPER_WSL_SHUTDOWN -> revenu a "1".

Trois correctifs ECRITS, MESURES, COMMITES... et silencieusement rouverts. Le
symptome est revenu a l'identique des semaines plus tard, et il a fallu relire
les memoires pour comprendre qu'on avait DEJA paye ce diagnostic.

Aucun garde ne couvrait ce cas : les tests passent (le code compile), le lint
passe, la revue passe — le defaut n'est pas dans le code present, il est dans
CE QUI A DISPARU. Un `git revert` large est un effecteur qui n'a pas de
periode refractaire et pas d'accuse de reception.

CE QUE LA SENTINELLE FAIT
=========================
Pour chaque commit `fix:`/`feat:` recent, elle releve les ANCRES DURABLES qu'il
a introduites (constantes en MAJUSCULES, definitions de fonctions) et verifie
qu'elles sont ENCORE dans HEAD. Une ancre disparue sans revert qui NOMME le
commit d'origine est un CORRECTIF PERDU.

Volontairement conservatrice — elle doit pouvoir etre lue sans discussion :
- seules les ancres NOMMEES sont suivies (une constante, une fonction), jamais
  des lignes de logique : un refactor legitime renomme, et on ne veut pas crier
  a chaque renommage ;
- un fichier supprime n'est PAS un correctif perdu (suppression assumee) ;
- un revert qui cite le sha d'origine est un retrait ASSUME, donc silencieux.

    LAFORGE_PYTHON tools/forge_fix_sentinel.py                 # 80 derniers fix
    LAFORGE_PYTHON tools/forge_fix_sentinel.py --limit 200 --json
    LAFORGE_PYTHON tools/forge_fix_sentinel.py --depuis 2026-07-01
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ancres DURABLES : ce qui porte un nom et ne devrait pas disparaitre en silence.
# Le `_` initial est OBLIGATOIRE dans le motif : la constante reellement perdue
# le 2026-08-14 s'appelait `_FORCE_RECYCLE_REFRACTORY_S`. Un detecteur qui exige
# une majuscule en tete rate PRECISEMENT le cas qu'il vise — les constantes
# privees d'un module sont les plus fragiles, personne ne les importe ailleurs,
# donc rien ne casse quand elles disparaissent.
_ANCRE_CONST = re.compile(r"^\+\s*(_{0,2}[A-Z][A-Z0-9_]{3,})\s*[:=]")
_ANCRE_DEF = re.compile(r"^\+\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")


def _git(*args: str, timeout: int = 60) -> str:
    """git avec safe.directory : le depot appartient a un AUTRE compte que celui
    qui execute (dubious ownership) — piege paye plusieurs fois."""
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
        capture_output=True, text=True, errors="replace", timeout=timeout,
    )
    return out.stdout or ""


def _commits(limit: int, depuis: str | None) -> list:
    fmt = "%H|%ad|%s"
    args = ["log", f"--format={fmt}", "--date=short", f"-n{limit}",
            "--grep=^fix", "--grep=^feat", "--regexp-ignore-case"]
    if depuis:
        args.append(f"--since={depuis}")
    lignes = [l for l in _git(*args).splitlines() if "|" in l]
    return [dict(zip(("sha", "date", "sujet"), l.split("|", 2))) for l in lignes]


def _ancres(sha: str) -> dict:
    """{fichier: [ancres introduites]} pour un commit."""
    diff = _git("show", sha, "--unified=0", "--format=", "--", "*.py", "*.toml")
    par_fichier: dict = {}
    fichier = None
    for l in diff.splitlines():
        if l.startswith("+++ b/"):
            fichier = l[6:].strip()
            continue
        if not fichier or not l.startswith("+"):
            continue
        m = _ANCRE_CONST.match(l) or _ANCRE_DEF.match(l)
        if m:
            par_fichier.setdefault(fichier, set()).add(m.group(1))
    return {f: sorted(a) for f, a in par_fichier.items()}


def _revert_assume(sha: str) -> bool:
    """Un revert qui NOMME le commit est un retrait assume, pas une perte."""
    court = sha[:8]
    return bool(_git("log", "--format=%H", f"--grep={court}", "--grep=revert",
                     "--all-match", "-n1").strip())


def _remplacement_assume(ancre: str, fichier: str) -> str:
    """'' si l'ancre a ete PERDUE ; sinon le sha du commit qui l'a REMPLACEE.

    MESURE 2026-08-14, premiere passe : 5 alertes dont **3 faux positifs (60 %)**.
    `_MARQUEURS` avait ete retiree par « refactor(intentions): brancher le routeur
    souverain AU LIEU DE marqueurs ecrits a la main », `_tools_now` par une
    refonte « inventaire par union registre + surface ». Ce sont des
    remplacements ANNONCES — mais aucun ne cite le sha d'origine, donc la regle
    « revert qui nomme le commit » ne les voyait pas.

    Le critere qui DISCRIMINE n'est pas le message, c'est la forme du diff : un
    remplacement AJOUTE des ancres dans le meme fichier ; un revert large RETIRE
    sans rien mettre a la place (cas reel : `3aec1500`, qui a emporte deux
    correctifs docker en touchant plusieurs fichiers, sans rien y introduire).
    """
    ligne = _git("log", "--format=%H|%s", "-S", ancre, "-n1", "--", fichier).strip()
    if not ligne or "|" not in ligne:
        return ""
    sha, sujet = ligne.split("|", 1)

    # UN REVERT N'EST JAMAIS UN REMPLACEMENT — meme s'il ajoute des ancres.
    # v2 de ce detecteur ecartait tout commit qui reintroduisait des noms dans le
    # fichier. MESURE qui l'a invalidee : `3aec1500` (« revert(docker): abandon
    # pivot dockerd-WSL »), celui-la meme qui a fait perdre
    # `_FORCE_RECYCLE_REFRACTORY_S`, AJOUTE 3 ancres dans forge_docker_keeper.py
    # — il restaurait l'etat d'avant le pivot. La v2 l'aurait donc classe
    # « remplacement assume » : faux negatif sur le cas de reference, autrement
    # dit un capteur aveugle a la panne qu'il vise.
    # Un revert revient en arriere : par construction il peut emporter le
    # correctif d'un TIERS pose entre-temps. C'est precisement le motif traque.
    if re.match(r"\s*revert", sujet, re.I):
        return ""

    ajoutees = _ancres(sha).get(fichier) or []
    # Hors revert : l'ancre disparait ET le commit en introduit d'autres ICI
    # (refactor annonce « au lieu de X », refonte) -> remplacement assume.
    return sha[:8] if ajoutees else ""


_BLOB_VIVANT: str | None = None


def _corpus_vivant() -> str:
    """Concatene le code VIVANT du depot, une seule fois.

    La sentinelle ne cherchait l'ancre que dans son fichier d'origine : un
    module DEPLACE (app/forge_gdb_live.py -> tools/ctf/forge_gdb_live.py)
    faisait compter ses correctifs comme perdus alors qu'ils avaient
    simplement suivi le code. Mesure du 2026-08-14 : sur les 3 premiers cas
    verifies a la main, 2 etaient de ce type.

    `_attic` est EXCLU volontairement : une ancre qui ne survit que dans
    l'archive est bel et bien sortie du code vivant — la compter presente
    serait le faux-vert symetrique, et c'est exactement le cas de `_vitality`.
    """
    global _BLOB_VIVANT
    if _BLOB_VIVANT is None:
        morceaux = []
        # `recon_silo` et `proxy_deno` manquaient : `push_hosts` a ete declare
        # perdu alors qu'il vit dans `recon_silo/__main__.py` (mesure 14/08).
        # Un corpus incomplet fabrique des disparitions — c'est le meme defaut
        # que de ne chercher que dans le fichier d'origine, a l'echelle du depot.
        for motif in ("app/**/*.py", "tools/**/*.py", "forge_desktop/**/*.py",
                      "recon_silo/**/*.py", "proxy_deno/**/*.py", "tests/**/*.py"):
            for p in ROOT.glob(motif):
                if "_attic" in p.parts or "node_modules" in p.parts:
                    continue
                try:
                    morceaux.append(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
        _BLOB_VIVANT = "\n".join(morceaux)
    return _BLOB_VIVANT


def scanner(limit: int = 80, depuis: str | None = None) -> dict:
    perdus, remplacees, deplacees, examines, ancres_n = [], [], [], 0, 0
    presents = {}
    for c in _commits(limit, depuis):
        examines += 1
        for fichier, ancres in _ancres(c["sha"]).items():
            chemin = ROOT / fichier
            if not chemin.exists():
                continue  # fichier supprime = suppression assumee, pas une perte
            if fichier not in presents:
                try:
                    presents[fichier] = chemin.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
            src = presents[fichier]
            for a in ancres:
                ancres_n += 1
                if a in src:
                    continue
                if _revert_assume(c["sha"]):
                    continue
                remplacee_par = _remplacement_assume(a, fichier)
                if remplacee_par:
                    remplacees.append({"ancre": a, "fichier": fichier,
                                       "par": remplacee_par})
                    continue
                # Test tardif (seulement sur les candidats a la perte, pas sur
                # les ~24 000 ancres) : le cout reste marginal.
                if a in _corpus_vivant():
                    deplacees.append({"ancre": a, "fichier": fichier,
                                      "sha": c["sha"][:8]})
                    continue
                perdus.append({"ancre": a, "fichier": fichier, "sha": c["sha"][:8],
                               "date": c["date"], "sujet": c["sujet"][:90]})
    return {"commits_examines": examines, "ancres_suivies": ancres_n,
            "perdus": perdus, "n_perdus": len(perdus),
            # Declare AUSSI ce qui a ete ecarte : un detecteur qui ne montre que
            # ses trouvailles cache son taux de faux positifs.
            "remplacees_assumees": remplacees, "n_remplacees": len(remplacees),
            # Ancre absente de SON fichier mais vivante AILLEURS = module
            # deplace, pas correctif perdu. Declare a part pour que le taux de
            # faux positifs reste lisible au lieu d'etre noye dans "perdus".
            "deplacees": deplacees, "n_deplacees": len(deplacees)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--depuis", default=None, help="date ISO, ex 2026-07-01")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    res = scanner(a.limit, a.depuis)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 1 if res["n_perdus"] else 0

    print(f"commits examines : {res['commits_examines']} | "
          f"ancres suivies : {res['ancres_suivies']} | "
          f"remplacements assumes ecartes : {res['n_remplacees']}")
    if not res["perdus"]:
        print("[ok] aucun correctif perdu : toutes les ancres introduites sont "
              "encore dans HEAD.")
        return 0
    print(f"\n[ALERTE] {res['n_perdus']} correctif(s) PERDU(S) — introduits par un "
          f"commit puis disparus sans revert qui les nomme :\n")
    for p in res["perdus"]:
        print(f"  {p['sha']} ({p['date']}) {p['fichier']}")
        print(f"      ancre disparue : {p['ancre']}")
        print(f"      commit d'origine : {p['sujet']}")
    print("\nVerifier chacun : `git show <sha>` puis restaurer, ou documenter le "
          "retrait s'il est voulu. Un correctif mesure qui disparait en silence "
          "ramene le symptome des semaines plus tard.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
