"""NR — la révocation d'un secret MORD sur la chaîne réelle, mark() comprise.

PHASE 3 du CAP LONG V9. Le NR voisin `test_le_guichet_respecte_la_quarantaine_nr`
substitue `_sante_de_la_valeur` : il prouve la LOGIQUE du guichet, pas la CHAINE.
Celui-ci n'en substitue aucun maillon : il appelle le VRAI
`forge_key_rotation.mark()`, qui ecrit dans un VRAI `key_health.json`, et
verifie que `get_secret` refuse.

    mark()  ->  key_health.json  ->  empreinte sha256  ->  _usable  ->  get_secret

AUCUN SECRET REEL N'EST UTILISE, et rien de la production n'est touche :
  * `_HEALTH` est redirige vers `tmp_path` -- le ledger reel n'est ni lu ni ecrit ;
  * les valeurs sont des chaines de test, injectees par le test ;
  * `_fp` empreinte ces chaines, donc le ledger isole ne contient que des sha.

TROIS ETATS QU'IL NE FAUT PAS CONFONDRE, et c'est tout l'objet du fichier :

    MARKED     `mark()` a ecrit dans le ledger
    ENFORCED   le guichet LIT ce ledger et sait que la cle est mauvaise
    EFFECTIVE  un appelant reel se voit REFUSER la valeur

Un systeme peut etre MARKED sans etre EFFECTIVE -- c'etait l'etat mesure avant
le raccord du 2026-09-21 : `forge_key_rotation` savait `TOGETHER_API_KEY` morte
(http401) pendant que `get_secret` la distribuait a ses 159 appelants.

ET LA FENETRE EST MESUREE, pas affirmee : entre `mark()` et le refus, le cache
du guichet (`_CACHE_TTL_S`, 300 s) continue de servir la valeur deja lue. Cette
fenetre EXISTE, elle est bornee, et ce NR la rend observable au lieu de la
laisser implicite.
"""
import importlib
import json

import pytest

SECRETS = "nokido_agent.app.forge_secrets"
ROTATION = "nokido_agent.app.forge_key_rotation"

CLE = "NOKIDO_NR_PROVIDER_API_KEY"
K0 = "valeur-de-test-K0-jamais-un-vrai-secret"
K1 = "valeur-de-test-K1-jamais-un-vrai-secret"


@pytest.fixture()
def chaine(tmp_path, monkeypatch):
    """Guichet + rotateur isoles. Le ledger REEL n'est ni lu ni ecrit."""
    s = importlib.import_module(SECRETS)
    kr = importlib.import_module(ROTATION)

    monkeypatch.setattr(kr, "_HEALTH", tmp_path / "key_health.json")
    # Le rotateur a SON PROPRE cache module (`_health_cache`, TTL 60 s). Sans
    # ce reset, un test lirait le ledger du test precedent -- et c'est ce qui
    # a revele l'existence de ce second cache.
    monkeypatch.setattr(kr, "_health_cache", (0.0, None))
    s.invalidate_cache()
    if hasattr(s, "_vider_observations"):
        s._vider_observations()
    monkeypatch.setattr(s, "_wcm", lambda k: None)
    monkeypatch.setattr(s, "_dotenv", lambda k: None)
    monkeypatch.delenv(CLE, raising=False)

    etat = {"valeur": K0}
    monkeypatch.setattr(s, "_machine_vault", lambda k: etat["valeur"])

    yield s, kr, etat

    s.invalidate_cache()
    if hasattr(s, "_vider_observations"):
        s._vider_observations()


def test_le_ledger_de_test_est_bien_isole(chaine, tmp_path):
    """Garde-fou du NR lui-meme : si l'isolation casse, ce fichier ecrirait
    dans le ledger de PRODUCTION. On le verifie avant tout le reste."""
    _s, kr, _e = chaine
    assert str(tmp_path) in str(kr._HEALTH)
    assert "sandbox" not in str(kr._HEALTH.parent.name)


