"""NR — une revocation ne doit ni expirer par surprise, ni s'effacer en silence.

CAP V9, P3 — rotation. Critere owner, rappele mot pour mot : le critere est le
NEGATIF — la cle doit CESSER D'ETRE SERVIE. Ce NR ne verifie donc pas qu'une
rotation « marche » ; il verifie que la sortie du pool TIENT.

CE QUI EXISTE DEJA, et qu'on n'a pas reecrit (anti-dup, mesure du 2026-09-21)
============================================================================
`forge_key_rotation` porte le cycle presque entier : `_pool()` expose les
generations d'une meme cle (`GROQ_API_KEY`, `_2`, `_3`...), `set_key(env, val,
slot)` installe l'entrante, `resolve()` sert la premiere `_usable()` — donc la
bascule K0 -> K1 existe — et `quarantine_info()` dit la duree restante.

TROIS DEFAUTS MESURES, ET ILS NE SONT PAS DE MEME NATURE
========================================================
1. VOULU ET DOCUMENTE : `bad` se re-arme apres `_BAD_TTL` (6 h). C'est juste
   pour une sante OPERATIONNELLE — un 403 transitoire doit reessayer. Ce NR ne
   le conteste pas. Il exige seulement qu'un etat de POLITIQUE, lui, ne se
   re-arme JAMAIS tout seul. `DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE`.

2. NON VOULU, SILENCIEUX : `_load_health` rend `{}` sur toute exception, et
   `_usable(None)` rend True (« inconnue = optimiste »). Un ledger corrompu ou
   illisible rend donc TOUTES les cles utilisables, revocations comprises, sans
   un mot. C'est « conclure d'une source qui se tait », et du cote le plus cher.

3. NON VOULU : `mark()` fait un read-modify-write sur un cache de 60 s puis
   reecrit le dict ENTIER, sans verrou, avec 5 ecrivains hors module en
   multi-process. Une entree posee par un autre process entre le chargement et
   l'ecriture est perdue. Mesure du 2026-09-21 : `TOGETHER_API_KEY`, vue `bad`
   le 2026-09-20, ne figurait plus au ledger — 4 entrees, toutes `ok`, toutes
   du meme horodatage.

AUCUNE VALEUR DE SECRET N'EST LUE NI ECRITE. Le ledger est indexe par empreinte
sha256 ; ce NR fabrique des chaines de test et ne touche jamais le vrai fichier
(`_HEALTH` est substitue vers `tmp_path`).
"""
import importlib
import json

import pytest

# Ce NR eprouve le ledger de sante par ses entrailles — `_HEALTH`, `_usable`,
# `_fp`, `_load_health`. C'est son objet : un etat interne qui ne tient pas se
# constate de l'interieur. Nomme ici plutot que laisse en avertissements muets.
# pylint: disable=protected-access

KR = "nokido_agent.app.forge_key_rotation"


@pytest.fixture(name="rot")
def _fx_rot(tmp_path, monkeypatch):
    """Le rotateur, isole sur un ledger jetable et sans cache resident.

    Le cache `_health_cache` survit a la substitution de `_HEALTH` : sans le
    vider, les tests liraient l'etat du VRAI ledger et ne mesureraient rien.
    """
    mod = importlib.import_module(KR)
    monkeypatch.setattr(mod, "_HEALTH", tmp_path / "key_health.json", raising=True)
    monkeypatch.setattr(mod, "_health_cache", (0.0, None), raising=True)
    return mod


def _vider_cache(mod, monkeypatch):
    monkeypatch.setattr(mod, "_health_cache", (0.0, None), raising=True)


# ------------------------------------------------ 1. le ledger qui se tait

def test_un_ledger_ILLISIBLE_ne_rend_pas_tout_utilisable(rot, monkeypatch):
    """Un ledger corrompu doit etre distingue d'un ledger VIDE.

    Aujourd'hui les deux rendent `{}`, et `{}` veut dire « aucune cle n'est
    marquee », donc « tout est servable ». Une corruption de fichier leve donc
    toutes les revocations, en silence et sans qu'aucun try/except le voie.
    """
    rot._HEALTH.write_text("{ ceci n est pas du JSON", encoding="utf-8")
    _vider_cache(rot, monkeypatch)
    assert hasattr(rot, "etat_du_ledger"), (
        "aucune forme ne distingue un ledger ILLISIBLE d'un ledger VIDE : une "
        "corruption leve toutes les revocations sans que personne le sache"
    )
    assert rot.etat_du_ledger() == "ILLISIBLE"


