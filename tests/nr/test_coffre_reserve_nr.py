"""NR -- etape 2a du correctif du coffre (go owner 2026-09-28) : le coffre RESERVE.

Mesure du jour : `LaForgeSbxOffline` lisait le jeton maitre, le secret de signature JWT
et le jeton admin au coffre machine (DPAPI portee MACHINE : tout compte local dechiffre).

Contrats :
  1. le coffre reserve scelle en portee UTILISATEUR ; le coffre machine reste MACHINE ;
  2. il ne s'ecrit que sous SYSTEM, jamais dans un dossier absent (cree par le module, il
     heriterait l'ACL de ProgramData), jamais par-dessus un coffre illisible ;
  3. ses lectures distinguent ABSENT et ILLISIBLE ;
  4. `get_secret` le lit D'ABORD pour les noms reserves -- et pour eux seuls -- avec
     repli sur le coffre machine ; le journal des noms reserves porte son etat ;
  5. une ecriture au coffre machine ne laisse jamais une copie reservee perimee ;
  6. l'outil de provisionnement refuse hors SYSTEM, n'ecrit rien sans --appliquer,
     n'ecrase jamais une valeur differente, n'affiche jamais une valeur, et ses cles
     dediees valent celles que les modules utilisent.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MV = "nokido_agent.app.forge_machine_vault"
FS = "nokido_agent.app.forge_secrets"
SYSTEM = "S-1-5-18"
AUTRE_COMPTE = "S-1-5-21-1-2-3-1009"
NOM = "LAFORGE_ADMIN_TOKEN"            # un nom reserve
ORDINAIRE = "NOKIDO_NR_NOM_ORDINAIRE"  # un nom qui ne l'est pas
WIN = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI : Windows seulement")

VALEURS = {
    "FORGE_MCP_TOKEN": "maitre-de-test-0001",
    "LAFORGE_SUPERVISOR_TOKEN": "superviseur-de-test-0002",
    "LAFORGE_JWT_SECRET": "jwt-de-test-0003",
    "LAFORGE_ADMIN_TOKEN": "admin-de-test-0004",
    # 2b-2 (2026-09-28)
    "MCP_DEV_SECRET": "dev-de-test-0007",
    "HUB_JWT_SECRET": "trame-de-test-0008",
    "LAFORGE_PRIV_BRIDGE_HMAC": "pont-de-test-0009",
    "firewall_log_hmac": "journal-pare-feu-de-test-0010",
    "LAFORGE_VC_KEYFILE_B64": "fichier-cle-vc-de-test-0011",
}
FERNET_TEST = "fernet-de-test-0005"
DB_TEST = "db-de-test-0006"


# DPAPI SIMULEE pour la logique. La portee UTILISATEUR exige un profil charge : mesure du
# 2026-09-28 sous LaForgeSbxOffline, `CryptProtectData` rend err 2 (aucun profil) --
# c'est le compte des NR et de la CI. SYSTEM a le sien. Le scellement REEL se prouve par
# `test_dpapi_portee_utilisateur_reelle` (qui DIT quand le compte ne peut pas) et par la
# relecture de chaque ecriture que fait l'outil sous SYSTEM.
def _faux_protect(plain: bytes, portee_machine: bool = True) -> bytes:
    return (b"M:" if portee_machine else b"U:") + plain[::-1]


def _faux_unprotect(cipher: bytes) -> bytes:
    if cipher[:2] not in (b"M:", b"U:"):
        raise OSError("CryptUnprotectData failed (err 13)")
    return cipher[2:][::-1]


@pytest.fixture
def mv(tmp_path, monkeypatch):
    m = importlib.import_module(MV)
    monkeypatch.setattr(m, "_protect", _faux_protect)
    monkeypatch.setattr(m, "_unprotect", _faux_unprotect)
    dossier = tmp_path / "NokidoCoffre"
    dossier.mkdir()
    monkeypatch.setattr(m, "RESERVE_DIR", dossier)
    monkeypatch.setattr(m, "RESERVE_PATH", dossier / "coffre_reserve.dat")
    monkeypatch.setattr(m, "_sid_courant", lambda: SYSTEM)
    # Le coffre MACHINE aussi hors du vrai : `vault_set` ecrit, `vault_get` relit.
    monkeypatch.delenv("LAFORGE_VAULT_PATH", raising=False)
    monkeypatch.setattr(m, "VAULT_PATH", tmp_path / "machine_vault.dat")
    return m


@pytest.fixture
def fs(mv, tmp_path, monkeypatch):
    s = importlib.import_module(FS)
    # Jamais le VRAI journal de recensement : il instruit l'etape 2b.
    monkeypatch.setattr(s, "_JOURNAL_RESERVES", tmp_path / "journal.jsonl")
    s._vider_observations()
    s.invalidate_cache()
    machine: dict = {}
    monkeypatch.setattr(s, "_machine_vault", lambda k: machine.get(k))
    monkeypatch.setattr(s, "_wcm", lambda k: None)
    monkeypatch.setattr(s, "_dotenv", lambda k: None)
    for k in (NOM, ORDINAIRE):
        monkeypatch.delenv(k, raising=False)
    yield s, machine
    s._vider_observations()
    s.invalidate_cache()


def _journal(s) -> list:
    p = Path(s._JOURNAL_RESERVES)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# --- 1. portee de scellement -----------------------------------------------------

def test_les_drapeaux_de_portee():
    m = importlib.import_module(MV)
    assert m._drapeaux_protection(False) & m.CRYPTPROTECT_LOCAL_MACHINE == 0
    assert m._drapeaux_protection(True) & m.CRYPTPROTECT_LOCAL_MACHINE
    assert m._drapeaux_protection(False) & m.CRYPTPROTECT_UI_FORBIDDEN


@WIN
def test_le_coffre_reserve_scelle_en_portee_utilisateur_le_machine_en_portee_machine(mv, fs, monkeypatch):
    portees = []
    vrai = mv._protect
    monkeypatch.setattr(mv, "_protect",
                        lambda plain, portee_machine=True: portees.append(portee_machine)
                        or vrai(plain, portee_machine))
    assert mv.reserve_set(NOM, "valeur-reservee")
    assert portees == [False]
    assert mv.vault_set(ORDINAIRE, "valeur-machine")
    assert portees == [False, True]


@WIN
def test_dpapi_portee_utilisateur_reelle():
    m = importlib.import_module(MV)
    try:
        blob = m._protect(b"sonde", portee_machine=False)
    except OSError as exc:
        pytest.skip(f"compte sans profil DPAPI utilisateur ({exc}) -- mesure 2026-09-28 : "
                    "err 2 sous LaForgeSbxOffline ; preuve reelle = relecture par l'outil sous SYSTEM")
    assert m._unprotect(blob) == b"sonde"


@WIN
def test_le_sid_du_process_se_lit():
    sid = importlib.import_module(MV)._sid_courant()
    assert sid and sid.startswith("S-1-5-")


# --- 2. qui ecrit, et ou ----------------------------------------------------------

def test_le_coffre_reserve_ne_s_ecrit_que_sous_system_et_jamais_ailleurs(mv, tmp_path, monkeypatch):
    for sid in (AUTRE_COMPTE, None):
        monkeypatch.setattr(mv, "_sid_courant", lambda sid=sid: sid)
        assert not mv.reserve_set(NOM, "x")
        assert not mv.RESERVE_PATH.exists()
    monkeypatch.setattr(mv, "_sid_courant", lambda: SYSTEM)
    # Dossier absent : JAMAIS cree ici, il heriterait l'ACL de ProgramData.
    absent = tmp_path / "pas_cree" / "coffre_reserve.dat"
    monkeypatch.setattr(mv, "RESERVE_PATH", absent)
    assert not mv.reserve_set(NOM, "x")
    assert not absent.parent.exists()


def test_le_coffre_reserve_n_ecrase_jamais_un_coffre_illisible(mv):
    mv.RESERVE_PATH.write_text("{pas du json", encoding="utf-8")
    assert not mv.reserve_set(NOM, "x")
    assert mv.RESERVE_PATH.read_text(encoding="utf-8") == "{pas du json"


# --- 3. ABSENT n'est pas ILLISIBLE ----------------------------------------------

@WIN
def test_une_lecture_du_coffre_reserve_distingue_absent_et_illisible(mv, monkeypatch):
    assert mv.reserve_lire(NOM) == (None, mv.RESERVE_COFFRE_ABSENT)
    assert mv.reserve_set(ORDINAIRE, "v")
    assert mv.reserve_lire(NOM) == (None, mv.RESERVE_CLE_ABSENTE)
    # blob scelle pour un autre compte, ou altere
    store = json.loads(mv.RESERVE_PATH.read_text(encoding="utf-8"))
    store[NOM] = "AAAA"
    mv.RESERVE_PATH.write_text(json.dumps(store), encoding="utf-8")
    assert mv.reserve_lire(NOM) == (None, mv.RESERVE_INDECHIFFRABLE)
    mv.RESERVE_PATH.write_text("[1, 2]", encoding="utf-8")
    assert mv.reserve_lire(NOM) == (None, mv.RESERVE_ILLISIBLE)

    class _AclRefuse:
        parent = mv.RESERVE_PATH.parent
        name = "coffre_reserve.dat"

        def read_text(self, **_k):
            raise PermissionError(13, "Acces refuse")

    monkeypatch.setattr(mv, "RESERVE_PATH", _AclRefuse())
    assert mv.reserve_lire(NOM) == (None, mv.RESERVE_ACCES_REFUSE)
    assert mv.reserve_list() == ([], mv.RESERVE_ACCES_REFUSE)
    assert mv.RESERVE_ETATS_ILLISIBLES == {
        mv.RESERVE_ACCES_REFUSE, mv.RESERVE_ILLISIBLE, mv.RESERVE_INDECHIFFRABLE}


# --- 4. le guichet --------------------------------------------------------------

@WIN
def test_get_secret_lit_le_coffre_reserve_d_abord_pour_un_nom_reserve(mv, fs):
    s, machine = fs
    machine[NOM] = "valeur-machine"
    assert mv.reserve_set(NOM, "valeur-reservee")
    assert s.get_secret(NOM) == "valeur-reservee"
    assert s.observees()[NOM]["source"] == "coffre_reserve"
    dernier = _journal(s)[-1]
    assert (dernier["cle"], dernier["source"], dernier["coffre_reserve"]) == (
        NOM, "coffre_reserve", "TROUVE")


def test_coffre_reserve_refuse_repli_sur_le_coffre_machine_et_le_journal_le_dit(mv, fs, monkeypatch):
    s, machine = fs
    machine[NOM] = "valeur-machine"
    monkeypatch.setattr(mv, "reserve_lire", lambda k: (None, mv.RESERVE_ACCES_REFUSE))
    assert s.get_secret(NOM) == "valeur-machine"
    dernier = _journal(s)[-1]
    # Exactement la lecture que l'etape 2b casserait : elle doit etre lisible au journal.
    assert (dernier["source"], dernier["coffre_reserve"]) == ("coffre", "ACCES_REFUSE")


def test_reserve_illisible_et_rien_ailleurs_vaut_ILLISIBLE_pas_ABSENT(mv, fs, monkeypatch):
    s, _machine = fs
    monkeypatch.setattr(mv, "reserve_lire", lambda k: (None, mv.RESERVE_ACCES_REFUSE))
    assert s.get_secret(NOM) is None
    assert s.observees()[NOM]["issue"] == "ILLISIBLE"
    assert "coffre_reserve" in s.observees()[NOM]["sources_illisibles"]
    assert NOM not in s._cache_miss


def test_un_nom_non_reserve_ne_sonde_jamais_le_coffre_reserve(mv, fs, monkeypatch):
    s, machine = fs
    appels = []
    monkeypatch.setattr(mv, "reserve_lire",
                        lambda k: appels.append(k) or (None, mv.RESERVE_COFFRE_ABSENT))
    machine[ORDINAIRE] = "v"
    assert s.get_secret(ORDINAIRE) == "v"
    assert appels == []


# --- 5. pas deux verites -------------------------------------------------------

@WIN
def test_une_ecriture_au_coffre_machine_ne_laisse_pas_une_copie_reservee_perimee(mv, fs, monkeypatch):
    assert mv.reserve_set(NOM, "ancienne")
    # Sous SYSTEM, la copie reservee suit.
    assert mv.vault_set(NOM, "nouvelle")
    assert mv.reserve_lire(NOM) == ("nouvelle", mv.RESERVE_TROUVE)
    assert mv._vault_get_brut(NOM) == "nouvelle"
    # Un autre compte ne scelle pas : refus, et rien n'est ecrit NULLE PART.
    monkeypatch.setattr(mv, "_sid_courant", lambda: AUTRE_COMPTE)
    assert not mv.vault_set(NOM, "troisieme")
    assert mv.reserve_lire(NOM)[0] == "nouvelle"
    assert mv._vault_get_brut(NOM) == "nouvelle"
    # Coffre reserve illisible pour ce compte : refus pour un nom reserve, libre sinon.
    monkeypatch.setattr(mv, "reserve_list", lambda: ([], mv.RESERVE_ACCES_REFUSE))
    assert not mv.vault_set(NOM, "quatrieme")
    assert mv.vault_set(ORDINAIRE, "libre")


# --- 6. l'outil de provisionnement ----------------------------------------------

def _outil():
    spec = importlib.util.spec_from_file_location(
        "forge_coffre_reserve_provision_nr", ROOT / "tools" / "forge_coffre_reserve_provision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fakes(o, monkeypatch):
    monkeypatch.setattr(o, "_lire_coffre_machine", lambda n: (VALEURS.get(n), "copie"))
    monkeypatch.setattr(o, "_hmac_en_service", lambda: (VALEURS["FORGE_MCP_TOKEN"], "maitre"))
    monkeypatch.setattr(o, "_fernet_en_service", lambda: (FERNET_TEST, "derivee"))
    monkeypatch.setattr(o, "_db_en_service", lambda: (DB_TEST, "derivee"))


def test_l_outil_couvre_exactement_les_noms_reserves(fs):
    s, _ = fs
    o = _outil()
    assert set(o.COPIES) | set(o.DEDIEES) | set(o.NOUVELLES) == set(s.NOMS_RESERVES)


def test_l_outil_refuse_hors_system_et_n_ecrit_rien(mv, fs, monkeypatch, capsys):
    o = _outil()
    _fakes(o, monkeypatch)
    monkeypatch.setattr(mv, "_sid_courant", lambda: AUTRE_COMPTE)
    assert o.main(["--appliquer"]) == 2
    assert not mv.RESERVE_PATH.exists()
    assert SYSTEM in capsys.readouterr().out


@WIN
def test_sans_appliquer_l_outil_n_ecrit_rien(mv, fs, monkeypatch):
    o = _outil()
    _fakes(o, monkeypatch)
    # Sans `--rotation-persona`, la cle persona reste A_GENERER_SUR_GO : NON provisionnee,
    # et l'outil le dit par son code de sortie (2b-1, 2026-09-28).
    assert o.main([]) == 1
    assert o.main(["--rotation-persona"]) == 0
    assert not mv.RESERVE_PATH.exists()


@WIN
def test_l_outil_provisionne_sans_jamais_afficher_une_valeur(mv, fs, monkeypatch, capsys):
    o = _outil()
    _fakes(o, monkeypatch)
    assert o.main(["--appliquer", "--rotation-persona"]) == 0
    sortie = capsys.readouterr().out
    for v in (*VALEURS.values(), FERNET_TEST, DB_TEST):
        assert v not in sortie
    persona, etat = mv.reserve_lire("FORGE_PERSONA_HMAC_KEY")
    assert etat == mv.RESERVE_TROUVE and persona  # nouvelle valeur, generee ici
    assert persona not in sortie
    assert persona not in VALEURS.values()        # jamais une copie
    for nom, v in VALEURS.items():
        assert mv.reserve_lire(nom) == (v, mv.RESERVE_TROUVE)
    # NOKIDO_HMAC_KEY n'est plus au coffre reserve (decision owner 2026-09-28 : cle
    # d'integrite partagee) -- verrou : test_cle_integrite_partagee_nr.py.
    assert mv.reserve_lire("NOKIDO_HMAC_KEY")[1] != mv.RESERVE_TROUVE
    assert mv.reserve_lire("FORGE_ENCRYPT_KEY")[0] == FERNET_TEST
    assert mv.reserve_lire("LAFORGE_DB_KEY")[0] == DB_TEST
    # Idempotent : relance = tout IDENTIQUE ; la cle persona n'est jamais regeneree.
    assert o.main(["--appliquer"]) == 0
    assert o.main(["--appliquer", "--rotation-persona"]) == 0
    assert mv.reserve_lire("FORGE_PERSONA_HMAC_KEY")[0] == persona


@WIN
def test_l_outil_n_ecrase_jamais_une_valeur_differente(mv, fs, monkeypatch, capsys):
    o = _outil()
    _fakes(o, monkeypatch)
    assert mv.reserve_set("LAFORGE_JWT_SECRET", "autre-valeur-deja-scellee")
    assert o.main(["--appliquer"]) == 1
    assert mv.reserve_lire("LAFORGE_JWT_SECRET")[0] == "autre-valeur-deja-scellee"
    assert "DIFFERENTE_NON_ECRASEE" in capsys.readouterr().out


def test_les_cles_dediees_valent_celles_que_les_modules_utilisent(fs, monkeypatch):
    pytest.importorskip("cryptography")
    o = _outil()
    fe = importlib.import_module("nokido_agent.app.forge_encrypt")
    dbc = importlib.import_module("nokido_agent.app.forge_db_conn")
    maitre = VALEURS["FORGE_MCP_TOKEN"]

    def faux(k):
        return maitre if k == "FORGE_MCP_TOKEN" else None

    monkeypatch.delenv("FORGE_ENCRYPT_KEY", raising=False)
    monkeypatch.setattr(fe, "get_secret", faux)
    monkeypatch.setattr(dbc, "get_secret", faux)
    monkeypatch.setattr(o.fs, "get_secret", faux)
    monkeypatch.setattr(fe, "_fernet_instance", None)
    # 2026-09-28 : le MAITRE seul ne fournit plus AUCUNE cle de chiffrement -- ni aux
    # modules, ni a l'outil (test_pas_de_cle_derivee_du_maitre_nr).
    ok = (o._fernet_en_service()[0], o._db_en_service()[0])
    assert ok == (None, None)
    assert o._hmac_en_service()[0] == maitre
    # Avec les cles DEDIEES, l'outil provisionne exactement celles des modules.
    Fernet, _, _ = fe._get_fernet()
    dediee_fernet, dediee_db = Fernet.generate_key().decode("ascii"), "passphrase-db-de-test"

    def faux_dediees(k):
        return {"FORGE_MCP_TOKEN": maitre, "FORGE_ENCRYPT_KEY": dediee_fernet,
                "LAFORGE_DB_KEY": dediee_db}.get(k)

    monkeypatch.setattr(fe, "get_secret", faux_dediees)
    monkeypatch.setattr(dbc, "get_secret", faux_dediees)
    monkeypatch.setattr(fe, "_fernet_instance", None)
    ok = (o._fernet_en_service()[0] == dediee_fernet, o._db_en_service()[0] == dediee_db)
    assert ok == (True, True)
    # La preuve MORD : une instance en service sur une autre cle -> rien n'est provisionne.
    Fernet, _, _ = fe._get_fernet()
    monkeypatch.setattr(fe, "_fernet_instance", Fernet(Fernet.generate_key()))
    valeur, provenance = o._fernet_en_service()
    assert valeur is None and "DIVERGENCE" in provenance
