"""NR -- executeur OpenCode multi-instances pilote par ACP (decision owner 17/10, T2).

Verifie les 5 exigences + correctifs securite P0 et modele P1 :
1. Table lue : config/opencode_instances.json avec les 3 instances (GPTOSS, NEMOTRON, GLM), modele et worktree.
2. Capacite mesuree : _peut_lancer_opencode(agent) et _capacite_pour(agent) (worktree dedie .git + binaire resolu).
3. Delegation pilotee par un ACPClient DOUBLE : initialisation, session, modele, prompt borne et config MCP distante.
4. Le juge refuse une livraison vide (aucun commit/pointer_ref ou configuration d'agent seule).
5. Une session occupee (SessionBusyError) reporte la tache via _reporter sans second prompt.
6. P0-1 : L'env passe a ACPClient ne contient JAMAIS le jeton de l'executeur (et contient celui lu au coffre, double) ;
         jeton d'instance absent -> delegation refusee et dite (fail-closed).
7. P0-2 : OPENCODE_CONFIG_CONTENT porte permission.bash == 'deny' et l'en-tete LaForge-Agent-Name.
8. P1 : Un set_model qui leve est dit dans le detail (« modele <x> non applique (<Type>) »).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _instances_de_reference(monkeypatch):
    """17/10 : la production fait tourner GPTOSS sur le modele par defaut d'OpenCode ; le NR teste la LOGIQUE sur une
    table de reference, jamais la configuration vivante."""
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE", str(ROOT / "tests" / "nr" / "opencode_instances_reference_nr.json"))

import forge_task_executor as T  # noqa: E402


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_table_instances_opencode_lue():
    """1. Table lue : config/opencode_instances.json contient les 3 instances et statut modele INCONNU."""
    instances = T._instances_opencode()
    assert "OPENCODE_GPTOSS" in instances, instances
    assert "OPENCODE_NEMOTRON" in instances, instances
    assert "OPENCODE_GLM" in instances, instances

    assert instances["OPENCODE_GPTOSS"]["modele"] == "groq/openai/gpt-oss-120b"
    assert instances["OPENCODE_GPTOSS"]["worktree"] == "opencode_gptoss"

    assert instances["OPENCODE_NEMOTRON"]["modele"] == "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
    assert instances["OPENCODE_NEMOTRON"]["worktree"] == "opencode_nemotron"

    assert instances["OPENCODE_GLM"]["modele"] == "zai/glm-4.7-flash"
    assert instances["OPENCODE_GLM"]["worktree"] == "opencode_glm"

    # Fichier physique : statut modele declare INCONNU
    cfg_file = ROOT / "config" / "opencode_instances.json"
    assert cfg_file.exists(), f"fichier {cfg_file} absent"
    texte = cfg_file.read_text(encoding="utf-8")
    assert "INCONNU" in texte

    # Les aiguillages connaissent les 3 instances
    for inst in ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM"):
        assert T._delegation_pour(inst) == T._delegate_to_opencode, inst
        assert callable(T._capacite_pour(inst)), inst


def test_capacite_opencode_sans_worktree(tmp_path, monkeypatch):
    """2a. Capacite mesuree : refus si le worktree dedie est absent."""
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(tmp_path / "absent"))
    ok, motif = T._peut_lancer_opencode("OPENCODE_GPTOSS")
    assert ok is False and "worktree" in motif.lower(), motif

    cap_fn = T._capacite_pour("OPENCODE_GPTOSS")
    assert cap_fn is not None
    ok2, motif2 = cap_fn()
    assert ok2 is False and "worktree" in motif2.lower(), motif2


def test_capacite_opencode_sans_binaire(tmp_path, monkeypatch):
    """2b. Capacite mesuree : refus si le binaire opencode est introuvable."""
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setenv("LAFORGE_OPENCODE_BIN", str(tmp_path / "absent_opencode.exe"))
    ok, motif = T._peut_lancer_opencode("OPENCODE_GPTOSS")
    assert ok is False and ("binaire" in motif.lower() or "opencode" in motif.lower()), motif


def test_capacite_opencode_presente_si_worktree_et_binaire_presents(tmp_path, monkeypatch):
    """2c. Capacite mesuree : succes si worktree (.git) et binaire sont presents."""
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    fake_exe = bin_dir / "opencode.exe"
    fake_exe.write_text("", encoding="utf-8")

    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setenv("LAFORGE_OPENCODE_BIN", str(fake_exe))
    ok, motif = T._peut_lancer_opencode("OPENCODE_GPTOSS")
    assert ok is True and "presents" in motif.lower(), motif

    cap_fn = T._capacite_pour("OPENCODE_GPTOSS")
    ok2, motif2 = cap_fn()
    assert ok2 is True and "presents" in motif2.lower(), motif2


class FakeACPClient:
    """Double d'ACPClient pour tester la delegation sans vrai binaire opencode."""

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.cmd = cmd
        self.cwd = cwd
        self.agent = agent
        self.env = env or {}
        self.calls = []
        self.closed = False
        FakeACPClient.dernier = self

    def start(self):
        self.calls.append("start")

    def initialize(self):
        self.calls.append("initialize")

    def session_new(self):
        self.calls.append("session_new")
        return "sid_fake_123"

    def set_model(self, sid, model):
        self.calls.append(("set_model", sid, model))

    def prompt(self, sid, text, timeout=None):
        self.calls.append(("prompt", sid, text, timeout))
        return {
            "text": '{"intent":"OK_DONE","pointer_ref":"commit:abc1234","commit_message":"feat: fait X"}',
            "stopReason": "end_turn",
        }

    def close(self):
        self.closed = True
        self.calls.append("close")


