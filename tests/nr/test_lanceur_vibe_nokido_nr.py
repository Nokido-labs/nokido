"""NR -- Vibe lance a la main par l'owner parle au hub MCP sous VIBE_CLI, sans jeton sur disque (owner 16/10).

RED ecrit par Claude. Decision owner (« lanceur vibe-nokido ») : un lanceur lit le jeton au coffre et demarre Vibe avec ce
jeton dans SON SEUL environnement -- rien d'ecrit sur disque ni dans l'environnement permanent, rotation transparente ;
identite VIBE_CLI (ring 1), DISTINCTE de VIBE_HEADLESS (executeur). La config utilisateur (~/.vibe/config.toml) porte
le serveur MCP du hub avec `api_key_env` et l'en-tete de nom, jamais le jeton ; installee sur le patron de _patch_codex
(sauvegarde, relecture TOML) sans jamais casser une config existante.
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from nokido_agent.app import forge_cli_harness as H  # noqa: E402

CLI, HEADLESS = "FORGE_TOKEN_VIBE_CLI", "FORGE_TOKEN_VIBE_HEADLESS"


@pytest.fixture()
def coffre(monkeypatch):
    from nokido_agent.app import forge_secrets as s
    valeurs = {CLI: "jeton-cli", HEADLESS: "jeton-headless"}
    monkeypatch.setattr(s, "get_secret", lambda k: valeurs.get(k))
    return valeurs


def test_chaque_identite_vibe_a_son_propre_jeton(coffre):
    assert H.jeton_mcp("vibe_cli") == {CLI: "jeton-cli"}
    assert H.jeton_mcp("vibe") == {HEADLESS: "jeton-headless"}
    assert H.jeton_mcp("codex") == {}


def test_le_lanceur_donne_a_vibe_le_seul_jeton_cli(coffre):
    import nokido_vibe as L

    env = L.environnement(base={"PATH": "x"})
    assert env.get(CLI) == "jeton-cli" and HEADLESS not in env, sorted(env)
    assert L.commande(["--prompt", "x"])[1:] == ["--prompt", "x"]
    assert Path(L.commande([])[0]).name.lower().startswith("vibe")


def _cfg(home: Path) -> Path:
    return home / ".vibe" / "config.toml"


def test_la_config_utilisateur_recoit_le_serveur_du_hub_sans_jeton(tmp_path):
    import forge_provision_clients as P

    _cfg(tmp_path).parent.mkdir(parents=True)
    _cfg(tmp_path).write_text('active_model = "devstral"\n', encoding="utf-8")
    P._patch_vibe(home=tmp_path, dry=False)
    texte = _cfg(tmp_path).read_text(encoding="utf-8")
    cfg = tomllib.loads(texte)
    assert cfg.get("active_model") == "devstral", "la config existante de l'owner doit etre conservee"
    (srv,) = [s for s in cfg.get("mcp_servers", []) if s.get("name") == "nokido"]
    assert srv["transport"] == "streamable-http" and srv["url"].endswith(":8766/mcp"), srv
    assert srv["auth"]["api_key_env"] == CLI and srv["auth"]["headers"]["LaForge-Agent-Name"] == "VIBE_CLI", srv
    assert "Bearer " not in texte


def test_l_installation_est_idempotente(tmp_path):
    import forge_provision_clients as P

    P._patch_vibe(home=tmp_path, dry=False)
    P._patch_vibe(home=tmp_path, dry=False)
    cfg = tomllib.loads(_cfg(tmp_path).read_text(encoding="utf-8"))
    assert len([s for s in cfg.get("mcp_servers", []) if s.get("name") == "nokido"]) == 1


def test_une_url_deja_prise_est_refusee_et_nommee(tmp_path):
    """Vecu 16/10 : vibe interdit deux serveurs sur la meme URL (« MCP server URL is already configured as
    `laforge` ») ; l'ajout aveugle de nokido etait masque par l'ancienne entree laforge (VIBE, 401). L'outil refuse,
    NOMME l'entree qui occupe l'URL, et ne retire jamais une entree de l'owner a sa place."""
    import forge_provision_clients as P

    _cfg(tmp_path).parent.mkdir(parents=True)
    avant = ('[[mcp_servers]]\nname = "laforge"\ntransport = "streamable-http"\n'
             'url = "http://127.0.0.1:8766/mcp"\n')
    _cfg(tmp_path).write_text(avant, encoding="utf-8")
    sortie = P._patch_vibe(home=tmp_path, dry=False)
    assert _cfg(tmp_path).read_text(encoding="utf-8") == avant
    assert any("laforge" in ligne and "vibe mcp remove" in ligne for ligne in sortie), sortie


def test_une_config_illisible_n_est_jamais_touchee(tmp_path):
    import forge_provision_clients as P

    _cfg(tmp_path).parent.mkdir(parents=True)
    _cfg(tmp_path).write_text("ceci [n'est pas du toml", encoding="utf-8")
    sortie = P._patch_vibe(home=tmp_path, dry=False)
    assert _cfg(tmp_path).read_text(encoding="utf-8") == "ceci [n'est pas du toml"
    assert any("ILLISIBLE" in ligne for ligne in sortie), sortie


def test_vibe_cli_est_une_identite_ring_1_au_registre():
    d = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    agents = d.get("agents") if isinstance(d.get("agents"), dict) else d
    assert (agents.get("VIBE_CLI") or {}).get("ring") == 1


def test_sans_home_explicite_la_config_suit_vibe_home(tmp_path, monkeypatch):
    """Vecu 16/10 : VIBE_HOME pointe le profil versionne du depot, et Vibe ne lit alors PLUS ~/.vibe. `--vibe` ecrivait
    pourtant dans ~/.vibe/config.toml -- un fichier que Vibe ne lit pas : succes affiche, effet nul."""
    import forge_provision_clients as P

    maison, profil = tmp_path / "maison", tmp_path / "profil_vibe"
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(maison))  # le chemin ~ du test, jamais celui du compte qui lance
    monkeypatch.setenv("VIBE_HOME", str(profil))
    P._patch_vibe(dry=False)
    assert (profil / "config.toml").exists(), "la config doit aller la ou Vibe la lit (VIBE_HOME)"
    assert not _cfg(maison).exists(), "~/.vibe n'est pas lu quand VIBE_HOME est pose"


def test_un_home_explicite_l_emporte_sur_vibe_home(tmp_path, monkeypatch):
    import forge_provision_clients as P

    monkeypatch.setenv("VIBE_HOME", str(tmp_path / "ailleurs"))
    P._patch_vibe(home=tmp_path, dry=False)
    assert _cfg(tmp_path).exists() and not (tmp_path / "ailleurs" / "config.toml").exists()
