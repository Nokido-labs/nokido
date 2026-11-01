"""NR : les reglages de projet n'autorisent SANS demande un curl que vers le hub :8766 (owner 29/10, registre ACP-c).

Mesure du 29/10 : .claude/settings.json (charge aussi par les sessions ACP des worktrees acp_*) autorisait
`Bash(curl -s -m * http://127.0.0.1:*)` ; le joker admet `-X DELETE -d ...` vers n'importe quel service local sans
authentification (API Ollama :11434). Decision owner : restreindre au hub, qui authentifie. Toute autre requete passe
par une demande de permission.
"""
import json
import re
from pathlib import Path

REGLAGES = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"


def test_aucun_curl_sans_demande_hors_du_hub():
    allow = json.loads(REGLAGES.read_text(encoding="utf-8")).get("permissions", {}).get("allow", [])
    curls = [a for a in allow if a.startswith("Bash(curl")]
    hors_hub = [a for a in curls if not re.search(r"http://127\.0\.0\.1:8766/", a)]
    assert hors_hub == [], hors_hub
