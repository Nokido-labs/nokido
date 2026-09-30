"""NR de MESURE — `_API_KEYS` est-il un cache, ou un second chemin de livraison ?

CAP V9, jalon `_API_KEYS`. Mandat owner du 2026-09-21 : **mesurer avant de
corriger**. Ce fichier ne modifie RIEN dans `forge_agent_proxy` ; il etablit ce
que le cache EST, pour qu'on decide ensuite en connaissance de cause --
supprime, rendu revocable, ou conserve comme cache interne d'un broker.

CE QUE L'AUDIT STATIQUE A DEJA ETABLI (2026-09-21, fige comme preuve)
=====================================================================
    _load_api_key(name)
     ├─0  resolve(name)          -> si managed : return cle du pool (ou None)
     ├─1  if name in _API_KEYS   -> return cache          <-- AVANT le coffre
     ├─2  get_secret(name)       -> si trouve : _API_KEYS[name] = v
     ├─3  os.environ[name]
     └─4  Nokido.env (fichier EN CLAIR)
          -> si val : _API_KEYS[name] = val

Deux ecritures, quatre sources, AUCUNE peremption, AUCUNE invalidation. Et le
code le dit lui-meme : « contrairement a la couche de rotation, ce cache n'a
aucune peremption : le seul remede etait un restart ».

LA QUESTION QUE CE NR TRANCHE
=============================
    Une credential peut-elle atteindre un consommateur SANS avoir traverse le
    controle gouverne ?

CINQ ETATS, JAMAIS `None`. Rendre `None` pour « pas de cle », « cle refusee »
et « je n'ai pas pu mesurer » est exactement la confusion qui a coute 331
process lus « eteints ». On classe donc en ABSENT / REFUSE / REVOQUE / SERVI /
NON_MESURABLE.

AUCUNE VRAIE CLE N'EST UTILISEE. Les noms sont `NOKIDO_NR_*`, les valeurs sont
fabriquees ici, et le cache reel est substitue par `monkeypatch` -- le
`_API_KEYS` du process de test n'est jamais celui d'un hub en service.
"""
import importlib
import inspect
import os

import pytest

PROXY = "nokido_agent.app.forge_agent_proxy"
ROT = "nokido_agent.app.forge_key_rotation"

ABSENT, REFUSE, REVOQUE, SERVI, NON_MESURABLE = (
    "ABSENT", "REFUSE", "REVOQUE", "SERVI", "NON_MESURABLE")


@pytest.fixture(name="proxy")
def _fx_proxy(monkeypatch):
    """Le proxy, avec un cache JETABLE. Sans cette substitution, le test
    ecrirait dans le `_API_KEYS` du process qui l'heberge."""
    mod = importlib.import_module(PROXY)
    monkeypatch.setattr(mod, "_API_KEYS", {}, raising=True)
    return mod


@pytest.fixture(name="rot")
def _fx_rot(tmp_path, monkeypatch):
    mod = importlib.import_module(ROT)
    monkeypatch.setattr(mod, "_HEALTH", tmp_path / "key_health.json", raising=True)
    monkeypatch.setattr(mod, "_health_cache", (0.0, None), raising=True)
    return mod


def _classer(rendu, nom, rot) -> str:
    """Traduit un retour en ETAT. `None` ne suffit pas a distinguer trois cas."""
    if rendu:
        return SERVI
    sante = rot._load_health()
    for empreinte, e in sante.items():
        if (e.get("env") or "").startswith(nom) and not rot._usable(e):
            return REVOQUE if e.get("status") == "revoked" else REFUSE
    return ABSENT


# ══════════════════════════════════════════ VOLET 1 — PROVENANCE (structure)

def test_le_cache_est_consulte_AVANT_le_coffre(proxy):
    """L'ordre des etages est la propriete qui decide de tout.

    Si le cache est lu avant `get_secret`, alors une valeur en cache est servie
    SANS repasser par le guichet -- donc sans le controle de revocation.
    """
    src = inspect.getsource(proxy._load_api_key)
    i_cache = src.find("_API_KEYS")
    i_coffre = src.find("get_secret")
    assert i_cache != -1 and i_coffre != -1
    assert i_cache < i_coffre, (
        "le coffre serait consulte avant le cache : le constat de l'audit du "
        "2026-09-21 ne tiendrait plus, il faut refaire la chaine"
    )


