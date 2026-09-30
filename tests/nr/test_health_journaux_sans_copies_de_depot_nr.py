"""NR -- l'audit des journaux non dates n'arpente pas les copies de depot (2026-09-24).

Mesure : `audit_journal_timestamps` = 87 s sur 139 s de phase health (qui depasse ses 90 s a CHAQUE
tick) ; son `rglob` parcourait 487 889 fichiers dont 380 529 dans les worktrees de preuve de la CI,
et 1 793 des 1 879 journaux retenus y etaient des COPIES (`worktree/logs/a2a.log`). Contrat :
  - un dossier portant `.git` (fichier de worktree OU dossier) est elague, et le nombre est RENDU ;
  - un vrai journal non date hors copie reste detecte (le garde n'est pas affaibli).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_health_diagnostic as hd  # noqa: E402

NON_DATE = "\n".join("ligne sans horodatage %d" % i for i in range(10)) + "\n"


def _arbre(tmp_path: Path) -> Path:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "organe_muet.log").write_text(NON_DATE, encoding="utf-8")
    wt = tmp_path / "sandbox" / "workspace" / "tmp" / "nokido_proof" / "ci-ref-x" / "worktree"
    (wt / "logs").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")        # worktree : .git FICHIER
    (wt / "logs" / "copie.log").write_text(NON_DATE, encoding="utf-8")
    clone = tmp_path / "sandbox" / "clone_y"
    (clone / ".git").mkdir(parents=True)                                      # clone : .git DOSSIER
    (clone / "trace.log").write_text(NON_DATE, encoding="utf-8")
    return tmp_path


def test_les_copies_de_depot_sont_elaguees_et_comptees(tmp_path):
    r = hd.audit_journal_timestamps(_arbre(tmp_path))
    chemins = [u["path"] for u in r["undated"]]
    assert not [c for c in chemins if "worktree" in c or "clone_y" in c], chemins
    assert r["copies_de_depot_elaguees"] == 2, "un filtre qui ecarte doit DIRE combien"


def test_le_garde_voit_toujours_un_vrai_journal_non_date(tmp_path):
    r = hd.audit_journal_timestamps(_arbre(tmp_path))
    assert "logs/organe_muet.log" in [u["path"] for u in r["undated"]]
    assert r["scanned"] == 1
