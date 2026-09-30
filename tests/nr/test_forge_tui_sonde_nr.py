"""NR -- tools/forge_tui_sonde.py rend TROIS etats et ne fabrique jamais un vert.

L'instrument prouve la TUI v13 (app/Nokido.py, bridge :7440) sous trusted_script ; ici on garde
sa LOGIQUE : un ecran lu vide est ILLISIBLE (lecteur aveugle), une exception est un DEFAUT
nomme, et le chemin reel (Pilot sur la TUI multi-CLI, capteurs reseau bouchonnes) rend PROUVE.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_tui_sonde as s  # noqa: E402
import nokido_tui as nt  # noqa: E402


def test_trois_etats_jamais_deux():
    assert s._verdict({"illisible": "x"}) == "ILLISIBLE"
    assert s._verdict({"texte_montage_car": 0}) == "ILLISIBLE", "ecran lu vide = lecteur aveugle, pas un vert"
    assert s._verdict({"texte_montage_car": 10, "exceptions_touches": ["f1: boom"]}) == "DEFAUT"
    assert s._verdict({"texte_montage_car": 10, "marqueurs_fin": ["Traceback ..."]}) == "DEFAUT"
    assert s._verdict({"texte_montage_car": 10, "exceptions_touches": [], "marqueurs_fin": []}) == "PROUVE"


def test_un_fil_ne_pendant_la_sonde_est_nomme_et_rend_defaut():
    """Mesure 25/09 : la TUI v13 fermee, un fil retenait le processus. Seuls les fils NES pendant
    la sonde comptent (ceux d'autres tests ne sont pas imputes a la TUI)."""
    import threading
    stop = threading.Event()
    ancien = threading.Thread(target=stop.wait, name="fil_ancien", daemon=False)
    ancien.start()
    avant = {t.ident for t in threading.enumerate()}
    nouveau = threading.Thread(target=stop.wait, name="fil_de_la_tui", daemon=False)
    nouveau.start()
    try:
        vivants = s._fils_vivants(avant)
        assert any(v.startswith("fil_de_la_tui") for v in vivants)
        assert not any(v.startswith("fil_ancien") for v in vivants)
        assert s._verdict({"texte_montage_car": 10, "fils_vivants_apres_fermeture": vivants}) == "DEFAUT"
    finally:
        stop.set()
        ancien.join(2)
        nouveau.join(2)


def test_un_ouvrier_d_executeur_inactif_n_est_pas_un_defaut():
    """Faux defaut mesure le 25/09 : l'ouvrier `asyncio_0` INACTIF etait compte ; l'arret le libere."""
    import concurrent.futures
    import threading
    avant = {t.ident for t in threading.enumerate()}
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="asyncio_nr")
    ex.submit(lambda: None).result()
    try:
        assert not any(v.startswith("asyncio_nr") for v in s._fils_vivants(avant)), \
            "un ouvrier inactif a ete impute a la TUI"
    finally:
        ex.shutdown(wait=True)


def test_une_tui_qui_plante_au_montage_est_nommee(monkeypatch):
    def boum():
        raise PermissionError("logs/ non inscriptible")
    monkeypatch.setattr(s, "TUIS", {"tui qui plante": boum})
    r = asyncio.run(s.sonder_tout(5))["tui qui plante"]
    assert r["verdict"] == "ILLISIBLE" and "PermissionError" in r["illisible"]


def test_chemin_reel_sur_la_tui_multi_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "status_services", lambda: {"hub": "🟢"})
    monkeypatch.setattr(nt, "opsec_state", lambda: {"level": "STANDARD", "locked": False, "by": None})
    monkeypatch.setattr(nt, "fetch_recent", lambda *a, **k: [])
    monkeypatch.setattr(nt, "M2M", tmp_path / "absente.db")
    monkeypatch.setattr(s, "TUIS", {"multi": s._fabriquer_nokido_tui})
    r = asyncio.run(s.sonder_tout(40))["multi"]
    assert r["verdict"] == "PROUVE", r
    assert r["touches"] >= 20
