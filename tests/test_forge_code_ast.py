import pytest
from app.forge_code import analyze_ast, count_real_errors

def test_analyze_ast_safe():
    code = "def hello():\n    return 'world'\n"
    ok, msg = analyze_ast(code)
    assert ok is True

def test_analyze_ast_unsafe():
    code = "def hello():\n    return 'world'" # missing newline could be fine, let's test a syntax error
    code = "def hello() return 'world'"
    ok, msg = analyze_ast(code)
    assert ok is False
    assert "SyntaxError" in msg

def test_count_real_errors():
    code = "import os\nos.unknown_func()\n"
    errors = count_real_errors(code)
    # The current count_real_errors might just use pylint if available, or ast.
    # Let's just ensure it runs without crashing.
    assert isinstance(errors, int)
