# -*- coding: utf-8 -*-
"""One-shot patcher: Sprint 3 M2M sur app/forge_mcp_registry.py.

Câble la validation M2M (app/forge_m2m_protocol.py, dictionnaire
config/m2m_intents.json) sur les 2 canaux du registry :
  N. handle_notify : verdict en tête (warn = annotation dans la réponse à
     l'émetteur + event bus ; error = refus M2M_REFUSED) ;
  T. handle_task_result : idem sur le champ result.
(Le canal postal est câblé dans forge_postal.post — module non critique.)

Fail-open partout : la validation ne casse JAMAIS un canal.

CRITICAL_FILE -> owner trusted_script, garanties habituelles : exact-match
count==1, idempotence, compile() avant écriture, newline préservé.

Run : run action=trusted_script path=tools/forge_patch_registry_m2m.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

# ── N1 : tête de handle_notify ───────────────────────────────────────────────
N1_OLD = (
    '        msg = args.get("message", "")\n'
    '        if not msg:\n'
    '            return "Erreur: parametre \'message\' requis"\n'
)
N1_NEW = N1_OLD + (
    '\n'
    '        # Sprint 3 M2M : validation du message inter-agents (config/m2m_intents.json).\n'
    '        # warn (defaut) = annotation + event bus ; error = refus. Fail-open.\n'
    '        _m2m_note = ""\n'
    '        try:\n'
    '            from forge_m2m_protocol import check as _m2m_check\n'
    '            _m2m_ok, _m2m_v = _m2m_check("notify", msg)\n'
    '            if not _m2m_ok:\n'
    '                return f"M2M_REFUSED {_m2m_v.get(\'code\')}: {\'; \'.join(_m2m_v.get(\'violations\') or [])}"\n'
    '            if _m2m_v.get("code") not in ("M2M_OK", "M2M_OK_PROSE"):\n'
    '                _m2m_note = f" [{_m2m_v.get(\'code\')}]"\n'
    '        except Exception:\n'
    '            pass\n'
)

# ── N2 : queue de handle_notify (annotation warn dans la réponse émetteur) ──
N2_OLD = (
    '        if _is_broadcast:\n'
    '            return f"OK broadcast envoye a {len(_targets)} agents: {\', \'.join(_targets)}"\n'
    '        return "OK notification envoyee"\n'
)
N2_NEW = (
    '        if _is_broadcast:\n'
    '            return f"OK broadcast envoye a {len(_targets)} agents: {\', \'.join(_targets)}" + _m2m_note\n'
    '        return "OK notification envoyee" + _m2m_note\n'
)

# ── T : tête de handle_task_result ───────────────────────────────────────────
T_OLD = (
    '        tid = args.get("task_id", "")\n'
    '        result_text = (args.get("result", "") or "")[:2000]\n'
    '        now = _dt.now().isoformat()\n'
)
T_NEW = T_OLD + (
    '\n'
    '        # Sprint 3 M2M : validation du result (warn par defaut ; error = refus).\n'
    '        try:\n'
    '            from forge_m2m_protocol import check as _m2m_check\n'
    '            _m2m_ok, _m2m_v = _m2m_check("task_result", result_text)\n'
    '            if not _m2m_ok:\n'
    '                return _j.dumps({"ok": False, "error": "M2M_REFUSED", "code": _m2m_v.get("code"),\n'
    '                                 "violations": _m2m_v.get("violations")}, ensure_ascii=False)\n'
    '        except Exception:\n'
    '            pass\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "forge_m2m_protocol" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("N1", N1_OLD), ("N2", N2_OLD), ("T", T_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(N1_OLD, N1_NEW, 1)
text = text.replace(N2_OLD, N2_NEW, 1)
text = text.replace(T_OLD, T_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: M2M wired (N1+N2 notify, T task_result) + AST valid. newline={nl!r}")
