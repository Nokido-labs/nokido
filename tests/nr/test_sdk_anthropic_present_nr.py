"""Le SDK anthropic reste installe dans l'interpreteur de Nokido (P1_voie_api_claude_frugale_reinstallation_sdk).

Il avait disparu (voie API Claude bloquee : claude -p et la voie frugale ne pouvaient plus l'importer). Mesure 24/10 :
LAFORGE_PYTHON 3.12 -> anthropic 0.105.2 ; laforge_py314 -> anthropic 2.3.0. Ce NR echoue si l'interpreteur qui le
joue le perd. Aucune cle lue ici (la lecture au coffre hors bac est portee par e994ec5e6 / 11c62f906). Aucun test
existant ne verifiait la presence (les regles d'or ne citent `import anthropic` que comme interdit d'appel direct).
"""
import importlib.util


def test_sdk_anthropic_importable():
    assert importlib.util.find_spec("anthropic") is not None, "SDK anthropic absent de cet interpreteur"


def test_sdk_anthropic_expose_le_client():
    import anthropic
    assert hasattr(anthropic, "Anthropic") and str(getattr(anthropic, "__version__", "")).strip()
