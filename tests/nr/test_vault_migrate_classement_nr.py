"""NR -- classement secret / config du migrateur de coffre (tools/forge_vault_migrate.py, 2026-10-13).

Mesure : SOURCEFORGE_SSH_PASSKEY (phrase de passe) et TAILSCALE_API (cle `tskey-api`) etaient classees
CONFIG et restaient en clair dans Nokido.env. Une cle publique SSH, elle, n'est pas un secret.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VM = pytest.importorskip("forge_vault_migrate")


@pytest.mark.parametrize("cle", ["GITLAB_TOKEN", "SOURCEFORGE_SSH_PASSKEY", "TAILSCALE_API",
                                 "UNE_PASSPHRASE", "GROQ_API_KEY", "TAILSCALE_AUTH_KEY",
                                 "ARTIFICIALANALYSIS.AI", "CONTROL_PLANE_TUNNEL_ID"])
def test_les_secrets_sont_reconnus(cle):
    assert VM.is_secret(cle), cle


@pytest.mark.parametrize("cle", ["SOURCEFORGE_SSH", "LITELLM_API_BASE", "MAX_TOKENS", "MCP_HTTP_PATH",
                                 "CODEBERG_URL", "TAILSCALE_API_URL"])
def test_la_config_reste_config(cle):
    assert not VM.is_secret(cle), cle
