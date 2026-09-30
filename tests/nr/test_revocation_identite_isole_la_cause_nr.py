"""NR — identité révoquée = DENY, et SEULE l'identité change.

PHASE 4 du CAP LONG V9. Le mécanisme existe -- `IntegrityManager.revoke` -- mais
la mesure du 2026-09-21 a établi qu'AUCUN appelant de production ne l'exerce :
il n'est instancié que dans `forge_dataset_sync`, et à des lignes qui génèrent
des cas limites (« EC-05 : Revoke agent inconnu »), pas en production.

« Ne pas transformer cette absence en preuve. » Ce NR construit donc la preuve,
avec le harness qui existe déjà (`tests/nr/test_integrity_nr.py` exerce le même
manager) et SANS ajouter d'organe.

L'EXPERIENCE ISOLE LA CAUSALITE, c'est tout son objet :

    même manager · même secret · même scope · même action · même token
    SEULE VARIABLE : l'état de révocation de l'identité

Sans cette discipline, un DENY pourrait venir d'un scope trop étroit, d'un
token expiré ou d'un secret différent -- et on aurait « prouvé » une révocation
qui n'a jamais eu lieu.

AUCUN SECRET REEL : le manager est construit avec un secret de TEST, local au
fichier. On ne touche ni au coffre, ni au manager global du corps.

LIMITE MESUREE ET NOMMEE, pas contournée : `_revoked_seqs` vit EN MEMOIRE. Une
révocation ne survit donc pas au redémarrage du process. Le dernier test le
DEMONTRE au lieu de le supposer -- c'est le maillon qu'attend
`tests/nr/test_agent_keys_ledger_nr.py`, resté rouge à dessein.
"""
import importlib

import pytest

MOD = "nokido_agent.app.forge_integrity"

SECRET_DE_TEST = "secret-de-test-local-a-ce-fichier-jamais-celui-du-corps"
AGENT_A = "NR_AGENT_A"
AGENT_B = "NR_AGENT_B"


@pytest.fixture()
def integrity():
    return importlib.import_module(MOD)


def _emettre(integrity, mgr, agent_id):
    """Un token pour cet agent, avec des scopes larges : on ne veut surtout pas
    qu'un DENY vienne d'un scope trop etroit.

    `scopes` est un DICT {scope: [actions]} -- `_scope_allows` fait
    `user_scopes.get(scope)`. Une liste ["fs:read"] leve AttributeError : c'est
    l'erreur d'usage que ce NR a commise a sa premiere ecriture, et la forme
    est fixee ici pour qu'elle ne se repaie pas.
    """
    return mgr.create_manifest(
        agent_id=agent_id,
        ring=integrity.IntegrityRing.DEV,
        scopes={"fs": ["read", "write"]},
        duration_s=600,
    )


def _jeton(res):
    """create_manifest peut rendre le token seul ou un couple/dict : on
    normalise SANS supposer, et on echoue en le disant si la forme change."""
    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        for cle in ("token", "token_str", "raw"):
            if cle in res:
                return res[cle]
    if isinstance(res, (tuple, list)) and res:
        return _jeton(res[0])
    raise AssertionError("forme inattendue de create_manifest : %r" % type(res))


def test_le_harness_est_local_et_ne_touche_pas_le_corps(integrity):
    """Garde-fou du NR : si l'on exercait le manager GLOBAL, on revoquerait
    pour de vrai des identites du corps."""
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    global_mgr = integrity.get_manager()
    assert mgr is not global_mgr, (
        "ce NR utiliserait le manager du corps : une revocation de test "
        "s'appliquerait aux identites reelles"
    )


def test_identite_ACTIVE_puis_REVOQUEE_sur_LE_MEME_jeton(integrity):
    """LE test du mandat. Une seule variable entre ALLOW et DENY."""
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    token = _jeton(_emettre(integrity, mgr, AGENT_A))

    ok_avant, _ = mgr.verify("fs", "read", token)
    assert ok_avant is True, "l'identite active doit etre autorisee"

    mgr.revoke(AGENT_A)                      # SEULE chose qui change

    ok_apres, _ = mgr.verify("fs", "read", token)
    assert ok_apres is False, (
        "le MEME jeton, le MEME scope et la MEME action passent encore apres "
        "revocation : la revocation d'identite ne produit aucun EFFET"
    )


