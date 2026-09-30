"""NR — le guichet des secrets doit distinguer ABSENT de ILLISIBLE, et se SAVOIR consulte.

PHASE 1 du mandat « organe de secretion securisee » (owner, 2026-09-20).

MESURE QUI MOTIVE CE NR, faite avant d'ecrire une ligne :

  * `_machine_vault`, `_wcm` et `_dotenv` rendent TOUS `None` dans `except
    Exception`. Un coffre inaccessible et un secret absent sont donc
    INDISTINGUABLES. C'est la premiere ligne de la constitution semantique :
    « UNKNOWN != NO ... un capteur rendant False pour "pas la" ET pour "acces
    refuse" ». L'audit du 2026-09-20 a classe 31 cles « NULLE PART » avec cet
    instrument : le chiffre ne pouvait pas etre meilleur que la sonde.

  * `_cache_miss` est un puits sans fond : une cle introuvable UNE fois est
    refusee pour toute la vie du process. Un coffre momentanement illisible, une
    rotation, un service qui demarre avant le vault -> l'absence devient
    definitive alors que la cause etait transitoire. `STALE != DEAD`.

  * `diagnostic()` connait 26 cles CODEES EN DUR quand le code en demande 74 sur
    219 sites : 72 % du coffre est invisible a son propre audit. Et il n'est
    appele par PERSONNE (le seul « appelant » est un commentaire dans
    forge_provider_admin.py:40). Le corriger sans le brancher serait corriger un
    jumeau mort -- faute payee deux fois le 2026-09-20.

CE QUE CE NR VERROUILLE, et rien de plus : le guichet doit pouvoir DIRE ce qu'on
lui a demande et ce qu'il n'a pas pu lire. Il ne verrouille aucune politique de
stockage, aucune KEK, aucun chiffrement : ce sont les phases suivantes.

REGLE ABSOLUE TENUE ICI AUSSI : aucun test n'affiche ni ne compare une valeur de
secret reelle. La sentinelle ci-dessous est une chaine de test, injectee par le
test lui-meme, et sert precisement a prouver qu'elle NE SORT PAS.
"""
import json
import time

import pytest

MOD = "nokido_agent.app.forge_secrets"

SENTINELLE = "sentinelle-de-test-qui-ne-doit-jamais-sortir-42"
CLE_TEST = "NOKIDO_NR_CLE_D_OBSERVATION"

ETATS_AUTORISES = {"TROUVE", "ABSENT", "ILLISIBLE", "NON_OBSERVEE"}


@pytest.fixture()
def secrets(monkeypatch):
    """Le module resolu par son nom canonique, caches vides.

    Deux noms d'import = deux instances = deux etats (lecon du 2026-09-10) :
    on resout une fois et on patche CET objet, jamais une seconde forme.
    """
    import importlib

    mod = importlib.import_module(MOD)
    mod.invalidate_cache()
    # Aucune source reelle n'est consultee par ce NR.
    monkeypatch.setattr(mod, "_wcm", lambda k: None)
    monkeypatch.setattr(mod, "_dotenv", lambda k: None)
    monkeypatch.setattr(mod, "_machine_vault", lambda k: None)
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()
    yield mod
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()


# ---------------------------------------------------------------- ILLISIBLE

def test_une_source_qui_leve_ne_se_lit_pas_comme_absente(secrets, monkeypatch):
    """Le coeur du NR. Une sonde qui ECHOUE n'autorise pas a conclure ABSENT."""

    def coffre_en_panne(_k):
        raise OSError("coffre injoignable (simule)")

    monkeypatch.setattr(secrets, "_machine_vault", coffre_en_panne)

    assert secrets.get_secret(CLE_TEST) is None, (
        "sans valeur lisible, get_secret rend bien None -- c'est l'ETAT qui doit "
        "porter la nuance, pas la valeur de retour"
    )

    obs = secrets.observees()
    assert CLE_TEST in obs, "une cle demandee doit laisser une trace d'observation"
    assert obs[CLE_TEST]["issue"] == "ILLISIBLE", (
        "une source qui leve rend ILLISIBLE, JAMAIS ABSENT -- sinon le capteur "
        "fabrique des faux negatifs indetectables"
    )
    assert obs[CLE_TEST]["sources_illisibles"], (
        "l'observation doit NOMMER ce qu'elle n'a pas pu lire"
    )


def test_un_illisible_nest_jamais_fige_en_cache_miss(secrets, monkeypatch):
    """Une panne transitoire ne doit pas condamner la cle pour la vie du process."""
    appels = {"n": 0}

    def coffre_intermittent(_k):
        appels["n"] += 1
        if appels["n"] == 1:
            raise OSError("panne transitoire (simule)")
        return SENTINELLE

    monkeypatch.setattr(secrets, "_machine_vault", coffre_intermittent)

    assert secrets.get_secret(CLE_TEST) is None          # 1er appel : la panne
    assert CLE_TEST not in secrets._cache_miss, (
        "mettre un ILLISIBLE en cache_miss transforme une panne de 3 secondes en "
        "absence definitive : STALE != DEAD"
    )
    assert secrets.get_secret(CLE_TEST) == SENTINELLE, (
        "la source guerie doit etre revue -- c'est tout l'interet de ne pas figer"
    )


