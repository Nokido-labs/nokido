"""NR -- opencode dans l'interface web reste FERME par defaut (decision owner 2026-09-25, choix A).

Mesure qui l'a impose : `opencode serve` sans OPENCODE_SERVER_PASSWORD etait lisible
depuis LaForgeSbxOffline -- un compte sandbox pouvait piloter l'agent de code de l'owner
et reecrire ses identifiants de fournisseurs (PUT /auth/{providerID}).

Gardes :
- la commande n'ecoute que 127.0.0.1:4096, sans --mdns ni --auto ;
- sans mot de passe (absent OU illisible), rien n'est lance ;
- le mot de passe ne va qu'a l'environnement de l'enfant : ni commande, ni sortie ;
- port deja tenu, Job Object non arme : refus, rien n'est lance ;
- le handle du job survit a servir() (le liberer tuerait le wrapper, membre du job) ;
- le point d'entree reel repond sans trace d'erreur ;
- le lanceur :7400 et la tuile du portail declarent le MEME port, en lien direct ;
- AUTHENTIFICATION DE L'AGENT selon les regles en place (demande owner du 25/09) : jeton
  DERIVE FORGE_TOKEN_OPENCODE, jamais le maitre (retire de l'env de l'enfant), config
  gouvernee versionnee qui coupe bash/edit natifs et s'identifie OPENCODE ; sans jeton ou
  sans config, rien ne demarre ; mot de passe web de 20 caracteres minimum.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.297)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
OUTIL = ROOT / "tools" / "nokido_opencode_web.py"
APP = ROOT / "app" / "web_hub" / "app.py"
CONFIG = ROOT / "config" / "clients" / "opencode" / "opencode.jsonc"
SEMIS = ROOT / "tools" / "forge_vault_seed_agent_tokens.py"
TEMOIN = "temoin-opencode-0123456789"
JETON = "jeton-derive-temoin-opencode"
MAITRE = "jeton-maitre-temoin"


def _charger():
    spec = importlib.util.spec_from_file_location("nokido_opencode_web_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ow(monkeypatch):
    mod = _charger()
    monkeypatch.setattr(mod, "trouver_opencode", lambda appdata: "C:/npm/opencode.cmd")
    monkeypatch.setattr(mod, "port_ecoute", lambda *a, **k: False)
    monkeypatch.setattr(mod, "lire_mot_de_passe", lambda: (TEMOIN, "present"))
    monkeypatch.setattr(mod, "lire_jeton_agent", lambda: (JETON, "present"))
    return mod


def _popen_interdit(*a, **k):
    raise AssertionError("opencode lance alors que le contrat exigeait un refus")


class _Enfant:
    pid = 4242

    def wait(self):
        return 0


def test_commande_locale_sans_drapeau_dangereux(ow):
    cmd = ow.construire_commande("opencode")
    assert cmd[1] == "serve"
    assert cmd[cmd.index("--hostname") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--port") + 1] == "4096"
    assert "--mdns" not in cmd and "--auto" not in cmd


@pytest.mark.parametrize("raison", ["absent du gestionnaire d'identification",
                                    "ILLISIBLE : gestionnaire d'identification inaccessible"])
def test_sans_mot_de_passe_rien_ne_demarre(ow, monkeypatch, capsys, raison):
    monkeypatch.setattr(ow, "lire_mot_de_passe", lambda: (None, raison))
    assert ow.servir(popen=_popen_interdit, armer=lambda: object()) == ow.RC_SANS_MOT_DE_PASSE
    assert raison in capsys.readouterr().out


def test_gestionnaire_illisible_n_est_pas_absent(monkeypatch):
    mod = _charger()

    def _explose(*a, **k):
        raise RuntimeError("acces refuse")

    monkeypatch.setitem(sys.modules, "keyring", types.SimpleNamespace(get_password=_explose))
    monkeypatch.setattr(mod, "service_wcm", lambda: "Nokido")
    valeur, raison = mod.lire_mot_de_passe()
    assert valeur is None and raison.startswith("ILLISIBLE")


def test_port_deja_tenu_refus(ow, monkeypatch):
    monkeypatch.setattr(ow, "port_ecoute", lambda *a, **k: True)
    assert ow.servir(popen=_popen_interdit, armer=lambda: object()) == ow.RC_PORT_OCCUPE


def test_sans_job_refus(ow):
    def _armer():
        raise OSError("job refuse")

    assert ow.servir(popen=_popen_interdit, armer=_armer) == ow.RC_SANS_JOB


def test_sans_jeton_derive_rien_ne_demarre(ow, monkeypatch, capsys):
    monkeypatch.setattr(ow, "lire_jeton_agent", lambda: (None, "absent du coffre"))
    assert ow.servir(popen=_popen_interdit, armer=lambda: object()) == ow.RC_SANS_JETON
    assert "jamais un repli" in capsys.readouterr().out


def test_mot_de_passe_court_refuse(ow, monkeypatch):
    monkeypatch.setattr(ow, "lire_mot_de_passe", lambda: ("essai-jetable-1", "present"))
    assert ow.servir(popen=_popen_interdit, armer=lambda: object()) == ow.RC_MOT_DE_PASSE_FAIBLE


def test_l_enfant_porte_son_jeton_et_jamais_le_maitre(ow, monkeypatch):
    monkeypatch.setenv("FORGE_MCP_TOKEN", MAITRE)
    vu = {}

    def _popen(cmd, **kw):
        vu["env"] = kw["env"]
        return _Enfant()

    assert ow.servir(popen=_popen, armer=lambda: object()) == 0
    assert vu["env"]["FORGE_TOKEN_OPENCODE"] == JETON
    assert "FORGE_MCP_TOKEN" not in vu["env"]
    assert MAITRE not in vu["env"].values()
    assert Path(vu["env"]["OPENCODE_CONFIG_DIR"]).resolve() == CONFIG.parent.resolve()


def _config():
    lignes = [l for l in CONFIG.read_text(encoding="utf-8").splitlines()
              if not l.strip().startswith("//")]
    return json.loads("\n".join(lignes))


def test_config_gouvernee_identite_et_outils_natifs_coupes():
    cfg = _config()
    laforge = cfg["mcp"]["laforge"]
    assert laforge["type"] == "remote" and laforge["url"].endswith(":8766/mcp")
    assert laforge["headers"]["Authorization"] == "Bearer {env:FORGE_TOKEN_OPENCODE}"
    assert laforge["headers"]["X-Agent-Name"] == "OPENCODE"
    assert cfg["permission"]["bash"] == "deny" and cfg["permission"]["edit"] == "deny"
    # Hors commentaires : la prose explique pourquoi le maitre est exclu, et un instrument
    # ne doit pas lire son propre vocabulaire.
    assert "FORGE_MCP_TOKEN" not in json.dumps(cfg), "la config nomme le jeton MAITRE"
    assert not re.search(r"Bearer (?!\{env:)", json.dumps(cfg)), "Bearer en clair dans la config"


def test_modele_par_la_passerelle_gouvernee_et_zen_coupe():
    """Decision owner du 25/09 : fournisseur = proxy Nokido :7777, jamais le cloud d'opencode."""
    cfg = _config()
    nokido = cfg["provider"]["nokido"]
    assert nokido["options"]["baseURL"] == "http://127.0.0.1:7777/v1"
    assert nokido["options"]["apiKey"] == "{env:FORGE_TOKEN_OPENCODE}", "identite OPENCODE au proxy"
    assert "opencode" in cfg["disabled_providers"], "Zen doit rester coupe (SYMBIOSE)"
    assert cfg["model"].startswith("nokido/") and cfg["small_model"].startswith("nokido/"), (
        "un modele (meme de titrage) hors passerelle sortirait sans firewall")


