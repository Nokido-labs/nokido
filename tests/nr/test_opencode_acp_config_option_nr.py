"""NR -- l'executeur OpenCode choisit son modele par le contrat ACP v1 (configOptions), legacy en repli (10/11 soir).

Mesure : depuis OpenCode 2.2.6 (9/11), `session/set_model` -> « Method not found » ; les executeurs GPTOSS/GLM
tournaient sur le modele par defaut ou restaient orphelins. ACP v1 annonce le modele dans la reponse de
`session/new` sous `configOptions` (option de categorie `model`, valeurs dans `options`, a plat ou groupees) et le
regle par `session/set_config_option` {sessionId, configId, value}. Contrats :
  1. `configOptions` presente -> modeles disponibles lus dans ses options (plates ET groupees) ;
  2. application par `session/set_config_option` avec le configId annonce, jamais `session/set_model` ;
  3. sans `configOptions`, forme legacy (`models.availableModels` + `session/set_model`) inchangee.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as E  # noqa: E402

_V1 = {"sessionId": "s1", "configOptions": [
    {"id": "mode", "category": "mode", "type": "select", "currentValue": "build",
     "options": [{"value": "build", "name": "Build"}]},
    {"id": "model", "category": "model", "type": "select", "currentValue": "opencode/big-pickle",
     "options": [{"value": "opencode/big-pickle", "name": "Big Pickle"},
                 {"group": "groq", "name": "Groq", "options": [{"value": "groq/openai/gpt-oss-120b", "name": "GPT-OSS"}]}]},
]}


class _Client:
    def __init__(self):
        self.appels = []

    def request(self, methode, params, timeout=None):
        self.appels.append((methode, params))
        return {}


def test_v1_modeles_lus_dans_config_options_groupees():
    choisi, note = E._choisir_modele("groq/openai/gpt-oss-120b", _V1)
    assert choisi == "groq/openai/gpt-oss-120b" and note == ""
    choisi, note = E._choisir_modele("zai/glm-9", _V1)
    assert choisi is None and "big-pickle" in note


def test_v1_application_par_set_config_option():
    c = _Client()
    E._appliquer_modele(c, "s1", _V1, "groq/openai/gpt-oss-120b")
    assert c.appels == [("session/set_config_option",
                         {"sessionId": "s1", "configId": "model", "value": "groq/openai/gpt-oss-120b"})]


def test_legacy_inchange():
    legacy = {"models": {"availableModels": [{"modelId": "a/b"}]}}
    assert E._choisir_modele("a/b", legacy) == ("a/b", "")
    c = _Client()
    E._appliquer_modele(c, "s1", legacy, "a/b")
    assert c.appels == [("session/set_model", {"sessionId": "s1", "modelId": "a/b"})]
