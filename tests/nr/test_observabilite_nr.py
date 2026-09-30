"""NR — le garde des pouls et la boite noire du hub.

Ces deux modules ont ete ecrits le 2026-08-14 et signales SANS TEST par le
cliquet de couverture, qui a donc fait exactement son office sur son auteur.

Les cas testes sont ceux qui ont failli passer inapercus le jour meme :
  * juger un pouls sur un seuil unique — `rss_watcher` bat toutes les 6 h et
    un seuil de 300 s l'aurait declare mort ;
  * confondre « pas de mesure » avec « en bonne sante » — un heartbeat sans
    periode declaree est INJUGEABLE, pas vivant ;
  * confondre « process absent » avec « interdit de le regarder » — 310 process
    sur 314 ont une cmdline illisible sous le compte de service, et les deux
    situations s'ecrivaient `null`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _pouls(dossier: Path, nom: str, age_s: float, contenu: dict) -> None:
    f = dossier / f"{nom}.heartbeat"
    f.write_text(json.dumps(contenu), encoding="utf-8")
    t = time.time() - age_s
    import os
    os.utime(f, (t, t))


# ── forge_stale_guard ────────────────────────────────────────────────────────

def test_pouls_juge_sur_son_propre_rythme(tmp_path):
    """Deux services au meme age, verdicts opposes : c'est tout l'enjeu."""
    import forge_stale_guard as G

    _pouls(tmp_path, "lent", 1000, {"interval_s": 21600})   # bat toutes les 6 h
    _pouls(tmp_path, "rapide", 1000, {"interval_s": 30})    # bat toutes les 30 s
    v = {f["service"]: f["verdict"] for f in G.scanner(base=tmp_path)}
    assert v == {"lent": "VIVANT", "rapide": "STALE"}


def test_trois_cycles_avant_d_accuser(tmp_path):
    """Un cycle rate arrive (charge, I/O) ; trois d'affilee est un silence."""
    import forge_stale_guard as G

    _pouls(tmp_path, "juste_avant", 85, {"interval_s": 30})   # 2,8 cycles
    _pouls(tmp_path, "juste_apres", 95, {"interval_s": 30})   # 3,2 cycles
    v = {f["service"]: f["verdict"] for f in G.scanner(base=tmp_path)}
    assert v == {"juste_avant": "VIVANT", "juste_apres": "STALE"}


def test_sans_periode_declaree_on_ne_conclut_pas(tmp_path):
    """Absence de mesure n'est pas succes : injugeable, et dit comme tel."""
    import forge_stale_guard as G

    _pouls(tmp_path, "muet", 4000, {"ts": 1})
    f = G.scanner(base=tmp_path)[0]
    assert f["verdict"] == "RYTHME_NON_DECLARE"
    assert f["verdict"] != "VIVANT"


def test_tres_vieux_sans_periode_est_dormant(tmp_path):
    """Un service arrete depuis 8 jours est un choix, pas une panne."""
    import forge_stale_guard as G

    _pouls(tmp_path, "endormi", 8 * 24 * 3600, {"ts": 1})
    assert G.scanner(base=tmp_path)[0]["verdict"] == "DORMANT"


def test_periode_lue_sous_ses_differents_noms():
    import forge_stale_guard as G

    assert G._periode({"interval_s": 30}) == 30
    assert G._periode({"tick_s": 5.5}) == 5.5
    assert G._periode({"ts": 12345}) is None
    assert G._periode({"interval_s": 0}) is None     # 0 n'est pas un rythme


# ── forge_hub_blackbox ───────────────────────────────────────────────────────

def test_port_ferme_est_vu_ferme():
    """Le verdict de vie repose sur le port : il doit etre franc."""
    import forge_hub_blackbox as B

    assert B._port_ouvert(port=1, timeout=0.2) is False


def test_echantillon_declare_sa_cecite():
    """`hub: null` seul confondrait « absent » et « interdit de regarder ».

    Sous le compte de service, 310 process sur 314 ont une cmdline illisible :
    sans le drapeau, la boite noire daterait de faux deces.
    """
    # `psutil` n'est pas dans les deps installees par ci.yml : sans ce saut, le
    # test casserait la CI distante au lieu de garder quoi que ce soit.
    psutil = pytest.importorskip("psutil")

    import forge_hub_blackbox as B

    e = B.echantillon(psutil)
    assert {"ts", "ram_pct", "ram_dispo_gb", "port8766"} <= set(e)
    if e.get("hub") is None:
        assert "process_indetermine" in e


def test_sonde_indisponible_ne_perd_pas_l_echantillon():
    """Le swap leve sur cette machine (compteurs de perf desactives). L'echantillon
    doit survivre et se declarer aveugle — sinon on perd les secondes cherchees."""
    psutil = pytest.importorskip("psutil")

    import forge_hub_blackbox as B

    e = B.echantillon(psutil)
    assert "swap_pct" in e
    if e["swap_pct"] is None:
        assert e.get("swap_aveugle")


# ── forge_circadian : une tache lourde ne part pas de n'importe ou ───────────

def test_reconstruction_refusee_sous_pytest():
    """Ce test EST la preuve : il tourne sous pytest, donc le refus doit tomber.

    Historique de la journee : le handler a d'abord ete cable dans une boucle
    morte, puis dote d'un garde d'HORAIRE — insuffisant, car la CI a tourne a
    02h07, DANS la fenetre NREM3. Le test `test_fire_phase_invokes_restart_for_
    services` a donc relance une reconstruction de 1,15 M lignes, en timeout.
    La CI passe a n'importe quelle heure : c'est a la tache de s'en proteger.
    """
    import forge_circadian as C

    r = C._reconstruire_index_fts()
    assert r["fts"] == "sous pytest"


