"""
forge_diff_analyzer.py - Détecteur breaking changes vs codebase Nokido
========================================================================
Compare les nouvelles releases (RAG domain=watch_alerts) avec les imports
et usages réels dans le code Nokido pour identifier les impacts potentiels.

Usage:
    from forge_diff_analyzer import analyze_breaking_changes
    impacts = analyze_breaking_changes("starlette", "0.42.0")

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `bilan_watch_alerts` — Bilan des alertes breaking ET securite, par identite canonique. Leve si la base est illisible.
- `identite_alerte` — Identite CANONIQUE d'une alerte, tiree de sa SOURCE.
- `version_installee` — Version du paquet dans CET interpreteur ; None s'il n'y est pas (ce n'est pas « absent partout »).
"""

from __future__ import annotations
import ast, logging, re, sqlite3
from pathlib import Path
from urllib.parse import unquote

logger = logging.getLogger("Nokido.DiffAnalyzer")
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
TOOLS = ROOT / "tools"
DB_PATH = ROOT / "RAG" / "embeddings.db"


# Fichiers de code qu'un scan n'a PAS pu lire ou parser : comptes, jamais tus -- un usage
# introuvable dans un fichier illisible n'est pas « aucun usage » (2026-09-24).
_ILLISIBLES: set = set()


def scan_imports(package: str) -> list[dict]:
    """Trouve tous les fichiers Nokido qui importent un package."""
    results = []
    pkg_lower = package.lower().replace("-", "_")

    for py_file in list(APP_DIR.rglob("*.py")) + list(TOOLS.rglob("*.py")):
        try:
            source = py_file.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            _ILLISIBLES.add(str(py_file))
            continue
        if pkg_lower not in source.lower():
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            _ILLISIBLES.add(str(py_file))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module, symbols = "", []
                # Module de PREMIER NIVEAU exact (2026-09-24, mesure) : la sous-chaine attribuait
                # l'alerte du SERVEUR `qdrant/qdrant` aux imports du CLIENT `qdrant_client`.
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0].lower() == pkg_lower:
                            module = alias.name
                            symbols = [alias.asname or alias.name]
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0].lower() == pkg_lower:
                        module = node.module
                        symbols = [a.name for a in node.names]
                if module:
                    results.append(
                        {
                            "file": str(py_file.relative_to(ROOT)),
                            "line": node.lineno,
                            "module": module,
                            "symbols": symbols,
                        }
                    )
    return results


def scan_function_calls(symbol: str) -> list[dict]:
    """Trouve les usages d'un symbole dans la codebase."""
    results = []
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    for py_file in list(APP_DIR.rglob("*.py")) + list(TOOLS.rglob("*.py")):
        try:
            source = py_file.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            _ILLISIBLES.add(str(py_file))
            continue
        for i, line in enumerate(source.splitlines(), 1):
            if pattern.search(line):
                results.append(
                    {
                        "file": str(py_file.relative_to(ROOT)),
                        "line": i,
                        "code": line.strip()[:120],
                    }
                )
    return results


def get_breaking_changes(package: str) -> list[dict]:
    """Récupère les breaking changes depuis le RAG."""
    try:
        conn = _lecture_seule()
        pkg_pat = f"%{package.lower().replace('-', '_')}%"
        rows = conn.execute(
            "SELECT id,text,source,role_hint,ingested_at FROM rag_chunks "
            "WHERE domain='watch_alerts' AND role_hint LIKE 'release:breaking%' "
            "AND (LOWER(source) LIKE ? OR LOWER(text) LIKE ?) "
            "ORDER BY ingested_at DESC LIMIT 10",
            (pkg_pat, pkg_pat),
        ).fetchall()
        conn.close()
        return [{"id": r[0], "text": r[1][:500], "source": r[2], "role": r[3], "ts": r[4]} for r in rows]
    except Exception as e:
        logger.warning(f"get_breaking_changes ILLISIBLE pour {package} : {e}")
        return []


