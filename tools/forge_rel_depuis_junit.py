"""tools/forge_rel_depuis_junit.py -- Rapports d'erreur LOCALISES (REL) depuis un JUnit rouge.

Pour chaque testcase en failure/error : sandbox/evolution_proposal_rel_<hash>.md avec un bloc
```json``` {error_id, pointer_ref{file,function,line}|null, evidence{message,trace}}.
pointer_ref = frame la PLUS PROFONDE sous app/ ou tools/ (jamais tests/).

Usage : python tools/forge_rel_depuis_junit.py --junit <rapport.xml> [--dry-run]
"""
__FORGE_COLOR__ = 'immunitaire/rapport_erreur_localise'

import argparse
import ast
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
SANDBOX = _RACINE_DONNEES / "sandbox"
FENETRE_DEDUP_S = 7 * 86400
MESSAGE_MAX = 2000
TRACE_LIGNES = 30

_RE_FRAME = re.compile(r"^\s*(?P<file>[^\s:'\"]+\.py):(?P<line>\d+):(?P<rest>.*)$")
_RE_DEF = re.compile(r"^\s*(?:>\s*)?(?:async\s+)?def\s+(\w+)")


def _lire_junit_commun(chemin):
    """Reutilise le parseur de ci_local ; None = rapport illisible."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from ci_local import _lire_junit
    finally:
        sys.path.pop(0)
    return _lire_junit(chemin)


def _chemin_depot(f: str):
    """Chemin relatif app/... ou tools/..., None si tests/ ou hors app/tools."""
    parts = f.replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if seg == "tests":
            return None
        if seg in ("app", "tools"):
            return "/".join(parts[i:])
    return None


# Echec d'ASSERTION (26/10) : la fonction fautive a RENDU une valeur, elle n'est dans aucune frame ; pytest la nomme.
_RE_SYMBOLE = re.compile(r"<function (\w+) at 0x[0-9A-Fa-f]+>\s*=\s*([\w.]+)\.(\w+)")
_RE_FICHIER_TEST = re.compile(r"^\s*(tests[\\/][^\s:]+\.py):\d+", re.M)


def _alias_du_test(test_rel: str) -> dict:
    """{alias: module} tire des imports du fichier de test ; {} s'il est illisible."""
    try:
        arbre = ast.parse((ROOT / test_rel).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):  # muet-ok : alias inconnu -> la localisation rend None, dit par l'appelant
        return {}
    alias = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                alias[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                alias[a.asname or a.name] = "%s.%s" % (n.module, a.name)
    return alias


def _fichier_du_module(module: str):
    """app/<x>.py ou tools/<x>.py pour le dernier segment du module ; None si absent des deux."""
    dernier = module.split(".")[-1]
    for d in ("app", "tools"):
        if (ROOT / d / (dernier + ".py")).exists():
            return "%s/%s.py" % (d, dernier)
    return None


def _ligne_def(fichier: str, fonction: str):
    try:
        for n in ast.walk(ast.parse((ROOT / fichier).read_text(encoding="utf-8", errors="replace"))):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fonction:
                return n.lineno
    except (OSError, SyntaxError):  # muet-ok : ligne introuvable -> None, la localisation est abandonnee
        pass
    return None


def _localiser_par_symbole(texte: str):
    """Fonction citee par pytest (« <function f at 0x..> = Alias.f »), resolue par les imports du test."""
    s = _RE_SYMBOLE.search(texte or "")
    t = _RE_FICHIER_TEST.search(texte or "")
    if not s or not t:
        return None
    fonction, chemin = s.group(1), s.group(2)
    module = _alias_du_test(t.group(1).replace("\\", "/")).get(chemin.split(".")[0])
    fichier = _fichier_du_module(module) if module else None
    ligne = _ligne_def(fichier, fonction) if fichier else None
    if not ligne:
        return None
    return {"file": fichier, "function": fonction, "line": ligne, "source": "symbole_assertion"}


def localiser(trace: str, message: str = ""):
    """Frame la plus profonde sous app/ ou tools/ ; a defaut, la fonction citee par l'assertion ; sinon None."""
    trouve = None
    derniere_def = None
    for ligne in trace.splitlines():
        d = _RE_DEF.match(ligne)
        if d:
            derniere_def = d.group(1)
        m = _RE_FRAME.match(ligne)
        if not m:
            continue
        chemin = _chemin_depot(m.group("file"))
        if chemin:
            mi = re.match(r"\s*in\s+(\w+)", m.group("rest"))
            fonction = mi.group(1) if mi else derniere_def
            trouve = {"file": chemin, "function": fonction, "line": int(m.group("line"))}
        derniere_def = None
    return trouve or _localiser_par_symbole((message or "") + "\n" + trace)


def extraire_rel(junit):
    """Liste de REL (dict) pour chaque failure/error ; None si rapport illisible."""
    if _lire_junit_commun(junit) is None:
        return None
    rels = []
    for cas in ET.parse(junit).getroot().iter("testcase"):
        for genre in ("failure", "error"):
            for noeud in cas.findall(genre):
                nodeid = "%s::%s" % (cas.get("classname", ""), cas.get("name", ""))
                trace = noeud.text or ""
                msg = noeud.get("message") or (trace.strip().splitlines() or [""])[0]
                coupe = max(0, len(msg) - MESSAGE_MAX)
                rels.append({
                    "error_id": nodeid,
                    "pointer_ref": localiser(trace, msg),
                    "evidence": {
                        "message": msg[:MESSAGE_MAX],
                        "message_coupe_de": coupe,
                        "trace": trace.splitlines()[-TRACE_LIGNES:],
                    },
                })
    return rels


def _nom(error_id: str) -> str:
    return "evolution_proposal_rel_%s.md" % hashlib.sha1(error_id.encode("utf-8")).hexdigest()[:10]


def _rendre(rel: dict) -> str:
    c = rel["evidence"]["message_coupe_de"]
    corps = ["# REL %s" % rel["error_id"], ""]
    corps.append("- **%s**" % rel["error_id"])
    if rel["pointer_ref"] is None:
        corps.append("pointer_ref null : aucune frame sous app/ ou tools/ dans la trace "
                     "(le correctif ne peut pas etre localise).")
    if c:
        corps.append("message coupe : %d caractere(s) retire(s) sur %d." % (c, c + MESSAGE_MAX))
    corps += ["", "```json", json.dumps(rel, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(corps)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--junit", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", default=str(SANDBOX))
    a = ap.parse_args(argv)
    rels = extraire_rel(a.junit)
    if rels is None:
        print("[rel] rapport JUnit illisible : rien ecrit", flush=True)
        return 2
    out = Path(a.out_dir)
    ecrits = 0
    for rel in rels:
        cible = out / _nom(rel["error_id"])
        if cible.exists() and time.time() - cible.stat().st_mtime < FENETRE_DEDUP_S:
            print("[rel] deja propose < 7 j : %s" % rel["error_id"], flush=True)
            continue
        texte = _rendre(rel)
        if a.dry_run:
            print("[rel] DRY-RUN ecrirait %s :\n%s" % (cible, texte), flush=True)
            continue
        out.mkdir(parents=True, exist_ok=True)
        cible.write_text(texte, encoding="utf-8")
        ecrits += 1
        print("[rel] ecrit %s" % cible, flush=True)
    print("[rel] %d echec(s), %d proposition(s) ecrite(s)" % (len(rels), ecrits), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
