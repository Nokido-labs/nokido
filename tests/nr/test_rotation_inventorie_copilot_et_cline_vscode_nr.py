"""NR -- l'inventaire de rotation examine les configs Copilot CLI et Cline (extension VS Code).

Mesure 2026-10-24 : la tache MISTRAL job_c76e84a5 a lu ~/.copilot/mcp-config.json et
.../globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json, qui portent des jetons Bearer en clair,
et leur contenu est parti chez le fournisseur cloud. Aucun des deux n'etait dans CONFIG_FILES : l'inventaire guide
de forge_hub_token_rotation ne pouvait pas designer les cles a faire tourner.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_hub_token_rotation as R  # noqa: E402


def test_copilot_et_cline_vscode_sont_inventories():
    chemins = {str(p).replace("\\", "/").lower() for p in R.CONFIG_FILES}
    assert any(c.endswith("/.copilot/mcp-config.json") for c in chemins), chemins
    assert any(c.endswith("/saoudrizwan.claude-dev/settings/cline_mcp_settings.json") for c in chemins), chemins
