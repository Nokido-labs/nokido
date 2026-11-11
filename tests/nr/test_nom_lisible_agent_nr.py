"""NR -- Noms lisibles d'agents (OAuth, OpenCode avec modele, agents ordinaires).

Conformite consignes de securite et observabilite (owner 6/11 & 7/11) :
- OAuth connu avec code, ex: Claude Code [nkc_nB_c] (jamais le nom seul, ligne bornee)
- Inconnu ou sans nom : identifiant seul, pas de fausse supposition
- Ambigu (homonymes au registre) : identifiant seul
- Registre illisible : identifiant seul, aucun crash
- OpenCode avec modele : OpenCode (fournisseur/modele) ou nom d'instance avec modele
- OpenCode sans modele ou modele vide : non devine (identifiant tel quel / declare)
- Agent ordinaire : nom tel quel
- Aucun jeton dans le libelle
- Branchement surfaces : statusline segment DEL, nokido_tray sans muter les dicts, forge_job_watch_cli _ligne_vue
"""
import copy
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools import forge_presence as P

REG_CLIENTS = {
    "nkc_nB_cvtqrbw29x1netsqlr_-o": {"client_name": "Claude Code"},
    "nkc_i_6BR0TYqrAEoEVGqX-vE052": {"client_name": "Google Antigravity"},
    "nkc_sans_nom": {"redirect_uris": []},
    "nkc_Ab": {"client_name": "Un"},
    "nkc_aB": {"client_name": "Deux"},
}

INSTANCES_OPENCODE = {
    "OPENCODE_GPTOSS": {
        "modele": "mistral/codestral-latest",
        "worktree": "opencode_gptoss",
    },
    "OPENCODE_VIDE": {
        "modele": "",
        "worktree": "opencode_vide",
    },
    "OPENCODE_ESPACES": {
        "modele": "   ",
        "worktree": "opencode_espaces",
    },
}


def test_oauth_connu_avec_code():
    res = P.nom_lisible("OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O", clients=REG_CLIENTS)
    assert res == "Claude Code [NKC_NB_C]"
    assert "\n" not in res
    assert res != "Claude Code"


def test_oauth_inconnu_sans_nom():
    res1 = P.nom_lisible("OAUTH_NKC_INCONNU_123456789", clients=REG_CLIENTS)
    assert res1 == "OAUTH_NKC_INCONNU_123456789"
    res2 = P.nom_lisible("OAUTH_NKC_SANS_NOM", clients=REG_CLIENTS)
    assert res2 == "OAUTH_NKC_SANS_NOM"


def test_oauth_ambigu():
    # Homonymes au registre (ex: nkc_Ab vs nkc_aB) : nom_reel rend None -> identifiant brut
    res = P.nom_lisible("OAUTH_NKC_AB", clients=REG_CLIENTS)
    assert res == "OAUTH_NKC_AB"


def test_registre_illisible():
    res = P.nom_lisible("OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O", clients={})
    assert res == "OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O"


def test_opencode_avec_modele():
    res1 = P.nom_lisible("OPENCODE_GPTOSS", instances=INSTANCES_OPENCODE)
    assert res1 == "OPENCODE_GPTOSS (mistral/codestral-latest)"
    res2 = P.nom_lisible("OPENCODE", instances={"OPENCODE": {"modele": "mistral/codestral-latest"}})
    assert res2 == "OpenCode (mistral/codestral-latest)"


def test_opencode_modele_vide_ou_inconnu():
    res1 = P.nom_lisible("OPENCODE_VIDE", instances=INSTANCES_OPENCODE)
    assert res1 == "OPENCODE_VIDE"
    res2 = P.nom_lisible("OPENCODE_ESPACES", instances=INSTANCES_OPENCODE)
    assert res2 == "OPENCODE_ESPACES"
    res3 = P.nom_lisible("OPENCODE_INEXISTANT", instances=INSTANCES_OPENCODE)
    assert res3 == "OPENCODE_INEXISTANT"


def test_agent_ordinaire():
    assert P.nom_lisible("CLAUDE_HEADLESS") == "CLAUDE_HEADLESS"
    assert P.nom_lisible("MISTRAL") == "MISTRAL"
    assert P.nom_lisible("") == ""


def test_aucun_jeton_dans_le_libelle():
    res = P.nom_lisible("OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O", clients=REG_CLIENTS)
    assert "VTQRBW29X1NETSQLR" not in res
    assert len(res) < 50


