"""NR — un secret retire du coffre doit CESSER d'etre servi, dans une fenetre BORNEE.

PHASE 5/11 du mandat « organe de secretion securisee » :
« un secret ou une autorisation mise en cache ne doit pas permettre de
contourner indefiniment une revocation. Mesurer la fenetre exacte si une
fenetre existe. »

CARTOGRAPHIE QUI MOTIVE CE MAILLON (mesure du 2026-09-21)
=========================================================
La racine cryptographique reelle n'est pas le TPM : c'est DPAPI avec le flag
`CRYPTPROTECT_LOCAL_MACHINE`. `forge_machine_vault` le dit dans ses propres
commentaires -- « tout compte de CETTE machine sait le dechiffrer ». Aucune
entropie optionnelle n'est passee a `CryptProtectData`, donc rien ne lie un
blob a un appelant particulier.

Le TPM, lui, ne chiffre RIEN aujourd'hui : `_ALG = ECDSA_P256`, `sign` et
`verify` seulement -- aucun `NCryptEncrypt`/`NCryptDecrypt`. Il protege une
SIGNATURE, pas une capacite a dechiffrer.

Dans cet etat, la question « qui peut obtenir le clair » a une reponse mesuree :
tout process de la machine qui appelle le guichet. Et une fois obtenu, le clair
reste dans `_cache` SANS AUCUNE EXPIRATION -- jusqu'a l'arret du process.

    CONSEQUENCE : retirer un secret du coffre ne le retire PAS des process qui
    l'ont deja lu. La fenetre de contournement d'une revocation n'est pas
    longue : elle est INFINIE.

C'est independant du TPM, et c'est corrigeable tout de suite. Une KEK posee
au-dessus d'un cache eternel ne protegerait rien non plus.

CE QUE CE NR VERROUILLE
=======================
1. La fenetre EXISTE et est BORNEE : `_CACHE_TTL_S`.
2. Dans la fenetre, le cache sert encore -- c'est voulu et DIT, sinon chaque
   appel re-sonderait quatre sources (la mesure du depot : ~300 acces DPAPI
   pour une seule resolution de pool).
3. Passee la fenetre, un secret disparu des sources CESSE d'etre servi.
4. `invalidate_cache()` reste IMMEDIAT : une revocation qu'on sait urgente ne
   doit pas attendre l'expiration.
5. La fenetre est OBSERVABLE : on doit pouvoir dire de quand date ce qu'on sert.
   Un etat sans temporalite ne suffit pas (phase 10).

Aucune valeur de secret n'est lue ni affichee : la sentinelle est injectee par
le test et sert a prouver qu'elle cesse d'etre rendue.
"""
import importlib

import pytest

MOD = "nokido_agent.app.forge_secrets"
CLE = "NOKIDO_NR_CLE_REVOCABLE"
VALEUR = "sentinelle-revocation-ne-doit-plus-sortir"


@pytest.fixture()
def secrets(monkeypatch):
    mod = importlib.import_module(MOD)
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()
    monkeypatch.setattr(mod, "_wcm", lambda k: None)
    monkeypatch.setattr(mod, "_dotenv", lambda k: None)
    monkeypatch.delenv(CLE, raising=False)
    yield mod
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()


def test_la_fenetre_existe_et_est_bornee(secrets):
    assert hasattr(secrets, "_CACHE_TTL_S"), (
        "sans TTL, la fenetre de contournement d'une revocation est INFINIE : "
        "elle dure autant que le process"
    )
    assert secrets._CACHE_TTL_S > 0
    assert secrets._CACHE_TTL_S <= 3600, (
        "une fenetre d'une heure ou plus n'est plus une fenetre, c'est un bail"
    )


def test_dans_la_fenetre_le_cache_sert_encore(secrets, monkeypatch):
    """Le cache garde sa raison d'etre : sans lui, chaque appel re-sonde quatre
    sources. Ce test empeche de 'corriger' en supprimant le cache."""
    sondes = {"n": 0}

    def coffre(_k):
        sondes["n"] += 1
        return VALEUR

    monkeypatch.setattr(secrets, "_machine_vault", coffre)
    for _ in range(5):
        assert secrets.get_secret(CLE) == VALEUR
    assert sondes["n"] == 1, (
        "dans la fenetre de fraicheur, le coffre ne doit etre sonde qu'une fois"
    )


def test_passee_la_fenetre_un_secret_retire_cesse_d_etre_servi(secrets, monkeypatch):
    """LE test du mandat : la revocation doit finir par MORDRE."""
    present = {"ok": True}

    def coffre(_k):
        return VALEUR if present["ok"] else None

    monkeypatch.setattr(secrets, "_machine_vault", coffre)
    assert secrets.get_secret(CLE) == VALEUR

    # Le secret est RETIRE du coffre (revocation), et la fenetre est echue.
    present["ok"] = False
    monkeypatch.setattr(secrets, "_CACHE_TTL_S", 0.0)

    assert secrets.get_secret(CLE) is None, (
        "un secret retire du coffre continue d'etre servi : la revocation ne "
        "produit aucun EFFET sur les process deja chauds"
    )


def test_la_revocation_urgente_n_attend_pas_l_expiration(secrets, monkeypatch):
    """`invalidate_cache` reste immediat : on ne doit pas dependre du TTL quand
    on SAIT qu'il faut couper."""
    present = {"ok": True}
    monkeypatch.setattr(secrets, "_machine_vault",
                        lambda k: VALEUR if present["ok"] else None)
    assert secrets.get_secret(CLE) == VALEUR
    present["ok"] = False
    secrets.invalidate_cache(CLE)
    assert secrets.get_secret(CLE) is None


def test_la_fraicheur_de_ce_qu_on_sert_est_observable(secrets, monkeypatch):
    """Phase 10 : un etat sans temporalite ne suffit pas. On doit pouvoir dire
    de QUAND date la valeur servie -- sans jamais exposer la valeur."""
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: VALEUR)
    secrets.get_secret(CLE)
    obs = secrets.observees()[CLE]
    assert "age_cache_s" in obs, (
        "l'observation doit dire l'AGE de ce qui est servi, sinon on ne peut "
        "pas juger si une revocation a eu le temps de mordre"
    )
    assert obs["age_cache_s"] is not None
    assert obs["age_cache_s"] >= 0
    import json
    assert VALEUR not in json.dumps(secrets.observees(), default=str)


def test_une_bascule_de_politique_ne_depend_pas_du_ttl(secrets, monkeypatch):
    """Les bascules ne sont pas cachees du tout : leur fenetre est NULLE, pas
    bornee. Ce test evite qu'on les fasse retomber dans le cache en ajoutant
    le TTL."""
    monkeypatch.setattr(secrets, "_BASCULES_DE_POLITIQUE", frozenset({CLE}))
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: None)
    monkeypatch.setenv(CLE, VALEUR)
    assert secrets.get_secret(CLE) == VALEUR
    monkeypatch.delenv(CLE, raising=False)
    assert secrets.get_secret(CLE) is None, (
        "une bascule doit se relever IMMEDIATEMENT, sans attendre un TTL"
    )
