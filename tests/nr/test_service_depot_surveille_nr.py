"""NR 2/11 (choix owner : service supervise dedie) -- le demon du depot surveille bat et parle.

Avant : forge_auto_ingest_daemon.py n'etait cable dans AUCUN service, n'ecrivait aucun pouls (un arret etait
indiscernable d'un depot vide) et ses messages d'ingestion partaient dans un logger non capture. Il est desormais
declare dans services.toml (NokidoHotFolder) avec un pouls, et ses cycles sont bornables pour le test du chemin reel.
"""
import json
import re
from pathlib import Path

from nokido_agent.app import forge_auto_ingest_daemon as A

ROOT = Path(__file__).resolve().parents[2]


class _FauxWatcher:
    def __init__(self):
        self.scans = 0
        self._seen = set()

    def _scan(self):
        self.scans += 1


def _pouls_canon(tmp_path, monkeypatch):
    # 2/11 soir : le pouls passe par le CANON forge_heartbeat.beat_daemon (cliquets pouls_canon et racine_donnees) ;
    # on redirige sa racine, plus une constante locale du demon.
    from nokido_agent.app import forge_heartbeat as HB
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    assert not hasattr(A, "HEARTBEAT"), "pouls maison reintroduit : passer par forge_heartbeat.beat_daemon"
    return tmp_path / "sandbox" / "hot_folder.heartbeat"


def test_un_cycle_scanne_et_ecrit_le_pouls(tmp_path, monkeypatch):
    w = _FauxWatcher()
    monkeypatch.setattr(A, "get_watcher", lambda **k: w)
    pouls = _pouls_canon(tmp_path, monkeypatch)
    A.run_daemon(intervalle=0, cycles=1)
    assert w.scans >= 1
    d = json.loads(pouls.read_text(encoding="utf-8"))
    assert d["service"] == "NokidoHotFolder" and d["pid"] > 0 and "ts" in d


def test_le_demon_dit_au_demarrage_si_l_ocr_est_disponible(tmp_path, monkeypatch, capsys):
    # 2/11 : le service refusait un PDF image en « OCR indisponible (ModuleNotFoundError) » sans que rien ne l'ait
    # annonce : l'etat de l'OCR (et le compte qui le voit ou non) se dit des le demarrage, pas au premier scan rate.
    w = _FauxWatcher()
    monkeypatch.setattr(A, "get_watcher", lambda **k: w)
    pouls = _pouls_canon(tmp_path, monkeypatch)
    from nokido_agent.app import forge_hot_ingest as H
    monkeypatch.setattr(H, "ocr_disponible", lambda: (False, "ModuleNotFoundError: No module named 'cv2'"))
    A.run_daemon(intervalle=0, cycles=1)
    sortie = capsys.readouterr().out
    assert "OCR" in sortie and "cv2" in sortie, sortie
    d = json.loads(pouls.read_text(encoding="utf-8"))
    assert d.get("ocr") is False


def test_le_service_est_declare_avec_son_pouls():
    toml = (ROOT / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8")
    bloc = re.search(r'name = "NokidoHotFolder"(.*?)(?:\n\[\[service\]\]|\Z)', toml, re.S)
    assert bloc, "NokidoHotFolder absent de services.toml"
    assert "forge_auto_ingest_daemon.py" in bloc.group(1)
    assert 'heartbeat = "sandbox/hot_folder.heartbeat"' in bloc.group(1)
