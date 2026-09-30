"""NR -- les acces SSH (et les clefs d'API) vivent au COFFRE, jamais recopies en clair dans Nokido.env.

Owner 2026-09-25 : « il ne faut pas mettre en dur mes acces SSH sur la version dist, et il faudra
proposer de renseigner des acces ssh au vault (comme pour les clefs api) sur la page de config des
acces ». MESURES du jour :
  - `Settings` lisait SSH_HOST / SSH_USER / PRIVATE_KEY_PATH dans os.environ SEUL : le coffre
    n'etait jamais consulte pour eux ;
  - `forge_env_sync.sync_env` RECOPIAIT ces variables -- et GEMINI_API_KEY, LITELLM_API_KEY -- de
    l'environnement de l'hote vers Nokido.env, EN CLAIR, a chaque construction de Settings ;
  - l'assistant SSH de la TUI (app/Nokido.py `_write_env`) ecrivait les acces dans Nokido.env.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app + lecture (l.147)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_env_sync as fes  # noqa: E402
from nokido_agent.app import forge_secrets as fsec  # noqa: E402
from nokido_agent.app import forge_settings as fs  # noqa: E402

SECRETS = ("SSH_HOST", "SSH_PORT", "SSH_USER", "PRIVATE_KEY_PATH", "GEMINI_API_KEY", "LITELLM_API_KEY")


def _sans_effets_de_bord(monkeypatch):
    monkeypatch.setattr(fes, "sync_env", lambda dry_run=False: [])


def test_settings_lit_les_acces_ssh_au_coffre_avant_l_environnement(monkeypatch):
    coffre = {"SSH_HOST": "hote-du-coffre", "SSH_USER": "user-du-coffre", "PRIVATE_KEY_PATH": "C:/cle_du_coffre",
              "SSH_PORT": "2222"}
    monkeypatch.setattr(fsec, "get_secret", lambda k, required=False: coffre.get(k))
    monkeypatch.setenv("SSH_HOST", "hote-de-l-environnement")
    _sans_effets_de_bord(monkeypatch)
    s = fs.Settings()
    assert (s.ssh_host, s.ssh_user, s.ssh_port) == ("hote-du-coffre", "user-du-coffre", 2222)
    assert str(s.private_key_path).replace("\\", "/") == "C:/cle_du_coffre"


def test_sans_coffre_le_comportement_actuel_est_conserve(monkeypatch):
    monkeypatch.setattr(fsec, "get_secret", lambda k, required=False: None)
    monkeypatch.setenv("SSH_HOST", "hote-de-l-environnement")
    _sans_effets_de_bord(monkeypatch)
    assert fs.Settings().ssh_host == "hote-de-l-environnement"


def test_un_coffre_qui_leve_ne_casse_pas_les_reglages(monkeypatch):
    def _leve(k, required=False):
        raise OSError("coffre illisible")
    monkeypatch.setattr(fsec, "get_secret", _leve)
    monkeypatch.setenv("SSH_HOST", "hote-de-l-environnement")
    _sans_effets_de_bord(monkeypatch)
    assert fs.Settings().ssh_host == "hote-de-l-environnement"


def test_sync_env_ne_recopie_plus_aucun_secret_en_clair(monkeypatch):
    monkeypatch.setattr(fes, "_read_env_file", lambda: {})
    for k in SECRETS:
        monkeypatch.setenv(k, "valeur-de-l-hote")
    rapport = fes.sync_env(dry_run=True)
    injectes = {r["key"] for r in rapport if r["action"] == "injected"}
    assert not injectes & set(SECRETS), "recopies en clair : %s" % sorted(injectes & set(SECRETS))
    assert {r["key"] for r in rapport if r["action"] == "coffre"} == set(SECRETS)


def test_la_page_ne_pose_que_des_acces_de_la_liste_blanche(monkeypatch):
    """La page de saisie n'est pas un ecrivain de secret generique : une cle hors liste est refusee."""
    from nokido_agent.app import forge_provider_admin as pa
    poses = []
    monkeypatch.setattr(fsec, "set_secret", lambda k, v: poses.append((k, v)) or True)
    assert pa.definir_acces("GROQ_API_KEY", "x")["ok"] is False
    assert pa.definir_acces("SSH_HOST", "  ")["ok"] is False
    assert pa.definir_acces("SSH_HOST", "mon-hote")["ok"] is True
    assert poses == [("SSH_HOST", "mon-hote")]


