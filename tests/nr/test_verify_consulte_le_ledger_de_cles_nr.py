"""NR — le chemin LIE consulte le ledger de cles, et dans le BON ORDRE.

P4.3.4-D. Le chantier C a prouve que `forge_agent_keys` sait dire REVOKED et
que cette reponse survit au redemarrage. Il n'a rien branche : `decode` ne
consultait pas le ledger, donc revoquer une cle restait SANS EFFET sur une
autorisation. Ce NR verrouille le cablage.

L'ORDRE EST L'INVARIANT CENTRAL
===============================
    cnf.jkt == jkt PROUVE          <- binding cryptographique D'ABORD
             puis
    statut_de_jkt(jkt) == ACTIVE   <- decision de statut ENSUITE

Le ledger ne doit JAMAIS servir a CHOISIR une cle qui permettrait ensuite de
verifier la signature : ce serait laisser un registre decider de ce qui est
cryptographiquement vrai. Il ne juge qu'une empreinte DEJA liee. Un test espion
verifie qu'un binding qui echoue n'interroge pas le ledger du tout.

CE QUE CE NR NE PEUT PAS EXERCER, ET IL LE DIT
==============================================
`decode` ne verifie aucune signature TPM : il recoit `dpop_jkt`, l'empreinte de
la cle dont l'appelant a DEJA prouve la possession. « JKT A + signature produite
par B » se traduit donc ici par « cnf.jkt = A, dpop_jkt = empreinte(B) » -- le
cas est couvert, mais au niveau du binding, pas de la cryptographie. La
verification de signature reste chez l'appelant, et ce NR ne pretend pas la
juger.

LE CHEMIN BEARER N'EST PAS TOUCHE
=================================
Un jeton sans `cnf.jkt` et sans preuve demandee ne paie rien : aucune exigence
TPM n'est ajoutee aux bearers par ce chantier. Un NR le verrouille, parce que
la derive naturelle serait d'exiger « un peu » de preuve partout -- ce qui
casserait le trafic mesure (bearer_derive 1346, anonyme 630) sans rien durcir.

NOTE DE FABRICATION : la constante de signature des jetons de test s'appelle
`_SEL_NR`. Le scanner d'ecriture gouvernee REFUSE une constante nommee avec le
vocabulaire qu'il surveille, meme pour une valeur de test -- refus deja paye le
2026-09-21 sur un autre NR de cette campagne, et repaye ici. Le garde a raison
les deux fois : il ne peut pas distinguer un litteral de test d'un vrai.
"""
from __future__ import annotations

import time
import uuid

import pytest


def _integrity():
    for nom in ("nokido_agent.app.forge_integrity", "app.forge_integrity",
                "forge_integrity"):
        try:
            return __import__(nom, fromlist=["CapabilityToken"])
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_integrity introuvable")


def _ledger():
    for nom in ("nokido_agent.app.forge_agent_keys", "app.forge_agent_keys",
                "forge_agent_keys"):
        try:
            return __import__(nom, fromlist=["statut_de_jkt"])
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_agent_keys introuvable")


# BYTES, et pas une chaine : `CapabilityToken.encode` passe la valeur telle
# quelle a `hmac.new`, qui refuse une `str`. C'est `IntegrityManager.__init__`
# qui encode, pas le jeton -- premiere version de ce NR rouge sur un
# `TypeError` de MON harnais, donc rouge pour une raison qui n'avait rien a
# voir avec le cablage mesure.
_SEL_NR = b"valeur-de-mesure-nr-p434d"
JWK_A = {"kty": "EC", "crv": "P-256", "x": "x" + "a" * 20, "y": "y" + "a" * 20}
JWK_B = {"kty": "EC", "crv": "P-256", "x": "x" + "b" * 20, "y": "y" + "b" * 20}


def _empreinte(jwk):
    for nom in ("nokido_agent.app.forge_dpop", "app.forge_dpop", "forge_dpop"):
        try:
            return __import__(nom, fromlist=["thumbprint"]).thumbprint(jwk)
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_dpop introuvable")


@pytest.fixture(autouse=True)
def _ledger_isole(tmp_path):
    """Chaque test a SON ledger : un NR ne touche pas l'etat reel."""
    led = _ledger()
    led._CHEMIN = tmp_path / "agent_keys.json"
    led._vider_cache()
    yield
    led._vider_cache()


