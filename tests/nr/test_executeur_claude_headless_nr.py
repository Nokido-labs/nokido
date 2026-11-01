"""NR -- executeur CLAUDE_HEADLESS : `claude -p` facture sur les CREDITS API, jamais sur le quota Max (owner 22/10).

RED ecrit par Claude. Owner : « branche l'executeur claude -p alors ! » apres avoir active 100 $ de credits API
(recharge automatique coupee). La session interactive est connectee par le compte Max (« Login method: Claude Max
account », /status du 22/10) : seul un `claude -p` lance AVEC la cle API (ANTHROPIC_API_KEY_ORG, au coffre) consomme
les credits. Forme retenue = extension des briques existantes, pas un second executeur :
- harness : un agent DISTINCT `claude_api` (jamais `claude`, que le pilotage interactif OAuth utilise) dont la table
  figee _SECRETS_PAR_AGENT injecte la cle ; le job JSON ne nomme aucun secret (meme regle que Vibe, 16/10) ;
- cle ABSENTE -> REFUS de lancer : sans elle, `claude -p` retomberait EN SILENCE sur la connexion Max de l'owner ;
- executeur : _delegate_to_claude sur le patron de _delegate_to_vibe (worktree dedie, verdict sur ce qui est LIVRE),
  modele et tours par TAILLE, plafond de depense JOURNALIER mesure sur `total_cost_usd`, cout inconnu jamais compte 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402
from nokido_agent.app import forge_cli_harness as H  # noqa: E402

CLE = "ANTHROPIC_API_KEY"


def _coffre(monkeypatch, valeurs):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: valeurs.get(k))


def _env(h) -> dict:
    return dict(getattr(h._b, "env", None) or {})


# --- harness : la cle API vient du coffre, pour le seul agent claude_api ---------------------------------------------

def test_claude_api_recoit_la_cle_api_du_coffre(monkeypatch):
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    env = _env(H.harness_for("claude_api", args=["-p"]))
    assert env.get(CLE) == "cle-de-test"


def test_claude_api_lance_le_binaire_claude(monkeypatch):
    monkeypatch.delenv("LAFORGE_CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda n: r"C:\bin\claude.exe" if n == "claude" else None)
    assert H.agent_bin("claude_api") == r"C:\bin\claude.exe"


def _politique(monkeypatch, tmp_path, repli):
    """Interrupteur OWNER versionne (config/, jamais sandbox/ que l'executeur peut ecrire) : reversible par un commit."""
    chemin = tmp_path / "claude_headless.json"
    if repli is not None:
        chemin.write_text(json.dumps({"repli_connexion_max": repli}), encoding="utf-8")
    monkeypatch.setattr(H, "_CONFIG_CLAUDE_HEADLESS", chemin)
    return chemin


@pytest.mark.parametrize("repli", [False, None])
def test_sans_cle_api_claude_api_refuse_de_demarrer(monkeypatch, tmp_path, repli):
    """Politique owner 22/10 (« explicitement a ma demande, reversible ») : sans cle, `claude -p` retomberait sur la
    connexion Max -- par DEFAUT (fichier absent compris) le harness REFUSE, et le refus nomme la politique et son
    interrupteur : c'est un DISABLED_BY_POLICY, pas une panne."""
    _coffre(monkeypatch, {})
    chemin = _politique(monkeypatch, tmp_path, repli)
    with pytest.raises(H.SecretObligatoireAbsent) as e:
        H.harness_for("claude_api", args=["-p"])
    msg = str(e.value)
    assert "repli_connexion_max" in msg and chemin.name in msg and "owner" in msg.lower()


def test_repli_max_autorise_par_l_owner_lance_sans_cle(monkeypatch, tmp_path):
    _coffre(monkeypatch, {})
    _politique(monkeypatch, tmp_path, True)
    env = _env(H.harness_for("claude_api", args=["-p"]))
    assert CLE not in env, "repli = connexion Max de l'owner, aucune cle fabriquee"


def test_politique_illisible_vaut_refus(monkeypatch, tmp_path):
    """Un interrupteur illisible n'ouvre rien : UNKNOWN n'est pas OUI."""
    _coffre(monkeypatch, {})
    chemin = _politique(monkeypatch, tmp_path, None)
    chemin.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(H.SecretObligatoireAbsent):
        H.harness_for("claude_api", args=["-p"])


def test_politique_par_defaut_versionnee_refuse_le_repli():
    cfg = json.loads((ROOT / "config" / "claude_headless.json").read_text(encoding="utf-8"))
    assert cfg["repli_connexion_max"] is False


def test_le_pilotage_interactif_de_claude_ne_recoit_pas_la_cle(monkeypatch):
    _coffre(monkeypatch, {"ANTHROPIC_API_KEY_ORG": "cle-de-test"})
    assert CLE not in _env(H.harness_for("claude", args=[]))


# --- executeur : routage, arguments, job --------------------------------------------------------------------------

def test_claude_headless_est_route_vers_son_executeur():
    assert T._delegation_pour("CLAUDE_HEADLESS") is T._delegate_to_claude
    assert T._capacite_pour("CLAUDE_HEADLESS") is T._peut_lancer_claude


def test_worktree_dedie_synchronise(monkeypatch):
    vus = []
    import forge_worktree as fw
    monkeypatch.setattr(fw, "sync", lambda nom: vus.append(nom) or {"rebased": True})
    T._preparer_worktree("CLAUDE_HEADLESS")
    assert vus == ["claude_headless"]


@pytest.mark.parametrize("taille", ["S", "M", "L"])
def test_arguments_bornes_par_taille(taille):
    args = T._args_claude(Path("C:/wt"), taille)
    assert "-p" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--model") + 1] == T._MODELE_CLAUDE_PAR_TAILLE[taille]
    assert int(args[args.index("--max-turns") + 1]) == T._TOURS_CLAUDE_PAR_TAILLE[taille]
    assert "--mcp-config" in args and "--strict-mcp-config" in args


def test_aucune_permission_totale_ni_shell_libre():
    args = T._args_claude(Path("C:/wt"), "M")
    assert "--dangerously-skip-permissions" not in args
    assert "bypassPermissions" not in args
    outils = args[args.index("--allowedTools") + 1]
    assert "Bash" not in [o.strip() for o in outils.replace(",", " ").split()], "Bash sans motif = shell libre"


def test_mode_bare_sans_hooks_ni_contexte_utilisateur_mais_mcp_explicite():
    """Owner 22/10 (essai mesure) : `claude -p` chargeait les hooks, CLAUDE.md et la memoire de l'owner a chaque
    tache -- 5 Edit natifs refuses dans le worktree (job_88af1e23) et un contexte injecte paye a chaque appel.
    `--bare` les ecarte ; le hub reste atteint par le `--mcp-config` EXPLICITE (ses gardes s'appliquent)."""
    args = T._args_claude(Path("C:/wt"), "M")
    assert "--bare" in args
    assert "--mcp-config" in args and "--strict-mcp-config" in args


def test_le_job_ne_porte_aucun_secret(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path)
    job = T._job_claude("job_x", "Fais le GREEN.", tmp_path, "M")
    assert job["agent"] == "claude_api"
    assert job["send"].startswith("Fais le GREEN.") and job.get("eof") is True
    brut = json.dumps(job)
    assert "sk-ant" not in brut and "ANTHROPIC_API_KEY" not in brut


def test_config_mcp_du_worktree_sans_jeton_sur_disque(tmp_path):
    chemin = T._config_mcp_claude(tmp_path)
    cfg = json.loads(Path(chemin).read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["nokido"]
    assert srv["url"] == "http://127.0.0.1:8766/mcp"
    # 22/10 : `${FORGE_TOKEN_...}` n'etait JAMAIS remplace par `claude -p --mcp-config` (16/16 en 401) ; le jeton est
    # servi a la connexion par headersHelper (tools/forge_mcp_json_sync.py --emit-headers), sans secret sur disque.
    assert "${" not in json.dumps(srv) and "Bearer" not in json.dumps(srv), "aucun jeton ni gabarit dans le fichier"
    assert "forge_mcp_json_sync.py" in srv["headersHelper"]
    assert "--emit-headers CLAUDE_HEADLESS" in srv["headersHelper"]


# --- budget : mesure sur total_cost_usd, plafond journalier, inconnu jamais compte 0 ----------------------------------

def test_cout_lu_dans_la_sortie_json():
    sortie = 'bruit\n{"type":"result","subtype":"success","total_cost_usd":0.4213,"result":"ok"}\n'
    assert T._cout_claude(sortie) == pytest.approx(0.4213)


def test_cout_illisible_vaut_none_pas_zero():
    assert T._cout_claude("pas de json") is None


def test_cout_inconnu_consomme_un_forfait(tmp_path):
    chemin = tmp_path / "budget.json"
    T._consommer_budget_claude(None, jour="2026-10-22", chemin=chemin)
    etat = json.loads(chemin.read_text(encoding="utf-8"))["2026-10-22"]
    assert etat["usd"] == pytest.approx(T._CLAUDE_COUT_INCONNU_USD) and etat["inconnus"] == 1


def test_plafond_journalier_refuse_le_lancement(monkeypatch, tmp_path):
    chemin = tmp_path / "budget.json"
    monkeypatch.setattr(T, "_CLAUDE_BUDGET", chemin)
    monkeypatch.setattr(T, "_CLAUDE_PLAFOND_JOUR_USD", 1.0)
    monkeypatch.setattr(T, "_workdir_claude", lambda: tmp_path)
    (tmp_path / ".git").write_text("gitdir: x", encoding="utf-8")
    T._consommer_budget_claude(1.2, chemin=chemin)
    ok, raison = T._peut_lancer_claude()
    assert not ok and "PLAFOND" in raison


# --- 22/10 : claude -p recoit ses PROPRES reglages (SCRUB garde, Write autorise) ---
def _reglages_claude():
    a = T._args_claude("/tmp/wt", "M")
    assert "--settings" in a
    p = Path(a[a.index("--settings") + 1])
    assert p.is_absolute() and p.is_file()
    return json.loads(p.read_text(encoding="utf-8"))


def test_args_claude_settings_existe_et_autorise_write():
    allow = _reglages_claude()["permissions"]["allow"]
    assert "Write" in allow
    assert "Bash" not in allow and "Bash(*)" not in allow


def test_args_claude_settings_egal_outils_claude():
    allow = _reglages_claude()["permissions"]["allow"]
    import re
    attendu = re.findall(r"Bash\([^)]*\)|[^\s]+", T._OUTILS_CLAUDE)
    assert len(allow) == len(set(allow))
    assert set(allow) == set(attendu)
