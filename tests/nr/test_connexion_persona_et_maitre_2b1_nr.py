"""NR -- etape 2b-1 du correctif du coffre (plan valide par l'owner le 2026-09-28).

Mesure du 2026-09-28 (lecture de code + ACL, non exercee) :
  - `login_agent` acceptait une connexion signee HMAC(`role_id:timestamp`) avec la cle
    persona pour N'IMPORTE QUEL role, ring <= 1 compris. La cle vivait dans un fichier
    lisible par les comptes bac a sable, et son dernier repli etait le sha256 du NOM DE
    MACHINE -- une valeur publique. Depuis les ACL owner du 28/09 le fichier n'est lisible
    que par SYSTEM et les administrateurs : tout autre compte tombait donc sur ce repli ;
  - le jeton maitre valait identite de l'owner et de MASTER_TOKEN dans `login_agent`.

Ce que ce NR verrouille :
  - la cle persona est un nom reserve (coffre reserve lu d'abord, recensement) ;
  - cle illisible -> `_hmac_key` LEVE, jamais de repli sur le nom de machine ;
    `sign_identity` ne fabrique pas de tag `hmac:` sans cle ; `forge_release_lock` ne
    plante pas et ne crie pas a la falsification quand il ne peut pas lire la cle ;
  - connexion par HMAC persona refusee pour ring <= 1 (TPM exige), acceptee au-dela ;
  - le maitre n'est plus l'identifiant de l'owner ni de MASTER_TOKEN, sur les trois
    chemins de chargement ; le secret propre d'un agent passe toujours ;
  - l'outil de provisionnement ne COPIE jamais la cle persona (valeur reputee eventee) et
    n'en genere une nouvelle que sur `--rotation-persona`.
Aucune valeur reelle : cles et jetons fabriques ici, coffre et registre simules.
"""
import hashlib
import hmac
import importlib
import importlib.util
import os
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAITRE = "maitre-nr-2b1-" + "a" * 40
JETON_CLAUDE = "jeton-claude-nr-2b1-" + "b" * 40
CLE_PERSONA = b"cle-persona-nr-2b1-" + b"c" * 32


def _identite_owner() -> str:
    """Le nom de l'owner, lu dans la configuration du videur (`_OWNER_AGENTS`) et non ecrit
    ici : il ne doit pas figurer dans le code distribue."""
    v = importlib.import_module("nokido_agent.app.forge_videur")
    autres = sorted(a for a in v._OWNER_AGENTS if a not in ("CLAUDE", "CLI_CLAUDE", "MASTER_TOKEN"))
    return autres[0] if autres else "OWNER"


OWNER = _identite_owner()
RINGS = {"NR_MAITRE": -1, "NR_SYSTEME": 0, "NR_DEV": 1, "NR_CONFIANCE": 2,
         "NR_COLLAB": 3, "CLAUDE": 1, OWNER: 0, "MASTER_TOKEN": 0}