def test_le_semis_connait_le_jeton_opencode():
    arbre = ast.parse(SEMIS.read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXPECTED_KEYS"
                                             for t in n.targets):
            assert "FORGE_TOKEN_OPENCODE" in [e.value for e in n.value.elts]
            return
    pytest.fail("EXPECTED_KEYS introuvable")


def test_mot_de_passe_seulement_dans_l_env_de_l_enfant(ow, capsys):
    vu = {}

    def _popen(cmd, **kw):
        vu["cmd"], vu["env"] = cmd, kw["env"]
        return _Enfant()

    job = object()
    assert ow.servir(popen=_popen, armer=lambda: job) == 0
    assert vu["env"][ow.CLE] == TEMOIN
    assert not any(TEMOIN in str(x) for x in vu["cmd"])
    assert TEMOIN not in capsys.readouterr().out
    assert job in ow._JOBS_VIVANTS, "handle du job libere : le wrapper se tuerait lui-meme"


def test_verifier_ne_montre_que_la_presence(ow, capsys):
    ow.verifier()
    sortie = capsys.readouterr().out
    assert TEMOIN not in sortie and "mot de passe : present" in sortie
    assert JETON not in sortie and "jeton agent FORGE_TOKEN_OPENCODE : present" in sortie


def _faux_serveur(reponses):
    vus = []

    def _get(chemin, entete, timeout=5.0):
        vus.append((chemin, entete))
        return reponses.get(chemin, (404, None))
    return _get, vus