def test_surface_statusline_delegations(tmp_path, monkeypatch):
    import nokido_statusline as S
    from datetime import datetime
    import sqlite3

    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, from_agent TEXT, updated_at TEXT)")
    c.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
              ("t1", "OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O", "running", "agt_claude", "2026-11-07T01:00:00"))
    c.commit()
    c.close()

    monkeypatch.setattr(P, "_clients_oauth", lambda: REG_CLIENTS)
    seg = S._delegations(db=db, maintenant=datetime(2026, 11, 7, 1, 5))
    assert "Claude Code [NKC_NB_C]▶5m" in seg, seg


def test_surface_tray_ne_mute_pas_alertes(monkeypatch):
    from unittest.mock import patch, MagicMock

    # Mock pystray and PIL imports to avoid dependency issues via monkeypatch
    monkeypatch.setitem(sys.modules, 'pystray', MagicMock())
    monkeypatch.setitem(sys.modules, 'PIL', MagicMock())
    monkeypatch.setitem(sys.modules, 'PIL.Image', MagicMock())
    monkeypatch.setitem(sys.modules, 'PIL.ImageDraw', MagicMock())
    monkeypatch.setitem(sys.modules, 'PIL.ImageFont', MagicMock())

    import nokido_tray as T

    long_detail = "X" * 250
    alertes = [
        {"id": "a1", "gravite": "high", "sujet": "Test alerte", "detail": "Detail alerte 1", "agent": "OPENCODE_GPTOSS"},
        {"id": "a2", "gravite": "critical", "sujet": "Urgence", "detail": "Detail alerte 2", "agent": "OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O"},
        {"id": "a3", "gravite": "high", "sujet": "Longue", "detail": long_detail, "agent": "OPENCODE_GPTOSS"},
    ]
    copie = copy.deepcopy(alertes)
    # Ligne agent
    ligne = T._ligne_agent({"agent": "OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O", "age_s": 10, "nom_reel": "Claude Code"})
    assert "Claude Code" in ligne
    # Verifier fenetre alertes avec mock MessageBoxW
    with patch('ctypes.windll.user32.MessageBoxW') as mock_messagebox:
        mock_messagebox.return_value = 0
        T._fenetre_alertes(alertes)
        # Verifier que le mock a ete appele
        assert mock_messagebox.called
        # Capturer les arguments
        args, kwargs = mock_messagebox.call_args
        text_capturé = args[1] if args else kwargs.get('text', '')
        # Verifier que le titre de l'alerte est dans le texte
        nom_lisible_attendu = "Test alerte – Detail alerte 1"
        assert nom_lisible_attendu in text_capturé
        # Verifier la borne sur detail et la mention du nombre de caracteres ecartes
        assert "50 car. écartés" in text_capturé
    assert alertes == copie


def test_surface_forge_job_watch_cli_subprocess(tmp_path):
    import subprocess
    cli_path = (ROOT / "tools" / "forge_job_watch_cli.py").as_posix()
    code = (
        "import sys, os\n"
        "from pathlib import Path\n"
        f"cli_path = Path('{cli_path}')\n"
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('forge_job_watch_cli', cli_path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "ligne = mod._ligne_vue({'task_id': 'job_123', 'agent': 'OPENCODE_GLM', 'statut': 'running', 'age_s': 10})\n"
        "print('LIGNE:' + ligne)\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        env={},
        capture_output=True,
        text=True,
        errors="replace",
    )
    assert res.returncode == 0, res.stderr
    mod_glm = P._opencode_modele("OPENCODE_GLM")
    attendu = f"OPENCODE_GLM ({mod_glm})" if mod_glm else "OPENCODE_GLM"
    assert attendu in res.stdout


def test_surface_forge_job_watch_ligne_vue(monkeypatch):
    import forge_job_watch_cli as W

    monkeypatch.setattr(P, "_clients_oauth", lambda: REG_CLIENTS)
    t = {
        "task_id": "job_12345_abc",
        "agent": "OAUTH_NKC_NB_CVTQRBW29X1NETSQLR_-O",
        "statut": "running",
        "age_s": 42,
        "depuis_progres_s": 5,
        "reaffectations": 0,
    }
    ligne = W._ligne_vue(t)
    assert "Claude Code [NKC_NB_C]" in ligne
    assert "age=42s" in ligne
