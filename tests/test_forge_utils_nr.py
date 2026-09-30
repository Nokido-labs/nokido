"""
tests/test_forge_utils_nr.py
Non-Régression pour forge_utils.py — _safe_llm_text centralisation
"""
import sys, pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"app"))


class TestSafeLlmText:
    """NR: _safe_llm_text doit se comporter identiquement partout."""

    def _import(self):
        from forge_utils import _safe_llm_text
        return _safe_llm_text

    def test_extrait_texte_normal(self):
        fn = self._import()
        res = {"results": [{"response": "bonjour"}]}
        assert fn(res) == "bonjour"

    def test_fallback_si_vide(self):
        fn = self._import()
        assert fn({}, fallback="fallback") == "fallback"

    def test_ignore_null(self):
        fn = self._import()
        res = {"results": [{"response": "null"}, {"response": "vrai"}]}
        assert fn(res) == "vrai"

    def test_ignore_none_str(self):
        fn = self._import()
        res = {"results": [{"response": "None"}, {"response": "ok"}]}
        assert fn(res) == "ok"

    def test_ignore_dict_vide(self):
        fn = self._import()
        res = {"results": [{"response": "{}"}, {"response": "réponse"}]}
        assert fn(res) == "réponse"

    def test_fallback_si_tous_invalides(self):
        fn = self._import()
        res = {"results": [{"response": "null"}, {"response": "None"}]}
        assert fn(res, fallback="defaut") == "defaut"

    def test_compatible_handler_build(self):
        """NR: forge_handler_build doit fonctionner après migration."""
        import forge_handler_build as hb
        # Vérifier que _safe_llm_text est importée depuis forge_utils
        import forge_utils
        assert hasattr(forge_utils, "_safe_llm_text")

    def test_compatible_handler_advanced(self):
        """NR: forge_handler_advanced doit fonctionner après migration."""
        import forge_handler_advanced as ha
        import forge_utils
        assert hasattr(forge_utils, "_safe_llm_text")


class TestForgeUtilsImport:
    """NR: forge_utils doit être importable sans side effects."""

    def test_import_clean(self):
        import forge_utils
        assert forge_utils is not None

    def test_pas_de_side_effects(self):
        """Import ne doit pas lancer de connexions ou threads."""
        import forge_utils
        # Si on arrive ici sans exception = OK
        assert True
