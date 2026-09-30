"""NR — « je ne peux pas verifier » n'est pas « le token est altéré ».

Mesure du 2026-09-02. `forge_persona_tpm.verify()` rendait `False` aussi bien
pour « la signature ne correspond pas » que pour « je n'ai pas pu ouvrir la
cle », et `CapabilityToken.decode` traduisait ce `False` en « Signature TPM
invalide (token altéré) ». Or la cle du TPM est une cle MACHINE : depuis un
compte de service, `sign()` rend None et `verify()` rend False pendant que le
HUB accepte le meme jeton (HTTP 200). Le jeton etait intact ; le verificateur
etait aveugle, et il accusait.

Le piege a coute un faux soupcon dans la session meme : le message a fait
croire que l'ajout de `cnf` cassait les jetons. La discrimination qui a
tranche : un jeton SANS lien echouait pareil, et le hub acceptait les deux.

Ces tests sont INDEPENDANTS DU COMPTE : sous le compte du hub la cle s'ouvre
et le verdict change, donc rien ici ne suppose un contexte particulier.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_integrity as fi  # noqa: E402
import forge_persona_tpm as tpm  # noqa: E402


def test_le_verdict_appartient_au_vocabulaire_declare():
    verdict, raison = tpm.verify_etat(b"temoin", b"signature-qui-ne-vaut-rien")
    assert verdict in tpm.VERDICTS, verdict
    assert isinstance(raison, str)


def test_une_signature_bidon_n_est_JAMAIS_valide():
    """Quel que soit le compte : une signature inventee ne passe pas."""
    assert tpm.verify_etat(b"temoin", b"bidon")[0] != "VALIDE"
    assert tpm.verify(b"temoin", b"bidon") is False


def test_verify_reste_booleen_pour_ses_appelants():
    """`login_agent` consomme encore le booleen : ne pas casser sa signature."""
    assert isinstance(tpm.verify(b"m", b"s"), bool)


def test_un_defaut_d_ACCES_ne_se_dit_pas_INVALIDE(monkeypatch):
    """Le coeur du defaut : cle non ouvrable -> INVERIFIABLE, jamais INVALIDE."""
    monkeypatch.setattr(tpm, "_open_key", lambda *a, **k: None)
    verdict, raison = tpm.verify_etat(b"temoin", b"peu importe")
    assert verdict == "INVERIFIABLE", (verdict, raison)
    assert "compte" in raison


def test_seul_le_code_windows_de_signature_dit_INVALIDE(monkeypatch):
    """Tout autre statut non nul est un probleme de contexte, pas une preuve
    d'altération. Confondre les deux, c'est accuser sans avoir constate."""
    class _NC:
        def NCryptVerifySignature(self, *a):
            return tpm.NTE_BAD_SIGNATURE

        def NCryptFreeObject(self, *a):
            return 0

    monkeypatch.setattr(tpm, "_ncrypt", lambda: (_NC(), None, None))
    monkeypatch.setattr(tpm, "_open_provider", lambda *a, **k: 1)
    monkeypatch.setattr(tpm, "_open_key", lambda *a, **k: 2)
    assert tpm.verify_etat(b"m", b"s")[0] == "INVALIDE"

    class _NCautre(_NC):
        def NCryptVerifySignature(self, *a):
            return 0x80090016  # NTE_BAD_KEYSET : contexte, pas signature

    monkeypatch.setattr(tpm, "_ncrypt", lambda: (_NCautre(), None, None))
    verdict, raison = tpm.verify_etat(b"m", b"s")
    assert verdict == "INVERIFIABLE", (verdict, raison)
    assert "0x80090016" in raison


SECRET_TEST = b"secret-de-test-hermetique"


def _jeton_a_segment_tpm() -> str:
    """Jeton a TROIS segments, sans dependre d'un TPM reel.

    Premiere ecriture de ces tests : ils appelaient `encode(tpm_sign=True)` et
    se SKIPPAIENT quand aucune signature materielle n'etait produite. Or ni ce
    compte ni la CI n'ont de cle TPM ouvrable -- les deux gardes les plus
    importants du fichier n'auraient donc JAMAIS tourne. Un garde toujours
    saute est un garde dormant, exactement le defaut que ce fichier documente.
    Le troisieme segment est donc forge ici : ce qu'on teste est le
    COMPORTEMENT DU VERIFICATEUR, pas la disponibilite du materiel.
    """
    import base64
    import time

    deux = fi.CapabilityToken(
        sub="ORGANE_TEST", ring=fi.IntegrityRing(3), scopes={},
        exp=time.time() + 600, iat=time.time(), jti="jti",
    ).encode(SECRET_TEST)
    faux = base64.urlsafe_b64encode(b"signature-materielle-de-test").decode().rstrip("=")
    return "%s.%s" % (deux, faux)


def test_decode_refuse_TOUJOURS_ce_qu_il_n_a_pas_pu_verifier(monkeypatch):
    """GARDE : la correction touche le DIAGNOSTIC, jamais la DECISION.

    Un message plus honnete ne doit pas devenir une porte : INVERIFIABLE
    refuse exactement comme avant.
    """
    monkeypatch.setattr(tpm, "tpm_available", lambda: True)
    monkeypatch.setattr(tpm, "verify_etat",
                        lambda p, s: ("INVERIFIABLE", "cle non ouvrable"))
    with pytest.raises(ValueError) as exc:
        fi.CapabilityToken.decode(_jeton_a_segment_tpm(), SECRET_TEST)
    message = str(exc.value)
    assert "INVERIFIABLE" in message
    assert "altéré" not in message, "le refus accuse encore le token"


def test_le_message_accuse_le_token_UNIQUEMENT_quand_c_est_constate(monkeypatch):
    monkeypatch.setattr(tpm, "tpm_available", lambda: True)
    monkeypatch.setattr(tpm, "verify_etat",
                        lambda p, s: ("INVALIDE", "ne correspond pas"))
    with pytest.raises(ValueError, match="altéré"):
        fi.CapabilityToken.decode(_jeton_a_segment_tpm(), SECRET_TEST)


def test_une_signature_TPM_VALIDE_laisse_passer(monkeypatch):
    """Sans ce cas, les deux tests ci-dessus passeraient meme si `decode`
    refusait TOUT : il faut prouver que le chemin acceptant existe encore."""
    monkeypatch.setattr(tpm, "tpm_available", lambda: True)
    monkeypatch.setattr(tpm, "verify_etat", lambda p, s: ("VALIDE", ""))
    t = fi.CapabilityToken.decode(_jeton_a_segment_tpm(), SECRET_TEST)
    assert t.sub == "ORGANE_TEST"
