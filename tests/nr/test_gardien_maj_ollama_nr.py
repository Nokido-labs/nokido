# -*- coding: utf-8 -*-
"""NR (owner 3/11 « a chaque mise a jour ca casse ; tu dois tenir une partie de ces dll » -> « Nokido pilote les mises
a jour »). Cause PROUVEE (upgrade.log 17:08) : l'application Ollama lance son installateur alors que ollama.exe est
tenu par NokidoOllama (deno <- nssm <- services, session 0) ; RestartManager « Permission Denied + Session
Mismatch », DeleteFile code 5, Abort, retour arriere = moteurs supprimes. Contrat du gardien (lanceur, session owner) :
arret TENU de NokidoOllama AVANT l'installateur, installation silencieuse, fermeture de l'app, retrait de son
demarrage automatique (son auto-installation est la cause), preuve du moteur, relance ; rien a faire = aucun geste.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_launcher as L  # noqa: E402


def test_verdict_pur():
    assert L.verdict_maj_ollama(None, 100.0, True) == "rien"
    assert L.verdict_maj_ollama(1000.0, 100.0, True) == "installer"
    assert L.verdict_maj_ollama(100.0, 1000.0, True) == "rien"
    assert L.verdict_maj_ollama(100.0, 1000.0, False) == "reparer"
    assert L.verdict_maj_ollama(None, 1000.0, False) == "geste_owner"


def test_version_plus_recente():
    assert L.version_plus_recente("0.12.10", "0.12.9") is True
    assert L.version_plus_recente("0.12.9", "0.12.9") is False
    assert L.version_plus_recente(None, "0.12.9") is False          # illisible : jamais un telechargement a l'aveugle


def _decor(monkeypatch, tmp_path, moteur):
    setup = tmp_path / "OllamaSetup.exe"
    prog = tmp_path / "Programs" / "Ollama"
    prog.mkdir(parents=True)
    (prog / "ollama.exe").write_bytes(b"x")
    if moteur:
        (prog / "lib" / "ollama").mkdir(parents=True)
    lnk = tmp_path / "Ollama.lnk"
    lnk.write_bytes(b"x")
    monkeypatch.setattr(L, "OLLAMA_SETUP", setup)
    monkeypatch.setattr(L, "OLLAMA_DIR", prog)
    monkeypatch.setattr(L, "DEMARRAGE_OLLAMA", lnk)
    monkeypatch.setattr(L, "JOURNAL_GARDIEN_OLLAMA", tmp_path / "j.jsonl")
    monkeypatch.setattr(L, "_verifier_version_ollama", lambda: None)   # pas de reseau en NR
    gestes = []

    def faux_run(cmd, **k):
        s = " ".join(map(str, cmd))
        if "forge_supervisor_ctl" in s:
            gestes.append("ctl_" + str(cmd[-2]))
        elif "OllamaSetup" in s:
            gestes.append("setup")
            (prog / "lib" / "ollama").mkdir(parents=True, exist_ok=True)
        elif "taskkill" in s:
            gestes.append("kill_app")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(L.subprocess, "run", faux_run)
    return setup, lnk, gestes, tmp_path / "j.jsonl"


def test_reparation_dans_le_bon_ordre(monkeypatch, tmp_path):
    setup, lnk, gestes, journal = _decor(monkeypatch, tmp_path, moteur=False)
    setup.write_bytes(b"installateur")
    assert L._action_ollama_maj() is True
    assert gestes == ["ctl_stop", "setup", "kill_app", "ctl_start"], gestes
    assert not lnk.exists()
    e = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert e["verdict"] == "reparer" and e["verdict_final"] == "ok"


def test_moteur_absent_sans_installateur_le_telecharge_puis_repare(monkeypatch, tmp_path):
    # 3/11 18 h : l'app Ollama avait retire OllamaSetup.exe apres son echec -> « geste_owner » renvoyait la panne a
    # l'owner. Le gardien telecharge l'installateur officiel puis repare.
    setup, lnk, gestes, journal = _decor(monkeypatch, tmp_path, moteur=False)
    monkeypatch.setattr(L, "_telecharger_installateur_ollama", lambda: setup.write_bytes(b"officiel") or True)
    assert L._action_ollama_maj() is True
    assert gestes == ["ctl_stop", "setup", "kill_app", "ctl_start"], gestes
    e = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert e["verdict"] == "reparer" and "installateur telecharge" in e["gestes"]


def test_rien_a_faire_aucun_geste_mais_demarrage_auto_retire(monkeypatch, tmp_path):
    # 3/11 18 h : l'installation (meme reussie) RECREE le raccourci de demarrage de l'app -- qui relance ses
    # auto-installations. Retire a CHAQUE passage, sans toucher au service.
    setup, lnk, gestes, journal = _decor(monkeypatch, tmp_path, moteur=True)
    assert L._action_ollama_maj() is True
    assert gestes == [] and not lnk.exists()


def test_le_tray_lance_le_gardien():
    src = (ROOT / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
    assert "_garder_ollama_maj()" in src and '"ollama-maj"' in src
