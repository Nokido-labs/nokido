"""forge_repo_map_ts.py — symboles TypeScript pour la repo map (proxy_deno, organes Deno).

Trou mesuré le 2026-08-02 : les 1 423 fiches de module en RAG sont 100 % Python, alors que
le SUPERVISEUR — l'organe qui démarre et relance tous les autres — est en TypeScript, et
qu'un `.ts` cassé le tue en entier (raison d'être du parse-check `.ts` de `forge_git_gate`).
L'organe le plus critique du corps était le seul absent de la carte.

## Pourquoi pas tree-sitter tout de suite

`forge_repo_map` annonce depuis sa ligne 13 « brancher tree-sitter plus tard ». Mesure :
`tree_sitter` 0.25.2 est bien installé, mais **aucune grammaire** ne l'est
(`tree_sitter_typescript`, `tree_sitter_languages`, `tree_sitter_javascript` : absents), et
`pip install` depuis le compte sandbox échoue (`HOME=C:\\Users\\Default`). Le binaire `deno`,
autre parseur exact déjà utilisé par le gate, vit dans le profil owner
(`%USERPROFILE%/.deno/bin/deno.exe`) et rend « Accès refusé » aux comptes de service.

Écrire ici un extracteur tree-sitter serait donc livrer du code que je ne peux pas
EXÉCUTER — exactement ce que le gate refuse depuis `d75dee6c`. `parse_tree_sitter()` reste
donc un point d'extension déclaré, qui répond honnêtement « indisponible » plutôt que de
prétendre parser.

## Ce que fait la voie disponible

Extraction LEXICALE des déclarations de haut niveau et des méthodes de classe. C'est un
MEILLEUR EFFORT, et la sortie le dit (`methode`) : une carte n'a pas besoin des corps, mais
elle ne doit jamais laisser croire qu'elle est exhaustive. Les limites connues sont
énumérées dans `LIMITES` — un lecteur doit pouvoir savoir ce que la carte ne voit pas.
"""

from __future__ import annotations

import re

__FORGE_COLOR__ = "cognition/carte-du-code"

LIMITES = (
    "declarations en une ligne uniquement (signature multi-lignes : nom capture, args tronques)",
    "aucune analyse de portee : une declaration citee dans un commentaire de bloc peut passer",
    "types generiques et surcharges non distingues",
    "remplacer par tree-sitter des que la grammaire TS est installee",
)

# Mots-clés de contrôle : `if (...) {` ressemble à une méthode pour un regex naïf.
_CONTROLE = {"if", "for", "while", "switch", "catch", "return", "function", "class",
             "else", "do", "try", "finally", "new", "await", "typeof", "case"}

_DECL = re.compile(
    r"^(?P<export>export\s+)?(?:default\s+)?"
    r"(?P<kind>async\s+function|function|class|interface|type|enum|const|let)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<reste>.*)$"
)
_METHODE = re.compile(
    r"^\s{2,}(?:(?:public|private|protected|static|async|readonly)\s+)*"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\)\s*[:{]"
)
_CLASSE = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)")
_ARGS = re.compile(r"\(([^)]*)\)")


def disponible() -> tuple[bool, str]:
    """(tree-sitter utilisable ?, méthode réellement employée). Jamais un silence."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_typescript  # noqa: F401
    except ImportError:
        return False, "lexicale"
    return True, "tree-sitter"


def parse_tree_sitter(_texte: str) -> list[dict] | None:
    """Point d'extension déclaré. Rend None tant que la grammaire TS n'est pas installée.

    None signifie « je ne peux pas voir », et non « rien à voir » : l'appelant bascule sur
    la voie lexicale et l'annonce. À implémenter APRÈS installation, pour pouvoir le tester
    (owner : `pip install tree-sitter-typescript` dans l'env de Nokido).
    """
    ok, _ = disponible()
    if not ok:
        return None
    return None  # grammaire présente mais extracteur non encore écrit ET TESTÉ


def _args_de(reste: str) -> list[str]:
    m = _ARGS.search(reste or "")
    if not m or not m.group(1).strip():
        return []
    bruts = [a.strip() for a in m.group(1).split(",") if a.strip()]
    return [a.split(":")[0].strip().lstrip(".") for a in bruts][:8]


def parse_lexicale(texte: str) -> list[dict]:
    """Déclarations de haut niveau + méthodes de classe. Meilleur effort, borné et annoncé."""
    symboles: list[dict] = []
    classe_courante: str | None = None
    dans_bloc = False
    for i, ligne in enumerate(texte.splitlines(), start=1):
        nu = ligne.strip()
        if dans_bloc:
            if "*/" in nu:
                dans_bloc = False
            continue
        if nu.startswith("/*"):
            dans_bloc = "*/" not in nu
            continue
        if nu.startswith("//") or not nu:
            continue

        mc = _CLASSE.match(ligne)
        if mc:
            classe_courante = mc.group("name")
            symboles.append({"name": classe_courante, "kind": "class", "lineno": i,
                             "args": [], "parent": None})
            continue
        if ligne and not ligne[0].isspace() and not nu.startswith("}"):
            classe_courante = None  # retour au niveau module

        md = _DECL.match(ligne)
        if md:
            brut = md.group("kind").replace("async ", "").strip()
            reste = md.group("reste") or ""
            if brut in ("const", "let"):
                # Seules les const-fonctions intéressent une carte : `export const f = (...) =>`
                if "=>" not in reste and "function" not in reste:
                    continue
                brut = "function"
            symboles.append({
                "name": md.group("name"),
                "kind": brut,
                "lineno": i,
                "args": _args_de(reste),
                "parent": None,
                "exported": bool(md.group("export")),
            })
            continue

        if classe_courante:
            mm = _METHODE.match(ligne)
            if mm and mm.group("name") not in _CONTROLE:
                symboles.append({"name": mm.group("name"), "kind": "method", "lineno": i,
                                 "args": _args_de("(" + mm.group("args") + ")"),
                                 "parent": classe_courante})
    return symboles


def parse_ts(texte: str) -> tuple[list[dict], str]:
    """Rend (symboles, méthode employée). La méthode voyage AVEC la donnée : une carte
    produite en mode dégradé doit se signaler partout où elle est lue."""
    exact = parse_tree_sitter(texte)
    if exact is not None:
        return exact, "tree-sitter"
    return parse_lexicale(texte), "lexicale"
