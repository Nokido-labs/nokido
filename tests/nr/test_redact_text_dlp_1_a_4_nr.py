"""NR 29/10 soir -- constats DLP-1 a DLP-4 du registre d'audit (banc redaction_dlp, F1 0,87) sur
forge_semantic_firewall.redact_text. Valeurs sensibles FABRIQUEES a l'execution (aucun secret dans ce fichier).
DLP-1 identifiant d'acces AK..IA en clair ; DLP-2 mot de passe en JSON en clair ; DLP-3 au-dela de 5 000 caviardages
le reste partait en clair (contournement par remplissage) ; DLP-4 texte tronque en silence a 256 Ko."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

import forge_semantic_firewall as F  # noqa: E402


def _fab(graine, n, alphabet):
    h = hashlib.sha256(graine.encode()).hexdigest() * 4
    return "".join(alphabet[int(h[i:i + 2], 16) % len(alphabet)] for i in range(0, 2 * n, 2))


MAJ_CHIFFRES = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def test_dlp1_identifiant_akia_caviarde():
    cle = "AK" + "IA" + _fab("akia", 16, MAJ_CHIFFRES)
    rendu, _m = F.redact_text("export ACCESS_KEY_ID=%s avant le deploiement" % cle)
    assert cle not in rendu and "deploiement" in rendu


def test_dlp1_identifiant_akia_nu_caviarde():
    cle = "AK" + "IA" + _fab("akia-nu", 16, MAJ_CHIFFRES)
    rendu, _m = F.redact_text("trace : %s fin" % cle)
    assert cle not in rendu


def test_dlp2_mot_de_passe_json_caviarde():
    mdp = _fab("mdp", 14, ALNUM) + "!"
    rendu, _m = F.redact_text('{"user": "admin", "password": "%s"}' % mdp)
    assert mdp not in rendu and "admin" in rendu


def test_dlp3_le_remplissage_ne_fait_pas_passer_un_secret():
    # Le remplissage DOIT viser un motif parcouru AVANT celui des secrets (les IP internes sont le premier) : des emails,
    # parcourus apres, laissaient le secret se faire caviarder avant l'epuisement du quota -- test vert a tort (29/10).
    remplissage = " ".join("192.168.%d.%d" % (i // 250, i % 250 + 1) for i in range(F._MAX_REDACTIONS + 10))
    secret = "sk-" + _fab("dlp3", 40, ALNUM)
    rendu, _m = F.redact_text(remplissage + " puis " + secret)
    assert secret not in rendu


def test_dlp4_texte_long_ni_tronque_ni_fuyant():
    secret = "sk-" + _fab("dlp4", 40, ALNUM)
    texte = ("ligne ordinaire sans donnee sensible\n" * 9000) + "fin " + secret + " MARQUEUR_DE_FIN"
    assert len(texte) > F._MAX_REDACT_LEN
    rendu, _m = F.redact_text(texte)
    assert "MARQUEUR_DE_FIN" in rendu and secret not in rendu
