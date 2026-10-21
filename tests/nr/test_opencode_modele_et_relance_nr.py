"""NR -- OpenCode par ACP : le modele s'applique au CONTRAT REEL, et une instance qui s'arrete en route est relancee.

Mesures 2026-10-17 16:16-16:18 (logs/task_executor.log) :
1. « [opencode] modele zai/glm-4.7-flash non applique (RuntimeError): session/set_model -> Invalid params ... modelId :
   expected string, received undefined » sur les deux instances. Le vrai ACPClient (tools/forge_acp_client.py) n'a PAS de
   set_model : la voie de repli envoie {"sessionId", "model"}, OpenCode attend "modelId". Le NR voisin passait parce que
   sa doublure FakeACPClient portait un set_model que la vraie classe n'a pas (doublure au faux contrat, 16/10).
2. OPENCODE_GLM (instruction R2) : un seul tour -- trois outils puis « ERR_PARTIAL, entries_done: 0 » ; prompt() rend la
   main a la fin du tour et l'executeur s'arrete la. Il faut relancer dans la MEME session tant que l'agent n'a pas rendu
   son intention finale (OK_DONE ou un echec dit), dans une borne de tours.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
from forge_acp_client import ACPClient as VraiACPClient  # noqa: E402


class ContratReelACP:
    """Doublure qui EPOUSE le vrai ACPClient : memes methodes, memes parametres (verifie par le premier test)."""

    reponses: list = []

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.requetes = []
        self.prompts = []
        ContratReelACP.dernier = self

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        return "sid-1"

    def request(self, method, params, timeout=30):
        self.requetes.append((method, dict(params)))
        return {}

    def prompt(self, sid, text, timeout=30):
        self.prompts.append(text)
        rang = min(len(self.prompts), len(self.reponses)) - 1
        return {"text": self.reponses[rang]}

    def close(self):
        return None


def test_la_doublure_epouse_le_vrai_contrat_acp():
    for nom in ("start", "initialize", "session_new", "request", "prompt", "close"):
        assert callable(getattr(VraiACPClient, nom, None)), nom
        vrai = list(inspect.signature(getattr(VraiACPClient, nom)).parameters)
        double = list(inspect.signature(getattr(ContratReelACP, nom)).parameters)
        assert vrai == double, (nom, vrai, double)
    assert not hasattr(VraiACPClient, "set_model") or callable(getattr(VraiACPClient, "set_model"))


def _preparer(tmp_path, monkeypatch, reponses):
    ContratReelACP.reponses = list(reponses)
    monkeypatch.setattr(T, "ACPClient", ContratReelACP)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GLM_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (ok, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton_coffre_%s" % inst)
    vus = {}
    monkeypatch.setattr(T, "_clore_delegation",
                        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (ok, detail, intent)))
    task = {"id": "job_relance_01", "agent": "OPENCODE_GLM",
            "description": "Instruction de test assez longue pour etre extraite par l'executeur, critere d'arret mesure."}
    T._delegate_to_opencode(task, "jeton_executeur")
    return ContratReelACP.dernier, vus


def test_le_modele_part_en_modelId_selon_le_contrat_reel(tmp_path, monkeypatch):
    client, vus = _preparer(tmp_path, monkeypatch, ['fini {"intent":"OK_DONE","pointer_ref":"docs/x.json"}'])
    modele = T._instances_opencode()["OPENCODE_GLM"]["modele"]
    assert ("session/set_model", {"sessionId": "sid-1", "modelId": modele}) in client.requetes, client.requetes
    assert "non applique" not in vus["clos"][1]


def test_une_instance_qui_s_arrete_en_route_est_relancee_dans_la_meme_session(tmp_path, monkeypatch):
    client, vus = _preparer(tmp_path, monkeypatch, [
        'Je commence par creer le fichier. {"intent":"ERR_PARTIAL","pointer_ref":"docs/x.json","entries_done":0}',
        'Les 27 verdicts sont ecrits. {"intent":"OK_DONE","pointer_ref":"docs/x.json"}',
    ])
    assert len(client.prompts) == 2, client.prompts
    assert "OK_DONE" in vus["clos"][1]


def test_la_relance_est_bornee(tmp_path, monkeypatch):
    client, vus = _preparer(tmp_path, monkeypatch, ['encore en cours {"intent":"ERR_PARTIAL","pointer_ref":"x"}'])
    assert 1 < len(client.prompts) <= T.OPENCODE_MAX_TOURS, len(client.prompts)


def test_une_reponse_finale_ne_relance_pas(tmp_path, monkeypatch):
    client, _vus = _preparer(tmp_path, monkeypatch, ['{"intent":"ERR_RBAC_DENY","pointer_ref":"refus dit"}'])
    assert len(client.prompts) == 1