def test_un_ledger_ABSENT_reste_distinct_d_un_ledger_ILLISIBLE(rot, monkeypatch):
    """La symetrie compte autant : un premier demarrage n'est pas une panne.
    Transformer « pas encore de ledger » en « ledger casse » fabriquerait des
    alertes fictives, et un garde qui crie a faux se fait desarmer."""
    _vider_cache(rot, monkeypatch)
    assert rot.etat_du_ledger() == "VIDE"


# ------------------------------------------------ 2. politique vs sante

def test_un_etat_de_POLITIQUE_ne_se_re_arme_JAMAIS_seul(rot):
    """`bad` expire apres 6 h, et c'est voulu. `revoked` ne doit pas.

    Une cle retiree par DECISION ne revient que par une decision inverse. Sinon
    « revoquee » veut dire « indisponible six heures », et le mot ment a
    l'operateur qui le lit.
    """
    ancien = {"env": "FAUX_API_KEY", "status": "revoked", "reason": "test",
              "ts": 0.0}  # epoch : bien au-dela de tout TTL
    assert rot._usable(ancien) is False, (
        "une cle REVOQUEE depuis 1970 est rendue utilisable : l'etat de "
        "politique est traite comme une quarantaine"
    )


def test_bad_continue_d_expirer_comme_avant(rot):
    """NON-REGRESSION explicite : on ajoute un etat, on ne durcit pas celui qui
    existe. Un 403 transitoire doit toujours pouvoir reessayer apres _BAD_TTL."""
    vieux_bad = {"env": "FAUX_API_KEY", "status": "bad", "reason": "403",
                 "ts": 0.0}
    assert rot._usable(vieux_bad) is True, (
        "`bad` ne se re-arme plus : ce NR devait ajouter un etat, pas changer "
        "la politique operationnelle existante"
    )


def test_le_guichet_ne_nomme_pas_REVOQUE_une_quarantaine():
    """`forge_secrets` etiquetait `REVOQUE` tout statut non utilisable — donc
    aussi un `quota` d'une heure. Deux causes, deux remedes, deux mots."""
    src = importlib.import_module("nokido_agent.app.forge_secrets")
    import inspect
    texte = inspect.getsource(src._memoriser)
    assert "QUARANTAINE" in texte or "quarantaine" in texte, (
        "le guichet ne distingue pas une mise en quarantaine temporaire d'une "
        "revocation : l'operateur lit REVOQUE et croit la cle morte"
    )


# ------------------------------------------------ 3. la course qui efface

def test_mark_ne_PERD_pas_une_entree_ecrite_entre_temps(rot):
    """Reproduit la course mesuree, sans concurrence reelle.

    Scenario : ce process a charge le ledger (cache 60 s), un AUTRE process y
    ecrit une revocation, puis ce process marque une cle et reecrit son dict.
    L'entree de l'autre doit survivre.
    """
    rot.mark("A_API_KEY", "valeur-a", "ok", "amorce")      # charge + ecrit
    # Un autre process pose une revocation DIRECTEMENT dans le fichier.
    autre = json.loads(rot._HEALTH.read_text(encoding="utf-8"))
    autre[rot._fp("valeur-b")] = {"env": "B_API_KEY", "status": "revoked",
                                  "reason": "compromise", "ts": 1.0}
    rot._HEALTH.write_text(json.dumps(autre), encoding="utf-8")
    # Ce process, lui, a toujours son cache : il ne voit PAS la revocation.
    rot.mark("A_API_KEY", "valeur-a", "ok", "second passage")

    final = json.loads(rot._HEALTH.read_text(encoding="utf-8"))
    assert rot._fp("valeur-b") in final, (
        "la revocation posee par un autre process a ete EFFACEE : `mark` "
        "reecrit un dict vieux de 60 s au lieu de fusionner"
    )
    assert final[rot._fp("valeur-b")]["status"] == "revoked"


def test_l_ecriture_du_ledger_est_ATOMIQUE(rot):
    """Un `write_text` direct laisse une fenetre ou le fichier est tronque : s'y
    lire donne un JSON invalide, donc `{}`, donc toutes les cles servables.
    L'ecriture doit passer par un temporaire puis un remplacement."""
    import inspect
    src = inspect.getsource(rot._save_health)
    assert "replace" in src, (
        "l'ecriture du ledger n'est pas atomique : une interruption laisse un "
        "fichier tronque, que `_load_health` lit comme un ledger VIDE"
    )


# ------------------------------------------------ 4. le CYCLE de rotation

