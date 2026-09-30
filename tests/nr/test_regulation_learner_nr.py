"""NR — la moitie apprentissage de la boucle de regulation.

On teste la LOGIQUE : recompense correcte, ledger dedoublonne, derive calculee,
passivite (aucune action sur le systeme). Series synthetiques, pas la serie
vivante.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_la_recompense_distingue_les_trois_issues():
    import forge_regulation_learner as L

    assert L._recompense({"recovered": True, "recovery_s": 30}, cible_s=60) == 1.0
    assert L._recompense({"recovered": True, "recovery_s": 90}, cible_s=60) == 0.5
    assert L._recompense({"recovered": False, "recovery_s": None}, cible_s=60) == 0.0
    # recupere mais temps inconnu : mi-recompense, pas 1.0 ni 0.0
    assert L._recompense({"recovered": True, "recovery_s": None}, cible_s=60) == 0.5


def _rows(pcts, dt=15.0):
    return [{"ts": i * dt, "ram_pct": p} for i, p in enumerate(pcts)]


def test_apprend_et_persiste_les_episodes(tmp_path, monkeypatch):
    import forge_physiology as P
    import forge_regulation_learner as L

    monkeypatch.setattr(L, "LEDGER", str(tmp_path / "ledger.jsonl"))
    # deux stress qui recuperent
    serie = _rows([70, 90, 70, 65, 70, 88, 70, 60])
    monkeypatch.setattr(P, "_lire_serie", lambda _w: serie)

    rap = L.apprendre(fenetre=999, anchor=False)
    assert rap["etat"] == "APPRIS"
    assert rap["nouveaux_au_ledger"] >= 1
    assert rap["valeur_apprise"] is not None


def test_le_ledger_ne_recompte_pas_un_episode(tmp_path, monkeypatch):
    """Deux passes sur la meme serie n'ajoutent pas deux fois les memes episodes
    (cle = t0)."""
    import forge_physiology as P
    import forge_regulation_learner as L

    monkeypatch.setattr(L, "LEDGER", str(tmp_path / "ledger.jsonl"))
    serie = _rows([70, 90, 70, 65])
    monkeypatch.setattr(P, "_lire_serie", lambda _w: serie)

    r1 = L.apprendre(999, anchor=False)
    r2 = L.apprendre(999, anchor=False)
    assert r2["nouveaux_au_ledger"] == 0
    assert r2["ledger_total"] == r1["ledger_total"]


def test_serie_sans_stress_n_apprend_rien(tmp_path, monkeypatch):
    import forge_physiology as P
    import forge_regulation_learner as L

    monkeypatch.setattr(L, "LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(P, "_lire_serie", lambda _w: _rows([50, 55, 60, 58]))
    rap = L.apprendre(999, anchor=False)
    assert rap["etat"] == "AUCUN_EPISODE"


def test_la_derive_se_calcule_recent_contre_ancien(tmp_path, monkeypatch):
    """Un ledger dont la moitie recente est moins bonne que l'ancienne rend une
    derive negative : le corps regule moins bien qu'avant."""
    import forge_physiology as P
    import forge_regulation_learner as L

    led = tmp_path / "ledger.jsonl"
    # 6 episodes deja au ledger : 3 bons (1.0) puis 3 mauvais (0.0)
    led.write_text("\n".join(json.dumps({"t0": i, "recompense": (1.0 if i < 3 else 0.0)})
                             for i in range(6)) + "\n", encoding="utf-8")
    monkeypatch.setattr(L, "LEDGER", str(led))
    monkeypatch.setattr(P, "_lire_serie", lambda _w: _rows([50, 55]))  # rien de neuf

    rap = L.apprendre(999, anchor=False)
    assert rap["derive_efficacite"] is not None and rap["derive_efficacite"] < 0


def test_la_cible_vient_de_la_baseline_gelee_pas_de_la_fenetre(tmp_path, monkeypatch):
    """#2 : la cible de recompense doit etre la NORME figee, jamais recalculee sur
    la fenetre courante -- sinon un corps qui ralentit deplace sa propre reference
    et une degradation passerait pour normale."""
    import forge_physiology as P
    import forge_regulation_learner as L

    base = tmp_path / "phys.json"
    base.write_text('{"constantes": {"recovery_time_p50_s": 50.0}}', encoding="utf-8")
    monkeypatch.setattr(P, "BASELINE", str(base))
    assert L._cible_baseline() == 50.0
    # une recuperation a 80s, plus lente que la norme gelee (50), n'est PAS parfaite
    assert L._recompense({"recovered": True, "recovery_s": 80}, L._cible_baseline()) == 0.5
    # a 40s, sous la norme, parfaite
    assert L._recompense({"recovered": True, "recovery_s": 40}, L._cible_baseline()) == 1.0


def test_l_etat_devient_la_cle_d_apprentissage(tmp_path, monkeypatch):
    """#1 : le ledger porte l'ETAT (bucket ram/cpu) et la valeur se ventile PAR
    etat -- substrat de « quelle politique dans quel etat »."""
    import forge_physiology as P
    import forge_regulation_learner as L

    assert L._bucket({"ram_at_trigger": 92, "cpu_at_trigger": 80}) == "ram90+|cpu_hi"
    assert L._bucket({"ram_at_trigger": 86, "cpu_at_trigger": 10}) == "ram85-90|cpu_lo"

    monkeypatch.setattr(L, "LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(P, "_lire_serie", lambda _w: [
        {"ts": 0, "ram_pct": 70, "cpu_pct": 80}, {"ts": 15, "ram_pct": 92, "cpu_pct": 80},
        {"ts": 30, "ram_pct": 88, "cpu_pct": 80}, {"ts": 45, "ram_pct": 60, "cpu_pct": 80}])
    rap = L.apprendre(999, anchor=False)
    assert "par_etat" in rap and "ram90+|cpu_hi" in rap["par_etat"]


def test_le_learner_est_passif():
    """Garde de conception : ce module N'AGIT PAS. Aucun appel de cycle de vie
    (stop/kill/restart/ensure_service/wake) dans sa source -- il observe et
    apprend, il ne regule pas. L'acte autonome est une etape distincte, gatee."""
    import inspect

    import forge_regulation_learner as L

    src = inspect.getsource(L)
    for interdit in ("ensure_service", "supervisor", "kill", "restart",
                     ".wanted", "guard("):
        assert interdit not in src, f"le learner passif ne doit pas contenir : {interdit}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
