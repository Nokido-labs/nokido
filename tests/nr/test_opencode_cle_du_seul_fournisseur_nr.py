"""NR -- chaque instance OpenCode recoit la cle de SON fournisseur, et de lui seul (decision owner 17/10, free tier).

Mesure 17/10 17:27 : « session/set_model -> model not found: groq/openai/gpt-oss-120b (providerId groq) » et
« zai/glm-4.7-flash (providerId zai) » : le fournisseur n'est pas configure dans la session OpenCode -- l'executeur ne
passait que le jeton hub et la config. Owner : « oui, sachant que je n'ai sans doute que le free tier ».
Contrat : cle resolue par forge_key_rotation.resolve puis forge_secrets.get_secret (couture `_lire_cle_fournisseur`),
posee dans l'env du SEUL processus OpenCode de l'instance, sous le nom que lit OpenCode pour CE fournisseur ; aucune
autre cle fournisseur, jamais le jeton de l'executeur ; cle absente = DITE dans le detail (pas un modele muet).
Aucune valeur reelle : la couture rend des valeurs fabriquees.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402

AUTRES = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "ZHIPU_API_KEY")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _instances_de_reference(monkeypatch):
    """La logique se teste sur la table de reference, pas sur la configuration vivante (17/10)."""
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE",
                       str(Path(__file__).resolve().parents[2] / "tests" / "nr" / "opencode_instances_reference_nr.json"))


def test_le_nom_de_cle_suit_le_fournisseur_du_modele():
    assert T._env_cle_fournisseur("groq/openai/gpt-oss-120b") == "GROQ_API_KEY"
    assert T._env_cle_fournisseur("openrouter/nvidia/nemotron-3-super-120b-a12b:free") == "OPENROUTER_API_KEY"
    assert T._env_cle_fournisseur("zai/glm-4.7-flash") == "ZHIPU_API_KEY"
    assert T._env_cle_fournisseur("opencode/big-pickle") is None   # fournisseur sans cle : rien a passer


class SessionQuiGardeLEnv:
    """Doublure au contrat REEL d'ACPClient ; retient l'env recu au constructeur."""

    env_recu = None

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        SessionQuiGardeLEnv.env_recu = dict(env or {})

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        return "sid-1"

    def request(self, method, params, timeout=30):
        return {}

    def prompt(self, sid, text, timeout=30):
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    def close(self):
        return None


def _deleguer(tmp_path, monkeypatch, inst, cles):
    monkeypatch.setattr(T, "ACPClient", SessionQuiGardeLEnv)
    monkeypatch.setattr(T, "_lire_cle_fournisseur", lambda nom: cles.get(nom))
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_%s_WORKDIR" % inst, str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (ok, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda i: "jeton_coffre_%s" % i)
    vus = {}
    monkeypatch.setattr(T, "_clore_delegation", lambda task_id, token, ok, detail, intent=None: vus.setdefault("d", detail))
    T._delegate_to_opencode({"id": "job_cle_01", "agent": inst,
                             "description": "Consigne de test assez longue pour etre extraite par l'executeur."},
                            "JETON_EXECUTEUR")
    return SessionQuiGardeLEnv.env_recu or {}, vus.get("d", "")


def test_gptoss_recoit_la_seule_cle_groq(tmp_path, monkeypatch):
    cles = {n: "valeur_fabriquee_%s" % n for n in AUTRES}
    env, _d = _deleguer(tmp_path, monkeypatch, "OPENCODE_GPTOSS", cles)
    assert env.get("GROQ_API_KEY") == "valeur_fabriquee_GROQ_API_KEY"
    assert "OPENROUTER_API_KEY" not in env and "ZHIPU_API_KEY" not in env
    assert "JETON_EXECUTEUR" not in env.values()


def test_la_cle_zai_se_lit_sous_son_nom_canonique_nokido(monkeypatch):
    """Mesure 17/10 ~19 h 50 : « ZHIPU_API_KEY absente au coffre » alors que la cle y etait sous ZAI_API_KEY, le nom que lit
    tout Nokido (forge_agent_proxy, catalogue, forge_zai_fix_key). L'env OpenCode garde ZHIPU_API_KEY ; le COFFRE se lit
    sous le nom canonique d'abord."""
    import nokido_agent.app.forge_secrets as S
    import nokido_agent.app.forge_key_rotation as R
    monkeypatch.setattr(R, "resolve", lambda nom: (False, None))
    monkeypatch.setattr(S, "get_secret", lambda nom: "valeur_fabriquee_zai" if nom == "ZAI_API_KEY" else None)
    assert T._lire_cle_fournisseur("ZHIPU_API_KEY") == "valeur_fabriquee_zai"
    assert T._lire_cle_fournisseur("GROQ_API_KEY") is None


def test_une_cle_absente_est_dite(tmp_path, monkeypatch):
    env, detail = _deleguer(tmp_path, monkeypatch, "OPENCODE_GLM", {})
    assert "ZHIPU_API_KEY" not in env
    assert "ZHIPU_API_KEY" in detail and "absente" in detail
