"""NR -- Mistral Vibe parle au hub MCP sous son identite PROPRE, sans jeton sur disque (owner 16/10).

RED ecrit par Claude. Owner : « il faut que vibe soit authentifie au mcp pour pouvoir l'utiliser ». Forme retenue
(owner) : config de projet dans le worktree (`.vibe/config.toml`, schema vibe 2.24.5 : [[mcp_servers]] transport
streamable-http, auth static avec `api_key_env` + en-tete de nom), le jeton lu au coffre AU LANCEMENT et injecte au
seul enfant vibe par le harness. Securite : le job JSON (fichier de sandbox/, forgeable par tout processus local) ne
nomme AUCUN secret -- c'est le harness qui associe un agent a son identite par une table figee.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402
from nokido_agent.app import forge_cli_harness as H  # noqa: E402

JETON = "FORGE_TOKEN_VIBE_HEADLESS"


def _coffre(monkeypatch, valeurs):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: valeurs.get(k))


def _env(h) -> dict:
    """L'environnement passe a l'enfant : porte par le backend (CliHarness._b), fusionne a os.environ au start."""
    return dict(getattr(h._b, "env", None) or {})


def test_le_harness_donne_a_vibe_son_jeton_d_identite(monkeypatch):
    _coffre(monkeypatch, {JETON: "jeton-de-test"})
    env = _env(H.harness_for("vibe", args=["--prompt", "x"]))
    assert env.get(JETON) == "jeton-de-test", sorted(env)


def test_aucun_autre_agent_ne_recoit_le_jeton_de_vibe(monkeypatch):
    _coffre(monkeypatch, {JETON: "jeton-de-test"})
    env = _env(H.harness_for("codex", args=["exec"]))
    assert JETON not in env, sorted(env)


def test_un_jeton_absent_du_coffre_n_est_pas_injecte_vide(monkeypatch):
    _coffre(monkeypatch, {})
    env = _env(H.harness_for("vibe", args=[]))
    assert JETON not in env, sorted(env)


def test_le_worktree_vibe_porte_la_config_mcp_du_hub_sans_jeton(tmp_path):
    chemin = T._config_mcp_vibe(tmp_path)
    assert chemin == tmp_path / ".vibe" / "config.toml"
    texte = chemin.read_text(encoding="utf-8")
    cfg = tomllib.loads(texte)
    (srv,) = [s for s in cfg.get("mcp_servers", []) if s.get("name") == "nokido"]
    assert srv["transport"] == "streamable-http" and srv["url"].endswith(":8766/mcp"), srv
    auth = srv["auth"]
    assert auth["type"] == "static" and auth["api_key_env"] == JETON, auth
    assert auth["headers"].get("LaForge-Agent-Name") == "VIBE_HEADLESS", auth
    assert "Bearer " not in texte, "aucun jeton dans le fichier : il est lu au coffre au lancement"


def test_le_worktree_vibe_travaille_sur_codestral_par_notre_cle(tmp_path):
    # 19/10 ~11 h 30, decision owner : RETOUR a codestral-latest. Mesure du census (17/10 et 19/10, en ligne) :
    # mistral-medium-latest / small / devstral = HTTP 429 avec x-ratelimit-limit-req-minute: 0 sur notre cle -- le
    # passage a Medium du matin garantissait un 429 (essai job_10971233). Codestral : 125 req/min, outils OK.
    """Decision owner 16/10 (forme b) : Vibe autonome sur NOTRE cle avec Codestral -- mesure ce soir 125 req/min et
    625 000 tokens/min ; Medium (modele par defaut de Vibe) est FERME a 0 req/min sur cette cle. Fournisseur DISTINCT
    (pas « mistral », dont la connexion navigateur interfererait), cle par variable dediee, jamais dans le fichier."""
    texte = T._config_mcp_vibe(tmp_path).read_text(encoding="utf-8")
    cfg = tomllib.loads(texte)
    assert cfg.get("active_model") == "codestral-nokido", cfg.get("active_model")
    (p,) = [x for x in cfg.get("providers", []) if x.get("name") == "mistral-api-nokido"]
    assert p["api_base"] == "https://api.mistral.ai/v1" and p["api_key_env_var"] == "NOKIDO_MISTRAL_API_KEY", p
    assert p.get("backend") == "generic", p
    (m,) = [x for x in cfg.get("models", []) if x.get("alias") == "codestral-nokido"]
    assert (m["name"], m["provider"]) == ("codestral-latest", "mistral-api-nokido"), m


def test_le_harness_donne_a_vibe_la_cle_mistral_du_coffre_et_pas_au_lanceur(monkeypatch):
    _coffre(monkeypatch, {JETON: "jeton-de-test", "MISTRAL_API_KEY": "cle-mistral-de-test"})
    assert _env(H.harness_for("vibe", args=[])).get("NOKIDO_MISTRAL_API_KEY") == "cle-mistral-de-test"
    assert "NOKIDO_MISTRAL_API_KEY" not in H.jeton_mcp("vibe_cli")


def test_la_config_existante_n_est_pas_ecrasee(tmp_path):
    (tmp_path / ".vibe").mkdir()
    (tmp_path / ".vibe" / "config.toml").write_text("# owner\n", encoding="utf-8")
    T._config_mcp_vibe(tmp_path)
    assert (tmp_path / ".vibe" / "config.toml").read_text(encoding="utf-8") == "# owner\n"


def test_vibe_autonome_n_a_pas_de_shell_natif(tmp_path):
    """Owner 17/10 (fermeture MCP-only : « les garde fous doivent emaner du hub... et pareil pour les autres cli »).
    Mesure : le profil INTERACTIF (config/clients/vibe/config.toml) ferme deja bash/git_bash/powershell, mais la config
    de Vibe AUTONOME n'en fermait aucun -- il tournait sous le compte interactif avec un shell natif OUVERT. Les shells
    passent par `run` du hub (gouverne, compte) ; les ecritures restent permises : l'executeur committe ce que Vibe ecrit
    DANS son worktree."""
    T._config_mcp_vibe(tmp_path)
    cfg = tomllib.loads((tmp_path / ".vibe" / "config.toml").read_text(encoding="utf-8"))
    outils = cfg.get("tools") or {}
    for nom in ("bash", "git_bash", "powershell"):
        assert (outils.get(nom) or {}).get("permission") == "never", (nom, sorted(outils))
    assert cfg.get("active_model") == "codestral-nokido", "les tables ajoutees ne doivent pas absorber la cle racine"


def test_aucun_secret_injecte_n_atteint_le_journal_ni_n_est_vide(monkeypatch, caplog):
    """RED 7 du plan AGY (16/10) : les valeurs que le harness injecte a l'enfant n'apparaissent dans AUCUN journal,
    y compris quand le coffre leve une erreur qui RECOPIE la valeur dans son message ; et un secret vide n'est pas
    injecte (une variable vide ferait partir Vibe sans credential, en silence)."""
    import logging

    from nokido_agent.app import forge_secrets as s

    jeton, cle = "jeton-identite-a1b2c3d4e5f6", "cle-mistral-0f9e8d7c6b5a"

    def coffre_bavard(nom):
        if nom == "MISTRAL_API_KEY":
            raise RuntimeError("backend en erreur sur la valeur %s" % cle)
        return {JETON: jeton}.get(nom, "")

    monkeypatch.setattr(s, "get_secret", coffre_bavard)
    caplog.set_level(logging.DEBUG)
    env = _env(H.harness_for("vibe", args=["--prompt", "x"]))
    assert env.get(JETON) == jeton and "NOKIDO_MISTRAL_API_KEY" not in env
    assert all(v for k, v in H.jeton_mcp("vibe").items()), "aucune valeur vide injectee"
    journal = caplog.text + "".join(str(r.args) for r in caplog.records)
    assert "MISTRAL_API_KEY illisible" in journal, "le journal doit etre OBSERVE : sinon ce test ne prouve rien"
    assert jeton not in journal and cle not in journal, "un secret injecte a atteint le journal"