def test_delegation_pilotee_par_acp_client_double(tmp_path, monkeypatch):
    """3. Delegation pilotee par un ACPClient DOUBLE : verification du flux complet et de OPENCODE_CONFIG_CONTENT."""
    monkeypatch.setattr(T, "ACPClient", FakeACPClient)

    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit executeur ok")
    monkeypatch.setattr(
        T, "_juger_livraison",
        lambda ok, detail, wt_, avant, autorises=None: (True, "commits produits : 1", "OK_DONE")
    )
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: f"token_vault_{inst}")
    vus = {}
    monkeypatch.setattr(
        T, "_clore_delegation",
        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (task_id, token, ok, detail, intent))
    )

    task = {
        "id": "job_acp_001",
        "agent": "OPENCODE_GPTOSS",
        "description": "Ajoute la fonctionnalite Z\ntests_autorises: tests/nr/test_executeur_opencode_instances_nr.py",
    }
    T._delegate_to_opencode(task, "token_mcp_executeur_processus")

    assert "clos" in vus, "la delegation n'a pas ete close"
    task_id, token, ok, detail, intent = vus["clos"]
    assert task_id == "job_acp_001"
    assert token == "token_mcp_executeur_processus"
    assert ok is True
    assert intent == "OK_DONE"

    # Verification du client instancie
    client = FakeACPClient.dernier
    assert client.agent == "opencode"
    assert client.cwd == str(wt)
    assert client.closed is True

    # P0-1: Verification de l'isolation du jeton (jamais celui de l'executeur, celui du coffre)
    assert client.env["FORGE_TOKEN_OPENCODE_GPTOSS"] == "token_vault_OPENCODE_GPTOSS"
    assert "token_mcp_executeur_processus" not in client.env.values()

    # P0-2: Verification de la configuration transmise par OPENCODE_CONFIG_CONTENT
    assert "OPENCODE_CONFIG_CONTENT" in client.env
    assert "OPENCODE_CONFIG" not in client.env
    cfg = json.loads(client.env["OPENCODE_CONFIG_CONTENT"])
    assert cfg["mcp"]["nokido"]["type"] == "remote"
    assert "8766/mcp" in cfg["mcp"]["nokido"]["url"]
    assert cfg["mcp"]["nokido"]["headers"]["LaForge-Agent-Name"] == "OPENCODE_GPTOSS"
    assert cfg["mcp"]["nokido"]["headers"]["Authorization"] == "Bearer {env:FORGE_TOKEN_OPENCODE_GPTOSS}"
    assert cfg["permission"]["bash"] == "deny"
    assert "tools" not in cfg or "bash" not in cfg.get("tools", {})
    assert cfg["model"] == "groq/openai/gpt-oss-120b"

    # Verification de l'ordre d'appels ACP
    assert "start" in client.calls
    assert "initialize" in client.calls
    assert "session_new" in client.calls
    assert ("set_model", "sid_fake_123", "groq/openai/gpt-oss-120b") in client.calls
    prompt_calls = [c for c in client.calls if isinstance(c, tuple) and c[0] == "prompt"]
    assert len(prompt_calls) == 1
    assert "Ajoute la fonctionnalite Z" in prompt_calls[0][2]
    assert client.calls[-1] == "close"