def test_seule_l_identite_revoquee_est_touchee(integrity):
    """Isole la causalite dans l'autre sens : revoquer A ne doit pas fermer B.

    Sans ce test, un DENY global (manager casse, secret change) se lirait comme
    une revocation reussie.
    """
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    token_a = _jeton(_emettre(integrity, mgr, AGENT_A))
    token_b = _jeton(_emettre(integrity, mgr, AGENT_B))

    assert mgr.verify("fs", "read", token_a)[0] is True
    assert mgr.verify("fs", "read", token_b)[0] is True

    mgr.revoke(AGENT_A)

    assert mgr.verify("fs", "read", token_a)[0] is False, "A doit etre refuse"
    assert mgr.verify("fs", "read", token_b)[0] is True, (
        "B a ete refuse alors qu'il n'etait pas revoque : le DENY ne vient pas "
        "de la revocation mais d'autre chose"
    )


def test_la_revocation_se_DECLARE_et_ne_se_devine_pas(integrity):
    """`revoke_status` doit rendre l'etat : une revocation invisible ne peut
    etre ni auditee, ni levee, ni expliquee."""
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    _jeton(_emettre(integrity, mgr, AGENT_A))
    assert AGENT_A not in mgr.revoke_status()
    mgr.revoke(AGENT_A)
    statut = mgr.revoke_status()
    assert AGENT_A in statut
    assert isinstance(statut[AGENT_A], int)


