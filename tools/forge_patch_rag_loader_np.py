# -*- coding: utf-8 -*-
"""One-shot patcher: decode numpy zero-copy du cache dense (forge_mcp_registry).

RCA 2026-07-07 : le hub pese 13.9GB/23.7GB (snapshot resource_state.json) ->
RAM systeme 90% chronique -> P1 throttle tous les spawns. Coupable =
_load_dense_cache : struct.unpack retourne des TUPLES de floats Python
(~28B/float x 544k x 1024 = pic ~14GB, heap jamais rendu a l'OS).
Fix : np.frombuffer (zero-copy, 4KB/vecteur) + np.vstack -> pic ~4GB.
CRITICAL_FILE -> trusted_script (mirror forge_patch_rag_prewarm) :
exact-match, idempotence, AST compile avant write, newline preserve.
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

A_OLD = (
    '            v = None\n'
    '            if isinstance(emb, bytes) and len(emb) == 4096:\n'
    '                v = _st.unpack("1024f", emb)\n'
    '            elif isinstance(emb, (bytes, str)):\n'
    '                try:\n'
    '                    jv = _j.loads(emb)\n'
    '                    if isinstance(jv, list) and len(jv) == 1024:\n'
    '                        v = jv\n'
    '                except Exception:\n'
    '                    pass\n'
)
A_NEW = (
    '            # RAM (2026-07-07, hub a 13.9GB) : ex-unpack en TUPLES de floats\n'
    '            # Python = pic ~14GB sur 544k vecteurs (28B/float, heap jamais\n'
    '            # rendu a l\'OS). np.frombuffer = zero-copy 4KB/vecteur -> ~4GB.\n'
    '            v = None\n'
    '            if isinstance(emb, bytes) and len(emb) == 4096:\n'
    '                v = _np.frombuffer(emb, dtype=_np.float32)\n'
    '            elif isinstance(emb, (bytes, str)):\n'
    '                try:\n'
    '                    jv = _j.loads(emb)\n'
    '                    if isinstance(jv, list) and len(jv) == 1024:\n'
    '                        v = _np.asarray(jv, dtype=_np.float32)\n'
    '                except Exception:\n'
    '                    pass\n'
)

B_OLD = '        mat = _np.asarray(vecs, dtype=_np.float32)\n'
B_NEW = '        mat = _np.vstack(vecs) if vecs else _np.zeros((0, 1024), dtype=_np.float32)\n'

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "_np.frombuffer(emb" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("A", A_OLD), ("B", B_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(A_OLD, A_NEW, 1)
text = text.replace(B_OLD, B_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: numpy zero-copy loader applied + AST valid. newline={nl!r}")
