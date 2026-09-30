"""NR — etape 0 du correctif du coffre : RECENSER qui lit un secret reserve, sans rien refuser.

Mesure du 2026-09-28 (owner) : sous le compte bac a sable `LaForgeSbxOffline`,
`get_secret` rendait, source `coffre`, les porteurs de ring <= 1 et le secret de
signature JWT. Le coffre machine est lisible par tout compte local PAR CONCEPTION.
Ces noms en sortiront (etape 2) ; avant, il faut savoir QUI les lit, sinon le
scellement casse des lecteurs qu'on n'a pas vus.

Ce que ce NR verrouille :
  - la liste fermee des noms reserves (les quatre mesures, pas le jeton de ring 4) ;
  - une lecture reservee laisse UNE ligne : cle, issue, source, module, compte ;
  - la valeur n'entre JAMAIS dans le journal ;
  - le compte vient du JETON du process, pas de `USERNAME` (heritable) ;
  - une lecture directe de `vault_get` est recensee ; la meme lecture passee par
    `get_secret` ne l'est pas deux fois (chemin reel, aucune source simulee au
    milieu) ;
  - un journal impossible n'empeche jamais la lecture, et son echec se VOIT.
Rien n'est refuse : un garde neuf observe avant d'enforcer.
"""
import importlib
import json
import os
import sys

import pytest

MOD = "nokido_agent.app.forge_secrets"
MV = "nokido_agent.app.forge_machine_vault"
CLE = "NOKIDO_NR_CLE_RESERVEE"
VALEUR = "sentinelle-reservee-ne-doit-jamais-etre-journalisee"


@pytest.fixture()
def base(monkeypatch, tmp_path):
    """Guichet isole : journal en tmp, liste reservee = la cle du NR, WCM et .env muets."""
    mod = importlib.import_module(MOD)
    mod.invalidate_cache()
    mod._vider_observations()
    monkeypatch.setattr(mod, "_wcm", lambda k: None)
    monkeypatch.setattr(mod, "_dotenv", lambda k: None)
    monkeypatch.setattr(mod, "NOMS_RESERVES", frozenset({CLE}))
    # Etape 2b-6 : un nom reserve FERME ne se lit plus au coffre machine. Le recensement
    # porte sur les lectures encore SERVIES -- celles des noms en transition.
    monkeypatch.setattr(mod, "RESERVES_EN_TRANSITION", frozenset({CLE}))
    monkeypatch.setattr(mod, "_JOURNAL_RESERVES", tmp_path / "lectures.jsonl")
    monkeypatch.setitem(mod._JOURNAL_ECHECS, "n", 0)
    monkeypatch.setitem(mod._JOURNAL_ECHECS, "derniere", None)
    yield mod
    mod.invalidate_cache()
    mod._vider_observations()


@pytest.fixture()
def secrets(base, monkeypatch):
    monkeypatch.setattr(base, "_machine_vault", lambda k: VALEUR)
    return base


def _lignes(mod):
    p = mod._JOURNAL_RESERVES
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_un_recensement_direct_impossible_se_compte_et_ne_casse_pas_la_lecture(monkeypatch):
    """`forge_secrets` inimportable dans un process : ses lectures directes ne sont pas
    recensees (limite dite) -- mais l'impossibilite se COMPTE, sans la valeur, et
    `vault_get` rend toujours ce qu'il lit. Un `except: pass` la rendait invisible."""
    mv = importlib.import_module(MV)
    monkeypatch.setattr(mv, "_vault_get_brut", lambda k: VALEUR)
    monkeypatch.setitem(mv._RECENSEMENT_INDISPONIBLE, "n", 0)
    monkeypatch.setitem(mv._RECENSEMENT_INDISPONIBLE, "derniere", None)
    monkeypatch.setitem(sys.modules, MOD, None)  # import -> ModuleNotFoundError
    assert mv.vault_get(CLE) == VALEUR
    assert mv._RECENSEMENT_INDISPONIBLE["n"] == 1
    assert "ModuleNotFoundError" in mv._RECENSEMENT_INDISPONIBLE["derniere"]
    assert VALEUR not in mv._RECENSEMENT_INDISPONIBLE["derniere"]


