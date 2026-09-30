# -*- coding: utf-8 -*-
"""NR — le noeud edge deploye sur le LAN n'ouvre aucune ecriture de fichier sans jeton.

Avant (27/09), `POST /ota` ecrivait un fichier dans ~/.nokido_edge/ota pour TOUT poste du
reseau, et les deux corps (/ota, /world_vector) etaient lus sur un Content-Length choisi par
l'emetteur. Le premier deploiement reel (VM StackDNS, DNS de production) l'aurait expose tel
quel. Et hors du depot, /world_vector rendait 400 : le codec n'etait importable que via le
paquet `nokido_agent`, absent d'un noeud.

Ces tests empruntent le chemin reel : le programme lance en `--serve` (point d'entree
`__main__`), interroge en HTTP. Le dernier reproduit le deploiement : deux fichiers seuls
dans un repertoire, paquet `nokido_agent` introuvable.
"""
import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (serveur); reseau
#   localhost (l.62)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
NODE = APP / "forge_edge_node.py"
CODEC = APP / "forge_world_vector_codec.py"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def noeud(tmp_path):
    procs = []

    def lancer(jeton=None, script=NODE, sans_paquet=False):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CREDENTIALS_DIRECTORY", "LAFORGE_EDGE_OTA_TOKEN_FILE", "PYTHONPATH")}
        env["LAFORGE_EDGE_OTA_DIR"] = str(tmp_path / "ota")
        if jeton is not None:
            f = tmp_path / "jeton_ota"
            f.write_text(jeton, encoding="utf-8")
            env["LAFORGE_EDGE_OTA_TOKEN_FILE"] = str(f)
        port = _port_libre()
        argv = ["--serve", "--host", "127.0.0.1", "--port", str(port), "--name", "nr"]
        if sans_paquet:
            # __main__ reel, mais le paquet du depot est rendu introuvable comme sur une VM
            code = ("import sys, runpy; sys.modules['nokido_agent'] = None; "
                    f"sys.argv = [{str(script)!r}] + {argv!r}; "
                    f"runpy.run_path({str(script)!r}, run_name='__main__')")
            cmd = [sys.executable, "-c", code]
        else:
            cmd = [sys.executable, str(script)] + argv
        p = subprocess.Popen(cmd, env=env, cwd=str(Path(script).parent),
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        procs.append(p)
        fin = time.time() + 15
        while time.time() < fin:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                return port
            except OSError:
                if p.poll() is not None:
                    raise AssertionError(p.stderr.read().decode("utf-8", "replace")[:500])
                time.sleep(0.1)
        raise AssertionError("noeud injoignable en 15 s")

    yield lancer
    for p in procs:
        p.kill()
        p.wait(timeout=5)


def _post(port, chemin, corps=b"", entetes=None, longueur=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.putrequest("POST", chemin)
        for k, v in (entetes or {}).items():
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(corps) if longueur is None else longueur))
        c.endheaders()
        if corps:
            try:
                c.send(corps)
            except OSError:
                pass  # le noeud a pu refuser et fermer avant de lire : c'est le cas teste
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()


def _fichiers_ota(tmp_path):
    d = tmp_path / "ota"
    return sorted(x.name for x in d.iterdir()) if d.exists() else []


def test_ota_fermee_sans_jeton(noeud, tmp_path):
    port = noeud()
    code, rep = _post(port, "/ota", b"#!/bin/sh\necho pris\n", {"X-OTA-Path": "evil.sh"})
    assert code == 403, rep
    assert "aucun jeton" in rep["error"]
    assert _fichiers_ota(tmp_path) == []


def test_ota_refuse_un_jeton_faux(noeud, tmp_path):
    port = noeud(jeton=secrets.token_hex(16))
    code, rep = _post(port, "/ota", b"abc", {"X-OTA-Path": "a.bin",
                                             "X-Edge-Token": secrets.token_hex(16)})
    assert code == 403, rep
    assert _fichiers_ota(tmp_path) == []


def test_ota_ouverte_avec_le_bon_jeton(noeud, tmp_path):
    jeton = secrets.token_hex(16)
    port = noeud(jeton=jeton)
    corps = b"charge utile OTA"
    sha = hashlib.sha256(corps).hexdigest()
    code, rep = _post(port, "/ota", corps, {"X-OTA-Path": "../../a.bin", "X-OTA-SHA256": sha,
                                            "X-Edge-Token": jeton})
    assert code == 200 and rep["ok"] and rep["sha256"] == sha, rep
    assert _fichiers_ota(tmp_path) == ["a.bin"]  # basename : pas de traversee


def test_ota_corps_hors_plafond_refuse_avant_lecture(noeud, tmp_path):
    jeton = secrets.token_hex(16)
    port = noeud(jeton=jeton)
    code, rep = _post(port, "/ota", entetes={"X-Edge-Token": jeton}, longueur=10 ** 9)
    assert code == 413, rep
    assert _fichiers_ota(tmp_path) == []


def test_world_vector_corps_hors_plafond_ou_negatif(noeud):
    port = noeud()
    code, rep = _post(port, "/world_vector", longueur=10 ** 7)
    assert code == 413, rep
    code, rep = _post(port, "/world_vector", longueur=-1)
    assert code == 400 and "negatif" in rep["error"], rep


def test_deploiement_deux_fichiers_seuls_recoit_le_world_vector(noeud, tmp_path):
    np = pytest.importorskip("numpy")
    vm = tmp_path / "vm"
    vm.mkdir()
    shutil.copy2(NODE, vm / NODE.name)
    shutil.copy2(CODEC, vm / CODEC.name)
    port = noeud(script=vm / NODE.name, sans_paquet=True)

    sys.path.insert(0, str(APP))
    try:
        import forge_world_vector_codec as wv
    finally:
        sys.path.remove(str(APP))
    vec = np.random.default_rng(0).normal(size=4096).astype("float32")
    blob = wv.pack(wv.quantize(vec))
    code, rep = _post(port, "/world_vector", blob)
    assert code == 200 and rep.get("ok"), rep
    assert rep["received"]["dim"] == 4096

    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request("GET", "/world_vector/last")
        dernier = json.loads(c.getresponse().read())
    finally:
        c.close()
    assert dernier["dim"] == 4096 and dernier["bytes"] == len(blob)