def test_le_juge_refuse_une_livraison_vide(tmp_path, monkeypatch):
    """4. Le juge refuse une livraison vide : aucun commit ou configuration d'agent seule."""
    class EmptyACPClient(FakeACPClient):
        def prompt(self, sid, text, timeout=None):
            self.calls.append(("prompt", sid, text, timeout))
            return {"text": "Pas d'artefact", "stopReason": "end_turn"}

    monkeypatch.setattr(T, "ACPClient", EmptyACPClient)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_NEMOTRON_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        T, "_juger_livraison",
        lambda ok, detail, wt_, avant, autorises=None: (True, "commits produits : 0", None)
    )
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: f"token_vault_{inst}")
    vus = {}
    monkeypatch.setattr(
        T, "_clore_delegation",
        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (task_id, token, ok, detail, intent))
    )

    task = {"id": "job_empty_01", "agent": "OPENCODE_NEMOTRON", "description": "Fais rien"}
    T._delegate_to_opencode(task, "token_123")

    assert "clos" in vus
    _, _, ok, detail, intent = vus["clos"]
    assert ok is False
    assert "AUCUN EFFET" in detail or "0 commit" in detail

    # Controle direct du juge sur un depot reel avec seulement .opencode/ committe. 17/10 (integration) : les doublures
    # ci-dessus sont ANNULEES d'abord -- _juger_livraison appelle lui-meme le global _etat_git ; double, il rendait None
    # (« cannot unpack non-iterable NoneType ») et la 2e partie interrogeait la doublure au lieu du vrai juge.
    monkeypatch.undo()
    repo = tmp_path / "repo_vide"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    avant = T._etat_git(str(repo))
    (repo / ".opencode").mkdir()
    (repo / ".opencode" / "opencode.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "config agent seule")

    ok_juge, effet, _ = T._juger_livraison(
        True,
        '{"intent":"OK_DONE","pointer_ref":".opencode/opencode.json"}',
        str(repo),
        avant,
    )
    assert ok_juge is False and "LIVRAISON VIDE" in effet, effet


def test_une_session_occupee_reporte_la_tache(tmp_path, monkeypatch):
    """5. Une session occupee (SessionBusyError) reporte la tache et n'envoie JAMAIS un second prompt."""
    class BusyACPClient(FakeACPClient):
        def prompt(self, sid, text, timeout=None):
            self.calls.append(("prompt", sid, text, timeout))
            raise T.SessionBusyError(f"session occupee ({sid}) : un seul prompt a la fois par session")

    monkeypatch.setattr(T, "ACPClient", BusyACPClient)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GLM_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: f"token_vault_{inst}")

    vus_reporter = []
    monkeypatch.setattr(T, "_reporter", lambda task, motif: vus_reporter.append((task, motif)) or "REPORTEE")

    vus_clore = []
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: vus_clore.append(a))

    task = {"id": "job_busy_01", "agent": "OPENCODE_GLM", "description": "Tache bloquee"}
    T._delegate_to_opencode(task, "token_busy")

    # La tache doit etre reportee, jamais close
    assert len(vus_reporter) == 1, vus_reporter
    t_rep, motif_rep = vus_reporter[0]
    assert t_rep["id"] == "job_busy_01"
    assert "session occupee" in motif_rep

    assert len(vus_clore) == 0, "la tache ne doit pas etre close lors d'un report"

    # UN SEUL prompt a ete tente (jamais un second prompt)
    client = FakeACPClient.dernier
    prompt_calls = [c for c in client.calls if isinstance(c, tuple) and c[0] == "prompt"]
    assert len(prompt_calls) == 1
    assert client.closed is True


