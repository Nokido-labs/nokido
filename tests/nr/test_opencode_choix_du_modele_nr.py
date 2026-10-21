"""NR -- OpenCode : on choisit un modele DISPONIBLE, on ne devine pas.

Mesure 2026-10-17 16:47:06 (logs/task_executor.log), apres le passage a `modelId` :
« session/set_model -> Invalid params: model not found: groq/openai/gpt-oss-120b (providerId groq) ». Les modeles
qu'OpenCode sait servir dependent des fournisseurs connectes dans le profil de l'executeur ; `session/new` les rend
(models.availableModels), mais ACPClient.session_new jetait cette reponse et l'executeur envoyait un set_model
voue a l'echec. Contrat : la reponse est conservee ; le modele configure est pris s'il est disponible (exact, sinon
nom de modele UNIQUE) ; sinon aucun set_model n'est tente et le detail DIT lesquels sont disponibles.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
from forge_acp_client import ACPClient as VraiACPClient  # noqa: E402

DISPO = {"sessionId": "sid-1", "models": {"currentModelId": "opencode/big-pickle",
                                          "availableModels": [{"modelId": "opencode/big-pickle", "name": "Big Pickle"},
                                                              {"modelId": "opencode/gpt-oss-120b", "name": "GPT OSS"},
                                                              {"modelId": "zai/glm-4.7-flash", "name": "GLM"}]}}


def test_le_vrai_session_new_conserve_la_reponse(tmp_path):
    client = VraiACPClient(cmd=["opencode-absent"], cwd=str(tmp_path), agent="opencode")
    client.request = lambda method, params, timeout=30: dict(DISPO)
    assert client.session_new() == "sid-1"
    assert client.derniere_session["models"]["availableModels"][1]["modelId"] == "opencode/gpt-oss-120b"


def test_choix_exact_puis_nom_unique_sinon_rien():
    assert T._choisir_modele("zai/glm-4.7-flash", DISPO)[0] == "zai/glm-4.7-flash"
    assert T._choisir_modele("groq/openai/gpt-oss-120b", DISPO)[0] == "opencode/gpt-oss-120b"
    choisi, note = T._choisir_modele("openrouter/nvidia/nemotron-3-super", DISPO)
    assert choisi is None
    assert "absent" in note and "opencode/big-pickle" in note
    assert T._choisir_modele("x/y", {"sessionId": "s"})[0] == "x/y"  # liste inconnue : on tente, comme avant


class SessionAvecModeles:
    """Doublure au contrat REEL (memes methodes que forge_acp_client.ACPClient) + l'attribut derniere_session."""

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.requetes = []
        self.derniere_session = {}
        SessionAvecModeles.dernier = self

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        self.derniere_session = dict(DISPO)
        return "sid-1"

    def request(self, method, params, timeout=30):
        self.requetes.append((method, dict(params)))
        return {}

    def prompt(self, sid, text, timeout=30):
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    def close(self):
        return None


def test_modele_absent_pas_de_set_model_et_c_est_dit(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ACPClient", SessionAvecModeles)
    table = {k: dict(v) for k, v in T._instances_opencode().items()}
    table["OPENCODE_NEMOTRON"]["modele"] = "openrouter/nvidia/nemotron-3-super"
    monkeypatch.setattr(T, "_instances_opencode", lambda: table)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_NEMOTRON_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (ok, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton_coffre_%s" % inst)
    vus = {}
    monkeypatch.setattr(T, "_clore_delegation",
                        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (ok, detail)))
    T._delegate_to_opencode({"id": "job_modele_01", "agent": "OPENCODE_NEMOTRON",
                             "description": "Consigne de test assez longue pour etre extraite par l'executeur."}, "jx")
    client = SessionAvecModeles.dernier
    assert not [r for r in client.requetes if r[0] == "session/set_model"], client.requetes
    assert "absent" in vus["clos"][1] and "opencode/gpt-oss-120b" in vus["clos"][1]
