"""NR -- `main` sort de la circulation : aucun workflow ne doit l'y ramener.

POURQUOI. Le 21/08/2026, `main` est fige au 17/03 et repointe vers `alpha` :
    * ci-selfhosted.yml ne se declenche plus que sur `alpha` (avant : [alpha, main]).
    * le lien CLA pointait vers blob/main/docs/CLA.md -- fichier ABSENT de main
      (404) -- corrige vers blob/alpha/docs/CLA.md, ou il existe.
Sans garde, un copier-coller de trigger ou un lien recolle en `main` re-cablerait
une branche morte a la CI ou renverrait les contributeurs sur un 404. Ce test lit
les .github/workflows REELS sur disque (deterministe, zero reseau) et refuse toute
reintroduction de `main` comme cible de push ou dans un lien blob/main/CLA.

Il n'interdit PAS toute mention de 'main' (un commentaire, une doc historique, ou
`if: github.ref == 'refs/heads/alpha'` restent legitimes) : il vise deux formes
PRECISES qui ont un effet -- le trigger push et le lien CLA casse.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF_DIR = ROOT / ".github" / "workflows"


def _workflows():
    assert WF_DIR.is_dir(), "repertoire workflows absent : %s" % WF_DIR
    return sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))


def _on_block(doc):
    """YAML 1.1 parse la cle `on:` tantot en 'on', tantot en booleen True."""
    if not isinstance(doc, dict):
        return {}
    for k in ("on", True, "on:"):
        if k in doc:
            return doc[k] or {}
    return {}


def _push_branches(on):
    if not isinstance(on, dict):
        return []
    push = on.get("push")
    if not isinstance(push, dict):
        return []
    br = push.get("branches") or []
    return [str(b) for b in br] if isinstance(br, list) else [str(br)]


def test_aucun_workflow_ne_se_declenche_sur_push_main():
    fautifs = []
    for wf in _workflows():
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise AssertionError("YAML invalide dans %s : %s" % (wf.name, e))
        if "main" in _push_branches(_on_block(doc)):
            fautifs.append(wf.name)
    assert not fautifs, (
        "workflow(s) declenche(s) sur push 'main' alors que main est hors circulation : %s "
        "-- retirer main du trigger (cible = alpha)" % fautifs)


def test_aucun_lien_CLA_vers_blob_main():
    fautifs = []
    for wf in _workflows():
        txt = wf.read_text(encoding="utf-8")
        if "blob/main/docs/CLA.md" in txt:
            fautifs.append(wf.name)
    assert not fautifs, (
        "lien CLA vers blob/main/docs/CLA.md (fichier absent de main -> 404) dans : %s "
        "-- repointer vers blob/alpha/docs/CLA.md" % fautifs)


def test_ci_selfhosted_declenche_bien_sur_alpha():
    """Le pendant positif : on a retire main, alpha doit RESTER cible -- sinon la
    CI auto ne tournerait plus du tout (regression silencieuse inverse)."""
    wf = WF_DIR / "ci-selfhosted.yml"
    assert wf.exists(), "ci-selfhosted.yml absent"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert "alpha" in _push_branches(_on_block(doc)), "ci-selfhosted ne se declenche plus sur alpha"
