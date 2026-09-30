"""Bridge stdio — anti-deadlock / anti-head-of-line (2026-07-14).

Avant : _write_out tenait un threading.Lock PENDANT write+flush -> client lent =>
pipe plein => flush bloque => lock pris => tous les writers geles (deadlock). Et la
boucle run_bridge etait SERIE -> une requete lente bloquait les suivantes.

Apres : queue de sortie + writer thread UNIQUE (ecriture serialisee sans lock contendu)
+ dispatch concurrent. Ces tests verrouillent les deux proprietes.
"""

import json
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

try:
    import mcp_stdio_bridge as br
except Exception as e:  # pragma: no cover - env-dependent import
    pytest.skip(f"mcp_stdio_bridge import KO ({e})", allow_module_level=True)


class _FakeOut:
    """stdout.buffer factice : capture chaque write, sans toucher au vrai flux."""

    def __init__(self):
        self.writes = []

    def write(self, b):
        self.writes.append(bytes(b))

    def flush(self):
        pass


def test_writer_unique_serialise_et_draine_tout(monkeypatch):
    """1000 messages enqueues depuis 10 threads -> le writer unique les ecrit TOUS,
    chacun atomique (jamais entrelace avec un autre)."""
    monkeypatch.setattr(br, "_OUT_Q", queue.Queue(maxsize=20000))
    fake = _FakeOut()
    t = threading.Thread(target=br._writer_loop, kwargs={"out": fake}, daemon=True)
    t.start()

    msgs = [json.dumps({"id": i}).encode() for i in range(1000)]

    def produce(chunk):
        for m in chunk:
            br._OUT_Q.put_nowait(m)

    threads = [threading.Thread(target=produce, args=(msgs[i::10],)) for i in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    br._OUT_Q.put(None)  # sentinelle d'arret
    t.join(timeout=5)
    assert not t.is_alive(), "le writer doit s'arreter sur la sentinelle"

    # Chaque write = une ligne complete terminee par \n (atomicite) ; drain complet.
    lines = [w.rstrip(b"\n") for w in fake.writes]
    assert all(w.endswith(b"\n") for w in fake.writes), "chaque write doit etre une ligne atomique"
    assert set(lines) == {m for m in msgs}, "tous les messages doivent sortir, sans perte"
    assert len(lines) == 1000


def test_write_out_ne_bloque_pas_sur_pipe_plein(monkeypatch):
    """_write_out enqueue sans bloquer meme si le writer n'ecrit rien (pipe fige).
    Avant, un flush bloquant aurait gele l'appelant."""
    monkeypatch.setattr(br, "_OUT_Q", queue.Queue(maxsize=20000))
    monkeypatch.setattr(br, "_WRITER_STARTED", threading.Event())
    # writer qui NE draine jamais (simule un client qui ne lit pas)
    monkeypatch.setattr(br, "_start_writer", lambda: None)

    done = threading.Event()

    def spam():
        for i in range(500):
            br._write_out(json.dumps({"id": i}).encode())
        done.set()

    threading.Thread(target=spam, daemon=True).start()
    assert done.wait(timeout=3), "_write_out ne doit jamais bloquer l'appelant sous pipe fige"


def test_dispatch_concurrent_pas_de_head_of_line(monkeypatch):
    """Une requete lente soumise en premier ne doit PAS retarder une rapide soumise
    juste apres : la rapide sort avant."""
    out_order = queue.Queue()

    def fake_handle_single(obj):
        if obj.get("id") == 0:
            time.sleep(0.5)  # requete lente
        return json.dumps({"id": obj.get("id")}).encode()

    monkeypatch.setattr(br, "_handle_single", fake_handle_single)
    monkeypatch.setattr(br, "_write_out", lambda d: out_order.put(json.loads(d)["id"]))

    with ThreadPoolExecutor(max_workers=4) as ex:
        ex.submit(br._process_line, b'{"id":0}')  # lente d'abord
        time.sleep(0.05)
        ex.submit(br._process_line, b'{"id":1}')  # rapide juste apres

    first = out_order.get(timeout=2)
    assert first == 1, "la requete rapide doit sortir avant la lente (head-of-line resolu)"
