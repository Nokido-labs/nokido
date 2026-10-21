"""NR 18/10 -- reconciliateur (decision owner : « reconciliateur seul d'abord »), extension de tools/forge_merge_gate.py.

Mesures du 18/10 : les commits d'executeurs embarquent des restes (90bc00bee : 8 fichiers pour 2 autorises ; c4f627a9f :
8 pour 5) ; le merge gate existant fusionne une branche wip/<agent> ENTIERE et exige AMELIORE (un correctif TDD se prouve
par son RED, pas par un gain de duree) ; les branches reelles sont agent/opencode_*. Chaque integration a ete refaite a la
main (relecture du diff, fichiers nommes seuls, commit citant l'origine). Contrat du mode reconciliation :
  * `plan_reconciliation(fichiers_du_commit, fichiers_nommes)` : a_integrer = intersection ; hors_consigne = fichiers du
    commit NON nommes (ecartes ET dits) ; manquants = nommes absents du commit (la tache n'a pas tout livre) ;
  * `reconcilier(sha, fichiers_nommes, apply=False)` en dry-run ne lance AUCUNE commande git qui ecrit
    (checkout/commit/merge) et rend le plan ;
  * le message de commit d'integration cite le sha d'origine.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("forge_merge_gate_reco_nr", ROOT / "tools" / "forge_merge_gate.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    return m


def test_le_plan_ecarte_et_nomme_les_fichiers_hors_consigne():
    m = _module()
    p = m.plan_reconciliation(
        ["app/a.py", "tests/nr/test_a_nr.py", "tools/forge_task_executor.py", "tests/nr/test_copie_nr.py"],
        ["app/a.py", "tests/nr/test_a_nr.py", "app/b.py"])
    assert sorted(p["a_integrer"]) == ["app/a.py", "tests/nr/test_a_nr.py"]
    assert sorted(p["hors_consigne"]) == ["tests/nr/test_copie_nr.py", "tools/forge_task_executor.py"]
    assert p["manquants"] == ["app/b.py"]


def test_le_dry_run_n_ecrit_rien_et_rend_le_plan(monkeypatch):
    m = _module()
    appels = []

    def faux_git(args, cwd=None):
        appels.append(list(args))
        if args[:2] == ["show", "--name-only"] or "--name-only" in args:
            return 0, "app/a.py\ntools/x.py", ""
        return 0, "", ""
    monkeypatch.setattr(m, "_git", faux_git)
    r = m.reconcilier("abc1234", ["app/a.py"], apply=False)
    ecritures = [a for a in appels if a and a[0] in ("checkout", "commit", "merge", "add", "cherry-pick")]
    assert ecritures == [], "un dry-run a lance une commande git qui ecrit : %s" % ecritures
    assert r["plan"]["a_integrer"] == ["app/a.py"] and r["plan"]["hors_consigne"] == ["tools/x.py"]
    assert r["applique"] is False


def test_le_message_d_integration_cite_l_origine():
    m = _module()
    msg = m.message_reconciliation("abc1234", "OPENCODE_GPTOSS", "lot 1 des ecrivains")
    assert "abc1234" in msg and "OPENCODE_GPTOSS" in msg
