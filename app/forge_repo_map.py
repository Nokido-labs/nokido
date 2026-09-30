"""app/forge_repo_map.py - Aider-style compressed repo map.

Pour SWE-bench (et toute tache d edition cross-fichier dans un gros repo),
le bon SCAFFOLDING n est PAS un DSL rigide cote prompt mais une CARTE
TOPOGRAPHIQUE precise cote contexte. On extrait via AST les SIGNATURES de
toutes les classes et fonctions du repo cible -> 100k LOC compressees a
~3k tokens. L agent voit la totalite des points d entree sans payer pour
le corps des methodes.

Choix d implementation :
  - ast natif Python (stdlib, zero install) au lieu de tree-sitter qui
    necessite des bindings C par langage. Limitation : Python only. Pour
    multi-language, brancher tree-sitter plus tard via une plug-in source.
  - Sortie en MARKDOWN structure (`### path/file.py` + listes signatures),
    compressible par n importe quel LLM, copiable dans n importe quel
    runner.

Combine avec forge_repo_map_tools (view_file_content / edit_file_block) :
l agent navigue librement via la map, ouvre les fichiers a la demande,
edite par bloc precis. Pas de DSL ; raisonnement libre du LLM.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Symbol:
    name: str
    kind: str  # "class" | "function" | "async_function" | "method"
    file: str
    lineno: int
    end_lineno: int | None = None
    args: list[str] = field(default_factory=list)
    parent: str | None = None  # nom classe parente pour methodes
    docstring: str = ""  # premiere ligne docstring si dispo


def _arg_names(node: ast.arguments) -> list[str]:
    names: list[str] = [a.arg for a in node.args]
    if node.vararg:
        names.append(f"*{node.vararg.arg}")
    names += [a.arg for a in node.kwonlyargs]
    if node.kwarg:
        names.append(f"**{node.kwarg.arg}")
    return names


def _docstring_line(node) -> str:
    if not (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return ""
    lines = node.body[0].value.value.strip().splitlines()
    if not lines:
        return ""
    return lines[0][:120]


def _parse_ts_symbols(path: Path, root: Path) -> list[Symbol]:
    """Symboles TypeScript — le superviseur Deno entre enfin dans la carte (2026-08-02).

    Trou mesuré ce jour-là : les 1 423 fiches de module en RAG étaient 100 % Python, alors
    que l'organe qui démarre et relance tous les autres est en `.ts`, et qu'un `.ts` cassé
    le tue en entier. Le plus critique était le seul invisible.

    Délègue à `forge_repo_map_ts`, qui ANNONCE sa méthode. En mode dégradé (grammaire
    tree-sitter absente), le `kind` porte le suffixe `~lex` : un lecteur de la carte doit
    pouvoir distinguer ce qui a été PARSÉ de ce qui a été DEVINÉ.
    """
    try:
        from nokido_agent.app.forge_repo_map_ts import parse_ts
    except ImportError:
        return []
    try:
        texte = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = str(path.relative_to(root)).replace("\\", "/")
    bruts, methode = parse_ts(texte)
    suffixe = "" if methode == "tree-sitter" else "~lex"
    return [
        Symbol(
            name=s["name"],
            kind=str(s["kind"]) + suffixe,
            file=rel,
            lineno=int(s["lineno"]),
            args=list(s.get("args") or []),
            parent=s.get("parent"),
        )
        for s in bruts
    ]


def parse_file_symbols(path: Path, root: Path) -> list[Symbol]:
    """Extract classes + top-level functions + methods. Skip private under-score."""
    if path.suffix.lower() in (".ts", ".tsx"):
        return _parse_ts_symbols(path, root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (SyntaxError, OSError):
        return []
    rel = str(path.relative_to(root)).replace("\\", "/")
    symbols: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    file=rel,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    docstring=_docstring_line(node),
                )
            )
            for body_node in node.body:
                if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if body_node.name.startswith("_") and body_node.name != "__init__":
                        continue
                    kind = "async_function" if isinstance(body_node, ast.AsyncFunctionDef) else "method"
                    symbols.append(
                        Symbol(
                            name=body_node.name,
                            kind=kind,
                            file=rel,
                            lineno=body_node.lineno,
                            end_lineno=getattr(body_node, "end_lineno", None),
                            args=_arg_names(body_node.args),
                            parent=node.name,
                            docstring=_docstring_line(body_node),
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            symbols.append(
                Symbol(
                    name=node.name,
                    kind=kind,
                    file=rel,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    args=_arg_names(node.args),
                    docstring=_docstring_line(node),
                )
            )
    return symbols


def build_repo_map(
    root: str | Path,
    # Le `.ts` entre dans la carte (2026-08-02) : les exclusions ci-dessous laissent
    # passer proxy_deno (superviseur + organes) et écartent le généré/jetable.
    include_globs: tuple[str, ...] = ("**/*.py", "**/*.ts"),
    exclude_globs: tuple[str, ...] = (
        "**/__pycache__/**",
        "**/.git/**",
        "**/_attic/**",
        "**/legacy/**",
        "**/.venv/**",
        "**/venv/**",
        "**/node_modules/**",
        "**/sandbox/**",
        "**/eval_repos/**",  # corpus SWE-bench : du code d'AUTRES projets, hors anatomie
    ),
    max_files: int = 5000,
) -> dict:
    """Scan root, retourne {files: int, symbols: list[Symbol], roots: ...}.
    Le repo map est la SOURCE pour la carte markdown."""
    root_path = Path(root).resolve()
    all_paths: list[Path] = []
    # Budget PAR GLOB, et non global (mesuré 2026-08-02) : avec un plafond partagé, les
    # 5 000 premiers `.py` l'épuisaient AVANT que le glob `.ts` ne soit atteint — la carte
    # sortait à 0 fichier TypeScript sans qu'aucun message ne le signale. Un langage ne
    # doit pas pouvoir affamer l'autre, et un plafond qui mord doit se DIRE.
    plafonds_atteints: list[str] = []
    for glob in include_globs:
        pris = 0
        for p in root_path.glob(glob):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            # `"/sandbox/" in rel` etait FAUX pour `sandbox/x.ts` (pas de slash initial) :
            # 182 fichiers generes entraient dans la carte, defaut prexistant mesure le
            # 2026-08-02 en y faisant entrer le TypeScript. Tester la RACINE aussi.
            if (
                any(p.match(eg.replace("**/", "*")) for eg in exclude_globs)
                or any(seg in rel for seg in ("__pycache__", "_attic", "legacy", ".venv",
                                              "node_modules", "eval_repos"))
                or any(rel.startswith(d + "/") or f"/{d}/" in rel
                       for d in ("sandbox", "backups", "node_modules"))
            ):
                continue
            all_paths.append(p)
            pris += 1
            if pris >= max_files:
                plafonds_atteints.append(glob)
                break
    symbols: list[Symbol] = []
    for p in all_paths:
        symbols.extend(parse_file_symbols(p, root_path))
    return {
        "root": str(root_path),
        "files": len(all_paths),
        "symbols": symbols,
        # Vide = couverture complète. Non vide = ces globs ont été TRONQUÉS : la carte
        # n'est pas exhaustive et le consommateur doit le savoir.
        "plafonds_atteints": plafonds_atteints,
    }


def render_markdown(repo_map: dict, max_chars: int = 30000) -> str:
    """Format compact markdown. Groupe par fichier.
    Limite max_chars pour eviter overflow contexte."""
    by_file: dict[str, list[Symbol]] = {}
    for s in repo_map["symbols"]:
        by_file.setdefault(s.file, []).append(s)
    lines = [f"# Repo Map ({repo_map['files']} files, {len(repo_map['symbols'])} symbols)\n"]
    # Le `kind` peut porter le suffixe `~lex` (symbole TypeScript extrait lexicalement,
    # cf. forge_repo_map_ts). Comparer sur le kind BRUT laissait tomber 100 % du
    # TypeScript en silence : les symboles etaient bien dans les donnees, et absents de
    # la carte rendue -- mesure 2026-08-02, supervisor.ts introuvable dans le markdown.
    def _base(kind: str) -> str:
        return kind.split("~", 1)[0]

    # Ordre EQUITABLE entre racines (mesure 2026-08-02) : `sorted(by_file)` epuisait les
    # 30 000 chars dans `app/`, si bien que `proxy_deno/` -- donc le SUPERVISEUR -- ne
    # figurait JAMAIS dans la carte rendue, alors qu'il etait bien dans les donnees. Un
    # budget + un ordre arbitraire = les derniers n'existent pas. Round-robin : chaque
    # partie du corps est representee avant que le plafond ne tombe.
    par_racine: dict[str, list[str]] = {}
    for _f in sorted(by_file):
        par_racine.setdefault(_f.split("/")[0], []).append(_f)
    ordre: list[str] = []
    while any(par_racine.values()):
        for _racine in sorted(par_racine):
            if par_racine[_racine]:
                ordre.append(par_racine[_racine].pop(0))
    montres = 0
    for fpath in ordre:
        syms = by_file[fpath]
        montres += 1
        approx = " — carte lexicale (approximative)" if any("~lex" in s.kind for s in syms) else ""
        lines.append(f"\n## {fpath}{approx}")
        # classes d abord, puis top-level functions
        classes = [s for s in syms if _base(s.kind) == "class"]
        functions = [s for s in syms
                     if _base(s.kind) in ("function", "async_function", "interface", "type", "enum")]
        for c in classes:
            doc = f" - {c.docstring}" if c.docstring else ""
            lines.append(f"  class {c.name}:L{c.lineno}{doc}")
            methods = [s for s in syms if s.parent == c.name]
            for m in methods:
                args = ", ".join(m.args[:5])
                more = "..." if len(m.args) > 5 else ""
                lines.append(f"    def {m.name}({args}{more}):L{m.lineno}")
        for f in functions:
            args = ", ".join(f.args[:5])
            more = "..." if len(f.args) > 5 else ""
            doc = f"  # {f.docstring}" if f.docstring else ""
            base = _base(f.kind)
            if base in ("function", "async_function"):
                lines.append(f"  def {f.name}({args}{more}):L{f.lineno}{doc}")
            else:
                # Une interface / un type / un enum n'est PAS appelable : lui coller des
                # parentheses vides ferait lire un contrat de donnees comme une fonction.
                lines.append(f"  {base} {f.name}:L{f.lineno}{doc}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            # Dire CE QUI MANQUE, pas seulement qu'on a coupe.
            lines.append(
                f"\n# ... [tronque a {max_chars} chars : {montres}/{len(by_file)} fichiers montres, "
                f"{len(repo_map['symbols'])} symboles au total. Cibler via "
                f"build_repo_map(include_globs=...) ou find_symbol().]"
            )
            break
    return "\n".join(lines)


def symbols_to_jsonl(repo_map: dict, dst: str | Path) -> int:
    """Persist sous forme JSONL pour requete ulterieure (filter par name, kind)."""
    p = Path(dst)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as f:
        for s in repo_map["symbols"]:
            d = {
                "name": s.name,
                "kind": s.kind,
                "file": s.file,
                "lineno": s.lineno,
                "end_lineno": s.end_lineno,
                "args": s.args,
                "parent": s.parent,
                "docstring": s.docstring,
            }
            f.write(json.dumps(d) + "\n")
            n += 1
    return n


def find_symbol(repo_map: dict, name: str) -> list[Symbol]:
    """Lookup par nom exact (case-sensitive). Retourne tous les matches."""
    return [s for s in repo_map["symbols"] if s.name == name]


def file_skeleton(path: str | Path, root: str | Path) -> str:
    """Retourne le SKELETON d un fichier : imports + signatures + docstrings,
    corps des methodes remplaces par `...`. Compresse pour contexte LLM."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(root) / p
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return ""
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.append("import " + ", ".join(n.name for n in node.names))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.append(f"from {'.' * node.level}{mod} import " + ", ".join(n.name for n in node.names))
        elif isinstance(node, ast.ClassDef):
            out.append(f"\nclass {node.name}:")
            doc = _docstring_line(node)
            if doc:
                out.append(f'    """{doc}"""')
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ", ".join(_arg_names(sub.args))
                    out.append(f"    def {sub.name}({args}): ...")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(_arg_names(node.args))
            out.append(f"\ndef {node.name}({args}): ...")
    return "\n".join(out)
