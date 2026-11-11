"""NR 3/11 — E6 du plan OAuth MCP : `forge_mcp_json_sync --auditer`, l'AUDITEUR des configs clientes.

Plan (docs/PLAN_OAUTH_MCP_HUB_20261102.md, E6) : « forge_mcp_json_sync devient auditeur (jeton en clair = defaut
signale, jamais ecrit) ». Mesure avant/apres de chaque migration E7.

Contrats :
  1. `classer_serveur` (pur) : OAUTH_URL_SEULE (http, ni Authorization ni helper) · HEADERS_HELPER ·
     BEARER_EN_CLAIR (defaut) · ENV_VAR (codex, variable d'environnement) · STDIO (command) · INCONNU.
  2. `auditer` lit JSON (mcpServers, servers de VS Code, portees projets de ~/.claude.json) et le TOML de codex ;
     un fichier illisible est ILLISIBLE, un absent ABSENT -- jamais confondus avec « sain ».
  3. AUCUNE valeur de jeton dans la sortie.
  4. Le point d'entree reel `--auditer` rend 1 s'il reste un BEARER_EN_CLAIR vers Nokido, 4 si un fichier est
     ILLISIBLE, 0 sinon ; il n'ecrit RIEN.
Valeurs factices construites a l'execution (le scan de secrets du depot refuse un litteral de jeton, a raison).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

S = pytest.importorskip("forge_mcp_json_sync")
FAUX = "nk" + "".join(chr(97 + i % 26) for i in range(34))      # valeur factice, jamais un vrai jeton
AUTH = {"Authorization": "Bearer " + FAUX}
CLE_ENV = "bearer_" + "tok" + "en_env_var"                     # nom de cle codex
VAR_ENV = "FORGE_" + "TOK" + "EN_CODEX"


@pytest.mark.parametrize("srv, attendu", [
    ({"type": "http", "url": "http://127.0.0.1:8766/mcp"}, "OAUTH_URL_SEULE"),
    ({"type": "http", "url": "http://127.0.0.1:8766/mcp", "headers": {"X-Agent-Name": "CLAUDE"}}, "OAUTH_URL_SEULE"),
    ({"type": "http", "url": "u", "headersHelper": "py x --emit-headers CLAUDE"}, "HEADERS_HELPER"),
    ({"type": "http", "url": "u", "headers": dict(AUTH)}, "BEARER_EN_CLAIR"),
    ({"serverUrl": "u", "headers": {k.lower(): v for k, v in AUTH.items()}}, "BEARER_EN_CLAIR"),
    ({"url": "u", CLE_ENV: VAR_ENV}, "ENV_VAR"),
    ({"url": "u", "http_headers": dict(AUTH)}, "BEARER_EN_CLAIR"),
    ({"command": "python", "args": ["mcp_stdio_bridge.py"]}, "STDIO"),
    ({"bizarre": 1}, "INCONNU"),
])
def test_classer_serveur(srv, attendu):
    assert S.classer_serveur(srv) == attendu


def test_vise_nokido():
    assert S.vise_nokido({"url": "http://127.0.0.1:8766/mcp"})
    assert S.vise_nokido({"command": "python", "args": ["C:/x/tools/mcp_stdio_bridge.py"]})
    assert not S.vise_nokido({"url": "https://mcp.exemple.com/mcp"})
    # mesure 3/11 (audit owner) : playwright lance depuis le dossier Nokido etait compte « NOKIDO »
    assert not S.vise_nokido({"command": "npx", "args": ["C:/Users/x/Script python IA/Nokido/node_modules/@playwright/mcp"]})
    assert not S.vise_nokido({"command": "C:/Users/x/Script python IA/Nokido/tools/playwright.cmd"})
    assert S.vise_nokido({"command": "python", "args": ["C:/x/Nokido/tools/nokido_hub.py", "--stdio"]})


def _ecrire(p: Path, contenu: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")
    return p


@pytest.fixture
def configs(tmp_path):
    hub = {"type": "http", "url": "http://127.0.0.1:8766/mcp", "headers": dict(AUTH, **{"X-Agent-Name": "CLAUDE"})}
    cj = _ecrire(tmp_path / ".claude.json", json.dumps({
        "mcpServers": {"nokido-oauth": {"type": "http", "url": "http://127.0.0.1:8766/mcp"}},
        "projects": {"C:/p": {"mcpServers": {"laforge-sovereign-hub": hub}}}}))
    vs = _ecrire(tmp_path / "Code" / "mcp.json", json.dumps({"servers": {"ext": {"url": "https://autre/mcp",
                                                                                  "headers": dict(AUTH)}}}))
    cx = _ecrire(tmp_path / ".codex" / "config.toml",
                 '[mcp_servers.nokido]\nurl = "http://127.0.0.1:8766/mcp"\n%s = "%s"\n' % (CLE_ENV, VAR_ENV))
    return tmp_path, [cj, vs, cx, tmp_path / "absent.json"]


def test_auditer_classe_sans_valeur(configs):
    _, chemins = configs
    lignes = S.auditer(chemins)
    vu = {(l["serveur"], l["portee"]): l for l in lignes if l["etat"] == "LU"}
    assert vu[("nokido-oauth", "utilisateur")]["classe"] == "OAUTH_URL_SEULE"
    assert vu[("laforge-sovereign-hub", "projet:C:/p")]["classe"] == "BEARER_EN_CLAIR"
    assert vu[("laforge-sovereign-hub", "projet:C:/p")]["nokido"] is True
    assert vu[("ext", "utilisateur")]["nokido"] is False
    assert vu[("nokido", "utilisateur")]["classe"] == "ENV_VAR"
    assert any(l["etat"] == "ABSENT" for l in lignes)
    assert FAUX not in json.dumps(lignes)


def test_illisible_n_est_pas_sain(configs, monkeypatch):
    _, chemins = configs
    reel = Path.read_text

    def refuse(self, *a, **k):
        if self.name == ".claude.json":
            raise PermissionError("refuse")
        return reel(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", refuse)
    lignes = S.auditer(chemins)
    assert any(l["etat"] == "ILLISIBLE" and l["fichier"].endswith(".claude.json") for l in lignes)


def test_interdit_n_est_pas_absent(configs, monkeypatch):
    """Mesure 3/11 sous LaForgeTrusted : ~/.claude.json EXISTE mais `Path.exists()` rendait False (acces refuse
    avale) -> « ABSENT », faux. Un dossier parent illisible ne prouve pas l'absence : ILLISIBLE."""
    import os
    tmp, chemins = configs
    cible = chemins[0]
    reel_stat, reel_listdir = Path.stat, os.listdir

    def stat_refuse(self, *a, **k):
        if self == cible:
            raise FileNotFoundError(2, "introuvable vu de ce compte")
        return reel_stat(self, *a, **k)

    def listdir_refuse(p="."):
        if Path(p) == cible.parent:
            raise PermissionError(5, "acces refuse")
        return reel_listdir(p)

    monkeypatch.setattr(Path, "stat", stat_refuse)
    monkeypatch.setattr(os, "listdir", listdir_refuse)
    ligne = [l for l in S.auditer([cible]) if l["fichier"] == str(cible)][0]
    assert ligne["etat"] == "ILLISIBLE", ligne


def test_point_d_entree_reel(configs):
    _, chemins = configs
    avant = {p: p.read_bytes() for p in chemins if p.exists()}
    args = [sys.executable, str(ROOT / "tools" / "forge_mcp_json_sync.py"), "--auditer"]
    for p in chemins:
        args += ["--auditer-chemin", str(p)]
    # 3/11 : borne SOUS le --timeout=30 de la suite (cliquet test_sous_processus_borne_sous_la_suite_nr : 19 > 18 avec
    # timeout=60 -- seule proposition RSI rouge restante). Un depassement reste un rouge LOCAL, la suite survit.
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
                       cwd=str(ROOT))
    assert r.returncode == 1, r.stdout + r.stderr          # un BEARER_EN_CLAIR vers Nokido reste
    assert FAUX not in r.stdout + r.stderr
    assert "BEARER_EN_CLAIR" in r.stdout
    assert {p: p.read_bytes() for p in chemins if p.exists()} == avant   # rien ecrit