def test_le_cycle_K0_vers_K1_se_deroule_sur_resolve(rot, monkeypatch):
    """K0 ACTIVE -> K1 STAGED -> K1 ACTIVE -> K0 GRACE -> K0 REVOKED.

    CE QUI EST REEL ICI : `resolve()`, `_usable()`, `mark()`, le ledger sur
    disque. CE QUI EST SUBSTITUE : `_secret`, c'est-a-dire la SOURCE des
    valeurs du pool — et rien d'autre.

    POURQUOI on ne passe pas par `set_key`, qui serait le geste complet :
    `set_key` appelle `forge_secrets.set_secret`, donc ECRIT DANS LE COFFRE.
    Meme sous un nom factice cela laisserait une entree DPAPI reelle. La
    consigne de campagne interdit la rotation d'un credential reel, et une
    demonstration ne justifie pas d'ecrire dans le vault. Ce test prouve donc
    la MECANIQUE du cycle ; il ne prouve pas l'installation d'une cle, qui
    reste un geste OPERATEUR.
    """
    ENV = "NOKIDO_NR_CYCLE_API_KEY"
    pool = {"": "valeur-K0"}                       # slot 1 seulement
    monkeypatch.setattr(rot, "_secret", lambda nom: pool.get(nom[len(ENV):])
                        if nom.startswith(ENV) else None, raising=True)

    # --- K0 ACTIVE : une seule cle, elle est servie
    _managed, servie = rot.resolve(ENV)
    assert servie == "valeur-K0"

    # --- K1 STAGED : l'entrante est presente mais K0 reste servie (ordre du pool)
    pool["_2"] = "valeur-K1"
    _m, servie = rot.resolve(ENV)
    assert servie == "valeur-K0", "K1 est staged, elle ne doit pas encore servir"

    # --- K0 GRACE puis K1 ACTIVE : K0 ecartee, la bascule est automatique
    rot.mark(ENV, "valeur-K0", "bad", "http401 lors de la rotation")
    _m, servie = rot.resolve(ENV)
    assert servie == "valeur-K1", "la bascule K0 -> K1 ne s'est pas faite"

    # --- GRACE est bien TEMPORAIRE : passe l'echeance, K0 redeviendrait servable
    ledger = json.loads(rot._HEALTH.read_text(encoding="utf-8"))
    entree_k0 = ledger[rot._fp("valeur-K0")]
    entree_k0["ts"] = 0.0
    assert rot._usable(entree_k0) is True, (
        "`bad` doit rester une GRACE qui expire — c'est ce qui permet a un 401 "
        "transitoire de revenir"
    )

    # --- K0 REVOKED : la decision, elle, ne s'use pas
    rot.mark(ENV, "valeur-K0", "revoked", "fin de rotation")
    ledger = json.loads(rot._HEALTH.read_text(encoding="utf-8"))
    entree_k0 = ledger[rot._fp("valeur-K0")]
    entree_k0["ts"] = 0.0
    assert rot._usable(entree_k0) is False, (
        "K0 REVOKED redevient servable avec le temps : le cycle ne se ferme pas"
    )
    _m, servie = rot.resolve(ENV)
    assert servie == "valeur-K1", "apres revocation de K0, seule K1 doit servir"


def test_un_pool_ENTIEREMENT_ECARTE_ne_se_lit_pas_comme_ABSENT(rot, monkeypatch):
    """Regression introduite par le raccord du 2026-09-20, mesuree le 21.

    Depuis que `forge_secrets` REFUSE de servir une valeur ecartee, `_secret`
    rend None pour elle — donc `_pool` ne la voit plus du tout. Quand toutes les
    cles d'un env sont ecartees, le pool devient VIDE, et :

        resolve(env)          -> (False, None)   « pas de pool du tout »
        quarantine_info(env)  -> None            muet

    Un pool en quarantaine devient donc indistinguable d'une cle jamais
    configuree. C'est exactement la confusion que `quarantine_info` a ete
    ecrite pour tenir — ABSENTE vs ECARTEE — apres la fausse enquete du
    2026-08-11 (20 min a soupconner le coffre DPAPI pour une cle valide).

    Le ledger, lui, SAIT : ses entrees portent `env`. C'est a lui qu'il faut
    demander quand le pool ne peut plus repondre.
    """
    ENV = "NOKIDO_NR_TOUT_ECARTE_KEY"
    # Le guichet a ecarte la cle : `_secret` ne la rend plus. On reproduit
    # l'effet, on ne le simule pas par une absence de configuration.
    monkeypatch.setattr(rot, "_secret", lambda _nom: None, raising=True)
    rot.mark(ENV, "valeur-ecartee", "revoked", "compromission")

    assert rot._pool(ENV) == [], "preambule : le pool doit bien etre vide ici"
    info = rot.quarantine_info(ENV)
    assert info is not None, (
        "un pool entierement ecarte rend None, comme un env jamais configure : "
        "l'operateur sera envoye re-provisionner une cle qui est la et qu'on a "
        "volontairement retiree"
    )
    assert info.get("reason"), "la raison du retrait doit etre dite"


