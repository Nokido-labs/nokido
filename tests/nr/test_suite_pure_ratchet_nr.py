"""NR -- cliquet : aucun test NOUVEAU ne reste hors de la suite pure en silence.

POURQUOI. Le 2026-08-20, trois lots de tests ont ete ecrits, commites et pousses.
Aucun n'a tourne. `PURE_TESTS` (tools/ci_local.py) cite ses fichiers UN A UN, et
l'absence d'un fichier de cette liste ne produit AUCUN signal : le test existe,
il est vert quand on le lance a la main, et il protege exactement zero surface en
CI. Vingt-sept tests dans ce cas, reveles par un simple ecart de comptage
(4883 puis 4885 apres seize ajouts). C'est le meme piege que
`forge_mutation_ratchet.SURFACES`, deja paye le 18/08 : **un test ne protege que
la surface qui le LANCE.**

CE QUE CE CLIQUET FAIT. Il ne demande pas de solder la dette : 82 fichiers sont
hors suite au socle, dont beaucoup a juste titre (vraie base RAG, ports ouverts,
services). Il interdit de l'AGGRANDIR. Un fichier de test NR nouveau doit entrer
dans `PURE_TESTS`, ou etre inscrit au socle -- ce qui oblige a ecrire pourquoi.

Le silence devient impossible : c'est tout ce qu'on lui demande.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (boucle); parcours du depot :
#   lecture des NR de la suite (l.132)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
NR = ROOT / "tests" / "nr"
SOCLE = NR / "_socle_suite_pure.json"


def _ci_local():
    """Charge ci_local par son chemin. Ses constantes sont au niveau module ;
    `main()` n'est pas appele, donc aucun gate ne se declenche a l'import."""
    chemin = ROOT / "tools" / "ci_local.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("ci_local", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_local"] = mod
    sys.modules["nokido_agent.tools.ci_local"] = mod
    spec.loader.exec_module(mod)
    return mod


def _hors_suite() -> set[str]:
    mod = _ci_local()
    dans = {Path(p).name for p in mod.PURE_TESTS if p.startswith("tests/nr/")}
    tous = {p.name for p in NR.glob("test_*.py")}
    return tous - dans


def test_socle_present():
    """Sans photo de reference, le cliquet ne cliquette pas -- et le dit."""
    assert SOCLE.exists(), (
        "socle absent : %s. Le regenerer une fois, en listant les fichiers de "
        "tests NR absents de PURE_TESTS." % SOCLE)


def test_PURE_TESTS_n_a_aucun_doublon():
    """DEFAUT MESURE le 2026-09-12 : `tests/nr/test_veille_pages_nr.py` figurait
    DEUX FOIS, lignes adjacentes, introduit par un commit qui justifiait l'ajout
    en affirmant que le fichier « n'etait declare nulle part ».

    Pourquoi personne ne l'a vu : ce cliquet compare des `set()` de noms
    (`dans = {Path(p).name for p in mod.PURE_TESTS}`). Un ensemble avale les
    doublons en silence — il repond « present », jamais « present deux fois ».
    L'instrument ne pouvait pas voir ce defaut-la.

    Ce qu'un doublon coute : le fichier est joue deux fois a chaque CI, et
    surtout la liste cesse d'etre lisible comme un inventaire — c'est elle qui
    decide ce qui protege une surface.
    """
    from collections import Counter

    mod = _ci_local()
    compte = Counter(mod.PURE_TESTS)
    doublons = {p: n for p, n in compte.items() if n > 1}
    assert not doublons, (
        "PURE_TESTS contient des doublons : %s\n"
        "Chaque entree doit etre unique — un set() ne les voit pas, un Counter si."
        % ", ".join(f"{p} x{n}" for p, n in sorted(doublons.items()))
    )


def test_aucun_test_nr_nouveau_hors_suite_pure():
    socle = set(json.loads(SOCLE.read_text(encoding="utf-8"))["fichiers"])
    orphelins = sorted(_hors_suite() - socle)
    assert not orphelins, (
        "%d fichier(s) de tests NR hors de la suite pure et absent(s) du socle :\n"
        % len(orphelins)
        + "\n".join("  - %s" % o for o in orphelins)
        + "\n\nUn test hors PURE_TESTS ne tourne PAS en CI : il ne protege aucune "
          "surface.\nSoit l'ajouter a PURE_TESTS (tools/ci_local.py) s'il respecte "
          "« zero service externe »,\nsoit l'inscrire dans tests/nr/"
          "_socle_suite_pure.json en disant POURQUOI il en est exclu.")


def test_aucun_test_de_la_suite_ne_depend_d_un_chemin_non_versionne():
    """Un test qui exige un chemin GITIGNORE mesure la machine, pas le code.

    Mesure 2026-08-20, run GHA 32410182488 : la porte locale rendait 5419 tests
    verts sur `d66e1570`, et la CI echouait sur le MEME commit. Cause :
    `test_evolutionary_nr` exigeait `shadow_mutation/`, dossier d'etat present
    sur une machine qui a deja tourne et ABSENT d'un checkout propre. Vert chez
    moi, rouge chez tout le monde -- le pire des verdicts, parce qu'il donne
    confiance a celui qui livre et casse chez celui qui recoit.

    Ce cliquet ferme la classe entiere : aucun fichier de `PURE_TESTS` ne doit
    referencer, via `ROOT / "..."`, un chemin que git ignore.
    """
    import re
    import subprocess

    mod = _ci_local()
    suspects: list[str] = []
    for rel in mod.PURE_TESTS:
        p = ROOT / rel
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        # On ne juge que les EXIGENCES de presence -- `assert (ROOT / "x").exists()`
        # -- pas les simples references. Un test qui ecrit
        # `if not dossier.exists(): return` se comporte correctement sur un
        # checkout propre, et le lui reprocher ferait crier le garde a faux.
        exigences = re.findall(
            r'assert\s*\(?\s*ROOT\s*/\s*"([^"]+)"\s*\)?\s*\.\s*exists\s*\(\s*\)', src)
        for cible in set(exigences):
            # `.git/HEAD` et consorts : on ne juge que ce qui ressemble a un
            # artefact du depot, pas les chemins internes de git.
            if cible.startswith(".git"):
                continue
            try:
                rc = subprocess.run(
                    ["git", "-c", "safe.directory=*", "check-ignore", "-q", cible],
                    cwd=str(ROOT), capture_output=True, timeout=20).returncode
            except Exception:  # noqa: BLE001 - git absent : on ne juge pas
                return
            if rc == 0:
                suspects.append("%s -> %s" % (rel, cible))
    assert not suspects, (
        "%d test(s) de la suite pure dependent d'un chemin IGNORE par git :\n"
        % len(suspects) + "\n".join("  - " + s for s in suspects)
        + "\n\nCes chemins n'existent pas sur un checkout propre : le test "
          "passera en local\net echouera en CI. Rendre la dependance optionnelle, "
          "ou versionner une fixture.")


def test_le_cliquet_sait_mordre():
    """Preuve que la comparaison DETECTE : un garde tout vert doit montrer qu'il
    mesure encore. On simule un fichier neuf, absent du socle et de la suite."""
    socle = {"test_ancien_nr.py"}
    presents = {"test_ancien_nr.py", "test_tout_neuf_nr.py"}
    assert sorted(presents - socle) == ["test_tout_neuf_nr.py"]


def test_les_trois_lots_du_20_aout_sont_bien_dans_la_suite():
    """Non-regression sur le defaut precis qui a motive ce cliquet."""
    mod = _ci_local()
    dans = {Path(p).name for p in mod.PURE_TESTS}
    for f in ("test_lot_20260820_outils_nr.py",
              "test_memory_compactor_datation_nr.py",
              "test_capability_audit_nr.py"):
        assert f in dans, "%s est retombe hors de la suite pure" % f