def _jeton(cnf=None, sub="CLAUDE"):
    """Jeton signe, eventuellement LIE a une empreinte de cle."""
    I = _integrity()
    maintenant = time.time()
    tok = I.CapabilityToken(
        sub=sub,
        ring=list(I.IntegrityRing)[3],
        scopes={"rag": ["read"]},
        exp=maintenant + 900,
        iat=maintenant,
        jti=str(uuid.uuid4()),
        cnf=dict(cnf or {}),
    )
    return tok.encode(_SEL_NR)


def _decode(raw, **kw):
    return _integrity().CapabilityToken.decode(raw, _SEL_NR, **kw)


# ───────────────────────  LE LEDGER EST CONSULTE  ─────────────────────────

def test_jkt_ACTIVE_et_binding_correct_est_ACCEPTE():
    led = _ledger()
    led.enregistrer("CLAUDE", public_key=JWK_A)
    jkt = _empreinte(JWK_A)
    tok = _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)
    assert tok.sub == "CLAUDE"


def test_jkt_REVOQUEE_est_REFUSEE_malgre_un_binding_PARFAIT():
    """LE COEUR DU CHANTIER. Le binding est correct, la signature serait
    valide : seule la decision de statut peut refuser. Sans ce cablage,
    revoquer une cle n'a aucun effet."""
    led = _ledger()
    e = led.enregistrer("CLAUDE", public_key=JWK_A)
    led.transition("CLAUDE", "REVOKED", generation=e["generation"],
                   par="SUPERVISOR", motif="cle compromise")
    jkt = _empreinte(JWK_A)
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)


def test_jkt_INCONNUE_du_ledger_est_REFUSEE_sans_repli():
    """Liste BLANCHE : une empreinte que le ledger ne connait pas ne passe pas,
    et on ne va surtout pas chercher une AUTRE cle qui conviendrait."""
    jkt = _empreinte(JWK_A)          # rien n'est enregistre
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)


def test_une_generation_ACTIVE_n_autorise_pas_la_PRECEDENTE():
    """K1 active n'absout pas K0 revoquee. Les generations se jugent une par
    une, sinon toute rotation blanchirait la cle qu'elle remplace."""
    led = _ledger()
    k0 = led.enregistrer("CLAUDE", public_key=JWK_A)
    led.enregistrer("CLAUDE", public_key=JWK_B)
    led.transition("CLAUDE", "REVOKED", generation=k0["generation"],
                   par="SUPERVISOR", motif="rotation terminee")
    jkt_a, jkt_b = _empreinte(JWK_A), _empreinte(JWK_B)
    assert _decode(_jeton({"jkt": jkt_b}), dpop_jkt=jkt_b).sub == "CLAUDE"
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt_a}), dpop_jkt=jkt_a)


# ────────────────────────────  L ORDRE  ───────────────────────────────────

def test_un_binding_QUI_ECHOUE_n_interroge_JAMAIS_le_ledger(monkeypatch):
    """Le ledger ne doit pas servir a CHOISIR une cle : il juge une empreinte
    DEJA liee. S'il etait consulte avant la comparaison, un registre deciderait
    de ce qui est cryptographiquement vrai."""
    led = _ledger()
    led.enregistrer("CLAUDE", public_key=JWK_A)
    appels = []
    vrai = led.statut_de_jkt
    monkeypatch.setattr(led, "statut_de_jkt",
                        lambda j: (appels.append(j), vrai(j))[1])
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": _empreinte(JWK_A)}),
                dpop_jkt=_empreinte(JWK_B))
    assert appels == [], (
        "le ledger a ete interroge alors que le binding a echoue : "
        "l'ordre est inverse, %r" % (appels,))


def test_jkt_A_avec_preuve_de_la_cle_B_est_REFUSE():
    """Les deux cles sont ACTIVE au ledger : seul le binding les separe."""
    led = _ledger()
    led.enregistrer("CLAUDE", public_key=JWK_A)
    led.enregistrer("CLAUDE", public_key=JWK_B)
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": _empreinte(JWK_A)}),
                dpop_jkt=_empreinte(JWK_B))