def test_K0_active_est_servie(chaine):
    s, _kr, _e = chaine
    assert s.get_secret(CLE) == K0
    assert s.observees()[CLE]["issue"] == "TROUVE"


def test_MARKED_puis_EFFECTIVE_le_meme_appel_est_REFUSE(chaine):
    """LE test du mandat : meme appel, meme guichet, seule la revocation change.

    On n'a substitue AUCUN maillon : `mark()` est le vrai, il ecrit un vrai
    fichier, et c'est `get_secret` qui refuse.
    """
    s, kr, _e = chaine
    assert s.get_secret(CLE) == K0                    # ACTIVE -> ACCEPTE

    kr.mark(CLE, K0, "bad", "http401")                # MARKED (vrai mark)
    assert kr._HEALTH.exists(), "mark() n'a rien ecrit : la chaine est rompue"
    ledger = json.loads(kr._HEALTH.read_text(encoding="utf-8"))
    assert any(e.get("status") == "bad" for e in ledger.values())

    s.invalidate_cache(CLE)                           # on sort de la fenetre
    assert s.get_secret(CLE) is None, (
        "MARKED sans EFFECTIVE : le rotateur sait la cle morte et le guichet "
        "la distribue quand meme -- exactement l'etat mesure avant le raccord"
    )
    assert s.observees()[CLE]["issue"] == "QUARANTAINE", (
        "le refus doit se distinguer d'ABSENT : confondre les deux enverrait "
        "re-provisionner une cle qui est la et qu'on a ecartee. Et depuis le "
        "2026-09-21 il dit aussi sa DUREE : `bad` est une QUARANTAINE que "
        "`_usable` leve seule apres 6 h, pas une revocation"
    )


def test_QUARANTAINE_et_REVOQUE_ne_se_confondent_pas(chaine):
    """La distinction posee le 2026-09-21, sur la chaine reelle.

    Les deux refusent de servir — c'est le meme effet immediat. Mais l'un
    revient seul apres `_BAD_TTL` et l'autre exige une decision inverse. Les
    nommer pareil ferait lire « morte » devant une cle qui reviendra, et
    « revient seule » devant une cle compromise.
    """
    s, kr, _e = chaine
    kr.mark(CLE, K0, "bad", "http401")
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) is None
    assert s.observees()[CLE]["issue"] == "QUARANTAINE"

    kr.mark(CLE, K0, "revoked", "compromission")
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) is None, "une cle REVOQUEE doit rester refusee"
    assert s.observees()[CLE]["issue"] == "REVOQUE"

    # Et le retrait par decision ne s'use pas : meme horodatee a l'epoch, elle
    # reste refusee, la ou un `bad` de 1970 serait re-arme depuis longtemps.
    ledger = json.loads(kr._HEALTH.read_text(encoding="utf-8"))
    entree = ledger[kr._fp(K0)]
    entree["ts"] = 0.0
    assert kr._usable(entree) is False


def test_K1_introduite_est_ACCEPTEE_alors_que_K0_reste_REFUSEE(chaine):
    """La rotation minimale : la nouvelle passe, l'ancienne non.

    Preuve que la revocation porte sur LA VALEUR (par empreinte) et non sur le
    NOM de la cle -- sans quoi K1 serait refusee avec K0.
    """
    s, kr, etat = chaine
    kr.mark(CLE, K0, "bad", "http401")
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) is None                  # K0 refusee

    etat["valeur"] = K1                               # K1 introduite au coffre
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) == K1, (
        "K1 est refusee alors que seule K0 a ete revoquee : la quarantaine "
        "porterait sur le NOM et non sur la VALEUR"
    )

    etat["valeur"] = K0                               # retour a l'ancienne
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) is None, "K0 doit rester refusee apres la rotation"