def test_une_absence_reelle_reste_une_absence(secrets):
    """Symetrie : ne pas remplacer une sur-deduction par une autre.

    Si AUCUNE source ne leve et qu'aucune ne repond, la cle est bien ABSENTE.
    Rendre ILLISIBLE partout fabriquerait des pannes fictives.
    """
    assert secrets.get_secret(CLE_TEST) is None
    obs = secrets.observees()
    assert obs[CLE_TEST]["issue"] == "ABSENT"
    assert not obs[CLE_TEST]["sources_illisibles"]


# ------------------------------------------------------------- OBSERVATION

def test_le_registre_dobservation_ne_contient_jamais_la_valeur(secrets, monkeypatch):
    """La regle absolue du mandat, rendue executable."""
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: SENTINELLE)
    secrets.get_secret(CLE_TEST)

    serialise = json.dumps(secrets.observees(), default=str)
    assert SENTINELLE not in serialise, (
        "le registre d'observation porte des NOMS, des ETATS et des COMPTEURS. "
        "Jamais une valeur."
    )
    obs = secrets.observees()[CLE_TEST]
    assert obs["issue"] == "TROUVE"
    assert obs["source"] == "coffre"
    assert obs["appels"] >= 1
    assert obs["dernier_ts"] >= obs["premier_ts"]


def test_le_registre_compte_les_appels_sans_les_dupliquer(secrets, monkeypatch):
    """Un DEBIT se mesure par comptage, pas par presence."""
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: SENTINELLE)
    avant = time.time()
    for _ in range(3):
        secrets.get_secret(CLE_TEST)
    obs = secrets.observees()[CLE_TEST]
    assert obs["appels"] == 3, (
        "le cache memoire ne doit pas rendre les consommateurs invisibles : "
        "c'est le nombre de DEMANDES qui interesse l'audit, pas le nombre de "
        "lectures effectives du coffre"
    )
    assert obs["premier_ts"] >= avant


# -------------------------------------------------------------- DIAGNOSTIC

def test_diagnostic_voit_les_cles_observees_hors_de_sa_liste(secrets, monkeypatch):
    """L'angle mort de 72 % : une cle demandee doit devenir visible a l'audit."""
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: SENTINELLE)
    secrets.get_secret(CLE_TEST)

    d = secrets.diagnostic()
    cles = d["cles"]
    assert CLE_TEST in cles, (
        "une cle que le corps demande REELLEMENT ne peut pas rester invisible a "
        "l'audit du coffre -- c'est le defaut mesure : 26 connues / 74 demandees"
    )
    assert cles[CLE_TEST]["origine"] == "observee"
    assert cles[CLE_TEST]["etat"] in ETATS_AUTORISES


def test_diagnostic_porte_un_etat_et_jamais_un_booleen(secrets):
    """Trois etats et jamais deux : vrai, faux, ILLISIBLE."""
    d = secrets.diagnostic()
    assert set(d["cles"]), "le diagnostic ne peut pas etre vide"
    for nom, fiche in d["cles"].items():
        assert fiche["etat"] in ETATS_AUTORISES, (
            "%s porte %r : un audit qui range UNKNOWN du cote sain classe par "
            "liste NOIRE" % (nom, fiche.get("etat"))
        )
        assert "origine" in fiche, "%s ne dit pas d'ou vient son nom" % nom


def test_diagnostic_dit_ce_quil_na_pas_pu_regarder(secrets):
    """Ce que l'audit ne lit pas, il le DIT."""
    d = secrets.diagnostic()
    assert "non_observe" in d, (
        "un diagnostic honnete nomme sa propre portee : les cles declarees mais "
        "jamais demandees dans CE process ne sont pas 'saines', elles sont "
        "NON_OBSERVEES"
    )
    assert "illisibles" in d


def test_diagnostic_ne_fuit_aucune_valeur(secrets, monkeypatch):
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: SENTINELLE)
    secrets.get_secret(CLE_TEST)
    assert SENTINELLE not in json.dumps(secrets.diagnostic(), default=str)


# ------------------------------------------- UNE ABSENCE N'EST PAS ETERNELLE

def test_une_bascule_posee_apres_coup_est_vue(secrets, monkeypatch):
    """Defaut de SECURITE mesure le 2026-09-20, pas une subtilite de cache.

    `forge_secret_guard.is_breakglass_active()` lit LAFORGE_ALLOW_SECRETS_READ
    par `get_secret`. Si le process a consulte la cle UNE fois avant qu'elle
    soit posee, `_cache_miss` la refuse pour toujours : l'operateur suit le
    message d'erreur (« lancer Nokido avec LAFORGE_ALLOW_SECRETS_READ=1 »),
    pose la variable, et RIEN ne change. Le breakglass ne fonctionne qu'au
    premier essai -- et c'est le mecanisme de secours.

    Mesure brute :
        1er appel, variable absente -> None ; dans _cache_miss -> True
        variable POSEE, 2e appel    -> None ; os.environ dit   -> 1

    L'environnement est la seule source qui change SANS que personne ne
    previenne. On ne fige jamais une absence contre lui.
    """
    assert secrets.get_secret(CLE_TEST) is None
    assert CLE_TEST in secrets._cache_miss        # absence reelle, correctement notee

    monkeypatch.setenv(CLE_TEST, SENTINELLE)
    assert secrets.get_secret(CLE_TEST) == SENTINELLE, (
        "une bascule posee apres coup DOIT etre vue : un interrupteur global se "
        "lit a chaque appel, sinon il ne commande rien"
    )


