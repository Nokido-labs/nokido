"""NR -- le hub se presente aux clients MCP sous le nom Nokido (owner 16/10).

RED ecrit par Claude. Vecu 16/10 : Vibe, authentifie sous VIBE_CLI, affichait le serveur comme « LaForge-Hub » -- la
reponse `initialize` portait encore `serverInfo.name = "LaForge-Hub"` (reliquat d'avant le renommage), et l'owner a cru
etre connecte a un autre serveur. Seul le NOM AFFICHE change : les clients identifient le serveur par la cle de leur
propre config, et les etiquettes `triggered_by` d'app/nokido_core.py (lues par des workflows externes) ne sont PAS
concernees. Le hub n'est pas importe en test (convention des NR du hub) : on lit la SOURCE.
"""
from __future__ import annotations

import re
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py"


def _server_info() -> list[str]:
    return re.findall(r'"serverInfo":\s*\{\s*"name":\s*"([^"]+)"', HUB.read_text(encoding="utf-8", errors="replace"))


def test_le_hub_se_nomme_nokido_a_l_initialize():
    noms = _server_info()
    assert noms, "serverInfo introuvable : la forme du hub a change"
    assert all(n == "Nokido-Hub" for n in noms), noms
