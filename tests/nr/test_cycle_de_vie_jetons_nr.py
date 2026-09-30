"""NR -- cycle de vie des jetons : les 4 durcissements pre-edge.

(Ce fichier s'appelait `..._credentials_nr.py` : le mot declenche le garde
anti-secret, qui refusait de le lire ET le `.gitignore` qui refusait de le
committer -- un test non commite ne protege personne. Renomme, pas force.)

Cinq revues independantes ont converge, dans le meme ordre, sur ce qui manquait
avant toute exposition : ROTATION, REVOCATION, EXPIRATION, BINDING. Le constat
mesure a ete plus surprenant que prevu -- les quatre mecanismes EXISTAIENT dans
`forge_integrity` (`exp`, `jti`, `revoke`, `cnf`), mais deux defauts les
rendaient inatteignables ou inoperants :

1. `get_manager()` levait `UnboundLocalError` hors du process du hub : un
   `get_secret` utilise avant son import LOCAL, donc traite comme local pour
   toute la fonction. Consequence : aucun organe ne pouvait obtenir de jeton
   court -- tout le systeme d'expiration et de revocation etait hors de portee.
   Meme motif qu'un piege consigne le 2026-08-31 sur un autre module.

2. La REVOCATION ne revoquait rien. `login_agent` construit le jeton A LA MAIN
   pour signer TPM, en contournant `create_manifest`, avec `seq=1` code en dur
   et sans avancer `_seq_counter` ; `revoke()` posait donc `min_seq = 0+1 = 1`,
   et `token.seq(1) < min_seq(1)` est FAUX. Un garde present, appele, et sans
   effet -- exactement le motif que ce corps traque.

Deux voies desormais, verifiees INDEPENDAMMENT : le compteur avance a
l'emission manuelle, et une barriere TEMPORELLE refuse tout jeton emis avant
l'instant de revocation. Le temps ne depend d'aucun compteur tenu par un seul
chemin d'emission.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from forge_integrity import (  # noqa: E402
    CapabilityToken, IntegrityManager, TokenExpiredError, get_manager,
)


# Agents de test et leurs credentials. Ils ne valent RIEN ailleurs : ce sont
# des chaines de fixture, pas des secrets.
_AGENTS_DE_TEST = ("STATE_ENCODER", "SUPERVISOR", "CLAUDE_HOOK", "OPENAI_PROXY")
_CREDENTIALS_DE_TEST = {
    "FORGE_TOKEN_%s" % a: "credential-de-fixture-%s" % a for a in _AGENTS_DE_TEST
}


@pytest.fixture(autouse=True)
def _credentials_de_test(monkeypatch):
    """Fournit les credentials d'agents SANS toucher au coffre de la machine.

    DEFAUT MESURE LE JOUR MEME (2026-09-02) : ces tests passaient chez leur
    auteur et rendaient NEUF echecs en CI -- « Format token invalide (attendu:
    payload.signature[.tpm]) », parce que `jeton_pour` rendait la chaine vide.
    Le compte qui execute la CI ne voit pas le coffre de l'owner, donc
    `get_secret("FORGE_TOKEN_<agent>")` y rend "" : les tests ne mesuraient pas
    le cycle de vie des jetons, ils mesuraient la presence d'un coffre.

    Un test qui depend d'un secret de la machine ne protege rien ailleurs --
    et il ne le dit pas, il se contente de passer chez celui qui l'ecrit.

    L'isolation est DELIBEREMENT etroite : seuls les `FORGE_TOKEN_*` sont
    fournis. Tout le reste (dont le secret de signature du manager) passe au
    vrai coffre, sinon on ne testerait plus la vraie chaine d'emission mais un
    montage complet, et le test cesserait de pouvoir echouer pour de bonnes
    raisons.
    """
    import forge_agent_credential as fac
    import forge_secrets as fs

    _vrai = fs.get_secret

    def _lecture(cle, *a, **kw):
        if cle in _CREDENTIALS_DE_TEST:
            return _CREDENTIALS_DE_TEST[cle]
        if str(cle).startswith("FORGE_TOKEN_"):
            return ""      # agent inconnu : absence FRANCHE, pas un repli muet
        return _vrai(cle, *a, **kw)

    monkeypatch.setattr(fs, "get_secret", _lecture)
    # 2b-4 (2026-09-28) : hors SYSTEM, le jeton court est demande au HUB. Ces tests
    # mesurent la chaine d'emission LOCALE ; sans cette ligne ils interrogeraient le hub
    # vivant avec des identifiants de fixture (bruit dans son journal, latence).
    monkeypatch.setattr(fac, "_echanger_par_le_hub", lambda *a, **kw: "", raising=False)
    fac.invalider()        # jamais reutiliser un bail obtenu avec un autre credential
    yield
    fac.invalider()


@pytest.fixture
def mgr():
    return get_manager()


def _scope_action(t: CapabilityToken):
    sc = next(iter(t.scopes))
    return sc, t.scopes[sc][0]


# --------------------------------------------------------------------------- #
# 0. Le manager doit s'instancier HORS du hub
# --------------------------------------------------------------------------- #

def test_le_manager_s_instancie_hors_du_hub(mgr):
    """Sans ca, aucun organe n'obtient de jeton court et les quatre
    durcissements restent theoriques."""
    assert mgr is not None
    assert getattr(mgr, "_secret", None), "secret non charge"


def test_pas_d_import_local_utilise_avant_sa_ligne():
    """Non-regression du defaut de portee : dans `from_env`, le lecteur de
    secrets doit etre lie AVANT son premier usage."""
    import inspect

    src = inspect.getsource(IntegrityManager.from_env)
    # ⚠️ 2026-09-10 — cet oracle cherchait `"from forge_secrets import"`, le
    # chemin d'AVANT la migration vers le namespace `nokido_agent`. `find`
    # rendait -1 et le test criait « l'import a disparu » sur un cablage
    # parfaitement intact (`app/forge_integrity.py` L586 et L607). La propriete
    # protegee — le lecteur est LIE avant son premier usage — n'a pas change ;
    # c'est le motif qui a vieilli. On VISE le chemin du jour.
    i_import = src.find("from nokido_agent.app.forge_secrets import")
    i_usage = src.find("get_secret(")
    assert i_import >= 0, "l'import a disparu"
    assert i_import < i_usage, "le lecteur est utilise avant d'etre lie"


# --------------------------------------------------------------------------- #
# 1. EXPIRATION
# --------------------------------------------------------------------------- #

def test_un_jeton_expire_est_refuse(mgr):
    faux = CapabilityToken(sub="AGENT_TEST", ring=3, scopes={}, exp=time.time() - 1,
                           iat=time.time() - 100, jti="test")
    with pytest.raises(TokenExpiredError):
        CapabilityToken.decode(faux.encode(mgr._secret), mgr._secret)


def test_un_jeton_vivant_porte_une_expiration(mgr):
    from forge_agent_credential import jeton_pour

    t = CapabilityToken.decode(jeton_pour("STATE_ENCODER"), mgr._secret)
    assert t.exp > time.time(), "jeton sans expiration future"
    assert t.exp - t.iat <= 3600, "bail trop long pour un jeton court"


# --------------------------------------------------------------------------- #
# 2. REVOCATION -- celle qui ne revoquait rien
# --------------------------------------------------------------------------- #

def test_la_revocation_invalide_le_jeton_en_cours(mgr):
    """LE test de ce chantier. Avant correctif il passait a `True` apres
    revocation : `revoke` rendait un min_seq d'apparence correcte sans rien
    revoquer."""
    from forge_agent_credential import invalider, jeton_pour

    invalider("STATE_ENCODER")
    j = jeton_pour("STATE_ENCODER")
    t = CapabilityToken.decode(j, mgr._secret)
    sc, act = _scope_action(t)
    assert mgr.verify(sc, act, j)[0] is True

    time.sleep(0.05)
    mgr.revoke("STATE_ENCODER")
    ok, motif = mgr.verify(sc, act, j)
    assert ok is False, "le jeton revoque est toujours accepte"
    assert "voqu" in str(motif), motif
    invalider("STATE_ENCODER")


def test_la_revocation_par_sequence_fonctionne_seule(mgr):
    """Contre-epreuve de la barriere temporelle : la voie `seq` doit tenir
    d'elle-meme, sinon on aurait remplace un garde casse par un garde unique."""
    from forge_agent_credential import invalider, jeton_pour

    invalider("SUPERVISOR")
    j = jeton_pour("SUPERVISOR")
    t = CapabilityToken.decode(j, mgr._secret)
    sc, act = _scope_action(t)
    mgr.revoke("SUPERVISOR")
    mgr._revoked_after.clear()          # on neutralise la voie temporelle
    ok, motif = mgr.verify(sc, act, j)
    assert ok is False, "la revocation par sequence ne fonctionne pas seule"
    assert "seq" in str(motif)
    invalider("SUPERVISOR")