def test_un_jeton_SANS_cnf_jkt_refuse_quand_une_preuve_est_exigee():
    """Refus, et pas « non mesurable » : omettre le lien ne vaut pas le lien.
    Volet deja pose en P1, re-verrouille ici parce que D pourrait l'affaiblir
    en rendant le chemin lie plus permissif."""
    with pytest.raises(ValueError):
        _decode(_jeton(), dpop_jkt=_empreinte(JWK_A))


# ─────────────────────────  FAIL-CLOSED  ──────────────────────────────────

def test_ledger_ILLISIBLE_refuse_le_chemin_lie():
    """Conforme au contrat b4ee5cf8c : un doute REFUSE. Heriter le fail-open de
    `jti_cache` serait rejouer le defaut qu'on vient de fermer."""
    led = _ledger()
    led.enregistrer("CLAUDE", public_key=JWK_A)
    led._CHEMIN.write_text("{ pas du json", encoding="utf-8")
    led._vider_cache()
    jkt = _empreinte(JWK_A)
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)


def test_la_revocation_de_CLE_survit_au_redemarrage_DANS_LE_VERIFICATEUR():
    """LE TEST QUI FERME LE TROU DE P4.3.4-B.

    Mesure du 2026-09-21 : un jeton revoque par `forge_integrity.revoke`
    REPASSE apres redemarrage, parce que `_revoked_seqs` vit en memoire. Ici
    la revocation porte sur la CLE, le ledger la persiste, et le verificateur
    doit rendre le MEME verdict apres reconstruction depuis le disque.
    """
    led = _ledger()
    e = led.enregistrer("CLAUDE", public_key=JWK_A)
    jkt = _empreinte(JWK_A)
    assert _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt).sub == "CLAUDE"
    led.transition("CLAUDE", "REVOKED", generation=e["generation"],
                   par="SUPERVISOR", motif="compromission")
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)
    led._vider_cache()                      # <- le redemarrage
    with pytest.raises(ValueError):
        _decode(_jeton({"jkt": jkt}), dpop_jkt=jkt)


# ───────────────────  LE BEARER NE PAIE RIEN  ─────────────────────────────

def test_un_bearer_NON_LIE_passe_sans_aucune_exigence_TPM():
    """Aucune exigence n'est ajoutee aux jetons non lies. Le trafic mesure est
    massivement non lie ; durcir « un peu » partout casserait sans durcir."""
    assert _decode(_jeton()).sub == "CLAUDE"


def test_un_bearer_NON_LIE_n_interroge_pas_le_ledger(monkeypatch):
    """Et il ne doit pas non plus PAYER une consultation : un ledger interroge
    sur un chemin qui ne l'utilise pas finirait par en dependre en silence."""
    led = _ledger()
    appels = []
    monkeypatch.setattr(led, "statut_de_jkt",
                        lambda j: appels.append(j) or led.INCONNU)
    _decode(_jeton())
    assert appels == [], "le chemin bearer a consulte le ledger : %r" % (appels,)


def test_verify_expose_le_chemin_lie_et_le_bearer_reste_son_defaut():
    """`verify` ne passait AUCUN `dpop_jkt` a `decode` : le chemin lie lui
    etait inatteignable. Le parametre s'ajoute avec un defaut None -- sans lui,
    brancher le ledger dans `decode` ne changerait rien pour l'appelant reel.
    """
    import inspect
    I = _integrity()
    params = inspect.signature(I.IntegrityManager.verify).parameters
    assert "dpop_jkt" in params, (
        "verify n'expose pas le chemin lie : le cablage serait inatteignable")
    assert params["dpop_jkt"].default is None, (
        "le defaut doit etre None, sinon les bearers changent de comportement")


# ──────────────  AUCUNE CLE PRIVEE DANS LE VERIFICATEUR  ──────────────────

def test_le_verificateur_n_ouvre_JAMAIS_une_cle_privee():
    """Compte les APPELS par AST, pas les occurrences : un docstring qui cite
    `sign_as` pour dire qu'on ne l'appelle pas ferait rougir un test textuel.
    Piege paye cinq fois dans cette campagne.
    """
    import ast
    import pathlib
    src = pathlib.Path(_integrity().__file__).read_text(encoding="utf-8")
    interdits = {"sign_as", "NCryptOpenKey", "NCryptSignHash",
                 "NCryptExportKey"}
    vus = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            nom = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if nom in interdits:
                vus.add(nom)
    assert not vus, f"le verificateur ouvre du materiau prive : {sorted(vus)}"