def test_diagnostic_ne_montre_ni_mot_de_passe_ni_porteur(ow, capsys):
    spec = {"paths": {p: {} for p in ("/project/current", "/session", "/config/providers", "/mcp")}}
    get, vus = _faux_serveur({
        "/doc": (200, spec),
        "/project/current": (200, {"worktree": "C:/depot", "id": "p1"}),
        "/session": (200, []),
        "/config/providers": (200, {"providers": [{"id": "anthropic", "models": {"a": {}, "b": {}},
                                                   "key": "sk-temoin-ne-doit-pas-sortir"}],
                                    "default": {"anthropic": "a"}}),
        "/mcp": (200, {"laforge": {"status": "failed", "error": "401 Bearer jeton-temoin-fuite"}}),
    })
    assert ow.port_ecoute() is False  # la fixture coupe le port : on le rouvre ici
    ow.port_ecoute = lambda *a, **k: True
    assert ow.diagnostiquer(get_json=get) == ow.RC_OK
    sortie = capsys.readouterr().out
    assert TEMOIN not in sortie and "sk-temoin" not in sortie and "jeton-temoin-fuite" not in sortie
    assert "0 session(s)" in sortie and "anthropic(2 modeles)" in sortie
    assert "laforge=failed" in sortie and "<masque>" in sortie
    assert "/project           absente de l'API" in sortie
    assert all(e.startswith("Basic ") for _c, e in vus)


def test_diagnostic_compte_les_sessions_de_chaque_projet(ow, capsys):
    """/session sans parametre ne voit que le projet courant : « 0 » y masquait les autres."""
    ow.port_ecoute = lambda *a, **k: True
    ow.erreurs_du_journal = lambda: []
    get, vus = _faux_serveur({
        "/doc": (200, {"paths": {"/project": {}, "/session": {}}}),
        "/project": (200, [{"worktree": "C:/depot"}, {"worktree": "C:/parent"}]),
        "/session": (200, []),
        "/session?directory=C%3A%2Fdepot": (200, []),
        "/session?directory=C%3A%2Fparent": (200, [{"id": "s1"}, {"id": "s2"}]),
    })
    ow.diagnostiquer(get_json=get)
    sortie = capsys.readouterr().out
    assert "C:/parent" in sortie and "2 session(s)" in sortie
    assert [c for c, _e in vus].count("/session?directory=C%3A%2Fdepot") == 1


