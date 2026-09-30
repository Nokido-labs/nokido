"""nokido_deep_rename.py — renommage PROFOND laforge->nokido (case-preserving).

Conçu pour tourner sur un WORKTREE ISOLE (--root pointe hors du live). Renomme :
  1. CONTENU de tout fichier texte : sous-chaîne 'laforge' / 'la-forge' (insensible
     à la casse) -> nokido, en préservant la casse (LaForge->Nokido, LAFORGE->NOKIDO,
     laforge->nokido). 'forge_' ne contient PAS 'laforge' => reste INTACT (garde-forge).
  2. NOMS de fichiers ET dossiers dont le basename contient laforge (bottom-up).

NE touche PAS le runtime-state (domaines DB, services NSSM, schtasks Task Scheduler,
header LaForge-Agent-Name côté clients, .env live) : ça = cutover SEPARE. Ce tool
produit un CODEBASE cohérent (imports + filenames alignés) à vérifier avant cutover.

Dry par défaut. --apply écrit. Idempotent.
"""

__FORGE_COLOR__ = "infra/rename : renommage profond laforge vers nokido (worktree isole)"  # organe declare le 2026-09-06 (audit de raccordement)
import argparse
import os
import re

BRAND = re.compile(r"la-?forge", re.I)


def cibler(terme: str, remplacement: str) -> None:
    """Restreint le renommage a UN terme, remplace par une valeur EXPLICITE.

    Mesure du 2026-08-17 : un dry-run de marque sur `tools/` seul annonce 135
    fichiers et 417 lignes. Or basculer le service `NokidoMCP` ne concerne que
    ses propres sites de pilotage. Elargir au-dela de la cible, c'est melanger
    une migration de service avec une refonte de marque, et rendre la revue
    impossible.

    ⚠️ Le remplacement doit etre DONNE : le `_repl` de marque rend la marque
    seule, donc cibler « NokidoMCP » sans plus produisait « Nokido » — suffixe
    MANGE, et 41 sites de pilotage pointes vers un service inexistant. Teste et
    corrige avant toute ecriture.

    Les KEEP sont neutralises ici : la cible est nommee explicitement par
    l'appelant, c'est lui qui porte la decision.
    """
    global BRAND, KEEP, _repl
    BRAND = re.compile(re.escape(terme), re.I)
    KEEP = re.compile(r"(?!x)x")  # ne matche jamais

    def _repl_cible(_m):
        return remplacement

    _repl = _repl_cible

# Strings FONCTIONNELS couplés à de l'état externe NON renommé (env NSSM, conteneurs
# docker, tâches schtask, logs, identités RBAC, id-mcp) : PRÉSERVÉS. Leur rename est
# STAGED (cf NOKIDO_CUTOVER_RUNBOOK Phase +N — chaque couplage derrière alias). Un
# rename aveugle casserait le live (shim env_alias mort, docker exec conteneur absent,
# glob 0 log, passthrough bash_guard, RBAC). --blind désactive (DANGER, worktree only).
KEEP = re.compile(
    r"LAFORGE_[A-Z0-9_]*"                # env vars NSSM (uppercase)
    r"|(?:agt|wrk|exegol|searxng|dist|lora|schtask)[_-]laforge"  # suffixe fonctionnel catalogue SEUL (identite/conteneur/slug/tache)
    r"|laforge-[a-z0-9][a-z0-9-]*"       # kebab lowercase: id-mcp laforge-sovereign-hub, services, tasks
    r"|LaForge-[A-Z0-9][A-Za-z0-9-]*"    # CamelCase tâches/headers: LaForge-Master, LaForge-Agent-Name
    # `NokidoMCP` etait protege tant que le service NSSM portait ce nom. Le
    # 2026-08-17 les 29 autres services ont ete renommes en Nokido* et celui-ci
    # bascule a son tour : la protection devient un piege, elle figerait 41 sites
    # de pilotage sur un service qui n'existera plus. Protection LEVEE.
    # `LaForge-Master` reste protege par la regle CamelCase ci-dessus : il porte
    # le hub et n'est PAS renomme.
    r"|laforge_py314t?"                  # env conda EXTERNE (laforge_py314/_py314t) — KEEP-miss casse hub au reboot 2026-07-10
    r"|LaForge(?:Sbx(?:Off|On)line|Trusted|Sandbox(?:Users|Online|Offline)|TrustedRunners)"  # comptes/groupes Windows sandbox (etat OS non renomme) — KEEP-miss casse run 2026-07-10
    r"|laforge_\*[A-Za-z0-9.]*"          # globs: laforge_*.log
    r"|['\"]laforge['\"]"                # lone-quoted 'laforge' (SQL DEFAULT, state keys)
)


