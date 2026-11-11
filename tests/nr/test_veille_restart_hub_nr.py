"""NR owner 9/11 : « tu es censé récupérer automatiquement après les ordres de reboot hub envoyés, tu régresses ».

Après `hub action=demander_ordre ordre=restart-hub`, le client arme un Monitor
`forge_job_watch_cli.py --hub-restart` qui le RÉVEILLE quand un NOUVEAU processus écoute :8766
(né après le début de la veille) et que /health répond. Toute issue est dite : RELANCE,
NON_RELANCE (borne atteinte : ordre refusé ou expiré), ILLISIBLE. Le gate rappelle de l'armer.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_job_watch_cli as W  # noqa: E402
import hook_capability_gate as G  # noqa: E402


class _Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.t += s


def test_relance_constatee_quand_nouveau_processus_et_sante(monkeypatch, capsys):
    h = _Horloge()
    vues = iter([(11, 500.0), None, (22, 1015.0)])
    monkeypatch.setattr(W, "_ecouteur_hub", lambda port=8766: next(vues))
    monkeypatch.setattr(W, "_hub_sain", lambda port=8766: True)
    rc = W.surveiller_hub_restart(max_s=300, intervalle=5, _horloge=h, _dormir=h.dormir)
    sortie = capsys.readouterr().out
    assert rc == 0 and "HUB RELANCE" in sortie and "22" in sortie


def test_ancien_processus_jamais_pris_pour_une_relance(monkeypatch, capsys):
    h = _Horloge()
    monkeypatch.setattr(W, "_ecouteur_hub", lambda port=8766: (11, 500.0))
    monkeypatch.setattr(W, "_hub_sain", lambda port=8766: True)
    rc = W.surveiller_hub_restart(max_s=60, intervalle=5, _horloge=h, _dormir=h.dormir)
    assert rc == 1 and "HUB NON_RELANCE" in capsys.readouterr().out


def test_nouveau_processus_mais_pas_sain_on_attend(monkeypatch, capsys):
    h = _Horloge()
    monkeypatch.setattr(W, "_ecouteur_hub", lambda port=8766: (22, 1010.0))
    monkeypatch.setattr(W, "_hub_sain", lambda port=8766: False)
    rc = W.surveiller_hub_restart(max_s=30, intervalle=5, _horloge=h, _dormir=h.dormir)
    assert rc == 1 and "HUB NON_RELANCE" in capsys.readouterr().out


def test_ecouteur_illisible_dit_illisible(monkeypatch, capsys):
    h = _Horloge()
    monkeypatch.setattr(W, "_ecouteur_hub", lambda port=8766: "ILLISIBLE")
    monkeypatch.setattr(W, "_hub_sain", lambda port=8766: True)
    rc = W.surveiller_hub_restart(max_s=30, intervalle=5, _horloge=h, _dormir=h.dormir)
    assert rc == 2 and "HUB ILLISIBLE" in capsys.readouterr().out


def test_option_cli_branchee(monkeypatch):
    vu = {}
    monkeypatch.setattr(W, "surveiller_hub_restart", lambda max_s, intervalle: vu.update(m=max_s) or 0)
    assert W.main(["--hub-restart", "--max-s", "120"]) == 0 and vu["m"] == 120


def test_gate_rappelle_le_veilleur_apres_ordre_restart():
    for nom in ("mcp__nokido-oauth__hub", "mcp__nokido__hub"):
        for ordre in ("restart-hub", "restart"):
            bloque, msg = G.verdict_forme(nom, {"action": "demander_ordre", "ordre": ordre})
            assert "--hub-restart" in msg, (nom, ordre)
    _, msg = G.verdict_forme("mcp__nokido-oauth__hub", {"action": "demander_ordre", "ordre": "commande-faite"})
    assert "--hub-restart" not in msg
