"""NR — forge_provision_clients n'ecrit plus les jetons de TOUS les agents en clair dans
C:\\tmp quand on ne lui demande qu'une reparation ciblee (2026-10-15).

Mesure : `C:\\tmp\\mcp_client_configs.txt` existait depuis le 2026-08-03, lisible par le
compte de bac a sable du hub. Toute execution hors --dry-run le reecrivait, y compris
--patch-codex, le geste prevu pour reparer le seul jeton de codex.
Les effets reels de l'outil (registre HKCU, ~/.codex/config.toml) sont neutralises ici.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

OUTIL = Path(__file__).resolve().parents[2] / "tools" / "forge_provision_clients.py"


@pytest.fixture
def outil(monkeypatch, tmp_path):
    secrets_factices = types.ModuleType("nokido_agent.app.forge_secrets")
    secrets_factices.get_secret = lambda cle: "jeton-factice-" + cle
    secrets_factices.set_secret = lambda cle, valeur: True
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", secrets_factices)
    spec = importlib.util.spec_from_file_location("forge_provision_clients_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", str(tmp_path / "mcp_client_configs.txt"))
    # Aucun effet hors du test : ni registre, ni config codex, ni lecture de l'environnement.
    monkeypatch.setattr(mod, "_sync_env", lambda tok, dry: [])
    monkeypatch.setattr(mod, "_check_env", lambda tok: [])
    monkeypatch.setattr(mod, "_patch_codex", lambda jeton, dry: [])
    return mod


def _lancer(mod, monkeypatch, *drapeaux):
    monkeypatch.setattr(sys, "argv", ["forge_provision_clients.py", *drapeaux])
    mod.main()
    return Path(mod.OUT).exists()


@pytest.mark.parametrize("drapeau", ["--apply", "--patch-codex", "--check"])
def test_un_mode_cible_n_ecrit_pas_les_jetons(outil, monkeypatch, capsys, drapeau):
    assert not _lancer(outil, monkeypatch, drapeau)
    assert "NON emises" in capsys.readouterr().out


def test_emettre_reste_possible_sur_demande(outil, monkeypatch):
    assert _lancer(outil, monkeypatch, "--check", "--emettre")


def test_sans_mode_cible_l_emission_reste_le_defaut(outil, monkeypatch):
    assert _lancer(outil, monkeypatch)


def test_dry_run_n_ecrit_rien(outil, monkeypatch):
    assert not _lancer(outil, monkeypatch, "--dry-run")


# --- Aucune EMPREINTE non plus (owner 16/10 : « booleens seulement, pas meme une empreinte ») ---------------------------
# L'outil imprimait le sha8 de chaque jeton dans quatre rapports. Une empreinte reste un derive du secret : elle se
# recoupe d'un journal a l'autre et confirme une valeur devinee. Comparer reste possible, en memoire, sans rien afficher.
import contextlib
import hashlib
import secrets as _secrets


def _formes(*valeurs):
    """Les deux formes deja vues affichees pour un jeton : son sha8 et sa queue de 6 caracteres."""
    return [f(v) for v in valeurs if v
            for f in (lambda x: hashlib.sha256(x.encode()).hexdigest()[:8], lambda x: x[-6:])]


def _sans_empreinte(sortie, *valeurs):
    texte = "\n".join(sortie) if isinstance(sortie, list) else sortie
    fuites = [e for e in _formes(*valeurs) if e in texte]
    # le message ne recopie JAMAIS la forme fuyante : seulement leur nombre
    assert not fuites and "sha8" not in texte, "%d forme(s) de jeton affichee(s)" % len(fuites)


class _Registre:
    """HKCU\\Environment factice : le test ne lit jamais le registre du compte qui le lance."""
    HKEY_CURRENT_USER = object()

    def __init__(self, valeurs):
        self.valeurs = valeurs

    def OpenKey(self, *_a):
        return contextlib.nullcontext(self)

    def QueryValueEx(self, _k, nom):
        if nom not in self.valeurs:
            raise FileNotFoundError(nom)
        return self.valeurs[nom], 1


@pytest.fixture
def brut(monkeypatch, tmp_path):
    """L'outil SANS neutralisation de ses rapports : seuls le coffre, le registre et ~ sont factices."""
    coffre = {}
    faux = types.ModuleType("nokido_agent.app.forge_secrets")
    setattr(faux, "get_secret", coffre.get)
    setattr(faux, "set_secret", lambda cle, valeur: coffre.__setitem__(cle, valeur) or True)
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", faux)
    spec = importlib.util.spec_from_file_location("forge_provision_clients_brut_nr", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", str(tmp_path / "mcp_client_configs.txt"))
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(tmp_path))
    for a in mod.AGENTS:
        monkeypatch.delenv("FORGE_TOKEN_%s" % a, raising=False)
    return mod, coffre


def test_le_rapport_de_provisionnement_n_imprime_aucune_empreinte(brut, monkeypatch, capsys):
    mod, coffre = brut
    present = _secrets.token_hex(24)
    coffre["FORGE_TOKEN_%s" % mod.AGENTS[0]] = present
    neuf = _secrets.token_hex(24)
    monkeypatch.setattr(mod._secrets, "token_hex", lambda n=24: neuf)
    monkeypatch.setitem(sys.modules, "winreg", _Registre({}))
    monkeypatch.setattr(sys, "argv", ["forge_provision_clients.py", "--check"])
    mod.main()
    _sans_empreinte(capsys.readouterr().out, present, neuf)


def test_la_verification_compare_sans_rien_afficher(brut, monkeypatch):
    mod, _ = brut
    a0, a1 = mod.AGENTS[0], mod.AGENTS[1]
    v0, v1, vieux = _secrets.token_hex(24), _secrets.token_hex(24), _secrets.token_hex(24)
    monkeypatch.setitem(sys.modules, "winreg", _Registre({"FORGE_TOKEN_%s" % a0: v0, "FORGE_TOKEN_%s" % a1: v1}))
    monkeypatch.setenv("FORGE_TOKEN_%s" % a0, v0)
    monkeypatch.setenv("FORGE_TOKEN_%s" % a1, vieux)
    sortie = mod._check_env({a0: v0, a1: v1})
    _sans_empreinte(sortie, v0, v1, vieux)
    ligne = {a: next(l for l in sortie if ("FORGE_TOKEN_%s " % a) in l) for a in (a0, a1)}
    assert "ALIGNE" in ligne[a0] and "session PERIMEE" in ligne[a1], "la comparaison doit survivre au retrait"


@pytest.mark.parametrize("dry", [True, False])
def test_la_synchronisation_n_imprime_aucune_empreinte(brut, monkeypatch, dry):
    mod, _ = brut
    v = _secrets.token_hex(24)
    monkeypatch.setattr(mod, "_poser_env_utilisateur", lambda nom, valeur: "pose")
    _sans_empreinte(mod._sync_env({mod.AGENTS[0]: v}, dry), v)


@pytest.mark.parametrize("dry", [True, False])
def test_la_bascule_codex_n_imprime_aucune_empreinte(brut, tmp_path, dry):
    mod, _ = brut
    jeton = _secrets.token_hex(24)
    cfg = tmp_path / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[mcp_servers.laforge]\nurl = "http://127.0.0.1:8766/mcp"\n'
                   'bearer_token_env_var = "FORGE_TOKEN_CODEX"\n', encoding="utf-8")
    _sans_empreinte(mod._patch_codex(jeton, dry), jeton)
    assert (jeton in cfg.read_text(encoding="utf-8")) is (not dry), "l'effet de la bascule doit etre conserve"