def extract_deprecated_symbols(text: str) -> list[str]:
    """Extrait les noms de symboles dépréciés depuis un texte de release."""
    STOP = {"the", "and", "for", "new", "old", "use", "api", "all", "its"}
    found = []
    pats = [
        r"[Rr]emoved?\s+[`'\"]?(\w+)[`'\"]?",
        r"[Dd]eprecated?\s+[`'\"]?(\w+)[`'\"]?",
        r"`(\w+)`\s+(?:is|has been|was)\s+(?:removed|deprecated)",
        r"(?:remove|deprecat)\w*\s+(?:the\s+)?`?(\w+)`?\s+(?:function|method|parameter|class|callback)",
    ]
    for pat in pats:
        for m in re.finditer(pat, text):
            sym = m.group(1)
            if len(sym) > 2 and sym.lower() not in STOP:
                found.append(sym)
    return list(dict.fromkeys(found))


def analyze_breaking_changes(package: str, version: str = "") -> dict:
    """
    Analyse l'impact d'un breaking change sur la codebase Nokido.

    Pipeline :
      1. Récupère les breaking changes depuis le RAG
      2. Extrait les symboles dépréciés/supprimés
      3. Scan la codebase pour les usages de ces symboles
      4. Génère un rapport d'impact priorisé
    """
    logger.info(f"[diff] Analyse: {package} {version}")

    breaking = get_breaking_changes(package)
    imports = scan_imports(package)

    if not imports:
        return {
            "package": package,
            "version": version,
            "used": False,
            "breaking_changes": breaking,
            "impacted_files": [],
            "critical": False,
            "summary": f"{package} non utilisé dans Nokido -- aucun impact.",
        }

    deprecated = []
    for bc in breaking:
        deprecated.extend(extract_deprecated_symbols(bc["text"]))
    deprecated = list(dict.fromkeys(deprecated))

    impacted = []
    for sym in deprecated:
        usages = scan_function_calls(sym)
        if usages:
            impacted.append({"symbol": sym, "usages": usages})

    critical = bool(impacted)
    parts = [f"{package}: {len(imports)} import(s) dans la codebase."]
    if deprecated:
        parts.append(f"Symboles dépréciés: {', '.join(deprecated[:5])}.")
    if impacted:
        files = list({u["file"] for item in impacted for u in item["usages"]})
        parts.append(f"IMPACT CRITIQUE: {len(files)} fichier(s) à migrer: {', '.join(files[:3])}.")
    else:
        parts.append("Aucun usage direct des symboles dépréciés.")

    return {
        "package": package,
        "version": version,
        "used": True,
        "imports": imports[:10],
        "breaking_changes": breaking[:3],
        "deprecated_symbols": deprecated,
        "impacted_files": impacted,
        "critical": critical,
        "summary": " ".join(parts),
    }


def _lecture_seule() -> sqlite3.Connection:
    """Ce consommateur ne fait que LIRE : jamais une connexion d'ecrivain sur la base RAG."""
    return sqlite3.connect("file:%s?mode=ro" % str(DB_PATH).replace("\\", "/"), uri=True, timeout=10)


def identite_alerte(source: str) -> dict:
    """Identite CANONIQUE d'une alerte, tiree de sa SOURCE.

    Mesure 2026-09-24 (veille lot_C_06) : `author` vide sur 12/12 alertes breaking/security, `meta`
    sans paquet ni version ; la source porte TOUJOURS depot + version (138/144 releases GitHub,
    6 pages PyPI). Un depot n'est pas un paquet : le paquet vient du tag s'il y est
    (`langchain-core==1.4.0`), sinon du nom du depot -- et la correspondance au code est exacte.
    """
    s = unquote(source or "")
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/releases/tag/(.+)$", s)
    if m:
        tag = m.group(3).strip()
        paquet, version = tag.split("==", 1) if "==" in tag else (m.group(2), tag)
        return {"hote": "github", "depot": m.group(1) + "/" + m.group(2), "paquet": paquet,
                "version": version.lstrip("vV")}
    m = re.match(r"https?://pypi\.org/project/([^/]+)/?([^/]*)", s)
    if m:
        return {"hote": "pypi", "depot": None, "paquet": m.group(1), "version": m.group(2) or None}
    return {"hote": "inconnu", "depot": None, "paquet": None, "version": None}


