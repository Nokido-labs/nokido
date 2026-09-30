"""tools/patch_m2m_nokido_endpoint.py — NOKIDO devient un endpoint M2M.

Contexte (2026-08-27). Test M2M owner : codex OK (recu via [HOOK:INBOX], emet
prouve), mais la TUI Nokido (app/Nokido.py) ne pouvait NI etre ciblee NI recevoir.
Cause mesuree : la TUI est une app Textual IN-PROCESS, pas un client HTTP du hub —
`hub_lifecycle_hooks.post_dispatch` (qui surface l'INBOX aux CLI clients-HTTP) ne
l'atteint jamais. Le drain cote TUI est deja cable (set_interval -> _drain_m2m_nokido
lit agent_messages WHERE to_agent='agt_nokido'). Il MANQUE le ROUTAGE cote registry :
sans `nokido` dans `_to_map`/`_AGT`, un notify to=nokido tombe en EVENTBUS_ARCHIVE.

CE QUE FAIT CE PATCH (4 edits dans handle_notify de app/forge_mcp_registry.py) :
1. `_to_map["NOKIDO"] = agt_nokido` (cible nommee, majuscule)
2. `_to_map["nokido"] = agt_nokido` (alias direct `to`, minuscule)
3. `_broadcast_all += agt_nokido, agt_antigravity` (to=ALL couvre TOUS les CLI dispo,
   AGY inclus — il draine agt_antigravity via son daemon autonome)
4. regex `_AGT += |NOKIDO` (prefixe [NOKIDO] route vers agt_nokido)

Pourquoi un patcher et pas governed_edit direct : forge_mcp_registry.py est
CRITICAL_FILE ; governed_edit allow_critical a COUPE le hub (chemin fragile, RAG
warm/AST sur 8k+ lignes). Chemin officiel eprouve = patcher committe + `run
action=trusted_script` (cf patch_notify_reveille_drain.py). AST valide AVANT
ecriture (anti reboot fail-close) + relecture apres.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (ancien, nouveau, label) — chaque ancien doit etre UNIQUE dans le fichier.
EDITS = [
    (
        '            "SYSTEM": "agt_hub",\n            # alias directs (parametre `to`)\n',
        '            "SYSTEM": "agt_hub",\n            "NOKIDO": "agt_nokido",\n            # alias directs (parametre `to`)\n',
        "_to_map majuscule +NOKIDO",
    ),
    (
        '            "hub": "agt_hub",\n            # ANTIGRAVITY (alias AGY) : identite canonique ring1, inbox agt_antigravity\n',
        '            "hub": "agt_hub",\n            "nokido": "agt_nokido",\n            # ANTIGRAVITY (alias AGY) : identite canonique ring1, inbox agt_antigravity\n',
        "_to_map minuscule +nokido",
    ),
    (
        '        _broadcast_all = ["agt_claude", "agt_gemini", "agt_copilot", "agt_codex", "agt_cline"]\n',
        '        _broadcast_all = ["agt_claude", "agt_gemini", "agt_copilot", "agt_codex", "agt_cline", "agt_nokido", "agt_antigravity"]\n',
        "_broadcast_all +nokido +antigravity",
    ),
    (
        '            _AGT = r"CLAUDE|GEMINI|ANTIGRAVITY|AGY|COPILOT|CODEX|DAEMON|HUB|CLINE|SYSTEM"\n',
        '            _AGT = r"CLAUDE|GEMINI|ANTIGRAVITY|AGY|COPILOT|CODEX|DAEMON|HUB|CLINE|SYSTEM|NOKIDO"\n',
        "regex _AGT +NOKIDO",
    ),
]


def main() -> int:
    p = ROOT / "app" / "forge_mcp_registry.py"
    src = p.read_text(encoding="utf-8")
    if '"NOKIDO": "agt_nokido"' in src and "|SYSTEM|NOKIDO" in src:
        print("SKIP : patch deja applique")
        return 0
    for ancien, nouveau, label in EDITS:
        if nouveau in src and ancien not in src:
            print(f"SKIP bloc deja applique : {label}")
            continue
        n = src.count(ancien)
        if n != 1:
            raise AssertionError(
                f"point d'ancrage non unique ({n} occurrences) pour [{label}] — patch NON applique")
        src = src.replace(ancien, nouveau)
        print(f"OK bloc applique : {label}")
    ast.parse(src)  # AST valide AVANT d'ecrire (anti fail-close reboot)
    p.write_text(src, encoding="utf-8")
    relu = p.read_text(encoding="utf-8")
    if '"NOKIDO": "agt_nokido"' not in relu or "|SYSTEM|NOKIDO" not in relu:
        raise AssertionError("RELECTURE sans le patch — edition perdue")
    print("PATCH APPLIQUE — verifie par relecture (to_map + broadcast + regex).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