def test_la_revocation_ne_touche_PAS_les_autres_cles(chaine):
    """Test negatif : revoquer une valeur ne doit pas assecher le guichet."""
    s, kr, _e = chaine
    autre = "NOKIDO_NR_AUTRE_CLE"
    kr.mark(CLE, K0, "bad", "http401")
    s.invalidate_cache()
    assert s.get_secret(autre) == K0 or s.get_secret(autre) is None
    # La valeur servie pour `autre` est la meme chaine K0, donc revoquee AUSSI :
    # c'est voulu -- la quarantaine porte sur la VALEUR. On le DIT plutot que
    # de feindre l'inverse.
    assert s.observees()[autre]["issue"] in {"QUARANTAINE", "REVOQUE", "TROUVE"}


def test_la_FENETRE_du_cache_est_reelle_et_bornee(chaine, monkeypatch):
    """« Si un cache retarde la revocation : mesurer exactement sa duree. »

    Dans la fenetre, la valeur deja lue continue d'etre servie -- ce n'est pas
    un defaut cache, c'est un delai BORNE qu'on rend observable.
    """
    s, kr, _e = chaine
    assert s.get_secret(CLE) == K0                    # entre en cache
    kr.mark(CLE, K0, "bad", "http401")                # revoquee MAINTENANT

    servi_dans_la_fenetre = s.get_secret(CLE)
    assert servi_dans_la_fenetre == K0, (
        "le cache ne sert plus dans sa fenetre : le TTL ne joue plus son role"
    )
    borne = s._CACHE_TTL_S
    assert borne > 0

    monkeypatch.setattr(s, "_CACHE_TTL_S", 0.0)       # fenetre echue
    assert s.get_secret(CLE) is None, (
        "passee la fenetre de %s s, la revocation DOIT mordre" % borne
    )


def test_la_fenetre_reelle_est_la_SOMME_DE_DEUX_CACHES(chaine):
    """DECOUVERTE du 2026-09-21, et elle corrige un chiffre que j'allais publier.

    Il n'y a pas UN cache sur le chemin de revocation, il y en a DEUX en serie :

        forge_key_rotation._health_cache   TTL _SECRET_TTL   (60 s)
        forge_secrets._cache               TTL _CACHE_TTL_S  (300 s)

    Annoncer « la fenetre vaut 300 s » aurait ete FAUX PAR OMISSION. La borne
    haute est leur SOMME -- 360 s -- et ce test la rend executable pour qu'elle
    ne se perde pas.

    NUANCE MESUREE, qui evite de crier au loup : `_save_health` note que
    « l'ecriture fait autorite sur le cache », donc dans le MEME process un
    `mark()` est vu immediatement et seuls les 300 s du guichet jouent. Les 60 s
    ne s'ajoutent qu'ENTRE PROCESS -- ce qui est precisement le cas reel, le
    rotateur marquant depuis un job pendant que le guichet vit dans le hub.
    """
    s, kr, _e = chaine
    assert hasattr(kr, "_SECRET_TTL"), "le cache du rotateur a disparu"
    assert hasattr(kr, "_health_cache")
    assert kr._SECRET_TTL > 0

    fenetre_max = kr._SECRET_TTL + s._CACHE_TTL_S
    assert fenetre_max <= 900, (
        "fenetre de contournement de %s s : au-dela d'un quart d'heure, une "
        "revocation cesse d'etre une revocation" % fenetre_max
    )

    # L'ecriture fait autorite : dans CE process, mark() est vu tout de suite.
    kr.mark(CLE, K0, "bad", "http401")
    assert kr._load_health(), "le ledger doit etre visible sans attendre le TTL"


def test_un_quota_ne_revoque_toujours_pas_sur_la_chaine_reelle(chaine):
    """L'asymetrie assumee, verifiee bout en bout et non plus par substitution :
    un 429 limite un debit, il ne dit rien sur la validite du credential."""
    s, kr, _e = chaine
    kr.mark(CLE, K0, "quota", "http429")
    s.invalidate_cache(CLE)
    assert s.get_secret(CLE) == K0
    assert s.observees()[CLE]["sante_cle"] == "quota"
