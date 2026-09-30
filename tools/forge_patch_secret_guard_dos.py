# -*- coding: utf-8 -*-
"""One-shot patcher: bound the secret-scan input length in forge_secret_guard.py.

Fix DoS-hub (regex-DoS via forged big payload wedging the event-loop). Adds a
module constant _MAX_SCAN_LEN (env LAFORGE_MAX_SCAN_LEN, default 256KB) and caps
the input in every regex scan entry (scan_outbound + the 3 sanitize_*). A real
secret fits well within 256KB; beyond that the length itself is the anomaly.

CRITICAL-ish security file -> applied via owner trusted_script. Safety: exact
match (assert count==1), idempotence guard, compile() AST before write, newline
style preserved. Aborts without writing on any mismatch. Idempotent.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_secret_guard.py")

CONST = (
    "# DoS bound (regex-DoS via payload forge) : on borne la taille scannee.\n"
    "# Un secret legitime tient largement dans 256KB ; au-dela = anomalie, on tronque pour scanner.\n"
    '_MAX_SCAN_LEN = int(os.environ.get("LAFORGE_MAX_SCAN_LEN", "262144"))\n\n\n'
)

BLOCKS = [
    # (label, old, new) — add module const just before scan_outbound def
    (
        "A_const",
        'def scan_outbound(prompt: str, provider: str = "unknown", local_only: bool = False) -> None:',
        CONST + 'def scan_outbound(prompt: str, provider: str = "unknown", local_only: bool = False) -> None:',
    ),
    (
        "B_outbound",
        "    if local_only:\n        return  # local — rien ne quitte la machine\n\n    for pattern, label in _OUTBOUND_PATTERNS:",
        "    if local_only:\n        return  # local — rien ne quitte la machine\n\n    prompt = prompt[:_MAX_SCAN_LEN]  # DoS bound : borne la taille scannee\n    for pattern, label in _OUTBOUND_PATTERNS:",
    ),
    (
        "C_python",
        "    if not code:\n        return None\n    matches = _SUSPICIOUS_PY_RE.findall(code)",
        "    if not code:\n        return None\n    code = code[:_MAX_SCAN_LEN]  # DoS bound\n    matches = _SUSPICIOUS_PY_RE.findall(code)",
    ),
    (
        "D_shell",
        "    if not cmd:\n        return None\n    matches = _SUSPICIOUS_SHELL_RE.findall(cmd)",
        "    if not cmd:\n        return None\n    cmd = cmd[:_MAX_SCAN_LEN]  # DoS bound\n    matches = _SUSPICIOUS_SHELL_RE.findall(cmd)",
    ),
    (
        "E_sql",
        "    if not sql:\n        return None\n    matches = _SQL_SELECT_RE.findall(sql)",
        "    if not sql:\n        return None\n    sql = sql[:_MAX_SCAN_LEN]  # DoS bound\n    matches = _SQL_SELECT_RE.findall(sql)",
    ),
]

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "_MAX_SCAN_LEN" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old, _new in BLOCKS:
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

for label, old, new in BLOCKS:
    text = text.replace(old, new, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: DoS bound applied to {len(BLOCKS)} scan entries + const. newline={nl!r}")