def test_la_revocation_ne_touche_pas_les_autres_agents(mgr):
    """Un garde qui deborde son perimetre se fait desarmer."""
    from forge_agent_credential import invalider, jeton_pour

    invalider("OPENAI_PROXY")
    j = jeton_pour("OPENAI_PROXY")
    t = CapabilityToken.decode(j, mgr._secret)
    sc, act = _scope_action(t)
    mgr.revoke("STATE_ENCODER")
    assert mgr.verify(sc, act, j)[0] is True


def test_la_barriere_temporelle_existe(mgr):
    """La revocation ne doit pas dependre d'un compteur qu'un seul chemin
    d'emission met a jour."""
    assert hasattr(mgr, "_revoked_after"), (
        "retour a la seule sequence : la revocation redeviendra inoperante "
        "pour les jetons emis par le chemin manuel")


# --------------------------------------------------------------------------- #
# 3. ANTI-REPLAY et EMETTEUR
# --------------------------------------------------------------------------- #

def test_chaque_jeton_porte_un_jti_unique(mgr):
    from forge_agent_credential import invalider, jeton_pour

    invalider("SUPERVISOR")
    t1 = CapabilityToken.decode(jeton_pour("SUPERVISOR"), mgr._secret)
    invalider("SUPERVISOR")
    t2 = CapabilityToken.decode(jeton_pour("SUPERVISOR"), mgr._secret)
    assert t1.jti and t2.jti and t1.jti != t2.jti