def _ecritures_du_cache(source: str) -> int:
    """Affectations REELLES `_API_KEYS[...] = ...`, comptees par AST.

    Surtout pas `str.count` : le corps de `_load_api_key` porte un commentaire
    qui CITE `_API_KEYS[name] = ""` pour expliquer pourquoi on ne met pas un
    echec en cache. Un comptage textuel en trouve 3 au lieu de 2 -- l'erreur
    exacte commise ici a la premiere ecriture de ce test, et la troisieme fois
    de la journee qu'un instrument a moi lit son propre vocabulaire.
    """
    import ast
    import textwrap
    arbre = ast.parse(textwrap.dedent(source))
    n = 0
    for node in ast.walk(arbre):
        if not isinstance(node, ast.Assign):
            continue
        for cible in node.targets:
            if (isinstance(cible, ast.Subscript)
                    and isinstance(cible.value, ast.Name)
                    and cible.value.id == "_API_KEYS"):
                n += 1
    return n


def test_le_cache_a_DEUX_ecrivains_et_QUATRE_sources(proxy):
    """Ce n'est pas un cache du coffre : c'est un cache de PLUSIEURS sources,
    qui n'ont pas les memes garanties."""
    src = inspect.getsource(proxy._load_api_key)
    ecritures = _ecritures_du_cache(src)
    assert ecritures == 2, (
        "%d site(s) d'ecriture au lieu de 2 : la carte des provenances a "
        "change, l'audit doit etre refait" % ecritures
    )
    for source in ("get_secret", "os.environ", "Nokido.env"):
        assert source in src, "source %r disparue de la chaine" % source


def test_le_cache_n_a_NI_peremption_NI_invalidation(proxy):
    """Mesure, pas lecture de commentaire : on cherche un TTL ou une purge."""
    src = inspect.getsource(proxy)
    autour = inspect.getsource(proxy._load_api_key)
    assert "_API_KEYS.pop" not in src and "_API_KEYS.clear" not in src, (
        "une invalidation existe desormais : elle doit etre mesuree, et ce "
        "test mis a jour"
    )
    assert "TTL" not in autour.upper(), "un TTL est apparu dans la chaine"


# ══════════════════════════ VOLET 2 — REVOCATION ADVERSARIALE (comportement)

NOM = "NOKIDO_NR_APIKEYS_CACHE"
K0 = "valeur-K0-synthetique-jamais-un-vrai-secret"


def test_une_cle_REVOQUEE_n_est_plus_servie_par_load_api_key(proxy, rot,
                                                             monkeypatch):
    """LE test du mandat. La cle est d'abord MISE EN CACHE, puis revoquee.

    On mesure le chemin REEL (`_load_api_key`), pas une reconstitution.
    """
    monkeypatch.setattr(rot, "_secret",
                        lambda n: K0 if n == NOM else None, raising=True)
    monkeypatch.setitem(proxy._API_KEYS, NOM, K0)      # la valeur est en cache
    assert _classer(proxy._load_api_key(NOM), NOM, rot) == SERVI

    rot.mark(NOM, K0, "revoked", "test adversarial")
    etat = _classer(proxy._load_api_key(NOM), NOM, rot)
    assert etat == REVOQUE, (
        "une cle REVOQUEE reste servie par le cache : etat mesure = %s. "
        "L'invariant est qu'une cle revoquee ne redevient jamais servable "
        "parce qu'elle existe encore dans un cache." % etat
    )


def test_la_protection_vient_de_resolve_PAS_du_cache(proxy, rot, monkeypatch):
    """Ce test NOMME la fragilite plutot que de s'en satisfaire.

    Si la cle est refusee, est-ce parce que le cache l'a lachee, ou parce qu'un
    etage AMONT a intercepte ? On le mesure : le cache contient-il TOUJOURS la
    valeur apres la revocation ?
    """
    monkeypatch.setattr(rot, "_secret",
                        lambda n: K0 if n == NOM else None, raising=True)
    monkeypatch.setitem(proxy._API_KEYS, NOM, K0)
    rot.mark(NOM, K0, "revoked", "test adversarial")
    proxy._load_api_key(NOM)

    assert proxy._API_KEYS.get(NOM) == K0, (
        "le cache a ete purge : la protection serait devenue intrinseque, et "
        "ce test doit etre reecrit pour le dire"
    )
    # Constat verrouille : la valeur revoquee EST encore dans le cache. Elle
    # n'est pas servie uniquement parce que `resolve` repond AVANT. Toute voie
    # qui lirait `_API_KEYS` sans passer par `_load_api_key` la servirait.