def test_une_bascule_retiree_se_referme(secrets, monkeypatch):
    """Le pendant OBLIGATOIRE du test precedent, et le plus dangereux des deux.

    Mesure du 2026-09-20 : en rendant la bascule visible apres coup, on l'avait
    rendue INDEBRANCHABLE -- `get_secret` la mettait en `_cache`, donc elle
    survivait au retrait de la variable. 15 tests du garde SQL sont passes au
    rouge en le disant : « [BREAKGLASS] SQL table sensible autorise » alors que
    plus personne n'avait autorise quoi que ce soit.

    En exploitation : un operateur ouvre le breakglass, fait son geste, retire
    la variable -- et le garde reste OUVERT jusqu'a l'arret du process. Un
    interrupteur qui ne se releve pas n'est pas un interrupteur.
    """
    monkeypatch.setattr(secrets, "_BASCULES_DE_POLITIQUE", frozenset({CLE_TEST}))
    monkeypatch.setenv(CLE_TEST, SENTINELLE)
    assert secrets.get_secret(CLE_TEST) == SENTINELLE

    monkeypatch.delenv(CLE_TEST, raising=False)
    assert secrets.get_secret(CLE_TEST) is None, (
        "une bascule de politique RETIREE doit redevenir inactive : la mettre "
        "en cache ouvre un garde que plus personne ne tient"
    )
    assert CLE_TEST not in secrets._cache, (
        "une bascule de politique n'a rien a faire dans le cache de valeurs"
    )


def test_le_breakglass_est_declare_comme_bascule(secrets):
    """Le raccord, sinon le mecanisme serait juste et non cable.

    LAFORGE_ALLOW_SECRETS_READ commande `forge_secret_guard` : lecture de
    secrets, code Python suspect, commandes shell, SQL sur tables sensibles,
    ecriture sur chemins proteges. C'est LE garde a ne jamais laisser ouvert
    par inadvertance.
    """
    assert "LAFORGE_ALLOW_SECRETS_READ" in secrets._BASCULES_DE_POLITIQUE


def test_le_cache_d_absence_expire(secrets, monkeypatch):
    """STALE != DEAD. Une absence constatee il y a longtemps n'est pas une
    absence maintenant : un secret provisionne pendant que le process tourne
    (rotation, coffre demarre en retard) doit finir par etre vu."""
    assert secrets.get_secret(CLE_TEST) is None
    assert CLE_TEST in secrets._cache_miss

    # Le constat d'absence est vieilli au-dela du TTL, sans attendre.
    monkeypatch.setattr(secrets, "_MISS_TTL_S", 0.0)
    monkeypatch.setattr(secrets, "_machine_vault", lambda k: SENTINELLE)

    assert secrets.get_secret(CLE_TEST) == SENTINELLE, (
        "un cache d'absence sans peremption transforme un incident transitoire "
        "en panne definitive pour toute la vie du process"
    )


def test_une_absence_fraiche_nest_pas_re_sondee(secrets, monkeypatch):
    """Symetrie : le cache doit garder son interet. Sans quoi 159 appelants
    re-sondent quatre sources a chaque appel sur les cles absentes."""
    sondes = {"n": 0}

    def compte(_k):
        sondes["n"] += 1
        return None

    monkeypatch.setattr(secrets, "_machine_vault", compte)
    secrets.get_secret(CLE_TEST)
    apres_premier = sondes["n"]
    for _ in range(5):
        secrets.get_secret(CLE_TEST)
    assert sondes["n"] == apres_premier, (
        "dans la fenetre de fraicheur, l'absence connue ne doit pas re-sonder"
    )


# ------------------------------------------------- CLIQUET ANTI-JUMEAU-MORT

def test_le_diagnostic_est_atteignable_par_un_chemin_reel():
    """Un correctif sur un module que personne n'appelle ne change rien.

    Mesure du 2026-09-20 : `diagnostic()` a zero appelant reel. Rendre la
    fonction exhaustive sans la brancher reproduirait a l'identique la faute du
    jour (« le correctif etait juste, et applique au jumeau mort »). Ce test
    exige donc un point d'entree que le corps peut emprunter.
    """
    import importlib

    mod = importlib.import_module(MOD)
    assert hasattr(mod, "main"), "le module doit garder un point d'entree CLI"

    import inspect

    src = inspect.getsource(mod.main)
    assert "diagnostic" in src, (
        "le CLI doit exposer le diagnostic : sans chemin reel, la fonction reste "
        "un jumeau mort quelle que soit sa qualite"
    )
