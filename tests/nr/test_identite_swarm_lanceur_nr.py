"""NR identite dediee SWARM_LANCEUR (ring 3) du lanceur du secours (faux coffre, faux hub, aucun secret reel)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402
from tools import forge_secours_lanceur as lz  # noqa: E402

FAUX = "faux-jeton-de-test"


class FauxCoffre:
    def __init__(self, valeur):
        self.valeur = valeur

    def __call__(self, cle):
        return self.valeur if cle == "FORGE_TOKEN_SWARM_LANCEUR" else "MAITRE-NE-DOIT-PAS-PARTIR"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    envoyes = []

    def faux_http(url, payload, headers):
        envoyes.append(dict(headers))
        return json.dumps({"ok": True, "task_id": "T1"})

    monkeypatch.setattr(lz, "_http", faux_http)
    monkeypatch.setattr(sw, "_appel_hub", lz._appel_identite)
    monkeypatch.setenv("FORGE_MCP_TOKEN", "MAITRE-NE-DOIT-PAS-PARTIR")
    (tmp_path / "workspace").mkdir()
    p = tmp_path / "cli_swarm_ptr_1.json"
    p.write_text(json.dumps({"task": "q", "synthesis": "", "demande_synthese": {
        "pointeur": "x.json", "consigne": "c", "executeurs": ["CLAUDE_HEADLESS"], "raison": "r"}}),
        encoding="utf-8")
    return envoyes, tmp_path, p


def test_jeton_present_identite_swarm_lanceur(monde, monkeypatch, capsys):
    envoyes, d, p = monde
    monkeypatch.setattr(lz, "_get_secret", FauxCoffre(FAUX))
    monkeypatch.setattr(lz, "_jeton_session", lambda secret: "SESSION-" + secret)
    lz.passer(d)
    assert envoyes, "aucun appel hub"
    for h in envoyes:
        # assertion REMPLACEE le 29/10 (ex « Bearer » + secret brut) : mesure reelle, le hub repond 401 au secret brut
        # et 200 au CapabilityToken de login_agent (sonde_jeton_swarm_lanceur.py) ; le secret ne part jamais tel quel
        assert h["Authorization"] == "Bearer SESSION-" + FAUX
        assert h["LaForge-Agent-Name"] == "SWARM_LANCEUR"
        assert "MAITRE" not in json.dumps(h)
    sortie = capsys.readouterr().out
    assert sortie.strip() and "cli_swarm_ptr_1.json" in sortie and FAUX not in sortie


def test_jeton_absent_motif_sans_repli_maitre(monde, monkeypatch, capsys):
    envoyes, d, p = monde
    monkeypatch.setattr(lz, "_get_secret", FauxCoffre(None))
    lz.passer(d)
    assert envoyes == []
    res = json.loads(p.read_text(encoding="utf-8"))
    assert "identité SWARM_LANCEUR indisponible" in json.dumps(res["secours_motifs"], ensure_ascii=False)
    sortie = capsys.readouterr().out
    assert sortie.strip() and "indisponible" in sortie


def test_login_refuse_motif_sans_appel(monde, monkeypatch, capsys):
    """login_agent refuse le secret -> motif « refusée au guichet », aucun appel hub."""
    envoyes, d, p = monde
    monkeypatch.setattr(lz, "_get_secret", FauxCoffre(FAUX))

    def refus(_s):
        raise ValueError("Invalid credentials")

    monkeypatch.setattr(lz, "_jeton_session", refus)
    lz.passer(d)
    assert envoyes == []
    assert "refusée au guichet" in json.dumps(json.loads(p.read_text(encoding="utf-8"))["secours_motifs"],
                                              ensure_ascii=False)


def test_json_sans_demande_dit_ignore(tmp_path):
    """Un resultat sans demande de synthese n'est pas « attente » : il est ignoré (pas de demande)."""
    assert lz._etat({}, {}) == "ignoré (pas de demande)"


def test_registre_declare_swarm_lanceur_ring3():
    reg = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    assert reg["agents"]["SWARM_LANCEUR"]["ring"] == 3