def test_env_acp_ne_contient_jamais_jeton_executeur_et_contient_celui_du_coffre(tmp_path, monkeypatch):
    """P0-1. L'env passe a ACPClient ne contient JAMAIS le jeton de l'executeur (et contient celui lu au coffre)."""
    monkeypatch.setattr(T, "ACPClient", FakeACPClient)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison", lambda *a, **k: (True, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: None)

    import nokido_agent.app.forge_secrets as S
    jeton_coffre = "secret_derive_instance_coffre_42"
    monkeypatch.setattr(
        S, "get_secret",
        lambda cle: jeton_coffre if cle == "FORGE_TOKEN_OPENCODE_GPTOSS" else None
    )

    jeton_executeur = "secret_processus_executeur_prive_99"
    task = {
        "id": "job_token_sec_02",
        "agent": "OPENCODE_GPTOSS",
        "description": "Tache isolation token\ntests_autorises: tests/nr/test_executeur_opencode_instances_nr.py",
    }
    T._delegate_to_opencode(task, jeton_executeur)

    client = FakeACPClient.dernier
    assert client.env is not None
    # L'env contient le jeton lu au coffre
    assert client.env["FORGE_TOKEN_OPENCODE_GPTOSS"] == jeton_coffre
    # L'env ne contient JAMAIS le jeton du processus executeur
    assert jeton_executeur not in client.env.values()
    for val in client.env.values():
        assert jeton_executeur not in str(val)


def test_jeton_instance_absent_delegation_refusee_et_dite(tmp_path, monkeypatch):
    """P0-1. Jeton d'instance absent au coffre -> delegation REFUSEE et DITE (fail-closed)."""
    FakeACPClient.dernier = None
    monkeypatch.setattr(T, "ACPClient", FakeACPClient)

    import nokido_agent.app.forge_secrets as S
    monkeypatch.setattr(S, "get_secret", lambda cle: None)

    vus = {}
    monkeypatch.setattr(
        T, "_clore_delegation",
        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (task_id, token, ok, detail, intent))
    )

    task = {
        "id": "job_token_absent_02",
        "agent": "OPENCODE_NEMOTRON",
        "description": "Tache sans jeton",
    }
    jeton_executeur = "token_executeur_valide"
    T._delegate_to_opencode(task, jeton_executeur)

    assert "clos" in vus, "la delegation aurait du etre refusee"
    task_id, token, ok, detail, intent = vus["clos"]
    assert task_id == "job_token_absent_02"
    assert token == jeton_executeur
    assert ok is False
    assert "FORGE_TOKEN_OPENCODE_NEMOTRON" in detail
    assert any(mot in detail.lower() for mot in ("absent", "illisible", "refusee"))

    # Fail-closed : ACPClient ne doit meme pas avoir ete instancie
    assert FakeACPClient.dernier is None


