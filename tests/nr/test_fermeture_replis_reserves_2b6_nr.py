"""NR -- etape 2b-6, lot 1, du correctif du coffre (go owner 2026-09-28) : FERMETURE des replis.

Mesure du 2026-09-28 (journal des lectures reservees, fenetre ~7 h, lecteurs relus un par
un). Un nom se FERME quand deux conditions tiennent : aucun lecteur legitime hors SYSTEM,
ET son lecteur SYSTEM le trouve au coffre reserve. Lot 1 : 5 des 12 noms reserves. Lot 2
(meme jour, apres `--appliquer` sous SYSTEM et relecture `coffre_reserve` des deux noms) :
HUB_JWT_SECRET et firewall_log_hmac. Restent en TRANSITION : 5 noms a lecteur reel hors
SYSTEM sans voie propre a ce jour (portail et pont stdio sous le compte owner, mode dev,
demon du pont privilegie). Cet ensemble ne fait que DECROITRE.

Contrats :
  1. `RESERVES_EN_TRANSITION` est inclus dans les noms reserves et dans les 5 noms mesures
     (cliquet : on n'y ajoute jamais un nom) ;
  2. un nom reserve FERME ne se lit plus au coffre machine ni dans Nokido.env (tous deux
     lisibles par les comptes bac a sable) -- ces sources ne sont meme pas sondees -- et
     l'issue vaut FERME : ni ABSENT, ni ILLISIBLE ;
  3. sous SYSTEM (coffre reserve) et dans le magasin PERSONNEL (WCM, illisible par un
     autre compte) il reste servi : les modes dev de l'owner ne cassent pas ;
  4. un nom en transition et un nom ordinaire gardent leur comportement ;
  5. le pare-feu ne reecrit plus sa cle au coffre machine quand le guichet la tait ;
  6. le reindex deporte n'injecte plus aucun nom reserve dans l'environnement ;
  7. le reconcile superviseur ne prend jamais le maitre pour jeton superviseur, ne lit
     plus le coffre machine en direct, et ne lit rien a l'import.

Aucune vraie valeur n'est lue : toutes les sources sont substituees, et chaque
comparaison est reduite a un booleen avant l'assert.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MV = "nokido_agent.app.forge_machine_vault"
FS = "nokido_agent.app.forge_secrets"
MESURES_EN_TRANSITION = frozenset({
    "FORGE_MCP_TOKEN", "LAFORGE_ADMIN_TOKEN", "LAFORGE_JWT_SECRET",
    "MCP_DEV_SECRET", "LAFORGE_PRIV_BRIDGE_HMAC",
    # REMONTEE JUSTIFIEE du cliquet (2026-09-28) : lecteur LEGITIME mesure apres coup -- le
    # lanceur du bureau de l'owner relance le hub avec ce jeton ; ferme, il a pris 401.
    "LAFORGE_SUPERVISOR_TOKEN",
    # FORGE_ENCRYPT_KEY / LAFORGE_DB_KEY : remontes puis REFERMES le meme jour, apres retrait
    # du repli sur une cle derivee du maitre (test_pas_de_cle_derivee_du_maitre_nr).
    # LAFORGE_VC_KEYFILE_B64 : ne en transition puis FERME le meme jour (voies propres :
    # coffre reserve + magasin personnel de l'owner) -- test_fichier_cle_veracrypt_reserve_nr.
})
ORDINAIRE = "NOKIDO_NR_2B6_NOM_ORDINAIRE"
VALEUR = "valeur-de-test-2b6"
ILLISIBLE = object()


def _fermes_mesures() -> list:
    return sorted(importlib.import_module(FS).NOMS_RESERVES - MESURES_EN_TRANSITION)


def _en_transition(s) -> frozenset:
    return getattr(s, "RESERVES_EN_TRANSITION", MESURES_EN_TRANSITION)


@pytest.fixture
def fs(tmp_path, monkeypatch):
    s = importlib.import_module(FS)
    monkeypatch.setattr(s, "_JOURNAL_RESERVES", tmp_path / "journal.jsonl")
    s._vider_observations()
    s.invalidate_cache()
    sources = {"coffre_reserve": {}, "coffre": {}, "wcm": {}, "dotenv": {}}
    sondes: list = []

    def _faux(nom):
        def lire(k):
            sondes.append((nom, k))
            v = sources[nom].get(k)
            if v is ILLISIBLE:
                raise PermissionError("acces refuse (substitut de test)")
            return v
        return lire

    monkeypatch.setattr(s, "_coffre_reserve", _faux("coffre_reserve"))
    monkeypatch.setattr(s, "_machine_vault", _faux("coffre"))
    monkeypatch.setattr(s, "_wcm", _faux("wcm"))
    monkeypatch.setattr(s, "_dotenv", _faux("dotenv"))
    for k in (*s.NOMS_RESERVES, ORDINAIRE):
        monkeypatch.delenv(k, raising=False)
    yield s, sources, sondes
    s._vider_observations()
    s.invalidate_cache()


def test_la_transition_est_un_cliquet_qui_ne_fait_que_decroitre():
    s = importlib.import_module(FS)
    transition = s.RESERVES_EN_TRANSITION
    ok = (transition <= s.NOMS_RESERVES, transition <= MESURES_EN_TRANSITION)
    assert ok == (True, True)
    assert len(s.NOMS_RESERVES - transition) >= 7


@pytest.mark.parametrize("nom", _fermes_mesures())
def test_un_nom_ferme_ne_se_lit_ni_au_coffre_machine_ni_dans_le_dotenv(fs, nom):
    s, sources, sondes = fs
    sources["coffre_reserve"][nom] = ILLISIBLE      # compte bac a sable
    sources["coffre"][nom] = VALEUR
    sources["dotenv"][nom] = VALEUR
    rien = s.get_secret(nom) is None
    assert rien
    touchees = {src for src, k in sondes if k == nom}
    assert not ({"coffre", "dotenv"} & touchees)
    assert s.observees()[nom]["issue"] == "FERME"
    assert nom not in s._cache_miss


def test_un_nom_ferme_reste_servi_sous_system_et_dans_le_magasin_personnel(fs):
    s, sources, _sondes = fs
    a, b = _fermes_mesures()[:2]
    sources["coffre_reserve"][a] = VALEUR            # SYSTEM
    sources["coffre_reserve"][b] = ILLISIBLE         # owner : reserve illisible...
    sources["wcm"][b] = VALEUR                       # ... mais son magasin personnel
    ok = (s.get_secret(a) == VALEUR, s.get_secret(b) == VALEUR)
    assert ok == (True, True)


def test_un_nom_ferme_requis_leve_en_disant_ferme_sans_valeur(fs):
    s, sources, _sondes = fs
    nom = _fermes_mesures()[0]
    sources["coffre_reserve"][nom] = ILLISIBLE
    sources["coffre"][nom] = VALEUR
    with pytest.raises(ValueError) as e:
        s.get_secret(nom, required=True)
    msg = str(e.value)
    ok = ("FERME" in msg, VALEUR in msg)
    assert ok == (True, False)


@pytest.mark.parametrize("nom", sorted(MESURES_EN_TRANSITION))
def test_un_nom_en_transition_reste_servi_par_le_coffre_machine(fs, nom):
    s, sources, _sondes = fs
    if nom not in _en_transition(s):
        pytest.skip("ferme depuis : le cliquet a avance")
    sources["coffre_reserve"][nom] = ILLISIBLE
    sources["coffre"][nom] = VALEUR
    ok = s.get_secret(nom) == VALEUR
    assert ok
    assert s.observees()[nom]["source"] == "coffre"


def test_un_nom_ordinaire_garde_tout_son_ordre(fs):
    s, sources, sondes = fs
    sources["dotenv"][ORDINAIRE] = VALEUR
    ok = s.get_secret(ORDINAIRE) == VALEUR
    assert ok
    assert ("coffre_reserve", ORDINAIRE) not in sondes


def test_le_pare_feu_ne_reecrit_plus_sa_cle_au_coffre_machine(monkeypatch):
    fw = importlib.import_module("nokido_agent.app.forge_semantic_firewall")
    s = importlib.import_module(FS)
    m = importlib.import_module(MV)
    ecrits: list = []
    monkeypatch.setattr(m, "vault_set", lambda k, v: ecrits.append(k) or True)
    monkeypatch.setattr(s, "get_secret", lambda k, required=False: None)
    monkeypatch.setattr(fw, "_LOG_HMAC_KEY", None)
    cle = fw._log_hmac_key()
    ok = (isinstance(cle, bytes), len(cle) == 32)
    assert ok == (True, True)
    assert ecrits == []


def _charger(rel: str, nom: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_reindex_n_injecte_aucun_nom_reserve_dans_l_environnement(monkeypatch):
    s = importlib.import_module(FS)
    m = importlib.import_module(MV)
    ec = importlib.import_module("nokido_agent.app.forge_env_crypt")
    rd = _charger("tools/forge_reindex_deport.py", "nr_2b6_reindex")
    reserve = sorted(s.NOMS_RESERVES)[0]
    for k in (reserve, ORDINAIRE):
        monkeypatch.setenv(k, "x")        # enregistre l'etat d'origine pour le retour
        monkeypatch.delenv(k)
    monkeypatch.setattr(m, "vault_list", lambda: [reserve, ORDINAIRE])
    monkeypatch.setattr(m, "vault_get", lambda k: VALEUR)
    monkeypatch.setattr(ec, "inject_into_environ", lambda *a, **k: None)
    monkeypatch.setattr(ec, "load_secrets", lambda *a, **k: {})
    monkeypatch.setattr(rd, "log", lambda *a, **k: None)
    noms = rd._load_vault()
    ok = (os.environ.get(ORDINAIRE) == VALEUR, reserve in os.environ, reserve in noms)
    assert ok == (True, False, False)


def test_le_reconcile_ne_prend_jamais_le_maitre_ni_le_coffre_en_direct(monkeypatch):
    s = importlib.import_module(FS)
    m = importlib.import_module(MV)
    direct: list = []
    lus: list = []
    monkeypatch.setattr(m, "vault_get", lambda k: direct.append(k) or VALEUR)
    monkeypatch.setattr(s, "get_secret", lambda k, required=False: lus.append(k) or None)
    monkeypatch.setenv("FORGE_MCP_TOKEN", "maitre-de-test-2b6")
    monkeypatch.delenv("LAFORGE_SUPERVISOR_TOKEN", raising=False)
    rc = _charger("tools/forge_supervisor_reconcile.py", "nr_2b6_reconcile")
    a_l_import = len(lus) + len(direct)
    jeton = rc._token()
    ok = (a_l_import == 0, jeton == "", direct == [], lus == ["LAFORGE_SUPERVISOR_TOKEN"])
    assert ok == (True, True, True, True)
