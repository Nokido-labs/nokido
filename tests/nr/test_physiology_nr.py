"""NR — les constantes physiologiques.

On teste la LOGIQUE de calcul et de verdict sur des series SYNTHETIQUES
deterministes, pas la serie vivante (gitignore, absente en CI). Ce qui compte :
une constante se calcule fidelement, une absence de mesure ne devient jamais un
faux chiffre, et une degradation au-dela de tolerance bloque.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _rows(pcts, cpu=5.0, dt=15.0):
    return [{"ts": i * dt, "ram_pct": p, "cpu_pct": cpu} for i, p in enumerate(pcts)]


def test_stabilite_haute_quand_ram_plat():
    import forge_physiology as P

    plat = P._stabilite(_rows([60.0] * 20))
    oscillant = P._stabilite(_rows([40.0, 80.0] * 10))
    assert plat > oscillant
    assert plat >= 0.99  # aucune dispersion


def test_recovery_compte_le_retour_a_l_equilibre():
    """Un stress qui repasse sous RELEASE est un episode RECUPERE ; un stress qui
    reste haut ne l'est pas."""
    import forge_physiology as P

    # monte au-dessus de HIGH (85), redescend sous RELEASE (75) -> recupere
    score, p50 = P._recovery(_rows([70, 90, 88, 70, 65]))
    assert score == 1.0 and p50 is not None
    # monte et reste bloque haut -> episode NON recupere
    score2, _ = P._recovery(_rows([70, 90, 90, 90, 90]))
    assert score2 == 0.0


def test_zero_episode_rend_none_jamais_un_chiffre():
    """Pas de stress dans la fenetre : recovery INDETERMINE, surtout pas 1.0."""
    import forge_physiology as P

    score, p50 = P._recovery(_rows([50, 55, 60, 58]))
    assert score is None and p50 is None


def test_pression_et_calme_sont_des_fractions():
    import forge_physiology as P

    assert P._pressure_fraction(_rows([90, 90, 50, 50])) == 0.5
    assert P._cpu_calm([{"cpu_pct": 90}, {"cpu_pct": 10}]) == 0.5


def test_une_degradation_au_dela_de_tolerance_bloque(tmp_path, monkeypatch):
    import forge_physiology as P

    base = tmp_path / "b.json"
    base.write_text('{"constantes": {"resource_recovery_score": 0.95, '
                    '"recovery_time_p50_s": 80}}', encoding="utf-8")
    monkeypatch.setattr(P, "BASELINE", str(base))
    # recovery chute de 0.95 a 0.5 (tol 0.15) -> DEGRADE
    code, rap = P._verdict({"constantes": {"resource_recovery_score": 0.5,
                                           "recovery_time_p50_s": 80}})
    assert code == 1 and rap["etat"] == "DEGRADE"


def test_le_bruit_sous_tolerance_ne_bloque_pas(tmp_path, monkeypatch):
    """Le corps oscille : une micro-variation sous la tolerance reste STABLE."""
    import forge_physiology as P

    base = tmp_path / "b.json"
    base.write_text('{"constantes": {"resource_recovery_score": 0.95, '
                    '"homeostasis_stability": 0.66}}', encoding="utf-8")
    monkeypatch.setattr(P, "BASELINE", str(base))
    code, rap = P._verdict({"constantes": {"resource_recovery_score": 0.90,
                                           "homeostasis_stability": 0.62}})
    assert code == 0 and rap["etat"] == "STABLE"


def test_une_mesure_manquante_ne_juge_pas(tmp_path, monkeypatch):
    """Si une constante est None d'un cote, on ne prononce pas de degradation
    dessus (0 episode de stress != regression)."""
    import forge_physiology as P

    base = tmp_path / "b.json"
    base.write_text('{"constantes": {"resource_recovery_score": 0.95}}', encoding="utf-8")
    monkeypatch.setattr(P, "BASELINE", str(base))
    code, _ = P._verdict({"constantes": {"resource_recovery_score": None}})
    assert code == 0


def test_le_baseline_du_depot_porte_les_constantes():
    import json

    import forge_physiology as P

    ref = json.loads(Path(P.BASELINE).read_text(encoding="utf-8"))
    assert ref.get("constantes"), "baseline sans constantes"
    assert set(ref["constantes"]) & set(P.DIRECTIONS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
