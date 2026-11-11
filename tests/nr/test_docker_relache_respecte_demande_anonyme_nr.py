"""NR -- la relache de la DERNIERE reclamation nommee n'efface plus une demande ANONYME fraiche (10/11 soir).

Mesure : `nokido_ensure_service docker` a 16:22 (docker.wanted, TTL 900 s) ; Gordon reclame puis relache sa
reclamation nommee vers 16:23 ; release_claim, voyant la liste vide, efface docker.wanted et programme l'arret
(grace 180 s) -> 16:29 « Docker Desktop is not running » pour le canari suivant. Meme mecanique pour les
recherches ponctuelles : SearXNG tantot arrete, tantot fige, quatre veilles degradees le 10/11. Contrats :
  1. demande anonyme (ensure_docker direct) plus jeune que le TTL -> la relache garde docker.wanted, n'arrete rien ;
  2. demande anonyme perimee -> comportement anterieur (drapeau retire, arret programme) ;
  3. claim_docker n'est PAS une demande anonyme (sinon toute chaine se garderait elle-meme).
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_docker_keeper as K  # noqa: E402


def _isoler(monkeypatch, tmp_path):
    arrets = []
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(K, "_annuler_release_at", lambda *a, **k: None)
    monkeypatch.setattr(K, "_release_docker", lambda *a, **k: arrets.append("arret") or {"engine_verdict": "ARRETE"})
    monkeypatch.setattr(K, "_signaler_relache", lambda *a, **k: None)
    monkeypatch.setattr(K, "palier_courant", lambda: "normal")
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda: 0)
    monkeypatch.setattr(K, "_release_at_path", lambda: tmp_path / "docker.release_at")
    return arrets


def test_demande_anonyme_fraiche_survit_a_la_relache(monkeypatch, tmp_path):
    arrets = _isoler(monkeypatch, tmp_path)
    K.ensure_docker()                      # demande anonyme (hub, recherche, ensure_service)
    K.claim_docker("gordon")
    r = K.release_claim("gordon", immediat=True)
    assert K.WANT_FLAG.exists()
    assert arrets == [] and not (tmp_path / "docker.release_at").exists()
    assert "garde_anonyme" in r  # age en s, 0 pour une demande a l'instant


def test_demande_anonyme_perimee_relache_normale(monkeypatch, tmp_path):
    arrets = _isoler(monkeypatch, tmp_path)
    K.ensure_docker()
    vieux = time.time() - K.WANT_TTL_S - 5
    os.utime(K._anonyme_path(), (vieux, vieux))
    K.claim_docker("gordon")
    K.release_claim("gordon", immediat=True)
    assert not K.WANT_FLAG.exists()
    assert arrets == ["arret"]


def test_claim_n_est_pas_une_demande_anonyme(monkeypatch, tmp_path):
    arrets = _isoler(monkeypatch, tmp_path)
    K.claim_docker("veille_x")
    K.release_claim("veille_x", immediat=True)
    assert not K._anonyme_path().exists()
    assert arrets == ["arret"]