def test_nouvelle_session_par_l_api(ow, capsys):
    appels = []

    def _get(chemin, entete, timeout=5.0, corps_post=None):
        appels.append((chemin, corps_post))
        return 200, {"id": "ses_1", "directory": "C:/depot"}

    assert ow.nouvelle_session(get_json=_get) == ow.RC_OK
    assert appels[0][0].startswith("/session?directory=") and appels[0][1] is not None
    sortie = capsys.readouterr().out
    assert "ses_1" in sortie and TEMOIN not in sortie


def test_diagnostic_401_le_dit(ow, capsys):
    ow.port_ecoute = lambda *a, **k: True
    get, _vus = _faux_serveur({"/doc": (401, None)})
    assert ow.diagnostiquer(get_json=get) == ow.RC_SANS_MOT_DE_PASSE
    assert "ne correspond pas" in capsys.readouterr().out


def test_code_de_sortie_ntstatus_ne_casse_pas_os_exit(ow):
    """Mesure du 25/09 : 0xC000013A a l'arret -> OverflowError dans os._exit."""
    assert ow.code_de_sortie(0xC000013A) == 0xC000013A - 0x100000000
    assert ow.code_de_sortie(0) == 0 and ow.code_de_sortie(2) == 2
    assert ow.code_de_sortie(None) == 1
    assert -2**31 <= ow.code_de_sortie(2**40 + 5) < 2**31


def test_journal_introuvable_se_dit(ow, monkeypatch, tmp_path):
    monkeypatch.setattr(ow, "journaux_opencode", lambda: [tmp_path / "absent"])
    (ligne,) = ow.erreurs_du_journal()
    assert "INTROUVABLE" in ligne and str(tmp_path / "absent") in ligne


def test_journal_erreurs_seules_porteur_masque(ow, monkeypatch, tmp_path):
    d = tmp_path / "log"
    d.mkdir()
    (d / "2026.log").write_text(
        "INFO  service=server ok\n"
        "ERROR service=provider Authorization: Bearer jeton-temoin-journal echec\n"
        "WARN  service=session lent\n", encoding="utf-8")
    monkeypatch.setattr(ow, "journaux_opencode", lambda: [d])
    lignes = ow.erreurs_du_journal()
    assert "2 ligne(s) ERROR/WARN" in lignes[0]
    assert not any("service=server ok" in l for l in lignes)
    assert not any("jeton-temoin-journal" in l for l in lignes)
    assert any("<masque>" in l for l in lignes)


def test_point_d_entree_reel_repond():
    r = subprocess.run([sys.executable, str(OUTIL), "--verifier"], capture_output=True,
                       text=True, errors="replace", timeout=60, cwd=str(ROOT))
    assert "Traceback" not in r.stderr, r.stderr[-800:]
    assert r.returncode in (0, 2), (r.returncode, r.stdout[-400:], r.stderr[-400:])
    assert "mot de passe :" in r.stdout


def test_lanceur_declare_opencode_en_lien_direct():
    from app.web_hub import launcher as LA
    spec = LA.MODULES["opencode"]
    ow = _charger()
    assert spec.default_port == ow.PORT
    assert (ROOT / spec.script).resolve() == OUTIL.resolve()
    assert spec.open_path.startswith("http://127.0.0.1:%d" % ow.PORT)
    assert spec.watch is False and spec.api_managed is True


def test_tuile_du_portail_meme_port_sans_healthcheck():
    arbre = ast.parse(APP.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SERVICES"
                                             for t in n.targets):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant) and k.value == "opencode":
                    tuile = {kk.value: vv.value for kk, vv in zip(v.keys, v.values)
                             if isinstance(kk, ast.Constant) and isinstance(vv, ast.Constant)}
                    assert re.search(r"127\.0\.0\.1:4096$", tuile["target"])
                    assert tuile.get("external") is True
                    assert "healthcheck" not in tuile, "GET / rend 401 par construction"
                    return
    pytest.fail("tuile opencode absente de SERVICES")
