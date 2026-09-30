"""forge_patch_wasm_parsing.py — one-shot : corrige le parsing sandbox=wasm.

CRITICAL_FILE (forge_mcp_registry) -> governed_edit refuse ; voie officielle =
patcher git-tracke lance en trusted_script. Le split() naif du dispatch cassait
sur les ESPACES du chemin Nokido ("Script python IA") -> « Acces refuse ».
On capture le chemin ENTIER jusqu'a .wasm (ou l'URL) avant func + args.

Idempotent : verifie l'ancre, s'abstient si deja patche.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "app" / "forge_mcp_registry.py"

OLD = (
    '            parts = cmd.strip().split()\n'
    '            wasm_file = parts[0] if parts else ""\n'
    '            func_name = parts[1] if len(parts) > 1 else "run"\n'
    '            wasm_args = [int(x) for x in parts[2:] if x.lstrip("-").isdigit()]'
)
NEW = (
    '            # PARSING ROBUSTE (fix 2026-07-28) : un split() naif cassait sur les\n'
    '            # ESPACES du chemin — Nokido vit dans "Script python IA", donc parts[0]\n'
    '            # devenait "C:\\\\...\\\\Script" et l\'open() rendait « Acces refuse ». On\n'
    '            # capture le chemin ENTIER jusqu\'a .wasm (ou l\'URL http), puis func+args.\n'
    '            import re as _re_wasm\n'
    '\n'
    '            _c = cmd.strip()\n'
    '            _m = _re_wasm.match(r"^\\s*(https?://\\S+|.+?\\.wasm)\\s*(.*)$", _c, _re_wasm.I)\n'
    '            if _m:\n'
    '                wasm_file = _m.group(1).strip().strip(\'"\')\n'
    '                _rest = _m.group(2).split()\n'
    '            else:\n'
    '                wasm_file, _rest = _c, []\n'
    '            func_name = _rest[0] if _rest else "run"\n'
    '            wasm_args = [int(x) for x in _rest[1:] if x.lstrip("-").isdigit()]'
)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if NEW.split("\n")[0].strip() in src or "PARSING ROBUSTE (fix 2026-07-28)" in src:
        print("DEJA PATCHE — rien a faire")
        return 0
    if OLD not in src:
        print("ANCRE INTROUVABLE — le bloc a change, patch NON applique (abstention)")
        return 2
    src2 = src.replace(OLD, NEW, 1)
    # validation AST avant ecriture
    import ast
    ast.parse(src2)
    TARGET.write_text(src2, encoding="utf-8")
    print("PATCH APPLIQUE + AST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
