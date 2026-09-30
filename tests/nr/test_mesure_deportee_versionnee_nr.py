"""NR 2026-09-09 — une suppleance qui certifie un SHA doit vivre DANS ce SHA,
et dater par son NOM, jamais par son mtime.

DEUX DEFAUTS MESURES LE MEME JOUR, tous deux reveles par T0 (la CI de reference
s'execute dans un worktree detache).

1. LA SUPPLEANCE INVISIBLE. `pip-audit` ne peut pas mesurer depuis le compte de la
   CI (pas d'egress, `WinError 10013`) : il est SUPPLEE par un rapport produit
   ailleurs. Ce rapport vivait dans `sandbox/`, NON VERSIONNE. Dans l'arbre de
   travail il etait la, et le run sortait vert ; dans le worktree de reference il
   est ABSENT, et le gate a rendu « 1 gate CRITIQUE non mesure ». Autrement dit le
   verdict vert du matin s'appuyait sur un fichier qui n'etait dans AUCUN commit.
   L'isolation n'a pas casse la preuve : elle a montre que la preuve empruntait une
   bequille invisible. Le depot a deja sa convention pour ce cas -- les mesures qui
   doivent survivre sont versionnees sous `sandbox/<domaine>_history/`
   (`perf_history`, `py314t_readiness_history`).

2. LE MTIME MENT DANS UN WORKTREE. Un checkout ecrit tous les fichiers MAINTENANT :
   une mesure versionnee y parait donc eternellement fraiche, quel que soit son age
   reel. Dater une suppleance par `st_mtime` reviendrait a certifier un SHA avec une
   mesure de l'an dernier en la croyant du jour -- exactement le motif « la date
   d'ingestion n'est pas la date de l'evenement », paye le 2026-09-08 sur la veille.
   La date vit dans le NOM (`pip_audit_2026-09-07.json`), qui survit au checkout.

Zero service externe : fichiers en tmp_path, aucun reseau, aucun pip-audit lance.
"""

import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402
import forge_deps_reconcilier as deps  # noqa: E402


def test_le_repertoire_versionne_de_mesures_existe_dans_le_depot():
    """Sans lui, la suppleance reste hors de tout commit."""
    hist = RACINE / "sandbox" / "pip_audit_history"
    assert hist.is_dir(), (
        "sandbox/pip_audit_history absent : la mesure qui supplee un gate CRITIQUE "
        "vit hors versionnement, donc elle est INVISIBLE depuis le worktree de "
        "reference -- le verdict ne peut pas etre rattache a un sha")
    rapports = sorted(hist.glob("pip_audit_*.json"))
    assert rapports, "repertoire present mais vide : aucune suppleance versionnee"


def test_rapport_courant_regarde_dans_le_repertoire_versionne(tmp_path, monkeypatch):
    """La selection reste UNIQUE : on etend celle qui existe, on n'en ajoute pas."""
    faux = tmp_path / "depot"
    (faux / "sandbox" / "pip_audit_history").mkdir(parents=True)
    cible = faux / "sandbox" / "pip_audit_history" / "pip_audit_2026-09-07.json"
    cible.write_text('{"dependencies": [], "fixes": []}', encoding="utf-8")
    monkeypatch.setattr(deps, "ROOT", faux)
    trouve = deps.rapport_courant()
    assert trouve is not None, (
        "rapport_courant ignore sandbox/pip_audit_history : la suppleance versionnee "
        "ne serait jamais vue depuis le worktree")
    assert Path(trouve).name == cible.name


def test_l_age_se_lit_dans_le_NOM_et_pas_sur_le_mtime(tmp_path):
    """LE test qui compte : un checkout rajeunit tout, le nom ne bouge pas."""
    assert hasattr(ci_local, "_age_mesure"), (
        "ci_local n'expose pas _age_mesure : l'age est donc calcule sur st_mtime, "
        "que tout checkout de worktree remet a maintenant")
    vieux = tmp_path / "pip_audit_2020-01-01.json"
    vieux.write_text("{}", encoding="utf-8")
    # mtime volontairement TRES recent : c'est l'etat d'un fichier fraichement
    # checkout dans un worktree.
    import os
    os.utime(vieux, (time.time(), time.time()))
    age_j, source = ci_local._age_mesure(vieux)
    assert age_j > 365, (
        "une mesure de 2020 vue comme fraiche (%.1f j) parce que son fichier vient "
        "d'etre ecrit : c'est ainsi qu'on certifierait un sha avec une mesure "
        "perimee" % age_j)
    assert "nom" in source.lower()


def test_sans_date_dans_le_nom_le_repli_mtime_se_DIT(tmp_path):
    """Un repli silencieux est indiscernable d'une mesure fiable."""
    sans = tmp_path / "pip_audit.json"
    sans.write_text("{}", encoding="utf-8")
    age_j, source = ci_local._age_mesure(sans)
    assert age_j >= 0
    assert "mtime" in source.lower(), (
        "le repli sur mtime doit se NOMMER dans la source, sinon on ne sait pas "
        "quelle horloge a servi : %s" % source)


def test_un_chemin_absent_ne_pretend_aucun_age(tmp_path):
    """ABSENT n'est ni frais ni perime."""
    with pytest.raises((OSError, ValueError)):
        ci_local._age_mesure(tmp_path / "jamais_ecrit.json")
