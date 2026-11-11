# -*- coding: utf-8 -*-
"""NR (8/11, choix owner) : generateurs deterministes pour 03_APPFLOW.md, 04_PRD.md et 05_UX_AX.md.

Prouve :
1. Plus aucun nom dans NON_COUVERTS (les 6 specs 01..06 sont produites par rendre_tout).
2. Determinisme strict (2 rendus identiques, aucun horodatage dans le corps, aucun LLM, aucun reseau) et
   distinction explicite ETAT STATIQUE (genere au commit) / ETAT DYNAMIQUE (pointeur vers la source vivante).
3. Toute source absente ou illisible ecrit ILLISIBLE dans la section correspondante, jamais une section vide.
4. --verifier rend FRAIS sur les 6 specs (dont 03, 04, 05) juste apres --ecrire.
"""
# pylint: disable=missing-function-docstring,protected-access
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_spec_extractor as S  # noqa: E402

_RE_HORODATAGE = re.compile(r"\b20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _sections_non_vides(md: str) -> bool:
    parties = re.split(r"(?m)^##+\s+.+$", md)
    return len(parties) > 1 and all(bloc.strip() for bloc in parties[1:])


def test_plus_aucun_nom_dans_non_couverts():
    assert S.NON_COUVERTS == ()
    for nom in ("03_APPFLOW.md", "04_PRD.md", "05_UX_AX.md"):
        assert nom not in S.NON_COUVERTS


def test_determinisme_et_separation_statique_dynamique():
    for fn in (S.rendre_appflow, S.rendre_prd, S.rendre_ux):
        r1 = fn(ROOT, "abc1234")
        r2 = fn(ROOT, "abc1234")
        assert r1 == r2, f"{fn.__name__} non deterministe"
        corps = "\n".join(S._normaliser(r1))
        assert not _RE_HORODATAGE.search(corps), f"horodatage trouve dans {fn.__name__}"
        assert "STATIQUE" in r1 and "DYNAMIQUE" in r1, f"distinction statique/dynamique absente de {fn.__name__}"
        assert "ILLISIBLE" not in r1, f"source illisible inattendue sur le depot reel dans {fn.__name__}"
        assert _sections_non_vides(r1), f"section vide dans {fn.__name__}"


def test_section_illisible_si_source_absente(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "ROOT", tmp_path)
    for fn in (S.rendre_appflow, S.rendre_prd, S.rendre_ux):
        txt = fn(tmp_path, "0000000")
        assert "**ILLISIBLE**" in txt, f"{fn.__name__} doit ecrire **ILLISIBLE** si source absente"
        assert _sections_non_vides(txt), f"{fn.__name__} ne doit laisser aucune section vide"
        assert fn() == fn(), f"{fn.__name__} sur tmp_path doit rester deterministe"


def test_ecrire_puis_verifier_rend_frais_sur_les_six_specs(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "bases_canoniques", lambda: {})
    assert S.main(["--verifier"]) == 1
    assert S.main(["--ecrire"]) == 0
    dossier = tmp_path / "docs" / "specs"
    attendus = ("01_SCHEMA.md", "02_TRD.md", "03_APPFLOW.md", "04_PRD.md", "05_UX_AX.md", "06_PLAN.md")
    for nom in attendus:
        assert (dossier / nom).is_file(), f"{nom} non ecrit par --ecrire"
    v = S.verifier(S.rendre_tout(), dossier)
    for nom in attendus:
        assert v[nom]["etat"] == "FRAIS", f"{nom} attendu FRAIS apres --ecrire, obtenu {v[nom]}"
    assert S.main(["--verifier"]) == 0


def test_specs_03_04_05_du_depot_sont_fraiches():
    import pytest
    sha = S._sha()
    rendus = {
        "03_APPFLOW.md": S.rendre_appflow(ROOT, sha),
        "04_PRD.md": S.rendre_prd(ROOT, sha),
        "05_UX_AX.md": S.rendre_ux(ROOT, sha),
    }
    v = S.verifier(rendus, ROOT / "docs" / "specs")
    for nom in ("03_APPFLOW.md", "04_PRD.md", "05_UX_AX.md"):
        if v[nom]["etat"] != "FRAIS":
            pytest.fail(f"\n=== DEBUT {nom} ===\n{rendus[nom]}=== FIN {nom} ===", pytrace=False)