def test_un_env_dont_une_cle_est_ECARTEE_reste_MANAGED(rot, monkeypatch):
    """`managed` commande s'il faut RESPECTER la rotation. Le perdre la contourne.

    Chemin reel, mesure le 2026-09-21 — `forge_agent_proxy._load_api_key` :

        _managed, _rk = _rot_resolve(name)
        if _managed:
            return _rk              # rotation respectee
        ... sinon _API_KEYS[name], puis get_secret(name)

    `_API_KEYS` est un cache de valeurs qui n'est JAMAIS purge (verifie : aucune
    invalidation dans le module, aucune mention dans les 1862 autres fichiers
    de app/ et tools/). Il vit autant que le process.

    Donc si `managed` retombe a False apres une revocation, le proxy quitte la
    voie gouvernee et ressert la cle REVOQUEE depuis son cache — indefiniment.

    Or `managed` se calculait sur les empreintes des cles PRESENTES DANS LE
    POOL. Depuis que le guichet ecarte les valeurs revoquees, la cle retiree
    n'est plus dans le pool : son empreinte n'est plus testee, et l'env cesse
    d'etre « gere » au moment precis ou il l'est le plus.
    """
    ENV = "NOKIDO_NR_MANAGED_KEY"
    # K0 revoquee et donc ecartee par le guichet ; K1 saine au slot 2.
    monkeypatch.setattr(rot, "_secret",
                        lambda nom: "valeur-K1" if nom.endswith("_2") else None,
                        raising=True)
    rot.mark(ENV, "valeur-K0", "revoked", "compromission")

    managed, servie = rot.resolve(ENV)
    assert servie == "valeur-K1", "preambule : K1 doit servir"
    assert managed is True, (
        "managed=False alors qu'une cle de cet env est revoquee au ledger : "
        "l'appelant quitte la voie gouvernee et retombe sur son propre cache, "
        "qui peut contenir la cle revoquee"
    )


def test_un_env_VRAIMENT_inconnu_reste_silencieux(rot, monkeypatch):
    """La symetrie, sans quoi on remplace un angle mort par du bruit : un nom
    que le ledger ne connait pas ne doit PAS fabriquer une quarantaine."""
    monkeypatch.setattr(rot, "_secret", lambda _nom: None, raising=True)
    assert rot.quarantine_info("NOKIDO_NR_JAMAIS_VU_KEY") is None


def test_un_ECHEC_d_ecriture_du_ledger_ne_passe_pas_inapercu(rot, monkeypatch, caplog):
    """Le garde que le gate de recidive a reclame au commit, et il avait raison.

    `_save_health` avalait toute erreur d'ecriture par un `pass`. `mark()`
    rendait donc la main normalement alors que RIEN n'avait ete persiste :
    l'appelant croyait avoir revoque une cle qui restait servie partout. Pire,
    le cache de CE process etait deja a jour — donc lui seul voyait la
    revocation, et elle disparaissait au redemarrage.

    Emettre reussit toujours, meme quand personne n'enregistre.
    """
    import logging
    # Un repertoire la ou le ledger attend un fichier : l'ecriture ne peut pas
    # aboutir, et c'est une panne REELLE du systeme de fichiers, pas une
    # exception simulee par un mock.
    impossible = rot._HEALTH.parent / "bloque"
    impossible.mkdir()
    monkeypatch.setattr(rot, "_HEALTH", impossible, raising=True)

    with caplog.at_level(logging.ERROR, logger="forge.key_rotation"):
        rot.mark("Z_API_KEY", "valeur-z", "revoked", "test echec ecriture")

    assert caplog.records, (
        "l'echec d'ecriture est MUET : `mark` a rendu la main comme si la "
        "revocation etait persistee"
    )
    msg = caplog.records[0].getMessage()
    assert "consequence" in msg, (
        "le journal dit qu'il a echoue mais pas CE QUE CA COUTE : sans la "
        "consequence, personne ne sait qu'une revocation vient d'etre perdue"
    )


def test_une_revocation_survit_a_une_relecture_complete(rot, monkeypatch):
    """Bout en bout, sur le chemin reel : marquer, vider le cache (equivaut a
    un autre process ou a un restart), relire, et la cle doit rester refusee."""
    rot.mark("C_API_KEY", "valeur-c", "revoked", "test bout en bout")
    _vider_cache(rot, monkeypatch)
    entree = rot._load_health().get(rot._fp("valeur-c"))
    assert entree is not None, "la revocation n'a pas survecu a la relecture"
    assert rot._usable(entree) is False, "la cle revoquee est de nouveau servie"
