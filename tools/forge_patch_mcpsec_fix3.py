# -*- coding: utf-8 -*-
"""One-shot patcher: fix #3 A+B on app/forge_mcp_security.py.

CRITICAL_FILE -> applied via owner trusted_script (bypasses governed_edit gate),
but replicates its safety: exact-match (assert count==1), idempotence guard,
AST compile() BEFORE write, newline-style preserved. Aborts without writing on
any mismatch. Safe to re-run (idempotent).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_security.py")

A_OLD = '        args_summary = json.dumps({k: str(v)[:80] for k, v in args.items()}, ensure_ascii=False)'
A_NEW = (
    '        from forge_conv_sanitizer import _redact\n'
    '        args_summary = json.dumps({k: _redact(str(v))[:80] for k, v in args.items()}, ensure_ascii=False)'
)

B_OLD = (
    '        # Bloque les commandes destructives non autorisées\n'
    '        sql_up = sql.strip().upper()\n'
    '        if any(sql_up.startswith(k) for k in ("DROP ", "TRUNCATE ", "DELETE FROM sqlite_")):\n'
    '            raise ValueError("query: commande SQL non autorisée")'
)
B_NEW = B_OLD + (
    '\n\n'
    '    # Fix #3-B : DLP non-bloquant sur les tools sortants (cloud).\n'
    '    # Detecte un credential passe en argument -> marque l\'audit (SECRET_IN_ARGS),\n'
    '    # ne leve PAS (eviter les faux-positifs qui casseraient un appel legitime).\n'
    '    if tool in ("ask", "crawl", "web_search", "orchestrate", "research_agent", "biblio"):\n'
    '        try:\n'
    '            from forge_secret_guard import scan_outbound, SecretLeakBlocked\n'
    '            blob = " ".join(str(v) for v in args.values() if v)\n'
    '            scan_outbound(blob, provider=tool, local_only=False)\n'
    '        except SecretLeakBlocked as _leak:\n'
    '            audit(tool, args, "SECRET_IN_ARGS", error=str(_leak))\n'
    '        except Exception:\n'
    '            pass  # DLP best-effort : ne jamais bloquer la validation'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "_redact(str(v))" in text or "SECRET_IN_ARGS" in text:
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
print(f"OK: fix #3 A+B applied + AST valid. newline={nl!r}")
