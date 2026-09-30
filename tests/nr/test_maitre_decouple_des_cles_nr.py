"""NR — etape 1 du correctif du coffre : le JETON MAITRE n'est plus une CLE.

Mesure du 2026-09-28 : `FORGE_MCP_TOKEN`, porteur de ring 0 lisible par les comptes
bac a sable au coffre machine, servait AUSSI de repli du secret JWT, de cle HMAC
(ledger vectoriel, sanitizer, sel de sauvegarde, bus d'etat) et de source de la cle
Fernet. Consequence : le faire tourner cassait les signatures deja posees et le
dechiffrement -- donc on ne le faisait jamais tourner.

Ce que ce NR verrouille :
  - le JWT ne retombe plus sur le maitre : un jeton signe avec le maitre est refuse,
    et sans secret JWT dedie on ne signe rien (fail-closed) ;
  - les HMAC locaux lisent `NOKIDO_HMAC_KEY` d'abord ; sans elle, RIEN ne change
    (repli de transition sur le maitre) ; provisionnee a la valeur du maitre, RIEN ne
    change non plus ; ensuite le maitre peut tourner sans toucher la signature ;
  - la cle Fernet est lue au coffre, plus seulement dans l'environnement ;
  - ces cles rejoignent le recensement de l'etape 0.
Aucune valeur reelle : chaque module lit un coffre simule (dict).
"""
import importlib

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus wmic/powershell (code appele,
#   Windows) (l.70)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

MAITRE = "maitre-nr-" + "a" * 40
MAITRE_TOURNE = "maitre-nr-tourne-" + "b" * 40
DEDIEE = "cle-hmac-dediee-nr-" + "c" * 40
JWT_DEDIE = "jwt-dedie-nr-" + "d" * 40

SIGNATAIRES = [
    ("nokido_agent.app.forge_vec_ledger", "_get_signing_key"),
    ("nokido_agent.app.forge_conv_sanitizer", "_signing_key"),
]


def _coffre(monkeypatch, mod, store):
    """Le module lit `store` a la place du guichet (lu A CHAQUE appel)."""
    monkeypatch.setattr(mod, "get_secret", lambda k, required=False: store.get(k))


@pytest.mark.parametrize("nom_mod, fonction", SIGNATAIRES)
def test_sans_cle_dediee_la_signature_est_celle_d_avant(nom_mod, fonction, monkeypatch):
    mod = importlib.import_module(nom_mod)
    _coffre(monkeypatch, mod, {"FORGE_MCP_TOKEN": MAITRE})
    assert getattr(mod, fonction)() == MAITRE.encode()[:64]


@pytest.mark.parametrize("nom_mod, fonction", SIGNATAIRES)
def test_provisionnee_a_la_valeur_du_maitre_rien_ne_change(nom_mod, fonction, monkeypatch):
    mod = importlib.import_module(nom_mod)
    store = {"FORGE_MCP_TOKEN": MAITRE}
    _coffre(monkeypatch, mod, store)
    avant = getattr(mod, fonction)()
    store["NOKIDO_HMAC_KEY"] = MAITRE
    assert getattr(mod, fonction)() == avant


@pytest.mark.parametrize("nom_mod, fonction", SIGNATAIRES)
def test_la_rotation_du_maitre_ne_touche_plus_la_signature(nom_mod, fonction, monkeypatch):
    mod = importlib.import_module(nom_mod)
    store = {"FORGE_MCP_TOKEN": MAITRE, "NOKIDO_HMAC_KEY": DEDIEE}
    _coffre(monkeypatch, mod, store)
    avant = getattr(mod, fonction)()
    store["FORGE_MCP_TOKEN"] = MAITRE_TOURNE
    assert getattr(mod, fonction)() == avant == DEDIEE.encode()[:64]


def test_le_sel_de_sauvegarde_survit_a_la_rotation_du_maitre(monkeypatch):
    snap = importlib.import_module("nokido_agent.app.forge_snapshot")
    store = {"FORGE_MCP_TOKEN": MAITRE, "NOKIDO_HMAC_KEY": DEDIEE}
    _coffre(monkeypatch, snap, store)
    avant = snap.derive_backup_salt("2026-09-28T00:00:00")
    store["FORGE_MCP_TOKEN"] = MAITRE_TOURNE
    assert snap.derive_backup_salt("2026-09-28T00:00:00") == avant


def test_sans_secret_jwt_dedie_on_ne_signe_rien(monkeypatch):
    j = importlib.import_module("nokido_agent.app.forge_auth_jwt")
    _coffre(monkeypatch, j, {"FORGE_MCP_TOKEN": MAITRE})
    with pytest.raises(RuntimeError):
        j.issue_token("nr", scopes=["admin:*"], ttl_s=60)


def test_un_jwt_signe_avec_le_maitre_est_refuse(monkeypatch):
    """Sur HEAD, le repli rendait ce jeton VALIDE : quiconque lisait le maitre signait."""
    j = importlib.import_module("nokido_agent.app.forge_auth_jwt")
    store = {"LAFORGE_JWT_SECRET": MAITRE}
    _coffre(monkeypatch, j, store)
    forge = j.issue_token("nr", scopes=["admin:*"], ttl_s=60)
    store.clear()
    store["FORGE_MCP_TOKEN"] = MAITRE
    assert j.verify_token(forge) is None


def test_un_jwt_survit_a_la_rotation_du_maitre(monkeypatch):
    j = importlib.import_module("nokido_agent.app.forge_auth_jwt")
    store = {"LAFORGE_JWT_SECRET": JWT_DEDIE, "FORGE_MCP_TOKEN": MAITRE}
    _coffre(monkeypatch, j, store)
    jeton = j.issue_token("nr", scopes=["services:start"], ttl_s=60)
    store["FORGE_MCP_TOKEN"] = MAITRE_TOURNE
    assert j.verify_token(jeton, required_scope="services:start") is not None


def test_la_cle_fernet_du_coffre_est_celle_qui_chiffre(monkeypatch):
    Fernet = pytest.importorskip("cryptography.fernet").Fernet
    enc = importlib.import_module("nokido_agent.app.forge_encrypt")
    cle = Fernet.generate_key().decode()
    _coffre(monkeypatch, enc, {"FORGE_ENCRYPT_KEY": cle, "FORGE_MCP_TOKEN": MAITRE})
    monkeypatch.delenv("FORGE_ENCRYPT_KEY", raising=False)
    monkeypatch.setattr(enc, "_fernet_instance", None)
    chiffre = enc.get_fernet().encrypt(b"nr-fernet")
    assert Fernet(cle.encode()).decrypt(chiffre) == b"nr-fernet"


def test_les_cles_decouplees_rejoignent_le_recensement():
    s = importlib.import_module("nokido_agent.app.forge_secrets")
    for nom in ("FORGE_ENCRYPT_KEY", "LAFORGE_DB_KEY"):
        assert nom in s.NOMS_RESERVES, nom
    # NOKIDO_HMAC_KEY en est SORTIE (decision owner 2026-09-28) : cle d'integrite
    # partagee par des signataires qui tournent sous les comptes bac a sable.
    # Verrou : tests/nr/test_cle_integrite_partagee_nr.py.
    assert "NOKIDO_HMAC_KEY" not in s.NOMS_RESERVES
