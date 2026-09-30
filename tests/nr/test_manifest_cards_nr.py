"""NR — le rendu des cartes du manifest (brique 2) + le patch des routes /organs.

Ce qu'on protege : (1) rendu DETERMINISTE, echappe, sans LLM ; (2) une surface
dormant/absent montre son ETAT et son remede, jamais un faux « OK » ; (3) le
patch des routes est idempotent et refuse de patcher a l'aveugle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def _surface(nom, etat, **kw):
    base = {"surface": nom, "organe": "X", "capabilities": ["x.y"],
            "etat": etat, "actions": ["open"], "importance": 0.5, "nouveaute": 0.0}
    base.update(kw)
    return base


def test_une_carte_dormante_montre_son_etat_pas_un_faux_ok():
    from app.web_hub.manifest_cards import _carte

    # `graph` : surface réseau réelle qui subsiste au cœur (les surfaces
    # offensives ctf/recon ont été retirées le 2026-09-01). L'invariant gardé
    # est le même : une carte dormante montre son état ET son remède.
    html = _carte(_surface("graph", "dormant"))
    assert "backend eteint" in html
    assert "lf-status--warn" in html
    assert "data-etat='dormant'" in html
    # et un remede est propose (comment le reveiller)
    assert "ensure_service" in html


def test_une_carte_absente_est_marquee_non_installe():
    from app.web_hub.manifest_cards import _carte

    html = _carte(_surface("redteam", "absent"))
    assert "non installe" in html and "lf-card--danger" in html


def test_une_carte_vivante_expose_ses_actions():
    from app.web_hub.manifest_cards import _carte

    html = _carte(_surface("netcfg", "live", actions=["inventory", "topology"]))
    assert "lf-status--ok" in html and "inventory" in html


def test_le_rendu_echappe_le_contenu():
    """Aucune injection : le HTML est echappe (regle : pas de vecteur de regression)."""
    from app.web_hub.manifest_cards import _carte

    dangereux = "<b>x</b> & 'q'"
    html = _carte(_surface(dangereux, "live"))
    assert "<b>x</b>" not in html      # la balise brute n'apparait jamais
    assert "&lt;b&gt;" in html          # elle est echappee


def test_render_organs_ne_leve_jamais(monkeypatch):
    """Meme si le manifest casse, la page ne doit pas exploser."""
    import forge_ui_manifest as M
    from app.web_hub import manifest_cards

    def _boom(persist=True):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "manifest", _boom)
    out = manifest_cards.render_organs()
    assert "manifest indisponible" in out


def test_le_patch_organs_est_idempotent_et_ancre():
    """Le patch NOOP si deja applique ; il refuse si l'ancre a disparu."""
    import forge_patch_organs_route as P

    assert P.SENTINELLE in P.AJOUT       # la sentinelle d'idempotence est bien produite
    assert "response_class=HTMLResponse" in P.AJOUT
    # l'ancre du patch doit exister dans app.py cible (sinon le patch est mort)
    src = Path(P.CIBLE).read_text(encoding="utf-8", errors="replace")
    assert P.ANCRE in src or P.SENTINELLE in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
