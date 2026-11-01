"""NR -- l'identite MCP d'un sous-processus headless lui est servie a la connexion (headersHelper), jamais via ${VAR}.

Mesure 22/10 : CLAUDE_HEADLESS n'avait JAMAIS ete authentifie par le hub (16 connexions sur 16 en 401,
mcp_audit.log, ring -1). Le jeton etait le bon -- sa valeur lue au coffre est ACCEPTEE par le hub (sonde
job_f08590bfae63, HTTP 200) -- mais `claude -p --mcp-config` ne remplace pas `${FORGE_TOKEN_...}` dans les
en-tetes : le hub recevait le texte litteral.
`headersHelper` (claude 2.1.308) execute une commande a la connexion : jeton lu au coffre a cet instant,
jamais ecrit sur disque ; preuve reelle : whoami -> CLAUDE_HEADLESS. Owner 22/10 : chaque canal et chaque provenance a son identite, et
un headless se lance depuis n'importe quel CLI -- l'en-tete LaForge-Provenance dit QUI l'a lance (RFC 6648 : sans X-).
Unifie le 22/10 sur le fournisseur unique `forge_mcp_json_sync.entetes_agent` ; `forge_mcp_entetes` n'est plus qu'un shim.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_mcp_entetes as E  # noqa: E402  (shim DEPRECIE -> forge_mcp_json_sync)
import forge_mcp_json_sync as fms  # noqa: E402


def _coffre(monkeypatch, valeurs):
    monkeypatch.setattr(fms, "vault_get", lambda cle: valeurs.get(cle))


def test_les_entetes_portent_le_jeton_l_identite_et_la_provenance(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE_HEADLESS": "valeur-de-test"})
    h = fms.entetes_agent("claude_headless", "task_executor")
    assert h == {"Authorization": "Bearer valeur-de-test", "X-Agent-Name": "CLAUDE_HEADLESS",
                 "LaForge-Agent-Name": "CLAUDE_HEADLESS", "LaForge-Provenance": "TASK_EXECUTOR"}


def test_provenance_absente_dite_inconnue_jamais_inventee(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE_HEADLESS": "v"})
    assert fms.entetes_agent("CLAUDE_HEADLESS")["LaForge-Provenance"] == "INCONNUE"
    assert fms.entetes_agent("CLAUDE_HEADLESS", "  ")["LaForge-Provenance"] == "INCONNUE"


def test_jeton_absent_pas_d_entete_du_tout(monkeypatch):
    _coffre(monkeypatch, {})
    assert fms.entetes_agent("CLAUDE_HEADLESS", "X") is None


def test_le_shim_delegue_au_fournisseur_unique(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE_HEADLESS": "v"})
    assert E.entetes("CLAUDE_HEADLESS", "TASK_EXECUTOR") == fms.entetes_agent("CLAUDE_HEADLESS", "TASK_EXECUTOR")
    assert "DEPRECIE" in (E.__doc__ or "")


def test_le_point_d_entree_refuse_sans_jeton_et_ne_dit_aucune_valeur():
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_mcp_json_sync.py"),
                        "--emit-headers", "NR_AGENT_INEXISTANT_22OCT"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
    assert p.returncode in (1, 2) and p.stdout.strip() == ""
    assert "FORGE_TOKEN_NR_AGENT_INEXISTANT_22OCT" in p.stderr


def test_l_executeur_sert_l_identite_par_headershelper_sans_secret_sur_disque(tmp_path):
    import forge_task_executor as T
    cfg = json.loads(T._config_mcp_claude(tmp_path).read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["nokido"]
    assert "${" not in json.dumps(cfg) and "Authorization" not in json.dumps(cfg)
    assert "forge_mcp_json_sync.py" in srv["headersHelper"] and "--emit-headers CLAUDE_HEADLESS" in srv["headersHelper"]
    assert "--provenance TASK_EXECUTOR" in srv["headersHelper"]
