"""NR -- le rejeu des observateurs OBSERVE, il ne juge pas.

Defaut que ce test empeche de revenir (2026-09-02, tour 0) : quatre instruments
d'atteignabilite existaient et rendaient des verdicts honnetes, mais aucun cycle
ne les rejouait -- matrices figees 17 jours, ratchet INDETERMINE par peremption
(424 h pour une norme de 72 h). `tools/forge_capability_freshness.py` ferme cette
boucle depuis le circadien (bloc NREM1 de `proxy_deno/core/supervisor.ts`).

Ce qui est teste ici est son EFFET, pas son import :

  1. INDETERMINE n'est NI PASS NI FAIL. Un `rc=3` du ratchet veut dire « je ne
     peux pas prouver », et le convertir en echec ferait du circadien un
     gatekeeper : une phase de sommeil echouerait parce qu'une matrice a vieilli.
  2. Le processus rend TOUJOURS 0. L'observation a eu lieu quels que soient les
     verdicts -- c'est le rejeu qui est le service rendu, pas le vert.
  3. Le producteur passe AVANT son consommateur : sans `forge_regression_matrix
     --extract`, le ratchet reste INDETERMINE par construction, et le rejeu
     n'aurait rien change au probleme qu'il pretend resoudre.
  4. Un age de fichier illisible ou absent n'est jamais rendu comme `0`. Un `0`
     se lirait « frais a l'instant » -- l'inverse exact de la verite.

Hermetique : `subprocess.run` est double, aucun instrument reel n'est lance.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

fcf = pytest.importorskip(
    "forge_capability_freshness",
    reason="module absent : le rejeu des observateurs n'est pas livre",
)


class _Rendu:
    """Doublure de CompletedProcess : seul le code de retour nous interesse."""

    def __init__(self, rc: int) -> None:
        self.returncode = rc
        self.stdout = "sortie simulee"
        self.stderr = ""


def _lancer(monkeypatch, rc, etats, produit=None, script="tools/forge_capability_ratchet.py"):
    monkeypatch.setattr(fcf.sp, "run", lambda *a, **k: _Rendu(rc))
    return fcf.lancer("sonde", script, ["--check"], produit, etats)


ETATS_RATCHET = {0: "PASS", 1: "REGRESSION", 3: "INDETERMINE"}


def test_indetermine_nest_ni_pass_ni_fail(monkeypatch):
    """rc=3 = « je ne peux pas prouver ». Le convertir serait fabriquer un verdict."""
    r = _lancer(monkeypatch, 3, ETATS_RATCHET)
    assert r["etat"] == "INDETERMINE"
    assert r["etat"] not in ("PASS", "REGRESSION", "ERREUR_OUTIL")


def test_une_regression_est_nommee_pas_confondue_avec_une_erreur(monkeypatch):
    assert _lancer(monkeypatch, 1, ETATS_RATCHET)["etat"] == "REGRESSION"


def test_un_code_inconnu_ne_devient_pas_un_succes(monkeypatch):
    """Un rc hors contrat est une ERREUR D'OUTIL, jamais un PASS par defaut."""
    assert _lancer(monkeypatch, 42, ETATS_RATCHET)["etat"] == "ERREUR_OUTIL"


def test_un_instrument_absent_le_dit_au_lieu_de_passer(monkeypatch):
    """« Je n'ai pas pu regarder » ne doit pas se lire comme « rien a signaler »."""
    r = fcf.lancer("sonde", "tools/instrument_qui_nexiste_pas.py", [], None, {0: "PASS"})
    assert r["etat"] == "OUTIL_ABSENT"


def test_le_processus_rend_zero_meme_sur_regression(monkeypatch, tmp_path):
    """Observation, pas gatekeeper : le circadien ne doit pas echouer sa phase
    parce qu'un observateur a trouve quelque chose."""
    monkeypatch.setattr(fcf.sp, "run", lambda *a, **k: _Rendu(1))
    monkeypatch.setattr(fcf, "SORTIE", tmp_path / "capability_freshness.json")
    assert fcf.main() == 0
    assert (tmp_path / "capability_freshness.json").is_file()


def test_le_journal_porte_un_etat_par_instrument(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(fcf.sp, "run", lambda *a, **k: _Rendu(0))
    monkeypatch.setattr(fcf, "SORTIE", tmp_path / "j.json")
    fcf.main()
    doc = json.loads((tmp_path / "j.json").read_text(encoding="utf-8"))
    noms = [i["instrument"] for i in doc["instruments"]]
    assert noms == [n for n, _, _, _, _ in fcf.INSTRUMENTS], "un instrument a ete saute en silence"
    assert doc["resume"] and set(doc["resume"]) == set(noms)


def test_le_producteur_de_la_matrice_precede_le_ratchet():
    """Sans `--extract` avant lui, le ratchet reste INDETERMINE par construction :
    le rejeu tournerait sans rien changer au probleme qu'il pretend resoudre."""
    noms = [n for n, _, _, _, _ in fcf.INSTRUMENTS]
    assert "regression_matrix" in noms, "le producteur de la matrice du ratchet a disparu"
    assert "ratchet_check" in noms
    assert noms.index("regression_matrix") < noms.index("ratchet_check")


def test_le_ratchet_declare_les_trois_verdicts():
    etats = dict(next(e for n, _, _, _, e in fcf.INSTRUMENTS if n == "ratchet_check"))
    assert etats.get(3) == "INDETERMINE", "le troisieme etat a disparu du contrat"
    assert etats.get(1) == "REGRESSION" and etats.get(0) == "PASS"


def test_un_age_illisible_nest_jamais_zero(tmp_path):
    """Un `0` se lirait « frais a l'instant » -- l'inverse exact de la verite."""
    assert fcf._age_h(None) is None
    absent = fcf._age_h(tmp_path / "jamais_ecrit.json")
    assert absent == "absent"
    assert absent != 0

    frais = tmp_path / "frais.json"
    frais.write_text("{}", encoding="utf-8")
    assert isinstance(fcf._age_h(frais), float)


def test_les_sorties_visent_les_chemins_que_les_consommateurs_lisent():
    """Un `--out` ailleurs laisserait les matrices figees malgre le rejeu :
    le crosswalk n'ecrit sur disque QU'avec `--out` (mesure du 2026-09-02)."""
    attendus = {"crosswalk": "capability_crosswalk.json",
                "execution_trace": "execution_trace.json",
                "reachability_ledger": "reachability.json",
                "regression_matrix": "regression_matrix.json"}
    for nom, _, args, produit, _ in fcf.INSTRUMENTS:
        if nom not in attendus:
            continue
        assert produit is not None, nom
        assert produit.name == attendus[nom], nom
        if nom in ("crosswalk",):
            assert "--out" in args, "sans --out, le crosswalk n'ecrit que sur stdout"


def test_subprocess_est_bien_double(monkeypatch):
    """Garde-fou de l'instrument : si la doublure ne prenait pas, ces tests
    lanceraient les vrais audits et deviendraient lents ET non hermetiques."""
    assert fcf.sp is subprocess
    monkeypatch.setattr(fcf.sp, "run", lambda *a, **k: _Rendu(0))
    assert fcf.sp.run(["n_importe_quoi"]).returncode == 0
