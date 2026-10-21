"""NR 18/10 -- ORACLE GELE + preuve independante des gains (chantier 5 de bb P1_preparation_takehome_anthropic_20261018).

Owner : le risque n°1 avant de confier le takehome a Nokido -- des resultats spectaculaires etaient invalides parce
que des agents avaient modifie les tests. Contrat (tools/forge_merge_gate.oracle_gele) : depot fige par SHA,
candidat evalue dans un worktree ISOLE, toute ecriture sous un chemin protege (tests/) = INVALID sans execution,
git diff des proteges revérifie vide, commande officielle executee ; verdicts CORRECTNESS_PASS / CORRECTNESS_FAIL /
INVALID / UNKNOWN (delai, erreur) ; archive par candidat ; promotion seulement si correction ET gain confirme ;
le depot de reference n'est jamais modifie, le worktree est retire.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_merge_gate as MG  # noqa: E402

CHECK = ("import sys; sys.path.insert(0, '.'); import kernel\n"
         "assert kernel.double(2) == 4, 'resultat faux'\n"
         "print('CYCLES=%d' % kernel.CYCLES)\n")


def _git(*a, cwd):
    return subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          cwd=str(cwd), capture_output=True, text=True, errors="replace", check=True).stdout.strip()


def _depot(tmp_path):
    d = tmp_path / "depot"
    (d / "tests").mkdir(parents=True)
    (d / "kernel.py").write_text("CYCLES = 100\ndef double(x):\n    return x * 2\n", encoding="utf-8")
    (d / "tests" / "check.py").write_text(CHECK, encoding="utf-8")
    _git("init", "-q", cwd=d)
    _git("add", "-A", cwd=d)
    _git("commit", "-q", "-m", "ref", cwd=d)
    return d, _git("rev-parse", "HEAD", cwd=d)


def _metrique(sortie):
    m = re.search(r"CYCLES=(\d+)", sortie or "")
    return {"nom": "cycles", "valeur": int(m.group(1)), "bruit": 0, "sens": "MIN"} if m else None


def _oracle(d, sha, fichiers, commande=None, timeout=60):
    return MG.oracle_gele(d, sha, fichiers, commande or [sys.executable, "tests/check.py"],
                          extraire_metrique=_metrique, timeout=timeout)


def test_candidat_correct_et_plus_rapide_est_promouvable(tmp_path):
    d, sha = _depot(tmp_path)
    base = _oracle(d, sha, {})
    cand = _oracle(d, sha, {"kernel.py": "CYCLES = 50\ndef double(x):\n    return x + x\n"})
    assert base["verdict"] == cand["verdict"] == "CORRECTNESS_PASS"
    assert cand["metrique"]["valeur"] == 50 and cand["sha_ref"] == sha
    assert MG.promouvable(base, cand)["promouvable"] is True


def test_plus_rapide_mais_faux_est_rejete(tmp_path):
    d, sha = _depot(tmp_path)
    base = _oracle(d, sha, {})
    cand = _oracle(d, sha, {"kernel.py": "CYCLES = 10\ndef double(x):\n    return x\n"})
    assert cand["verdict"] == "CORRECTNESS_FAIL"
    assert MG.promouvable(base, cand)["promouvable"] is False


def test_toucher_aux_tests_est_invalide_sans_execution(tmp_path):
    d, sha = _depot(tmp_path)
    cand = _oracle(d, sha, {"tests/check.py": "print('CYCLES=1')\n", "kernel.py": "CYCLES = 1\n"})
    assert cand["verdict"] == "INVALID" and cand.get("execute") is False


def test_delai_depasse_est_unknown_jamais_fail(tmp_path):
    d, sha = _depot(tmp_path)
    cand = _oracle(d, sha, {}, commande=[sys.executable, "-c", "import time; time.sleep(30)"], timeout=2)
    assert cand["verdict"] == "UNKNOWN"
    assert MG.promouvable(cand, cand)["promouvable"] is False


def test_depot_de_reference_intact_et_worktree_retire(tmp_path):
    d, sha = _depot(tmp_path)
    _oracle(d, sha, {"kernel.py": "CYCLES = 50\ndef double(x):\n    return x * 2\n"})
    assert _git("status", "--porcelain", cwd=d) == ""
    assert (d / "kernel.py").read_text(encoding="utf-8").startswith("CYCLES = 100")
    assert len(_git("worktree", "list", cwd=d).splitlines()) == 1
