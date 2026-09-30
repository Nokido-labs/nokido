"""Le tri factice/reel decide si l'alerte est credible.

Deux echecs possibles, aux couts opposes :
  - crier sur des placeholders -> le garde se fait desarmer (mesure : 6 findings
    `github_pat` de la membrane, tous la MEME chaine d'exemple) ;
  - rater un vrai jeton -> il part en public, definitivement.

NOTE : les echantillons sont ASSEMBLES a l'execution, jamais ecrits en clair.
Le scan secret de `governed_edit` a (a juste titre) refuse une premiere version
de ce fichier qui contenait un faux jeton litteral : un garde qui laisserait
passer un motif de secret dans un test ne protegerait plus rien ailleurs.
"""

import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_history_secret_audit as fhs  # noqa: E402

_PREFIXE_GOOGLE = b"AI" + b"za"
_ENTETE_CLE = b"-----BEGIN " + b"RSA " + b"PRIVATE " + b"KEY-----"


def _corps_haute_entropie(n=35):
    """Engendre une chaine dense SANS l'ecrire en clair.

    Une premiere version portait un litteral : le gate egress l'a signale en
    YELLOW (« token haute entropie »). Un faux positif fige dans un depot destine
    a devenir public use les scans suivants -- on genere, on n'inscrit pas.
    """
    alpha = string.ascii_letters + string.digits
    return bytes("".join(alpha[(i * 7 + 3) % len(alpha)] for i in range(n)), "ascii")


def test_placeholder_lexical_est_ecarte():
    assert fhs._est_factice(b"ghp_DEMO_FACTICE_redacted_non_reel_" + b"a" * 12)


def test_chaine_a_faible_entropie_est_ecartee():
    """Un exemple ecrit a la main se repete ; un secret genere non."""
    assert fhs._est_factice(b"ghp_" + b"abc" * 12)


def test_jeton_a_forte_entropie_est_retenu():
    """Sur le doute on RETIENT : rater un secret coute plus cher qu'instruire."""
    assert not fhs._est_factice(_PREFIXE_GOOGLE + _corps_haute_entropie())


def test_motif_cle_privee_sans_groupe_capturant():
    """Regression 2026-08-29 : un groupe CAPTURANT faisait rendre « RSA » a
    `re.findall` au lieu du match, et le classificateur d'entropie prenait alors
    une vraie cle privee pour un placeholder. Rate silencieux, cote cher."""
    trouve = re.findall(fhs.MOTIFS["cle_privee"], _ENTETE_CLE)
    assert trouve == [_ENTETE_CLE], "findall doit rendre le MATCH, pas un groupe"


def test_entropie_croit_avec_le_desordre():
    assert fhs._entropie(b"aaaaaaaa") < fhs._entropie(b"a1B2c3D4")


def test_les_refs_publiables_incluent_alpha_et_beta():
    """Un secret n'est « expose » que s'il est atteignable depuis ce qu'on publie.
    Mesure : le blob compromettant vit dans l'histoire d'alpha ET de beta, ce qui
    invalide l'option « mirror = alpha + beta seules »."""
    assert any("alpha" in r for r in fhs.REFS_PUBLIABLES)
    assert any("beta" in r for r in fhs.REFS_PUBLIABLES)


def test_chemins_sensibles_non_vide():
    """Une liste vide rendrait un PROPRE de complaisance."""
    assert fhs.CHEMINS_SENSIBLES


def test_le_lanceur_depose_son_rapport_et_rend_le_verdict(monkeypatch, tmp_path):
    """Le balayage exhaustif depasse le cap de 120 s d'un appel d'outil : il
    tourne en `run_job`, donc son rapport doit ATTERRIR sur disque -- sinon le
    resultat meurt avec le process detache. On simule l'audit : ce qui est
    verrouille ici, c'est le depot du rapport et le code de retour."""
    import forge_history_scan_job as job

    faux = {"verdict": "EXPOSE", "exposes_si_publication": 1, "findings": [],
            "blobs_lus": 3, "blobs_non_inspectes": 0}
    monkeypatch.setattr(job, "audit_exhaustif", lambda: dict(faux))
    monkeypatch.setattr(job, "SORTIE", tmp_path / "history_scan.json")

    assert job.main() == 1, "un verdict EXPOSE doit rendre un code non nul"
    ecrit = json.loads((tmp_path / "history_scan.json").read_text(encoding="utf-8"))
    assert ecrit["verdict"] == "EXPOSE"
    assert "duree_s" in ecrit and "horodatage" in ecrit


def test_le_lanceur_ne_porte_aucune_logique_d_audit():
    """Un lanceur pointe le DEPOT : s'il reimplemente l'audit, les deux versions
    divergent et c'est la copie qui tourne."""
    src = (ROOT / "tools" / "forge_history_scan_job.py").read_text(encoding="utf-8")
    assert "audit_exhaustif" in src
    assert "MOTIFS" not in src and "entropie" not in src
