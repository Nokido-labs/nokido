"""NR -- secours de la synthese depose par le LANCEUR (ring <= 3), jamais par le job (GO owner 29/10).

Faux statut, tmp_path : aucun vrai depot, aucune ecriture dans tasks.db."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import pytest  # noqa: E402
import forge_cli_swarm as S  # noqa: E402


@pytest.fixture(autouse=True)
def _seuil_substance_neutre(monkeypatch):
    """29/10 : textes factices courts ; le garde de substance a ses NR (test_secours_texte_complet_nr)."""
    monkeypatch.setattr(S, "SYNTHESE_MIN_CAR", 0)

FORT = "ollama_cloud_gptoss:gpt-oss:120b"


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    monkeypatch.setattr(S, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(S, "SORTIE_DIR", tmp_path)
    monkeypatch.setattr(S, "_tourner_membre", lambda m, t, n: {
        "provider": FORT, "ok": True, "text": "reponse 12 ms", "outils_appeles": [],
        "extraits": ["extrait 12 ms"], "ancrage": {"sans_source": []}})
    monkeypatch.setattr(S, "_synthetiser", lambda *a, **k: {"text": "", "error": "vide"})
    monkeypatch.setattr(S, "_pre_flight_envoi", lambda t, v: (True, None))
    monkeypatch.setattr(S, "_appeler_voie", lambda v, p, timeout=180: {"text": "", "error": "backend non prêt"})
    appels = []

    def hub(outil, arguments):
        appels.append((outil, dict(arguments)))
        raise AssertionError("appel hub depuis le job : %s %s" % (outil, arguments))
    monkeypatch.setattr(S, "_appel_hub", hub)
    return appels


def _res_json(tmp_path):
    res = asyncio.run(S.swarm_pointeur("q", ["p"], membres=[FORT]))
    p = tmp_path / "res.json"
    p.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res, p


def test_aucun_redacteur_demande_ecrite_sans_depot(job, tmp_path):
    res, _ = _res_json(tmp_path)
    assert job == []
    d = res["demande_synthese"]
    assert res["synthese_par"] is None and res["synthesis"] is None and res["answers"]
    assert d["executeurs"] == ["CLAUDE_HEADLESS", "ANTIGRAVITY"]
    assert d["raison"] == "depot reserve au lanceur (ring <= 3)"
    assert Path(d["pointeur"]).is_absolute() and Path(d["pointeur"]).is_file()
    assert '"%s"' % d["pointeur"] in d["consigne"]


def _statut(monkeypatch, etat, texte=""):
    monkeypatch.setattr(S, "_statut_tache", lambda tid: {
        "status": etat, "results": json.dumps([{"text": texte}]) if texte else "[]"})


def test_integrer_done_ecrit_synthese_jugee(job, tmp_path, monkeypatch):
    _, p = _res_json(tmp_path)
    _statut(monkeypatch, "review", "ligne ancree 12 ms")
    rc = S.main(["--integrer-secours", str(p), "T1", "--agent", "CLAUDE_HEADLESS"])
    assert rc == 0 and job == []
    r = json.loads(p.read_text(encoding="utf-8"))
    assert "ligne ancree" in r["synthesis"] and r["synthese_par"] == "executeur:CLAUDE_HEADLESS"
    assert "demande_synthese" not in r and r["secours_integre"] == {"task_id": "T1", "agent": "CLAUDE_HEADLESS"}
    assert "synthese_ancrage" in r and "synthese_garde" not in r


def test_integrer_chiffre_invente_ligne_retiree(job, tmp_path, monkeypatch):
    _, p = _res_json(tmp_path)
    _statut(monkeypatch, "done", "ancree 12 ms\ninventee 77 %")
    assert S.main(["--integrer-secours", str(p), "T1"]) == 0
    r = json.loads(p.read_text(encoding="utf-8"))
    assert "inventee" not in r["synthesis"] and "ancree" in r["synthesis"]
    assert r["synthese_ancrage"]["lignes_retirees"] == 1


def test_integrer_repetition_garde(job, tmp_path, monkeypatch):
    _, p = _res_json(tmp_path)
    _statut(monkeypatch, "done", "\n".join(["meme ligne"] * 5))
    S.main(["--integrer-secours", str(p), "T1"])
    r = json.loads(p.read_text(encoding="utf-8"))
    assert r["synthese_garde"]["lignes_ecartees"] == 3


def test_integrer_pending_rien_ecrit_etat_dit(job, tmp_path, monkeypatch, capsys):
    _, p = _res_json(tmp_path)
    avant = p.read_text(encoding="utf-8")
    _statut(monkeypatch, "pending")
    rc = S.main(["--integrer-secours", str(p), "T1"])
    assert rc != 0 and p.read_text(encoding="utf-8") == avant
    assert "pending" in capsys.readouterr().out