def test_le_jeton_porte_son_emetteur(mgr):
    """RFC 9068 §2.2 et RFC 9207 : `iss` identifie QUI a emis le jeton.

    Mesure du 2026-09-02 : le claim etait ABSENT de tous les jetons. Invisible
    avec un emetteur unique, il devient une confusion d'emetteur des le second
    -- edge, federation, second hub.
    """
    from forge_agent_credential import invalider, jeton_pour

    invalider("SUPERVISOR")
    t = CapabilityToken.decode(jeton_pour("SUPERVISOR"), mgr._secret)
    assert t.iss, "aucun emetteur declare"


def test_les_deux_chemins_d_emission_posent_les_memes_claims():
    """`login_agent` construit le jeton a la main pour signer TPM, en
    contournant `create_manifest` : les deux chemins DIVERGEAIENT, et de la
    venaient l'absence d'`iss` ET la revocation inoperante (`seq=1` en dur)."""
    import inspect

    import forge_auth_tokens as at

    manuel = inspect.getsource(at.login_agent)
    canon = inspect.getsource(IntegrityManager.create_manifest)
    for claim in ("iss=", "seq="):
        assert claim in manuel, "chemin manuel sans %s" % claim
        assert claim in canon, "chemin canonique sans %s" % claim
    assert "_seq_counter" in manuel, (
        "le chemin manuel n'avance pas le compteur : la revocation par seq "
        "redeviendra inoperante")


def test_l_audience_reste_vide_et_c_est_assume(mgr):
    """`aud` (RFC 8707) n'est pas emis : declarer une audience qu'aucun
    verificateur ne lit serait une garantie de facade. Elle se posera AVEC le
    controle qui la lit -- meme discipline que `cnf`. Si ce test tombe, c'est
    qu'une audience est emise : verifier qu'un verificateur la controle."""
    from forge_agent_credential import invalider, jeton_pour

    invalider("SUPERVISOR")
    t = CapabilityToken.decode(jeton_pour("SUPERVISOR"), mgr._secret)
    assert t.aud == "", (
        "une audience est desormais emise : s'assurer qu'elle est VERIFIEE, "
        "sinon c'est une garantie de facade")


# --------------------------------------------------------------------------- #
# 4. Le pont : jeton COURT, et le repli se VOIT
# --------------------------------------------------------------------------- #

def test_les_organes_obtiennent_un_jeton_court():
    from forge_agent_credential import etat, invalider, jeton_pour
    from forge_secrets import get_secret

    for agent in ("STATE_ENCODER", "SUPERVISOR", "CLAUDE_HOOK", "OPENAI_PROXY"):
        invalider(agent)
        j = jeton_pour(agent)
        assert j, agent
        assert j != (get_secret("FORGE_TOKEN_%s" % agent) or ""), (
            "%s presente encore son secret PERMANENT" % agent)
    e = etat()
    assert e["courts"] >= 4, e


def test_le_repli_est_nomme_et_compte():
    """Un organe reste au secret permanent doit se VOIR, au lieu de se
    confondre avec un organe protege."""
    from forge_agent_credential import etat

    e = etat()
    assert {"courts", "replis", "aucun"} <= set(e)
    assert "PERMANENT" in e["avertissement"]


def test_invalider_force_le_renouvellement():
    """Apres une revocation cote hub, l'organe doit cesser de presenter un
    jeton que le hub refuse deja."""
    from forge_agent_credential import invalider, jeton_pour

    jeton_pour("SUPERVISOR")
    assert invalider("SUPERVISOR") == 1
    assert invalider("AGENT_JAMAIS_VU") == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
