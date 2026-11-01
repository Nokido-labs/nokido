"""NR : une simulation du self-patcher (--dry-run) ne consomme aucune proposition.

Piege mesure le 26/10 avant le reveil owner : run_once(dry_run=True) ecrivait le
marqueur sandbox/patch_applied/<proposition>, et le cycle reel suivant sautait la
proposition. Une simulation qui consomme n'est pas une simulation.
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_self_patcher as sp  # noqa: E402


def _poser(monkeypatch, tmp_path):
    props = tmp_path / "props"
    faits = props / "patch_applied"
    props.mkdir()
    (props / "evolution_proposal_cible_bfcl_1.md").write_text(
        "# cible\n- **bfcl** : score 94.0 < cible 95.0\n", encoding="utf-8")
    (props / "evolution_proposal_vide_2.md").write_text("rien d'actionnable\n", encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    # signature elargie le 26/10 (rel_ctx, REL depuis tests rouges) : la doublure accepte tout
    monkeypatch.setattr(sp, "_llm_generate_patch", lambda *a, **k: None)
    return faits


def test_dry_run_ne_marque_aucune_proposition(monkeypatch, tmp_path):
    faits = _poser(monkeypatch, tmp_path)
    stats = sp.run_once(dry_run=True)
    assert stats["proposals"] == 2
    assert list(faits.glob("*.md")) == []


def test_dry_run_puis_reel_retraite_les_memes(monkeypatch, tmp_path):
    faits = _poser(monkeypatch, tmp_path)
    sp.run_once(dry_run=True)
    stats = sp.run_once(dry_run=False)
    assert stats["proposals"] == 2
    assert sorted(f.name for f in faits.glob("*.md")) == [
        "evolution_proposal_cible_bfcl_1.md", "evolution_proposal_vide_2.md"]