def _repl(m):
    s = m.group(0)
    if s.isupper():
        return "NOKIDO"
    if s[0].isupper():
        return "Nokido"
    return "nokido"


def rename_str(s):
    return BRAND.sub(_repl, s)


# Le DOSSIER submodule reste 'LaForge/' (décision owner). Protéger le segment de
# chemin 'LaForge' (adjacent à / \ @) AVANT le renommage du contenu. Les identifiants
# lowercase laforge_* et le mot-marque 'LaForge' (entouré d'espaces/ponctuation) NON
# protégés -> renommés normalement.
DIR_SEG = re.compile(r"(?<=[\\/@])LaForge(?![A-Za-z0-9_])|LaForge(?=[\\/])")


def rewrite_content(text, protect=True):
    store = []

    def _mask(m):
        store.append(m.group(0))
        return "\x01%d\x02" % (len(store) - 1)

    masked = DIR_SEG.sub(_mask, text)
    if protect:
        masked = KEEP.sub(_mask, masked)
    out = BRAND.sub(_repl, masked)
    return re.sub(r"\x01(\d+)\x02", lambda mm: store[int(mm.group(1))], out)


SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
TEXT_EXT = {
    ".py", ".md", ".json", ".toml", ".ts", ".tsx", ".js", ".jsx", ".html", ".htm", ".css",
    ".scss", ".bat", ".ps1", ".sh", ".cmd", ".yaml", ".yml", ".xml", ".cfg", ".ini", ".txt",
    ".mmd", ".env", ".example", ".lock", ".pssc", ".psrc", ".tcss", ".ipynb", ".rst", ".svg",
    ".mermaid", ".secrets",
}
BIN_EXT = {
    ".db", ".hc", ".npz", ".woff2", ".woff", ".ttf", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".zip", ".7z", ".wasm", ".exe", ".dll", ".pyc", ".bak", ".filehandler", ".pdf", ".bin",
    ".pt", ".onnx", ".gguf", ".so", ".pyd", ".mp4", ".webp", ".log", ".out", ".jsonl", ".ndjson",
}


def is_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        return True
    if ext in BIN_EXT:
        return False
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(4096)
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--blind", action="store_true", help="DANGER: desactive la protection des strings fonctionnels")
    ap.add_argument(
        "--only",
        help="ne renommer QUE ce terme (ex: NokidoMCP) au lieu de toute la marque. "
             "Un renommage de marque touche des centaines de fichiers ; basculer UN "
             "service n'en demande qu'une poignee. Exige --par.",
    )
    ap.add_argument("--par", help="valeur de remplacement exacte pour --only (ex: NokidoMCP)")
    a = ap.parse_args()
    if a.only:
        if not a.par:
            print("--only exige --par (ex: --only NokidoMCP --par NokidoMCP)")
            return 2
        cibler(a.only, a.par)
        print("CIBLE : %s -> %s uniquement" % (a.only, a.par))
    root = os.path.abspath(a.root)
    protect = not a.blind

    cfiles = clines = 0
    changed_content = []
    # 1) CONTENU (top-down, avant les renames de chemins)
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f == ".git":
                continue  # worktree: .git est un FICHIER pointeur, ne pas toucher (mais .gitignore/.gitleaks OK)
            p = os.path.join(dp, f)
            if not is_text(p):
                continue
            try:
                raw = open(p, "rb").read()
            except Exception:
                continue
            low = raw.lower()
            if b"aforge" not in low and b"a-forge" not in low:
                continue
            txt = raw.decode("utf-8", "surrogateescape")
            new = rewrite_content(txt, protect)
            if new != txt:
                cfiles += 1
                clines += sum(1 for o, n in zip(txt.split("\n"), new.split("\n")) if o != n)
                changed_content.append(os.path.relpath(p, root))
                if a.apply:
                    open(p, "wb").write(new.encode("utf-8", "surrogateescape"))

    # 2) NOMS fichiers + dossiers (bottom-up : enfants avant parents)
    renamed = []
    for dp, dn, fn in os.walk(root, topdown=False):
        low = dp.replace("\\", "/").lower()
        if any(("/" + s) in ("/" + low) for s in SKIP_DIRS):
            continue
        for name in fn + dn:
            if not BRAND.search(name):
                continue
            if protect and KEEP.search(name):
                continue
            newname = BRAND.sub(_repl, name)
            if newname == name:
                continue
            src = os.path.join(dp, name)
            dst = os.path.join(dp, newname)
            renamed.append(os.path.relpath(src, root) + "  ->  " + newname)
            if a.apply:
                os.rename(src, dst)

    tag = "APPLIED" if a.apply else "DRY"
    print("%s: content_files=%d content_lines=%d renamed_paths=%d" % (tag, cfiles, clines, len(renamed)))
    print("--- renamed paths (%d) ---" % len(renamed))
    for r in renamed:
        print("  ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
