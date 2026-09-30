"""tools/patch_m2m_cli_derivation.py — M2M suit le registre LIVE des CLI.

Contexte (2026-08-27). Apres avoir cable NOKIDO en dur, l'owner signale que
D'AUTRES CLI existent (mammouth, zcode, roo, vibe, sixth, vscode) et manquent au
M2M. Source de verite = config/agent_identities.json : 13 agents kind=cli_agent,
dont 6 absents de _to_map/_INJECT_AGENTS. Plutot que rallonger des listes figees
(fragile, a maintenir a deux endroits, ratant les futurs CLI), on DERIVE.

CE QUE FAIT CE PATCH (handle_notify de app/forge_mcp_registry.py) :
1. Apres les maps figees (_to_map / _broadcast_all), un bloc COMPLETE ces maps
   depuis forge_videur.cli_agents() + mailbox_de() (registre LIVE, reload mtime).
   Le fige reste un PLANCHER (zero regression si le registre illisible) ; la
   derivation ajoute mammouth/zcode/roo/vibe/sixth/vscode + tout futur CLI sans
   redeploiement. On n'itere QUE les cli_agent -> les providers (mistral, cohere)
   ne sont PAS ajoutes.
2. Le regex _AGT (routage par prefixe [DEST]) est etendu aux memes cli_agent.

Reutilise forge_videur (loader central agent_identities, cache mtime) — anti-dup.
_ns (sys) et _no (os) sont deja importes plus haut dans handle_notify.

Patcher + trusted_script (CRITICAL_FILE) : governed_edit allow_critical a coupe le
hub le 2026-08-27 (chemin fragile). AST valide AVANT ecriture + relecture apres.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DERIV_BLOCK = '''        _broadcast_all = ["agt_claude", "agt_gemini", "agt_copilot", "agt_codex", "agt_cline", "agt_nokido", "agt_antigravity"]
        # ── M2M DURABLE : complete les maps figees par les cli_agent du registre
        # LIVE (config/agent_identities.json, reload mtime). Le fige ci-dessus reste
        # un PLANCHER (fallback si registre illisible) ; la derivation ajoute
        # mammouth/zcode/roo/vibe/sixth/vscode + tout futur CLI sans redeploiement.
        # On n'itere QUE les cli_agent : les providers (mistral, cohere) sont exclus.
        try:
            _ns.path.insert(0, _no.path.join(_no.path.dirname(__file__)))
            from forge_videur import cli_agents as _cli_ag, mailbox_de as _mb_de
            for _nm in _cli_ag():
                _bx = _mb_de(_nm)
                if not _bx:
                    continue
                _to_map[_nm] = _bx
                _to_map[_nm.lower()] = _bx
                if _bx not in _broadcast_all:
                    _broadcast_all.append(_bx)
        except Exception:  # noqa: BLE001
            pass  # registre illisible -> plancher fige conserve
        _explicit_to = args.get("to", "")
'''

EDITS = [
    (
        '        _broadcast_all = ["agt_claude", "agt_gemini", "agt_copilot", "agt_codex", "agt_cline", "agt_nokido", "agt_antigravity"]\n        _explicit_to = args.get("to", "")\n',
        DERIV_BLOCK,
        "derivation _to_map/_broadcast_all depuis cli_agents()",
    ),
    (
        '            _AGT = r"CLAUDE|GEMINI|ANTIGRAVITY|AGY|COPILOT|CODEX|DAEMON|HUB|CLINE|SYSTEM|NOKIDO"\n',
        '            _AGT = r"CLAUDE|GEMINI|ANTIGRAVITY|AGY|COPILOT|CODEX|DAEMON|HUB|CLINE|SYSTEM|NOKIDO"\n'
        '            try:\n'
        '                from forge_videur import cli_agents as _cag2\n'
        '                _AGT = "|".join(sorted(set(_AGT.split("|")) | _cag2()))\n'
        '            except Exception:  # noqa: BLE001\n'
        '                pass\n',
        "regex _AGT etendu aux cli_agent",
    ),
]

MARQUEUR = "M2M DURABLE : complete les maps figees"


def main() -> int:
    p = ROOT / "app" / "forge_mcp_registry.py"
    src = p.read_text(encoding="utf-8")
    if MARQUEUR in src:
        print("SKIP : patch deja applique")
        return 0
    for ancien, nouveau, label in EDITS:
        n = src.count(ancien)
        if n != 1:
            raise AssertionError(
                f"point d'ancrage non unique ({n} occurrences) pour [{label}] — patch NON applique")
        src = src.replace(ancien, nouveau)
        print(f"OK bloc applique : {label}")
    ast.parse(src)  # AST valide AVANT d'ecrire (anti fail-close reboot)
    p.write_text(src, encoding="utf-8")
    relu = p.read_text(encoding="utf-8")
    if MARQUEUR not in relu or "_cag2" not in relu:
        raise AssertionError("RELECTURE sans le patch — edition perdue")
    print("PATCH APPLIQUE — verifie par relecture (derivation + regex).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