@pytest.fixture
def ja(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_auth_tokens")
    monkeypatch.setattr(mod, "_load_store", lambda: dict(RINGS))
    return mod


@pytest.fixture
def tpm():
    return importlib.import_module("nokido_agent.app.forge_persona_tpm")


def _cle_nom_de_machine() -> bytes:
    return hashlib.sha256(
        ("laforge-persona@" + os.environ.get("COMPUTERNAME", "host")).encode()).digest()


class _FichierIllisible:
    """Le fichier de cle existe mais ce compte ne peut pas le lire (ACL owner du 28/09)."""

    def exists(self):
        return True

    def read_bytes(self):
        raise PermissionError("acces refuse (simule)")


class _DossierInterdit:
    def mkdir(self, *a, **kw):
        raise PermissionError("acces refuse (simule)")


class _DossierPermis:
    def mkdir(self, *a, **kw):
        return None


class _FichierAbsent:
    """Aucun fichier de cle, dossier INSCRIPTIBLE. Le module ne doit PAS en creer un :
    cree ici, il heriterait l'ACL de `sandbox/`, lisible par les comptes bac a sable."""

    def __init__(self):
        self.ecritures = 0
        self.parent = _DossierPermis()

    def exists(self):
        return False

    def write_bytes(self, _octets):
        self.ecritures += 1


def _sans_cle_persona(tpm, monkeypatch):
    monkeypatch.setattr(tpm, "get_secret", lambda k, required=False: None)
    monkeypatch.setattr(tpm, "_HMAC_KEY_FILE", _FichierIllisible())


def _charger_outil(nom_fichier: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, ROOT / "tools" / nom_fichier)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- la cle persona -----------------------------------------------------------------

def test_la_cle_persona_est_un_nom_reserve():
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    assert "FORGE_PERSONA_HMAC_KEY" in fs.NOMS_RESERVES


@pytest.mark.parametrize("fichier", [_FichierIllisible(), _FichierAbsent()],
                         ids=["illisible", "absent"])
def test_cle_persona_introuvable_leve_au_lieu_du_nom_de_machine(tpm, monkeypatch, fichier):
    monkeypatch.setattr(tpm, "get_secret", lambda k, required=False: None)
    monkeypatch.setattr(tpm, "_HMAC_KEY_FILE", fichier)
    try:
        cle = tpm._hmac_key()
    except RuntimeError:
        cle = None
    assert cle != _cle_nom_de_machine(), "repli sur le nom de machine : une cle PUBLIQUE"
    assert cle is None, "sans cle lisible, _hmac_key doit lever (fail-closed)"


def test_cle_persona_absente_aucun_fichier_n_est_cree(tpm, monkeypatch):
    fichier = _FichierAbsent()
    monkeypatch.setattr(tpm, "get_secret", lambda k, required=False: None)
    monkeypatch.setattr(tpm, "_HMAC_KEY_FILE", fichier)
    with pytest.raises(RuntimeError):
        tpm._hmac_key()
    assert fichier.ecritures == 0, "fichier de cle cree avec l'ACL heritee de sandbox/"


def test_cle_persona_du_guichet_toujours_servie(tpm, monkeypatch):
    monkeypatch.setattr(tpm, "get_secret",
                        lambda k, required=False: "cle-guichet-nr"
                        if k == "FORGE_PERSONA_HMAC_KEY" else None)
    monkeypatch.setattr(tpm, "_HMAC_KEY_FILE", _FichierIllisible())
    assert tpm._hmac_key() == b"cle-guichet-nr"


def test_sign_identity_sans_cle_ne_fabrique_pas_de_tag_hmac(tpm, monkeypatch):
    monkeypatch.setattr(tpm, "sign", lambda *a, **kw: None)
    _sans_cle_persona(tpm, monkeypatch)
    tag = tpm.sign_identity("texte nr")  # ne leve jamais : contrat de la persona
    assert not tag.startswith("hmac:")
    assert tag.startswith("aucune:")


def test_verrou_de_release_sans_cle_ni_plantage_ni_fausse_accusation(tpm, monkeypatch):
    rl = _charger_outil("forge_release_lock.py", "forge_release_lock_nr_2b1")
    monkeypatch.setattr(tpm, "sign", lambda *a, **kw: None)
    _sans_cle_persona(tpm, monkeypatch)
    verrou = {"sha": "0" * 40, "date": "2026-09-28"}
    prov = rl._sign_provenance(verrou)
    assert prov["scheme"] == "none"  # empreinte posee, absence de signature DITE
    verrou["provenance"] = {"scheme": "hmac-sha256", "digest": prov["digest"],
                            "sig": "00" * 32}
    # ACCES != AUTHENTICITE : une cle qu'on ne peut pas lire ne prouve pas un faux.
    assert rl._verify_provenance(verrou)["etat"] == "INDETERMINE"


# --- connexion par HMAC persona -----------------------------------------------------

def _signature(role: str, ts: float, cle: bytes = CLE_PERSONA) -> str:
    return hmac.new(cle, f"{role}:{ts}".encode("utf-8"), hashlib.sha256).hexdigest()


@pytest.fixture
def persona_hmac_seule(tpm, monkeypatch):
    """TPM qui ne reconnait rien, cle persona connue : seul le chemin HMAC peut passer."""
    monkeypatch.setattr(tpm, "verify", lambda payload, sig: False)
    monkeypatch.setattr(tpm, "_hmac_key", lambda: CLE_PERSONA)


@pytest.mark.parametrize("role", ["NR_MAITRE", "NR_SYSTEME", "NR_DEV"])
def test_hmac_persona_refuse_pour_ring_le_1(ja, persona_hmac_seule, role):
    ts = time.time()
    with pytest.raises(ValueError, match="TPM"):
        ja.login_agent(role, timestamp=ts, signature=_signature(role, ts))


@pytest.mark.parametrize("role", ["NR_CONFIANCE", "NR_COLLAB"])
def test_hmac_persona_accepte_au_dela_du_ring_1(ja, persona_hmac_seule, role):
    ts = time.time()
    assert ja.login_agent(role, timestamp=ts, signature=_signature(role, ts))


def test_hmac_persona_d_une_autre_cle_refuse(ja, persona_hmac_seule):
    ts = time.time()
    with pytest.raises(ValueError):
        ja.login_agent("NR_CONFIANCE", timestamp=ts,
                       signature=_signature("NR_CONFIANCE", ts, b"autre-cle"))


# --- le maitre n'est plus une identite ---------------------------------------------

def test_registre_injecte_le_secret_d_une_identite_n_ouvre_pas_l_autre(ja):
    with pytest.raises(ValueError, match="Invalid credentials"):
        ja.login_agent(OWNER, secret_id=MAITRE, agent_tokens={"MASTER_TOKEN": MAITRE})
    with pytest.raises(ValueError, match="Invalid credentials"):
        ja.login_agent("MASTER_TOKEN", secret_id=MAITRE, agent_tokens={OWNER: MAITRE})


class _HubSentinelle(types.ModuleType):
    """Un hub deja charge sous le nom d'import de la bibliotheque : y toucher est une
    faute (process client = hub entier charge ; tests = jetons d'une autre instance)."""

    touche = 0

    def __getattr__(self, nom):
        _HubSentinelle.touche += 1
        raise AttributeError(nom)


def test_la_bibliotheque_ne_lit_jamais_les_jetons_du_hub(ja, monkeypatch):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    store = {"FORGE_MCP_TOKEN": MAITRE, "FORGE_TOKEN_CLAUDE": JETON_CLAUDE}
    _HubSentinelle.touche = 0
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.nokido_hub",
                        _HubSentinelle("nokido_agent.tools.nokido_hub"))
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.setattr(ja, "_agents_connus", lambda: ["CLAUDE"])
    for role in (OWNER, "MASTER_TOKEN"):
        with pytest.raises(ValueError, match="Invalid credentials"):
            ja.login_agent(role, secret_id=MAITRE)
    assert ja.login_agent("CLAUDE", secret_id=JETON_CLAUDE)
    assert _HubSentinelle.touche == 0, "login_agent a lu les jetons dans le module du hub"