def test_l_etat_des_acces_dit_la_source_jamais_la_valeur(monkeypatch):
    from nokido_agent.app import forge_provider_admin as pa
    sources = {("coffre", "SSH_HOST"): "hote-secret", ("dotenv", "SSH_USER"): "user-secret"}
    monkeypatch.setattr(fsec, "_sonder", lambda nom, k: (sources.get((nom, k)), False))
    for k in ("SSH_HOST", "SSH_USER", "PRIVATE_KEY_PATH", "SSH_PORT"):
        monkeypatch.delenv(k, raising=False)
    etat = {a["cle"]: a for a in pa.etat_des_acces()}
    assert (etat["SSH_HOST"]["source"], etat["SSH_HOST"]["en_clair"]) == ("coffre", False)
    assert (etat["SSH_USER"]["source"], etat["SSH_USER"]["en_clair"]) == ("dotenv", True)
    assert etat["PRIVATE_KEY_PATH"]["source"] is None
    import json as _json
    assert "secret" not in _json.dumps(list(etat.values()))


def test_l_ecriture_exige_le_ring_1(monkeypatch):
    import asyncio
    from nokido_agent.app import forge_provider_admin as pa

    class _Req:
        path_params = {"cle": "SSH_HOST"}

        async def json(self):
            return {"valeur": "h"}
    monkeypatch.setattr(pa, "_resolve_request_ring", lambda r: 3)
    assert asyncio.run(pa.api_set_access(_Req())).status_code == 403


def test_routes_du_hub_et_relais_du_portail():
    from nokido_agent.app import forge_provider_admin as pa
    chemins_hub = {(r.path, tuple(sorted(r.methods or []))) for r in pa.get_starlette_routes()}
    assert ("/api/access", ("GET", "HEAD")) in chemins_hub
    assert any(p == "/api/access/{cle}" and "POST" in m for p, m in chemins_hub)
    assert any(p == "/api/access/{cle}" and "DELETE" in m for p, m in chemins_hub)
    web = (RACINE / "app" / "web_hub" / "provider_views.py").read_text(encoding="utf-8")
    for route in ('@router.get("/api/providers/acces")', '@router.post("/api/providers/acces/{cle}")',
                  '@router.delete("/api/providers/acces/{cle}")', 'id="acces-ssh"'):
        assert route in web, route
    assert "/api/providers/acces" in (RACINE / "app" / "web_hub" / "static" / "providers.js").read_text(encoding="utf-8")


def test_une_cle_illisible_n_est_pas_absente_et_ne_leve_pas(monkeypatch):
    """MESURE pre-controle 2026-09-25 : Settings trouve desormais le chemin de la cle (coffre ou
    Nokido.env), et `Path.exists()` LEVE PermissionError sous un compte qui ne peut pas lire le
    profil de l'owner -- validate_all plantait. ILLISIBLE n'est pas ABSENT : c'est dit, pas leve."""
    coffre = {"SSH_HOST": "h", "SSH_USER": "u", "PRIVATE_KEY_PATH": "C:/profil_owner/cle"}
    monkeypatch.setattr(fsec, "get_secret", lambda k, required=False: coffre.get(k))
    _sans_effets_de_bord(monkeypatch)
    vrai_exists = fs.Path.exists

    def _exists(self):
        if str(self).replace("\\", "/").endswith("profil_owner/cle"):
            raise PermissionError(5, "Acces refuse")
        return vrai_exists(self)
    monkeypatch.setattr(fs.Path, "exists", _exists)
    erreurs = fs.Settings().validate_all()
    assert any("ILLISIBLE" in e for e in erreurs), erreurs
    assert not any("introuvable" in e for e in erreurs)


def test_aucun_lecteur_brut_des_acces_ssh_hors_du_coffre():
    """CLIQUET. `forge_env_to_vault.JAMAIS_NEUTRALISER` le disait : brain_worker (L1189-1192) et
    forge_mesh_memory (L300-302, L410) lisaient les acces SSH par os.environ BRUT -- vider la ligne
    de Nokido.env les privait d'acces. Une lecture passe par forge_secrets.get_secret (coffre d'abord)."""
    import re
    motif = re.compile(r"(os\.environ\.get|os\.getenv)\(\s*[\"'](SSH_HOST|SSH_PORT|SSH_USER|PRIVATE_KEY_PATH)[\"']")
    fautifs = []
    for p in (RACINE / "app").rglob("*.py"):
        if any(x in p.parts for x in ("_attic", "backups", "tests", "__pycache__")):
            continue
        for n, ligne in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if motif.search(ligne) and "forge_settings.py" not in str(p):
                fautifs.append("%s:%d" % (p.relative_to(RACINE), n))
    assert not fautifs, "lecteurs bruts des acces SSH : %s" % fautifs


def test_l_assistant_ssh_de_la_tui_n_ecrit_plus_nokido_env():
    """Garde de SOURCE : la TUI (app/Nokido.py) est trop lourde a instancier dans un test pur."""
    src = (RACINE / "app" / "Nokido.py").read_text(encoding="utf-8")
    debut = src.index("def _write_env(")
    corps = src[debut:src.index("def on_button_pressed(", debut)]
    assert "set_secret" in corps
    assert "write_text" not in corps and "Nokido.env" not in corps.split('"""', 2)[2]
