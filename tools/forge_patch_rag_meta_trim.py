# -*- coding: utf-8 -*-
"""One-shot patcher: trim meta text du cache dense (app/forge_mcp_registry.py).

RAM 93% constatee post-prewarm 2026-07-07 : _load_dense_cache stocke le texte
COMPLET des ~691k chunks alors que les consommateurs n'utilisent que text[:512]
(rerank) et [:400] (sortie) -> plusieurs GB de RAM gaspilles. Fix = stocker 512
chars. Zero perte fonctionnelle. CRITICAL_FILE -> trusted_script (mirror
forge_patch_rag_prewarm): exact-match, idempotence, AST compile avant write,
newline preserve.
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

OLD = (
    '            ids.append(cid)\n'
    '            vecs.append(v)\n'
    '            meta[cid] = {"source": src, "domain": dom, "text": txt}\n'
)
NEW = (
    '            ids.append(cid)\n'
    '            vecs.append(v)\n'
    '            # RAM (2026-07-07, 93% post-prewarm) : les consommateurs ne lisent\n'
    '            # que text[:512] (rerank) / [:400] (sortie) -> stocker 512 chars\n'
    '            # au lieu du texte complet = plusieurs GB rendus, zero perte.\n'
    '            meta[cid] = {"source": src, "domain": dom, "text": (txt or "")[:512]}\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if '"text": (txt or "")[:512]' in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

n = text.count(OLD)
if n != 1:
    print(f"ABORT: block found {n} times (expected exactly 1) -> no write")
    sys.exit(2)

text = text.replace(OLD, NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: meta text trim [:512] applied + AST valid. newline={nl!r}")