def test_la_phase_reste_verifiee():
    """Le garde d'horaire ne doit pas disparaitre au profit du seul garde
    pytest : hors CI, c'est lui qui protege."""
    from pathlib import Path as _P

    src = _P(__file__).resolve().parents[2] / "app" / "forge_circadian.py"
    t = src.read_text(encoding="utf-8", errors="replace")
    assert "current_phase() is not Phase.NREM3" in t
    assert "PYTEST_CURRENT_TEST" in t


# ── forge_module_wiring ──────────────────────────────────────────────────────

def test_les_inventaires_ne_comptent_pas_comme_branchement():
    """Un fichier qui LISTE les modules n'en branche aucun.

    Premier resultat du scan : 1788 modules, 1788 « branches », zero orphelin.
    Cause : `*.json` etait compte comme declaratif, or
    `sandbox/workspace/organ_map_full.json` cite TOUS les modules du depot. Un
    critere qui declare tout le monde sain ne mesure rien.
    """
    import forge_module_wiring as W

    assert "*.json" not in W.DECLARATIFS
    assert "*.toml" in W.DECLARATIFS and "*.ps1" in W.DECLARATIFS


def test_extraction_des_modules_cites():
    """Les noms cites sont EXTRAITS du source, pas cherches un par un.

    La version naive testait les 2307 modules connus dans chaque fichier :
    5,3 millions de recherches de sous-chaine, le scan ne rendait jamais.
    """
    import re

    src = 'lance("forge_docker_keeper.py") puis tools/forge_stale_guard.py ; pas moi.py'
    trouves = {m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)\.py\b", src)}
    assert {"forge_docker_keeper", "forge_stale_guard"} <= trouves


def test_perimetre_du_scan_est_celui_du_depot():
    """`forge_desktop` est gitignore : le scanner ne doit pas s'y aventurer."""
    import forge_module_wiring as W

    assert "forge_desktop" not in W.ZONES
    assert {"app", "tools"} <= set(W.ZONES)


# ── forge_golden_state ───────────────────────────────────────────────────────

def test_sonde_qui_echoue_est_unknown_pas_zero():
    """Le coeur du Golden State : une mesure impossible se DECLARE.

    Toute la journee du 2026-08-14 a ete faussee par l'inverse — `/health`
    repondant `ok` avec V: non monte, `rc=0` sur un gate saute, 35 orphelins qui
    etaient des packages. Une sonde qui echoue et rend 0 transforme une panne en
    bulletin vert.
    """
    import forge_golden_state as G

    def _casse():
        raise OSError("base verrouillee")

    m = G._mesure("essai", _casse)
    assert m["etat"] == "UNKNOWN"
    assert m["valeur"] is None
    assert "OSError" in m["pourquoi"]          # la cause, pas juste l'echec


def test_sonde_qui_marche_est_mesuree():
    import forge_golden_state as G

    m = G._mesure("essai", lambda: 42)
    assert m == {"nom": "essai", "valeur": 42, "etat": "mesure"}


def test_sans_reference_aucun_verdict_vert(tmp_path, monkeypatch):
    """Pas de reference = pas de PASS. Un `--verifier` sans golden doit refuser
    de conclure plutot que d'annoncer que tout va bien."""
    import forge_golden_state as G

    monkeypatch.setattr(G, "GOLDEN", tmp_path / "absent.json")
    assert G.verifier() == 2


def test_toutes_les_sondes_sont_nommees():
    """Une sonde anonyme ne peut pas etre comparee d'une photo a l'autre."""
    import forge_golden_state as G

    noms = [n for n, _ in G.SONDES]
    assert len(noms) == len(set(noms)) and all(noms)


def test_la_sonde_graph_explorer_vise_le_port_du_service():
    """7474 est le port de Neo4j, que Nokido n'installe pas ; le Graph Explorer
    ecoute sur 7420 (tools/nokido_graph_server.py, proxy /graph/ du web hub).

    Onze cycles de « SOIN requis : graph_explorer DOWN » ont ete emis pendant
    que le service repondait 200. Une sonde qui vise le mauvais port ne mesure
    pas un service : elle fabrique une panne."""
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parents[2] / "app"))
    import inspect

    import forge_health_diagnostic as H

    src = inspect.getsource(H.audit_services_http)
    assert '"graph_explorer": "http://127.0.0.1:7420/"' in src
    # Viser l'URL, pas le nombre : le commentaire qui explique l'erreur cite
    # forcement 7474, et un test qui interdit d'en parler interdit d'expliquer.
    assert "://127.0.0.1:7474" not in src


def test_un_service_absent_ne_peut_pas_etre_declare_demarre():
    """ensure_service(graph) rendait `success: true, starting:
    NokidoGraphExplorer` alors que `sc query` rend 1060 : service inexistant.

    La nuance qui compte : 1060 PROUVE l'absence, 5 (acces refuse) prouve
    seulement qu'on n'a pas pu regarder. Confondre les deux transformerait le
    garde en bloqueur permanent sous un compte non privilegie."""
    import subprocess
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools"))
    import forge_ensure_service as E

    class _R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    vrai = subprocess.run
    try:
        subprocess.run = lambda *a, **k: _R(0)
        assert E._installe("QuelqueService") is True
        subprocess.run = lambda *a, **k: _R(1, "OpenService echec(s) 1060 : n'existe pas")
        assert E._installe("Fantome") is False
        subprocess.run = lambda *a, **k: _R(1, "OpenService echec(s) 5 : Acces refuse")
        assert E._installe("Interdit") is None
    finally:
        subprocess.run = vrai

    # Et le service a desormais une sonde d'issue reelle, pas seulement un rc.
    assert "graph" in E._HEALTH and "7420" in E._HEALTH["graph"][0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
