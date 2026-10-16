"""Verdict des PR Dependabot, pose en UN commentaire -- la fusion reste HUMAINE (decision owner du 2026-10-14).

Pourquoi un outil a part : la LOGIQUE de verdict vit dans tools/forge_deps_reconcilier.py (memes regles que
`classer`), mais cet outil d'analyse ne lance aucun processus (garde test_l_outil_n_installe_rien : une installation
depuis un outil d'analyse serait un effet de bord invisible). Les entrees-sorties GitHub (lire la PR par `gh`, poser
ou mettre a jour le commentaire) vivent donc ICI, et seulement ici.

    python tools/forge_dependabot_verdict.py --pr N --ci success [--depot OWNER/REPO] [--poster]
    python tools/forge_dependabot_verdict.py --titre "..." --corps-fichier c.md [--diff-fichier d.diff] --ci success

Ne fusionne, n'approuve ni ne ferme RIEN. Appele par .github/workflows/dependabot-verdict.yml a la fin de la CI de
quarantaine.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : verdict commente des PR Dependabot (fusion humaine)"

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_deps_reconcilier as R  # noqa: E402


def _gh(*args: str, entree: str = None):
    return subprocess.run(["gh", *args], input=entree, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def lire_pr(depot: str, numero: int) -> tuple:
    """(titre, corps, diff) ou leve RuntimeError en NOMMANT ce qui manque. Un diff illisible est dit, pas tu."""
    r = _gh("pr", "view", str(numero), "-R", depot, "--json", "title,body")
    if r.returncode:
        raise RuntimeError("PR %s ILLISIBLE (gh rc=%d) : %s" % (numero, r.returncode, r.stderr.strip()[:200]))
    pr = json.loads(r.stdout)
    d = _gh("pr", "diff", str(numero), "-R", depot)
    if d.returncode:
        print("diff ILLISIBLE (gh rc=%d) : verdict sur le corps seul, et DIT" % d.returncode)
    return pr.get("title", ""), pr.get("body", ""), (d.stdout if d.returncode == 0 else "")


def poser(depot: str, numero: int, texte: str) -> int:
    """Pose OU met a jour l'unique commentaire marque -- jamais un second."""
    lus = _gh("api", "--paginate", "repos/%s/issues/%d/comments" % (depot, numero),
              "--jq", '.[] | select(.body | contains("%s")) | .id' % R.MARQUEUR_VERDICT)
    if lus.returncode:
        print("commentaires ILLISIBLES (gh rc=%d) : rien pose, pour ne pas en creer un second" % lus.returncode)
        return 2
    ids = lus.stdout.split()
    if ids:
        r = _gh("api", "-X", "PATCH", "repos/%s/issues/comments/%s" % (depot, ids[-1]), "-F", "body=@-", entree=texte)
    else:
        r = _gh("pr", "comment", str(numero), "-R", depot, "--body-file", "-", entree=texte)
    print("commentaire %s : rc=%d %s" % ("MIS A JOUR" if ids else "POSE", r.returncode, r.stderr.strip()[:200]))
    return 0 if r.returncode == 0 else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--depot", default="Nokido-labs/nokido-private")
    ap.add_argument("--ci", default=None, help="conclusion de la CI de quarantaine (success, failure...)")
    ap.add_argument("--poster", action="store_true")
    ap.add_argument("--titre", default=None, help="hors ligne : titre de la PR")
    ap.add_argument("--corps-fichier", default=None)
    ap.add_argument("--diff-fichier", default=None)
    a = ap.parse_args(argv)
    if a.titre is not None:
        titre = a.titre
        corps = Path(a.corps_fichier).read_text(encoding="utf-8") if a.corps_fichier else ""
        diff = Path(a.diff_fichier).read_text(encoding="utf-8") if a.diff_fichier else ""
    elif a.pr is not None:
        try:
            titre, corps, diff = lire_pr(a.depot, a.pr)
        except RuntimeError as e:
            print(e)
            return 2
    else:
        ap.error("--pr ou --titre requis")
    texte = R.texte_verdict(R.verdict_pr(titre, corps, a.ci or "inconnue", diff))
    print(texte)
    if a.poster and a.pr is not None:
        return poser(a.depot, a.pr, texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
