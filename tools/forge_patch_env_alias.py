"""forge_patch_env_alias.py — patcher one-shot (CRITICAL_FILE) : cable forge_env_alias
au boot du hub, juste apres le chargement de Nokido.env.

Phase 3a rebrand Nokido. nokido_hub.py = CRITICAL_FILE (governed_edit refuse le
gate) -> chemin officiel = ce patcher lance via `run action=trusted_script`
(privilegie, bypass ACL). Idempotent (no-op si deja patche), byte-safe (preserve
la convention de fin de ligne CRLF/LF), valide l'AST avant ecriture. Reversible :
retirer le bloc insere = comportement d'origine.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HUB = ROOT / "tools" / "nokido_hub.py"
ANCHOR = b'_LAFORGE_ENV_LOADED = _load_dotenv(ROOT / "Nokido.env")'


def main() -> int:
    data = HUB.read_bytes()
    if b"forge_env_alias" in data:
        print("ALREADY PATCHED")
        return 0
    if ANCHOR not in data:
        print("ANCHOR NOT FOUND")
        return 2
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    block = nl.join([
        b"",
        b"# Phase 3a rebrand Nokido : miroir env LAFORGE_ <-> NOKIDO_ (dual-read reversible)",
        b"try:",
        b'    sys.path.insert(0, str(ROOT / "app"))',
        b"    from forge_env_alias import apply as _apply_env_alias",
        b"    _apply_env_alias()",
        b"except Exception:",
        b"    pass",
        b"",
    ])
    new = data.replace(ANCHOR, ANCHOR + block, 1)
    ast.parse(new.decode("utf-8"))  # fail-closed si le patch casse la syntaxe
    HUB.write_bytes(new)
    print("PATCHED OK nl=" + repr(nl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
