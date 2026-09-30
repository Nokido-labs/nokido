"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_brain_ping
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
brain_ping.py — Attend que brain_worker soit prêt (max 10s).
Appelé par Nokido_Lanceur.bat juste après le start /B brain_worker.
"""

import sys, time

try:
    import zmq
except ImportError:
    sys.exit(0)  # pyzmq absent — pas un echec bloquant

port = int(sys.argv[1]) if len(sys.argv) > 1 else 5557

ctx = zmq.Context()
s = ctx.socket(zmq.REQ)
s.setsockopt(zmq.RCVTIMEO, 1200)
s.setsockopt(zmq.SNDTIMEO, 1200)
s.connect(f"tcp://127.0.0.1:{port}")

for i in range(5):
    try:
        s.send(b'{"cmd":"ping"}')
        r = s.recv()
        if b"pong" in r:
            print(f"  [brain] pret ({i + 1}s)")
            s.close()
            ctx.term()
            sys.exit(0)
    except Exception:
        pass
    time.sleep(1)

print("  [brain] timeout 5s -- demarrage sans sidecar (fallback Ollama)")
s.close()
ctx.term()
sys.exit(0)  # non bloquant
