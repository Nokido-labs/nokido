"""NR — une cle revoquee par le rotateur ne doit plus etre servie par le guichet.

PHASE 7 du mandat, niveau C (secret revoque), et invariant n.9 :
« possibilite de distinguer ABSENT / ILLISIBLE / REFUSE / REVOQUE / EXPIRE ».

SEARCH BEFORE BUILD -- et il change tout
========================================
La revocation d'un SECRET n'est pas a construire : elle EXISTE.

    forge_key_rotation.mark(env_base, key, status, reason)   status: ok|bad|quota
    persistee dans sandbox/key_health.json, indexee par EMPREINTE de la valeur
    _usable(entry) ecarte deja les entrees non saines du pool

Et ce ledger est VIVANT. Mesure du 2026-09-21, 6 entrees, dont :

    TOGETHER_API_KEY   status=bad   reason=http401

DEFAUT MESURE
=============
`forge_secrets` ne mentionne NI key_rotation, NI quarantine, NI healthy_key.
Le guichet ignore donc totalement cette quarantaine : une cle que le rotateur
sait morte continue d'etre distribuee a ses 159 appelants. Deux organes, deux
verites -- et c'est le guichet, celui que tout le corps traverse, qui porte la
fausse.

Le remede est un RACCORD entre deux organes existants, pas un troisieme organe.

DEUX ASYMETRIES ASSUMEES, et elles sont le coeur du contrat
==========================================================
1. `bad` REVOQUE, `quota` NON. Un http401 dit que le credential n'est plus
   valide ; un 429 dit que le fournisseur limite le debit. Les confondre, c'est
   soit jeter une cle saine, soit servir une cle morte. `quota` est un etat
   TEMPORAIRE du fournisseur, pas une propriete du credential.
2. Une sante ILLISIBLE ne REVOQUE PAS. Ici le fail-closed serait catastrophique :
   un `key_health.json` corrompu eteindrait tout le corps d'un coup. L'absence
   d'information de sante n'est pas une preuve de revocation -- ILLISIBLE n'est
   pas NON. Le fail-closed reste la regle pour l'AUTORISATION (breakglass) ;
   il ne s'applique pas a un signal de SANTE. L'asymetrie est voulue, et dite.

Aucune valeur n'est lue ni affichee : la quarantaine se consulte par EMPREINTE.
"""
import importlib

import pytest

MOD = "nokido_agent.app.forge_secrets"
CLE = "NOKIDO_NR_CLE_QUARANTAINE"
VALEUR = "sentinelle-quarantaine-ne-doit-pas-sortir"


@pytest.fixture()
def secrets(monkeypatch):
    mod = importlib.import_module(MOD)
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()
    monkeypatch.setattr(mod, "_machine_vault", lambda k: VALEUR)
    monkeypatch.setattr(mod, "_wcm", lambda k: None)
    monkeypatch.setattr(mod, "_dotenv", lambda k: None)
    yield mod
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()


def _sante(mod, statut):
    """Force l'etat de sante vu par le guichet, sans toucher au ledger reel."""
    return lambda _valeur: statut


def test_une_cle_marquee_bad_nest_plus_servie(secrets, monkeypatch):
    """Le coeur : le guichet doit respecter la quarantaine du rotateur."""
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, "bad"))
    assert secrets.get_secret(CLE) is None, (
        "une cle que le rotateur sait morte (http401) continue d'etre "
        "distribuee : le guichet porte une verite que le rotateur a dementie"
    )


def test_revoque_nest_pas_absent(secrets, monkeypatch):
    """Invariant n.9 : cinq etats distincts, pas deux.

    Confondre un retrait et ABSENT enverrait quelqu'un re-provisionner une cle
    qui est la et qu'on a volontairement ecartee.

    Depuis le 2026-09-21 le guichet dit aussi la DUREE du retrait : `bad` est
    une QUARANTAINE que `forge_key_rotation._usable` leve seule apres 6 h,
    `revoked` est une decision qui ne se re-arme pas. Ce test couvre les deux —
    ce que le nom de ce fichier annoncait deja.
    """
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, "bad"))
    secrets.get_secret(CLE)
    assert secrets.observees()[CLE]["issue"] == "QUARANTAINE"

    secrets.invalidate_cache(CLE)
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, "revoked"))
    secrets.get_secret(CLE)
    assert secrets.observees()[CLE]["issue"] == "REVOQUE"


def test_un_quota_nest_PAS_une_revocation(secrets, monkeypatch):
    """Un 429 limite un debit ; il ne dit rien sur la validite du credential."""
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, "quota"))
    assert secrets.get_secret(CLE) == VALEUR
    obs = secrets.observees()[CLE]
    assert obs["issue"] == "TROUVE"
    assert obs.get("sante_cle") == "quota", (
        "l'etat du fournisseur doit rester VISIBLE meme quand il n'empeche pas "
        "la delivrance"
    )


def test_une_sante_illisible_ne_revoque_pas(secrets, monkeypatch):
    """Asymetrie assumee : fail-closed pour l'autorisation, PAS pour la sante.

    Un key_health.json corrompu eteindrait tout le corps. ILLISIBLE n'est pas
    NON -- et ici le cout des deux erreurs est spectaculairement dissymetrique.
    """
    def illisible(_valeur):
        raise OSError("key_health illisible (simule)")

    monkeypatch.setattr(secrets, "_sante_de_la_valeur", illisible)
    assert secrets.get_secret(CLE) == VALEUR
    assert secrets.observees()[CLE].get("sante_cle") == "ILLISIBLE"


def test_une_cle_saine_est_servie_normalement(secrets, monkeypatch):
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, "ok"))
    assert secrets.get_secret(CLE) == VALEUR
    assert secrets.observees()[CLE]["issue"] == "TROUVE"


def test_une_cle_inconnue_du_ledger_est_servie(secrets, monkeypatch):
    """La quarantaine ne connait que ce qu'on lui a signale. Une cle jamais
    marquee n'est pas suspecte : absente du ledger != revoquee."""
    monkeypatch.setattr(secrets, "_sante_de_la_valeur", _sante(secrets, None))
    assert secrets.get_secret(CLE) == VALEUR


def test_la_quarantaine_se_consulte_par_empreinte_jamais_par_valeur(secrets):
    """Le ledger indexe par empreinte ; le guichet ne doit pas le contourner en
    stockant ou en journalisant la valeur."""
    import json

    assert hasattr(secrets, "_sante_de_la_valeur")
    secrets.get_secret(CLE)
    assert VALEUR not in json.dumps(secrets.observees(), default=str)


def test_le_raccord_passe_par_le_rotateur_existant(secrets):
    """Anti-troisieme-organe : la sante doit venir de forge_key_rotation, pas
    d'un second ledger qui divergerait du premier."""
    import inspect

    src = inspect.getsource(secrets._sante_de_la_valeur)
    assert "key_rotation" in src or "_load_health" in src, (
        "le guichet doit lire LE ledger du rotateur, pas s'en fabriquer un"
    )
