import sys
import os
import pytest
from pathlib import Path

# Ajout du chemin vers app pour l'import
sys.path.append(str(Path(__file__).parent.parent / "app"))

from forge_secret_guard import (
    is_protected_path, 
    sanitize_python_code, 
    sanitize_sql, 
    assert_can_read,
    SecretGuardViolation
)

def test_is_protected_path():
    # 10 cas bloqués (adaptés aux patterns réels)
    blocked_cases = [
        ".env",
        "Nokido.env",
        "id_rsa",
        "my_embeddings.db", # Pattern: .*embeddings\.db$
        "vault.kdbx",
        "my_credentials.txt",
        "bridge_state.json",
        "backup.env.bak",
        "id_ed25519",
        "secret_token.txt"
    ]
    for p in blocked_cases:
        assert is_protected_path(p) is True, f"Should be blocked: {p}"

    # 4 cas libres
    free_cases = [
        "README.md",
        "app_log.log",
        "main.py",
        "utils/helper.py"
    ]
    for p in free_cases:
        assert is_protected_path(p) is False, f"Should be free: {p}"

def test_sanitize_python_code(monkeypatch):
    monkeypatch.setenv("LAFORGE_ENV", "prod")
    monkeypatch.setenv("LAFORGE_MCP_DEV", "false")
    # Cas bloqués
    assert sanitize_python_code("open('Nokido.env')", "TEST", 0) is not None
    assert sanitize_python_code("os.environ['GITHUB_TOKEN']", "TEST", 0) is not None
    assert sanitize_python_code("load_dotenv()", "TEST", 0) is not None
    
    # Cas libres
    assert sanitize_python_code("print('hello')", "TEST", 0) is None
    assert sanitize_python_code("import json", "TEST", 0) is None

def test_sanitize_sql():
    # Cas bloqués
    assert sanitize_sql("SELECT * FROM event_log", "TEST", 0) is not None
    assert sanitize_sql("SELECT * FROM shared_prompt_log", "TEST", 0) is not None
    
    # Cas libres
    assert sanitize_sql("SELECT * FROM rag_chunks", "TEST", 0) is None

def test_dev_mode(monkeypatch):
    monkeypatch.setenv("LAFORGE_ENV", "dev")
    # En mode dev, sanitize_python_code doit retourner None (warn only)
    code_suspect = "open('Nokido.env')"
    assert sanitize_python_code(code_suspect, "TEST", 0) is None

def test_breakglass_refuse_une_simple_variable_d_environnement(monkeypatch):
    """Ce test affirmait l'INVERSE jusqu'au 2026-09-20.

    Il verrouillait le fait qu'une variable d'environnement desarme le garde.
    Directive owner du jour : « si tu arrives a renforcer, vire ca si pas
    utile » -- mesure a l'appui, 0 usage du breakglass sur 2416 interventions
    journalisees du garde. Le contrat est donc inverse, pas relache.
    """
    monkeypatch.setenv("LAFORGE_ALLOW_SECRETS_READ", "1")
    with pytest.raises(SecretGuardViolation):
        assert_can_read("Nokido.env", "TEST", 0)


def test_breakglass_s_ouvre_sur_une_attestation(monkeypatch):
    """Le deblocage legitime reste possible : on a REMPLACE, pas supprime."""
    import importlib

    dev = importlib.import_module("nokido_agent.tools.forge_dev_mode")
    monkeypatch.setattr(dev, "is_armed", lambda: (True, 600))
    monkeypatch.delenv("LAFORGE_ALLOW_SECRETS_READ", raising=False)
    try:
        assert_can_read("Nokido.env", "TEST", 0)
    except SecretGuardViolation:
        pytest.fail("une attestation dev-mode armee doit ouvrir le garde")