def test_opencode_config_content_permission_bash_deny_et_agent_name():
    """P0-2. OPENCODE_CONFIG_CONTENT porte permission.bash == 'deny' et l'en-tete LaForge-Agent-Name."""
    for inst in ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM"):
        cfg = T._config_opencode_instance(inst)
        # Refus du shell via permission, pas tools
        assert "permission" in cfg, f"cle permission manquante pour {inst}"
        assert cfg["permission"].get("bash") == "deny", f"bash deny manquant dans permission pour {inst}"
        assert "tools" not in cfg or "bash" not in cfg.get("tools", {}), f"bash ne doit pas etre sous tools pour {inst}"

        # En-tete LaForge-Agent-Name et Authorization
        mcp_nokido = cfg.get("mcp", {}).get("nokido", {})
        headers = mcp_nokido.get("headers", {})
        assert headers.get("LaForge-Agent-Name") == inst, f"LaForge-Agent-Name incorrect pour {inst}"
        assert headers.get("Authorization") == f"Bearer {{env:FORGE_TOKEN_{inst}}}", f"Authorization incorrecte pour {inst}"

        # Model configure
        assert cfg.get("model") == T._instances_opencode()[inst]["modele"]


def test_set_model_qui_leve_est_dit_dans_le_detail(tmp_path, monkeypatch):
    """P1. Un set_model qui leve est dit dans le detail (« modele <x> non applique (<Type>) »)."""
    class FailingModelACPClient(FakeACPClient):
        def set_model(self, sid, model):
            self.calls.append(("set_model", sid, model))
            raise RuntimeError("modele incompatible ou non trouve")

    monkeypatch.setattr(T, "ACPClient", FailingModelACPClient)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(
        T, "_juger_livraison",
        lambda ok, detail, wt_, avant, autorises=None: (True, "commits produits : 1", "OK_DONE")
    )
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: f"token_vault_{inst}")

    vus = {}
    monkeypatch.setattr(
        T, "_clore_delegation",
        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (task_id, token, ok, detail, intent))
    )

    task = {
        "id": "job_set_model_fail_01",
        "agent": "OPENCODE_GPTOSS",
        "description": "Tache avec echec set_model\ntests_autorises: tests/nr/test_executeur_opencode_instances_nr.py",
    }
    T._delegate_to_opencode(task, "token_exec")

    assert "clos" in vus
    _, _, _, detail, _ = vus["clos"]
    modele_attendu = T._instances_opencode()["OPENCODE_GPTOSS"]["modele"]
    phrase_attendue = f"modele {modele_attendu} non applique (RuntimeError)"
    assert phrase_attendue in detail, f"'{phrase_attendue}' non trouve dans detail: {detail}"


def test_set_model_via_request_qui_leve_est_dit_dans_le_detail(tmp_path, monkeypatch):
    """P1. Un set_model via request qui leve est aussi dit dans le detail."""
    class RequestFailingACPClient(FakeACPClient):
        set_model = None  # Force le passage par request

        def request(self, method, params, timeout=10):
            if method == "session/set_model":
                raise ValueError("request session/set_model refuse")
            return {}

    monkeypatch.setattr(T, "ACPClient", RequestFailingACPClient)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GLM_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(
        T, "_juger_livraison",
        lambda ok, detail, wt_, avant, autorises=None: (True, "commits produits : 1", "OK_DONE")
    )
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: f"token_vault_{inst}")

    vus = {}
    monkeypatch.setattr(
        T, "_clore_delegation",
        lambda task_id, token, ok, detail, intent=None: vus.setdefault("clos", (task_id, token, ok, detail, intent))
    )

    task = {
        "id": "job_set_model_req_01",
        "agent": "OPENCODE_GLM",
        "description": "Tache avec echec request set_model\ntests_autorises: tests/nr/test_executeur_opencode_instances_nr.py",
    }
    T._delegate_to_opencode(task, "token_exec")

    assert "clos" in vus
    _, _, _, detail, _ = vus["clos"]
    modele_attendu = T._instances_opencode()["OPENCODE_GLM"]["modele"]
    phrase_attendue = f"modele {modele_attendu} non applique (ValueError)"
    assert phrase_attendue in detail, f"'{phrase_attendue}' non trouve dans detail: {detail}"

