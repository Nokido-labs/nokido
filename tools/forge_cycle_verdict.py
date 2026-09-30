"""Certifier un cycle de dev collaboratif : le NR fait foi, pas le rapport de l'agent.

__FORGE_COLOR__ = "qualite/certification"

CE QUE CE FICHIER N'EST PAS : un second arbitre. `app/forge_swarm_evidence.arbitrer`
tranche deja, et bien -- refus de surete dominant, voix INDEPENDANTES plutot que
majorite, preuve avant popularite, abstention traitee comme une reussite. Il avait
**un seul importeur** : une these juste et non branchee. On lui donne a manger.

CE QU'IL AJOUTE, et pourquoi (cycle 1, 2026-09-07). Le contrat de delegation retenu
vient de la veille (`watch_e9ef7213e2_294`, « define tests upfront as completion
signals ») : on ne remet pas une consigne en prose a un executant, on lui remet un NR
ROUGE. Ce contrat a un trou evident -- **rendre le NR vert en modifiant le NR**. Le
signal de completion doit donc etre EMPREINTE au moment du dispatch et re-verifie a la
livraison ; sinon la cible bouge avec le tireur.

Mesure du premier cycle, qui a paye ce manque : WORKER_CODE a livre correctement, mais
je n'avais capture aucune empreinte au depart. `git diff` est MUET sur un fichier non
tracke -- son silence ne prouve donc rien (« ne jamais conclure d'une source qui se
tait »). Il a fallu recouper mtime et taille apres coup. Cette fonction existe pour que
ce recoupement ne soit plus a refaire de tete.

Trois etats partout : LU / ABSENT / ILLISIBLE. Un rapport absent n'est pas un vert, et
une cible deplacee n'est pas un echec -- c'est une mesure invalide, ce qui se dit
autrement a l'executant.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_scorecard import ExecutionState, evaluate_symbolic  # noqa: E402
from nokido_agent.app.forge_swarm_evidence import Tentative, arbitrer  # noqa: E402


def scorecard(fichiers) -> dict:
    """Le juge CANONIQUE du manifesto, applique aux fichiers livres.

    « Aucun LLM ne juge un autre LLM dans la voie critique » (declaration 2), et la
    chaine de §3.4 passe par `forge_scorecard`. Mesure du 2026-09-07 : cette chaine
    n'existait pas -- les trois evaluateurs du module avaient ZERO appelant, le seul
    usage vivant s'en servait comme FORMAT de sortie, et aucun test ne le couvrait.
    Cette fonction en est le premier appelant reel.

    On appelle `evaluate_symbolic` et JAMAIS `evaluate_code` : ce dernier convoque un
    juge LLM, ce qui reintroduirait exactement ce que la declaration 2 interdit.

    Trois etats par fichier, jamais un grade neutre invente :
      LU     mesure faite, grade et score portes
      ABSENT le fichier n'est pas la -- on le DIT, on ne le note pas
      VETO   l'AST ne parse pas ; premier axe du juge, veto par construction
    """
    fiches: dict = {}
    for f in fichiers:
        p = Path(f)
        if not p.exists():
            fiches[str(p)] = {"etat": "ABSENT", "grade": None, "score": None,
                              "critique": "fichier introuvable"}
            continue
        sc = evaluate_symbolic(str(p))
        etat = "VETO" if sc.state == ExecutionState.CRASHED else "LU"
        fiches[str(p)] = {"etat": etat, "grade": sc.grade.value,
                          "score": round(sc.confidence_score, 4),
                          "critique": sc.critique}
    return fiches


def empreinte(chemin) -> str:
    """sha256 du signal de completion, ou 'ABSENT' -- jamais une chaine vide.

    Une empreinte vide comparee a une empreinte vide serait « identique » : le garde
    s'ouvrirait exactement quand il ne peut pas voir.
    """
    p = Path(chemin)
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "ABSENT"
    except OSError as exc:
        return "ILLISIBLE:%s" % type(exc).__name__


def lire_junit(chemin) -> dict | None:
    """Bilan du rapport JUnit, ou None si on N'A PAS PU LIRE.

    `None` n'est pas « zero echec » : c'est l'absence de mesure. Deux fois paye le
    2026-09-07 -- un verdict conclu a l'oeil quand le rapport disait `failures="1"`,
    puis un pytest tue avant d'ecrire son rapport, ou le gate a eu raison de refuser
    de racheter un rc non nul sans preuve ecrite.
    """
    try:
        arbre = ET.parse(Path(chemin))
    except (OSError, ET.ParseError):
        return None
    total = {"tests": 0, "failures": 0, "errors": 0}
    suites = arbre.getroot().iter("testsuite")
    vu = False
    for s in suites:
        vu = True
        for cle in total:
            total[cle] += int(s.get(cle) or 0)
    return total if vu else None


def mesurer(nr, cwd=None) -> tuple[dict | None, str]:
    """Chemin REEL : empreinte AVANT, pytest, puis lecture du rapport structure.

    L'empreinte se prend avant l'execution : c'est la cible telle qu'elle a ete jugee.
    """
    nr = Path(nr)
    emp = empreinte(nr)
    dossier = Path(cwd or nr.parent)
    rapport = dossier / ("junit_%s.xml" % nr.stem)
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", str(nr), "-q", "-p", "no:cacheprovider",
         "--junitxml=%s" % rapport],
        # `errors="replace"` est OBLIGATOIRE avec `text=True` : sans lui, un octet
        # non decodable dans la sortie fait crasher le thread lecteur de subprocess
        # (anti-regression de l'incident 47 Go, gate firehose). Une sortie de test
        # peut contenir n'importe quoi.
        cwd=str(dossier), capture_output=True, text=True, errors="replace",
        timeout=300, check=False)
    return lire_junit(rapport), emp


def tentative(*, agent: str = "", modele: str = "", strategie: str = "",
              solution_id: str = "", junit: dict | None = None,
              empreinte_attendue: str = "", empreinte_constatee: str = "",
              preuves: list | None = None, scorecard: dict | None = None) -> Tentative:
    """Une livraison devient une OBSERVATION -- jamais directement un verdict.

    La cible deplacee est traitee en `format_ok=False`, pas en `test_ok=False` : on ne
    dit pas a l'executant « ta solution est fausse », on dit « je n'ai pas pu la
    juger ». La distinction change la reprise, et c'est deja la semantique portee par
    `Tentative.utilisable`.
    """
    deplacee = empreinte_attendue != empreinte_constatee
    # UN FICHIER LIVRE QUI NE PARSE PAS EST UN VETO, meme sous des tests verts : un
    # JUnit vert sur un fichier qui ne parse pas prouve seulement qu'il n'est pas
    # exerce. C'est le premier axe du juge canonique, et le manifesto en fait un veto.
    fiches = dict(scorecard or {})
    vetos = [c for c, v in fiches.items() if v.get("etat") == "VETO"]
    if junit is None:
        test_ok = None
    else:
        test_ok = (junit.get("tests", 0) > 0
                   and junit.get("failures", 0) == 0
                   and junit.get("errors", 0) == 0)
    # Le grade entre dans les PREUVES : « tu peux remonter chaque verdict a une
    # metrique calculee » (manifesto §2.3). Un juge qui ne laisse pas de trace dans
    # la preuve ne rend pas le verdict tracable.
    traces = list(preuves or ([] if junit is None else ["junit"]))
    for chemin, v in fiches.items():
        if v.get("etat") == "LU":
            traces.append("scorecard:%s:%s:%s" % (Path(chemin).name, v["grade"], v["score"]))

    invalide = deplacee or bool(vetos)
    if deplacee:
        motif = ("cible deplacee : le signal de completion a ete modifie "
                 "(attendu %s, constate %s)" % (empreinte_attendue[:12],
                                                empreinte_constatee[:12]))
    elif vetos:
        motif = ("veto du juge symbolique : %d fichier(s) livre(s) ne parsent pas (%s)"
                 % (len(vetos), ", ".join(Path(c).name for c in vetos[:3])))
    else:
        motif = None

    return Tentative(
        worker=agent, modele=modele, strategie=strategie, runtime="agent",
        solution_id=solution_id,
        format_ok=False if invalide else True,
        test_ok=None if invalide else test_ok,
        erreur=motif,
        preuves=traces,
    )


def verdict(tentatives, min_voix: int = 2, exiger_preuve: bool = True):
    """DELEGUE a l'organe existant. Aucune regle de decision ne vit ici."""
    return arbitrer(list(tentatives), min_voix=min_voix, exiger_preuve=exiger_preuve)


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--nr", required=True, help="le signal de completion")
    ap.add_argument("--empreinte-attendue", default="",
                    help="empreinte capturee AU DISPATCH ; vide = premiere capture")
    ap.add_argument("--agent", default="")
    ap.add_argument("--modele", default="")
    ap.add_argument("--strategie", default="")
    ap.add_argument("--solution-id", default="")
    ap.add_argument("--min-voix", type=int, default=2)
    a = ap.parse_args()

    bilan, emp = mesurer(a.nr)
    if not a.empreinte_attendue:
        print(json.dumps({"capture": emp, "nr": a.nr, "bilan": bilan}, ensure_ascii=False))
        return 0
    t = tentative(agent=a.agent, modele=a.modele, strategie=a.strategie,
                  solution_id=a.solution_id or "solution", junit=bilan,
                  empreinte_attendue=a.empreinte_attendue, empreinte_constatee=emp)
    v = verdict([t], min_voix=a.min_voix)
    print(json.dumps({"etat": v.etat, "action": v.action, "motif": v.motif,
                      "bilan": bilan, "cible_intacte": emp == a.empreinte_attendue},
                     ensure_ascii=False))
    return 0 if v.action == "accept" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