def test_guichet_illisible_se_dit_au_journal(ja, monkeypatch, caplog):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")

    def _panne(k, required=False):
        raise OSError("guichet illisible (simule)")

    monkeypatch.setattr(fs, "get_secret", _panne)
    monkeypatch.setattr(ja, "_agents_connus", lambda: ["CLAUDE"])
    with caplog.at_level("WARNING"):
        with pytest.raises(ValueError, match="Invalid credentials"):
            ja.login_agent("CLAUDE", secret_id=JETON_CLAUDE)
    assert "guichet illisible" in caplog.text


def test_chemin_guichet_le_maitre_n_est_plus_l_identite_de_l_owner(ja, monkeypatch):
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    store = {"FORGE_MCP_TOKEN": MAITRE, "FORGE_TOKEN_CLAUDE": JETON_CLAUDE}
    # Hub non importable : `login_agent` charge alors les jetons par le guichet.
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.nokido_hub", None)
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.setattr(ja, "_agents_connus", lambda: ["CLAUDE"])
    for role in (OWNER, "MASTER_TOKEN"):
        with pytest.raises(ValueError, match="Invalid credentials"):
            ja.login_agent(role, secret_id=MAITRE)
    assert ja.login_agent("CLAUDE", secret_id=JETON_CLAUDE)


# --- provisionnement ---------------------------------------------------------------

def test_la_cle_persona_n_est_jamais_copiee_et_ne_se_genere_que_sur_rotation():
    o = _charger_outil("forge_coffre_reserve_provision.py", "forge_coffre_provision_nr_2b1")
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    nom = "FORGE_PERSONA_HMAC_KEY"
    assert nom in o.NOUVELLES
    assert nom not in o.COPIES + o.DEDIEES

    def absente(_n):
        return None, mv.RESERVE_CLE_ABSENTE

    def presente(_n):
        return "valeur-simulee", mv.RESERVE_TROUVE

    assert o.planifier_nouvelles(absente, rotation=False)[nom] == o.A_GENERER
    assert o.planifier_nouvelles(absente, rotation=True)[nom] == o.A_ECRIRE
    for rotation in (False, True):
        assert o.planifier_nouvelles(presente, rotation=rotation)[nom] == o.DEJA_EN_PLACE
