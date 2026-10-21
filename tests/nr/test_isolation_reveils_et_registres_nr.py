"""NR -- AUCUN test ne reveille un organe reel ni n'ecrit dans un registre vivant (owner 19/10).

Mesure du 19/10 : deux fois dans l'apres-midi, Docker a ete reveille par un test de ma CI (crawl reel ->
forge_docker_agent.demander_crawl4ai -> crawl4ai.wanted + ensure_daemon) ; la 2e fois vmmemWSL a pris 3,15 Go et
la RAM est montee a 95,1 % pendant la CI. La provenance (acf8e4035) a montre en plus qu'un NR ecrivait dans le
VRAI signal_emissions.db. Meme patron que le sang endocrinien et la boite postale : l'isolation est cote HARNAIS,
autouse, sous les deux noms d'import.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
VIVANT = (RACINE / "sandbox").resolve()


def _sous_le_vivant(p) -> bool:
    """Vivant = DIRECTEMENT dans sandbox/ (la ou le keeper et les organes lisent) ; le bac de pytest vit plus bas."""
    try:
        return Path(p).resolve().parent == VIVANT
    except (TypeError, ValueError):
        return False


def test_les_drapeaux_docker_ne_visent_pas_le_vrai_sandbox():
    from nokido_agent.app import forge_docker_agent as da

    assert not _sous_le_vivant(da.WANT_FLAG)
    assert not _sous_le_vivant(da.CRAWL4AI_FLAG)


def test_ensure_daemon_pose_son_drapeau_hors_du_vivant():
    # la VRAIE logique tourne (des NR la testent) ; seul le drapeau est redirige : le keeper ne lit pas le bac.
    # RED observe le 19/10 : ce test a pose le vrai sandbox/docker.wanted (retire aussitot).
    from nokido_agent.app import forge_docker_agent as da

    r = da.ensure_daemon()
    assert r.get("flag") is None or not _sous_le_vivant(r["flag"]), r


def test_le_couplage_des_signaux_est_isole():
    for nom in ("forge_signal_coupling", "nokido_agent.app.forge_signal_coupling"):
        mod = __import__("importlib").import_module(nom)
        assert not _sous_le_vivant(mod.DB), (nom, mod.DB)


def test_le_registre_des_intentions_est_isole():
    from nokido_agent.app import forge_timecode as tc

    assert Path(tc.get_timecode_engine().db_path).resolve() != (RACINE / "RAG" / "embeddings.db").resolve()