def version_installee(paquet: str):
    """Version du paquet dans CET interpreteur ; None s'il n'y est pas (ce n'est pas « absent partout »)."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version(paquet)
    except PackageNotFoundError:
        return None


def _deja_au_dela(installee, alerte):
    """True / False, ou None si les versions ne se comparent pas (le DIRE, jamais trancher)."""
    try:
        from packaging.version import InvalidVersion, Version
        return Version(installee) >= Version(alerte)
    except (ImportError, InvalidVersion, TypeError):
        return None


def bilan_watch_alerts() -> dict:
    """Bilan des alertes breaking ET securite, par identite canonique. Leve si la base est illisible.

    Remplace la selection `author != ''` qui ne lisait RIEN (0 critique en 0,0 s, faux negatif
    mesure le 24/09 : onnxruntime v1.25 breaking et qdrant v1.17.1 security invisibles).
    Statuts : A_EXAMINER (utilise, version anterieure ou incomparable) · DEJA_AU_DELA ·
    NON_UTILISE_EN_PYTHON (peut viser une PROTHESE native : non verifie ici, DIT) · SANS_IDENTITE.
    """
    _ILLISIBLES.clear()
    conn = _lecture_seule()
    try:
        rows = conn.execute(
            "SELECT source, role_hint, text FROM rag_chunks WHERE domain='watch_alerts' "
            "AND (role_hint LIKE 'release:breaking%' OR role_hint LIKE 'alert:security%')").fetchall()
    finally:
        conn.close()
    groupes: dict = {}
    for source, role, text in rows:
        ident = identite_alerte(source)
        cle = (ident["depot"] or ident["hote"], ident["paquet"], ident["version"])
        g = groupes.setdefault(cle, {**ident, "genres": set(), "textes": [], "sources": set()})
        g["genres"].add("securite" if (role or "").startswith("alert:security") else "breaking")
        g["textes"].append(text or "")
        g["sources"].add(source)
    alertes = []
    for g in groupes.values():
        a = {k: g[k] for k in ("hote", "depot", "paquet", "version")}
        a["genres"], a["sources"] = sorted(g["genres"]), sorted(g["sources"])[:3]
        if not g["paquet"]:
            a["statut"] = "SANS_IDENTITE"
        elif not scan_imports(g["paquet"]):
            a["statut"] = "NON_UTILISE_EN_PYTHON"
            a["note"] = "aucun import exact ; peut viser une prothese native (serveur, binaire) : NON verifie ici"
        else:
            inst = version_installee(g["paquet"])
            a["version_installee"] = inst
            au_dela = _deja_au_dela(inst, g["version"]) if inst else None
            if au_dela:
                a["statut"] = "DEJA_AU_DELA"
            else:
                a["statut"] = "A_EXAMINER"
                a["comparaison"] = "installee anterieure" if au_dela is False else "INCOMPARABLE ou non installee ici"
                deprecies = list(dict.fromkeys(s for t in g["textes"] for s in extract_deprecated_symbols(t)))
                a["symboles_deprecies"] = deprecies[:10]
                a["usages"] = [{"symbole": s, "usages": scan_function_calls(s)[:5]} for s in deprecies[:10]
                               if scan_function_calls(s)]
        alertes.append(a)
    alertes.sort(key=lambda a: (a["statut"] != "A_EXAMINER", "securite" not in a["genres"], a.get("paquet") or ""))
    return {"etat": "MESURE", "alertes_lues": len(rows), "identites": len(alertes), "alertes": alertes,
            "fichiers_code_illisibles": sorted(_ILLISIBLES)[:20], "nb_fichiers_code_illisibles": len(_ILLISIBLES)}


def analyze_all_watch_alerts() -> list[dict]:
    """Les alertes A_EXAMINER du bilan. Base illisible = EXCEPTION, jamais `[]` (« rien » != « illisible »)."""
    return [a for a in bilan_watch_alerts()["alertes"] if a["statut"] == "A_EXAMINER"]


if __name__ == "__main__":
    import json, sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pkg = sys.argv[1] if len(sys.argv) > 1 else "starlette"
    result = analyze_breaking_changes(pkg)
    print(
        json.dumps(
            {
                "package": result["package"],
                "used": result["used"],
                "critical": result["critical"],
                "summary": result["summary"],
                "imports": len(result.get("imports", [])),
                "impacted": len(result.get("impacted_files", [])),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