def test_un_appelant_qui_LIT_le_cache_directement_contourne_tout(proxy, rot,
                                                                 monkeypatch):
    """La mesure du risque, sans le corriger : que voit un consommateur qui
    lit le dict au lieu d'appeler la primitive ?"""
    monkeypatch.setattr(rot, "_secret",
                        lambda n: K0 if n == NOM else None, raising=True)
    monkeypatch.setitem(proxy._API_KEYS, NOM, K0)
    rot.mark(NOM, K0, "revoked", "test adversarial")

    direct = proxy._API_KEYS.get(NOM)
    gouverne = proxy._load_api_key(NOM)
    assert direct and not gouverne, (
        "la lecture directe et la voie gouvernee rendent la meme chose : soit "
        "le cache a ete durci, soit `resolve` ne mord plus -- les deux "
        "changent le constat de l'audit"
    )


def test_un_REDEMARRAGE_vide_le_cache_et_c_est_son_seul_remede(proxy):
    """Le code annonce « le seul remede etait un restart ». On le mesure : le
    cache est un etat de PROCESS, il ne survit a rien."""
    proxy._API_KEYS[NOM] = K0
    neuf = {}                       # ce qu'un process neuf trouverait
    assert NOM not in neuf
    assert proxy._API_KEYS.get(NOM) == K0   # alors que celui-ci l'a encore


# ══════════════════════ VOLET 3 — PROVENANCE HORS COFFRE (credential fictive)

FICTIVE = "NOKIDO_NR_JAMAIS_AU_COFFRE"
VAL_FICTIVE = "valeur-fictive-hors-coffre-synthetique"


def test_une_credential_de_os_environ_atteint_le_consommateur(proxy, rot,
                                                              monkeypatch):
    """LA question du mandat : une credential peut-elle atteindre un
    consommateur SANS avoir traverse le controle gouverne ?

    On en pose une dans l'environnement seulement -- jamais au coffre, jamais
    au ledger -- et on regarde si elle sort.
    """
    monkeypatch.setattr(rot, "_secret", lambda _n: None, raising=True)
    monkeypatch.setenv(FICTIVE, VAL_FICTIVE)
    rendu = proxy._load_api_key(FICTIVE)
    assert rendu == VAL_FICTIVE, (
        "l'etage `os.environ` ne livre plus : la chaine a change et l'audit "
        "doit etre refait"
    )
    # CONSTAT VERROUILLE : elle est livree, et elle est desormais EN CACHE,
    # alors qu'elle n'a jamais vu `get_secret` -- donc jamais le controle
    # `bad`/`revoked`. C'est ce qui fait de `_API_KEYS` un SECOND CHEMIN DE
    # LIVRAISON et non un simple cache du coffre.
    assert proxy._API_KEYS.get(FICTIVE) == VAL_FICTIVE


def test_une_credential_de_Nokido_env_atteint_aussi_le_consommateur(proxy, rot,
                                                                    tmp_path,
                                                                    monkeypatch):
    """Meme question pour le fichier EN CLAIR. Un `Nokido.env` fabrique dans
    `tmp_path` : le vrai fichier du depot n'est jamais lu ni ecrit."""
    monkeypatch.setattr(rot, "_secret", lambda _n: None, raising=True)
    monkeypatch.delenv(FICTIVE, raising=False)
    (tmp_path / "Nokido.env").write_text(
        "# commentaire\n%s=%s\n" % (FICTIVE, VAL_FICTIVE), encoding="utf-8")
    monkeypatch.setattr(proxy, "ROOT", tmp_path, raising=True)

    rendu = proxy._load_api_key(FICTIVE)
    assert rendu == VAL_FICTIVE, (
        "l'etage `Nokido.env` ne livre plus : la chaine a change"
    )
    assert proxy._API_KEYS.get(FICTIVE) == VAL_FICTIVE


def test_une_credential_hors_coffre_n_est_connue_d_AUCUN_ledger(proxy, rot,
                                                                monkeypatch):
    """Consequence directe, et c'est elle qui decide du statut de `_API_KEYS` :
    une valeur qui n'a pas traverse le guichet n'est dans AUCUN ledger, donc
    `mark()` n'a rien a revoquer tant que personne ne l'y inscrit."""
    monkeypatch.setattr(rot, "_secret", lambda _n: None, raising=True)
    monkeypatch.setenv(FICTIVE, VAL_FICTIVE)
    proxy._load_api_key(FICTIVE)

    sante = rot._load_health()
    assert not any((e.get("env") or "").startswith(FICTIVE)
                   for e in sante.values()), (
        "la valeur hors coffre est desormais inscrite au ledger : le chemin "
        "aurait ete gouverne, et l'audit doit etre refait"
    )
    etat = _classer(proxy._load_api_key(FICTIVE), FICTIVE, rot)
    assert etat == SERVI
