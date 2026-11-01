# -*- coding: utf-8 -*-
"""NR roadmap_next_20261015 : `submit()` de forge_workflow est RENOMME `ecrire_plan` (il ecrit, il ne lance rien).

Decision owner 22/10 : aucun lancement implicite ; l'ancien nom reste un alias DEPRECIE qui AVERTIT, et plus
aucun appelant du depot ne l'utilise.
"""
import re
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _wf():
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_workflow_nr", ROOT / "app" / "forge_workflow.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_submit_est_un_alias_deprecie_qui_avertit(tmp_path):
    wf = _wf()
    wf.ROOT = tmp_path
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = wf.submit({"name": "x", "phases": []})
    assert any(issubclass(x.category, DeprecationWarning) and "ecrire_plan" in str(x.message) for x in w)
    assert "plan_path" in r and "job_id" not in r  # ecrit, ne lance rien


def test_ecrire_plan_n_avertit_pas_et_ne_lance_rien(tmp_path):
    wf = _wf()
    wf.ROOT = tmp_path
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        r = wf.ecrire_plan({"name": "x", "phases": []})
    assert not [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert "rien n'est lance" in r["note"]


def test_aucun_appelant_du_depot_n_utilise_submit():
    motif = re.compile(r"forge_workflow\s+import[^\n]*\bsubmit\b|forge_workflow\.submit\s*\(|\bwf_submit\b")
    fautifs = []
    for d in ("app", "tools"):
        for f in (ROOT / d).rglob("*.py"):
            if "_attic" in f.parts or "__pycache__" in f.parts:
                continue
            if motif.search(f.read_text(encoding="utf-8", errors="replace")):
                fautifs.append(f.relative_to(ROOT).as_posix())
    assert not fautifs, fautifs


def test_le_generateur_wiki_marque_l_alias_deprecie():
    """La page de reference est GENEREE (tools/forge_wiki_modules.py) : la corriger a la main ne tient
    qu'a la regeneration suivante. Le generateur lit la docstring `DÉPRÉCIÉ` et le dit dans la colonne API."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_wiki_modules_nr", ROOT / "tools" / "forge_wiki_modules.py")
    W = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(W)
    fiche = W._lire(ROOT / "app" / "forge_workflow.py")
    assert "submit" in fiche["deprecies"] and "ecrire_plan" not in fiche["deprecies"], fiche["deprecies"]
    api = W._api(fiche)
    assert "`submit` *(déprécié)*" in api and "`ecrire_plan`" in api, api


def test_etiquettes_et_docs_nomment_ecrire_plan():
    keeper = (ROOT / "app" / "forge_keeper_base.py").read_text(encoding="utf-8")
    assert "submit/run_plan" not in keeper
    for doc in ("docs/wiki/20-Modules-Reference.md", "docs/wiki/20-Modules-Reference.fr.md"):
        ligne = [l for l in (ROOT / doc).read_text(encoding="utf-8").splitlines() if "app/forge_workflow.py" in l][0]
        assert "ecrire_plan" in ligne, doc
        assert "`submit`" not in ligne or "déprécié" in ligne, doc