def test_les_quatre_noms_mesures_sont_reserves_et_pas_le_ring_4():
    mod = importlib.import_module(MOD)
    for nom in ("FORGE_MCP_TOKEN", "LAFORGE_SUPERVISOR_TOKEN",
                "LAFORGE_JWT_SECRET", "LAFORGE_ADMIN_TOKEN"):
        assert nom in mod.NOMS_RESERVES, "%s mesure lisible par le bac a sable" % nom
    # Ring 4 : lisible par les comptes bac a sable PAR CONCEPTION.
    assert "FORGE_TOKEN_SERVICES" not in mod.NOMS_RESERVES


def test_une_lecture_reservee_est_recensee_avec_son_lecteur(secrets):
    assert secrets.get_secret(CLE) == VALEUR, "l'etape 0 observe, elle ne refuse rien"
    lignes = _lignes(secrets)
    assert len(lignes) == 1, lignes
    l = lignes[0]
    assert (l["cle"], l["issue"], l["source"]) == (CLE, "TROUVE", "coffre")
    assert l["module"] == os.path.basename(__file__)
    assert l["compte"] and l["compte"] != "ILLISIBLE"
    assert l["pid"] == os.getpid()
    assert l["aussi_dans_environ"] is False


def test_la_valeur_n_entre_jamais_dans_le_journal(secrets):
    secrets.get_secret(CLE)
    assert VALEUR not in secrets._JOURNAL_RESERVES.read_text(encoding="utf-8")


def test_une_seule_ligne_par_lecteur_et_par_source(secrets):
    for _ in range(5):
        secrets.get_secret(CLE)
    assert len(_lignes(secrets)) == 1


def test_un_nom_ordinaire_n_est_pas_recense(secrets):
    secrets.get_secret("NOKIDO_NR_CLE_ORDINAIRE")
    assert _lignes(secrets) == []


def test_un_journal_impossible_ne_casse_pas_la_lecture_et_se_voit(secrets, monkeypatch, tmp_path):
    dossier = tmp_path / "un_dossier_pas_un_fichier"
    dossier.mkdir()
    monkeypatch.setattr(secrets, "_JOURNAL_RESERVES", dossier)
    assert secrets.get_secret(CLE) == VALEUR
    etat = secrets.etat_journal_reserves()
    assert etat["echecs"] == 1 and etat["derniere_erreur"], etat


@pytest.mark.skipif(sys.platform != "win32", reason="compte du jeton : API Windows")
def test_le_compte_vient_du_jeton_pas_de_l_environnement(secrets, monkeypatch):
    monkeypatch.setenv("USERNAME", "COMPTE_MENTEUR_NR")
    secrets.get_secret(CLE)
    assert _lignes(secrets)[0]["compte"] != "COMPTE_MENTEUR_NR"


def test_un_lecteur_direct_du_coffre_est_recense(base, monkeypatch):
    mv = importlib.import_module(MV)
    monkeypatch.setattr(mv, "_vault_get_brut", lambda k: VALEUR)
    assert mv.vault_get(CLE) == VALEUR
    lignes = _lignes(base)
    assert len(lignes) == 1, lignes
    assert lignes[0]["source"] == "coffre_direct"
    assert lignes[0]["module"] == os.path.basename(__file__)
    assert VALEUR not in base._JOURNAL_RESERVES.read_text(encoding="utf-8")


def test_une_lecture_par_get_secret_n_est_pas_comptee_deux_fois(base, monkeypatch):
    """Chemin reel : get_secret -> _machine_vault -> vault_get, seul le dechiffrement est simule."""
    mv = importlib.import_module(MV)
    monkeypatch.setattr(mv, "_vault_get_brut", lambda k: VALEUR)
    assert base.get_secret(CLE) == VALEUR
    lignes = _lignes(base)
    assert [l["source"] for l in lignes] == ["coffre"], lignes