def test_un_jeton_EMIS_APRES_la_revocation_repasse(integrity):
    """REVOQUER N'EST PAS BANNIR -- mais la barriere a une GRANULARITE, et elle
    est mesuree ici plutot qu'ignoree.

    `revoke` pose DEUX barrieres : un `min_seq` et une barriere TEMPORELLE
    `_revoked_after = time.time()`. `verify` refuse si `token.iat <= _apres`.

    LA BARRIERE EST A LA MICROSECONDE, ET C'EST MESURE (2026-09-21) :

        iat 1er jeton  = 1789956240.8469198   -> refuse
        _revoked_after = 1789956240.8470314
        iat 2e  jeton  = 1789956240.8470350   -> accepte (+4 us)

    CE QUE CE TEST AFFIRMAIT A TORT. Sa premiere version posait « comme `iat`
    est en SECONDES, un jeton emis dans la meme seconde est refuse » et
    exigeait donc `verify(...) is False` sur le jeton reemis. La premisse
    n'avait jamais ete mesuree : `iat` est un FLOTTANT microseconde. Le test se
    contredisait lui-meme -- son NOM dit « repasse », son assertion exigeait
    l'inverse -- et il echouait 200 fois sur 200, pas par intermittence.

    La propriete VRAIE, et c'est celle du titre : REVOQUER N'EST PAS BANNIR.
    Un jeton emis APRES la revocation repasse ; seuls tombent ceux emis AVANT.
    La barriere temporelle existe parce que `min_seq` seul ne revoquait rien
    quand `_seq_counter` n'avait pas suivi l'emission -- le cas de
    `login_agent` -- et non pour bannir l'agent.

    Le verrou ajoute ici porte sur la GRANULARITE : tronquer `iat` a la seconde
    rendrait la barriere aveugle a deux emissions de la meme seconde, ce qui
    est exactement le trou que je croyais avoir trouve. Le test le mesure
    desormais au lieu de le supposer.
    """
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    vieux = _jeton(_emettre(integrity, mgr, AGENT_A))
    mgr.revoke(AGENT_A)
    assert mgr.verify("fs", "read", vieux)[0] is False

    # LE MEME TICK D'HORLOGE EST UN CAS AMBIGU : ON L'INSTRUIT, ON NE L'ASSERTE
    # PAS. Sur Windows `time.time()` a une resolution de l'ordre de la
    # milliseconde. Quand `revoke()` et la reemission tombent dans le meme
    # tick, `iat == _revoked_after` et le `<=` refuse -- fail-closed, donc sur.
    # Sinon le jeton passe. Les DEUX sont corrects, et c'est l'ordonnanceur qui
    # tranche : asserter ici fait un NR non deterministe.
    #
    # Mesure du 2026-09-21 : ce test a fait echouer la CI du sha 261b9f80b, a
    # raison d'environ 1 run sur 5. Un NR qui echoue par intermittence sur un
    # invariant de securite est pire qu'un NR absent -- le jour ou il a raison,
    # on le croit flaky. Il a d'ailleurs fallu quatre hypotheses fausses avant
    # de LIRE la raison rendue par `verify`, qui la donnait mot pour mot :
    #     'Token révoqué : émis à 1789956534 ≤ révocation à 1789956534'
    immediat = _jeton(_emettre(integrity, mgr, AGENT_A))
    _ok_ambigu, _raison_ambigue = mgr.verify("fs", "read", immediat)
    assert isinstance(_ok_ambigu, bool), (
        "verify doit rendre un booleen meme dans le cas ambigu ; raison=%r"
        % (_raison_ambigue,)
    )

    # GRANULARITE : la barriere doit distinguer deux emissions separees de
    # quelques microsecondes. Tronquer `iat` a la seconde ouvrirait une fenetre
    # d'une seconde entiere ou un jeton reemis apres revocation passerait sans
    # que `min_seq` puisse le rattraper.
    barriere = mgr._revoked_after[AGENT_A]
    assert not float(barriere).is_integer(), (
        "la barriere de revocation est tombee a une precision d'une seconde : "
        "deux emissions de la meme seconde deviennent indiscernables"
    )
    _tok = integrity.CapabilityToken.decode(immediat, mgr._secret)
    assert not float(_tok.iat).is_integer(), (
        "`iat` est tronque a la seconde : la comparaison `iat <= barriere` "
        "perd la resolution dont elle depend"
    )

    # Une fois la seconde ecoulee, la re-habilitation redevient possible.
    mgr._revoked_after[AGENT_A] -= 2.0
    apres = _jeton(_emettre(integrity, mgr, AGENT_A))
    assert mgr.verify("fs", "read", apres)[0] is True, (
        "aucun jeton neuf ne repasse meme apres la barriere : la revocation "
        "est devenue un BANNISSEMENT, et une revocation qu'on ne peut pas "
        "lever est une revocation qu'on n'ose plus employer"
    )


# ------------------------------------------------ la limite, mesuree et dite

def test_la_revocation_NE_SURVIT_PAS_au_redemarrage(integrity):
    """Ce test ne celebre pas un defaut : il le MESURE pour qu'il cesse d'etre
    une supposition.

    `_revoked_seqs` vit en memoire. Un nouveau manager -- ce que produit tout
    redemarrage de process -- repart sans aucune revocation. Un jeton revoque
    AVANT le restart redevient donc valable APRES.

    C'est precisement le maillon qu'attend `test_agent_keys_ledger_nr`, laisse
    ROUGE a dessein : un ledger PERSISTANT agent_id -> key_id -> generation ->
    status. Tant qu'il n'existe pas, IDENTITY_REVOCATION est PROUVE en
    intra-process et NON ATTEINT a travers un redemarrage.
    """
    mgr = integrity.IntegrityManager(SECRET_DE_TEST)
    token = _jeton(_emettre(integrity, mgr, AGENT_A))
    mgr.revoke(AGENT_A)
    assert mgr.verify("fs", "read", token)[0] is False

    apres_restart = integrity.IntegrityManager(SECRET_DE_TEST)
    assert apres_restart.revoke_status() == {}, (
        "l'etat de revocation a survecu a un nouveau manager : la limite "
        "mesuree n'existe plus, ce test doit etre reecrit"
    )
    ok, _ = apres_restart.verify("fs", "read", token)
    assert ok is True, (
        "un jeton revoque reste refuse apres restart : tant mieux, mais alors "
        "la persistance existe et ce NR decrit une limite perimee"
    )
